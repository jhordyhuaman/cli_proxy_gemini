"""grep: búsqueda regex sobre archivos de texto del workspace."""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePath

from .base import Tool, ToolContext, ToolResult, resolve_read_path

SKIP_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv"}
MAX_MATCHES = 200


class GrepTool(Tool):
    name = "grep"
    description = "Busca un patrón regex en archivos de texto; salida paginada con límite"
    body_param = "pattern"
    parameters_schema = {
        "pattern": "(CUERPO del tag) expresión regular a buscar",
        "path": "archivo o directorio donde buscar (opcional, defecto: workspace)",
        "glob": "filtro de archivos, p. ej. '*.py' (opcional)",
    }
    required_params = ("pattern",)
    risk = "read"
    delegable = True

    def subject(self, args: dict[str, str]) -> str:
        return args.get("path") or "."

    def _iter_files(self, root: Path, glob_pattern: str | None):
        if root.is_file():
            yield root
            return
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for filename in filenames:
                path = Path(dirpath) / filename
                rel = path.relative_to(root).as_posix() if root.is_dir() else filename
                if glob_pattern and not PurePath(rel).match(glob_pattern):
                    continue
                yield path

    async def execute(self, args: dict[str, str], context: ToolContext) -> ToolResult:
        try:
            regex = re.compile(args["pattern"])
        except re.error as exc:
            return ToolResult(False, f"[ERROR] regex inválida: {exc}")

        root = resolve_read_path(context.workspace, args.get("path") or ".")
        if not root.exists():
            return ToolResult(False, f"[ERROR] no existe la ruta: {args.get('path') or '.'}")

        glob_pattern = args.get("glob") or None
        matches: list[str] = []
        truncated = False
        for path in self._iter_files(root, glob_pattern):
            try:
                with path.open("rb") as fh:
                    if b"\x00" in fh.read(8192):
                        continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append(f"{path.relative_to(root) if root.is_dir() else path.name}:{lineno}: {line.strip()}")
                    if len(matches) >= MAX_MATCHES:
                        truncated = True
                        break
            if truncated:
                break

        if not matches:
            return ToolResult(True, f"[sin coincidencias] patrón {args['pattern']!r}")
        header = f"[{len(matches)} coincidencia(s){' — truncado' if truncated else ''}]"
        return ToolResult(True, header + "\n" + "\n".join(matches))
