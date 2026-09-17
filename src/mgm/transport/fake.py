"""Transporte falso, determinista y sin red. Es el que usan todos los tests."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Iterable, Union

from .base import Chunk, Health, Message

ScriptEntry = Union[str, Iterable[str], BaseException]


class FakeTransport:
    name = "fake"

    def __init__(self, script: Iterable[ScriptEntry] | None = None, *, chunk_delay: float = 0.0):
        self._script = list(script) if script is not None else None
        self._index = 0
        self.chunk_delay = chunk_delay
        #: El `state` recibido en cada llamada a stream(), en orden. Para que
        #: los tests puedan comprobar qué le llega al transporte.
        self.estados_recibidos: list[dict | None] = []

    async def stream(
        self, messages: list[Message], *, state: dict | None = None
    ) -> AsyncIterator[Chunk]:
        self.estados_recibidos.append(state)
        entry: ScriptEntry
        if self._script is not None and self._index < len(self._script):
            entry = self._script[self._index]
            self._index += 1
        else:
            last = next((m.content for m in reversed(messages) if m.role == "user"), "")
            entry = f"[fake] Eco sin red: {last}"

        if isinstance(entry, BaseException):
            raise entry

        pieces = [entry] if isinstance(entry, str) else list(entry)
        for piece in pieces:
            if isinstance(piece, BaseException):
                raise piece
            if self.chunk_delay:
                await asyncio.sleep(self.chunk_delay)
            yield piece if isinstance(piece, Chunk) else Chunk(text=piece)

    async def health(self) -> Health:
        return Health(ok=True, detail="transporte simulado (sin red)")
