# Clank

Portable Strix Halo local-agent stack.

## Stack

- Hermes: chat/orchestration/gateway
- Gemopus Gemma: default Hermes model
- Pi + Qwopus: coding worker
- whisper.cpp: local STT
- llama.cpp TurboQuant ROCm builds for LLM serving
- TurboQuant model servers run under `llama-server-watchdog`, which exits the
  container if `/v1/models` stays unavailable past the configured ready timeout.

## Workspace

- Hermes default cwd: `/workspace` (isolated scratch workspace)
- Hermes sees the live repo at `/workspace/host`
- Pi default cwd: `/workspace`
- Pi sees the live repo at `/workspace/host`
- Local Hermes skills: `Hermes/skills/`

Scratch projects live under `/workspace/code/...`. Live repo edits must use
`/workspace/host/...` from both Hermes and Pi.

## Beads

- Shared Beads runtime service: `beads`
- Initialize project-local Beads metadata with:

```bash
./scripts/beads-init
```

- Pi and Hermes both have `bd` available after build.
- `scripts/beads-init` also refreshes generated `.beads/*.jsonl` export files
  so stale container-owned cache files do not block Pi/Hermes writes.

## Pi Project Pipeline

- Hermes skill `pi-coder` starts tracked work through `pi_project_*` tools.
- Pi executes plan items in `/workspace/code/<ProjectName>`.
- Beads persists the project epic, child tasks, dependencies, and comments.
- Hermes gateway owns the editable Telegram tracker message.
- Each completed Pi step can emit an architecture report and render a short
  Manim video under `/workspace/animations/...`; richer revisions can use the
  upstream `skills/creative/manim-video` skill in `repos/hermes-agent`.

## Quickstart

1. Copy env files:

```bash
cp .env.example .env
cp Hermes/.env.example Hermes/.env
```

2. Edit:

- `.env`
  - set `MODEL_ROOT`
  - adjust model paths if your files differ
- `Hermes/.env`
  - set `API_SERVER_KEY`
  - set `TELEGRAM_BOT_TOKEN`
  - optional allowlists

3. Bootstrap repos:

```bash
./scripts/init.sh
```

4. Start:

```bash
docker compose up -d --build
```

## Main Commands

```bash
docker compose exec pi pi
docker compose exec hermes hermes
./scripts/pi-delegate "task"
```

Model server readiness timeouts:

- `QWOPUS_READY_TIMEOUT` defaults to `900` seconds
- `GEMMA_READY_TIMEOUT` defaults to `300` seconds

Qwopus runs at `--ctx-size 32768` with `--gpu-layers -1` so llama.cpp
`fit` can choose a ROCm-safe partial offload. Forcing `--gpu-layers 999`
with native `262144` context can wedge after tensor offload.

If a model load wedges while returning `503 Loading model`, the watchdog dumps
process, `radeontop`, and KFD accounting before killing the child process so
ROCm memory is released.

Hermes API:

- `http://127.0.0.1:8642/v1`

## Required Models

- Qwopus:
  - `QWOPUS_MODEL_PATH`
- Gemopus/Gemma:
  - `GEMMA_MODEL_PATH`
  - `GEMMA_MMPROJ_PATH`
- Whisper STT:
  - `STT_MODEL_PATH`

All are container-relative under `/models`, with host root mounted from `MODEL_ROOT`.
