"""Proceso hijo: un subagente aislado.

Se lanza con ``python -m mgm.agentd`` y habla JSONL por stdin/stdout con el
proceso padre. No tiene la cookie, no habla con el modelo y no puede escribir
ni ejecutar nada por su cuenta: para todo eso le pide permiso al padre, que
es el único guardián de la cuota y de los permisos del usuario.

Lo único que hace localmente son las herramientas de solo lectura marcadas
como ``delegable`` — leer, buscar, listar — porque no hay nada que proteger y
así el IPC no se ahoga en mensajes.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import AsyncIterator

from .agent.events import AssistantText
from .agent.loop import AgentLoop
from .agent.prompts import build_system_prompt
from .ipc.channel import JsonlChannel
from .ipc.protocol import (
    CANCEL,
    LLM_CHUNK,
    LLM_END,
    LLM_ERROR,
    LLM_REQUEST,
    PROGRESS,
    READY,
    RESULT,
    TASK,
    TOOL_REQUEST,
    TOOL_RESPONSE,
    Envelope,
)
from .permissions import PermissionEngine
from .skills import load_library
from .tools import ToolContext, ToolRegistry, ToolResult, default_registry
from .tools.base import Tool
from .transport import AuthError, Chunk, Health, InferenceBroker, Message, TransportError

PROMPT_SUBAGENTE = """Eres un SUBAGENTE de mgm: trabajas solo, en tu propio contexto,
sobre una tarea concreta que te delegó el agente principal.

- No puedes preguntarle nada a nadie a mitad de camino: decide y actúa.
- Termina con un informe corto en texto plano: qué hiciste, qué verificaste y
  qué quedó pendiente. Ese informe es lo único que verá quien te delegó.
- No te desvíes de la tarea encargada."""


class ChildRuntime:
    """Enruta los mensajes del padre a quien los está esperando."""

    def __init__(self, channel: JsonlChannel):
        self.channel = channel
        self._colas: dict[str, asyncio.Queue] = {}
        self._contador = 0
        self.cancelado = asyncio.Event()

    def siguiente_id(self) -> str:
        self._contador += 1
        return str(self._contador)

    def abrir(self, msg_id: str) -> asyncio.Queue:
        cola: asyncio.Queue = asyncio.Queue()
        self._colas[msg_id] = cola
        return cola

    def cerrar(self, msg_id: str) -> None:
        self._colas.pop(msg_id, None)

    async def bombear(self) -> None:
        """Lee del padre hasta que cierre la tubería."""
        while True:
            mensaje = await self.channel.recv()
            if mensaje is None:
                self.cancelado.set()
                for cola in self._colas.values():
                    cola.put_nowait(None)
                return
            if mensaje.type == CANCEL:
                self.cancelado.set()
                for cola in self._colas.values():
                    cola.put_nowait(None)
                continue
            # El encargo inicial se enruta por tipo: el padre no conoce el id.
            clave = "task" if mensaje.type == TASK else mensaje.id
            cola = self._colas.get(clave)
            if cola is not None:
                cola.put_nowait(mensaje)


class ParentTransport:
    """Transporte que no habla con el modelo: se lo pide al padre."""

    name = "padre"

    def __init__(self, runtime: ChildRuntime):
        self.runtime = runtime

    async def stream(
        self, messages: list[Message], *, state: dict | None = None
    ) -> AsyncIterator[Chunk]:
        # El estado de conversación real de Gemini no viaja hacia los
        # subagentes a propósito: cada llamada de un hijo debe ser un
        # intercambio aislado, nunca mezclado con el hilo del agente
        # principal ni con el de otro subagente que comparta el mismo broker.
        msg_id = self.runtime.siguiente_id()
        cola = self.runtime.abrir(msg_id)
        try:
            await self.runtime.channel.send(
                Envelope(
                    LLM_REQUEST,
                    {"messages": [{"role": m.role, "content": m.content} for m in messages]},
                    id=msg_id,
                )
            )
            while True:
                mensaje = await cola.get()
                if mensaje is None:
                    raise TransportError("el proceso padre cerró la conexión")
                if mensaje.type == LLM_CHUNK:
                    yield Chunk(text=str(mensaje.payload.get("text", "")))
                elif mensaje.type == LLM_END:
                    return
                elif mensaje.type == LLM_ERROR:
                    detalle = str(mensaje.payload.get("detail", "error del padre"))
                    if mensaje.payload.get("kind") == "auth":
                        raise AuthError(detalle)
                    raise TransportError(detalle)
        finally:
            self.runtime.cerrar(msg_id)

    async def health(self) -> Health:
        return Health(ok=True, detail="inferencia delegada al proceso padre")


class RemoteTool(Tool):
    """Herramienta que se ejecuta en el padre, no aquí."""

    def __init__(self, modelo: Tool, runtime: ChildRuntime):
        self.name = modelo.name
        self.description = modelo.description
        self.body_param = modelo.body_param
        self.parameters_schema = modelo.parameters_schema
        self.required_params = modelo.required_params
        self.risk = modelo.risk
        self.delegable = False
        self._modelo = modelo
        self.runtime = runtime

    def subject(self, args: dict[str, str]) -> str:
        return self._modelo.subject(args)

    def summary(self, args: dict[str, str]) -> str:
        return self._modelo.summary(args)

    async def execute(self, args: dict[str, str], context: ToolContext) -> ToolResult:
        msg_id = self.runtime.siguiente_id()
        cola = self.runtime.abrir(msg_id)
        try:
            await self.runtime.channel.send(
                Envelope(TOOL_REQUEST, {"name": self.name, "args": args}, id=msg_id)
            )
            mensaje = await cola.get()
            if mensaje is None or mensaje.type != TOOL_RESPONSE:
                return ToolResult(False, "[ERROR] el proceso padre no respondió a la herramienta")
            return ToolResult(
                bool(mensaje.payload.get("ok")), str(mensaje.payload.get("output", ""))
            )
        finally:
            self.runtime.cerrar(msg_id)


def build_child_registry(runtime: ChildRuntime, skills) -> ToolRegistry:
    """Locales las de solo lectura; el resto viajan al padre."""
    base = default_registry(skills)
    hijo = ToolRegistry()
    for tool in base.tools():
        hijo.register(tool if tool.delegable else RemoteTool(tool, runtime))
    return hijo


async def run_child(channel: JsonlChannel) -> int:
    runtime = ChildRuntime(channel)
    bomba = asyncio.create_task(runtime.bombear())
    await channel.send(Envelope(READY, {"pid": __import__("os").getpid()}))

    tarea = runtime.abrir("task")
    # El encargo llega con id fijo "task".
    mensaje = await tarea.get()
    if mensaje is None or mensaje.type != TASK:
        bomba.cancel()
        return 1

    prompt = str(mensaje.payload.get("prompt", ""))
    workspace = Path(str(mensaje.payload.get("workspace", "."))).resolve()
    modo = str(mensaje.payload.get("mode", "ask"))
    max_iter = int(mensaje.payload.get("max_iterations", 15))

    skills = load_library(workspace, Path.home())
    registry = build_child_registry(runtime, skills)
    broker = InferenceBroker(ParentTransport(runtime), max_retries=0)

    pendientes: set[asyncio.Task] = set()

    async def emitir(texto: str) -> None:
        await channel.send(Envelope(PROGRESS, {"text": texto}))

    def on_event(evento) -> None:
        if isinstance(evento, AssistantText) and evento.text.strip():
            tarea_progreso = asyncio.create_task(emitir(evento.text))
            pendientes.add(tarea_progreso)
            tarea_progreso.add_done_callback(pendientes.discard)

    loop = AgentLoop(
        broker,
        registry,
        # El hijo no decide permisos: todo lo peligroso viaja al padre igual.
        PermissionEngine("libre"),
        ToolContext(workspace=workspace),
        system_prompt=build_system_prompt(
            registry,
            workspace=str(workspace),
            skills=skills.render_catalog(),
            extra=PROMPT_SUBAGENTE,
        ),
        on_event=on_event,
        max_iterations=max_iter,
    )

    try:
        resultado = await loop.run_turn(prompt)
        await channel.send(
            Envelope(RESULT, {"ok": resultado.reason == "respuesta", "text": resultado.text,
                              "reason": resultado.reason, "iterations": resultado.iterations})
        )
    except Exception as exc:  # nunca morir en silencio
        await channel.send(
            Envelope(RESULT, {"ok": False, "text": f"{type(exc).__name__}: {exc}", "reason": "excepcion"})
        )
    finally:
        if pendientes:
            await asyncio.gather(*pendientes, return_exceptions=True)
        bomba.cancel()
    return 0


async def _main() -> int:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    transporte, protocolo = await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, sys.stdout)
    writer = asyncio.StreamWriter(transporte, protocolo, reader, loop)
    return await run_child(JsonlChannel(reader, writer))


def main() -> None:
    try:
        sys.exit(asyncio.run(_main()))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
