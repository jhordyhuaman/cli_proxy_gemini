"""Eventos que el loop emite hacia quien lo observa (UI, logs, subagentes)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..permissions import Decision
from ..tools import ToolCall, ToolResult


@dataclass
class TurnStart:
    user_text: str
    iteration: int = 0


@dataclass
class AssistantText:
    text: str


@dataclass
class ToolRequested:
    call: ToolCall
    summary: str
    risk: str


@dataclass
class ToolDecided:
    call: ToolCall
    decision: Decision
    asked: bool = False


@dataclass
class ToolExecuted:
    call: ToolCall
    result: ToolResult


@dataclass
class IterationStart:
    iteration: int
    max_iterations: int


@dataclass
class TurnEnd:
    reason: str
    iterations: int
    text: str = ""


@dataclass
class LoopError:
    kind: str
    detail: str


Event = (
    TurnStart
    | AssistantText
    | ToolRequested
    | ToolDecided
    | ToolExecuted
    | IterationStart
    | TurnEnd
    | LoopError
)


@dataclass
class EventRecorder:
    """Observador de pruebas: guarda todo lo que pasó en el turno."""

    events: list = field(default_factory=list)

    def __call__(self, event) -> None:
        self.events.append(event)

    def of(self, *tipos):
        return [e for e in self.events if isinstance(e, tipos)]

    @property
    def text(self) -> str:
        return "".join(e.text for e in self.of(AssistantText))
