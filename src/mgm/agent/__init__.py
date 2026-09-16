"""Núcleo del agente: prompt, loop y eventos."""

from .events import (
    AssistantText,
    EventRecorder,
    IterationStart,
    LoopError,
    ToolDecided,
    ToolExecuted,
    ToolRequested,
    TurnEnd,
    TurnStart,
)
from .loop import ALLOW_ONCE, ALLOW_PROJECT, ALLOW_SESSION, DENY, AgentLoop, TurnOutcome
from .prompts import build_system_prompt
from .subagent import SubagentResult, SubagentSupervisor

__all__ = [
    "ALLOW_ONCE",
    "ALLOW_PROJECT",
    "ALLOW_SESSION",
    "AgentLoop",
    "AssistantText",
    "DENY",
    "EventRecorder",
    "SubagentResult",
    "SubagentSupervisor",
    "IterationStart",
    "LoopError",
    "ToolDecided",
    "ToolExecuted",
    "ToolRequested",
    "TurnEnd",
    "TurnOutcome",
    "TurnStart",
    "build_system_prompt",
]
