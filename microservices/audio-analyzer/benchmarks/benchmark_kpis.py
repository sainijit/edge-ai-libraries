#!/usr/bin/env python3
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Audio Analyzer — KPI benchmarking harness.

Drives the benchmarkable endpoints and computes the KPIs defined in
docs/benchmarking-strategy.md:

  * End-to-end latency  (p50/p90/p95/p99/max, mean, stddev)
  * TTFT (time to first token/chunk) for streaming endpoints
  * Inter-chunk latency for streaming endpoints
  * RTF / xRT (real-time factor) from the response `duration`
  * Throughput (requests/s and audio-seconds/s) under concurrency
  * Server-side ASR latency, read from `GET /v1/performance`
  * Error rate

Every result row is stamped with the model/provider/device from
`GET /v1/model-info` so CPU vs GPU runs are never confused.

Endpoints supported (mode):
  batch    POST /v1/audio/transcriptions                    (json | verbose_json)
  sse      POST /v1/audio/transcriptions  (stream=true)      OpenAI SSE

Only compute-bearing endpoints are benchmarked. /health, /devices,
/v1/model-info, /v1/performance and /models are metadata/observability probes
and are used to *label* or *augment* results, not as systems under test.

Usage examples
--------------
  # Batch, single audio, concurrency sweep
  python benchmark_kpis.py --host http://127.0.0.1:8010 \
      --mode batch --manifest benchmarks/sample_files/manifest.jsonl \
      --concurrency 1 4 8 --warmup 5 --iterations 50 \
      --out benchmarks/results/batch

  # Streaming SSE (captures TTFT)
  python benchmark_kpis.py --mode sse --manifest benchmarks/sample_files/manifest.jsonl \
      --concurrency 1 4 --out benchmarks/results/sse

Manifest format (JSON Lines, one object per line):
  {"file": "short/0.wav", "language": "en"}
  Relative `file` paths are resolved against the manifest's own directory.
  `duration_sec` is optional; it is measured from the WAV header when absent
  and otherwise taken from the service response `duration`.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("This harness requires `requests`.  pip install requests")


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class RequestResult:
    """One request's raw measurements."""

    ok: bool
    file: str
    audio_duration_sec: float | None = None      # from WAV header or response
    e2e_sec: float | None = None                 # client wall time
    ttft_sec: float | None = None                # streaming: first event
    inter_chunk_sec: list[float] = field(default_factory=list)
    server_asr_last_ms: float | None = None      # GET /v1/performance
    text: str | None = None
    response_duration_sec: float | None = None   # response body `duration`
    status_code: int | None = None
    error: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolation percentile (pct in 0..100)."""
    data = sorted(v for v in values if v is not None)
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    rank = (pct / 100.0) * (len(data) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return data[lo]
    return data[lo] + (data[hi] - data[lo]) * (rank - lo)


def summarize(values: list[float]) -> dict[str, float | None]:
    vals = [v for v in values if v is not None]
    if not vals:
        return {k: None for k in ("count", "mean", "stddev", "p50", "p90", "p95", "p99", "max", "min")}
    return {
        "count": len(vals),
        "mean": statistics.fmean(vals),
        "stddev": statistics.pstdev(vals) if len(vals) > 1 else 0.0,
        "p50": percentile(vals, 50),
        "p90": percentile(vals, 90),
        "p95": percentile(vals, 95),
        "p99": percentile(vals, 99),
        "max": max(vals),
        "min": min(vals),
    }


def wav_duration_sec(path: str) -> float | None:
    try:
        with wave.open(path, "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            return frames / float(rate) if rate else None
    except Exception:
        return None


def probe_duration_sec(path: str) -> float | None:
    """Audio duration in seconds for any format via ffprobe.

    Used by the file-upload modes (batch/sse), which send the original file
    untouched but still need the duration for RTF/xRT. Falls back to the WAV
    header when ffprobe is unavailable.
    """
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            out = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=30,
            )
            val = out.stdout.strip()
            if val and val.lower() != "n/a":
                return float(val)
        except Exception:
            pass
    return wav_duration_sec(path)


# ─────────────────────────────────────────────────────────────────────────────
# Service metadata probes (NOT the SUT — used to label/augment results)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_model_info(host: str, timeout: float = 10.0) -> dict:
    try:
        r = requests.get(f"{host}/v1/model-info", timeout=timeout)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return {}


def fetch_server_asr_last_ms(host: str, timeout: float = 5.0) -> float | None:
    """Read the last server-side ASR latency from GET /v1/performance."""
    try:
        r = requests.get(f"{host}/v1/performance", timeout=timeout)
        if r.ok:
            return (r.json().get("latency") or {}).get("last_ms")
    except Exception:
        pass
    return None


def wait_until_ready(host: str, timeout: float = 300.0) -> bool:
    """Block until GET /health returns 200 (covers GPU warmup)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(f"{host}/health", timeout=5).ok:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint callers — each returns a RequestResult
# ─────────────────────────────────────────────────────────────────────────────
def call_batch(host: str, item: dict, response_format: str, read_perf: bool) -> RequestResult:
    path = item["file"]
    res = RequestResult(ok=False, file=path, audio_duration_sec=item.get("duration_sec") or probe_duration_sec(path))
    data = {"response_format": response_format}
    if item.get("language"):
        data["language"] = item["language"]
    t0 = time.perf_counter()
    try:
        with open(path, "rb") as fh:
            r = requests.post(f"{host}/v1/audio/transcriptions",
                              files={"file": (os.path.basename(path), fh)}, data=data, timeout=600)
        res.e2e_sec = time.perf_counter() - t0
        res.status_code = r.status_code
        if not r.ok:
            res.error = f"HTTP {r.status_code}: {r.text[:200]}"
            return res
        if response_format in ("json", "verbose_json"):
            body = r.json()
            res.text = body.get("text")
            res.response_duration_sec = body.get("duration")
        else:
            res.text = r.text
        res.ok = True
    except Exception as exc:
        res.e2e_sec = time.perf_counter() - t0
        res.error = repr(exc)
    if read_perf:
        res.server_asr_last_ms = fetch_server_asr_last_ms(host)
    return res


def call_sse(host: str, item: dict, read_perf: bool) -> RequestResult:
    """POST /v1/audio/transcriptions with stream=true — OpenAI SSE."""
    path = item["file"]
    res = RequestResult(ok=False, file=path, audio_duration_sec=item.get("duration_sec") or probe_duration_sec(path))
    data = {"stream": "true", "response_format": "json"}
    if item.get("language"):
        data["language"] = item["language"]
    t0 = time.perf_counter()
    last_event = t0
    text_final = None
    try:
        with open(path, "rb") as fh:
            r = requests.post(f"{host}/v1/audio/transcriptions",
                              files={"file": (os.path.basename(path), fh)}, data=data,
                              stream=True, timeout=600)
            res.status_code = r.status_code
            if not r.ok:
                res.error = f"HTTP {r.status_code}: {r.text[:200]}"
                return res
            for raw in r.iter_lines(decode_unicode=True):
                if not raw or not raw.startswith("data:"):
                    continue
                payload = raw[len("data:"):].strip()
                now = time.perf_counter()
                if payload == "[DONE]":
                    break
                evt = json.loads(payload)
                etype = evt.get("type")
                if etype == "transcript.text.delta":
                    if res.ttft_sec is None:
                        res.ttft_sec = now - t0
                    res.inter_chunk_sec.append(now - last_event)
                    last_event = now
                elif etype == "transcript.text.done":
                    text_final = evt.get("text")
                    res.response_duration_sec = evt.get("duration")
        res.e2e_sec = time.perf_counter() - t0
        res.text = text_final
        res.ok = True
    except Exception as exc:
        res.e2e_sec = time.perf_counter() - t0
        res.error = repr(exc)
    if read_perf:
        res.server_asr_last_ms = fetch_server_asr_last_ms(host)
    return res


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────
def build_caller(args) -> Callable[[dict], RequestResult]:
    host = args.host.rstrip("/")
    read_perf = not args.no_perf
    if args.mode == "batch":
        return lambda item: call_batch(host, item, args.response_format, read_perf)
    if args.mode == "sse":
        return lambda item: call_sse(host, item, read_perf)
    raise ValueError(f"unknown mode {args.mode}")


def run_phase(caller, workload: list[dict], concurrency: int) -> tuple[list[RequestResult], float]:
    """Closed-loop: keep `concurrency` requests in flight until workload done."""
    results: list[RequestResult] = []
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(caller, item) for item in workload]
        for fut in as_completed(futures):
            results.append(fut.result())
    wall = time.perf_counter() - t0
    return results, wall


def compute_kpis(results: list[RequestResult], wall_sec: float) -> dict:
    ok = [r for r in results if r.ok]
    errors = [r for r in results if not r.ok]

    e2e = [r.e2e_sec for r in ok if r.e2e_sec is not None]
    ttft = [r.ttft_sec for r in ok if r.ttft_sec is not None]
    inter = [x for r in ok for x in r.inter_chunk_sec]
    server_ms = [r.server_asr_last_ms for r in ok if r.server_asr_last_ms is not None]

    # RTF per request = processing_time / audio_duration
    rtfs, xrts, audio_secs = [], [], []
    for r in ok:
        dur = r.audio_duration_sec or r.response_duration_sec
        if dur and r.e2e_sec:
            rtfs.append(r.e2e_sec / dur)
            xrts.append(dur / r.e2e_sec)
            audio_secs.append(dur)

    total_audio = sum(audio_secs)
    kpi = {
        "requests_total": len(results),
        "requests_ok": len(ok),
        "requests_failed": len(errors),
        "error_rate": (len(errors) / len(results)) if results else None,
        "wall_sec": round(wall_sec, 4),
        "throughput_rps": round(len(ok) / wall_sec, 4) if wall_sec else None,
        "throughput_audio_sec_per_sec": round(total_audio / wall_sec, 4) if wall_sec else None,
        "e2e_latency_sec": summarize(e2e),
        "rtf": summarize(rtfs),
        "xrt": summarize(xrts),
        "server_asr_latency_ms": summarize(server_ms),
        
    }
    if ttft:
        kpi["ttft_sec"] = summarize(ttft)
    if inter:
        kpi["inter_chunk_sec"] = summarize(inter)

    if errors:
        kpi["error_samples"] = [e.error for e in errors[:5]]
    return kpi


# ─────────────────────────────────────────────────────────────────────────────
# I/O
# ─────────────────────────────────────────────────────────────────────────────
def load_manifest(path: str) -> list[dict]:
    if not os.path.isfile(path):
        raise SystemExit(
            f"Manifest not found: {path}\n"
            "Create one (JSON Lines, one {\"file\": ...} per line) or generate "
            "sample files first, e.g.:\n"
            "  mkdir -p benchmarks/sample_files/short && ffmpeg -i input.mp3 -ac 1 -ar 16000 "
            "-sample_fmt s16 benchmarks/sample_files/short/0.wav\n"
            "  echo '{\"file\": \"short/0.wav\", \"language\": \"en\"}' > "
            f"{path}"
        )
    items: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        if path.endswith(".jsonl"):
            for line in fh:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
        else:
            data = json.load(fh)
            items = data if isinstance(data, list) else data.get("items", [])
    if not items:
        raise SystemExit(f"Manifest is empty: {path}")
    manifest_dir = os.path.dirname(os.path.abspath(path))
    missing: list[str] = []
    for it in items:
        if "file" not in it:
            raise SystemExit(f"Manifest entry missing 'file': {it}")
        # Resolve relative audio paths against the manifest's own directory so
        # the harness works regardless of the current working directory.
        if not os.path.isabs(it["file"]) and not os.path.isfile(it["file"]):
            candidate = os.path.join(manifest_dir, it["file"])
            if os.path.isfile(candidate):
                it["file"] = candidate
        if not os.path.isfile(it["file"]):
            missing.append(it["file"])
    if missing:
        raise SystemExit(
            "The following audio files referenced by the manifest do not exist:\n  "
            + "\n  ".join(missing)
        )
    return items


def build_workload(items: list[dict], total: int) -> list[dict]:
    """Repeat/truncate the corpus to exactly `total` requests."""
    if not items:
        return []
    out = []
    while len(out) < total:
        out.extend(items)
    return out[:total]


def write_raw_csv(path: Path, results: list[RequestResult]) -> None:
    import csv
    fields = ["ok", "file", "status_code", "audio_duration_sec", "e2e_sec", "ttft_sec",
              "server_asr_last_ms", "response_duration_sec", "error"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in results:
            row = asdict(r)
            writer.writerow({k: row.get(k) for k in fields})


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="Audio Analyzer KPI benchmarking harness")
    ap.add_argument("--host", default="http://127.0.0.1:8010", help="Service base URL")
    ap.add_argument("--mode", required=True, choices=["batch", "sse"])
    ap.add_argument("--manifest", required=True, help="JSONL/JSON corpus manifest")
    ap.add_argument("--concurrency", type=int, nargs="+", default=[1],
                    help="One or more concurrency levels to sweep")
    ap.add_argument("--iterations", type=int, default=50,
                    help="Measured requests per concurrency level")
    ap.add_argument("--warmup", type=int, default=5, help="Warmup requests (discarded)")
    ap.add_argument("--response-format", default="json",
                    choices=["json", "verbose_json", "text", "srt", "vtt"],
                    help="batch mode only")
    ap.add_argument("--no-perf", action="store_true",
                    help="Do NOT poll GET /v1/performance after each request")
    ap.add_argument("--out", default="benchmarks/results/run", help="Output prefix for JSON/CSV")
    ap.add_argument("--ready-timeout", type=float, default=300.0,
                    help="Seconds to wait for /health before starting (0 to skip)")
    args = ap.parse_args()

    host = args.host.rstrip("/")
    items = load_manifest(args.manifest)
    caller = build_caller(args)
    if args.ready_timeout > 0:
        print(f"Waiting for {host}/health ...", flush=True)
        if not wait_until_ready(host, args.ready_timeout):
            print("Service not ready — aborting.", file=sys.stderr)
            return 2

    model_info = fetch_model_info(host)
    print(f"Model info: {model_info}", flush=True)

    # Warmup (discarded)
    if args.warmup > 0:
        print(f"Warmup: {args.warmup} requests ...", flush=True)
        run_phase(caller, build_workload(items, args.warmup), concurrency=1)

    out_prefix = Path(args.out)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "meta": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "host": host,
            "mode": args.mode,
            "response_format": args.response_format if args.mode == "batch" else None,
            "manifest": args.manifest,
            "iterations": args.iterations,
            "warmup": args.warmup,
            "model_info": model_info,
        },
        "phases": [],
    }

    for conc in args.concurrency:
        print(f"\n=== Concurrency {conc} | {args.iterations} requests ===", flush=True)
        workload = build_workload(items, args.iterations)
        results, wall = run_phase(caller, workload, concurrency=conc)

        kpis = compute_kpis(results, wall)
        phase = {"concurrency": conc, "kpis": kpis}
        report["phases"].append(phase)

        write_raw_csv(Path(f"{args.out}_c{conc}_raw.csv"), results)

        e2e = kpis["e2e_latency_sec"]
        rtf = kpis["rtf"]
        print(f"  ok={kpis['requests_ok']}/{kpis['requests_total']} "
              f"err_rate={kpis['error_rate']:.3f} "
              f"rps={kpis['throughput_rps']} audio_s/s={kpis['throughput_audio_sec_per_sec']}")
        if e2e["p50"] is not None:
            print(f"  E2E  p50={e2e['p50']:.3f}s p95={e2e['p95']:.3f}s p99={e2e['p99']:.3f}s")
        if rtf["p50"] is not None:
            print(f"  RTF  p50={rtf['p50']:.3f} (xRT p50={kpis['xrt']['p50']:.2f})")
        if kpis.get("ttft_sec"):
            print(f"  TTFT p50={kpis['ttft_sec']['p50']:.3f}s")

    report_path = Path(f"{args.out}_summary.json")
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nSummary written to {report_path}")
    print(f"Raw per-request CSVs written to {args.out}_c<N>_raw.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
