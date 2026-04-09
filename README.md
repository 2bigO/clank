# Clank

Portable Strix Halo local-agent stack.

## Stack

- Hermes: chat/orchestration/gateway
- Gemopus Gemma: default Hermes model
- Pi + Qwopus: coding worker
- whisper.cpp: local STT
- llama.cpp TurboQuant ROCm builds for LLM serving

## Workspace

- Repo root is the workspace in containers: `/workspace`
- Hermes default cwd: `/workspace`
- Pi default cwd: `/workspace`
- Local Hermes skills: `Hermes/skills/`

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
