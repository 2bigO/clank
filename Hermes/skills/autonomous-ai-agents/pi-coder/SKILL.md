---
name: pi-coder
description: Delegate substantial coding and repository modification tasks to the Pi coding agent container running Qwopus, using Pi project orchestration for tracked, multi-step work.
metadata:
  hermes:
    category: autonomous-ai-agents
    requires_tools: [terminal]
---

# Pi Coder — Orchestrated Project Pipeline

## When to Use

- The user says **"use pi to do …"** or **"use pi for …"** — this is the trigger phrase for pi-coder.
- The user wants a coding project with multiple steps, not a one-off edit.
- The task should be tracked with progress visible in Telegram (one editable tracker message).

## Architecture

- **Hermes** orchestrates: creates the project, tracks progress, and routes follow-up feedback.
- **Pi** executes: writes code, builds, and tests inside the shared workspace project folder.
- **Beads** persists: epic + child tasks for durable state across restarts.
- **Gateway tracker**: one editable Telegram message with checklist + progress bar.
- **Shared scratch**: Hermes and Pi both use `/workspace`; the live repo remains at `/workspace/host`.
- **Architecture animation**: each completed Pi step should yield a compact architecture report and a short Manim video Hermes can send to the user.

## Procedure

### 1. Parse the request

Extract from the user's message:
- **Project title** — short PascalCase name (e.g. "HelloWorld")
- **Description** — what the project should do
- **Plan items** — break the work into 2-5 concrete steps

If the user says "use pi to do X", treat X as the project description and derive a plan.

### 2. Create the project via pi_project_start

Call the `pi_project_start` tool with:

```json
{
  "title": "<short project name>",
  "description": "<detailed description>",
  "plan": "[{\"title\": \"Step 1\", \"content\": \"...\"}, {\"title\": \"Step 2\", \"content\": \"...\"}]"
}
```

The tool returns a `project_id`, starts a background worker, and uses `/workspace/code/<ProjectName>` as the project root automatically. The gateway will poll for updates.

### 3. Let the orchestrator run

- Do **not** create the folder yourself.
- Do **not** use terminal to call `pi-delegate` manually for normal project execution.
- Do **not** write project files from Hermes.

`pi_project_start` owns:
- creating `/workspace/code/<ProjectName>`
- delegating each plan item to Pi in that cwd
- updating Beads state
- persisting project state for resume after restart
- capturing architecture summaries and rendering per-step animation artifacts

### 4. Handle follow-ups

- If the user sends feedback while the project is running, call `pi_project_comment`.
- If the user explicitly asks for status, call `pi_project_status`.
- If the user wants to stop the run, call `pi_project_cancel`.

### 5. Verify and report

After the project completes:
- Inspect the results under `/workspace/code/<ProjectName>/`
- Run direct verification when needed from that same directory
- Report the final outcome using the final tracker state

When project status exposes a completed-step architecture animation:
- send a short textual summary of the architectural change
- send the rendered video with `MEDIA:/workspace/.../final.mp4`
- if a richer or revised animation is needed, use the `manim-video` skill to regenerate it

## Example Flow

User: "use pi to create a hello world web server using Bun"

1. Call `pi_project_start`:
   - title: "HelloWorld"
   - description: "Create a simple hello world web server using Bun"
   - plan: [
       {"title": "Create Dockerfile", "content": "Create a Dockerfile using oven/bun base image with proper build setup"},
       {"title": "Write server", "content": "Create index.ts with Bun.serve() returning Hello World"},
       {"title": "Add package.json", "content": "Create package.json for the Bun project"},
       {"title": "Verify build", "content": "Build the Docker image and verify it starts correctly"}
     ]

2. Wait for the orchestrator to run the plan in `/workspace/code/HelloWorld`.

3. If the user says "also add a health endpoint", call `pi_project_comment` with that feedback.

4. Verify the final files and report the result.

## Constraints

- The project root is `/workspace/code/<ProjectName>` and is shared naturally by Hermes and Pi.
- Hermes should not write the project files itself during normal execution.
- Keep plan items specific and atomic so the background worker can make clear progress.
- The project folder name should be PascalCase with no spaces (e.g. `HelloWorld`, `ApiGateway`).
- Pi should end each task with a machine-readable architecture report that Hermes can present back to the user.

## Verification

- Check that the planned files exist under `/workspace/code/<ProjectName>/`
- Optionally build or run from `/workspace/code/<ProjectName>`
- Report the final state to the user
