"""SQLite graph-state savers.

The checkpointer resumes serializable LangGraph state for a conversation id.
It is not the live ThreadManager, submission queue, or event stream.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


@contextmanager
def open_checkpointer(path: Path) -> Iterator[SqliteSaver]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(path)) as saver:
        yield saver


@asynccontextmanager
async def open_async_checkpointer(path: Path) -> AsyncIterator[AsyncSqliteSaver]:
    """Async saver used by the submission-loop runtime."""

    path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        yield saver
