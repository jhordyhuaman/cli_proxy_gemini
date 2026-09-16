"""Interfaz de terminal: tema, diffs, autocompletado y preguntas de permiso."""

from .completer import MgmCompleter
from .console import TEMA, acortar, diff_de_llamada, make_console, panel_resultado, render_diff
from .prompt import PermissionAsker

__all__ = [
    "MgmCompleter",
    "PermissionAsker",
    "TEMA",
    "acortar",
    "diff_de_llamada",
    "make_console",
    "panel_resultado",
    "render_diff",
]
