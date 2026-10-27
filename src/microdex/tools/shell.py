"""Run one bounded shell command in the active workspace."""

import subprocess

from microdex import constants
from microdex.agent.state import ToolResult
from microdex.schemas import ExecCommandArgs
from microdex.tools.paths import resolve_workspace_path, workspace_root


def _decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode("utf-8", errors="replace")


def _cap(output: bytes) -> str:
    limit = constants.EXEC_OUTPUT_CAP_BYTES
    if len(output) <= limit:
        return output.decode("utf-8", errors="replace")
    return (
        output[:limit].decode("utf-8", errors="replace") + constants.TRUNCATION_MARKER
    )


def exec_command(args: ExecCommandArgs, cwd: str) -> ToolResult:
    try:
        root = workspace_root(cwd)
        workdir = resolve_workspace_path(cwd, args.workdir) if args.workdir else root
        if not workdir.is_dir():
            return {"ok": False, "output": f"not a directory: {workdir}"}
        completed = subprocess.run(
            args.cmd,
            cwd=workdir,
            shell=True,
            executable="/bin/sh",
            capture_output=True,
            timeout=constants.EXEC_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial = _decode(exc.stdout) + _decode(exc.stderr)
        return {
            "ok": False,
            "output": (
                f"{partial}\ncommand timed out "
                f"(timeout {constants.EXEC_TIMEOUT_SECONDS} seconds)"
            ).lstrip(),
        }
    except (OSError, ValueError) as exc:
        return {"ok": False, "output": str(exc)}

    output = _cap(completed.stdout + completed.stderr)
    if completed.returncode == 0:
        return {"ok": True, "output": output}
    if not output:
        output = f"command exited with status {completed.returncode}"
    return {"ok": False, "output": output}
