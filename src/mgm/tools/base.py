"""Contrato base de herramientas, resultado y política de rutas del workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ToolResult:
    ok: bool
    output: str


@dataclass
class ToolContext:
    workspace: Path


class ToolPathError(Exception):
    """Ruta rechazada por la política del workspace."""


def resolve_read_path(workspace: Path, raw: str) -> Path:
    """Lectura: relativa al workspace, o absoluta si existe en el sistema."""
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    return candidate.resolve()


def resolve_write_path(workspace: Path, raw: str) -> Path:
    """Escritura: SIEMPRE confinada al workspace."""
    resolved = resolve_read_path(workspace, raw)
    root = workspace.resolve()
    if not resolved.is_relative_to(root):
        raise ToolPathError(
            f"ruta fuera del workspace: {raw!r} (las escrituras están confinadas a {root})"
        )
    return resolved


class Tool:
    name: str = ""
    description: str = ""
    body_param: str | None = None
    parameters_schema: dict[str, str] = {}
    required_params: tuple[str, ...] = ()
    #: "read" no toca nada, "write" modifica archivos, "exec" corre comandos.
    risk: str = "read"
    #: Si es True, un subagente puede ejecutarla sin consultar al proceso padre.
    delegable: bool = False

    def validate(self, args: dict[str, str]) -> str | None:
        for param in self.required_params:
            if not args.get(param):
                return f"falta el parámetro obligatorio {param!r}"
        return None

    def subject(self, args: dict[str, str]) -> str:
        """Texto contra el que se evalúan las reglas de permiso."""
        return args.get("path", "")

    def summary(self, args: dict[str, str]) -> str:
        """Una línea legible de lo que la llamada va a hacer."""
        subject = self.subject(args)
        return f"{self.name}: {subject}" if subject else self.name

    async def execute(self, args: dict[str, str], context: ToolContext) -> ToolResult:
        raise NotImplementedError
