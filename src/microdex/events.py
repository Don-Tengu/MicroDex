"""Events the model node and the tool node push while a run is in flight.

The CLI prints `stream_mode="custom"`. The finished model message is still
what the next node reads. A later node must not be the thing that reveals
tokens.

Text uses Codex's UI event name, `AgentMessageContentDelta`
(`protocol/src/protocol.rs`). Tool start and end stay generic. Codex emits
`ExecCommandBegin` or `PatchApplyBegin` per tool, and one name would not
cover `read_file` and `rg`.
"""

from collections.abc import Callable
from typing import Literal, TypedDict

from langgraph.config import get_stream_writer

from microdex.agent.state import ToolCallState, ToolResult


class StreamEvent(TypedDict):
    kind: Literal["agent_message_content_delta", "tool_start", "tool_end"]
    text: str
    tool_name: str
    tool_call_id: str
    ok: bool


Emit = Callable[[StreamEvent], None]


def agent_message_content_delta(text: str) -> StreamEvent:
    return {
        "kind": "agent_message_content_delta",
        "text": text,
        "tool_name": "",
        "tool_call_id": "",
        "ok": True,
    }


def tool_start(call: ToolCallState) -> StreamEvent:
    return {
        "kind": "tool_start",
        "text": "",
        "tool_name": call["name"],
        "tool_call_id": call["id"],
        "ok": True,
    }


def tool_end(call: ToolCallState, result: ToolResult) -> StreamEvent:
    return {
        "kind": "tool_end",
        "text": "",
        "tool_name": call["name"],
        "tool_call_id": call["id"],
        "ok": result["ok"],
    }


def emit(event: StreamEvent) -> None:
    """Push one event to the active graph run's custom stream."""

    get_stream_writer()(event)
