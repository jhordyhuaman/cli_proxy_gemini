"""skill: carga el cuerpo completo de una skill bajo demanda (carga progresiva)."""

from __future__ import annotations

from .base import Tool, ToolContext, ToolResult


class SkillTool(Tool):
    name = "skill"
    description = "Carga las instrucciones completas de una skill del catálogo"
    body_param = "name"
    parameters_schema = {
        "name": "(CUERPO del tag) nombre de la skill, tal cual aparece en el catálogo",
    }
    required_params = ("name",)
    risk = "read"
    delegable = True

    def __init__(self, library):
        self.library = library

    def subject(self, args: dict[str, str]) -> str:
        return args.get("name", "")

    def summary(self, args: dict[str, str]) -> str:
        return f"cargar skill: {args.get('name', '')}"

    async def execute(self, args: dict[str, str], context: ToolContext) -> ToolResult:
        nombre = args["name"].strip()
        skill = self.library.get(nombre)
        if skill is None:
            disponibles = ", ".join(self.library.names) or "(ninguna)"
            return ToolResult(
                False, f"[ERROR] no existe la skill {nombre!r}. Disponibles: {disponibles}"
            )
        return ToolResult(True, f"[SKILL {skill.name}]\n\n{skill.body}")
