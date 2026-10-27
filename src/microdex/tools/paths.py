"""Path validation shared by workspace tools."""

from pathlib import Path


def workspace_root(cwd: str) -> Path:
    root = Path(cwd).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"working directory does not exist: {root}")
    return root


def resolve_workspace_path(cwd: str, value: str, *, default: str = ".") -> Path:
    root = workspace_root(cwd)
    raw = Path(value or default).expanduser()
    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes working directory: {value}") from exc
    return candidate
