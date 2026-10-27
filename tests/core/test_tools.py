"""Tool runtime. These fail until the functions in `microdex.tools` are filled in."""

import pytest
from microdex import constants
from microdex.tools.registry import execute_tool

pytestmark = pytest.mark.core

ADD_PATCH = """*** Begin Patch
*** Add File: created.txt
+hello
*** End Patch
"""

UPDATE_PATCH = """*** Begin Patch
*** Update File: hello.py
@@
-print("bad")
+print("good")
*** End Patch
"""

DELETE_PATCH = """*** Begin Patch
*** Delete File: created.txt
*** End Patch
"""


def _call(name: str, arguments: dict, call_id: str = "1") -> dict:
    return {"id": call_id, "name": name, "arguments": arguments}


def test_read_file_returns_the_text(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    result = execute_tool(_call("read_file", {"path": "a.txt"}), str(tmp_path))
    assert result == {"ok": True, "output": "hello\n"}


def test_missing_file_is_a_tool_error(tmp_path):
    result = execute_tool(_call("read_file", {"path": "missing.txt"}), str(tmp_path))
    assert result["ok"] is False
    assert "missing.txt" in result["output"]


def test_invalid_arguments_are_a_tool_error(tmp_path):
    result = execute_tool(_call("read_file", {}), str(tmp_path))
    assert result["ok"] is False


def test_unknown_tool_is_a_tool_error(tmp_path):
    result = execute_tool(_call("web_search", {}), str(tmp_path))
    assert result["ok"] is False


def test_rg_finds_a_line_and_treats_no_match_as_success(tmp_path):
    (tmp_path / "notes.txt").write_text("microdex-needle\n", encoding="utf-8")
    found = execute_tool(_call("rg", {"pattern": "microdex-needle"}), str(tmp_path))
    assert found["ok"] is True
    assert "notes.txt" in found["output"]
    assert "microdex-needle" in found["output"]
    missing = execute_tool(_call("rg", {"pattern": "nowhere-token"}), str(tmp_path))
    assert missing["ok"] is True
    assert "nowhere-token" not in missing["output"]


def test_apply_patch_add_update_and_delete(tmp_path):
    added = execute_tool(_call("apply_patch", {"patch": ADD_PATCH}), str(tmp_path))
    assert added["ok"] is True
    assert (tmp_path / "created.txt").read_text(encoding="utf-8") == "hello\n"

    (tmp_path / "hello.py").write_text('print("bad")\n', encoding="utf-8")
    updated = execute_tool(_call("apply_patch", {"patch": UPDATE_PATCH}), str(tmp_path))
    assert updated["ok"] is True
    assert (tmp_path / "hello.py").read_text(encoding="utf-8") == 'print("good")\n'

    removed = execute_tool(_call("apply_patch", {"patch": DELETE_PATCH}), str(tmp_path))
    assert removed["ok"] is True
    assert not (tmp_path / "created.txt").exists()


def test_apply_patch_mismatch_does_not_write(tmp_path):
    target = tmp_path / "hello.py"
    target.write_text('print("other")\n', encoding="utf-8")
    result = execute_tool(_call("apply_patch", {"patch": UPDATE_PATCH}), str(tmp_path))
    assert result["ok"] is False
    assert target.read_text(encoding="utf-8") == 'print("other")\n'


def test_exec_command_runs_in_cwd_and_keeps_stderr(tmp_path):
    result = execute_tool(
        _call("exec_command", {"cmd": "printf out; printf err >&2"}),
        str(tmp_path),
    )
    assert result == {"ok": True, "output": "outerr"}


def test_exec_command_nonzero_is_a_tool_error(tmp_path):
    result = execute_tool(_call("exec_command", {"cmd": "exit 3"}), str(tmp_path))
    assert result["ok"] is False


def test_exec_command_uses_the_timeout_constant(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "EXEC_TIMEOUT_SECONDS", 0.2)
    result = execute_tool(_call("exec_command", {"cmd": "sleep 5"}), str(tmp_path))
    assert result["ok"] is False
    assert "timeout" in result["output"].lower()


def test_exec_command_uses_the_output_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "EXEC_OUTPUT_CAP_BYTES", 4)
    result = execute_tool(
        _call("exec_command", {"cmd": "printf abcdefghij"}),
        str(tmp_path),
    )
    assert result == {"ok": True, "output": "abcd" + constants.TRUNCATION_MARKER}
