from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph
from microdex.persistence.checkpointer import open_checkpointer

pytestmark = pytest.mark.scaffold


def test_sqlite_checkpointer_restores_a_finished_run(tmp_path):
    class Count(TypedDict):
        n: int

    def inc(state: Count) -> dict:
        return {"n": state["n"] + 1}

    with open_checkpointer(tmp_path / "turns.sqlite") as saver:
        builder = StateGraph(Count)
        builder.add_node("inc", inc)
        builder.add_edge(START, "inc")
        builder.add_edge("inc", END)
        graph = builder.compile(checkpointer=saver)
        config = {"configurable": {"thread_id": "thread-a"}}
        assert graph.invoke({"n": 1}, config) == {"n": 2}
        assert graph.get_state(config).values["n"] == 2
    assert (tmp_path / "turns.sqlite").is_file()
