"""Long-lived operation loop for one Session.

This is the asyncio counterpart of Codex submission_loop in
codex-rs/core/src/session/handlers.rs. The loop owns task lifecycle; the
LangGraph inside run_turn owns only model/tool progression.
"""

import asyncio
from contextlib import suppress

from microdex.runtime.protocol import (
    Interrupt,
    Shutdown,
    Submission,
    ToolApprovalDecision,
    TurnInput,
    event_msg,
)
from microdex.runtime.regular_task import RegularTask
from microdex.runtime.session import Session


async def submission_loop(session: Session) -> None:
    receive = asyncio.create_task(session.io.recv_submission())
    try:
        while True:
            wait_for: set[asyncio.Task] = {receive}
            if session.active_task is not None:
                wait_for.add(session.active_task)

            done, _ = await asyncio.wait(
                wait_for,
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Reap first. If a completed task and a new submission become ready
            # together, the submission must see the session as idle.
            if session.active_task is not None and session.active_task in done:
                await _reap_active_task(session, restart_pending=True)

            if receive not in done:
                continue

            submission = receive.result()
            receive = asyncio.create_task(session.io.recv_submission())
            if await _handle_submission(session, submission):
                break
    finally:
        receive.cancel()
        with suppress(asyncio.CancelledError):
            await receive
        session.approval_broker.reject_pending(close=True)
        if session.active_task is not None:
            session.active_task.cancel()
            await _reap_active_task(session, restart_pending=False)
        session.closed = True
        await session.emit(event_msg("session_closed", thread_id=session.id))


async def _handle_submission(session: Session, submission: Submission) -> bool:
    op = submission.op
    if isinstance(op, Shutdown):
        return True

    if isinstance(op, ToolApprovalDecision):
        if not session.approval_broker.resolve(op.tool_call_id, op.approved):
            await session.emit(
                event_msg(
                    "error",
                    thread_id=session.id,
                    submission_id=submission.id,
                    text=f"no pending approval for tool call {op.tool_call_id}",
                    ok=False,
                )
            )
        return False

    if isinstance(op, Interrupt):
        if session.active_task is None:
            await session.emit(
                event_msg(
                    "interrupt_ignored",
                    thread_id=session.id,
                    submission_id=submission.id,
                    reason="no active task",
                )
            )
        else:
            session.approval_broker.reject_pending()
            session.input_queue.drain()
            session.active_task.cancel()
            await _reap_active_task(session, restart_pending=False)
        return False

    if not isinstance(op, TurnInput):
        raise TypeError(f"unsupported operation: {type(op).__name__}")

    text = op.text.strip()
    if not text:
        await session.emit(
            event_msg(
                "error",
                thread_id=session.id,
                submission_id=submission.id,
                text="turn input is empty",
                ok=False,
            )
        )
        await session.emit(
            event_msg(
                "turn_aborted",
                thread_id=session.id,
                submission_id=submission.id,
                ok=False,
                reason="empty input",
            )
        )
        return False

    if session.active_task is None:
        _start_regular_task(session, submission.id, text)
    else:
        session.active_submission_ids.append(submission.id)
        session.input_queue.push(text)
        await session.emit(
            event_msg(
                "input_queued",
                thread_id=session.id,
                submission_id=submission.id,
                text=text,
            )
        )
    return False


def _start_regular_task(
    session: Session,
    submission_id: str,
    text: str,
    *,
    submission_ids: list[str] | None = None,
) -> None:
    task = RegularTask(
        session,
        Submission(id=submission_id, op=TurnInput(text=text)),
    )
    session.active_submission_ids = submission_ids or [submission_id]
    session.active_task = asyncio.create_task(
        task.run(),
        name=f"microdex-regular-{session.id}",
    )


async def _reap_active_task(
    session: Session,
    *,
    restart_pending: bool,
) -> None:
    task = session.active_task
    session.active_task = None
    if task is None:
        return
    with suppress(asyncio.CancelledError):
        await task
    if not restart_pending:
        session.input_queue.drain()
        orphaned_ids = session.active_submission_ids
        session.active_submission_ids = []
        for submission_id in orphaned_ids:
            await session.emit(
                event_msg(
                    "turn_aborted",
                    thread_id=session.id,
                    submission_id=submission_id,
                    ok=False,
                    reason="interrupted",
                )
            )
        return

    # Input can arrive after the graph's final drain but before the task's
    # completion event. Promote that late steering input into a new task.
    late_inputs = session.input_queue.drain()
    if not late_inputs:
        return
    late_ids = session.active_submission_ids
    first_id = late_ids[0] if late_ids else "late-input"
    for text in late_inputs[1:]:
        session.input_queue.push(text)
    _start_regular_task(
        session,
        first_id,
        late_inputs[0],
        submission_ids=late_ids or [first_id],
    )
