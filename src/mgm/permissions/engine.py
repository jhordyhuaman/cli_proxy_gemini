"""Motor de permisos: decide si una llamada a herramienta se permite, se pregunta o se niega.

Orden de decisión (el primero que aplica, gana):

1. Regla de denegación  → NIEGA siempre, en cualquier modo.
2. Modo ``plan``        → NIEGA todo lo que escriba o ejecute (solo lectura).
3. Regla de permiso     → PERMITE.
4. Defecto del modo     → según el riesgo de la herramienta.

El motor nunca habla con el usuario: devuelve ``ask`` y quien llama decide
cómo preguntar. Eso lo hace testeable sin terminal y reutilizable desde los
subagentes, que preguntan a través del proceso padre.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .rules import RuleSet, load_ruleset, save_ruleset

Outcome = Literal["allow", "ask", "deny"]
Risk = Literal["read", "write", "exec"]

MODES = ("plan", "ask", "auto-edits", "libre")
DEFAULT_MODE = "ask"

_MODE_DEFAULTS: dict[str, dict[str, Outcome]] = {
    "plan": {"read": "allow", "write": "deny", "exec": "deny"},
    "ask": {"read": "allow", "write": "ask", "exec": "ask"},
    "auto-edits": {"read": "allow", "write": "allow", "exec": "ask"},
    "libre": {"read": "allow", "write": "allow", "exec": "allow"},
}

MODE_HELP = {
    "plan": "solo lectura: investiga y propone, no toca nada",
    "ask": "pregunta antes de escribir o ejecutar (defecto)",
    "auto-edits": "edita archivos sin preguntar, pregunta para ejecutar",
    "libre": "no pregunta nada (úsalo solo en carpetas desechables)",
}


class ModeError(ValueError):
    pass


@dataclass
class Decision:
    outcome: Outcome
    reason: str

    @property
    def allowed(self) -> bool:
        return self.outcome == "allow"


class PermissionEngine:
    def __init__(
        self,
        mode: str = DEFAULT_MODE,
        *,
        user_rules: RuleSet | None = None,
        project_rules: RuleSet | None = None,
        session_rules: RuleSet | None = None,
        user_path: Path | None = None,
        project_path: Path | None = None,
    ):
        self.mode = self._check_mode(mode)
        self.user_rules = user_rules or RuleSet()
        self.project_rules = project_rules or RuleSet()
        self.session_rules = session_rules or RuleSet()
        self.user_path = user_path
        self.project_path = project_path

    @staticmethod
    def _check_mode(mode: str) -> str:
        if mode not in MODES:
            raise ModeError(f"modo desconocido: {mode!r}. Opciones: {', '.join(MODES)}")
        return mode

    def set_mode(self, mode: str) -> str:
        self.mode = self._check_mode(mode)
        return self.mode

    @property
    def effective(self) -> RuleSet:
        return self.user_rules.merge(self.project_rules).merge(self.session_rules)

    def evaluate(self, tool: str, risk: Risk, subject: str = "") -> Decision:
        rules = self.effective
        if rules.denies(tool, subject):
            return Decision("deny", f"hay una regla que prohíbe {tool} sobre {subject!r}")
        if self.mode == "plan" and risk != "read":
            return Decision(
                "deny", "estás en modo plan (solo lectura): no puedo escribir ni ejecutar"
            )
        if rules.allows(tool, subject):
            return Decision("allow", f"permitido por regla guardada para {tool}")
        outcome = _MODE_DEFAULTS[self.mode].get(risk, "ask")
        return Decision(outcome, f"defecto del modo '{self.mode}' para riesgo '{risk}'")

    def remember(self, raw_rule: str, scope: str = "session") -> str:
        """Guarda una regla de permiso. scope: session | project | user."""
        if scope == "session":
            rule = self.session_rules.add_allow(raw_rule)
        elif scope == "project":
            rule = self.project_rules.add_allow(raw_rule)
            if self.project_path:
                save_ruleset(self.project_path, self.project_rules)
        elif scope == "user":
            rule = self.user_rules.add_allow(raw_rule)
            if self.user_path:
                save_ruleset(self.user_path, self.user_rules)
        else:
            raise ValueError(f"alcance desconocido: {scope!r} (session|project|user)")
        return str(rule)

    def deny_rule(self, raw_rule: str, scope: str = "session") -> str:
        target = {
            "session": self.session_rules,
            "project": self.project_rules,
            "user": self.user_rules,
        }.get(scope)
        if target is None:
            raise ValueError(f"alcance desconocido: {scope!r} (session|project|user)")
        rule = target.add_deny(raw_rule)
        if scope == "project" and self.project_path:
            save_ruleset(self.project_path, self.project_rules)
        if scope == "user" and self.user_path:
            save_ruleset(self.user_path, self.user_rules)
        return str(rule)


def permissions_paths(home: Path, workspace: Path) -> tuple[Path, Path]:
    return home / ".mgm" / "permissions.json", workspace / ".mgm" / "permissions.json"


def load_engine(mode: str, home: Path, workspace: Path) -> PermissionEngine:
    user_path, project_path = permissions_paths(home, workspace)
    return PermissionEngine(
        mode,
        user_rules=load_ruleset(user_path),
        project_rules=load_ruleset(project_path),
        user_path=user_path,
        project_path=project_path,
    )
