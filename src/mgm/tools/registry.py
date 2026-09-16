"""Registro de herramientas: nombre → instancia, documentación y ejecución segura."""

from __future__ import annotations

from dataclasses import dataclass

from .base import Tool, ToolContext, ToolPathError, ToolResult


@dataclass
class ToolCall:
    """Una llamada ya normalizada: atributos del tag + cuerpo fusionados."""

    name: str
    args: dict[str, str]


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> Tool:
        if not tool.name:
            raise ValueError("la herramienta necesita un nombre")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def tools(self) -> list[Tool]:
        return [self._tools[n] for n in self.names]

    def call_from_event(self, name: str, attrs: dict[str, str], body: str) -> ToolCall:
        """Fusiona atributos XML y cuerpo del tag en un único diccionario de args."""
        args = dict(attrs)
        tool = self.get(name)
        if tool is not None and tool.body_param:
            if body or tool.body_param not in args:
                args[tool.body_param] = body
        elif body:
            args.setdefault("body", body)
        return ToolCall(name, args)

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        tool = self.get(call.name)
        if tool is None:
            disponibles = ", ".join(self.names)
            return ToolResult(
                False,
                f"[ERROR] no existe la herramienta {call.name!r}. Disponibles: {disponibles}",
            )
        problem = tool.validate(call.args)
        if problem:
            return ToolResult(False, f"[ERROR] {call.name}: {problem}")
        try:
            return await tool.execute(call.args, context)
        except ToolPathError as exc:
            return ToolResult(False, f"[ERROR] {exc}")
        except Exception as exc:  # una tool rota no puede tumbar el agente
            return ToolResult(False, f"[ERROR] {call.name} falló: {type(exc).__name__}: {exc}")

    def render_docs(self) -> str:
        """Bloque de documentación que se inyecta en el prompt del sistema."""
        bloques: list[str] = []
        for tool in self.tools():
            lineas = [f'<tool name="{tool.name}"> — {tool.description}']
            for param, ayuda in tool.parameters_schema.items():
                marca = "obligatorio" if param in tool.required_params else "opcional"
                lineas.append(f"    · {param} ({marca}): {ayuda}")
            bloques.append("\n".join(lineas))
        return "\n\n".join(bloques)


def default_registry(skills=None, *, task_runner=None) -> ToolRegistry:
    """Registro estándar.

    `skills` añade la herramienta `skill` (carga progresiva del catálogo).
    `task_runner` añade `task`, que delega trabajo en un subagente.
    """
    from .bash import BashTool
    from .edit import EditTool
    from .glob import GlobTool
    from .grep import GrepTool
    from .read_file import ReadFileTool
    from .write_file import WriteFileTool

    registry = ToolRegistry(
        [
            ReadFileTool(),
            WriteFileTool(),
            EditTool(),
            GrepTool(),
            GlobTool(),
            BashTool(),
        ]
    )
    if skills is not None:
        from .skill import SkillTool

        registry.register(SkillTool(skills))
    if task_runner is not None:
        from .task import TaskTool

        registry.register(TaskTool(task_runner))
    return registry
