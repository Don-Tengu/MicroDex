"""Execute the inner model-tool loop for one step of a RegularTask."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from microdex.agent.state import TurnState
from microdex.events import StreamEvent


@dataclass(frozen=True, slots=True)
class TurnRunResult:
    state: dict[str, Any]

    @property
    def terminal_error(self) -> str:
        return str(self.state.get("terminal_error") or "")


async def run_turn(
    graph: CompiledStateGraph,
    state: TurnState,
    *,
    config: dict[str, Any],
    on_event: Callable[[StreamEvent], Awaitable[None]],
) -> TurnRunResult:
    """Run LangGraph until END and bridge its custom events to the session."""

    final_state: dict[str, Any] = {}
    async for mode, payload in graph.astream(
        state,
        config=config,
        stream_mode=["custom", "values"],
    ):
        if mode == "custom":
            await on_event(payload)
        elif mode == "values":
            final_state = dict(payload)
    return TurnRunResult(state=final_state)
