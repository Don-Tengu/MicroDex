"""Read UTF-8 text inside the active workspace."""

from microdex.agent.state import ToolResult
from microdex.schemas import ReadFileArgs
from microdex.tools.paths import resolve_workspace_path


def read_file(args: ReadFileArgs, cwd: str) -> ToolResult:
    try:
        path = resolve_workspace_path(cwd, args.path)
        return {"ok": True, "output": path.read_text(encoding="utf-8")}
    except (OSError, UnicodeError, ValueError) as exc:
        return {"ok": False, "output": f"{args.path}: {exc}"}
