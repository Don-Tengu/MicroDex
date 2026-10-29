import asyncio

import pytest
from microdex.cli import (
    _default_checkpoint_path,
    interactive_session,
    main,
    parse_args,
    run_session,
)
from microdex.constants import EXEC_OUTPUT_CAP_BYTES, EXEC_TIMEOUT_SECONDS

pytestmark = pytest.mark.scaffold


def test_help_exits_cleanly():
    with pytest.raises(SystemExit) as caught:
        parse_args(["--help"])
    assert caught.value.code == 0


def test_exec_defaults_to_a_local_checkpoint_outside_git_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = parse_args(["exec", "fix this test"])
    assert args.prompt == "fix this test"
    assert args.checkpoint is None
    assert _default_checkpoint_path(args.cwd) == (
        tmp_path / ".microdex" / "checkpoints.sqlite"
    )
    assert args.thread == ""
    assert args.model is None
    assert args.provider == "xai"


def test_provider_can_be_selected_explicitly():
    args = parse_args(["--provider", "openai", "--model", "gpt-test"])
    assert args.provider == "openai"
    assert args.model == "gpt-test"


def test_missing_cwd_is_a_usage_error(tmp_path):
    missing = tmp_path / "nope"
    assert main(["exec", "fix this test", "--cwd", str(missing)]) == 2


def test_no_prompt_opens_a_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = parse_args([])
    assert args.prompt is None


def test_session_keeps_reading_until_exit():
    lines = iter(["fix this test", "", "run it again", "/exit"])
    seen = []

    def read_line(_prompt: str) -> str:
        return next(lines)

    assert run_session(seen.append, "thread-a", read_line) == 0
    assert seen == ["fix this test", "run it again"]


def test_session_stays_open_when_a_turn_fails():
    lines = iter(["first", "second", "/quit"])
    seen = []

    def read_line(_prompt: str) -> str:
        return next(lines)

    def on_turn(text: str) -> None:
        seen.append(text)
        if text == "first":
            raise RuntimeError("model failed")

    assert run_session(on_turn, "thread-a", read_line) == 0
    assert seen == ["first", "second"]


def test_interactive_cli_submits_steering_before_current_turn_finishes():
    class FakeThread:
        id = "thread-a"

        def __init__(self):
            self.started = []
            self.interrupts = 0

        async def start_turn(self, text):
            self.started.append(text)
            return f"submission-{len(self.started)}"

        async def interrupt(self):
            self.interrupts += 1
            return "interrupt"

        async def next_event(self):
            await asyncio.Future()

    lines = iter(["first", "steering", "/interrupt", "/exit"])
    thread = FakeThread()

    def read_line(_prompt):
        return next(lines)

    assert asyncio.run(interactive_session(thread, read_line=read_line)) == 0
    assert thread.started == ["first", "steering"]
    assert thread.interrupts == 1


def test_interactive_cli_routes_approval_through_its_single_input_loop(monkeypatch):
    class FakeThread:
        id = "thread-a"

        def __init__(self):
            self.events = asyncio.Queue()
            self.approvals = []

        async def start_turn(self, text):
            if text == "first":
                await self.events.put(
                    {
                        "kind": "tool_approval_requested",
                        "thread_id": self.id,
                        "turn_id": "turn-a",
                        "submission_id": "",
                        "text": "",
                        "tool_name": "exec_command",
                        "tool_call_id": "exec-1",
                        "tool_arguments": {"cmd": "printf ok"},
                        "cwd": "/tmp/project",
                        "ok": False,
                    }
                )
                await asyncio.sleep(0)
            return "submission"

        async def approve_tool(self, tool_call_id, approved):
            self.approvals.append((tool_call_id, approved))
            return "approval-submission"

        async def interrupt(self):
            return "interrupt"

        async def next_event(self):
            return await self.events.get()

    class Tty:
        def isatty(self):
            return True

    monkeypatch.setattr("sys.stdin", Tty())
    lines = iter(["first", "/approve", "/exit"])
    thread = FakeThread()

    def read_line(_prompt):
        return next(lines)

    assert asyncio.run(interactive_session(thread, read_line=read_line)) == 0
    assert thread.approvals == [("exec-1", True)]


def test_phase1_limits_are_positive_constants():
    assert EXEC_TIMEOUT_SECONDS > 0
    assert EXEC_OUTPUT_CAP_BYTES > 0
