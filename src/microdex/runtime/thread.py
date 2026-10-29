"""Public handle for one coding-agent conversation."""

import asyncio

from microdex.runtime.protocol import (
    EventMsg,
    Interrupt,
    Shutdown,
    ToolApprovalDecision,
    TurnInput,
)
from microdex.runtime.session import Session
from microdex.runtime.session_io import SessionIo


class MicrodexThread:
    """A conversation handle, not an operating-system thread."""

    def __init__(
        self,
        session: Session,
        io: SessionIo,
        loop_task: asyncio.Task[None],
    ) -> None:
        self.session = session
        self.io = io
        self._loop_task = loop_task

    @property
    def id(self) -> str:
        return self.session.id

    async def start_turn(self, text: str) -> str:
        return await self.io.submit(TurnInput(text=text))

    async def interrupt(self, reason: str = "user") -> str:
        return await self.io.submit(Interrupt(reason=reason))

    async def approve_tool(self, tool_call_id: str, approved: bool) -> str:
        return await self.io.submit(
            ToolApprovalDecision(tool_call_id=tool_call_id, approved=approved)
        )

    async def next_event(self) -> EventMsg:
        return await self.io.next_event()

    async def shutdown(self) -> None:
        if self._loop_task.done():
            await self._loop_task
            return
        await self.io.submit(Shutdown())
        await self._loop_task
