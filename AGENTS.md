# Clank

## Purpose

Portable Strix Halo local-agent stack. Telegram is the control plane. Hermes orchestrates. Gemopus handles normal chat. Pi+Qwopus handles coding. whisper.cpp handles STT.

## Workspace

- Shared scratch workspace: `/workspace`
- Live repo mount in Hermes and Pi: `/workspace/host`
- Scratch projects live under `/workspace/code/...`
- Use `/workspace` for ad hoc work and generated project files
- Use `/workspace/host/...` for live repo edits, scripts, config, and source

## Services

- `hermes`
  - interactive Hermes container
  - image: `Hermes/Dockerfile`
  - mounts:
    - `workspace` -> `/workspace` rw
    - repo root -> `/workspace/host` rw
    - Hermes state/config lives in shared scratch `/workspace/.hermes`
    - `Hermes/config.yaml` -> `/etc/hermes-bootstrap/config.yaml` ro
    - `${DOCKER_BIN}` -> `/usr/local/bin/docker` ro
    - `/var/run/docker.sock` rw
- `hermes-api`
  - Hermes gateway/API
  - host port: `${HERMES_API_PORT}`
- `gemma-hermes`
  - TurboQuant ROCm `llama-server`
  - model: `${GEMMA_MODEL_PATH}`
  - projector: `${GEMMA_MMPROJ_PATH}`
  - alias: `gemma-hermes`
  - host port: `${GEMMA_PORT}`
  - current modalities: `vision=true`, `audio=false`
- `qwopus-pi`
  - TurboQuant ROCm `llama-server`
  - model: `${QWOPUS_MODEL_PATH}`
  - alias: `qwopus-pi`
  - host port: `${QWOPUS_PORT}`
  - context/offload: `--ctx-size 32768`, `--gpu-layers -1` so llama.cpp fit can choose partial ROCm offload
  - startup is bounded by `llama-server-watchdog` / `${QWOPUS_READY_TIMEOUT:-900}`
- `pi`
  - dedicated coding worker
  - image: `Pi/Dockerfile`
  - mounts:
    - `workspace` -> `/workspace` rw
    - repo root -> `/workspace/host` rw
    - Pi runtime state lives under shared scratch `/workspace/.pi/`
    - `Pi/models.json` / `Pi/settings.json` are bootstrapped from `/workspace/host/Pi/`
  - UX: `docker compose exec pi pi`
- `beads`
  - shared Beads / Dolt SQL runtime
  - image: `Beads/Dockerfile`
  - mounts:
    - repo root -> `/workspace` rw
    - `Beads/state` -> `/var/lib/beads` rw
  - provides the shared Dolt server for `bd`
- `stt`
  - local OpenAI-style transcription endpoint
  - image: `STT/Dockerfile`
  - backend: `whisper.cpp`
  - route used by Hermes: `POST /v1/audio/transcriptions`
  - model: `${STT_MODEL_PATH}`
  - host port: `${STT_PORT}`

## Control Flow

- Telegram -> `hermes-api` -> Hermes loop
- normal chat -> `gemma-hermes`
- voice -> Hermes STT adapter -> `stt` -> transcript -> `gemma-hermes`
- coding -> Hermes skill `pi-coder` -> `pi_project_*` tools -> background Pi work in shared `/workspace`
- completed Pi steps can emit architecture reports that Hermes renders into Manim artifacts under `/workspace/animations/...`; richer animation revisions can use `repos/hermes-agent/skills/creative/manim-video`
- direct Pi delegation wrapper still lives at `/workspace/host/scripts/pi-delegate`
- Pi uses `/workspace` for scratch projects and `/workspace/host` for live repo work

## Config

- root `.env`
  - host/model/path/port variables for compose
- `Hermes/.env`
  - Hermes secrets and gateway env
  - `HF_TOKEN` for authenticated HuggingFace downloads
  - `MODEL_ROOT=/models` inside Hermes containers
- Hermes containers run with `HOME=/workspace` and `XDG_STATE_HOME=/workspace/.local/state`
- `Hermes/config.yaml`
  - Hermes model/STT config
  - external skills dirs: `/workspace/host/Hermes/skills`, `/opt/src/hermes-agent/skills`
  - `terminal.cwd: /workspace`
  - streaming enabled for Telegram edits
  - `huggingface.token` / `huggingface.model_root` read from env
- `.beads/`
  - project-local Beads workspace metadata/config
  - created by `./scripts/beads-init`
- `Beads/state/`
  - Beads service server state and shared Dolt data
- `Pi/models.json`
  - Pi provider config
  - `local-qwopus` -> `http://qwopus-pi:8080/v1`
- `Pi/settings.json`
  - Pi defaults
  - default provider/model: `local-qwopus/qwopus-pi`

## Source Layout

- `docker-compose.yml`
  - topology, ports, mounts, runtime wiring
- `scripts/init.sh`
  - bootstrap repos and env files
- `scripts/pi-delegate`
  - stable headless Pi wrapper
- `Hermes/skills/autonomous-ai-agents/pi-coder/SKILL.md`
  - Hermes coding delegation entrypoint
- `Pi/ARCHITECTURE.md`
  - Pi project pipeline handoff/status notes
- `repos/`
  - local source checkouts used at Docker build time
  - gitignored
- `tools/`
  - external tool packages that live outside `hermes-agent`
  - `tools/HuggingFace/` is copied into the Hermes image and imported dynamically
  - `tools/GatewaySmoke/telegram_ux_smoke.py` runs a fake-Telegram UX harness and logs send/edit content for inspection
  - paired source repo lives in `repos/huggingface_hub/`

## Persistence

- `pi-agent-home`
- models live outside repo under `${MODEL_ROOT}`, mounted to `/models`
- `workspace/`
  - shared Hermes/Pi scratch area mounted as `/workspace`
  - includes Hermes state under `/workspace/.hermes`
- `workspace/.local/state/hermes/gateway-locks/`
  - machine-local gateway token locks for Telegram and other platform adapters

## Build Pattern

- Dockerfiles bind-mount local repos from `repos/`
- `scripts/init.sh` is the canonical bootstrap for missing repos and env files
- rebuild after updating `repos/*` or `tools/*`
- HuggingFace support depends on both `repos/huggingface_hub/` and `tools/HuggingFace/`
- TurboQuant model servers use `TurboQuant/llama-server-watchdog`; rebuild after changing the wrapper or model-server command wiring

## Constraints

- Gemma projector loads; server still exposes no native audio endpoint
- Hermes needs `stt` for Telegram voice
- Hermes delegates coding to Pi via Docker CLI wrapper, not Pi RPC
- Pi is the preferred writer for repo/system changes; Hermes orchestrates and reports
- `/workspace` is shared scratch, not the live repo
- both Hermes and Pi must use `/workspace/host/...` explicitly to touch the live repo
- Pi runs as the host UID/GID via docker-compose `user:` so files written in `/workspace` or `/workspace/host` are host-owned
- HuggingFace downloads land in `/models` and are chowned back to the host UID/GID by the tool
- Telegram download progress tracking is gateway-owned: the gateway edits one tracker message every ~5s until completion
- Qwopus must not force full GPU offload at native 262k context; that can wedge after tensor loading on Strix Halo ROCm
- Stuck `llama-server` startup is treated as unhealthy: the watchdog kills a child that remains in `503 Loading model` beyond its timeout so ROCm memory does not stay pinned

## Ops

- bootstrap: `./scripts/init.sh`
- start: `docker compose up -d --build`
- Beads init: `./scripts/beads-init`
- Pi CLI: `docker compose exec pi pi`
- Beads CLI in Pi: `docker compose exec pi bd ...`
- Beads CLI in Hermes: `docker compose exec hermes bd ...`
- headless Pi: `./scripts/pi-delegate "task"`
- Telegram UX smoke harness: `./scripts/telegram-ux-smoke "Use Pi to ..."` logs JSONL to `/workspace/.hermes/logs/telegram-ux.jsonl`
- Hermes CLI: `docker compose exec hermes hermes`
- Hermes API: `http://127.0.0.1:${HERMES_API_PORT}/v1`

## Recovery Notes

- Working HuggingFace integration spans both the root repo and `repos/hermes-agent`
- Gateway tracker logic lives in `repos/hermes-agent/gateway/run.py`
- External HuggingFace tool code lives in `tools/HuggingFace/`
- If the workspace is recloned, restore both the root files and the `repos/hermes-agent` patches, then rebuild `hermes-local`

## Change Policy

If you change the system:

- update this `AGENTS.md` for topology, mounts, models, ports, delegation, persistence, bootstrap, or control-flow changes
- update affected docs in the relevant subfolder
- keep docs compressed, token-efficient, exact
