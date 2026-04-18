---
name: huggingface
description: When a HuggingFace URL appears, ALWAYS call hf_model_specs FIRST before anything else. Then offer download options. Never skip the specs step.
metadata:
  hermes:
    category: utilities
    requires_tools: [terminal]
triggers:
  - pattern: "huggingface.co/"
  - pattern: "hf.co/"
  - tool: hf_model_specs
  - tool: hf_download
---

# HuggingFace

## MANDATORY: Always Show Specs First

**When ANY HuggingFace URL appears in a message, you MUST call `hf_model_specs` FIRST before doing anything else.** No exceptions. Do not skip this step, do not offer download options before showing specs.

## Tools

### `hf_model_specs(repo_id, url)` — ALWAYS CALL THIS FIRST

Fetch model card metadata: parameters, license, base model, available files (GGUF, safetensors, etc.).

**This must be called for every HF link before any other action.**

### `hf_download(repo_id, url, filename, target_dir)`

Start downloading a model file from HF Hub. Returns immediately with a job ID and progress bar.
- If `filename` is omitted, lists all available files
- If `filename` is given, starts the download in the background and returns a job ID

### `hf_download_status(job_id)`

Check progress of an active download. Pass the `job_id` from `hf_download`.

In Telegram/gateway mode, the gateway updates the tracker message automatically in the background every few seconds. Only call this tool if the user explicitly asks for a manual status check.

## Procedure

1. **When a HF link appears** -> call `hf_model_specs` with the URL. Show the specs to the user.
2. After showing specs -> call `hf_download` without `filename` to list available files with sizes.
3. When the user picks a file -> call `hf_download` with `filename`.
4. After `hf_download` returns, tell the user the download has started. In Telegram/gateway mode, do not keep polling: the gateway-owned tracker message updates automatically in the background.
5. Only call `hf_download_status` if the user explicitly asks for a manual status check, or if you are not in gateway mode.
6. Report final file path and size when the tracker or manual status check shows completion.

## Rules

- **ALWAYS call `hf_model_specs` first** — never skip to download
- **NEVER ask "Would you like me to keep checking?"**
- **DO NOT poll `hf_download_status` repeatedly in Telegram/gateway mode** — the gateway tracker handles that automatically
- Show file sizes so the user knows what to expect
- Private models need `HF_TOKEN` env var
- Downloads go to `MODEL_ROOT` env var or `/models`
