import pytest
from pydantic import ValidationError
from microdex.schemas import ReadFileArgs, UnknownTool, parse_arguments
from microdex.tools.registry import tool_names, tool_specs

pytestmark = pytest.mark.scaffold


def test_phase1_tool_names():
    assert tool_names() == ["read_file", "rg", "apply_patch", "exec_command"]
    assert [spec["function"]["name"] for spec in tool_specs()] == tool_names()


def test_parse_arguments_accepts_a_read_and_rejects_a_gap():
    parsed = parse_arguments({"name": "read_file", "arguments": {"path": "a.py"}})
    assert parsed == ReadFileArgs(path="a.py")
    with pytest.raises(ValidationError):
        parse_arguments({"name": "exec_command", "arguments": {}})
    with pytest.raises(UnknownTool):
        parse_arguments({"name": "web_search", "arguments": {}})
