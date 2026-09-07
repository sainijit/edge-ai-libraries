# `benchmark_kpis.py` — KPI Benchmarking Harness

A standalone load-testing / KPI harness for the Audio Analyzer service. It fires
audio-transcription requests at a running instance, times everything
client-side, and writes a JSON summary plus per-request CSVs.

## Inputs (CLI arguments)

| Arg | Purpose |
|---|---|
| `--host` | Base URL of the running service (default `http://127.0.0.1:8010`) |
| `--mode` | Which endpoint to benchmark: `batch` or `sse` |
| `--manifest` | JSONL/JSON corpus file listing audio files to send |
| `--concurrency` | One or more concurrency levels to sweep (e.g. `1 4 8`) |
| `--iterations` | Measured requests per concurrency level (default 50) |
| `--warmup` | Warmup requests, discarded (default 5) |
| `--response-format` | `batch` only: `json` / `verbose_json` / `text` / `srt` / `vtt` |
| `--no-perf` | Skip polling `GET /v1/performance` after each request |
| `--out` | Output path prefix for JSON/CSV |
| `--ready-timeout` | Seconds to wait for `/health` before starting |

### Audio input handling

Any audio format (mp3, m4a, wav, etc.) can be listed in the manifest — no
manual pre-conversion is required. Both modes (`batch`, `sse`) send the original
file untouched; the service decodes it. The script computes `audio_duration_sec`
itself via `ffprobe` (`probe_duration_sec`), falling back to the WAV header.

> `ffprobe` is optional (the WAV header is used as a fallback for duration).

### Manifest format

One JSON object per line (JSON Lines):

```json
{"file": "short/0.wav", "language": "en"}
```

- Relative `file` paths resolve against the manifest's own directory.
- `duration_sec` is optional (measured via `ffprobe`/WAV header when absent).
- `load_manifest` validates that every referenced file exists and aborts otherwise.

## Endpoint modes (systems under test)

Each mode has a `call_*` function returning a `RequestResult`:

- **`batch`** → `POST /v1/audio/transcriptions` — single request/response, times total wall clock.
- **`sse`** → same endpoint with `stream=true` — parses OpenAI SSE `data:` lines, capturing `transcript.text.delta` / `.done` events.

Metadata endpoints (`/health`, `/v1/model-info`, `/v1/performance`) are **not**
benchmarked — they only label or augment results.

## Metrics collected

Raw per-request fields (`RequestResult` dataclass):

- `e2e_sec` — client wall time (`time.perf_counter()` delta around the request)
- `ttft_sec` — time to first streamed event
- `inter_chunk_sec[]` — gaps between successive stream chunks
- `server_asr_last_ms` — server-side ASR latency read from `GET /v1/performance`
- `audio_duration_sec` — via `ffprobe`/WAV header (`probe_duration_sec`); response `duration` is a fallback
- `ok`, `status_code`, `error`, `text`, `response_duration_sec`

## How metrics are calculated

### Runner

`run_phase` uses a `ThreadPoolExecutor` sized to the concurrency level,
submitting all `iterations` requests and collecting results as they complete
(closed-loop), while timing total wall clock.

### Aggregation

`compute_kpis` splits results into ok/errors, then computes:

- **RTF / xRT** per request:

$$\text{RTF} = \frac{\text{e2e\_sec}}{\text{audio\_duration}}, \qquad \text{xRT} = \frac{\text{audio\_duration}}{\text{e2e\_sec}}$$

- **Throughput**:

$$\text{rps} = \frac{\text{requests\_ok}}{\text{wall\_sec}}, \qquad \text{audio\_sec/s} = \frac{\sum \text{audio\_duration}}{\text{wall\_sec}}$$

- **Error rate** = `requests_failed / requests_total`
- Latency distributions (e2e, ttft, inter-chunk, server ASR) go through `summarize`.

### `summarize`

Returns `count, mean, stddev, p50, p90, p95, p99, max, min`:

- `mean` = `statistics.fmean`, `stddev` = `statistics.pstdev` (population)
- percentiles via `percentile()`, which does **linear interpolation** on sorted values:

$$\text{rank} = \frac{p}{100}(n-1), \quad \text{value} = d_{\lfloor r \rfloor} + (d_{\lceil r \rceil} - d_{\lfloor r \rfloor})(r - \lfloor r \rfloor)$$

## Outputs

- `{out}_summary.json` — meta block (timestamp, host, mode, model info) plus a `phases[]` array, one KPI object per concurrency level.
- `{out}_c<N>_raw.csv` — raw per-request rows for each concurrency level `N`.

Console output prints a per-phase summary (ok count, error rate, rps, e2e
p50/p95/p99, RTF, TTFT).

## Key caveat

All latency is measured **client-side**, so it includes network and
serialization overhead. The only server-truth metric is `server_asr_last_ms`
from `/v1/performance`.

## How to run the benchmark

### 1. Install harness dependencies

```bash
pip install -r benchmarks/requirements-bench.txt
```

### 2. Make sure the service is running

Start the Audio Analyzer service and note its base URL (default
`http://127.0.0.1:8010`). The harness waits for `GET /health` before starting.

### 3. Prepare a manifest

Create a JSON Lines file pointing at your audio corpus (paths are relative to
the manifest's own directory). Any format works — the script probes duration
with `ffprobe`:

```bash
mkdir -p benchmarks/sample_files/short
cp input.mp3 benchmarks/sample_files/short/0.mp3
echo '{"file": "short/0.mp3", "language": "en"}' > benchmarks/sample_files/manifest.jsonl
```

### 4. Run a benchmark

```bash
# Batch mode, concurrency sweep
python benchmarks/benchmark_kpis.py \
    --host http://127.0.0.1:8010 \
    --mode batch \
    --manifest benchmarks/sample_files/manifest.jsonl \
    --concurrency 1 4 8 --warmup 5 --iterations 50 \
    --out benchmarks/results/batch

# Streaming SSE (captures TTFT)
python benchmarks/benchmark_kpis.py --mode sse \
    --manifest benchmarks/sample_files/manifest.jsonl \
    --concurrency 1 4 --out benchmarks/results/sse
```

### 5. Read the results

- `benchmarks/results/<prefix>_summary.json` — aggregated KPIs per concurrency level.
- `benchmarks/results/<prefix>_c<N>_raw.csv` — raw per-request rows.

Per-phase summaries (ok count, error rate, rps, e2e p50/p95/p99, RTF, TTFT)
are also printed to the console during the run.
`audio_duration_sec` and `response_duration_sec`: Both columns measure the same thing — the audio's length — but from different sources: audio_duration_sec is probed client-side (ffprobe/manifest), while response_duration_sec is the duration the server reports. Equal values are expected; a mismatch flags a problem (e.g. truncated audio or a wrong probe duration).
