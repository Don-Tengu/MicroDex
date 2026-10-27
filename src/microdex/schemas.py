"""Objects that cross the model boundary.

Inside the graph, state stays a plain dict. Pydantic is used where JSON from
the model enters, and for the arguments of a tool call.
"""

from typing import Any

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ModelOutcome(BaseModel):
    """One finished model response. Tokens are streamed separately.

    Codex does not keep this as one struct. `run_sampling_request` accumulates
    `ResponseItem`s, and `SamplingRequestResult` only records whether the turn
    needs another sample. This object is the pair of those facts the graph
    needs: the assistant text and the tool calls.
    """

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)


class Prompt(BaseModel):
    """Payload of one model call. Codex: `Prompt` in `core/src/client_common.rs`.

    Codex stores `input` as `ResponseItem`s for the Responses API. This client
    sends chat-completions `messages`, so the field keeps that name.
    """

    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]


class ReadFileArgs(BaseModel):
    path: str


class RgArgs(BaseModel):
    pattern: str
    path: str = ""
    glob: str = ""


class ApplyPatchArgs(BaseModel):
    """`patch` is the Codex freeform grammar, not a unified diff.

    Grammar: `codex-rs/core/assets/tools/apply_patch.lark` under `~/Code/codex`.
    Phase 1 exercises Add File, Delete File, and one Update File hunk.
    """

    patch: str


class ExecCommandArgs(BaseModel):
    """One shell command. Phase 1 ignores Codex's tty, yield, and login fields."""

    cmd: str
    workdir: str = ""


class UnknownTool(ValueError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(name)


_ARG_MODELS = {
    "read_file": ReadFileArgs,
    "rg": RgArgs,
    "apply_patch": ApplyPatchArgs,
    "exec_command": ExecCommandArgs,
}


def parse_arguments(call: dict) -> BaseModel:
    """Validate `call["arguments"]` for a phase-1 tool.

    `execute_tool` should catch `UnknownTool` and `ValidationError` and return
    `ok=False`. A bad argument is something the model can correct on the next
    sample. It is not a crash of the graph.
    """

    name = call.get("name", "")
    model = _ARG_MODELS.get(name)
    if model is None:
        raise UnknownTool(str(name))
    return model.model_validate(call.get("arguments") or {})
