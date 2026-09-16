"""Presupuesto de contexto y compactación.

Sin tokenizador del modelo, estimamos: ~4 caracteres por token. Sirve para
decidir *cuándo* compactar, que es lo único que necesitamos.

La compactación conserva los primeros mensajes (donde suele estar el encargo
real) y los últimos (el trabajo en curso), y reemplaza el medio por un resumen
pedido al propio modelo. Si no hay transporte disponible, cae a un resumen
mecánico para no perder el hilo del todo.
"""

from __future__ import annotations

from contextlib import aclosing
from dataclasses import dataclass

from ..transport import InferenceBroker, Message, TransportError

CHARS_POR_TOKEN = 4
PRESUPUESTO_DEFECTO = 120_000
UMBRAL = 0.8
CONSERVAR_INICIO = 2
CONSERVAR_FINAL = 6
MARCA_RESUMEN = "[RESUMEN DE LA CONVERSACIÓN PREVIA]"

PROMPT_RESUMEN = """Resume la conversación de abajo para que otro agente pueda continuar
el trabajo sin haberla leído. Incluye, en español y en viñetas:

- Qué pidió el usuario y con qué objetivo.
- Qué archivos se leyeron, crearon o modificaron (rutas exactas).
- Qué comandos se ejecutaron y qué resultado dieron.
- Qué decisiones se tomaron y por qué.
- Qué quedó pendiente o fallando.

No inventes nada que no esté en la conversación.

CONVERSACIÓN:

"""


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_POR_TOKEN)


def messages_tokens(messages: list[Message]) -> int:
    return sum(estimate_tokens(m.content) for m in messages)


@dataclass
class ContextBudget:
    limit: int = PRESUPUESTO_DEFECTO
    threshold: float = UMBRAL

    @property
    def trigger(self) -> int:
        return int(self.limit * self.threshold)

    def used(self, messages: list[Message]) -> int:
        return messages_tokens(messages)

    def ratio(self, messages: list[Message]) -> float:
        return self.used(messages) / self.limit if self.limit else 0.0

    def needs_compaction(self, messages: list[Message]) -> bool:
        return self.used(messages) >= self.trigger


def _resumen_mecanico(medio: list[Message]) -> str:
    lineas = []
    for m in medio:
        primera = m.content.strip().splitlines()[0] if m.content.strip() else ""
        lineas.append(f"- {m.role}: {primera[:160]}")
    return f"{MARCA_RESUMEN}\n(resumen mecánico, sin modelo)\n" + "\n".join(lineas[:60])


async def summarize(broker: InferenceBroker | None, medio: list[Message]) -> str:
    transcripcion = "\n\n".join(f"[{m.role}]\n{m.content}" for m in medio)
    if broker is None:
        return _resumen_mecanico(medio)
    peticion = [Message(role="user", content=PROMPT_RESUMEN + transcripcion)]
    piezas: list[str] = []
    try:
        async with aclosing(broker.stream(peticion)) as stream:
            async for chunk in stream:
                piezas.append(chunk.text)
    except (TransportError, NotImplementedError):
        return _resumen_mecanico(medio)
    texto = "".join(piezas).strip()
    return f"{MARCA_RESUMEN}\n{texto}" if texto else _resumen_mecanico(medio)


async def compact(
    messages: list[Message],
    broker: InferenceBroker | None = None,
    *,
    keep_head: int = CONSERVAR_INICIO,
    keep_tail: int = CONSERVAR_FINAL,
) -> list[Message]:
    """Devuelve una lista nueva: cabeza + resumen + cola."""
    if len(messages) <= keep_head + keep_tail:
        return list(messages)
    cabeza = messages[:keep_head]
    medio = messages[keep_head : len(messages) - keep_tail]
    cola = messages[len(messages) - keep_tail :]
    if not medio:
        return list(messages)
    resumen = await summarize(broker, medio)
    return [*cabeza, Message(role="user", content=resumen), *cola]
