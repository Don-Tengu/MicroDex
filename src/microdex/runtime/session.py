"""Runtime-owned state for one MicrodexThread."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from microdex.runtime.input_queue import InputQueue
from microdex.runtime.protocol import EventMsg
from microdex.runtime.session_io import SessionIo


@dataclass(slots=True)
class Session:
    id: str
    cwd: Path
    instructions: str
    graph: CompiledStateGraph
    io: SessionIo
    input_queue: InputQueue
    recursion_limit: int
    active_task: asyncio.Task[None] | None = field(default=None, init=False)
    active_submission_ids: list[str] = field(default_factory=list, init=False)
    closed: bool = field(default=False, init=False)

    @property
    def graph_config(self) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": self.id},
            "recursion_limit": self.recursion_limit,
        }

    async def emit(self, event: EventMsg) -> None:
        await self.io.emit(event)

    def finish_submission_ids(self, fallback: str) -> list[str]:
        ids = self.active_submission_ids or [fallback]
        self.active_submission_ids = []
        return ids
