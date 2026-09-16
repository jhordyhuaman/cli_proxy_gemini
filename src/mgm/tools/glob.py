"""glob: lista archivos del workspace por patrón, ordenados por mtime."""

from __future__ import annotations

from pathlib import Path

from .base import Tool, ToolContext, ToolResult
from .grep import SKIP_DIRS

MAX_RESULTS = 100


class GlobTool(Tool):
    name = "glob"
    description = "Lista archivos del workspace que coinciden con un patrón glob"
    body_param = "pattern"
    parameters_schema = {
        "pattern": "(CUERPO del tag) patrón glob relativo, p. ej. '**/*.py'",
    }
    required_params = ("pattern",)
    risk = "read"
    delegable = True

    def subject(self, args: dict[str, str]) -> str:
        return args.get("pattern", "")

    async def execute(self, args: dict[str, str], context: ToolContext) -> ToolResult:
        pattern = args["pattern"]
        if Path(pattern).is_absolute():
            return ToolResult(False, "[ERROR] el patrón debe ser relativo al workspace")
        root = context.workspace.resolve()
        try:
            matches = [
                p
                for p in root.glob(pattern)
                if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(root).parts)
            ]
        except (NotImplementedError, ValueError) as exc:
            return ToolResult(False, f"[ERROR] patrón glob inválido: {exc}")

        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        total = len(matches)
        matches = matches[:MAX_RESULTS]
        if not matches:
            return ToolResult(True, f"[sin archivos] patrón {pattern!r}")
        lines = [p.relative_to(root).as_posix() for p in matches]
        header = f"[{len(lines)} archivo(s){f' de {total} — truncado' if total > len(lines) else ''}]"
        return ToolResult(True, header + "\n" + "\n".join(lines))
