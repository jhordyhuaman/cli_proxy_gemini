"""write_file: escribe un archivo completo (crea directorios padre)."""

from __future__ import annotations

from .base import Tool, ToolContext, ToolResult, resolve_write_path


class WriteFileTool(Tool):
    name = "write_file"
    description = "Escribe un archivo completo; crea los directorios padre si hacen falta"
    body_param = "content"
    parameters_schema = {
        "path": "ruta destino, siempre dentro del workspace",
        "content": "(CUERPO del tag) contenido completo del archivo",
    }
    required_params = ("path", "content")
    risk = "write"

    async def execute(self, args: dict[str, str], context: ToolContext) -> ToolResult:
        path = resolve_write_path(context.workspace, args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        return ToolResult(
            True, f"[ÉXITO] Archivo {path} escrito ({len(args['content'])} caracteres)."
        )
