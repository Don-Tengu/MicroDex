import pytest
from microdex.client import ScriptedModelClient, _ToolAcc, finish_outcome, fold_chat_delta
from microdex.schemas import ModelOutcome, Prompt, ToolCall

pytestmark = pytest.mark.scaffold


def test_scripted_client_emits_text_and_pops_in_order():
    events = []
    client = ScriptedModelClient(
        [ModelOutcome(text="hi"), ModelOutcome(text="", tool_calls=[])]
    )
    prompt = Prompt(messages=[], tools=[])
    first = client.complete(prompt, events.append)
    assert first.text == "hi"
    assert events == [
        {
            "kind": "agent_message_content_delta",
            "text": "hi",
            "tool_name": "",
            "tool_call_id": "",
            "ok": True,
        }
    ]
    second = client.complete(prompt, events.append)
    assert second.text == ""
    assert len(events) == 1


def test_stream_deltas_fold_into_one_outcome():
    parts: list[str] = []
    tools: dict[int, _ToolAcc] = {}

    class Function:
        def __init__(self, name=None, arguments=None):
            self.name = name
            self.arguments = arguments

    class Call:
        def __init__(self, index, id=None, name=None, arguments=None):
            self.index = index
            self.id = id
            self.function = Function(name, arguments)

    class Delta:
        def __init__(self, content=None, tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls

    assert fold_chat_delta(parts, tools, Delta(content="look")) == "look"
    fold_chat_delta(parts, tools, Delta(tool_calls=[Call(0, id="c1", name="read_")]))
    fold_chat_delta(
        parts,
        tools,
        Delta(tool_calls=[Call(0, name="file", arguments='{"path":')]),
    )
    fold_chat_delta(parts, tools, Delta(tool_calls=[Call(0, arguments='"a.py"}')]))
    outcome = finish_outcome(parts, tools)
    assert outcome == ModelOutcome(
        text="look",
        tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})],
    )


def test_broken_tool_arguments_fail_at_the_boundary():
    with pytest.raises(RuntimeError, match="not JSON"):
        finish_outcome([], {0: _ToolAcc(id="c", name="rg", arguments="{")})
