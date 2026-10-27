import pytest
from microdex.cli import main, parse_args, run_session
from microdex.constants import EXEC_OUTPUT_CAP_BYTES, EXEC_TIMEOUT_SECONDS

pytestmark = pytest.mark.scaffold


def test_help_exits_cleanly():
    with pytest.raises(SystemExit) as caught:
        parse_args(["--help"])
    assert caught.value.code == 0


def test_defaults_point_at_a_local_checkpoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = parse_args(["fix this test"])
    assert args.prompt == "fix this test"
    assert args.checkpoint.as_posix() == ".microdex/checkpoints.sqlite"
    assert args.thread == ""
    assert args.model is None


def test_missing_cwd_is_a_usage_error(tmp_path):
    missing = tmp_path / "nope"
    assert main(["fix this test", "--cwd", str(missing)]) == 2


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


def test_phase1_limits_are_positive_constants():
    assert EXEC_TIMEOUT_SECONDS > 0
    assert EXEC_OUTPUT_CAP_BYTES > 0
