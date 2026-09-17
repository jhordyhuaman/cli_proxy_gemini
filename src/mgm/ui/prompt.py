"""La pregunta de permiso: qué se va a hacer y qué puedes responder."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit.shortcuts import PromptSession
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from ..agent.loop import ALLOW_ONCE, ALLOW_PROJECT, ALLOW_SESSION, DENY
from .console import diff_de_llamada

OPCIONES = {
    "s": ALLOW_ONCE,
    "si": ALLOW_ONCE,
    "sí": ALLOW_ONCE,
    "1": ALLOW_ONCE,
    "": ALLOW_ONCE,
    "a": ALLOW_SESSION,
    "2": ALLOW_SESSION,
    "p": ALLOW_PROJECT,
    "3": ALLOW_PROJECT,
    "n": DENY,
    "no": DENY,
    "4": DENY,
}

#: Menú numerado, en el orden en que se ofrece. Las letras de siempre
#: (s/a/p/n) siguen valiendo, pero lo que se muestra son números: es lo que
#: la gente espera de un prompt de terminal y no hay que adivinar nada.
MENU = (
    ("1", "Sí", "(Enter)"),
    ("2", "Sí, y no preguntes más en esta sesión", ""),
    ("3", "Sí, y no preguntes más en este proyecto", ""),
    ("4", "No", ""),
)


class PermissionAsker:
    """Pregunta al usuario. Devuelve la respuesta que el loop entiende."""

    def __init__(self, console: Console, session: PromptSession, workspace: Path):
        self.console = console
        self.session = session
        self.workspace = workspace

    async def __call__(self, call, resumen: str, decision) -> str:
        diff = diff_de_llamada(call, self.workspace)
        if diff is not None:
            self.console.print(
                Panel(
                    diff,
                    title=f"[warning]{resumen}[/warning]",
                    border_style="warning",
                    title_align="left",
                )
            )
        else:
            self.console.print(
                Panel(
                    Text(resumen),
                    title="[warning]¿Autorizas esta acción?[/warning]",
                    border_style="warning",
                    title_align="left",
                )
            )

        for tecla, etiqueta, pista in MENU:
            sufijo = f" [apagado]{pista}[/apagado]" if pista else ""
            self.console.print(f"  [bold]{tecla}.[/bold] {etiqueta}{sufijo}")
        try:
            respuesta = (await self.session.prompt_async("  › ")).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return DENY
        return OPCIONES.get(respuesta, DENY)
