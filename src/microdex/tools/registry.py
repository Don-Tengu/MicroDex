"""Tool specs and dispatch.

Codex registers tools in `codex-rs/core/src/tools/registry.rs` and
`spec_plan.rs`. This module advertises the four phase-1 tools and sends a
call to the matching function. Unknown names and invalid arguments become
`ok=False` here, so a bad call does not crash the graph. The tool bodies
themselves are core.
"""

from pydantic import ValidationError

from microdex.agent.state import ToolCallState, ToolResult
from microdex.schemas import (
    ApplyPatchArgs,
    ExecCommandArgs,
    ReadFileArgs,
    RgArgs,
    UnknownTool,
    parse_arguments,
)
from microdex.tools.filesystem import read_file
from microdex.tools.patch import apply_patch
from microdex.tools.search import rg
from microdex.tools.shell import exec_command

_SPECS = (
    (
        "read_file",
        "Read a UTF-8 text file. `path` is relative to the working directory.",
        ReadFileArgs,
    ),
    (
        "rg",
        "Search files with ripgrep. `path` defaults to the working directory. "
        "No match is a normal empty result, not a failure.",
        RgArgs,
    ),
    (
        "apply_patch",
        "Create, update, or delete files. `patch` uses the Codex apply_patch "
        'grammar, wrapped in JSON as {"patch": "..."}.',
        ApplyPatchArgs,
    ),
    (
        "exec_command",
        "Run one shell command and wait for it to finish. "
        "The tool applies its own timeout and output cap.",
        ExecCommandArgs,
    ),
)

_HANDLERS = {
    "read_file": read_file,
    "rg": rg,
    "apply_patch": apply_patch,
    "exec_command": exec_command,
}

# Only side-effect-free tools may share a worker batch. Mutating tools are
# barriers because model call order may encode a dependency.
_PARALLEL_SAFE = frozenset({"read_file", "rg"})


def tool_specs() -> list[dict]:
    """OpenAI chat-completions tool list. Include this in every prompt."""

    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": model.model_json_schema(),
            },
        }
        for name, description, model in _SPECS
    ]


def tool_names() -> list[str]:
    return [name for name, _, _ in _SPECS]


def is_parallel_safe(name: str) -> bool:
    return name in _PARALLEL_SAFE


def execute_tool(call: ToolCallState, cwd: str) -> ToolResult:
    """Validate one call and turn recoverable failures into tool results."""

    try:
        parsed = parse_arguments(call)
    except UnknownTool as exc:
        return {"ok": False, "output": f"unknown tool: {exc.name}"}
    except ValidationError as exc:
        return {"ok": False, "output": str(exc)}
    try:
        return _HANDLERS[call["name"]](parsed, cwd)
    except Exception as exc:
        return {"ok": False, "output": f"{type(exc).__name__}: {exc}"}
