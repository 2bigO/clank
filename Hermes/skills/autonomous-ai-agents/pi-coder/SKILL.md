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

- **Hermes** orchestrates: creates the project, delegates steps, tracks progress.
- **Pi** executes: writes code, builds, tests inside the project folder.
- **Beads** persists: epic + child tasks for durable state across restarts.
- **Gateway tracker**: one editable Telegram message with checklist + progress bar.

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

The tool returns a `project_id` and a tracker-ready summary. The gateway will automatically start polling for updates.

### 3. Create the project folder

Create a folder under `/workspace/code/` named after the project (PascalCase, e.g. `HelloWorld`):

```bash
mkdir -p /workspace/code/HelloWorld
```

From Pi's perspective (same mount), this path is `/workspace/code/HelloWorld`.

### 4. Delegate steps to Pi

For each plan item, delegate to Pi using `pi-delegate` with `--cwd /workspace/code/<ProjectName>`:

```bash
cat <<'EOF' | /workspace/host/scripts/pi-delegate --cwd /workspace/code/HelloWorld
<specific task for this step>
EOF
```

**First step is always: create a Dockerfile** for the project's runtime environment.

For example, for a Bun project:
```
Create a Dockerfile that:
- Uses oven/bun as the base image
- Copies the project files
- Installs dependencies
- Exposes the needed port
- Has a CMD to run the application
```

Then subsequent steps:
```
Create index.ts with a Bun.serve() HTTP server that returns "Hello World"
```

```
Create package.json with bun as the package manager
```

### 5. Update project state

After each step completes, call `pi_project_status` with the `project_id` to get the current summary. The gateway tracker will reflect progress.

### 6. Verify and report

After all steps:
- Inspect the created files under `/workspace/code/<ProjectName>/`
- Optionally build/test: `docker build -t <name> /workspace/code/<ProjectName>`
- Report the result to the user with the final tracker summary

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

2. Create folder: `mkdir -p /workspace/code/HelloWorld`

3. Delegate step 1 to Pi:
   ```bash
   cat <<'EOF' | /workspace/host/scripts/pi-delegate --cwd /workspace/code/HelloWorld
   Create a Dockerfile for a Bun-based web server project. Use oven/bun as the base image. The Dockerfile should:
   - Use oven/bun:1 as the base
   - Set working directory to /app
   - Copy package.json and install dependencies
   - Copy all source files
   - Expose port 3000
   - CMD to run index.ts with bun
   EOF
   ```

4. Delegate step 2 to Pi:
   ```bash
   cat <<'EOF' | /workspace/host/scripts/pi-delegate --cwd /workspace/code/HelloWorld
   Create index.ts with a Bun HTTP server that listens on port 3000 and returns "Hello World" for all requests.
   EOF
   ```

5. Delegate step 3 to Pi:
   ```bash
   cat <<'EOF' | /workspace/host/scripts/pi-delegate --cwd /workspace/code/HelloWorld
   Create a package.json for this Bun project with name "hello-world-bun", version "1.0.0", and main "index.ts".
   EOF
   ```

6. Verify: check files exist, optionally build with docker.

7. Report result to user.

## Constraints

- **Always create a project folder** under `/workspace/code/` — never write files in the workspace root.
- **Always start with a Dockerfile** — the project should be self-contained and buildable.
- **Pi's cwd** for delegation is `/workspace/code/<ProjectName>` (same path from both Hermes and Pi perspectives).
- **Hermes inspects** results at `/workspace/code/<ProjectName>/`.
- Keep delegated tasks **specific and atomic** — one file or one concern per delegation.
- The project folder name should be **PascalCase** with no spaces (e.g. `HelloWorld`, `ApiGateway`).

## Verification

- Check that all planned files exist under `/workspace/code/<ProjectName>/`
- Optionally build: `docker build -t <project-name> /workspace/code/<ProjectName>`
- Optionally run: `docker run --rm -p 3000:3000 <project-name>` and curl localhost
- Report the final state to the user
