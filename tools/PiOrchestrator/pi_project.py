#!/usr/bin/env python3
"""
Pi Project Orchestration Tool

Manages long-running coding projects via:
- In-memory project store (gateway-polled for tracker updates)
- Beads as durable task graph (epics, child tasks, dependencies, comments)
- Pi delegation for actual coding work

Tools:
  pi_project_start    - Start a new project with a plan
  pi_project_status   - Get status of running/completed projects
  pi_project_comment  - Add a comment/feedback to a running project
  pi_project_cancel   - Cancel a running project
"""

import json
import logging
import os
import subprocess
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory project store (gateway-polled for status; Beads is the durable store)
# ---------------------------------------------------------------------------

_projects_lock = threading.Lock()
_projects: Dict[str, Dict[str, Any]] = {}

# Project states
STATE_PENDING = "pending"
STATE_PLANNING = "planning"
STATE_RUNNING = "running"
STATE_BLOCKED = "blocked"
STATE_COMPLETE = "complete"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"

TERMINAL_STATES = {STATE_COMPLETE, STATE_FAILED, STATE_CANCELLED}

_PI_CONTAINER = os.getenv("PI_CONTAINER", "pi")
_PI_WORKDIR = os.getenv("PI_WORKDIR", "/workspace")

# ---------------------------------------------------------------------------
# Beads helpers
# ---------------------------------------------------------------------------


def _bd(cmd_parts: List[str], project_dir: Optional[str] = None) -> str:
    """Run a bd command and return stdout."""
    env = os.environ.copy()
    cwd = project_dir or "/workspace"
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
    except Exception as e:
        logger.warning("bd %s error: %s", cmd_parts[0], e)
        return ""


def _bd_json(cmd_parts: List[str], project_dir: Optional[str] = None) -> Any:
    """Run a bd command and parse JSON output."""
    out = _bd(cmd_parts, project_dir)
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def _ensure_beads_project(project_id: str, title: str, description: str = "") -> Optional[str]:
    """Create a Beads epic for the project if it doesn't exist. Returns the epic ID."""
    existing = _bd_json(["list", "--json"])
    if existing:
        for item in existing:
            if item.get("title") == f"[project:{project_id}] {title}":
                return item.get("id")
    out = _bd(["create", "--title", f"[project:{project_id}] {title}", "--type", "epic", "--json"])
    if out:
        try:
            return json.loads(out).get("id")
        except json.JSONDecodeError:
            pass
    return None


def _add_beads_task(
    project_id: str,
    title: str,
    depends_on: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Optional[str]:
    """Add a child task to the project epic in Beads."""
    out = _bd(["create", "--title", title, "--type", "task", "--json"])
    if not out:
        return None
    try:
        created = json.loads(out)
        tid = created.get("id")
        if not tid:
            return None
        if depends_on:
            _bd(["link", depends_on, tid, "--type", "blocks"])
        return tid
    except json.JSONDecodeError:
        return None


def _update_beads_task_state(task_id: str, state: str) -> None:
    """Update a Beads task's status."""
    status_map = {
        STATE_PENDING: "todo",
        STATE_PLANNING: "todo",
        STATE_RUNNING: "in_progress",
        STATE_BLOCKED: "blocked",
        STATE_COMPLETE: "closed",
        STATE_FAILED: "blocked",
        STATE_CANCELLED: "cancelled",
    }
    beads_status = status_map.get(state, "todo")
    _bd(["update", task_id, "--status", beads_status])


def _add_beads_comment(task_id: str, comment: str) -> None:
    """Add a comment to a Beads task."""
    _bd(["comment", task_id, comment])


# ---------------------------------------------------------------------------
# Project management
# ---------------------------------------------------------------------------


def _create_project(
    project_id: str,
    title: str,
    description: str,
    plan_items: Optional[List[Dict[str, Any]]] = None,
    chat_id: Optional[str] = None,
    session_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new project and persist to Beads."""
    project = {
        "project_id": project_id,
        "title": title,
        "description": description,
        "state": STATE_PENDING,
        "created_at": time.time(),
        "updated_at": time.time(),
        "chat_id": chat_id,
        "session_key": session_key,
        "plan_items": plan_items or [],
        "current_task": None,
        "completed_tasks": [],
        "comments": [],
        "progress_pct": 0.0,
        "error": None,
    }
    with _projects_lock:
        _projects[project_id] = project

    epic_id = _ensure_beads_project(project_id, title, description)

    if plan_items and epic_id:
        for item in plan_items:
            tid = _add_beads_task(
                project_id,
                item.get("title", item.get("content", "Untitled task")),
                depends_on=None,
                task_id=item.get("id"),
            )
            if tid:
                item["beads_id"] = tid
                _bd(["link", epic_id, tid, "--type", "parent-child"])

    return project


def _get_project(project_id: str) -> Optional[Dict[str, Any]]:
    with _projects_lock:
        return _projects.get(project_id)


def _update_project_state(project_id: str, **kwargs) -> Optional[Dict[str, Any]]:
    with _projects_lock:
        project = _projects.get(project_id)
        if not project:
            return None
        project.update(kwargs)
        project["updated_at"] = time.time()
        return project


def _format_project_summary(project: Dict[str, Any]) -> str:
    """Format a project into a tracker-compatible summary."""
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
            }.get(item_state, "⬜")
            lines.append(f"{item_icon} {item.get('title', item.get('content', '?'))}")

    progress = project.get("progress_pct", 0.0)
    filled = int(20 * progress / 100.0)
    lines.append("")
    lines.append(f"[{'█' * filled}{'░' * (20 - filled)}] {progress:.1f}%")

    if project.get("error"):
        lines.append("")
        lines.append(f"⚠️ {project['error']}")

    if project.get("comments"):
        lines.append("")
        lines.append("Comments:")
        for c in project["comments"][-3:]:
            lines.append(f"  • {c}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pi delegation helpers
# ---------------------------------------------------------------------------


def _run_pi_task(project_id: str, task_prompt: str) -> Dict[str, Any]:
    """Delegate a task to Pi and return the result."""
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "-w",
                _PI_WORKDIR,
                _PI_CONTAINER,
                "pi",
                "--provider",
                "local-qwopus",
                "--model",
                "qwopus-pi",
                "--no-session",
                "-p",
                task_prompt,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout.strip(),
            "error": result.stderr.strip() if result.returncode != 0 else None,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "Task timed out (10min)"}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def pi_project_start(
    title: str,
    description: str = "",
    plan: str = "",
    chat_id: Optional[str] = None,
    session_key: Optional[str] = None,
    task_id: str = None,
) -> str:
    """Start a new Pi project with an optional plan."""
    project_id = str(uuid.uuid4())[:8]

    plan_items = []
    if plan:
        try:
            parsed = json.loads(plan)
            if isinstance(parsed, list):
                plan_items = parsed
            elif isinstance(parsed, dict) and "items" in parsed:
                plan_items = parsed["items"]
            else:
                plan_items = [{"title": plan, "state": STATE_PENDING}]
        except json.JSONDecodeError:
            plan_items = [{"title": plan, "state": STATE_PENDING}]

    project = _create_project(
        project_id,
        title,
        description,
        plan_items,
        chat_id=chat_id,
        session_key=session_key,
    )

    return json.dumps(
        {
            "success": True,
            "project_id": project_id,
            "title": title,
            "state": project["state"],
            "plan_items": len(plan_items),
            "summary": _format_project_summary(project),
        }
    )


def pi_project_status(project_id: str = "", task_id: str = None) -> str:
    """Get status of one or all projects."""
    if project_id:
        project = _get_project(project_id)
        if not project:
            return json.dumps(
                {"success": False, "error": f"Project not found: {project_id}"}
            )
        return json.dumps(
            {
                "success": True,
                "project_id": project_id,
                "state": project["state"],
                "progress_pct": project.get("progress_pct", 0.0),
                "plan_items": project.get("plan_items", []),
                "summary": _format_project_summary(project),
            }
        )

    with _projects_lock:
        all_projects = list(_projects.values())

    if not all_projects:
        return json.dumps({"success": True, "summary": "No active projects."})

    summaries = []
    for p in sorted(all_projects, key=lambda x: x.get("created_at", 0), reverse=True):
        icon = {"complete": "✅", "failed": "❌", "cancelled": "⛔"}.get(
            p["state"], "🔄"
        )
        summaries.append(f"{icon} `{p['project_id']}` — {p['title']} ({p['state']})")

    return json.dumps(
        {
            "success": True,
            "projects": len(all_projects),
            "summary": "\n".join(summaries),
        }
    )


def pi_project_comment(project_id: str, comment: str, task_id: str = None) -> str:
    """Add a comment to a running project."""
    project = _get_project(project_id)
    if not project:
        return json.dumps(
            {"success": False, "error": f"Project not found: {project_id}"}
        )

    comments = project.setdefault("comments", [])
    comments.append(comment)
    _update_project_state(project_id, comments=comments)

    return json.dumps(
        {
            "success": True,
            "project_id": project_id,
            "summary": f"Comment added to project {project_id}",
        }
    )


def pi_project_cancel(project_id: str, task_id: str = None) -> str:
    """Cancel a running project."""
    project = _get_project(project_id)
    if not project:
        return json.dumps(
            {"success": False, "error": f"Project not found: {project_id}"}
        )

    if project["state"] in TERMINAL_STATES:
        return json.dumps(
            {
                "success": False,
                "error": f"Project is already in terminal state: {project['state']}",
            }
        )

    _update_project_state(project_id, state=STATE_CANCELLED)

    return json.dumps(
        {
            "success": True,
            "project_id": project_id,
            "state": STATE_CANCELLED,
            "summary": f"Project {project_id} cancelled",
        }
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

try:
    from tools.registry import registry

    registry.register(
        name="pi_project_start",
        toolset="pi-orchestrator",
        schema={
            "name": "pi_project_start",
            "description": (
                "Start a new long-running coding project managed by Pi. "
                "Returns a project_id and a summary suitable for the gateway tracker. "
                "The plan should be a JSON array of {title, content} items, or a single task description."
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
                        "description": (
                            "JSON array of plan items: [{title, content}, ...] "
                            "or a single task description if no plan is needed"
                        ),
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
            "description": (
                "Get the status of a Pi project. "
                "Omit project_id to list all active projects."
            ),
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
            "description": (
                "Add a comment or user feedback to a running Pi project. "
                "Use this to route user replies into the live task."
            ),
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
    pass  # Registry not available outside hermes-agent context
