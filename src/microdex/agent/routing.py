"""Deterministic routing for the inner model-tool loop."""

from typing import Literal

from microdex.agent.state import TurnState


def route_after_sample(state: TurnState) -> Literal["tools", "drain_input"]:
    """A complete model response either requests a tool batch or may finish."""

    return "tools" if state["pending_calls"] else "drain_input"


def route_after_input(state: TurnState) -> Literal["sample", "end"]:
    """Continue for tool results or steering input; otherwise reach END."""

    return "sample" if state["needs_follow_up"] else "end"
