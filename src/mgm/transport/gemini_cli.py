"""Respaldo futuro: delegar en el binario oficial `gemini` CLI si existe en el sistema.

Planificado para una fase posterior; hoy no implementado a propósito.
"""

from __future__ import annotations

from typing import AsyncIterator

from .base import Chunk, Health, Message

_MESSAGE = (
    "GeminiCLITransport es un respaldo planificado y aún no está implementado; "
    "usa el transporte 'g4f' o 'fake'."
)


class GeminiCLITransport:
    name = "gemini-cli"

    async def stream(
        self, messages: list[Message], *, state: dict | None = None
    ) -> AsyncIterator[Chunk]:
        raise NotImplementedError(_MESSAGE)
        yield

    async def health(self) -> Health:
        return Health(ok=False, detail=_MESSAGE)
