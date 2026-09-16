"""Cargador de skills.

Una skill es un archivo markdown con cabecera::

    ---
    name: tdd
    description: cuándo y cómo aplicar TDD
    ---

    (instrucciones completas...)

Carga progresiva: en el prompt del sistema solo entran `name` y `description`
de cada skill — unas pocas líneas. El cuerpo completo llega solo cuando el
modelo pide esa skill con la herramienta `skill`. Así puedes tener cincuenta
skills sin quemar el contexto.

Se buscan en tres sitios, y el más específico gana si hay nombres repetidos:
1. las incluidas con mgm
2. ~/.mgm/skills/
3. .mgm/skills/ del proyecto
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

CERCA = "---"
MAX_BYTES = 100_000


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path
    scope: str  # "incluida" | "usuario" | "proyecto"


def parse_frontmatter(texto: str) -> tuple[dict[str, str], str]:
    """Devuelve (metadatos, cuerpo). Sin cabecera válida, metadatos vacíos."""
    lineas = texto.lstrip().splitlines()
    if not lineas or lineas[0].strip() != CERCA:
        return {}, texto.strip()
    meta: dict[str, str] = {}
    for i, linea in enumerate(lineas[1:], start=1):
        if linea.strip() == CERCA:
            return meta, "\n".join(lineas[i + 1 :]).strip()
        clave, sep, valor = linea.partition(":")
        if sep:
            meta[clave.strip().lower()] = valor.strip()
    return {}, texto.strip()


def _leer_skill(path: Path, scope: str) -> Skill | None:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        texto = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    meta, cuerpo = parse_frontmatter(texto)
    nombre = meta.get("name") or path.stem
    if path.name.upper() == "SKILL.MD":
        nombre = meta.get("name") or path.parent.name
    if not cuerpo:
        return None
    return Skill(
        name=nombre,
        description=meta.get("description", ""),
        body=cuerpo,
        path=path,
        scope=scope,
    )


def _archivos(carpeta: Path) -> list[Path]:
    if not carpeta.is_dir():
        return []
    encontrados = sorted(p for p in carpeta.glob("*.md") if p.is_file())
    encontrados += sorted(p for p in carpeta.glob("*/SKILL.md") if p.is_file())
    return encontrados


def builtin_dir() -> Path:
    return Path(__file__).parent / "builtin"


class SkillLibrary:
    def __init__(self, skills: list[Skill] | None = None):
        self._skills: dict[str, Skill] = {}
        for skill in skills or []:
            self._skills[skill.name] = skill

    def add(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: object) -> bool:
        return name in self._skills

    @property
    def names(self) -> list[str]:
        return sorted(self._skills)

    def all(self) -> list[Skill]:
        return [self._skills[n] for n in self.names]

    def render_catalog(self) -> str:
        """Lo único que entra en el prompt: nombre + descripción."""
        if not self._skills:
            return ""
        lineas = [
            "SKILLS DISPONIBLES (cárgalas con "
            '<tool name="skill">nombre</tool> antes de trabajar en algo que cubran):'
        ]
        for skill in self.all():
            desc = skill.description or "(sin descripción)"
            lineas.append(f"  · {skill.name}: {desc}")
        return "\n".join(lineas)


def load_library(
    workspace: Path | None = None,
    home: Path | None = None,
    *,
    include_builtin: bool = True,
) -> SkillLibrary:
    library = SkillLibrary()
    fuentes: list[tuple[Path, str]] = []
    if include_builtin:
        fuentes.append((builtin_dir(), "incluida"))
    if home is not None:
        fuentes.append((home / ".mgm" / "skills", "usuario"))
    if workspace is not None:
        fuentes.append((workspace / ".mgm" / "skills", "proyecto"))

    for carpeta, scope in fuentes:
        for path in _archivos(carpeta):
            skill = _leer_skill(path, scope)
            if skill is not None:
                library.add(skill)
    return library
