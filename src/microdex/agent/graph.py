"""Compile the LangGraph used by run_turn.

    START -> sample
                 | tool calls
                 v
               tools
                 |
                 v
             drain_input -- follow up --> sample
                 |
                 +----------------------> END

The outer submission_loop and RegularTask live in microdex.runtime.
"""

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from microdex.agent.nodes.model import sample_node
from microdex.agent.nodes.tools import tools_node
from microdex.agent.routing import route_after_input, route_after_sample
from microdex.agent.state import TurnState, user_message
from microdex.client import ModelClient, ScriptedModelClient
from microdex.events import emit


def build_turn_graph(
    model_client: ModelClient | ScriptedModelClient,
    checkpointer=None,
    *,
    drain_pending_inputs: Callable[[], list[str]] | None = None,
) -> CompiledStateGraph:
    drain_pending_inputs = drain_pending_inputs or (list)

    def sample(state: TurnState) -> dict:
        return sample_node(state, model_client, emit)

    def tools(state: TurnState) -> dict:
        return tools_node(state, emit)

    def drain_input(state: TurnState) -> dict:
        pending = drain_pending_inputs()
        if not pending:
            return {"needs_follow_up": state["needs_follow_up"]}
        return {
            "history": [user_message(text) for text in pending],
            "needs_follow_up": True,
        }

    builder = StateGraph(TurnState)
    builder.add_node("sample", sample)
    builder.add_node("tools", tools)
    builder.add_node("drain_input", drain_input)
    builder.add_edge(START, "sample")
    builder.add_conditional_edges(
        "sample",
        route_after_sample,
        {"tools": "tools", "drain_input": "drain_input"},
    )
    builder.add_edge("tools", "drain_input")
    builder.add_conditional_edges(
        "drain_input",
        route_after_input,
        {"sample": "sample", "end": END},
    )
    return builder.compile(checkpointer=checkpointer)
