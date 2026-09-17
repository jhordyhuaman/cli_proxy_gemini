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


async def test_por_defecto_NO_reutiliza_la_conversacion_de_gemini(monkeypatch):
    """El loop agéntico necesita mandar el contexto completo en cada llamada.

    Si se reutiliza la conversación del servidor, g4f manda SOLO el último
    mensaje y delega la memoria en Gemini: el modelo pierde el prompt de
    sistema y el contrato de herramientas, y el chat queda incoherente.
    Verificado en vivo: por eso viene apagado.
    """
    llamadas: list = []
    monkeypatch.setattr(mod, "_import_g4f", lambda: fake_g4f(["ok"], llamadas))
    transporte = G4FCookieTransport({"__Secure-1PSID": "x"})
    estado = {
        "conversation_id": "c1", "response_id": "r1",
        "choice_id": "ch1", "model": "gemini-auto", "turn_index": 2,
    }

    _ = [c async for c in transporte.stream([Message(role="user", content="hi")], state=estado)]

    assert "conversation" not in llamadas[0]


async def test_sin_state_previo_manda_conversation_none(monkeypatch):
    llamadas: list = []
    monkeypatch.setattr(mod, "_import_g4f", lambda: fake_g4f(["hola"], llamadas))
    transporte = G4FCookieTransport({"__Secure-1PSID": "x"}, conversacion_continua=True)

    chunks = [c async for c in transporte.stream([Message(role="user", content="hi")])]

    assert [c.text for c in chunks] == ["hola"]
    assert llamadas[0]["conversation"] is None
    assert llamadas[0]["return_conversation"] is True


async def test_state_previo_se_manda_como_conversation(monkeypatch):
    llamadas: list = []
    monkeypatch.setattr(mod, "_import_g4f", lambda: fake_g4f(["ok"], llamadas))
    transporte = G4FCookieTransport({"__Secure-1PSID": "x"}, conversacion_continua=True)
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
        "enviados": 1,
    }


class TestUnSoloChatSinPerderElContrato:
    """Mismo chat en Gemini Y contexto bajo control de mgm.

    Con `conversation=` a secas, g4f manda SOLO el último mensaje del usuario:
    el modelo se queda sin prompt de sistema y rompe el formato de
    herramientas. Con el transcript completo cada vez, el hilo del servidor
    crece al cuadrado. La salida: pasar `prompt=` explícito con el sistema
    (que es el contrato) + lo que el modelo todavía no ha visto.
    """

    def _transporte(self, monkeypatch, llamadas, piezas=("ok",)):
        monkeypatch.setattr(mod, "_import_g4f", lambda: fake_g4f(list(piezas), llamadas))
        return G4FCookieTransport({"__Secure-1PSID": "x"}, conversacion_continua=True)

    async def test_la_primera_llamada_deja_que_g4f_mande_todo(self, monkeypatch):
        llamadas: list = []
        transporte = self._transporte(monkeypatch, llamadas)

        _ = [c async for c in transporte.stream([Message(role="user", content="hola")])]

        assert llamadas[0]["conversation"] is None
        assert "prompt" not in llamadas[0]

    async def test_al_continuar_manda_sistema_mas_solo_lo_nuevo(self, monkeypatch):
        llamadas: list = []
        transporte = self._transporte(monkeypatch, llamadas)
        estado = {
            "conversation_id": "c1", "response_id": "r1", "choice_id": "ch1",
            "model": "gemini-auto", "turn_index": 1, "enviados": 2,
        }
        mensajes = [
            Message(role="system", content="CONTRATO DE HERRAMIENTAS"),
            Message(role="user", content="viejo 1"),
            Message(role="assistant", content="viejo 2"),
            Message(role="user", content="nuevo de verdad"),
        ]

        _ = [c async for c in transporte.stream(mensajes, state=estado)]

        prompt = llamadas[0]["prompt"]
        assert "CONTRATO DE HERRAMIENTAS" in prompt, "el contrato debe ir siempre"
        assert "nuevo de verdad" in prompt
        assert "viejo 1" not in prompt and "viejo 2" not in prompt

    async def test_usa_el_mismo_formato_de_roles_que_g4f(self, monkeypatch):
        llamadas: list = []
        transporte = self._transporte(monkeypatch, llamadas)
        estado = {
            "conversation_id": "c1", "response_id": "r", "choice_id": "ch",
            "model": "gemini-auto", "enviados": 0,
        }

        _ = [
            c async for c in transporte.stream(
                [Message(role="user", content="hola")], state=estado
            )
        ]

        assert "User: hola" in llamadas[0]["prompt"]

    async def test_apunta_cuantos_mensajes_ya_vio_gemini(self, monkeypatch):
        conv = FalsaConversacion("c9", "r9", "ch9", "gemini-auto", 1)
        llamadas: list = []
        transporte = self._transporte(monkeypatch, llamadas, piezas=("hola", conv))
        mensajes = [
            Message(role="system", content="contrato"),
            Message(role="user", content="uno"),
            Message(role="assistant", content="dos"),
        ]

        chunks = [c async for c in transporte.stream(mensajes)]

        # Dos mensajes no-sistema quedaron del lado de Gemini.
        assert chunks[-1].state["enviados"] == 2


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
