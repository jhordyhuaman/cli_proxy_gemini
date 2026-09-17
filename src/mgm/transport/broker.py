"""Broker sobre el puerto de transporte.

Una sola inferencia a la vez (candado), reintentos con backoff exponencial ante
fallos del endpoint, y sin reintentos ante errores de autenticación.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Awaitable, Callable

from .base import AuthError, Chunk, Health, Message, Transport, TransportError


class InferenceBroker:
    def __init__(
        self,
        transport: Transport,
        *,
        max_retries: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 8.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._transport = transport
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._sleep = sleep
        self._lock = asyncio.Lock()

    @property
    def transport(self) -> Transport:
        return self._transport

    def set_transport(self, transport: Transport) -> None:
        self._transport = transport

    async def stream(
        self, messages: list[Message], *, state: dict | None = None
    ) -> AsyncIterator[Chunk]:
        async with self._lock:
            attempt = 0
            estado_actual = state
            while True:
                yielded = False
                try:
                    async for chunk in self._transport.stream(messages, state=estado_actual):
                        yielded = True
                        yield chunk
                    return
                except AuthError:
                    raise
                except TransportError:
                    if yielded or attempt >= self.max_retries:
                        raise
                    # El estado pudo ser la causa del fallo (conversación
                    # vencida/rechazada): el reintento cae a modo texto-completo
                    # en vez de repetir el mismo error para siempre.
                    estado_actual = None
                    delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                    await self._sleep(delay)
                    attempt += 1

    async def health(self) -> Health:
        return await self._transport.health()
