"""Reglas de permiso y su sintaxis.

Una regla es ``herramienta(patrón)`` o ``herramienta`` a secas (cualquier uso).
El patrón se compara contra el *sujeto* de la llamada — el comando para
``bash``, la ruta para las herramientas de archivo — con dos formas::

    bash(git status:*)     prefijo: el comando empieza por "git status"
    bash(npm test)         exacto
    write_file(src/**)     glob estilo fnmatch sobre la ruta relativa
    read_file              la herramienta entera, sin restricción

Las reglas de denegación siempre ganan sobre las de permiso.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path

_PREFIX_MARK = ":*"


class RuleError(ValueError):
    """Regla mal escrita."""


@dataclass(frozen=True)
class Rule:
    tool: str
    pattern: str | None = None

    @classmethod
    def parse(cls, raw: str) -> "Rule":
        text = raw.strip()
        if not text:
            raise RuleError("regla vacía")
        if "(" not in text:
            if ")" in text:
                raise RuleError(f"regla mal formada: {raw!r}")
            return cls(text)
        if not text.endswith(")"):
            raise RuleError(f"regla mal formada, falta ')': {raw!r}")
        tool, _, rest = text.partition("(")
        tool = tool.strip()
        if not tool:
            raise RuleError(f"regla sin herramienta: {raw!r}")
        return cls(tool, rest[:-1])

    def __str__(self) -> str:
        return self.tool if self.pattern is None else f"{self.tool}({self.pattern})"

    def matches(self, tool: str, subject: str) -> bool:
        if self.tool != tool:
            return False
        if self.pattern is None:
            return True
        pattern = self.pattern
        if pattern.endswith(_PREFIX_MARK):
            return subject.startswith(pattern[: -len(_PREFIX_MARK)])
        return subject == pattern or fnmatch.fnmatch(subject, pattern)


@dataclass
class RuleSet:
    allow: list[Rule] = field(default_factory=list)
    deny: list[Rule] = field(default_factory=list)

    def allows(self, tool: str, subject: str) -> bool:
        return any(r.matches(tool, subject) for r in self.allow)

    def denies(self, tool: str, subject: str) -> bool:
        return any(r.matches(tool, subject) for r in self.deny)

    def add_allow(self, raw: str) -> Rule:
        rule = Rule.parse(raw)
        if rule not in self.allow:
            self.allow.append(rule)
        return rule

    def add_deny(self, raw: str) -> Rule:
        rule = Rule.parse(raw)
        if rule not in self.deny:
            self.deny.append(rule)
        return rule

    def merge(self, other: "RuleSet") -> "RuleSet":
        merged = RuleSet(list(self.allow), list(self.deny))
        for rule in other.allow:
            if rule not in merged.allow:
                merged.allow.append(rule)
        for rule in other.deny:
            if rule not in merged.deny:
                merged.deny.append(rule)
        return merged

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "allow": [str(r) for r in self.allow],
            "deny": [str(r) for r in self.deny],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RuleSet":
        def parse_list(key: str) -> list[Rule]:
            rules: list[Rule] = []
            for raw in data.get(key, []) or []:
                try:
                    rule = Rule.parse(str(raw))
                except RuleError:
                    continue
                if rule not in rules:
                    rules.append(rule)
            return rules

        return cls(allow=parse_list("allow"), deny=parse_list("deny"))


def load_ruleset(path: Path) -> RuleSet:
    if not path.is_file():
        return RuleSet()
    try:
        with path.open("r", encoding="utf-8") as fh:
            return RuleSet.from_dict(json.load(fh))
    except (json.JSONDecodeError, OSError):
        return RuleSet()


def save_ruleset(path: Path, ruleset: RuleSet) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(ruleset.to_dict(), fh, indent=2, ensure_ascii=False)
    return path
