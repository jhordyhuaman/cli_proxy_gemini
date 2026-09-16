"""Memoria de proyecto: archivos MGM.md.

Se cargan de lo general a lo específico y se concatenan:

1. ~/.mgm/MGM.md            — tus preferencias, en todas las carpetas
2. .../MGM.md de los padres — desde el ancestro más lejano hacia abajo
3. ./MGM.md                 — el del proyecto actual, el que más manda

Es el equivalente de CLAUDE.md: lo que mgm debe saber sin que se lo repitas.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

NOMBRE = "MGM.md"
MAX_BYTES = 64_000


@dataclass
class MemoryFile:
    path: Path
    content: str
    scope: str  # "usuario" | "ancestro" | "proyecto"


def _leer(path: Path, scope: str) -> MemoryFile | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        texto = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return MemoryFile(path, texto, scope) if texto else None


def discover(workspace: Path, home: Path | None = None) -> list[MemoryFile]:
    home = home or Path.home()
    encontrados: list[MemoryFile] = []

    usuario = _leer(home / ".mgm" / NOMBRE, "usuario")
    if usuario:
        encontrados.append(usuario)

    workspace = workspace.resolve()
    ancestros = [p for p in workspace.parents if p != home]
    for carpeta in reversed(ancestros):
        archivo = _leer(carpeta / NOMBRE, "ancestro")
        if archivo:
            encontrados.append(archivo)

    propio = _leer(workspace / NOMBRE, "proyecto")
    if propio:
        encontrados.append(propio)
    return encontrados


def load_memory(workspace: Path, home: Path | None = None) -> str:
    archivos = discover(workspace, home)
    if not archivos:
        return ""
    bloques = [f"--- {f.path} ({f.scope}) ---\n{f.content}" for f in archivos]
    return "\n\n".join(bloques)
