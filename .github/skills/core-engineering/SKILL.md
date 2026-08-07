---
name: core-engineering
description: >
  Always-on multi-discipline engineering skill combining Python development, Docker/containerization,
  GitHub workflows, software architecture, senior software engineering judgment, and machine learning /
  LLM / VLM engineering practices. Load this skill at the start of every Copilot session in this
  repository, alongside `.github/copilot-instructions.md`, regardless of the specific task, because it
  defines the baseline engineering standards and mindsets (code quality, containerization, CI/CD,
  architectural decision-making, and AI/ML model integration) that apply across all Edge AI Libraries
  components (libraries/, microservices/, tools/, frameworks/, sample-applications/).
license: Apache-2.0
metadata:
  tags: "python docker github software-architect senior-software-engineer machine-learning-engineer llm vlm always-on"
---

# Core Engineering Skill

Combined baseline skill set for working anywhere in the Edge AI Libraries monorepo. This
skill is **always-on**: load it together with `.github/copilot-instructions.md` at the start
of every session, before diving into task-specific or on-demand skills (e.g.
`.github/skills/security-review/SKILL.md`).

---

## 1. Python Engineering

- Target Python 3.11+ unless a component pins an older version; check `pyproject.toml` /
  `requirements.txt` for the actual supported range before assuming.
- Prefer `src/`-layout packages; keep application entrypoints (`main.py`) thin — business
  logic belongs in modules under `src/`, `api/`, `components/`, `utils/`, etc.
- Use type hints on public functions/methods and Pydantic (or dataclasses) for request/response
  DTOs in FastAPI-based services.
- Formatting/linting: respect each component's configured tools (commonly `black`, `isort`,
  `flake8`, `pylint`) and their settings in `pyproject.toml`/`setup.cfg` — don't introduce new
  tools or reformat unrelated code.
- Dependency management: `requirements.txt` components → edit the file and rebuild the image;
  `uv`/`pyproject.toml` components → use `uv add` / `uv sync` and commit the updated lockfile.
- Prefer standard library and already-vendored dependencies over adding new ones; justify any
  new dependency and pin its version.
- Write or update unit/functional tests alongside code changes (`tests/` per component,
  `pytest` is the common runner — check `pytest.ini`/`conftest.py` for fixtures/markers).
- Never introduce blocking calls in async FastAPI request handlers; offload CPU-bound or
  blocking I/O (ffmpeg, model inference) to worker threads/processes as the existing code does.

## 2. Docker & Containerization

- Every microservice ships its own `Dockerfile` (often paired with a `docker/Dockerfile`
  variant for special builds) and a `docker/docker-compose.yml` for local development —
  follow the existing pattern rather than inventing a new one.
- Use multi-stage builds; keep final images minimal and free of build tools/caches.
- Pin base image tags/digests; avoid `latest`.
- Never run containers as root in the final stage unless there is a documented, justified
  reason (e.g., hardware device access); prefer least privilege.
- Configuration flows in via environment variables and mounted config files (e.g.
  `config.yaml` + `AUDIO_ANALYZER__...`-style env overrides) — never bake secrets or
  environment-specific values into the image.
- Validate changes with `docker compose -f docker/docker-compose.yml build` and `up`, then
  check `logs -f` before considering a containerization change complete.
- Any Dockerfile/Compose/Helm change is also a security-review trigger — load
  `.github/skills/security-review/SKILL.md` for hardening checks.

## 3. GitHub / CI / Workflow Practices

- CI lives under `.github/workflows/`; each component has a dedicated workflow (naming
  patterns like `GENAI-<component>.yaml`, `<component>-pr-workflow.yaml`,
  `<component>-build-scans-pr-workflow.yaml`). Reuse existing composite actions under
  `.github/actions/common/` (code-style, hadolint, pylint, shellcheck, trivy-image-scan,
  yamllint, license-namespace-checker) instead of duplicating logic.
- Every new microservice needs its own CI workflow for PR validation and scanning (see the
  "Quick Reference: New Microservice Checklist" in `.github/copilot-instructions.md`).
- REUSE/SPDX license compliance is enforced in CI — always include the SPDX header and
  Intel copyright line on new files.
- Commit messages/PRs: keep changes scoped to the component being modified; avoid touching
  unrelated components' CI or Dockerfiles.
- Use `gh` CLI for issues/PRs/workflow-run inspection when operating from the terminal.

## 4. Software Architect Mindset

- Respect component boundaries: `libraries/`, `microservices/`, `tools/`, `frameworks/`,
  `sample-applications/` are independently versioned and deployable — avoid introducing
  cross-component coupling that breaks independent deployability.
- Favor the layered structure already present in services (API layer → orchestrator/pipeline
  → pluggable backend components → session/storage layer), as seen in `audio-analyzer`
  (`api/` → `pipeline.py` → `components/` → `storage/`).
- Design for pluggability: backends (ASR providers, sentiment providers, inference devices)
  should be swappable via configuration, not hardcoded branches scattered through the code.
- Prefer configuration-driven behavior (`config.yaml` + env var overrides) over code changes
  for tunable parameters.
- Think about failure modes and observability up front: structured error responses, health
  endpoints, and (where present) OpenTelemetry instrumentation.

## 5. Senior Software Engineer Judgment

- Make surgical, minimal-blast-radius changes; don't refactor unrelated code while fixing a
  bug or adding a feature.
- Read existing tests and docs before changing behavior — align with documented contracts
  (e.g., API reference pages) and update them when behavior changes.
- Validate assumptions against the actual code (config defaults, DTO shapes, endpoint
  contracts) rather than guessing.
- Consider backward compatibility for public APIs/config keys; document breaking changes
  clearly in `release-notes.md` and `document-versions.yaml`.
- Always run the smallest targeted test/lint command that exercises the change before
  declaring it done.

## 6. Machine Learning / LLM / VLM Engineering

- Model lifecycle: model loading, caching, and device placement are typically isolated in
  dedicated backend/component modules (e.g. `components/asr/`, `components/sentiment/`) —
  keep provider-specific logic there, not scattered in API handlers.
- Inference devices: CPU is the safe default; GPU/NPU support is provider-specific (e.g.
  OpenVINO) — never assume GPU/NPU availability without a config-driven fallback.
- OpenVINO is the standard optimized-inference path across the monorepo; model formats are
  IR (`.xml`+`.bin`) or ONNX. Validate runtime/device compatibility (see
  `openvino_runtime_validation`-style checks) before enabling new accelerator paths.
- LLM backends are typically OpenAI-API-compatible or served via local OpenVINO Model
  Server — prefer this compatibility layer over bespoke client code.
- VLM (vision-language model) serving follows the same pattern as `vlm-openvino-serving`:
  OpenVINO-optimized inference behind a REST API.
- For any model producing probabilistic/confidence output (e.g. ASR no-speech/logprob
  thresholds, sentiment scores), keep thresholding and post-processing logic configurable and
  documented — do not hardcode magic numbers without config exposure.
- Treat model weights and downloaded artifacts as untrusted-until-verified; prefer trusted
  model hubs and pinned revisions, and never commit model weights to source control.
- When adding a new ML/LLM/VLM capability, document the model source, license, hardware
  requirements, and configuration knobs in the component's `docs/user-guide/`.

---

## Interaction with other instructions

- This skill is a peer to `.github/copilot-instructions.md` and is intended to be active for
  every task in this repository, not loaded conditionally like the on-demand skills listed in
  that file's "Language-Specific Skills" table.
- Component-specific context (e.g., Audio Analyzer architecture and API surface) lives in
  `.github/copilot-instructions.md` under "Component Deep Dives" — consult it for concrete
  API contracts before modifying a specific microservice.
- Security-sensitive changes still require loading `.github/skills/security-review/SKILL.md`
  in addition to this skill.
