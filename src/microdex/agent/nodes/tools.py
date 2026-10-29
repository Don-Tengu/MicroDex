"""Execute one complete model-requested tool batch before resampling."""

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable

from microdex.agent.state import (
    HistoryMessage,
    ToolCallState,
    ToolResult,
    TurnState,
)
from microdex.events import Emit, tool_end, tool_start
from microdex.tools.registry import (
    execute_tool,
    is_parallel_safe,
    requires_approval,
)

ApprovalRequest = Callable[[ToolCallState, str], bool]


def tool_message(call: ToolCallState, result: ToolResult) -> HistoryMessage:
    return {
        "role": "tool",
        "content": result["output"],
        "tool_call_id": call["id"],
        "tool_calls": [],
    }


def record_tool_result(
    state: TurnState,
    call: ToolCallState,
    result: ToolResult,
) -> dict:
    """Compatibility helper for one result; the graph uses the batch form."""

    remaining = [
        pending for pending in state["pending_calls"] if pending["id"] != call["id"]
    ]
    return {
        "history": [tool_message(call, result)],
        "pending_calls": remaining,
        "needs_follow_up": True,
    }


def record_tool_results(
    calls: list[ToolCallState],
    results: list[ToolResult],
) -> dict:
    return {
        "history": [
            tool_message(call, result)
            for call, result in zip(calls, results, strict=True)
        ],
        "pending_calls": [],
        "needs_follow_up": True,
    }


def tools_node(
    state: TurnState,
    emit: Emit,
    request_approval: ApprovalRequest | None = None,
) -> dict:
    """Run all calls from one model response, preserving model order."""

    calls = list(state["pending_calls"])
    results: list[ToolResult] = []
    index = 0
    while index < len(calls):
        if not is_parallel_safe(calls[index]["name"]):
            call = calls[index]
            if requires_approval(call["name"]):
                approved = (
                    request_approval(call, state["turn_id"])
                    if request_approval is not None
                    else False
                )
                if not approved:
                    result = {
                        "ok": False,
                        "output": "user declined tool execution",
                    }
                    emit(tool_start(call))
                    emit(tool_end(call, result))
                    results.append(result)
                    index += 1
                    continue
            emit(tool_start(call))
            result = execute_tool(call, state["cwd"])
            emit(tool_end(call, result))
            results.append(result)
            index += 1
            continue

        end = index
        while end < len(calls) and is_parallel_safe(calls[end]["name"]):
            end += 1
        batch = calls[index:end]
        for call in batch:
            emit(tool_start(call))
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            batch_results = list(
                pool.map(lambda call: execute_tool(call, state["cwd"]), batch)
            )
        for call, result in zip(batch, batch_results, strict=True):
            emit(tool_end(call, result))
        results.extend(batch_results)
        index = end

    return record_tool_results(calls, results)
