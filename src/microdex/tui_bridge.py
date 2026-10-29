"""JSON-lines bridge from the TypeScript TUI to the Microdex runtime."""

import argparse
import asyncio
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from importlib.metadata import PackageNotFoundError, version

from microdex.agent.graph import build_turn_graph
from microdex.client import ModelClient
from microdex.persistence.checkpointer import open_async_checkpointer
from microdex.persistence.session_index import (
    list_saved_sessions,
    load_saved_history,
    session_as_dict,
)
from microdex.runtime.thread import MicrodexThread
from microdex.runtime.thread_manager import ThreadManager


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--provider", choices=("xai", "openai"), required=True)
    parser.add_argument("--model", default=None)
    return parser.parse_args(argv)


async def serve(args: argparse.Namespace) -> int:
    cwd = args.cwd.expanduser().resolve()
    checkpoint = args.checkpoint.expanduser().resolve()
    if not cwd.is_dir():
        _write({"type": "bridge_error", "message": f"Directory not found: {cwd}"})
        return 2

    model_client = ModelClient(model=args.model, provider=args.provider)
    try:
        package_version = version("microdex")
    except PackageNotFoundError:
        package_version = "development"

    async with open_async_checkpointer(checkpoint) as saver:
        # This graph is used only for checkpoint reads. Live sessions are always
        # created by ThreadManager and all user operations still enter SessionIo.
        history_graph = build_turn_graph(model_client, checkpointer=saver)
        manager = ThreadManager(model_client, checkpointer=saver)
        active_thread: MicrodexThread | None = None
        event_tasks: set[asyncio.Task[None]] = set()

        async def send_sessions(target_cwd: Path) -> None:
            sessions = await list_saved_sessions(history_graph, checkpoint, target_cwd)
            _write(
                {
                    "type": "sessions_loaded",
                    "cwd": str(target_cwd.expanduser().resolve()),
                    "sessions": [session_as_dict(item) for item in sessions],
                }
            )

        async def start_session(
            target_cwd: Path,
            thread_id: str | None = None,
        ) -> None:
            nonlocal active_thread
            active_thread = await manager.create_thread(target_cwd, thread_id=thread_id)
            history = await load_saved_history(history_graph, active_thread.id)
            task = asyncio.create_task(_forward_events(active_thread))
            event_tasks.add(task)
            task.add_done_callback(event_tasks.discard)
            _write(
                {
                    "type": "session_loaded",
                    "session": history,
                    "title": _session_title(history.get("history", [])),
                }
            )

        await send_sessions(cwd)
        _write(
            {
                "type": "ready",
                "cwd": str(cwd),
                "checkpoint": str(checkpoint),
                "provider": model_client.provider,
                "model": model_client.model,
                "version": package_version,
            }
        )

        try:
            while True:
                line = await asyncio.to_thread(sys.stdin.readline)
                if not line:
                    break
                request: Any = None
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError("request must be a JSON object")
                    op = request.get("op")
                    if op == "list_sessions":
                        target_cwd = Path(request.get("cwd") or cwd).expanduser().resolve()
                        await send_sessions(target_cwd)
                    elif op == "start_session":
                        target_cwd = Path(request.get("cwd") or cwd).expanduser().resolve()
                        await start_session(target_cwd, request.get("thread_id"))
                    elif op == "submit":
                        if active_thread is None:
                            raise RuntimeError("Start or resume a session before sending input")
                        submission_id = await active_thread.start_turn(str(request.get("text") or ""))
                        _write({"type": "submitted", "submission_id": submission_id})
                    elif op == "interrupt":
                        if active_thread is not None:
                            await active_thread.interrupt()
                    elif op == "approval_decision":
                        if active_thread is None:
                            raise RuntimeError("There is no active session")
                        await active_thread.approve_tool(
                            str(request.get("tool_call_id") or ""),
                            bool(request.get("approved")),
                        )
                    elif op == "create_worktree":
                        name = str(request.get("name") or "task")
                        worktree_cwd, branch = _create_worktree(cwd, name)
                        _write(
                            {
                                "type": "worktree_created",
                                "cwd": str(worktree_cwd),
                                "branch": branch,
                            }
                        )
                        await start_session(worktree_cwd)
                    elif op == "changelog":
                        _write({"type": "changelog_loaded", "lines": _changelog(cwd)})
                    elif op == "quit":
                        break
                    else:
                        raise ValueError(f"unknown operation: {op}")
                except Exception as exc:
                    _write(
                        {
                            "type": "bridge_error",
                            "op": request.get("op") if isinstance(request, dict) else "",
                            "message": str(exc),
                        }
                    )
        finally:
            await manager.shutdown_all()
            if event_tasks:
                await asyncio.gather(*event_tasks, return_exceptions=True)
    return 0


async def _forward_events(thread: MicrodexThread) -> None:
    while True:
        event = await thread.next_event()
        _write({"type": "event", "event": event})
        if event["kind"] == "session_closed":
            return


def _create_worktree(cwd: Path, name: str) -> tuple[Path, str]:
    root_result = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if root_result.returncode != 0:
        raise RuntimeError("New Worktree requires a Git repository")
    root = Path(root_result.stdout.strip()).resolve()
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip()).strip("-._") or "task"
    slug = slug[:40]
    branch = f"microdex/{slug}-{stamp}"
    target = Path.home() / ".microdex" / "worktrees" / root.name / f"{slug}-{stamp}"
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "-b", branch, str(target), "HEAD"],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "git worktree add failed"
        raise RuntimeError(message)
    return target, branch


def _changelog(cwd: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(cwd), "log", "-8", "--pretty=format:%h  %s"],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.splitlines()
    return ["No changelog is available in this directory."]


def _session_title(history: object) -> str:
    if not isinstance(history, list):
        return "New session"
    for message in history:
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content", "")
            if isinstance(content, str) and content.strip():
                return content.strip().splitlines()[0][:120]
    return "New session"


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(serve(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
