"""Steering input that arrives while a RegularTask is active."""

from collections import deque
from threading import Lock


class InputQueue:
    """A small thread-safe queue shared by runtime and graph nodes.

    LangGraph may execute synchronous nodes on a worker thread, so an asyncio
    Queue alone is not the right boundary here.
    """

    def __init__(self) -> None:
        self._items: deque[str] = deque()
        self._lock = Lock()

    def push(self, text: str) -> None:
        with self._lock:
            self._items.append(text)

    def drain(self) -> list[str]:
        with self._lock:
            items = list(self._items)
            self._items.clear()
        return items

    def __bool__(self) -> bool:
        with self._lock:
            return bool(self._items)
