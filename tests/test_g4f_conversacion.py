"""Continuidad real de conversación en Gemini: pasar y capturar el estado
que g4f/Gemini usa para no abrir un chat nuevo en cada llamada.

Todo con un g4f falso inyectado por monkeypatch: sin red, sin el paquete real.
"""
from dataclasses import dataclass

import mgm.transport.g4f_cookie as mod
from mgm.transport import Message
from mgm.transport.g4f_cookie import G4FCookieTransport


@dataclass
class FalsaConversacion:
    conversation_id: str
    response_id: str
    choice_id: str
    model: str
    turn_index: int = 0


def fake_g4f(piezas, llamadas: list):
    class _ChatCompletion:
        @staticmethod
        def create(**kwargs):
            llamadas.append(kwargs)
            return iter(piezas)

    class _G4F:
        ChatCompletion = _ChatCompletion

    return _G4F()


async def test_sin_state_previo_manda_conversation_none(monkeypatch):
    llamadas: list = []
    monkeypatch.setattr(mod, "_import_g4f", lambda: fake_g4f(["hola"], llamadas))
    transporte = G4FCookieTransport({"__Secure-1PSID": "x"})

    chunks = [c async for c in transporte.stream([Message(role="user", content="hi")])]

    assert [c.text for c in chunks] == ["hola"]
    assert llamadas[0]["conversation"] is None
    assert llamadas[0]["return_conversation"] is True


async def test_state_previo_se_manda_como_conversation(monkeypatch):
    llamadas: list = []
    monkeypatch.setattr(mod, "_import_g4f", lambda: fake_g4f(["ok"], llamadas))
    transporte = G4FCookieTransport({"__Secure-1PSID": "x"})
    estado = {
        "conversation_id": "c1", "response_id": "r1",
        "choice_id": "ch1", "model": "gemini-auto", "turn_index": 2,
    }

    _ = [c async for c in transporte.stream([Message(role="user", content="hi")], state=estado)]

    conv = llamadas[0]["conversation"]
    assert conv.conversation_id == "c1"
    assert conv.response_id == "r1"
    assert conv.choice_id == "ch1"
    assert conv.model == "gemini-auto"
    assert conv.turn_index == 2


async def test_captura_la_conversation_devuelta_como_chunk_de_estado(monkeypatch):
    nueva = FalsaConversacion("c2", "r2", "ch2", "gemini-auto", 3)
    llamadas: list = []
    monkeypatch.setattr(mod, "_import_g4f", lambda: fake_g4f(["hola ", "mundo", nueva], llamadas))
    transporte = G4FCookieTransport({"__Secure-1PSID": "x"})

    chunks = [c async for c in transporte.stream([Message(role="user", content="hi")])]

    assert [c.text for c in chunks] == ["hola ", "mundo", ""]
    assert chunks[-1].state == {
        "conversation_id": "c2", "response_id": "r2",
        "choice_id": "ch2", "model": "gemini-auto", "turn_index": 3,
    }


async def test_no_manda_conversation_si_el_proveedor_no_es_gemini(monkeypatch):
    llamadas: list = []
    monkeypatch.setattr(mod, "_import_g4f", lambda: fake_g4f(["ok"], llamadas))
    transporte = G4FCookieTransport({"__Secure-1PSID": "x"}, provider="auto")

    _ = [
        c async for c in transporte.stream(
            [Message(role="user", content="hi")],
            state={"conversation_id": "c1", "response_id": "r", "choice_id": "ch", "model": "gemini-auto"},
        )
    ]

    assert "conversation" not in llamadas[0]
    assert "return_conversation" not in llamadas[0]
