import pytest
from langgraph.graph import END, START, StateGraph
from microdex.agent.graph import build_turn_graph
from microdex.agent.state import initial_state
from microdex.client import ScriptedModelClient
from microdex.events import agent_message_content_delta, emit
from microdex.schemas import ModelOutcome

pytestmark = pytest.mark.scaffold


def test_graph_has_the_sample_tool_loop():
    graph = build_turn_graph(ScriptedModelClient([]))
    assert {"sample", "tools", "drain_input"} <= set(graph.nodes)


def test_sample_builds_the_prompt_before_calling_the_client(tmp_path):
    seen = []

    class RecordingClient(ScriptedModelClient):
        def complete(self, prompt, emit):
            seen.append(prompt)
            return super().complete(prompt, emit)

    client = RecordingClient([ModelOutcome(text="done")])
    graph = build_turn_graph(client)
    graph.invoke(initial_state("fix this test", str(tmp_path)))
    assert len(seen) == 1
    assert any(
        message.get("role") == "user" and "fix this test" in str(message.get("content"))
        for message in seen[0].messages
    )
    assert client._script == []


def test_emit_shows_up_on_the_custom_stream():
    class Box(dict):
        pass

    builder = StateGraph(Box)
    builder.add_node(
        "speak",
        lambda state: emit(agent_message_content_delta("hi")) or {"n": 1},
    )
    builder.add_edge(START, "speak")
    builder.add_edge("speak", END)
    graph = builder.compile()
    assert list(graph.stream({"n": 0}, stream_mode="custom")) == [
        agent_message_content_delta("hi")
    ]
