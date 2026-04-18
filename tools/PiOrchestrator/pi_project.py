#!/usr/bin/env python3
"""
Pi Project Orchestration Tool

Manages long-running coding projects via:
- persistent project state on disk
- Beads as durable task graph (epics, child tasks, comments)
- background Pi execution inside the shared /workspace scratch area

Tools:
  pi_project_start    - Start and run a new project with a plan
  pi_project_status   - Get status of running/completed projects
  pi_project_comment  - Add a comment/feedback to a running project
  pi_project_cancel   - Cancel a running project
"""

import json
import logging
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


STATE_PENDING = "pending"
STATE_PLANNING = "planning"
STATE_RUNNING = "running"
STATE_BLOCKED = "blocked"
STATE_COMPLETE = "complete"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"

TERMINAL_STATES = {STATE_COMPLETE, STATE_FAILED, STATE_CANCELLED}
ACTIVE_STATES = {STATE_PENDING, STATE_PLANNING, STATE_RUNNING, STATE_BLOCKED}

_projects_lock = threading.Lock()
_projects: Dict[str, Dict[str, Any]] = {}
_workers: Dict[str, threading.Thread] = {}
_running_processes: Dict[str, subprocess.Popen] = {}

_PI_CONTAINER = os.getenv("PI_CONTAINER", "pi")
_PI_WORKDIR = os.getenv("PI_WORKDIR", "/workspace")
_PROJECT_ROOT = Path(os.getenv("PI_PROJECT_ROOT", "/workspace/code"))
_PROJECT_STATE_FILE = Path(
    os.getenv("PI_PROJECT_STATE_FILE", "/workspace/.hermes/pi-projects.json")
)
_MAX_PI_ATTEMPTS = int(os.getenv("PI_PROJECT_MAX_ATTEMPTS", "3"))


def _now() -> float:
    return time.time()


def _ensure_state_parent() -> None:
    _PROJECT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def _persist_projects_locked() -> None:
    _ensure_state_parent()
    payload = {
        "version": 1,
        "projects": _projects,
    }
    tmp_path = _PROJECT_STATE_FILE.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(_PROJECT_STATE_FILE)


def _sanitize_project_dir(title: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", title or "")
    if not tokens:
        return f"Project{str(uuid.uuid4())[:8]}"
    return "".join(token[:1].upper() + token[1:] for token in tokens)


def _truncate(text: str, limit: int = 1200) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _project_dir_for_title(title: str) -> Path:
    return _PROJECT_ROOT / _sanitize_project_dir(title)


def _compute_progress(plan_items: List[Dict[str, Any]]) -> float:
    if not plan_items:
        return 100.0
    completed = sum(1 for item in plan_items if item.get("state") == STATE_COMPLETE)
    return round((completed / len(plan_items)) * 100.0, 1)


def _normalize_plan_items(raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    previous_beads_id = None
    for index, raw in enumerate(raw_items):
        title = str(raw.get("title") or raw.get("content") or f"Step {index + 1}").strip()
        content = str(raw.get("content") or title).strip()
        normalized.append(
            {
                "id": str(raw.get("id") or f"step-{index + 1}"),
                "title": title,
                "content": content,
                "state": str(raw.get("state") or STATE_PENDING),
                "beads_id": raw.get("beads_id"),
                "depends_on": raw.get("depends_on") or previous_beads_id,
                "started_at": raw.get("started_at"),
                "completed_at": raw.get("completed_at"),
                "last_output": raw.get("last_output", ""),
            }
        )
        previous_beads_id = normalized[-1]["beads_id"]
    return normalized


def _save_project(project: Dict[str, Any]) -> None:
    with _projects_lock:
        _projects[project["project_id"]] = project
        _persist_projects_locked()


def _load_projects() -> None:
    if not _PROJECT_STATE_FILE.exists():
        return
    try:
        payload = json.loads(_PROJECT_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("failed to load project state: %s", exc)
        return
    projects = payload.get("projects") if isinstance(payload, dict) else {}
    if not isinstance(projects, dict):
        return
    with _projects_lock:
        _projects.clear()
        for project_id, project in projects.items():
            if not isinstance(project, dict):
                continue
            project["project_id"] = project_id
            project["plan_items"] = _normalize_plan_items(project.get("plan_items", []))
            if project.get("state") in {STATE_PLANNING, STATE_RUNNING}:
                for item in project["plan_items"]:
                    if item.get("state") == STATE_RUNNING:
                        item["state"] = STATE_PENDING
                project["state"] = STATE_PENDING
            project["progress_pct"] = _compute_progress(project["plan_items"])
            _projects[project_id] = project


def _get_project(project_id: str) -> Optional[Dict[str, Any]]:
    with _projects_lock:
        project = _projects.get(project_id)
        if not project:
            return None
        return json.loads(json.dumps(project))


def _update_project(project_id: str, mutator) -> Optional[Dict[str, Any]]:
    with _projects_lock:
        project = _projects.get(project_id)
        if not project:
            return None
        mutator(project)
        project["updated_at"] = _now()
        project["progress_pct"] = _compute_progress(project.get("plan_items", []))
        _persist_projects_locked()
        return json.loads(json.dumps(project))


def _find_project_by_title(project_id: str, title: str) -> Optional[str]:
    existing = _bd_json(["list", "--json"])
    if not existing:
        return None
    expected = f"[project:{project_id}] {title}"
    for item in existing:
        if item.get("title") == expected:
            return item.get("id")
    return None


def _bd(cmd_parts: List[str], project_dir: Optional[str] = None) -> str:
    env = os.environ.copy()
    cwd = project_dir or "/workspace/host"
    try:
        result = subprocess.run(
            ["bd"] + cmd_parts,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
            env=env,
        )
        if result.returncode != 0:
            logger.warning("bd %s failed: %s", cmd_parts[0], result.stderr.strip())
        return result.stdout
    except Exception as exc:
        logger.warning("bd %s error: %s", cmd_parts[0], exc)
        return ""


def _bd_json(cmd_parts: List[str], project_dir: Optional[str] = None) -> Any:
    out = _bd(cmd_parts, project_dir)
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def _ensure_beads_project(project: Dict[str, Any]) -> Optional[str]:
    epic_id = project.get("epic_id")
    if epic_id:
        return epic_id
    epic_id = _find_project_by_title(project["project_id"], project["title"])
    if epic_id:
        _update_project(project["project_id"], lambda p: p.__setitem__("epic_id", epic_id))
        return epic_id
    out = _bd(
        [
            "create",
            "--title",
            f"[project:{project['project_id']}] {project['title']}",
            "--type",
            "epic",
            "--json",
        ]
    )
    if not out:
        return None
    try:
        epic_id = json.loads(out).get("id")
    except json.JSONDecodeError:
        epic_id = None
    if epic_id:
        if project.get("description"):
            _bd(["comment", epic_id, project["description"]])
        _update_project(project["project_id"], lambda p: p.__setitem__("epic_id", epic_id))
    return epic_id


def _ensure_beads_tasks(project: Dict[str, Any]) -> None:
    epic_id = _ensure_beads_project(project)
    if not epic_id:
        return
    project = _get_project(project["project_id"]) or project

    previous_task_id = None
    for index, item in enumerate(project.get("plan_items", [])):
        if not item.get("beads_id"):
            out = _bd(
                [
                    "create",
                    "--title",
                    item.get("title") or f"Step {index + 1}",
                    "--type",
                    "task",
                    "--json",
                ]
            )
            if out:
                try:
                    item["beads_id"] = json.loads(out).get("id")
                except json.JSONDecodeError:
                    item["beads_id"] = None
            if item.get("beads_id"):
                _bd(["link", epic_id, item["beads_id"], "--type", "parent-child"])
                if previous_task_id:
                    _bd(["link", previous_task_id, item["beads_id"], "--type", "blocks"])
                item["depends_on"] = previous_task_id
        previous_task_id = item.get("beads_id") or previous_task_id

    _save_project(project)


def _update_beads_state(beads_id: Optional[str], state: str) -> None:
    if not beads_id:
        return
    status_map = {
        STATE_PENDING: "todo",
        STATE_PLANNING: "todo",
        STATE_RUNNING: "in_progress",
        STATE_BLOCKED: "blocked",
        STATE_COMPLETE: "closed",
        STATE_FAILED: "blocked",
        STATE_CANCELLED: "closed",
    }
    _bd(["update", beads_id, "--status", status_map.get(state, "todo")])


def _append_beads_comment(beads_id: Optional[str], comment: str) -> None:
    if beads_id and comment:
        _bd(["comment", beads_id, comment])


def _format_project_summary(project: Dict[str, Any]) -> str:
    state_icons = {
        STATE_PENDING: "⏳",
        STATE_PLANNING: "📋",
        STATE_RUNNING: "🔄",
        STATE_BLOCKED: "⏸️",
        STATE_COMPLETE: "✅",
        STATE_FAILED: "❌",
        STATE_CANCELLED: "⛔",
    }
    icon = state_icons.get(project["state"], "❓")
    lines = [f"**{icon} Project: {project['title']}**"]
    lines.append(f"ID: `{project['project_id']}`")
    lines.append(f"State: {project['state']}")
    lines.append(f"Workspace: `{project['project_dir']}`")

    plan = project.get("plan_items", [])
    if plan:
        lines.append("")
        for item in plan:
            item_state = item.get("state", STATE_PENDING)
            item_icon = {
                STATE_COMPLETE: "✅",
                STATE_RUNNING: "🔄",
                STATE_FAILED: "❌",
                STATE_CANCELLED: "⛔",
                STATE_BLOCKED: "⏸️",
            }.get(item_state, "⬜")
            lines.append(f"{item_icon} {item.get('title', '?')}")

    progress = project.get("progress_pct", 0.0)
    filled = int(20 * progress / 100.0)
    lines.append("")
    lines.append(f"[{'#' * filled}{'.' * (20 - filled)}] {progress:.1f}%")

    report = str(project.get("last_report") or "").strip()
    if report:
        lines.append("")
        lines.append(_truncate(report, 800))

    comments = project.get("comments") or []
    if comments:
        lines.append("")
        lines.append("Comments:")
        for comment in comments[-3:]:
            text = comment["text"] if isinstance(comment, dict) else str(comment)
            lines.append(f"- {_truncate(text, 160)}")

    error = str(project.get("error") or "").strip()
    if error:
        lines.append("")
        lines.append(f"Error: {_truncate(error, 300)}")

    return "\n".join(lines)


def _build_task_prompt(project: Dict[str, Any], item: Dict[str, Any]) -> str:
    comment_lines = []
    for comment in project.get("comments", [])[-5:]:
        if isinstance(comment, dict):
            comment_lines.append(f"- {comment.get('text', '').strip()}")
        else:
            comment_lines.append(f"- {str(comment).strip()}")
    comment_block = "\n".join(line for line in comment_lines if line.strip())
    prompt = f"""
You are working inside the correct project directory already.

Rules:
- Treat the current working directory as the project root.
- Only create, edit, read, or run files from the current working directory.
- Do not write files in /workspace root or parent directories.
- Prefer direct file edits and normal shell commands inside this directory.
- Keep changes focused to the requested step.

Project title: {project['title']}
Project description:
{project.get('description', '').strip()}

Current step: {item.get('title', '').strip()}
Step details:
{item.get('content', '').strip()}
""".strip()
    if comment_block:
        prompt += f"\n\nLatest user feedback:\n{comment_block}"
    prompt += "\n\nWhen done, briefly summarize what you changed and any verification you ran."
    return prompt


def _run_pi_task(project_id: str, task_prompt: str, cwd: str) -> Dict[str, Any]:
    cmd = [
        "docker",
        "exec",
        "-i",
        "-w",
        cwd,
        _PI_CONTAINER,
        "pi",
        "--provider",
        "local-qwopus",
        "--model",
        "qwopus-pi",
        "--no-session",
        "-p",
        task_prompt,
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _running_processes[project_id] = proc
    started = time.monotonic()
    stdout = ""
    stderr = ""
    try:
        while True:
            if proc.poll() is not None:
                stdout, stderr = proc.communicate(timeout=5)
                break
            project = _get_project(project_id)
            if project and project.get("cancel_requested"):
                proc.terminate()
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout, stderr = proc.communicate(timeout=5)
                return {
                    "success": False,
                    "cancelled": True,
                    "output": (stdout or "").strip(),
                    "error": (stderr or "Cancelled by user").strip(),
                }
            if (time.monotonic() - started) > 1800:
                proc.kill()
                stdout, stderr = proc.communicate(timeout=5)
                return {
                    "success": False,
                    "cancelled": False,
                    "output": (stdout or "").strip(),
                    "error": "Task timed out after 30 minutes",
                }
            time.sleep(1.0)
    finally:
        _running_processes.pop(project_id, None)

    return {
        "success": proc.returncode == 0,
        "cancelled": False,
        "output": (stdout or "").strip(),
        "error": (stderr or "").strip() if proc.returncode != 0 else None,
    }


def _is_retryable_pi_error(result: Dict[str, Any]) -> bool:
    if result.get("cancelled"):
        return False
    combined = " ".join(
        str(part or "")
        for part in (result.get("error"), result.get("output"))
    ).lower()
    retry_markers = (
        "503 loading model",
        "loading model",
        "connection refused",
        "timed out",
        "temporarily unavailable",
    )
    return any(marker in combined for marker in retry_markers)


def _set_item_state(project_id: str, item_id: str, state: str, last_output: str = "") -> Optional[Dict[str, Any]]:
    def mutator(project: Dict[str, Any]) -> None:
        for item in project.get("plan_items", []):
            if item.get("id") != item_id:
                continue
            item["state"] = state
            if state == STATE_RUNNING:
                item["started_at"] = _now()
                project["current_task_id"] = item_id
            if state in TERMINAL_STATES or state == STATE_COMPLETE:
                item["completed_at"] = _now()
            if last_output:
                item["last_output"] = _truncate(last_output, 1200)
            if item.get("beads_id"):
                _update_beads_state(item["beads_id"], state)
                if last_output:
                    _append_beads_comment(item["beads_id"], _truncate(last_output, 1200))
            break

    return _update_project(project_id, mutator)


def _set_project_state(project_id: str, state: str, error: str = "", report: str = "") -> Optional[Dict[str, Any]]:
    def mutator(project: Dict[str, Any]) -> None:
        project["state"] = state
        if state in TERMINAL_STATES:
            project["current_task_id"] = None
        if error:
            project["error"] = _truncate(error, 1200)
        if report:
            project["last_report"] = _truncate(report, 1200)
        if project.get("epic_id"):
            _update_beads_state(project["epic_id"], state)
            if error:
                _append_beads_comment(project["epic_id"], _truncate(error, 1200))
            if report:
                _append_beads_comment(project["epic_id"], _truncate(report, 1200))

    return _update_project(project_id, mutator)


def _execute_project(project_id: str) -> None:
    project = _get_project(project_id)
    if not project:
        return

    _PROJECT_ROOT.mkdir(parents=True, exist_ok=True)
    Path(project["project_dir"]).mkdir(parents=True, exist_ok=True)

    project = _set_project_state(project_id, STATE_PLANNING, report="Project created and queued for Pi execution.")
    if not project:
        return
    _ensure_beads_tasks(project)

    for item in project.get("plan_items", []):
        fresh = _get_project(project_id)
        if not fresh:
            return
        if fresh.get("cancel_requested"):
            _set_project_state(project_id, STATE_CANCELLED, report="Project cancelled before next step.")
            return
        if item.get("state") == STATE_COMPLETE:
            continue

        _set_item_state(project_id, item["id"], STATE_RUNNING)
        _set_project_state(project_id, STATE_RUNNING, report=f"Running: {item['title']}")

        result = None
        for attempt in range(1, _MAX_PI_ATTEMPTS + 1):
            result = _run_pi_task(project_id, _build_task_prompt(fresh, item), fresh["project_dir"])
            if result.get("success") or result.get("cancelled") or not _is_retryable_pi_error(result):
                break
            _set_project_state(
                project_id,
                STATE_RUNNING,
                report=f"Waiting for Pi model availability before retrying {item['title']} (attempt {attempt + 1}/{_MAX_PI_ATTEMPTS}).",
            )
            time.sleep(min(15, 5 * attempt))

        if result.get("cancelled"):
            _set_item_state(project_id, item["id"], STATE_CANCELLED, result.get("error", "Cancelled"))
            _set_project_state(project_id, STATE_CANCELLED, report="Project cancelled during execution.")
            return

        if not result.get("success"):
            _set_item_state(project_id, item["id"], STATE_FAILED, result.get("error") or result.get("output") or "Pi task failed")
            _set_project_state(
                project_id,
                STATE_FAILED,
                error=result.get("error") or "Pi task failed",
                report=result.get("output") or "",
            )
            return

        _set_item_state(project_id, item["id"], STATE_COMPLETE, result.get("output") or "Completed")
        _set_project_state(project_id, STATE_RUNNING, report=result.get("output") or f"Completed: {item['title']}")

    _set_project_state(project_id, STATE_COMPLETE, report="All plan items completed.")


def _ensure_worker(project_id: str) -> None:
    existing = _workers.get(project_id)
    if existing and existing.is_alive():
        return
    worker = threading.Thread(target=_execute_project, args=(project_id,), daemon=True)
    _workers[project_id] = worker
    worker.start()


def _resume_projects() -> None:
    with _projects_lock:
        pending_ids = [
            project_id
            for project_id, project in _projects.items()
            if project.get("state") in ACTIVE_STATES and not project.get("cancel_requested")
        ]
    for project_id in pending_ids:
        _ensure_worker(project_id)


def pi_project_start(
    title: str,
    description: str = "",
    plan: str = "",
    chat_id: Optional[str] = None,
    session_key: Optional[str] = None,
    task_id: str = None,
) -> str:
    project_id = str(uuid.uuid4())[:8]

    plan_items: List[Dict[str, Any]] = []
    if plan:
        try:
            parsed = json.loads(plan)
            if isinstance(parsed, list):
                plan_items = parsed
            elif isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
                plan_items = parsed["items"]
            else:
                plan_items = [{"title": str(plan).strip(), "content": str(plan).strip()}]
        except json.JSONDecodeError:
            plan_items = [{"title": str(plan).strip(), "content": str(plan).strip()}]
    if not plan_items:
        seed = description.strip() or title.strip()
        plan_items = [{"title": seed or "Implement project", "content": seed or "Implement project"}]

    project_dir = _project_dir_for_title(title)
    project = {
        "project_id": project_id,
        "title": title,
        "description": description,
        "state": STATE_PENDING,
        "created_at": _now(),
        "updated_at": _now(),
        "chat_id": chat_id,
        "session_key": session_key,
        "project_dir": str(project_dir),
        "plan_items": _normalize_plan_items(plan_items),
        "current_task_id": None,
        "comments": [],
        "progress_pct": 0.0,
        "error": "",
        "last_report": "",
        "cancel_requested": False,
        "epic_id": None,
    }
    _save_project(project)
    _ensure_worker(project_id)

    created = _get_project(project_id) or project
    return json.dumps(
        {
            "success": True,
            "project_id": project_id,
            "title": title,
            "state": created["state"],
            "project_dir": created["project_dir"],
            "plan_items": len(created["plan_items"]),
            "summary": _format_project_summary(created),
        }
    )


def pi_project_status(project_id: str = "", task_id: str = None) -> str:
    if project_id:
        project = _get_project(project_id)
        if not project:
            return json.dumps({"success": False, "error": f"Project not found: {project_id}"})
        return json.dumps(
            {
                "success": True,
                "project_id": project_id,
                "state": project["state"],
                "progress_pct": project.get("progress_pct", 0.0),
                "project_dir": project.get("project_dir", ""),
                "plan_items": project.get("plan_items", []),
                "summary": _format_project_summary(project),
            }
        )

    with _projects_lock:
        all_projects = list(_projects.values())

    if not all_projects:
        return json.dumps({"success": True, "summary": "No projects found."})

    summaries = []
    for project in sorted(all_projects, key=lambda item: item.get("created_at", 0), reverse=True):
        summaries.append(
            f"{project['project_id']} {project['title']} ({project['state']}) {project.get('progress_pct', 0.0):.1f}%"
        )
    return json.dumps({"success": True, "projects": len(all_projects), "summary": "\n".join(summaries)})


def pi_project_comment(project_id: str, comment: str, task_id: str = None) -> str:
    text = str(comment or "").strip()
    if not text:
        return json.dumps({"success": False, "error": "Comment cannot be empty"})

    def mutator(project: Dict[str, Any]) -> None:
        comments = project.setdefault("comments", [])
        comments.append({"timestamp": _now(), "text": text})
        if project.get("epic_id"):
            _append_beads_comment(project["epic_id"], text)
        current_task_id = project.get("current_task_id")
        if current_task_id:
            for item in project.get("plan_items", []):
                if item.get("id") == current_task_id and item.get("beads_id"):
                    _append_beads_comment(item["beads_id"], text)
                    break

    project = _update_project(project_id, mutator)
    if not project:
        return json.dumps({"success": False, "error": f"Project not found: {project_id}"})

    return json.dumps(
        {
            "success": True,
            "project_id": project_id,
            "state": project["state"],
            "summary": _format_project_summary(project),
        }
    )


def pi_project_cancel(project_id: str, task_id: str = None) -> str:
    def mutator(project: Dict[str, Any]) -> None:
        if project.get("state") in TERMINAL_STATES:
            return
        project["cancel_requested"] = True
        project["state"] = STATE_CANCELLED
        project["last_report"] = "Cancellation requested."
        if project.get("epic_id"):
            _update_beads_state(project["epic_id"], STATE_CANCELLED)

    project = _update_project(project_id, mutator)
    if not project:
        return json.dumps({"success": False, "error": f"Project not found: {project_id}"})

    proc = _running_processes.get(project_id)
    if proc and proc.poll() is None:
        proc.terminate()

    return json.dumps(
        {
            "success": True,
            "project_id": project_id,
            "state": STATE_CANCELLED,
            "summary": _format_project_summary(project),
        }
    )


_load_projects()
_resume_projects()


try:
    from tools.registry import registry

    registry.register(
        name="pi_project_start",
        toolset="pi-orchestrator",
        schema={
            "name": "pi_project_start",
            "description": (
                "Start a persistent long-running coding project managed by Pi. "
                "The project runs in /workspace/code/<ProjectName> and keeps state on disk."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short project title shown in the tracker",
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed project description and context",
                    },
                    "plan": {
                        "type": "string",
                        "description": "JSON array of plan items: [{title, content}, ...]",
                    },
                },
                "required": ["title"],
            },
        },
        handler=lambda args, **kw: pi_project_start(
            title=args.get("title", ""),
            description=args.get("description", ""),
            plan=args.get("plan", ""),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
    )

    registry.register(
        name="pi_project_status",
        toolset="pi-orchestrator",
        schema={
            "name": "pi_project_status",
            "description": "Get the status of a Pi project, or list all projects.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID from pi_project_start. Omit to list all.",
                    },
                },
            },
        },
        handler=lambda args, **kw: pi_project_status(
            project_id=args.get("project_id", ""),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
    )

    registry.register(
        name="pi_project_comment",
        toolset="pi-orchestrator",
        schema={
            "name": "pi_project_comment",
            "description": "Add a comment or user feedback to a running Pi project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID to comment on",
                    },
                    "comment": {
                        "type": "string",
                        "description": "Comment text or user feedback",
                    },
                },
                "required": ["project_id", "comment"],
            },
        },
        handler=lambda args, **kw: pi_project_comment(
            project_id=args.get("project_id", ""),
            comment=args.get("comment", ""),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
    )

    registry.register(
        name="pi_project_cancel",
        toolset="pi-orchestrator",
        schema={
            "name": "pi_project_cancel",
            "description": "Cancel a running Pi project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID to cancel",
                    },
                },
                "required": ["project_id"],
            },
        },
        handler=lambda args, **kw: pi_project_cancel(
            project_id=args.get("project_id", ""),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
    )

except ImportError:
    pass
