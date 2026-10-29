"""Operations entering a session and events leaving it.

Codex defines Op and EventMsg in codex-rs/protocol/src/protocol.rs. These
smaller Python types preserve the same seam: clients submit operations and
observe events; they never call the turn graph directly.
"""

from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict


@dataclass(frozen=True, slots=True)
class TurnInput:
    text: str


@dataclass(frozen=True, slots=True)
class Interrupt:
    reason: str = "user"


@dataclass(frozen=True, slots=True)
class Shutdown:
    pass


@dataclass(frozen=True, slots=True)
class ToolApprovalDecision:
    tool_call_id: str
    approved: bool


Op = TurnInput | Interrupt | Shutdown | ToolApprovalDecision


@dataclass(frozen=True, slots=True)
class Submission:
    id: str
    op: Op


EventKind = Literal[
    "turn_started",
    "input_queued",
    "agent_message_content_delta",
    "tool_start",
    "tool_end",
    "tool_approval_requested",
    "turn_completed",
    "turn_aborted",
    "error",
    "interrupt_ignored",
    "session_closed",
]


class EventMsg(TypedDict):
    kind: EventKind
    thread_id: str
    turn_id: str
    submission_id: str
    text: str
    tool_name: str
    tool_call_id: str
    ok: bool
    reason: NotRequired[str]
    tool_arguments: NotRequired[dict[str, Any]]
    cwd: NotRequired[str]


def event_msg(
    kind: EventKind,
    *,
    thread_id: str,
    turn_id: str = "",
    submission_id: str = "",
    text: str = "",
    tool_name: str = "",
    tool_call_id: str = "",
    ok: bool = True,
    reason: str = "",
    tool_arguments: dict[str, Any] | None = None,
    cwd: str = "",
) -> EventMsg:
    event: EventMsg = {
        "kind": kind,
        "thread_id": thread_id,
        "turn_id": turn_id,
        "submission_id": submission_id,
        "text": text,
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "ok": ok,
    }
    if reason:
        event["reason"] = reason
    if tool_arguments is not None:
        event["tool_arguments"] = tool_arguments
    if cwd:
        event["cwd"] = cwd
    return event
