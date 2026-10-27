"""Discover project instructions the same way a coding agent sees them.

Microdex snapshots project instructions when a session is created. Starting
at the project root, each directory down to the working directory may
contribute one file. AGENTS.override.md wins over AGENTS.md in that directory.

This mirrors the important behavior of codex-rs/core/src/agents_md.rs without
copying Codex's configurable project-root marker machinery.
"""

from pathlib import Path

PREFERRED_NAME = "AGENTS.override.md"
FALLBACK_NAME = "AGENTS.md"
# pyproject.toml keeps instruction discovery useful in teaching copies that
# were generated without Git metadata.
ROOT_MARKERS = (".git", "pyproject.toml")


def find_project_root(cwd: Path) -> Path:
    """Return the nearest ancestor carrying a project-root marker."""

    current = cwd.resolve()
    for candidate in (current, *current.parents):
        if any((candidate / marker).exists() for marker in ROOT_MARKERS):
            return candidate
    return current


def instruction_files(cwd: Path) -> list[Path]:
    """Return instruction files from project root to cwd, in merge order."""

    resolved = cwd.resolve()
    root = find_project_root(resolved)
    relative = resolved.relative_to(root)
    directories = [root]
    current = root
    for part in relative.parts:
        current = current / part
        directories.append(current)

    found: list[Path] = []
    for directory in directories:
        preferred = directory / PREFERRED_NAME
        fallback = directory / FALLBACK_NAME
        if preferred.is_file():
            found.append(preferred)
        elif fallback.is_file():
            found.append(fallback)
    return found


def load_project_instructions(cwd: Path | str) -> str:
    """Read and concatenate the instruction snapshot for one session."""

    sections: list[str] = []
    for path in instruction_files(Path(cwd)):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            sections.append(f"# Instructions from {path}\n\n{text}")
    return "\n\n".join(sections)
