"""Search workspace text with ripgrep."""

import subprocess

from microdex.agent.state import ToolResult
from microdex.schemas import RgArgs
from microdex.tools.paths import resolve_workspace_path, workspace_root


def rg(args: RgArgs, cwd: str) -> ToolResult:
    try:
        root = workspace_root(cwd)
        target = resolve_workspace_path(cwd, args.path, default=".")
        relative = target.relative_to(root)
        command = [
            "rg",
            "--line-number",
            "--no-heading",
            "--color=never",
        ]
        if args.glob:
            command.extend(["--glob", args.glob])
        command.extend(["--", args.pattern, str(relative or ".")])
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError) as exc:
        return {"ok": False, "output": str(exc)}

    output = completed.stdout + completed.stderr
    if completed.returncode in (0, 1):
        return {"ok": True, "output": output}
    return {
        "ok": False,
        "output": output or f"rg exited with status {completed.returncode}",
    }
