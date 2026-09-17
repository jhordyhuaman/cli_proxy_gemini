"""Puerto de transporte: interfaz reemplazable entre mgm y el proveedor de inferencia."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable


@dataclass
class Message:
    role: str
    content: str


@dataclass
class Chunk:
    text: str
    #: Estado de conversación opaco (p. ej. el conversation_id de Gemini) que
    #: el transporte quiera que se le reenvíe en la próxima llamada. Los
    #: transportes que no lo soporten simplemente lo dejan en None.
    state: dict | None = None


@dataclass
class Health:
    ok: bool
    detail: str = ""


class TransportError(Exception):
    """Fallo del endpoint o de la red; el broker puede reintentar."""


class AuthError(TransportError):
    """Cookie vencida o rechazada; no se reintenta, hay que re-pegar la cookie."""


@runtime_checkable
class Transport(Protocol):
    name: str

    def stream(
        self, messages: list[Message], *, state: dict | None = None
    ) -> AsyncIterator[Chunk]: ...

    async def health(self) -> Health: ...
