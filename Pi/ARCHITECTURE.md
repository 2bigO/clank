# Pi Project Architecture

## Status

The Pi project pipeline is live in the local stack. Hermes is the control
plane, Pi is the preferred writer for coding work, Beads stores durable task
state, and the gateway owns Telegram progress updates.

## Runtime Flow

1. Telegram sends a coding request to `hermes-api`.
2. Hermes routes substantial coding work through the `pi-coder` skill.
3. `pi_project_start` creates a project under `/workspace/code/<ProjectName>`.
4. `pi_project_start` persists the project state in
   `/workspace/.hermes/pi-projects.json`.
5. Beads stores a project epic, child tasks, parent-child links, sequential
   task dependencies, comments, and state transitions.
6. A background worker delegates each plan item to Pi in the project directory.
7. The gateway polls `pi_project_status` and edits one tracker message with
   state, progress, checklist, comments, latest report, and animation path.
8. Follow-up feedback is appended through `pi_project_comment`; cancellation
   uses `pi_project_cancel`.

## Services

- `pi`: dedicated coding worker, `HOME=/workspace`, live repo at
  `/workspace/host`, scratch projects under `/workspace/code`.
- `qwopus-pi`: local OpenAI-compatible `llama-server` alias `qwopus-pi`,
  currently `--ctx-size 32768` with llama.cpp fit-controlled partial ROCm
  offload.
- `hermes` / `hermes-api`: orchestration, skills, gateway, tool registry, and
  tracker polling.
- `beads`: shared Dolt SQL server for Beads.

## Files

- `tools/PiOrchestrator/pi_project.py`: `pi_project_*` tools, persistence,
  Beads integration, resume handling, Pi delegation, and per-step animation.
- `Hermes/skills/autonomous-ai-agents/pi-coder/SKILL.md`: Hermes-facing
  procedure and constraints.
- `Pi/models.json`: Pi provider entry for `local-qwopus`.
- `Pi/settings.json`: default Pi provider/model selection.
- `Pi/pi-wrapper.sh`: self-healing wrapper that repopulates missing Pi config.
- `scripts/pi-delegate`: direct headless Pi wrapper retained for operations.
- `scripts/beads-init`: initializes repo-local Beads metadata and refreshes
  generated export files if old container ownership blocks writes.

## Persistence and Resume

Project state lives in `/workspace/.hermes/pi-projects.json`. On import,
`pi_project.py` reloads projects and restarts active, non-cancelled projects.
`pi_project_status` and `pi_project_comment` also resume active projects whose
worker or child Pi process disappeared after a container restart.

Running items are reset to pending during recovery so the current task can be
retried. Completed items remain complete.

## Beads

Pi and Hermes run with:

- `BEADS_DOLT_SHARED_SERVER=1`
- `BEADS_DOLT_SERVER_HOST=beads`
- `BEADS_DOLT_SERVER_PORT=3308`
- `BEADS_DIR=/workspace/host/.beads`

Use `./scripts/beads-init` after bootstrap or when generated `.beads` export
files have stale ownership.

## Tracker Model

`repos/hermes-agent/gateway/task_tracker.py` provides the generic gateway-owned
tracked message manager. `repos/hermes-agent/gateway/run.py` wires tool
completion callbacks for:

- `hf_download` trackers, polled every 5 seconds while downloading.
- `pi_project_*` trackers, polled every 10 seconds while planning/running.

Tracker message IDs and pollers are currently process-local. Project state is
durable through `pi-projects.json` and Beads, but tracker message bindings are
not yet restored across gateway restarts.

## Architecture Animations

Each completed Pi plan item asks Pi to return an `ARCHITECTURE_REPORT_JSON`
block. Hermes extracts the report, writes a Manim plan/script under
`/workspace/animations/<Project>/<step>/`, renders `final.mp4`, and stores the
paths on the project state. Tracker summaries include `MEDIA:/workspace/...`
when a rendered animation is available.

The implementation uses Manim directly in `pi_project.py`; the richer upstream
animation workflow remains available through
`repos/hermes-agent/skills/creative/manim-video`.

## Known Limitations

- Automatic reply-to-tracker routing is not durable yet; Hermes should call
  `pi_project_comment` when user feedback belongs to a running project.
- Gateway tracker message bindings are in memory, so after gateway restart a
  running project can resume, but the old Telegram tracker message may not be
  reused automatically.
- Long-running foreground dev servers are disallowed in Pi prompts; plan items
  should use bounded build, test, lint, or smoke commands.
- Qwopus availability depends on the model server reaching `/v1/models`.
  `llama-server-watchdog` bounds startup and releases ROCm resources if the
  server remains stuck in `503 Loading model`.
- Full forced Qwopus offload at native 262k context can stall after tensor
  loading; keep `--gpu-layers -1` unless retesting the offload plan.
