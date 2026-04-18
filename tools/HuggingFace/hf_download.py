"""HuggingFace Download Tool — async download with progress tracking."""

import json
import os
import re
import sys
import threading
import time
from typing import Callable, Optional

_HF_SRC = "/opt/src/huggingface_hub/src"
if _HF_SRC not in sys.path:
    sys.path.insert(0, _HF_SRC)

from huggingface_hub import HfApi, snapshot_download
from huggingface_hub.errors import RepositoryNotFoundError, HfHubHTTPError

from tools.registry import registry, tool_error


def _parse_hf_url(url: str) -> str | None:
    m = re.match(r"https?://huggingface\.co/([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-/]+)", url)
    return m.group(1) if m else None


def _human_size(nbytes):
    if nbytes < 1024:
        return f"{nbytes} B"
    for unit in ("KB", "MB", "GB", "TB"):
        nbytes /= 1024.0
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
    return f"{nbytes:.1f} PB"


def _progress_bar(pct, width=20):
    filled = int(width * pct / 100)
    return f"[{'█' * filled}{'░' * (width - filled)}] {pct:.1f}%"


def _format_eta(seconds):
    if seconds is None:
        return ""
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return "0.0s"
    if seconds < 120:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 120:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _get_hf_token():
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")


def _state_dir():
    state_dir = os.path.join(
        os.environ.get("HF_MODEL_ROOT", "") or os.environ.get("MODEL_ROOT", "/models"),
        ".hf_downloads",
    )
    os.makedirs(state_dir, exist_ok=True)
    return state_dir


def _state_path(job_id):
    safe = job_id.replace("/", "__").replace("::", "_")
    return os.path.join(_state_dir(), f"{safe}.json")


def _load_state(job_id):
    path = _state_path(job_id)
    if os.path.exists(path):
        try:
            with open(path) as file_obj:
                state = json.load(file_obj)
            if "job_id" not in state:
                state["job_id"] = job_id
            if "success" not in state and state.get("status") == "complete":
                state["success"] = True
            return state
        except Exception:
            pass
    return None


def _save_state(job_id, state):
    path = _state_path(job_id)
    try:
        state = dict(state)
        state.setdefault("job_id", job_id)
        with open(path, "w") as file_obj:
            json.dump(state, file_obj)
    except Exception:
        pass


def _restore_all_states():
    restored = {}
    state_dir = _state_dir()
    if not os.path.isdir(state_dir):
        return restored
    for filename in os.listdir(state_dir):
        if not filename.endswith(".json"):
            continue
        try:
            with open(os.path.join(state_dir, filename)) as file_obj:
                saved = json.load(file_obj)
            job_id = saved.get("job_id")
            if not job_id and saved.get("repo_id") and saved.get("filename"):
                job_id = f"{saved['repo_id']}::{saved['filename']}"
                saved["job_id"] = job_id
            if job_id:
                restored[job_id] = saved
        except Exception:
            pass
    return restored


def _refresh_job_from_disk(job_id, job):
    local_path = job.get("local_path") or os.path.join(
        job.get("dest_dir", ""), job.get("filename", "")
    )
    total_bytes = job.get("total_bytes") or 0
    if local_path and os.path.exists(local_path):
        try:
            actual_size = os.path.getsize(local_path)
        except OSError:
            actual_size = 0
        if actual_size > 0:
            job["downloaded_bytes"] = actual_size
            job["local_path"] = local_path
            if total_bytes > 0 and actual_size >= total_bytes:
                job["status"] = "complete"
                job["pct"] = 100.0
                job["size_str"] = _human_size(actual_size)
                job["eta_seconds"] = 0
                job["success"] = True
                _save_state(job_id, job)
                return job
            if total_bytes > 0 and job.get("status") == "downloading":
                job["pct"] = min(99.0, round(actual_size / total_bytes * 100, 1))
    return job


def _job_from_disk(job_id):
    if "::" not in job_id:
        return None
    repo_id, filename = job_id.split("::", 1)
    model_root = os.environ.get("HF_MODEL_ROOT") or os.environ.get(
        "MODEL_ROOT", "/models"
    )
    dest_dir = os.path.join(model_root, repo_id)
    local_path = os.path.join(dest_dir, filename)
    if not os.path.exists(local_path):
        return None
    try:
        size = os.path.getsize(local_path)
    except OSError:
        return None
    return {
        "job_id": job_id,
        "status": "complete",
        "repo_id": repo_id,
        "filename": filename,
        "dest_dir": dest_dir,
        "downloaded_bytes": size,
        "pct": 100.0,
        "local_path": local_path,
        "size_str": _human_size(size),
        "elapsed_seconds": 0,
        "speed_mbps": 0,
        "eta_seconds": 0,
        "error": None,
        "success": True,
    }


def _chown(path, uid, gid):
    if uid > 0 and gid > 0:
        try:
            os.chown(path, uid, gid)
        except OSError:
            pass


_downloads = {}
_downloads_lock = threading.Lock()


def _download_worker(job_id, repo_id, filename, dest_dir, token, file_size):
    job = _downloads[job_id]
    job["status"] = "downloading"
    job["started_at"] = time.time()
    _save_state(job_id, job)
    try:
        snapshot_download(
            repo_id=repo_id,
            allow_patterns=[filename],
            local_dir=dest_dir,
            max_workers=8,
            token=token,
        )
        local_path = os.path.join(dest_dir, filename)
        host_uid = int(os.environ.get("HOST_UID", "0"))
        host_gid = int(os.environ.get("HOST_GID", "0"))
        _chown(local_path, host_uid, host_gid)
        _chown(dest_dir, host_uid, host_gid)
        actual_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0
        elapsed = time.time() - job["started_at"]
        job["status"] = "complete"
        job["pct"] = 100.0
        job["downloaded_bytes"] = actual_size
        job["local_path"] = local_path
        job["size_str"] = _human_size(actual_size)
        job["elapsed_seconds"] = round(elapsed, 1)
        job["eta_seconds"] = 0
        _save_state(job_id, job)
    except HfHubHTTPError as exc:
        job["status"] = "error"
        job["error"] = f"HTTP error: {exc}"
        _save_state(job_id, job)
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        _save_state(job_id, job)


def _poll_progress(job_id, dest_dir, filename, file_size):
    try:
        local_path = os.path.join(dest_dir, filename)
        cache_dir = os.path.join(dest_dir, ".cache", "huggingface", "download")
        while True:
            time.sleep(2)
            if job_id not in _downloads:
                return
            job = _downloads[job_id]
            if job["status"] in ("complete", "error"):
                return

            current_size = 0
            if os.path.exists(local_path):
                try:
                    current_size = os.path.getsize(local_path)
                except OSError:
                    pass
            if current_size == 0 and os.path.isdir(cache_dir):
                for cached in os.listdir(cache_dir):
                    if cached.endswith(".incomplete"):
                        try:
                            current_size = os.path.getsize(
                                os.path.join(cache_dir, cached)
                            )
                        except OSError:
                            pass
                        break

            if current_size > 0 and file_size > 0:
                job["pct"] = min(99.0, round(current_size / file_size * 100, 1))
            job["downloaded_bytes"] = current_size
            elapsed = time.time() - job.get("started_at", time.time())
            job["elapsed_seconds"] = round(elapsed, 1)
            if elapsed > 0 and current_size > 0:
                job["speed_mbps"] = round(current_size / elapsed / (1024 * 1024), 1)
                if file_size > current_size:
                    remaining = file_size - current_size
                    speed_bps = current_size / elapsed
                    if speed_bps > 0:
                        job["eta_seconds"] = round(remaining / speed_bps, 1)
            elif file_size > 0:
                job["eta_seconds"] = None

            _save_state(job_id, job)
    except Exception:
        pass


def hf_download(
    repo_id: str = "",
    url: str = "",
    filename: str = "",
    target_dir: str = "",
    progress_callback: Optional[Callable[[dict], None]] = None,
    task_id: str = None,
) -> str:
    if not repo_id and url:
        repo_id = _parse_hf_url(url)
    if not repo_id:
        return tool_error("Provide either repo_id or a HuggingFace URL.")

    model_root = os.environ.get("HF_MODEL_ROOT") or os.environ.get(
        "MODEL_ROOT", "/models"
    )
    dest_dir = target_dir or os.path.join(model_root, repo_id)
    os.makedirs(dest_dir, exist_ok=True)
    token = _get_hf_token()
    api = HfApi(token=token)

    if not filename:
        try:
            files = []
            for entry in api.list_repo_tree(repo_id, recursive=True):
                if hasattr(entry, "size") and hasattr(entry, "path"):
                    files.append({"path": entry.path, "size": entry.size})
        except RepositoryNotFoundError:
            return tool_error(f"Repository not found: {repo_id}")
        except Exception as exc:
            return tool_error(f"Failed to list files for {repo_id}: {exc}")

        if not files:
            return tool_error(f"No files found for repo {repo_id}")

        gguf = [f for f in files if f["path"].endswith(".gguf")]
        safetensors = [f for f in files if f["path"].endswith(".safetensors")]
        lines = [f"**Available files for `{repo_id}`:**"]
        if gguf:
            lines.append(f"\n**GGUF ({len(gguf)}):**")
            for file_info in sorted(gguf, key=lambda item: item["size"], reverse=True)[
                :15
            ]:
                lines.append(
                    f"- `{file_info['path']}` ({_human_size(file_info['size'])})"
                )
            if len(gguf) > 15:
                lines.append(f"- ... and {len(gguf) - 15} more")
        if safetensors:
            lines.append(f"\n**Safetensors ({len(safetensors)}):**")
            for file_info in sorted(
                safetensors, key=lambda item: item["size"], reverse=True
            )[:10]:
                lines.append(
                    f"- `{file_info['path']}` ({_human_size(file_info['size'])})"
                )
        total_size = sum(file_info["size"] for file_info in files)
        lines.append(f"\n**Total size:** {_human_size(total_size)}")
        lines.append(f"**Target directory:** `{dest_dir}`")
        lines.append(
            "\nUse `hf_download` with a `filename` parameter to download a specific file."
        )
        return json.dumps(
            {
                "success": True,
                "repo_id": repo_id,
                "files": files,
                "total_size": total_size,
                "summary": "\n".join(lines),
            }
        )

    file_size = 0
    try:
        for entry in api.list_repo_tree(repo_id, recursive=True):
            if hasattr(entry, "path") and entry.path == filename:
                file_size = getattr(entry, "size", 0)
                break
    except Exception:
        pass

    job_id = f"{repo_id}::{filename}"
    existing = _load_state(job_id)
    if existing and existing.get("status") == "complete":
        if os.path.exists(existing.get("local_path", "")):
            bar = _progress_bar(100)
            existing["summary"] = (
                f"✅ Already downloaded `{filename}` to `{existing['local_path']}` ({existing.get('size_str', '?')})\n{bar}"
            )
            existing["job_id"] = job_id
            existing["success"] = True
            return json.dumps(existing)

    local_path = os.path.join(dest_dir, filename)
    if os.path.exists(local_path) and file_size > 0:
        existing_size = os.path.getsize(local_path)
        if existing_size == file_size:
            host_uid = int(os.environ.get("HOST_UID", "0"))
            host_gid = int(os.environ.get("HOST_GID", "0"))
            _chown(local_path, host_uid, host_gid)
            job = {
                "status": "complete",
                "repo_id": repo_id,
                "filename": filename,
                "dest_dir": dest_dir,
                "total_bytes": file_size,
                "downloaded_bytes": existing_size,
                "pct": 100.0,
                "local_path": local_path,
                "size_str": _human_size(existing_size),
                "elapsed_seconds": 0,
                "speed_mbps": 0,
                "eta_seconds": 0,
                "error": None,
                "job_id": job_id,
                "success": True,
            }
            _save_state(job_id, job)
            with _downloads_lock:
                _downloads[job_id] = job
            job["summary"] = (
                f"✅ Already downloaded `{filename}` to `{local_path}` ({_human_size(existing_size)})\n{_progress_bar(100)}"
            )
            return json.dumps(job)

    job = {
        "job_id": job_id,
        "status": "downloading",
        "repo_id": repo_id,
        "filename": filename,
        "dest_dir": dest_dir,
        "total_bytes": file_size,
        "downloaded_bytes": 0,
        "pct": 0.0,
        "speed_mbps": 0.0,
        "eta_seconds": None,
        "elapsed_seconds": 0.0,
        "started_at": time.time(),
        "local_path": None,
        "size_str": None,
        "error": None,
    }
    with _downloads_lock:
        _downloads[job_id] = job
    _save_state(job_id, job)

    threading.Thread(
        target=_download_worker,
        args=(job_id, repo_id, filename, dest_dir, token, file_size),
        daemon=True,
    ).start()
    if file_size > 0:
        threading.Thread(
            target=_poll_progress,
            args=(job_id, dest_dir, filename, file_size),
            daemon=True,
        ).start()

    bar = _progress_bar(0)
    size_hint = f" ({_human_size(file_size)})" if file_size else ""
    summary = (
        f"⏳ Download started: `{filename}`{size_hint}\n{bar}\n\nJob ID: `{job_id}`"
    )
    return json.dumps(
        {
            "success": True,
            "status": "downloading",
            "job_id": job_id,
            "pct": 0.0,
            "summary": summary,
        }
    )


def hf_download_status(job_id: str = "", task_id: str = None) -> str:
    if job_id:
        with _downloads_lock:
            if job_id not in _downloads:
                saved = _load_state(job_id)
                if saved:
                    _downloads[job_id] = _refresh_job_from_disk(job_id, saved)
                else:
                    from_disk = _job_from_disk(job_id)
                    if from_disk:
                        _downloads[job_id] = from_disk
    else:
        with _downloads_lock:
            for jid, saved in _restore_all_states().items():
                if jid not in _downloads:
                    _downloads[jid] = _refresh_job_from_disk(jid, saved)

    if not job_id:
        with _downloads_lock:
            if not _downloads:
                return json.dumps(
                    {
                        "success": True,
                        "downloads": [],
                        "summary": "No active or recent downloads.",
                    }
                )
            active = [
                (jid, job)
                for jid, job in _downloads.items()
                if job.get("status") == "downloading"
            ]
            if len(active) == 1:
                job_id = active[0][0]
            elif len(_downloads) == 1:
                job_id = next(iter(_downloads.keys()))
            else:
                jobs = []
                for jid, job in sorted(
                    _downloads.items(),
                    key=lambda item: item[1].get("started_at", 0),
                    reverse=True,
                ):
                    status_emoji = {
                        "downloading": "⏳",
                        "complete": "✅",
                        "error": "❌",
                    }.get(job["status"], "❓")
                    jobs.append(
                        {
                            "job_id": jid,
                            "filename": job["filename"],
                            "status": job["status"],
                            "pct": job["pct"],
                            "summary": f"{status_emoji} `{job['filename']}` — {job['status']} {_progress_bar(job['pct'])}",
                        }
                    )
                return json.dumps(
                    {
                        "success": True,
                        "downloads": jobs,
                        "summary": "\n".join(job["summary"] for job in jobs),
                    }
                )

    job = _downloads.get(job_id)
    if not job:
        saved = _load_state(job_id)
        if saved:
            job = _refresh_job_from_disk(job_id, saved)
            _downloads[job_id] = job
        else:
            from_disk = _job_from_disk(job_id)
            if from_disk:
                job = from_disk
                _downloads[job_id] = job
    elif job:
        job = _refresh_job_from_disk(job_id, job)
        _downloads[job_id] = job

    if not job:
        return tool_error(f"Download job not found: {job_id}")

    bar = _progress_bar(job["pct"])
    speed = f" | {job.get('speed_mbps', 0)} MB/s" if job.get("speed_mbps") else ""
    eta = (
        f" | ETA {_format_eta(job.get('eta_seconds'))}"
        if job.get("eta_seconds") is not None
        else ""
    )

    if job["status"] == "downloading":
        return json.dumps(
            {
                "success": True,
                "status": "downloading",
                "job_id": job_id,
                "pct": job["pct"],
                "downloaded_bytes": job.get("downloaded_bytes", 0),
                "speed_mbps": job.get("speed_mbps", 0),
                "eta_seconds": job.get("eta_seconds"),
                "summary": f"⏳ Downloading `{job['filename']}`\n{bar}{speed}{eta}",
            }
        )

    if job["status"] == "complete":
        result = {
            k: job[k]
            for k in (
                "status",
                "repo_id",
                "filename",
                "local_path",
                "size_str",
                "pct",
                "elapsed_seconds",
                "job_id",
            )
            if k in job
        }
        result["success"] = True
        result["summary"] = (
            f"✅ Downloaded `{job['filename']}` to `{job['local_path']}` ({job['size_str']})\n{bar}"
        )
        return json.dumps(result)

    if job["status"] == "error":
        return tool_error(f"Download failed: {job['error']}")

    return json.dumps(
        {
            "success": True,
            "status": job["status"],
            "pct": job["pct"],
            "summary": f"Status: {job['status']} {bar}",
        }
    )


registry.register(
    name="hf_download",
    toolset="huggingface",
    schema={
        "name": "hf_download",
        "description": "Start downloading a model file from HuggingFace Hub. Returns immediately with a job_id. In Telegram/gateway mode, progress is monitored automatically by the gateway in the background, so do NOT keep polling hf_download_status unless the user explicitly asks for a manual status check. If no filename is given, lists available files instead.",
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
                "filename": {
                    "type": "string",
                    "description": "File to download. If omitted, lists available files.",
                },
                "target_dir": {
                    "type": "string",
                    "description": "Download directory. Defaults to MODEL_ROOT/repo_id.",
                },
            },
        },
    },
    handler=lambda args, **kw: hf_download(
        repo_id=args.get("repo_id", ""),
        url=args.get("url", ""),
        filename=args.get("filename", ""),
        target_dir=args.get("target_dir", ""),
        task_id=kw.get("task_id"),
    ),
    check_fn=lambda: True,
    emoji="📥",
)

registry.register(
    name="hf_download_status",
    toolset="huggingface",
    schema={
        "name": "hf_download_status",
        "description": "Check progress of a HuggingFace download. Use this for manual status checks or non-gateway environments. In Telegram/gateway mode, background monitoring updates the tracker automatically, so do NOT poll this repeatedly unless the user explicitly asks. Pass the job_id from hf_download. Leave empty to list all.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Download job ID from hf_download. Leave empty to list all.",
                },
            },
        },
    },
    handler=lambda args, **kw: hf_download_status(
        job_id=args.get("job_id", ""),
        task_id=kw.get("task_id"),
    ),
    check_fn=lambda: True,
    emoji="📊",
)
