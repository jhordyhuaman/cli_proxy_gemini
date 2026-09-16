"""Parser incremental del protocolo de herramientas.

El modelo emite texto plano mezclado con bloques::

    <tool name="..." attr="...">cuerpo</tool>

El parser recibe chunks de texto arbitrarios (las etiquetas pueden quedar
partidas entre chunks) y emite eventos: texto plano, apertura de tool y
cierre de tool con atributos y cuerpo. Tolera XML mal cerrado al final del
stream (``flush`` cierra con ``closed=False``) y basura parcial (texto que
solo parece etiqueta se devuelve como texto plano).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Union

_OPEN = "<tool"
_CLOSE = "</tool>"
_TAG_END_CHARS = (" ", "\t", "\n", "\r", ">", "/")
_ATTR_RE = re.compile(r'([A-Za-z_][\w.-]*)\s*=\s*"([^"]*)"')


@dataclass
class TextEvent:
    text: str


@dataclass
class ToolStartEvent:
    name: str
    attrs: dict[str, str]


@dataclass
class ToolCallEvent:
    name: str
    attrs: dict[str, str]
    body: str
    closed: bool = True


Event = Union[TextEvent, ToolStartEvent, ToolCallEvent]


def _suffix_prefix_len(text: str, tag: str) -> int:
    """Largo del mayor sufijo de `text` que es prefijo propio de `tag`."""
    for n in range(min(len(text), len(tag) - 1), 0, -1):
        if text.endswith(tag[:n]):
            return n
    return 0


class XMLToolParser:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._buf = ""
        self._in_tool = False
        self._tool_name = ""
        self._tool_attrs: dict[str, str] = {}
        self._body: list[str] = []

    def feed(self, chunk: str) -> list[Event]:
        self._buf += chunk
        return self._drain(final=False)

    def flush(self) -> list[Event]:
        events = self._drain(final=True)
        if self._in_tool:
            body = "".join(self._body) + self._buf
            events.append(
                ToolCallEvent(self._tool_name, self._tool_attrs, body, closed=False)
            )
        elif self._buf:
            events.append(TextEvent(self._buf))
        self.reset()
        return events

    def _drain(self, final: bool) -> list[Event]:
        events: list[Event] = []
        while True:
            if self._in_tool:
                if not self._drain_body(events, final):
                    return events
            else:
                if not self._drain_text(events, final):
                    return events

    def _drain_text(self, events: list[Event], final: bool) -> bool:
        idx = self._buf.find(_OPEN)
        if idx == -1:
            hold = 0 if final else _suffix_prefix_len(self._buf, _OPEN)
            emit = self._buf[: len(self._buf) - hold] if hold else self._buf
            self._buf = self._buf[len(emit):]
            if emit:
                events.append(TextEvent(emit))
            return False

        after = idx + len(_OPEN)
        if after >= len(self._buf):
            if final:
                events.append(TextEvent(self._buf))
                self._buf = ""
            return False

        next_char = self._buf[after]
        if next_char not in _TAG_END_CHARS:
            events.append(TextEvent(self._buf[:after]))
            self._buf = self._buf[after:]
            return True

        tag_end = self._buf.find(">", after)
        if tag_end == -1:
            if final:
                events.append(TextEvent(self._buf))
                self._buf = ""
            elif idx:
                events.append(TextEvent(self._buf[:idx]))
                self._buf = self._buf[idx:]
            return False

        if idx:
            events.append(TextEvent(self._buf[:idx]))
        inner = self._buf[after:tag_end]
        self_closing = inner.rstrip().endswith("/")
        attrs = dict(_ATTR_RE.findall(inner))
        name = attrs.pop("name", "")
        self._buf = self._buf[tag_end + 1:]

        events.append(ToolStartEvent(name, attrs))
        if self_closing:
            events.append(ToolCallEvent(name, attrs, ""))
        else:
            self._in_tool = True
            self._tool_name = name
            self._tool_attrs = attrs
            self._body = []
        return True

    def _drain_body(self, events: list[Event], final: bool) -> bool:
        idx = self._buf.find(_CLOSE)
        if idx == -1:
            hold = 0 if final else _suffix_prefix_len(self._buf, _CLOSE)
            take = len(self._buf) - hold
            if take:
                self._body.append(self._buf[:take])
            self._buf = self._buf[take:]
            return False

        self._body.append(self._buf[:idx])
        self._buf = self._buf[idx + len(_CLOSE):]
        events.append(
            ToolCallEvent(self._tool_name, self._tool_attrs, "".join(self._body))
        )
        self._in_tool = False
        self._body = []
        return True
