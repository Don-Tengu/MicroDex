"""Serializable state for the inner run_turn graph.

Queues, asyncio tasks, locks, and subprocess handles deliberately stay in
microdex.runtime. Only checkpoint-safe conversation state crosses LangGraph
nodes.
"""

from typing import Annotated, Literal, TypedDict

from microdex.context.agents_md import load_project_instructions


class ToolCallState(TypedDict):
    id: str
    name: str
    arguments: dict


class HistoryMessage(TypedDict):
    role: Literal["user", "assistant", "tool"]
    content: str
    tool_call_id: str
    tool_calls: list[ToolCallState]


class ToolResult(TypedDict):
    ok: bool
    output: str


def append_list(existing: list, incoming: list) -> list:
    """Append only the items produced during the current graph visit."""

    return [*existing, *incoming]


class TurnState(TypedDict):
    turn_id: str
    cwd: str
    instructions: str
    history: Annotated[list[HistoryMessage], append_list]
    pending_calls: list[ToolCallState]
    needs_follow_up: bool
    terminal_error: str


def user_message(text: str) -> HistoryMessage:
    return {
        "role": "user",
        "content": text,
        "tool_call_id": "",
        "tool_calls": [],
    }


def initial_state(
    user_text: str,
    cwd: str,
    *,
    turn_id: str = "",
    instructions: str | None = None,
) -> TurnState:
    return initial_state_for_inputs(
        [user_text],
        cwd,
        turn_id=turn_id,
        instructions=instructions,
    )


def initial_state_for_inputs(
    user_inputs: list[str],
    cwd: str,
    *,
    turn_id: str = "",
    instructions: str | None = None,
) -> TurnState:
    """Build one graph input; a reused checkpoint appends these messages."""

    stable_instructions = (
        load_project_instructions(cwd) if instructions is None else instructions
    )
    return {
        "turn_id": turn_id,
        "cwd": cwd,
        "instructions": stable_instructions,
        "history": [user_message(text) for text in user_inputs],
        "pending_calls": [],
        "needs_follow_up": False,
        "terminal_error": "",
    }
