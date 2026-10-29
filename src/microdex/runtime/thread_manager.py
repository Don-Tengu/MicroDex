"""Create and own multiple independent MicrodexThread instances."""

import asyncio
import uuid
from pathlib import Path

from microdex.agent.graph import build_turn_graph
from microdex.client import ModelClient, ScriptedModelClient
from microdex.constants import RECURSION_LIMIT
from microdex.context.agents_md import load_project_instructions
from microdex.runtime.input_queue import InputQueue
from microdex.runtime.approval import ApprovalBroker
from microdex.runtime.session import Session
from microdex.runtime.session_io import SessionIo
from microdex.runtime.submission_loop import submission_loop
from microdex.runtime.thread import MicrodexThread


class ThreadManager:
    """Registry and lifecycle owner for live conversations."""

    def __init__(
        self,
        model_client: ModelClient | ScriptedModelClient,
        *,
        checkpointer=None,
        recursion_limit: int = RECURSION_LIMIT,
    ) -> None:
        self._model_client = model_client
        self._checkpointer = checkpointer
        self._recursion_limit = recursion_limit
        self._threads: dict[str, MicrodexThread] = {}
        self._lock = asyncio.Lock()

    async def create_thread(
        self,
        cwd: Path | str,
        *,
        thread_id: str | None = None,
    ) -> MicrodexThread:
        resolved = Path(cwd).expanduser().resolve()
        if not resolved.is_dir():
            raise NotADirectoryError(resolved)
        identity = thread_id or uuid.uuid4().hex

        async with self._lock:
            existing = self._threads.get(identity)
            if existing is not None:
                return existing

            io = SessionIo()
            input_queue = InputQueue()
            approval_broker = ApprovalBroker(identity, io, str(resolved))
            graph = build_turn_graph(
                self._model_client,
                checkpointer=self._checkpointer,
                drain_pending_inputs=input_queue.drain,
                request_approval=approval_broker.request,
            )
            session = Session(
                id=identity,
                cwd=resolved,
                instructions=load_project_instructions(resolved),
                graph=graph,
                io=io,
                input_queue=input_queue,
                approval_broker=approval_broker,
                recursion_limit=self._recursion_limit,
            )
            loop_task = asyncio.create_task(
                submission_loop(session),
                name=f"microdex-submissions-{identity}",
            )
            thread = MicrodexThread(session, io, loop_task)
            self._threads[identity] = thread
            return thread

    def get_thread(self, thread_id: str) -> MicrodexThread | None:
        return self._threads.get(thread_id)

    async def shutdown_thread(self, thread_id: str) -> None:
        async with self._lock:
            thread = self._threads.pop(thread_id, None)
        if thread is not None:
            await thread.shutdown()

    async def shutdown_all(self) -> None:
        async with self._lock:
            threads = list(self._threads.values())
            self._threads.clear()
        await asyncio.gather(*(thread.shutdown() for thread in threads))
