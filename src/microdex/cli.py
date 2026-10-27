"""Line-oriented client for the Microdex session runtime."""

import argparse
import asyncio
import os
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

from microdex.client import ModelClient
from microdex.oauth import OAuthError, auth_path, delete_auth, login
from microdex.persistence.checkpointer import open_async_checkpointer
from microdex.runtime.protocol import EventMsg
from microdex.runtime.thread import MicrodexThread
from microdex.runtime.thread_manager import ThreadManager


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Codex-style coding-agent session with a submission loop."
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="Run one task and exit. Omit to open an interactive session.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        help="Working directory given to the tools",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path(".microdex/checkpoints.sqlite"),
        help="SQLite file for LangGraph checkpoints",
    )
    parser.add_argument(
        "--thread",
        default="",
        help="Conversation id. Reuse it to continue checkpointed history.",
    )
    parser.add_argument("--model", default=None, help="Model name")
    return parser.parse_args(argv)


def print_event(event: EventMsg) -> None:
    kind = event["kind"]
    if kind == "agent_message_content_delta":
        print(event["text"], end="", flush=True)
    elif kind == "tool_start":
        print(f"\n[tool] {event['tool_name']}", file=sys.stderr)
    elif kind == "tool_end":
        status = "ok" if event["ok"] else "error"
        print(f"[tool] {event['tool_name']} {status}", file=sys.stderr)
    elif kind == "input_queued":
        print("[input queued for the active turn]", file=sys.stderr)
    elif kind == "error":
        print(f"\n[error] {event['text']}", file=sys.stderr)
    elif kind == "turn_aborted":
        reason = event.get("reason", "aborted")
        print(f"\n[turn aborted: {reason}]", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    _load_dotenv(Path(".env"))
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list[:1] in (["debug"], ["debug-loop"]):
        from microdex.debug_walkthrough import main as debug_main

        return debug_main(args_list[1:])
    if args_list[:1] == ["login"]:
        return _login()
    if args_list[:1] == ["logout"]:
        return _logout()

    args = parse_args(args_list)
    cwd = args.cwd.expanduser().resolve()
    if not cwd.is_dir():
        print(f"Working directory not found: {cwd}", file=sys.stderr)
        return 2
    try:
        return asyncio.run(_run(args, cwd))
    except KeyboardInterrupt:
        print("\n[interrupted]", file=sys.stderr)
        return 130


async def _run(args: argparse.Namespace, cwd: Path) -> int:
    thread_id = args.thread or uuid.uuid4().hex
    model_client = ModelClient(model=args.model)
    async with open_async_checkpointer(args.checkpoint) as saver:
        manager = ThreadManager(model_client, checkpointer=saver)
        thread = await manager.create_thread(cwd, thread_id=thread_id)
        try:
            if args.prompt is not None:
                return 0 if await submit_and_render(thread, args.prompt) else 1
            return await interactive_session(thread)
        finally:
            await manager.shutdown_all()


async def submit_and_render(thread: MicrodexThread, text: str) -> bool:
    """Submit through SessionIo and render until that RegularTask terminates."""

    submission_id = await thread.start_turn(text)
    printed_text = False
    while True:
        event = await thread.next_event()
        print_event(event)
        printed_text = printed_text or (event["kind"] == "agent_message_content_delta")
        if (
            event["kind"] in {"turn_completed", "turn_aborted"}
            and event["submission_id"] == submission_id
        ):
            if printed_text:
                print()
            return event["kind"] == "turn_completed"


async def interactive_session(thread: MicrodexThread) -> int:
    print(f"thread {thread.id}", file=sys.stderr)
    print("empty line is ignored, /exit quits", file=sys.stderr)
    while True:
        try:
            line = await asyncio.to_thread(input, "› ")
        except EOFError:
            print(file=sys.stderr)
            return 0
        text = line.strip()
        if not text:
            continue
        if text in {"/exit", "/quit"}:
            return 0
        try:
            await submit_and_render(thread, text)
        except KeyboardInterrupt:
            await thread.interrupt()


def run_session(
    on_turn: Callable[[str], None],
    thread_id: str,
    read_line: Callable[[str], str] = input,
) -> int:
    """Compatibility helper for synchronous embedding.

    The production CLI above uses ThreadManager and SessionIo. This helper
    remains for small callers that already provide their own submission
    callback.
    """

    print(f"thread {thread_id}", file=sys.stderr)
    print("empty line is ignored, /exit quits", file=sys.stderr)
    while True:
        try:
            line = read_line("› ")
        except EOFError:
            print(file=sys.stderr)
            return 0
        except KeyboardInterrupt:
            print(file=sys.stderr)
            return 0
        text = line.strip()
        if not text:
            continue
        if text in {"/exit", "/quit"}:
            return 0
        try:
            on_turn(text)
        except KeyboardInterrupt:
            print("\n[interrupted]", file=sys.stderr)
        except Exception as exc:
            print(f"\n[error] {exc}", file=sys.stderr)


def _login() -> int:
    try:
        path = login()
    except OAuthError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Signed in. Saved {path}", file=sys.stderr)
    return 0


def _logout() -> int:
    if delete_auth():
        print(f"Removed {auth_path()}", file=sys.stderr)
    else:
        print("No saved login.", file=sys.stderr)
    return 0


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
