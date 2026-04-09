# Clank

## Purpose

Portable Strix Halo local-agent stack. Telegram is the control plane. Hermes orchestrates. Gemopus handles normal chat. Pi+Qwopus handles coding. whisper.cpp handles STT.

## Workspace

- Repo root is the runtime workspace: `/workspace`
- Hermes cwd: `/workspace`
- Pi cwd: `/workspace`
- `Hermes/root/` is scratch/output, not the canonical workspace

## Services

- `hermes`
  - interactive Hermes container
  - image: `Hermes/Dockerfile`
  - mounts:
    - repo root -> `/workspace` rw
    - `hermes-home` -> `/root/.hermes`
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
- `pi`
  - dedicated coding worker
  - image: `Pi/Dockerfile`
  - mounts:
    - repo root -> `/workspace` rw
    - `pi-agent-home` -> `/root/.pi/agent`
    - `Pi/models.json` / `Pi/settings.json` bootstrap
  - UX: `docker compose exec pi pi`
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
- coding -> Hermes skill `pi-coder` -> `/workspace/scripts/pi-delegate` -> `docker exec pi ...` -> Pi CLI -> `qwopus-pi`
- Pi edits repo files through `/workspace`

## Config

- root `.env`
  - host/model/path/port variables for compose
- `Hermes/.env`
  - Hermes secrets and gateway env
- `Hermes/config.yaml`
  - Hermes model/STT config
  - external skills dir: `/workspace/Hermes/skills`
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
- `repos/`
  - local source checkouts used at Docker build time
  - gitignored

## Persistence

- `hermes-home`
  - `/root/.hermes`
- `pi-agent-home`
  - `/root/.pi/agent`
- models live outside repo under `${MODEL_ROOT}`, mounted to `/models`

## Build Pattern

- Dockerfiles bind-mount local repos from `repos/`
- `scripts/init.sh` is the canonical bootstrap for missing repos and env files
- rebuild after updating `repos/*`

## Constraints

- Gemma projector loads; server still exposes no native audio endpoint
- Hermes needs `stt` for Telegram voice
- Hermes delegates coding to Pi via Docker CLI wrapper, not Pi RPC
- Pi is the preferred writer for repo/system changes; Hermes orchestrates and reports

## Ops

- bootstrap: `./scripts/init.sh`
- start: `docker compose up -d --build`
- Pi CLI: `docker compose exec pi pi`
- headless Pi: `./scripts/pi-delegate "task"`
- Hermes CLI: `docker compose exec hermes hermes`
- Hermes API: `http://127.0.0.1:${HERMES_API_PORT}/v1`

## Change Policy

If you change the system:

- update this `AGENTS.md` for topology, mounts, models, ports, delegation, persistence, bootstrap, or control-flow changes
- update affected docs in the relevant subfolder
- keep docs compressed, token-efficient, exact
