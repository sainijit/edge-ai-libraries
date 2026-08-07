# Edge AI Libraries – AI Agent Instructions

**Edge AI Libraries** is a monorepo of optimized libraries, microservices, tools, and sample applications for building and deploying real-time AI solutions on edge devices. Components span computer vision, multimedia analytics, generative AI, time-series analytics, and model lifecycle management.

Components are **independently versioned and deployable**. Each component under `libraries/`, `microservices/`, `tools/`, `frameworks/`, and `sample-applications/` is self-contained with its own Dockerfile, Makefile, Helm chart, and tests.

## Licensing Requirements (Critical – All Files)

**All files must include:**

- SPDX license header: `SPDX-License-Identifier: Apache-2.0`
- Copyright line: `(C) <YEAR> Intel Corporation` (use current year for new files)
- Example:
  ```python
  # SPDX-FileCopyrightText: (C) 2026 Intel Corporation
  # SPDX-License-Identifier: Apache-2.0
  ```
- **Enforcement**: REUSE/license compliance checked in CI (see `codeql.yaml`, `zizmor-scan.yaml`)

## Always-On Skills (Load at Session Start)

Load this skill file automatically at the beginning of **every** Copilot session in this
repository, together with this instructions file, regardless of the task:

| Skill file | Why it's always-on |
|---|---|
| `.github/skills/core-engineering/SKILL.md` | Baseline Python, Docker, GitHub/CI, software-architecture, senior-engineering, and ML/LLM/VLM engineering standards that apply to every component in this monorepo. |

## Language-Specific Skills (Load On-Demand)

Consult these based on the code you're working with. Skills reside under `.github/skills/`.

| Skill file | When to load |
|---|---|
| `.github/skills/security-review/SKILL.md` | Dockerfile, Compose, Helm, auth/authz, input parsing, file handling, secrets/logging, dependency upgrades, CI/CD workflow changes, privilege elevation |

> **Instruction Placement Policy**: Keep this file focused on high-level routing and architecture context. Detailed procedural checklists belong in skill files under `.github/skills/`. Avoid duplicating checklist content between this file and skills.

## Security Defaults (Always-On)

Apply secure-by-default behavior across all code generation, changes, and reviews, regardless of language or component.

- Prefer least privilege across code, services, identities, file permissions, APIs, containers, and workflows; avoid insecure defaults.
- Treat all external input as untrusted and validate format, type, range, and length at trust boundaries.
- Never hard-code or introduce secrets, credentials, keys, tokens, or passwords in source, tests, configs, or templates; use environment variables or approved secret-management mechanisms.
- Avoid exposing sensitive data in logs, traces, errors, metrics, or test artifacts.
- Prevent injection vulnerabilities by avoiding unsafe string construction and using safe, context-appropriate APIs.
- Prefer trusted, actively maintained dependencies and images; verify sources and pin versions where feasible.
- Avoid deprecated, unmaintained, or ambiguous packages.
- Do not suggest bypassing or weakening existing security checks or validations.
- Keep authorization checks server-side and close to protected resources.
- Avoid unsafe dynamic execution patterns (`eval`, `exec`, untrusted command construction).
- Prevent time-of-check/time-of-use (TOCTOU) race conditions in state-dependent checks (e.g., certificate validation.
- Do not assume trusted inputs, networks, or environments.
- Be explicit about assumptions and limitations.
- Fail safely and visibly.

## AI Output Trust Model

Treat AI-generated output as **untrusted draft code** until reviewed and tested.
Reject suggestions that bypass security controls for convenience or introduce unsafe defaults.

For detailed security review guidance, follow:
`.github/skills/security-review/SKILL.md`.

## Repository Structure

```
edge-ai-libraries/
├── libraries/          # Reusable AI/ML libraries (anomalib, datumaro, geti-sdk, model_api, …)
├── microservices/      # Standalone deployable services (dlstreamer-pipeline-server, model-registry,
│                       #   time-series-analytics, vlm-openvino-serving, audio-analyzer, …)
├── sample-applications/# End-to-end reference apps (chat-qna, document-summarization, …)
├── tools/              # Developer tooling (npu-monitor-tool, visual-pipeline-evaluation, …)
├── frameworks/         # Edge device enablement framework
└── .github/
    ├── workflows/      # Per-component CI (dlsps-*, timeseries-*, GENAI-*, modelregistry-*, …)
    └── skills/         # On-demand AI agent skill files
```

## Component Layout Convention

Each component follows a consistent layout:

```
<component>/
├── Dockerfile              # Container build definition
├── Makefile                # Standard targets: build, lint, test, coverage
├── README.md               # Quick start
├── helm/ or chart/         # Helm chart for Kubernetes deployment
├── docker/                 # Docker Compose files and supporting config
├── src/                    # Application source code
├── tests/                  # Unit and integration tests
├── docs/                   # Component documentation
├── requirements.txt         # Python runtime dependencies (or pyproject.toml / uv.lock)
└── document-versions.yaml  # Tracks documentation versioning
```

> Some newer components use `pyproject.toml` + `uv.lock` instead of `requirements.txt`. Prefer `uv` for lock-file-based installs in those components.

## Code Patterns & Conventions

**Python packaging**:
- Most microservices use `src/` layout with `requirements.txt` (or `pyproject.toml`)
- Newer components (`model-download`) use `uv` with a `uv.lock` lockfile — prefer `uv sync` over `pip install` in those components

**REST APIs**:
- Services expose HTTP REST APIs; refer to each component's `docs/` or `README.md` for endpoint definitions
- OpenAPI specs, where available, are under `docs/` or `src/rest_api/`

**Helm / Kubernetes**:
- Helm charts are under `<component>/helm/` or `<component>/chart/`
- Values files follow `values.yaml` (defaults) with override patterns documented in component `docs/`

**Configuration injection**:
- Runtime configuration via environment variables and mounted config files
- Secrets must use Docker Compose secrets, Kubernetes Secrets, or environment variable injection — never baked into images

**Observability**:
- OpenTelemetry instrumentation is present in some components (e.g., `dlstreamer-pipeline-server/src/opentelemetry/`)
- Enable via environment variables; refer to component documentation

**Documentation versioning**:
- `document-versions.yaml` in each component tracks doc artifact versions
- Update when publishing new component versions

## Common Developer Workflows

**Modifying a microservice** (example: `model-registry`):

1. Edit source in `<component>/src/`
2. Rebuild image: `make build`
3. Run tests: `make test`
4. Start service: `docker compose -f docker/docker-compose.yml up`
5. Review logs: `docker compose -f docker/docker-compose.yml logs -f`

**Adding a Python dependency**:
- `requirements.txt`-based: add to `requirements.txt`, rebuild image
- `pyproject.toml`/`uv`-based: `uv add <package>`, commit updated `uv.lock`
- Dependency upgrades are a security-review trigger — load `.github/skills/security-review/SKILL.md` to check for CVE-related concerns and lockfile hygiene

**Running linters**:

```bash
make lint
# or directly
pylint src/
yamllint .
```

## Integration Points & Dependencies

**External runtime services** (component-specific, declared in `docker/docker-compose.yml`):
- Vector databases: Milvus (semantic-search, vector-retriever, visual-data-preparation)
- LLM backends: OpenAI-compatible API or local OpenVINO model server
- Message brokers: Kafka or MQTT (where applicable in pipeline-server)
- Object storage: MinIO or equivalent (model-download, document-ingestion)

**OpenVINO**:
- Used across inference-serving microservices for optimized edge inference
- Model format: IR (`.xml` + `.bin`) or ONNX; see individual component docs

**DLStreamer**:
- GStreamer-based video analytics pipeline server
- Pipeline definitions via JSON or REST API; see `dlstreamer-pipeline-server/docs/`

## Documentation Requirements (Always-On)

### When to update documentation

Update documentation immediately when making any of these changes:

- Adding new features, APIs, endpoints, or configuration options
- Modifying request/response formats or default behaviors
- Changing build targets, Makefile commands, or deployment procedures
- Updating dependencies or system requirements
- Adding or removing environment variables
- Publishing a new component version (update `document-versions.yaml`)

### Key documentation locations (per component)

- `<component>/README.md` — Quick start and overview
- `<component>/docs/user-guide/` — Full user guide, API reference, build-from-source guide
- `docs.openedgeplatform.intel.com` — Published cross-component documentation

## Component Deep Dives

### Audio Analyzer (`microservices/audio-analyzer/`)

FastAPI microservice (default port **8010**) for audio transcription with optional
voice-sentiment analysis. Accepts an uploaded audio/video file, chunks it with FFmpeg, runs
ASR on each chunk, and returns a single JSON response or an NDJSON event stream; when
`sentiment.enabled` is true it also returns a session-level sentiment summary.

**Architecture (request flow):**

```
Client -> API layer (api/) -> Pipeline orchestrator (pipeline.py)
        -> Preprocessing (FFmpeg: decode, chunk, optional denoise via components/ffmpeg/)
        -> ASR backend (components/asr/: openai | openvino | whispercpp) on CPU/GPU
        -> Sentiment backend (components/sentiment/: openvino | pytorch), optional, in parallel
        -> Session store (storage/<session_id>/)
        -> JSON response or NDJSON events, with X-Session-ID response header
```

- **API layer** (`api/openai_endpoints.py`, `api/custom_endpoints.py`, `api/error_responses.py`) —
  request validation, session header handling, OpenAI-style error shaping.
- **Pipeline orchestrator** (`pipeline.py`) — drives preprocessing → ASR → sentiment and
  aggregates per-chunk results into the session-level summary.
- **Backends** (`components/asr_component.py`, `components/asr/base_asr.py`,
  `components/sentiment_component.py`, `components/sentiment/`) — pluggable ASR/sentiment
  providers selected via `config.yaml`; each handles its own model loading/device placement.
  Diarization (speaker identity) is implemented under `components/asr/` and gated by
  `models.asr.diarization`.
- **Session store** — `storage/<session_id>/` holds chunk files and metadata; reusing
  `session_id` across uploads continues the same session.
- **DTOs** (`dto/audiosource.py`, `dto/transcription_dto.py`, `dto/vss_dto.py`) — request/response
  models.
- **Utils** (`utils/`) — config loading (`config_loader.py`), audio helpers (`audio_util.py`),
  model management (`ensure_model.py`, `preload_models.py`), OpenVINO/NPU runtime validation
  (`openvino_runtime_validation.py`), MinIO client (`minio_handler.py`), session lifecycle
  (`session_manager.py`, `session_state_manager.py`), locking, and logging.

**Configuration:** all runtime behavior comes from `config.yaml` (models, audio_preprocessing,
audio_util, minio, pipeline, sentiment sections), overridable with
`AUDIO_ANALYZER__<SECTION>__<KEY>` environment variables. Notable knobs: `models.asr.provider`
(`openai`/`openvino`/`whispercpp`), `models.asr.device`, `models.asr.diarization`,
`sentiment.enabled`/`sentiment.provider`, and `minio.*` (only used by the VSS-compatibility
endpoint).

**REST API surface** (base URL `http://127.0.0.1:8010`, JSON responses unless noted):

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness probe → `{"status": "ok"}` |
| `/devices` | GET | Lists detected ALSA capture devices (`hw:<card>,<device>`) |
| `/v1/audio/transcriptions` | POST | OpenAI-compatible transcription; single JSON response. Form fields: `file` (required), `model` (`whisper-1`), `session_id`, `language`, `prompt` (ignored), `response_format` (`json`/`text`/`verbose_json`/`srt`/`vtt`), `temperature`. Returns `X-Session-ID` header. |
| `/v1/audio/transcriptions/stream` | POST | Same as above but streams NDJSON events: `transcription.chunk` (per chunk) and `transcription.completed` (final). |
| `/models` | GET | VSS-compatibility: lists the single configured ASR model (`models.asr.name`). |
| `/transcriptions` | POST | VSS-compatibility (not OpenAI-compatible): accepts a direct `file` upload **or** a MinIO source (`minio_bucket` + `video_id` + `video_name`), plus optional `device`, `model_name`, `include_timestamps` (informational), and `language` query param. When using MinIO, downloads the video, transcribes it, and uploads the transcript back to the same bucket at `{video_id}/{video_name-stem}.txt`; returns `503` if `minio.endpoint` is unset. |

Sessions are addressed by `session_id` (directory `storage/<session_id>/`); reusing the id
across uploads appends transcript state and updates the sentiment summary when enabled.

**Docs:** `microservices/audio-analyzer/README.md` (index),
`docs/user-guide/how-it-works.md` (architecture/request flow),
`docs/user-guide/api-reference.md` (full endpoint reference),
`docs/user-guide/get-started.md` and `get-started/configuration.md` (setup/config),
`docs/user-guide/troubleshooting.md`, `docs/user-guide/release-notes.md`.

**Build/test:** no `Makefile` — this component builds via `Dockerfile`/`docker/Dockerfile` and
`docker-compose.yml`/`docker/docker-compose.yml`; Python deps via `requirements.txt`; dev/lint
tooling (`black`, `isort`, `pylint`, `flake8`) configured in `pyproject.toml`; tests under
`tests/` (unit) and `tests/functional/` (pytest, see `pytest.ini`/`conftest.py`). CI workflow:
`.github/workflows/GENAI-Audio-analyzer.yaml`.

## Quick Reference: New Microservice Checklist

When adding a new microservice under `microservices/`:

1. Create folder with `Dockerfile`, `Makefile`, `src/`, `requirements.txt` (or `pyproject.toml`)
2. Add standard Makefile targets: `build`, `lint`, `test`, `coverage`, `help`
3. Add `docker/docker-compose.yml` for local development
4. Add Helm chart under `helm/` with `Chart.yaml`, `values.yaml`, and templates
5. Create tests in `tests/` with appropriate test runner configuration
6. Add a CI workflow under `.github/workflows/` for PR validation and scanning
7. Create `README.md` and `docs/` with user guide and API reference
8. Add `document-versions.yaml` for documentation versioning
9. Ensure SPDX license headers are present in all source files
10. Register component in root `README.md` component table
11. Run security review (`.github/skills/security-review/SKILL.md`) on Dockerfile, Helm chart, and CI/CD workflow before merging
