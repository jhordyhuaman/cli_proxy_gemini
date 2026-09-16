"""task: delega una tarea en un subagente con su propio contexto."""

from __future__ import annotations

from .base import Tool, ToolContext, ToolResult


class TaskTool(Tool):
    name = "task"
    description = (
        "Delega una tarea larga o exploratoria en un subagente aislado; "
        "vuelve solo su informe final, sin ensuciar tu contexto"
    )
    body_param = "prompt"
    parameters_schema = {
        "prompt": "(CUERPO del tag) el encargo completo y autocontenido para el subagente",
        "label": "nombre corto para identificarlo en la terminal (opcional)",
        "max_iterations": "tope de iteraciones del subagente (opcional, defecto 15)",
    }
    required_params = ("prompt",)
    risk = "exec"

    def __init__(self, runner):
        self.runner = runner

    def subject(self, args: dict[str, str]) -> str:
        return args.get("label", "") or args.get("prompt", "")[:60]

    def summary(self, args: dict[str, str]) -> str:
        etiqueta = args.get("label") or "sin nombre"
        return f"lanzar subagente '{etiqueta}'"

    async def execute(self, args: dict[str, str], context: ToolContext) -> ToolResult:
        try:
            max_iter = int(args.get("max_iterations") or 15)
        except ValueError:
            return ToolResult(False, "[ERROR] max_iterations debe ser un entero")
        resultado = await self.runner(
            args["prompt"], label=args.get("label", ""), max_iterations=max_iter
        )
        return ToolResult(resultado.ok, resultado.render())
