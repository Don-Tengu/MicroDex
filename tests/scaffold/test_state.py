import pytest
from microdex.agent.state import append_list, initial_state

pytestmark = pytest.mark.scaffold


def test_initial_state_is_one_user_message(tmp_path):
    state = initial_state("fix this test", str(tmp_path))
    assert state["cwd"] == str(tmp_path)
    assert state["pending_calls"] == []
    assert state["history"] == [
        {
            "role": "user",
            "content": "fix this test",
            "tool_call_id": "",
            "tool_calls": [],
        }
    ]


def test_history_reducer_appends_only_the_incoming_items():
    assert append_list(["user"], ["assistant"]) == ["user", "assistant"]
