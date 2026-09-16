"""Mensajería entre el proceso padre y los subagentes."""

from .channel import JsonlChannel, memory_pair
from .protocol import (
    CANCEL,
    LLM_CHUNK,
    LLM_END,
    LLM_ERROR,
    LLM_REQUEST,
    LOG,
    PROGRESS,
    READY,
    RESULT,
    TASK,
    TOOL_REQUEST,
    TOOL_RESPONSE,
    Envelope,
    ProtocolError,
)

__all__ = [
    "CANCEL", "Envelope", "JsonlChannel", "LLM_CHUNK", "LLM_END", "LLM_ERROR",
    "LLM_REQUEST", "LOG", "PROGRESS", "ProtocolError", "READY", "RESULT",
    "TASK", "TOOL_REQUEST", "TOOL_RESPONSE", "memory_pair",
]
