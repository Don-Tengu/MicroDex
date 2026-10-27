"""One user task around one or more inner run_turn executions."""

import asyncio
import uuid

from microdex.agent.state import initial_state_for_inputs
from microdex.agent.turn import run_turn
from microdex.events import StreamEvent
from microdex.runtime.protocol import Submission, TurnInput, event_msg
from microdex.runtime.session import Session


class RegularTask:
    """Own the lifetime of one accepted TurnInput.

    Steering input normally enters the running graph before its next model
    sample. A final drain after graph END closes the small race where input
    arrives just as the graph is deciding to stop.
    """

    def __init__(self, session: Session, submission: Submission) -> None:
        if not isinstance(submission.op, TurnInput):
            raise TypeError("RegularTask requires TurnInput")
        self.session = session
        self.submission = submission
        self.turn_id = uuid.uuid4().hex

    async def run(self) -> None:
        try:
            await self.session.emit(
                event_msg(
                    "turn_started",
                    thread_id=self.session.id,
                    turn_id=self.turn_id,
                    submission_id=self.submission.id,
                )
            )
            pending = [self.submission.op.text]
            while pending:
                state = initial_state_for_inputs(
                    pending,
                    cwd=str(self.session.cwd),
                    turn_id=self.turn_id,
                    instructions=self.session.instructions,
                )
                result = await run_turn(
                    self.session.graph,
                    state,
                    config=self.session.graph_config,
                    on_event=self._forward_graph_event,
                )
                if result.terminal_error:
                    raise RuntimeError(result.terminal_error)
                pending = self.session.input_queue.drain()

            for submission_id in self.session.finish_submission_ids(self.submission.id):
                await self.session.emit(
                    event_msg(
                        "turn_completed",
                        thread_id=self.session.id,
                        turn_id=self.turn_id,
                        submission_id=submission_id,
                    )
                )
        except asyncio.CancelledError:
            for submission_id in self.session.finish_submission_ids(self.submission.id):
                await self.session.emit(
                    event_msg(
                        "turn_aborted",
                        thread_id=self.session.id,
                        turn_id=self.turn_id,
                        submission_id=submission_id,
                        ok=False,
                        reason="interrupted",
                    )
                )
            raise
        except Exception as exc:
            for submission_id in self.session.finish_submission_ids(self.submission.id):
                await self.session.emit(
                    event_msg(
                        "error",
                        thread_id=self.session.id,
                        turn_id=self.turn_id,
                        submission_id=submission_id,
                        text=str(exc),
                        ok=False,
                    )
                )
                await self.session.emit(
                    event_msg(
                        "turn_aborted",
                        thread_id=self.session.id,
                        turn_id=self.turn_id,
                        submission_id=submission_id,
                        ok=False,
                        reason="error",
                    )
                )

    async def _forward_graph_event(self, graph_event: StreamEvent) -> None:
        await self.session.emit(
            event_msg(
                graph_event["kind"],
                thread_id=self.session.id,
                turn_id=self.turn_id,
                submission_id=self.submission.id,
                text=graph_event["text"],
                tool_name=graph_event["tool_name"],
                tool_call_id=graph_event["tool_call_id"],
                ok=graph_event["ok"],
            )
        )
