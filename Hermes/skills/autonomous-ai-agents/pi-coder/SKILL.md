---
name: pi-coder
description: Delegate substantial coding and repository modification tasks to the Pi coding agent container running Qwopus.
metadata:
  hermes:
    category: autonomous-ai-agents
    requires_tools: [terminal]
---

# Pi Coder

## When to Use

- The user wants code changes, refactors, debugging, or repo-wide edits.
- The task should be executed by the dedicated Pi coding worker instead of Hermes directly.
- The task touches the live repo under `/workspace/host`.

## Procedure

1. Clarify the target working directory under `/workspace/host` if it is ambiguous. Use `/workspace/host` by default.
2. Translate Hermes paths to Pi paths before delegation:

- Hermes sees the live repo at `/workspace/host/...`
- Pi sees that same repo at `/workspace/...`
- Example: Hermes path `/workspace/host/repos/foo` becomes Pi path `/workspace/repos/foo`
3. Delegate the task through the wrapper script:

```bash
cat <<'EOF' | /workspace/host/scripts/pi-delegate --cwd /workspace
<task for pi>
EOF
```

4. Let Pi perform the code work and return the result.
5. Summarize the result back to the user and mention any changed files or remaining risks.

## Constraints

- Hermes default cwd `/workspace` is an isolated scratch area.
- The live host repo is mounted at `/workspace/host` for Hermes and at `/workspace` for Pi.
- Prefer Pi for code edits. Hermes should orchestrate, inspect, and report.
- Keep the delegated task explicit: what to change, where, and how to verify it.

## Verification

- If the task changed code, inspect the modified files under `/workspace/host`.
- Run targeted checks from Hermes if needed after Pi completes.
