"""Apply a small, fully preflighted subset of the Codex patch grammar."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from microdex.agent.state import ToolResult
from microdex.schemas import ApplyPatchArgs
from microdex.tools.paths import resolve_workspace_path


@dataclass(frozen=True, slots=True)
class FileChange:
    kind: Literal["add", "delete", "update"]
    path: str
    body: list[str]


def apply_patch(args: ApplyPatchArgs, cwd: str) -> ToolResult:
    try:
        changes = _parse_patch(args.patch)
        plan = _preflight(changes, cwd)
        for kind, path, content in plan:
            if kind == "delete":
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        return {"ok": False, "output": str(exc)}

    summary = "\n".join(f"{change.kind}: {change.path}" for change in changes)
    return {"ok": True, "output": summary}


def _parse_patch(patch: str) -> list[FileChange]:
    lines = patch.splitlines()
    if not lines or lines[0] != "*** Begin Patch":
        raise ValueError("patch must start with *** Begin Patch")
    if lines[-1:] != ["*** End Patch"]:
        raise ValueError("patch must end with *** End Patch")

    changes: list[FileChange] = []
    index = 1
    while index < len(lines) - 1:
        header = lines[index]
        prefixes = {
            "*** Add File: ": "add",
            "*** Delete File: ": "delete",
            "*** Update File: ": "update",
        }
        match = next(
            (
                (prefix, kind)
                for prefix, kind in prefixes.items()
                if header.startswith(prefix)
            ),
            None,
        )
        if match is None:
            raise ValueError(f"invalid patch header: {header}")
        prefix, kind = match
        path = header[len(prefix) :].strip()
        if not path:
            raise ValueError("patch path is empty")
        index += 1
        body: list[str] = []
        while index < len(lines) - 1 and not lines[index].startswith("*** "):
            body.append(lines[index])
            index += 1
        changes.append(FileChange(kind=kind, path=path, body=body))

    if not changes:
        raise ValueError("patch contains no file changes")
    return changes


def _preflight(
    changes: list[FileChange],
    cwd: str,
) -> list[tuple[str, Path, str]]:
    plan: list[tuple[str, Path, str]] = []
    projected: dict[Path, str | None] = {}

    for change in changes:
        path = resolve_workspace_path(cwd, change.path)
        if path in projected:
            current = projected[path]
        elif path.exists():
            current = path.read_text(encoding="utf-8")
        else:
            current = None

        if change.kind == "add":
            if current is not None:
                raise ValueError(f"cannot add existing file: {change.path}")
            if any(not line.startswith("+") for line in change.body):
                raise ValueError(f"add lines must start with +: {change.path}")
            content = "\n".join(line[1:] for line in change.body)
            if change.body:
                content += "\n"
            projected[path] = content
            plan.append(("add", path, content))
        elif change.kind == "delete":
            if current is None:
                raise ValueError(f"cannot delete missing file: {change.path}")
            projected[path] = None
            plan.append(("delete", path, ""))
        else:
            if current is None:
                raise ValueError(f"cannot update missing file: {change.path}")
            content = _apply_hunks(current, change.body, change.path)
            projected[path] = content
            plan.append(("update", path, content))
    return plan


def _apply_hunks(original: str, body: list[str], path: str) -> str:
    hunks: list[list[str]] = []
    current: list[str] | None = None
    for line in body:
        if line.startswith("@@"):
            if current is not None:
                hunks.append(current)
            current = []
        elif current is None:
            raise ValueError(f"update needs an @@ hunk: {path}")
        else:
            current.append(line)
    if current is not None:
        hunks.append(current)
    if not hunks:
        raise ValueError(f"update contains no hunks: {path}")

    lines = original.splitlines()
    trailing_newline = original.endswith("\n")
    for hunk in hunks:
        old: list[str] = []
        new: list[str] = []
        for line in hunk:
            if not line or line[0] not in {" ", "+", "-"}:
                raise ValueError(f"invalid hunk line in {path}: {line}")
            if line[0] in {" ", "-"}:
                old.append(line[1:])
            if line[0] in {" ", "+"}:
                new.append(line[1:])
        offset = _find_block(lines, old)
        if offset is None:
            raise ValueError(f"hunk does not match {path}")
        lines[offset : offset + len(old)] = new

    content = "\n".join(lines)
    if trailing_newline or lines:
        content += "\n"
    return content


def _find_block(lines: list[str], block: list[str]) -> int | None:
    if not block:
        return len(lines)
    width = len(block)
    for index in range(len(lines) - width + 1):
        if lines[index : index + width] == block:
            return index
    return None
