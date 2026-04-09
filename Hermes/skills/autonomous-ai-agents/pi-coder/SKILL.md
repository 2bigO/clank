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
- The task touches files under `/workspace`.

## Procedure

1. Clarify the target working directory under `/workspace` if it is ambiguous. Use `/workspace` by default.
2. Delegate the task through the wrapper script:

```bash
cat <<'EOF' | /workspace/scripts/pi-delegate --cwd /workspace
<task for pi>
EOF
```

3. Let Pi perform the code work and return the result.
4. Summarize the result back to the user and mention any changed files or remaining risks.

## Constraints

- Pi has write access to `/workspace`, which is the host's `/home/keyvan`.
- Prefer Pi for code edits. Hermes should orchestrate, inspect, and report.
- Keep the delegated task explicit: what to change, where, and how to verify it.

## Verification

- If the task changed code, inspect the modified files under `/workspace`.
- Run targeted checks from Hermes if needed after Pi completes.
