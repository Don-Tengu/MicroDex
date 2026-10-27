"""Turn policy. These fail until the agent nodes and `routing` are filled in."""

import pytest
from microdex.agent.nodes.model import build_prompt, record_model_outcome
from microdex.agent.nodes.tools import record_tool_result
from microdex.agent.routing import route_after_input, route_after_sample
from microdex.agent.state import initial_state
from microdex.schemas import ModelOutcome, ToolCall
from microdex.tools.registry import tool_names

pytestmark = pytest.mark.core


def test_request_carries_the_user_text_and_the_four_tools(tmp_path):
    state = initial_state("fix this test", str(tmp_path))
    prompt = build_prompt(state)
    blob = str(prompt.messages)
    assert "fix this test" in blob
    advertised = [spec["function"]["name"] for spec in prompt.tools]
    assert advertised == tool_names()


def test_text_outcome_appends_one_assistant_message_and_clears_calls(tmp_path):
    state = initial_state("fix this test", str(tmp_path))
    update = record_model_outcome(state, ModelOutcome(text="done"))
    assert update["pending_calls"] == []
    assert update["history"] == [
        {
            "role": "assistant",
            "content": "done",
            "tool_call_id": "",
            "tool_calls": [],
        }
    ]


def test_tool_outcome_keeps_text_and_queues_calls_in_order(tmp_path):
    state = initial_state("fix this test", str(tmp_path))
    outcome = ModelOutcome(
        text="looking",
        tool_calls=[
            ToolCall(id="1", name="rg", arguments={"pattern": "needle"}),
            ToolCall(id="2", name="read_file", arguments={"path": "a.py"}),
        ],
    )
    update = record_model_outcome(state, outcome)
    assert [call["id"] for call in update["pending_calls"]] == ["1", "2"]
    assert len(update["history"]) == 1
    message = update["history"][0]
    assert message["role"] == "assistant"
    assert message["content"] == "looking"
    assert message["tool_calls"] == [call.model_dump() for call in outcome.tool_calls]


def test_route_follows_pending_calls(tmp_path):
    state = initial_state("fix this test", str(tmp_path))
    assert route_after_sample(state) == "drain_input"
    assert route_after_input(state) == "end"
    state["pending_calls"] = [
        {"id": "1", "name": "read_file", "arguments": {"path": "a.py"}}
    ]
    assert route_after_sample(state) == "tools"


def test_tool_result_appends_one_message_and_drops_only_that_call(tmp_path):
    state = initial_state("fix this test", str(tmp_path))
    first = {"id": "1", "name": "read_file", "arguments": {"path": "a.py"}}
    second = {"id": "2", "name": "rg", "arguments": {"pattern": "needle"}}
    state["pending_calls"] = [first, second]
    update = record_tool_result(state, first, {"ok": False, "output": "missing"})
    assert update["pending_calls"] == [second]
    assert update["history"] == [
        {
            "role": "tool",
            "content": "missing",
            "tool_call_id": "1",
            "tool_calls": [],
        }
    ]
