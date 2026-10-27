"""One scripted turn: read, run, answer. Fails until the seams work together."""

import pytest
from microdex.agent.graph import build_turn_graph
from microdex.agent.state import initial_state
from microdex.client import ScriptedModelClient
from microdex.schemas import ModelOutcome, ToolCall

pytestmark = pytest.mark.core


def test_scripted_read_and_exec_then_stop(tmp_path):
    (tmp_path / "hello.py").write_text("print(1)\n", encoding="utf-8")
    client = ScriptedModelClient(
        [
            ModelOutcome(
                tool_calls=[
                    ToolCall(
                        id="read-1", name="read_file", arguments={"path": "hello.py"}
                    )
                ]
            ),
            ModelOutcome(
                tool_calls=[
                    ToolCall(
                        id="exec-1",
                        name="exec_command",
                        arguments={"cmd": "python3 hello.py"},
                    )
                ]
            ),
            ModelOutcome(text="fixed"),
        ]
    )
    graph = build_turn_graph(client)
    final = graph.invoke(
        initial_state("fix this test", str(tmp_path)),
        config={"recursion_limit": 12},
    )
    roles = [message["role"] for message in final["history"]]
    assert roles == ["user", "assistant", "tool", "assistant", "tool", "assistant"]
    assert final["pending_calls"] == []
    assert final["history"][2]["content"] == "print(1)\n"
    assert final["history"][2]["tool_call_id"] == "read-1"
    assert "1" in final["history"][4]["content"]
    assert final["history"][5]["content"] == "fixed"
    assert client._script == []
