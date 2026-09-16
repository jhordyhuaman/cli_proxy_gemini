"""Protocolo de mensajería entre el proceso padre y los subagentes.

Un mensaje por línea, JSON, sobre stdin/stdout del proceso hijo. Formato::

    {"v": 1, "type": "tool_request", "id": "7", "payload": {...}}

Quién manda qué:

    padre → hijo : task, llm_chunk, llm_end, llm_error, tool_response, cancel
    hijo  → padre: ready, llm_request, tool_request, progress, result, log

El hijo NO habla con el modelo ni ejecuta herramientas peligrosas por su
cuenta: se las pide al padre. Así la cookie, la cuota y los permisos del
usuario tienen un único guardián, aunque corran cinco subagentes a la vez.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

VERSION = 1

# padre → hijo
TASK = "task"
LLM_CHUNK = "llm_chunk"
LLM_END = "llm_end"
LLM_ERROR = "llm_error"
TOOL_RESPONSE = "tool_response"
CANCEL = "cancel"

# hijo → padre
READY = "ready"
LLM_REQUEST = "llm_request"
TOOL_REQUEST = "tool_request"
PROGRESS = "progress"
RESULT = "result"
LOG = "log"

TIPOS = {
    TASK, LLM_CHUNK, LLM_END, LLM_ERROR, TOOL_RESPONSE, CANCEL,
    READY, LLM_REQUEST, TOOL_REQUEST, PROGRESS, RESULT, LOG,
}


class ProtocolError(ValueError):
    """Línea que no es un mensaje válido del protocolo."""


@dataclass
class Envelope:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = ""
    v: int = VERSION

    def encode(self) -> bytes:
        dato = {"v": self.v, "type": self.type, "id": self.id, "payload": self.payload}
        return (json.dumps(dato, ensure_ascii=False) + "\n").encode("utf-8")

    @classmethod
    def decode(cls, linea: bytes | str) -> "Envelope":
        texto = linea.decode("utf-8") if isinstance(linea, bytes) else linea
        texto = texto.strip()
        if not texto:
            raise ProtocolError("línea vacía")
        try:
            dato = json.loads(texto)
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"JSON inválido: {exc}") from None
        if not isinstance(dato, dict):
            raise ProtocolError("el mensaje debe ser un objeto JSON")
        tipo = dato.get("type")
        if tipo not in TIPOS:
            raise ProtocolError(f"tipo de mensaje desconocido: {tipo!r}")
        payload = dato.get("payload") or {}
        if not isinstance(payload, dict):
            raise ProtocolError("payload debe ser un objeto")
        return cls(type=tipo, payload=payload, id=str(dato.get("id", "")), v=int(dato.get("v", VERSION)))
