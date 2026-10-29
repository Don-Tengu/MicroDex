"""Deterministic, offline walkthrough of the complete Microdex loop."""

import argparse
import asyncio
import tempfile
import threading
from pathlib import Path

from microdex.client import ScriptedModelClient
from microdex.events import Emit
from microdex.persistence.checkpointer import open_async_checkpointer
from microdex.runtime.protocol import EventMsg
from microdex.runtime.thread import MicrodexThread
from microdex.runtime.thread_manager import ThreadManager
from microdex.schemas import ModelOutcome, Prompt, ToolCall

INITIAL_SOURCE = """def greet(name: str) -> str:
    return f"hello {name}"
"""

PATCH = """*** Begin Patch
*** Update File: hello.py
@@
-    return f"hello {name}"
+    return f"HELLO {name}"
*** End Patch
"""

FIRST_PROMPT = "Change greet() to return an uppercase greeting and verify it."
STEERING_PROMPT = (
    "Also preserve the function signature and show the verification result."
)


class WalkthroughModelClient(ScriptedModelClient):
    """Scripted client with a gate that makes steering deterministic."""

    def __init__(self) -> None:
        super().__init__(
            [
                ModelOutcome(
                    text="I will inspect the implementation first.",
                    tool_calls=[
                        ToolCall(
                            id="read-1",
                            name="read_file",
                            arguments={"path": "hello.py"},
                        ),
                        ToolCall(
                            id="search-1",
                            name="rg",
                            arguments={"pattern": "return", "path": "."},
                        ),
                    ],
                ),
                ModelOutcome(
                    text="The signature can stay unchanged. I will update the return value.",
                    tool_calls=[
                        ToolCall(
                            id="patch-1",
                            name="apply_patch",
                            arguments={"patch": PATCH},
                        )
                    ],
                ),
                ModelOutcome(
                    text="The edit is in place. I will execute a focused verification.",
                    tool_calls=[
                        ToolCall(
                            id="exec-1",
                            name="exec_command",
                            arguments={
                                "cmd": (
                                    "grep -Fq 'return f\"HELLO {name}\"' "
                                    "hello.py && printf 'HELLO Codex\\n'"
                                )
                            },
                        )
                    ],
                ),
                ModelOutcome(
                    text=(
                        "Done. The function signature is unchanged and the "
                        "verification printed HELLO Codex."
                    )
                ),
            ]
        )
        self.prompts: list[Prompt] = []
        self.first_request_started = threading.Event()
        self.release_first_request = threading.Event()

    def complete(self, prompt: Prompt, emit: Emit) -> ModelOutcome:
        self.prompts.append(prompt.model_copy(deep=True))
        if len(self.prompts) == 1:
            self.first_request_started.set()
            if not self.release_first_request.wait(timeout=10):
                raise RuntimeError(
                    "debug walkthrough timed out at the first model gate"
                )
        return super().complete(prompt, emit)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Walk through submission_loop, RegularTask, and run_turn offline."
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        help="Wait for Enter between architecture stages.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Use an empty directory instead of a temporary workspace.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\nWalkthrough interrupted.")
        return 130
    except Exception as exc:
        print(f"\nWalkthrough failed: {exc}")
        return 1


async def _run(args: argparse.Namespace) -> int:
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if args.workspace is None:
        temporary = tempfile.TemporaryDirectory(prefix="microdex-walkthrough-")
        workspace = Path(temporary.name)
    else:
        workspace = args.workspace.expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        if any(workspace.iterdir()):
            raise RuntimeError(f"debug workspace must be empty: {workspace}")

    try:
        return await _walkthrough(workspace, pause=args.pause)
    finally:
        if temporary is not None:
            temporary.cleanup()


async def _walkthrough(workspace: Path, *, pause: bool) -> int:
    (workspace / "hello.py").write_text(INITIAL_SOURCE, encoding="utf-8")
    client = WalkthroughModelClient()
    checkpoint = workspace / "checkpoints.sqlite"

    print("\nMicrodex Agent Loop Walkthrough")
    print(f"workspace: {workspace}")
    print("network: disabled; model: WalkthroughModelClient\n")

    async with open_async_checkpointer(checkpoint) as saver:
        manager = ThreadManager(client, checkpointer=saver)
        thread: MicrodexThread | None = None
        try:
            await _stage(
                1,
                "ThreadManager creates one MicrodexThread, Session, "
                "SessionIo, and submission_loop.",
                pause,
            )
            thread = await manager.create_thread(
                workspace,
                thread_id="debug-thread",
            )
            print(f"   thread id: {thread.id}")
            print("   active task: None")

            await _stage(
                2,
                "The client submits TurnInput. It does not call LangGraph.",
                pause,
            )
            first_id = await thread.start_turn(FIRST_PROMPT)
            print(f"   submission id: {first_id}")
            await _consume_until(
                thread,
                lambda event: (
                    event["kind"] == "turn_started"
                    and event["submission_id"] == first_id
                ),
            )

            first_started = await asyncio.to_thread(
                client.first_request_started.wait,
                5,
            )
            if not first_started:
                raise RuntimeError("first model request did not start")

            await _stage(
                3,
                "While run_turn is sampling, submit another prompt. "
                "submission_loop routes it to InputQueue.",
                pause,
            )
            steering_id = await thread.start_turn(STEERING_PROMPT)
            print(f"   steering submission id: {steering_id}")
            await _consume_until(
                thread,
                lambda event: (
                    event["kind"] == "input_queued"
                    and event["submission_id"] == steering_id
                ),
            )

            await _stage(
                4,
                "Release the model. run_turn now performs complete tool "
                "batches, merges pending input, and resamples.",
                pause,
            )
            client.release_first_request.set()
            terminal_ids: set[str] = set()
            while terminal_ids != {first_id, steering_id}:
                event = await _next_event(thread)
                _show_event(event)
                if event["kind"] in {"turn_completed", "turn_aborted"}:
                    terminal_ids.add(event["submission_id"])

            await _stage(
                5,
                "Inspect checkpointed history and the requests seen by the model.",
                pause,
            )
            snapshot = await thread.session.graph.aget_state(
                thread.session.graph_config
            )
            history = snapshot.values["history"]
            _show_requests(client.prompts)
            _show_history(history)

            print("\nFinal hello.py:")
            print((workspace / "hello.py").read_text(encoding="utf-8"))
            print("Walkthrough complete.")
            return 0
        finally:
            client.release_first_request.set()
            await manager.shutdown_all()


async def _stage(number: int, text: str, pause: bool) -> None:
    print(f"\n[{number}] {text}")
    if pause:
        await asyncio.to_thread(input, "    Press Enter to continue...")


async def _next_event(thread: MicrodexThread) -> EventMsg:
    event = await asyncio.wait_for(thread.next_event(), timeout=15)
    if event["kind"] == "tool_approval_requested":
        # This deterministic walkthrough intentionally acts as the approving
        # client so it can demonstrate mutating tools without an interactive UI.
        await thread.approve_tool(event["tool_call_id"], True)
    return event


async def _consume_until(thread: MicrodexThread, predicate) -> EventMsg:
    while True:
        event = await _next_event(thread)
        _show_event(event)
        if predicate(event):
            return event


def _show_event(event: EventMsg) -> None:
    kind = event["kind"]
    if kind == "agent_message_content_delta":
        detail = event["text"]
    elif kind in {"tool_start", "tool_end"}:
        detail = (
            f"{event['tool_name']} call_id={event['tool_call_id']} ok={event['ok']}"
        )
    elif kind == "tool_approval_requested":
        arguments = event.get("tool_arguments", {})
        detail = f"{event['tool_name']} call_id={event['tool_call_id']} args={arguments}"
    elif kind == "input_queued":
        detail = f"submission={event['submission_id']}"
    elif kind in {"turn_started", "turn_completed", "turn_aborted"}:
        detail = f"turn={event['turn_id'] or '-'} submission={event['submission_id']}"
    else:
        detail = event["text"] or event.get("reason", "")
    print(f"   EVENT {kind:<31} {detail}")


def _show_requests(prompts: list[Prompt]) -> None:
    print("\nModel requests:")
    for number, prompt in enumerate(prompts, start=1):
        roles = [message["role"] for message in prompt.messages]
        user_texts = [
            str(message.get("content", ""))
            for message in prompt.messages
            if message["role"] == "user"
        ]
        print(f"   request {number}: roles={roles}")
        print(f"              user_inputs={user_texts}")


def _show_history(history: list[dict]) -> None:
    print("\nFinal checkpoint history:")
    for index, message in enumerate(history, start=1):
        role = message["role"]
        call_id = message.get("tool_call_id") or ""
        calls = [
            f"{call['name']}:{call['id']}" for call in message.get("tool_calls", [])
        ]
        content = message.get("content", "").replace("\n", "\\n")
        if len(content) > 100:
            content = content[:97] + "..."
        extras = f" call_id={call_id}" if call_id else ""
        if calls:
            extras += f" calls={calls}"
        print(f"   {index:02d}. {role:<9}{extras} content={content!r}")


if __name__ == "__main__":
    raise SystemExit(main())
