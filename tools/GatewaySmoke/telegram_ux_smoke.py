#!/usr/bin/env python3
"""
Reusable Telegram UX smoke harness for Hermes gateway flows.

Runs the real gateway message handler against a fake Telegram adapter that:
- preserves Telegram-oriented send/edit behavior
- logs user-visible outbound content as JSONL
- optionally auto-approves the synthetic user for pairing bypass

Intended to run inside the hermes-api container.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from gateway.config import Platform, load_gateway_config
from gateway.pairing import PairingStore
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    SendResult,
)
from gateway.run import GatewayRunner
from gateway.session import SessionSource


DEFAULT_LOG_PATH = Path("/workspace/.hermes/logs/telegram-ux.jsonl")
DEFAULT_PRINT_CATEGORIES = {"SYSTEM", "SEND", "EDIT", "PROJECT", "FINAL"}


class FakeTelegramAdapter(BasePlatformAdapter):
    SUPPORTS_MESSAGE_EDITING = True

    def __init__(self, config, log_path: Path, print_categories: set[str]):
        super().__init__(config, Platform.TELEGRAM)
        self._next_id = 1
        self._log_path = log_path
        self._print_categories = print_categories

    async def connect(self) -> bool:
        self._mark_connected()
        self._log("SYSTEM", "fake telegram adapter connected")
        return True

    async def disconnect(self) -> None:
        self._mark_disconnected()
        self._log("SYSTEM", "fake telegram adapter disconnected")

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        return {"id": chat_id, "type": "private", "title": "Telegram UX Smoke"}

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        message_id = self._alloc_message_id()
        self._log(
            "SEND",
            content,
            chat_id=chat_id,
            reply_to=reply_to,
            metadata=metadata,
            message_id=message_id,
        )
        return SendResult(success=True, message_id=message_id)

    async def edit_message(
        self,
        chat_id: str,
        message_id: str,
        content: str,
    ) -> SendResult:
        self._log(
            "EDIT",
            content,
            chat_id=chat_id,
            message_id=message_id,
        )
        return SendResult(success=True, message_id=message_id)

    async def send_typing(
        self,
        chat_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._log("TYPING", "typing", chat_id=chat_id, metadata=metadata)

    def _alloc_message_id(self) -> str:
        message_id = f"msg-{self._next_id}"
        self._next_id += 1
        return message_id

    def _log(self, category: str, content: str, **extra: Any) -> None:
        record = {
            "ts": round(time.time(), 3),
            "category": category,
            "content": content,
        }
        record.update(extra)
        line = json.dumps(record, ensure_ascii=False)
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        if category in self._print_categories:
            print(line, flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", help="User prompt to send through the Telegram UX harness")
    parser.add_argument(
        "--log-path",
        default=str(DEFAULT_LOG_PATH),
        help="JSONL log file written inside hermes-api",
    )
    parser.add_argument(
        "--print-categories",
        default="SYSTEM,SEND,EDIT,PROJECT,FINAL",
        help="Comma-separated categories echoed to stdout",
    )
    parser.add_argument(
        "--include-typing",
        action="store_true",
        help="Also print TYPING entries to stdout",
    )
    parser.add_argument(
        "--chat-id",
        default="telegram-ux-smoke-chat",
        help="Synthetic Telegram chat id",
    )
    parser.add_argument(
        "--user-id",
        default="telegram-ux-smoke-user",
        help="Synthetic Telegram user id",
    )
    parser.add_argument(
        "--user-name",
        default="Telegram UX Smoke",
        help="Synthetic Telegram user name",
    )
    parser.add_argument(
        "--message-id",
        default="telegram-ux-smoke-message",
        help="Synthetic inbound Telegram message id",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Max seconds to wait for terminal project state",
    )
    parser.add_argument(
        "--project-detect-timeout",
        type=int,
        default=120,
        help="Max seconds to wait for Hermes to create a Pi project",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Pre-approve the synthetic Telegram user in the pairing store",
    )
    parser.add_argument(
        "--no-auto-approve",
        action="store_false",
        dest="auto_approve",
        help="Do not pre-approve the synthetic Telegram user",
    )
    parser.add_argument(
        "--keep-log",
        action="store_true",
        help="Append to the existing log instead of truncating it",
    )
    parser.set_defaults(auto_approve=True)
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    log_path = Path(args.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not args.keep_log:
        log_path.write_text("", encoding="utf-8")

    print_categories = {
        token.strip().upper()
        for token in str(args.print_categories).split(",")
        if token.strip()
    }
    if args.include_typing:
        print_categories.add("TYPING")

    if args.auto_approve:
        PairingStore()._approve_user("telegram", args.user_id, args.user_name)

    runner = GatewayRunner(load_gateway_config())
    adapter = FakeTelegramAdapter(
        runner.config.platforms[Platform.TELEGRAM],
        log_path=log_path,
        print_categories=print_categories,
    )
    adapter.set_message_handler(runner._handle_message)
    adapter.set_fatal_error_handler(runner._handle_adapter_fatal_error)
    adapter.set_session_store(runner.session_store)
    adapter.set_busy_session_handler(runner._handle_active_session_busy_message)
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._sync_voice_mode_state_to_adapter(adapter)
    await adapter.connect()

    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id=args.chat_id,
        chat_type="dm",
        user_id=args.user_id,
        user_name=args.user_name,
        chat_name="Telegram UX Smoke",
    )
    event = MessageEvent(
        text=args.prompt,
        message_type=MessageType.TEXT,
        source=source,
        message_id=args.message_id,
    )

    start_ts = time.time()
    await adapter.handle_message(event)
    adapter._log("SYSTEM", "prompt dispatched", prompt=args.prompt)

    project_id = await _detect_project_id(
        adapter=adapter,
        start_ts=start_ts,
        detect_timeout=args.project_detect_timeout,
    )
    if not project_id:
        adapter._log("FINAL", "no pi project detected", prompt=args.prompt)
        await adapter.disconnect()
        return 1

    terminal_status = await _wait_for_terminal_project_state(
        adapter=adapter,
        project_id=project_id,
        timeout=args.timeout,
    )
    await adapter.disconnect()
    return 0 if terminal_status in {"complete", "failed", "cancelled"} else 1


async def _detect_project_id(
    adapter: FakeTelegramAdapter,
    start_ts: float,
    detect_timeout: int,
) -> Optional[str]:
    state_path = Path("/workspace/.hermes/pi-projects.json")
    deadline = time.time() + detect_timeout
    while time.time() < deadline:
        if state_path.exists():
            try:
                payload = json.loads(state_path.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
            projects = payload.get("projects", {}) if isinstance(payload, dict) else {}
            candidates = []
            for project_id, project in projects.items():
                if project.get("created_at", 0) >= start_ts - 1:
                    candidates.append((project.get("created_at", 0), project_id, project))
            if candidates:
                _, project_id, project = sorted(candidates)[-1]
                adapter._log(
                    "PROJECT",
                    "project detected",
                    project_id=project_id,
                    title=project.get("title"),
                    state=project.get("state"),
                )
                return project_id
        await asyncio.sleep(2)
    return None


async def _wait_for_terminal_project_state(
    adapter: FakeTelegramAdapter,
    project_id: str,
    timeout: int,
) -> str:
    from PiOrchestrator.pi_project import pi_project_status

    deadline = time.time() + timeout
    last_state = None
    while time.time() < deadline:
        status = json.loads(pi_project_status(project_id, None))
        state = str(status.get("state") or "")
        if state != last_state:
            adapter._log(
                "PROJECT",
                "project state changed",
                project_id=project_id,
                state=state,
                progress_pct=status.get("progress_pct"),
            )
            last_state = state
        if state in {"complete", "failed", "cancelled"}:
            adapter._log(
                "FINAL",
                "project terminal",
                project_id=project_id,
                state=state,
                summary=status.get("summary", ""),
                latest_architecture=status.get("latest_architecture", {}),
            )
            return state
        await asyncio.sleep(10)
    adapter._log("FINAL", "timeout waiting for project terminal state", project_id=project_id)
    return "timeout"


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
