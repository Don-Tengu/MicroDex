"""Read resumable conversations from LangGraph checkpoint storage."""

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from langgraph.graph.state import CompiledStateGraph


@dataclass(frozen=True, slots=True)
class SavedSession:
    id: str
    cwd: str
    title: str
    preview: str
    updated_at: str
    user_turns: int


def checkpoint_thread_ids(path: Path, *, limit: int | None = None) -> list[str]:
    """Return checkpoint thread ids, newest checkpoint first."""

    if not path.is_file():
        return []
    try:
        with sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=2
        ) as db:
            query = (
                "SELECT thread_id FROM checkpoints "
                "GROUP BY thread_id ORDER BY MAX(checkpoint_id) DESC"
            )
            rows = (
                db.execute(query)
                if limit is None
                else db.execute(f"{query} LIMIT ?", (limit,))
            )
            return [str(row[0]) for row in rows]
    except sqlite3.Error:
        return []


async def list_saved_sessions(
    graph: CompiledStateGraph,
    checkpoint_path: Path,
    cwd: Path,
    *,
    limit: int | None = None,
) -> list[SavedSession]:
    """Load the latest checkpoint for sessions whose saved cwd matches cwd."""

    resolved_cwd = cwd.expanduser().resolve()
    sessions: list[SavedSession] = []
    for thread_id in checkpoint_thread_ids(checkpoint_path, limit=limit):
        snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
        state = snapshot.values
        if not state:
            continue
        saved_cwd = state.get("cwd")
        if not isinstance(saved_cwd, str):
            continue
        if Path(saved_cwd).expanduser().resolve() != resolved_cwd:
            continue

        history = state.get("history", [])
        if not isinstance(history, list) or not history:
            continue
        user_messages = [
            _message_content(item)
            for item in history
            if isinstance(item, dict) and item.get("role") == "user"
        ]
        title = _short_title(user_messages[0] if user_messages else "New session")
        preview = _short_title(user_messages[-1] if user_messages else title)
        sessions.append(
            SavedSession(
                id=thread_id,
                cwd=str(resolved_cwd),
                title=title,
                preview=preview,
                updated_at=str(snapshot.created_at or ""),
                user_turns=len(user_messages),
            )
        )

    sessions.sort(key=lambda session: session.updated_at, reverse=True)
    return sessions


async def load_saved_history(
    graph: CompiledStateGraph,
    thread_id: str,
) -> dict[str, Any]:
    """Return the latest serializable conversation state for a resume view."""

    snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    state = snapshot.values
    if not state:
        return {"thread_id": thread_id, "history": [], "cwd": ""}
    history = state.get("history", [])
    return {
        "thread_id": thread_id,
        "history": history if isinstance(history, list) else [],
        "cwd": str(state.get("cwd") or ""),
        "updated_at": str(snapshot.created_at or ""),
    }


def session_as_dict(session: SavedSession) -> dict[str, Any]:
    return asdict(session)


def _message_content(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content", "")
    return content if isinstance(content, str) else ""


def _short_title(text: str, limit: int = 120) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if len(first_line) <= limit:
        return first_line
    return first_line[: limit - 1].rstrip() + "…"
