"""Runtime-owned approval waiters for mutating tools."""

import asyncio
from concurrent.futures import Future
from threading import Lock

from microdex.agent.state import ToolCallState
from microdex.runtime.protocol import event_msg
from microdex.runtime.session_io import SessionIo


class ApprovalBroker:
    """Bridge synchronous graph workers to SessionIo approval decisions."""

    def __init__(self, thread_id: str, io: SessionIo, cwd: str) -> None:
        self._thread_id = thread_id
        self._io = io
        self._cwd = cwd
        self._loop = asyncio.get_running_loop()
        self._pending: dict[str, Future[bool]] = {}
        self._lock = Lock()
        self._closed = False

    def request(self, call: ToolCallState, turn_id: str) -> bool:
        """Emit one approval event, then wait until the session resolves it."""

        call_id = call["id"]
        future: Future[bool] = Future()
        with self._lock:
            if self._closed or call_id in self._pending:
                return False
            self._pending[call_id] = future

        event = event_msg(
            "tool_approval_requested",
            thread_id=self._thread_id,
            turn_id=turn_id,
            tool_name=call["name"],
            tool_call_id=call_id,
            ok=False,
            tool_arguments=call["arguments"],
            cwd=self._cwd,
        )
        try:
            asyncio.run_coroutine_threadsafe(self._io.emit(event), self._loop).result()
            return future.result()
        except RuntimeError:
            return False
        finally:
            with self._lock:
                if self._pending.get(call_id) is future:
                    del self._pending[call_id]

    def resolve(self, tool_call_id: str, approved: bool) -> bool:
        with self._lock:
            future = self._pending.get(tool_call_id)
            if future is None or future.done():
                return False
            future.set_result(bool(approved))
            return True

    def reject_pending(self, *, close: bool = False) -> None:
        """Fail closed on interrupt or shutdown and release blocked workers."""

        with self._lock:
            if close:
                self._closed = True
            for future in self._pending.values():
                if not future.done():
                    future.set_result(False)
