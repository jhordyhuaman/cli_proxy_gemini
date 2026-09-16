"""Lado padre de los subagentes: lanza el proceso, lo vigila y le sirve.

El padre es el guardián único de los dos recursos escasos:

- **la cuota del modelo**: toda inferencia del hijo pasa por el broker del
  padre, así que cinco subagentes no abren cinco sesiones contra Gemini.
- **los permisos del usuario**: toda herramienta que escriba o ejecute pasa
  por el motor de permisos del padre, con el nombre del subagente delante
  para que sepas quién pide qué.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import aclosing
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from ..ipc.channel import JsonlChannel
from ..ipc.protocol import (
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
)
from ..permissions import Decision, PermissionEngine
from ..tools import ToolCall, ToolContext, ToolRegistry, ToolResult
from ..transport import AuthError, InferenceBroker, Message, TransportError

TIMEOUT_DEFECTO = 900.0


@dataclass
class SubagentResult:
    ok: bool
    text: str
    reason: str = ""
    iterations: int = 0
    label: str = ""

    def render(self) -> str:
        cabecera = f"[SUBAGENTE {self.label or 'sin nombre'} — {'ok' if self.ok else 'falló'}]"
        return f"{cabecera}\n{self.text}".strip()


class SubagentSupervisor:
    def __init__(
        self,
        broker: InferenceBroker,
        registry: ToolRegistry,
        permissions: PermissionEngine,
        tool_context: ToolContext,
        *,
        asker: Callable[[ToolCall, str, Decision], Awaitable[str]] | None = None,
        on_progress: Callable[[str, str], None] | None = None,
        log_dir: Path | None = None,
        timeout: float = TIMEOUT_DEFECTO,
        python: str | None = None,
        mode: str = "ask",
    ):
        self.broker = broker
        self.registry = registry
        self.permissions = permissions
        self.tool_context = tool_context
        self.asker = asker
        self.on_progress = on_progress or (lambda label, text: None)
        self.log_dir = log_dir
        self.timeout = timeout
        self.python = python or sys.executable
        self.mode = mode
        self._contador = 0

    # ------------------------------------------------------------------ logs

    def _log_path(self, label: str) -> Path | None:
        if self.log_dir is None:
            return None
        self.log_dir.mkdir(parents=True, exist_ok=True)
        seguro = "".join(c if c.isalnum() or c in "-_" else "_" for c in label) or "subagente"
        return self.log_dir / f"{seguro}.jsonl"

    def _anotar(self, path: Path | None, direccion: str, envelope: Envelope) -> None:
        if path is None:
            return
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {"dir": direccion, "type": envelope.type, "id": envelope.id,
                         "payload": envelope.payload},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except OSError:
            pass

    # --------------------------------------------------------------- servicio

    async def _servir_inferencia(self, channel: JsonlChannel, envelope: Envelope, log: Path | None) -> None:
        mensajes = [
            Message(role=str(m.get("role", "user")), content=str(m.get("content", "")))
            for m in envelope.payload.get("messages", [])
        ]
        try:
            async with aclosing(self.broker.stream(mensajes)) as stream:
                async for chunk in stream:
                    salida = Envelope(LLM_CHUNK, {"text": chunk.text}, id=envelope.id)
                    await channel.send(salida)
            fin = Envelope(LLM_END, {}, id=envelope.id)
            await channel.send(fin)
            self._anotar(log, "→hijo", fin)
        except AuthError as exc:
            await channel.send(Envelope(LLM_ERROR, {"kind": "auth", "detail": str(exc)}, id=envelope.id))
        except TransportError as exc:
            await channel.send(
                Envelope(LLM_ERROR, {"kind": "transporte", "detail": str(exc)}, id=envelope.id)
            )

    async def _servir_herramienta(
        self, channel: JsonlChannel, envelope: Envelope, label: str, log: Path | None
    ) -> None:
        nombre = str(envelope.payload.get("name", ""))
        args = {str(k): str(v) for k, v in (envelope.payload.get("args") or {}).items()}
        call = ToolCall(nombre, args)
        tool = self.registry.get(nombre)

        if tool is None:
            resultado = await self.registry.execute(call, self.tool_context)
        else:
            decision = self.permissions.evaluate(tool.name, tool.risk, tool.subject(args))
            if decision.outcome == "ask":
                if self.asker is None:
                    decision = Decision("deny", "no hay nadie a quien preguntar")
                else:
                    resumen = f"[{label}] {tool.summary(args)}"
                    respuesta = await self.asker(call, resumen, decision)
                    if respuesta == "deny":
                        decision = Decision("deny", "el usuario denegó esta llamada del subagente")
                    else:
                        if respuesta in ("session", "project"):
                            sujeto = tool.subject(args)
                            regla = f"{tool.name}({sujeto})" if sujeto else tool.name
                            self.permissions.remember(regla, scope=respuesta)
                        decision = Decision("allow", "el usuario autorizó al subagente")
            if decision.outcome == "allow":
                resultado = await self.registry.execute(call, self.tool_context)
            else:
                resultado = ToolResult(False, f"[DENEGADO] {decision.reason}")

        respuesta_env = Envelope(
            TOOL_RESPONSE, {"ok": resultado.ok, "output": resultado.output}, id=envelope.id
        )
        await channel.send(respuesta_env)
        self._anotar(log, "→hijo", respuesta_env)

    async def serve(
        self,
        channel: JsonlChannel,
        prompt: str,
        *,
        label: str = "subagente",
        workspace: Path | None = None,
        max_iterations: int = 15,
    ) -> SubagentResult:
        """Bombea mensajes del hijo hasta que entregue su resultado."""
        log = self._log_path(label)
        encargo = Envelope(
            TASK,
            {
                "prompt": prompt,
                "workspace": str(workspace or self.tool_context.workspace),
                "mode": self.mode,
                "max_iterations": max_iterations,
            },
            id="task",
        )
        await channel.send(encargo)
        self._anotar(log, "→hijo", encargo)

        while True:
            mensaje = await channel.recv()
            if mensaje is None:
                return SubagentResult(False, "el subagente cerró sin entregar resultado",
                                      reason="desconectado", label=label)
            self._anotar(log, "←hijo", mensaje)

            if mensaje.type == READY:
                continue
            if mensaje.type == PROGRESS:
                self.on_progress(label, str(mensaje.payload.get("text", "")))
                continue
            if mensaje.type == LOG:
                continue
            if mensaje.type == LLM_REQUEST:
                await self._servir_inferencia(channel, mensaje, log)
                continue
            if mensaje.type == TOOL_REQUEST:
                await self._servir_herramienta(channel, mensaje, label, log)
                continue
            if mensaje.type == RESULT:
                return SubagentResult(
                    ok=bool(mensaje.payload.get("ok")),
                    text=str(mensaje.payload.get("text", "")),
                    reason=str(mensaje.payload.get("reason", "")),
                    iterations=int(mensaje.payload.get("iterations", 0) or 0),
                    label=label,
                )

    # --------------------------------------------------------------- proceso

    async def run(
        self, prompt: str, *, label: str = "", max_iterations: int = 15
    ) -> SubagentResult:
        self._contador += 1
        label = label or f"agente-{self._contador}"

        creationflags = 0
        if os.name == "nt":  # sin ventana de consola emergente en Windows
            creationflags = getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0)

        entorno = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        proceso = await asyncio.create_subprocess_exec(
            self.python, "-u", "-m", "mgm.agentd",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.tool_context.workspace),
            env=entorno,
            creationflags=creationflags,
        )
        channel = JsonlChannel(proceso.stdout, proceso.stdin)
        try:
            return await asyncio.wait_for(
                self.serve(channel, prompt, label=label, max_iterations=max_iterations),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            await self._matar(proceso, channel)
            return SubagentResult(
                False, f"el subagente superó el límite de {self.timeout:g}s y fue detenido",
                reason="timeout", label=label,
            )
        except asyncio.CancelledError:
            await self._matar(proceso, channel)
            raise
        finally:
            if proceso.returncode is None:
                await self._matar(proceso, channel)

    async def _matar(self, proceso, channel: JsonlChannel) -> None:
        try:
            await channel.send(Envelope(CANCEL, {}))
        except Exception:
            pass
        if proceso.returncode is None:
            try:
                proceso.kill()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(proceso.wait(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError):
            pass
