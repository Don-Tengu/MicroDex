"""Build one request, sample the model, and record the finished response."""

import json

from microdex.agent.state import HistoryMessage, ToolCallState, TurnState
from microdex.events import Emit
from microdex.schemas import ModelOutcome, Prompt
from microdex.tools.registry import tool_specs

BASE_INSTRUCTIONS = """You are Microdex, a coding agent working in the user's repository.
Inspect the relevant code before changing it. Use the provided tools for
evidence, preserve unrelated behavior, and report what you actually verified.
Tool failures are observations: read the result, adjust, and continue."""


def build_prompt(state: TurnState) -> Prompt:
    """Translate checkpoint history into one chat-completions request."""

    instructions = BASE_INSTRUCTIONS
    project = state.get("instructions", "").strip()
    if project:
        instructions = f"{instructions}\n\nProject instructions:\n{project}"

    messages: list[dict] = [{"role": "system", "content": instructions}]
    for item in state["history"]:
        role = item["role"]
        if role == "assistant":
            message: dict = {
                "role": "assistant",
                "content": item["content"],
            }
            if item["tool_calls"]:
                message["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(
                                call["arguments"],
                                ensure_ascii=False,
                            ),
                        },
                    }
                    for call in item["tool_calls"]
                ]
            messages.append(message)
        elif role == "tool":
            messages.append(
                {
                    "role": "tool",
                    "content": item["content"],
                    "tool_call_id": item["tool_call_id"],
                }
            )
        else:
            messages.append({"role": "user", "content": item["content"]})

    return Prompt(messages=messages, tools=tool_specs())


def record_model_outcome(state: TurnState, outcome: ModelOutcome) -> dict:
    """Append the assistant response and queue its complete tool-call batch."""

    del state
    calls = [call.model_dump() for call in outcome.tool_calls]
    return {
        "history": [assistant_message(outcome.text, calls)],
        "pending_calls": calls,
        "needs_follow_up": bool(calls),
        "terminal_error": "",
    }


def assistant_message(content: str, tool_calls: list[ToolCallState]) -> HistoryMessage:
    return {
        "role": "assistant",
        "content": content,
        "tool_call_id": "",
        "tool_calls": tool_calls,
    }


def sample_node(state: TurnState, model_client, emit: Emit) -> dict:
    prompt = build_prompt(state)
    outcome = model_client.complete(prompt, emit)
    return record_model_outcome(state, outcome)
