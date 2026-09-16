"""Canal JSONL asíncrono sobre un par lector/escritor.

Funciona igual sobre las tuberías de un subproceso real que sobre un par en
memoria, que es lo que permite probar todo el protocolo sin lanzar procesos.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from .protocol import Envelope, ProtocolError


class Reader(Protocol):
    async def readline(self) -> bytes: ...


class Writer(Protocol):
    def write(self, data: bytes) -> object: ...
    async def drain(self) -> None: ...


class JsonlChannel:
    def __init__(self, reader: Reader | None, writer: Writer | None):
        self._reader = reader
        self._writer = writer
        self._send_lock = asyncio.Lock()

    async def send(self, envelope: Envelope) -> None:
        if self._writer is None:
            raise RuntimeError("canal sin escritor")
        async with self._send_lock:
            self._writer.write(envelope.encode())
            await self._writer.drain()

    async def recv(self) -> Envelope | None:
        """Siguiente mensaje válido, o None si la otra punta cerró."""
        if self._reader is None:
            raise RuntimeError("canal sin lector")
        while True:
            linea = await self._reader.readline()
            if not linea:
                return None
            if not linea.strip():
                continue
            try:
                return Envelope.decode(linea)
            except ProtocolError:
                continue  # basura en la tubería: la saltamos sin morir

    def __aiter__(self):
        return self

    async def __anext__(self) -> Envelope:
        mensaje = await self.recv()
        if mensaje is None:
            raise StopAsyncIteration
        return mensaje


class _MemoryWriter:
    def __init__(self, reader: asyncio.StreamReader):
        self._reader = reader

    def write(self, data: bytes) -> None:
        self._reader.feed_data(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self._reader.feed_eof()


def memory_pair() -> tuple[JsonlChannel, JsonlChannel]:
    """Dos canales conectados entre sí, en memoria. Para pruebas."""
    hacia_b, hacia_a = asyncio.StreamReader(), asyncio.StreamReader()
    canal_a = JsonlChannel(hacia_a, _MemoryWriter(hacia_b))
    canal_b = JsonlChannel(hacia_b, _MemoryWriter(hacia_a))
    return canal_a, canal_b
