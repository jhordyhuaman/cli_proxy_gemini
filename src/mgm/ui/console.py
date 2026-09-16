"""Consola con tema propio y renderizadores.

El tema define los estilos que el resto del código usa por nombre. Sin esto,
rich revienta con MissingStyle al encontrar una etiqueta que no conoce — que
es justo el fallo que tenía la versión vieja de mgm.
"""

from __future__ import annotations

import difflib
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

TEMA = Theme(
    {
        "user": "bold cyan",
        "agente": "white",
        "error": "bold red",
        "warning": "yellow",
        "ok": "bold green",
        "tool": "magenta",
        "tool.ok": "green",
        "tool.fail": "red",
        "riesgo.read": "green",
        "riesgo.write": "yellow",
        "riesgo.exec": "bold red",
        "apagado": "dim",
        "marca": "bold cyan",
        "diff.mas": "green",
        "diff.menos": "red",
        "diff.cabecera": "cyan",
    }
)

MAX_SALIDA = 2000


def make_console(**kwargs) -> Console:
    return Console(theme=TEMA, **kwargs)


def acortar(texto: str, limite: int = MAX_SALIDA) -> str:
    if len(texto) <= limite:
        return texto
    return texto[:limite] + f"\n[... {len(texto) - limite} caracteres más ...]"


def render_diff(viejo: str, nuevo: str, ruta: str) -> Text:
    """Diff unificado coloreado. Vacío si no hay cambios."""
    lineas = list(
        difflib.unified_diff(
            viejo.splitlines(), nuevo.splitlines(),
            fromfile=f"{ruta} (antes)", tofile=f"{ruta} (después)", lineterm="", n=3,
        )
    )
    salida = Text()
    for linea in lineas[:200]:
        if linea.startswith("+++") or linea.startswith("---"):
            salida.append(linea + "\n", style="diff.cabecera")
        elif linea.startswith("@@"):
            salida.append(linea + "\n", style="apagado")
        elif linea.startswith("+"):
            salida.append(linea + "\n", style="diff.mas")
        elif linea.startswith("-"):
            salida.append(linea + "\n", style="diff.menos")
        else:
            salida.append(linea + "\n")
    if len(lineas) > 200:
        salida.append(f"[... {len(lineas) - 200} líneas de diff más ...]\n", style="apagado")
    return salida


def diff_de_llamada(call, workspace: Path) -> Text | None:
    """Para write_file/edit: qué cambiaría si se autoriza."""
    ruta_cruda = call.args.get("path")
    if not ruta_cruda or call.name not in ("write_file", "edit"):
        return None
    try:
        destino = (workspace / ruta_cruda).resolve()
        viejo = destino.read_text(encoding="utf-8") if destino.is_file() else ""
    except (OSError, ValueError):
        return None

    if call.name == "write_file":
        nuevo = call.args.get("content", "")
    else:
        from ..tools.edit import parse_edit_block

        try:
            buscar, reemplazo = parse_edit_block(call.args.get("block", ""))
        except ValueError:
            return None
        if buscar not in viejo:
            return None
        todas = (call.args.get("replace_all") or "").lower() == "true"
        nuevo = viejo.replace(buscar, reemplazo) if todas else viejo.replace(buscar, reemplazo, 1)

    if viejo == nuevo:
        return None
    return render_diff(viejo, nuevo, ruta_cruda)


def panel_resultado(nombre: str, ok: bool, salida: str) -> Panel:
    estilo = "tool.ok" if ok else "tool.fail"
    marca = "✓" if ok else "✗"
    return Panel(
        Text(acortar(salida.strip()) or "(sin salida)"),
        title=f"[{estilo}]{marca} {nombre}[/{estilo}]",
        border_style=estilo,
        title_align="left",
    )
