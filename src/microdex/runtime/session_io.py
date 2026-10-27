"""In-memory channels on the public edge of one session."""

import asyncio
import uuid

from microdex.runtime.protocol import EventMsg, Op, Submission


class SessionIo:
    """Submission receiver plus event sender for one MicrodexThread."""

    def __init__(self) -> None:
        self._submissions: asyncio.Queue[Submission] = asyncio.Queue()
        self._events: asyncio.Queue[EventMsg] = asyncio.Queue()

    async def submit(self, op: Op) -> str:
        submission_id = uuid.uuid4().hex
        await self._submissions.put(Submission(id=submission_id, op=op))
        return submission_id

    async def recv_submission(self) -> Submission:
        return await self._submissions.get()

    async def emit(self, event: EventMsg) -> None:
        await self._events.put(event)

    async def next_event(self) -> EventMsg:
        return await self._events.get()
