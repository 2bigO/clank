"""HuggingFace model specs tool."""

import json
import os
import re
import sys

from tools.registry import registry, tool_error

_HF_SRC = "/opt/src/huggingface_hub/src"
if _HF_SRC not in sys.path:
    sys.path.insert(0, _HF_SRC)

from huggingface_hub import HfApi
from huggingface_hub.errors import RepositoryNotFoundError, HfHubHTTPError


def _parse_hf_url(url: str) -> str | None:
    m = re.match(r"https?://huggingface\.co/([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-/]+)", url)
    return m.group(1) if m else None


def _human_size(nbytes: int) -> str:
    if nbytes < 1024:
        return f"{nbytes} B"
    for unit in ("KB", "MB", "GB", "TB"):
        nbytes /= 1024.0
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
    return f"{nbytes:.1f} PB"


def hf_model_specs(repo_id: str = "", url: str = "", task_id: str = None) -> str:
    if not repo_id and url:
        repo_id = _parse_hf_url(url)
    if not repo_id:
        return tool_error(
            "Provide either repo_id (e.g. 'unsloth/Qwen3.5-4B-GGUF') or a HuggingFace URL."
        )

    api = HfApi(
        token=os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    )
    try:
        info = api.repo_info(repo_id, files_metadata=True)
    except RepositoryNotFoundError:
        return tool_error(f"Repository not found: {repo_id}")
    except HfHubHTTPError as e:
        return tool_error(f"HTTP error fetching {repo_id}: {e}")
    except Exception as e:
        return tool_error(f"Failed to fetch specs for {repo_id}: {e}")

    model_id = info.id or repo_id
    pipeline_tag = info.pipeline_tag or "unknown"
    tags = info.tags or []
    library = None
    for tag in tags:
        if tag.startswith("library:"):
            library = tag.split(":", 1)[1]
            break

    siblings = info.siblings or []
    file_list = [s.rfilename for s in siblings if s.rfilename]
    gguf_files = [f for f in file_list if f.endswith(".gguf")]
    safetensors_files = [f for f in file_list if f.endswith(".safetensors")]

    card_data = info.card_data or {}
    license_val = getattr(card_data, "license", None) or "unknown"
    if isinstance(license_val, list):
        license_val = ", ".join(license_val)

    base_models = getattr(card_data, "base_model", None) or []
    if isinstance(base_models, list):
        base_model = ", ".join(base_models) if base_models else ""
    elif isinstance(base_models, str):
        base_model = base_models
    else:
        base_model = ""

    lines = [
        f"**Model:** `{model_id}`",
        f"**Pipeline:** {pipeline_tag}",
        f"**License:** {license_val}",
    ]
    if library:
        lines.append(f"**Library:** {library}")
    if base_model:
        lines.append(f"**Base Model:** {base_model}")
    if info.downloads is not None:
        lines.append(f"**Downloads:** {info.downloads:,}")
    if info.likes is not None:
        lines.append(f"**Likes:** {info.likes:,}")

    params = getattr(card_data, "params", None) or {}
    if params:
        total = params.get("total", 0)
        if total:
            if total >= 1e9:
                lines.append(f"**Parameters:** {total / 1e9:.1f}B")
            elif total >= 1e6:
                lines.append(f"**Parameters:** {total / 1e6:.1f}M")

    if info.gguf is not None:
        gguf_info = info.gguf
        total_size = getattr(gguf_info, "total", None)
        arch = getattr(gguf_info, "architecture", None)
        ctx_len = getattr(gguf_info, "context_length", None)
        if total_size:
            if total_size >= 1e9:
                lines.append(f"**GGUF total size:** {total_size / 1e9:.1f} GB")
            else:
                lines.append(f"**GGUF total size:** {total_size / 1e6:.1f} MB")
        if arch:
            lines.append(f"**Architecture:** {arch}")
        if ctx_len:
            lines.append(f"**Context length:** {ctx_len:,}")

    if gguf_files:
        lines.append(f"\n**GGUF files ({len(gguf_files)}):**")
        for sibling in siblings:
            if sibling.rfilename and sibling.rfilename.endswith(".gguf"):
                lines.append(
                    f"- `{sibling.rfilename}` ({_human_size(sibling.size or 0)})"
                )
    elif safetensors_files:
        lines.append(f"\n**Safetensors files ({len(safetensors_files)}):**")
        for filename in safetensors_files[:10]:
            lines.append(f"- `{filename}`")

    if file_list and not gguf_files and not safetensors_files:
        lines.append(f"\n**Files ({len(file_list)}):**")
        for filename in file_list[:15]:
            lines.append(f"- `{filename}`")

    lines.append(f"\n[View on HuggingFace](https://huggingface.co/{model_id})")

    return json.dumps(
        {
            "success": True,
            "repo_id": model_id,
            "pipeline_tag": pipeline_tag,
            "license": license_val,
            "library": library,
            "base_model": base_model,
            "downloads": info.downloads,
            "likes": info.likes,
            "summary": "\n".join(lines),
        }
    )


HF_MODEL_SPECS_SCHEMA = {
    "name": "hf_model_specs",
    "description": "ALWAYS call this FIRST when a HuggingFace URL appears. Fetch model card metadata including files, license, parameters, downloads, and base model info. Must be called before hf_download.",
    "parameters": {
        "type": "object",
        "properties": {
            "repo_id": {
                "type": "string",
                "description": "HuggingFace repo ID, e.g. 'unsloth/Qwen3.5-4B-GGUF'",
            },
            "url": {
                "type": "string",
                "description": "HuggingFace URL, e.g. 'https://huggingface.co/unsloth/Qwen3.5-4B-GGUF'",
            },
        },
    },
}


registry.register(
    name="hf_model_specs",
    toolset="huggingface",
    schema=HF_MODEL_SPECS_SCHEMA,
    handler=lambda args, **kw: hf_model_specs(
        repo_id=args.get("repo_id", ""),
        url=args.get("url", ""),
        task_id=kw.get("task_id"),
    ),
    check_fn=lambda: True,
    emoji="🤗",
)
