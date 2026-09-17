"""El loop agéntico: stream → parse → permisos → ejecutar → realimentar.

El turno termina cuando el modelo responde SIN pedir herramientas. No hay
etiqueta de "terminar": si el modelo quiere hablar, habla; si quiere actuar,
emite herramientas y recibe sus resultados reales.

Una denegación de permiso NO aborta el turno: se le devuelve al modelo como
resultado para que se adapte o proponga otra cosa.
"""

from __future__ import annotations

from contextlib import aclosing
from dataclasses import dataclass
from typing import Awaitable, Callable

from ..permissions import Decision, PermissionEngine
from ..protocol import TextEvent, ToolCallEvent, XMLToolParser
from ..transport import AuthError, InferenceBroker, Message, TransportError
from ..tools import ToolCall, ToolContext, ToolRegistry, ToolResult
from .events import (
    AssistantText,
    IterationStart,
    LoopError,
    ToolDecided,
    ToolExecuted,
    ToolRequested,
    TurnEnd,
    TurnStart,
)

#: Respuestas posibles de quien pregunta al usuario.
ALLOW_ONCE = "once"
ALLOW_SESSION = "session"
ALLOW_PROJECT = "project"
DENY = "deny"

Asker = Callable[[ToolCall, str, Decision], Awaitable[str]]
Emit = Callable[[object], None]

CABECERA_RESULTADOS = "RESULTADOS DE TUS HERRAMIENTAS:"
AVISO_LIMITE = (
    "Se alcanzó el límite de iteraciones del turno. Resume en una frase qué "
    "lograste y qué quedó pendiente, sin usar más herramientas."
)


@dataclass
class TurnOutcome:
    reason: str
    iterations: int
    text: str


class AgentLoop:
    def __init__(
        self,
        broker: InferenceBroker,
        registry: ToolRegistry,
        permissions: PermissionEngine,
        tool_context: ToolContext,
        *,
        system_prompt: str = "",
        messages: list[Message] | None = None,
        asker: Asker | None = None,
        on_event: Emit | None = None,
        max_iterations: int = 25,
        conversation_state: dict | None = None,
    ):
        self.broker = broker
        self.registry = registry
        self.permissions = permissions
        self.tool_context = tool_context
        self.system_prompt = system_prompt
        self.messages: list[Message] = messages if messages is not None else []
        self.asker = asker
        self.on_event = on_event or (lambda event: None)
        self.max_iterations = max_iterations
        #: Estado opaco de continuidad de conversación (p. ej. el
        #: conversation_id de Gemini) para que el transporte no abra un chat
        #: nuevo en cada llamada. Lo actualiza _stream_once con lo que
        #: devuelva el transporte.
        self.conversation_state = conversation_state

    # ---------------------------------------------------------------- helpers

    def _wire_messages(self) -> list[Message]:
        if not self.system_prompt:
            return list(self.messages)
        return [Message(role="system", content=self.system_prompt), *self.messages]

    async def _stream_once(self) -> tuple[str, list[ToolCallEvent]]:
        parser = XMLToolParser()
        crudo: list[str] = []
        llamadas: list[ToolCallEvent] = []

        def procesar(eventos):
            for evento in eventos:
                if isinstance(evento, TextEvent):
                    self.on_event(AssistantText(evento.text))
                elif isinstance(evento, ToolCallEvent):
                    llamadas.append(evento)

        peticion = self.broker.stream(self._wire_messages(), state=self.conversation_state)
        async with aclosing(peticion) as stream:
            async for chunk in stream:
                if chunk.state is not None:
                    self.conversation_state = chunk.state
                crudo.append(chunk.text)
                procesar(parser.feed(chunk.text))
        procesar(parser.flush())
        return "".join(crudo), llamadas

    async def _resolver_permiso(self, call: ToolCall) -> tuple[Decision, bool]:
        tool = self.registry.get(call.name)
        if tool is None:
            return Decision("allow", "herramienta inexistente: el registro dará el error"), False

        decision = self.permissions.evaluate(tool.name, tool.risk, tool.subject(call.args))
        self.on_event(ToolRequested(call, tool.summary(call.args), tool.risk))
        if decision.outcome != "ask":
            self.on_event(ToolDecided(call, decision))
            return decision, False

        if self.asker is None:
            decision = Decision("deny", "no hay nadie a quien preguntar (modo no interactivo)")
            self.on_event(ToolDecided(call, decision))
            return decision, False

        respuesta = await self.asker(call, tool.summary(call.args), decision)
        if respuesta == DENY:
            decision = Decision("deny", "el usuario denegó esta llamada")
        else:
            if respuesta in (ALLOW_SESSION, ALLOW_PROJECT):
                sujeto = tool.subject(call.args)
                regla = f"{tool.name}({sujeto})" if sujeto else tool.name
                self.permissions.remember(regla, scope=respuesta)
            decision = Decision("allow", "el usuario autorizó esta llamada")
        self.on_event(ToolDecided(call, decision, asked=True))
        return decision, True

    async def _ejecutar(self, eventos: list[ToolCallEvent]) -> list[str]:
        salidas: list[str] = []
        for evento in eventos:
            call = self.registry.call_from_event(evento.name, evento.attrs, evento.body)
            if not evento.closed:
                resultado = ToolResult(
                    False,
                    f"[ERROR] el bloque XML de {evento.name!r} quedó sin cerrar; "
                    "vuelve a emitirlo completo con su </tool>",
                )
                self.on_event(ToolExecuted(call, resultado))
                salidas.append(f"<{evento.name}> {resultado.output}")
                continue

            decision, _ = await self._resolver_permiso(call)
            if decision.outcome != "allow":
                resultado = ToolResult(False, f"[DENEGADO] {decision.reason}")
            else:
                resultado = await self.registry.execute(call, self.tool_context)
            self.on_event(ToolExecuted(call, resultado))
            salidas.append(f"<{call.name}> {resultado.output}")
        return salidas

    # ------------------------------------------------------------------- API

    async def run_turn(self, user_text: str) -> TurnOutcome:
        self.on_event(TurnStart(user_text))
        self.messages.append(Message(role="user", content=user_text))

        iteracion = 0
        ultimo_texto = ""
        while iteracion < self.max_iterations:
            iteracion += 1
            self.on_event(IterationStart(iteracion, self.max_iterations))
            try:
                crudo, llamadas = await self._stream_once()
            except AuthError as exc:
                self.on_event(LoopError("auth", str(exc)))
                return self._fin("auth", iteracion, "")
            except TransportError as exc:
                self.on_event(LoopError("transporte", str(exc)))
                return self._fin("transporte", iteracion, "")

            if crudo:
                self.messages.append(Message(role="assistant", content=crudo))
                ultimo_texto = crudo

            if not llamadas:
                return self._fin("respuesta", iteracion, ultimo_texto)

            salidas = await self._ejecutar(llamadas)
            self.messages.append(
                Message(
                    role="user",
                    content=f"{CABECERA_RESULTADOS}\n\n" + "\n\n".join(salidas),
                )
            )

        self.messages.append(Message(role="user", content=AVISO_LIMITE))
        return self._fin("limite", iteracion, ultimo_texto)

    def _fin(self, reason: str, iterations: int, text: str) -> TurnOutcome:
        self.on_event(TurnEnd(reason, iterations, text))
        return TurnOutcome(reason, iterations, text)
