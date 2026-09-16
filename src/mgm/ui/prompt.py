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

AYUDA = (
    "[bold]s[/bold]í (una vez) · "
    "[bold]a[/bold]utorizar toda la sesión · "
    "[bold]p[/bold]ermitir siempre en este proyecto · "
    "[bold]n[/bold]o"
)


class PermissionAsker:
    """Pregunta al usuario. Devuelve la respuesta que el loop entiende."""

    def __init__(self, console: Console, session: PromptSession, workspace: Path):
        self.console = console
        self.session = session
        self.workspace = workspace

    async def __call__(self, call, resumen: str, decision) -> str:
        cuerpo = Text(resumen)
        diff = diff_de_llamada(call, self.workspace)
        self.console.print(
            Panel(
                cuerpo,
                title="[warning]¿Autorizas esta acción?[/warning]",
                border_style="warning",
                title_align="left",
            )
        )
        if diff is not None:
            self.console.print(diff)
        self.console.print(f"  {AYUDA}")
        try:
            respuesta = (await self.session.prompt_async("¿permites? [s/a/p/n] ")).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return DENY
        return OPCIONES.get(respuesta, DENY)
