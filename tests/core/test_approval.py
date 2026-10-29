import asyncio
import io

import pytest

from microdex.client import ScriptedModelClient
from microdex.cli import submit_and_render
from microdex.runtime.thread_manager import ThreadManager
from microdex.schemas import ModelOutcome, ToolCall

pytestmark = pytest.mark.core

PATCH = """*** Begin Patch
*** Add File: created.txt
+hello
*** End Patch
"""


async def _next_event(thread, kind):
    while True:
        event = await asyncio.wait_for(thread.next_event(), timeout=3)
        if event["kind"] == kind:
            return event


def test_mutating_tool_waits_for_approval_and_denial_is_recoverable(tmp_path):
    async def run():
        class RecordingClient(ScriptedModelClient):
            def __init__(self):
                super().__init__(
                    [
                        ModelOutcome(
                            tool_calls=[
                                ToolCall(
                                    id="patch-1",
                                    name="apply_patch",
                                    arguments={"patch": PATCH},
                                )
                            ]
                        ),
                        ModelOutcome(text="I will leave the file unchanged."),
                    ]
                )
                self.prompts = []

            def complete(self, prompt, emit):
                self.prompts.append(prompt)
                return super().complete(prompt, emit)

        client = RecordingClient()
        manager = ThreadManager(client)
        thread = await manager.create_thread(tmp_path, thread_id="approval-deny")
        try:
            submission_id = await thread.start_turn("create a file")
            request = await _next_event(thread, "tool_approval_requested")
            assert request["tool_name"] == "apply_patch"
            assert request["tool_arguments"] == {"patch": PATCH}
            assert not (tmp_path / "created.txt").exists()

            await thread.approve_tool(request["tool_call_id"], False)
            while True:
                event = await asyncio.wait_for(thread.next_event(), timeout=3)
                if (
                    event["kind"] == "turn_completed"
                    and event["submission_id"] == submission_id
                ):
                    break

            assert not (tmp_path / "created.txt").exists()
            assert any(
                message["role"] == "tool"
                and message["tool_call_id"] == "patch-1"
                and "declined" in message["content"]
                for message in client.prompts[1].messages
            )
        finally:
            await manager.shutdown_all()

    asyncio.run(run())


def test_approved_patch_executes(tmp_path):
    async def run():
        client = ScriptedModelClient(
            [
                ModelOutcome(
                    tool_calls=[
                        ToolCall(
                            id="patch-approved",
                            name="apply_patch",
                            arguments={"patch": PATCH},
                        )
                    ]
                ),
                ModelOutcome(text="created"),
            ]
        )
        manager = ThreadManager(client)
        thread = await manager.create_thread(tmp_path, thread_id="approval-allow")
        try:
            submission_id = await thread.start_turn("create a file")
            request = await _next_event(thread, "tool_approval_requested")
            await thread.approve_tool(request["tool_call_id"], True)
            while True:
                event = await asyncio.wait_for(thread.next_event(), timeout=3)
                if (
                    event["kind"] == "turn_completed"
                    and event["submission_id"] == submission_id
                ):
                    break
            assert (tmp_path / "created.txt").read_text(encoding="utf-8") == "hello\n"
        finally:
            await manager.shutdown_all()

    asyncio.run(run())


def test_approval_during_interrupt_fails_closed(tmp_path):
    async def run():
        client = ScriptedModelClient(
            [
                ModelOutcome(
                    tool_calls=[
                        ToolCall(
                            id="exec-1",
                            name="exec_command",
                            arguments={"cmd": "printf ran > ran.txt"},
                        )
                    ]
                )
            ]
        )
        manager = ThreadManager(client)
        thread = await manager.create_thread(tmp_path, thread_id="approval-interrupt")
        try:
            submission_id = await thread.start_turn("run a command")
            await _next_event(thread, "tool_approval_requested")
            await thread.interrupt()
            while True:
                event = await asyncio.wait_for(thread.next_event(), timeout=3)
                if (
                    event["kind"] == "turn_aborted"
                    and event["submission_id"] == submission_id
                ):
                    break
            assert not (tmp_path / "ran.txt").exists()
        finally:
            await manager.shutdown_all()

    asyncio.run(run())


def test_shutdown_during_approval_fails_closed(tmp_path):
    async def run():
        client = ScriptedModelClient(
            [
                ModelOutcome(
                    tool_calls=[
                        ToolCall(
                            id="exec-shutdown",
                            name="exec_command",
                            arguments={"cmd": "printf ran > ran.txt"},
                        )
                    ]
                )
            ]
        )
        manager = ThreadManager(client)
        thread = await manager.create_thread(tmp_path, thread_id="approval-shutdown")
        await thread.start_turn("run a command")
        await _next_event(thread, "tool_approval_requested")

        await manager.shutdown_all()
        assert not (tmp_path / "ran.txt").exists()

    asyncio.run(run())


def test_read_tool_does_not_request_approval(tmp_path):
    async def run():
        (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
        client = ScriptedModelClient(
            [
                ModelOutcome(
                    tool_calls=[
                        ToolCall(
                            id="read-1",
                            name="read_file",
                            arguments={"path": "hello.txt"},
                        )
                    ]
                ),
                ModelOutcome(text="read it"),
            ]
        )
        manager = ThreadManager(client)
        thread = await manager.create_thread(tmp_path, thread_id="approval-read")
        try:
            submission_id = await thread.start_turn("read it")
            saw_approval = False
            while True:
                event = await asyncio.wait_for(thread.next_event(), timeout=3)
                saw_approval |= event["kind"] == "tool_approval_requested"
                if (
                    event["kind"] == "turn_completed"
                    and event["submission_id"] == submission_id
                ):
                    break
            assert not saw_approval
        finally:
            await manager.shutdown_all()

    asyncio.run(run())


def test_one_shot_cli_denies_approval_without_tty(tmp_path, monkeypatch):
    async def run():
        client = ScriptedModelClient(
            [
                ModelOutcome(
                    tool_calls=[
                        ToolCall(
                            id="patch-1",
                            name="apply_patch",
                            arguments={"patch": PATCH},
                        )
                    ]
                ),
                ModelOutcome(text="The patch was declined."),
            ]
        )
        manager = ThreadManager(client)
        thread = await manager.create_thread(tmp_path, thread_id="approval-no-tty")
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        try:
            assert await submit_and_render(thread, "create a file") is True
            assert not (tmp_path / "created.txt").exists()
        finally:
            await manager.shutdown_all()

    asyncio.run(run())
