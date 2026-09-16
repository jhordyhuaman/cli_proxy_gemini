"""Autocompletado del REPL: /comandos y @archivos."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit.completion import Completer, Completion

MAX_ARCHIVOS = 200
SALTAR = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache"}


class MgmCompleter(Completer):
    def __init__(self, comandos: dict[str, str], workspace: Path):
        self.comandos = comandos
        self.workspace = workspace

    def _archivos(self, prefijo: str):
        encontrados = 0
        for path in sorted(self.workspace.rglob("*")):
            if encontrados >= MAX_ARCHIVOS:
                return
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(self.workspace)
            except ValueError:
                continue
            if SALTAR.intersection(rel.parts):
                continue
            texto = rel.as_posix()
            if texto.startswith(prefijo):
                encontrados += 1
                yield texto

    def get_completions(self, document, complete_event):
        texto = document.text_before_cursor
        palabra = texto.split()[-1] if texto.split() and not texto.endswith(" ") else ""

        if texto.startswith("/") and " " not in texto:
            for nombre, ayuda in sorted(self.comandos.items()):
                if nombre.startswith(texto):
                    yield Completion(nombre, start_position=-len(texto), display_meta=ayuda)
            return

        if palabra.startswith("@"):
            prefijo = palabra[1:]
            for ruta in self._archivos(prefijo):
                yield Completion("@" + ruta, start_position=-len(palabra))
