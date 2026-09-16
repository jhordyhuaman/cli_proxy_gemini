"""read_file: lectura de texto con paginado por líneas."""

from __future__ import annotations

from .base import Tool, ToolContext, ToolResult, resolve_read_path

MAX_BYTES = 1_000_000
_SNIFF_BYTES = 8192


class ReadFileTool(Tool):
    name = "read_file"
    description = "Lee un archivo de texto; soporta offset/limit de líneas"
    body_param = None
    parameters_schema = {
        "path": "ruta del archivo (relativa al workspace o absoluta existente)",
        "offset": "línea inicial, 1-based (opcional)",
        "limit": "máximo de líneas a devolver (opcional)",
    }
    required_params = ("path",)
    risk = "read"
    delegable = True

    async def execute(self, args: dict[str, str], context: ToolContext) -> ToolResult:
        path = resolve_read_path(context.workspace, args["path"])
        if not path.is_file():
            return ToolResult(False, f"[ERROR] no existe o no es un archivo: {args['path']}")
        size = path.stat().st_size
        if size > MAX_BYTES:
            return ToolResult(
                False,
                f"[ERROR] archivo demasiado grande ({size} bytes > {MAX_BYTES}); "
                "usa grep para localizar la parte relevante",
            )
        with path.open("rb") as fh:
            if b"\x00" in fh.read(_SNIFF_BYTES):
                return ToolResult(False, f"[ERROR] archivo binario rechazado: {args['path']}")
        try:
            offset = max(int(args.get("offset") or "1"), 1)
            limit = int(args["limit"]) if args.get("limit") else None
        except ValueError:
            return ToolResult(False, "[ERROR] offset/limit deben ser enteros")

        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        end = None if limit is None else offset - 1 + limit
        chunk = lines[offset - 1 : end]
        header = f"[{args['path']} — líneas {offset}–{offset - 1 + len(chunk)} de {len(lines)}]"
        return ToolResult(True, header + "\n" + "\n".join(chunk))
