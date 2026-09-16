import pytest

from mgm.transport import FakeTransport, Message, TransportError


async def collect(transport, messages):
    return [chunk.text async for chunk in transport.stream(messages)]


@pytest.fixture
def messages():
    return [Message(role="user", content="hola")]


async def test_scripted_string_is_single_chunk(messages):
    transport = FakeTransport(script=["respuesta completa"])
    assert await collect(transport, messages) == ["respuesta completa"]


async def test_scripted_list_streams_multiple_chunks(messages):
    transport = FakeTransport(script=[["uno", "dos", "tres"]])
    assert await collect(transport, messages) == ["uno", "dos", "tres"]


async def test_default_echo_without_script(messages):
    transport = FakeTransport()
    chunks = await collect(transport, messages)
    assert len(chunks) == 1
    assert "hola" in chunks[0]


async def test_echo_after_script_exhausted(messages):
    transport = FakeTransport(script=["primera"])
    assert await collect(transport, messages) == ["primera"]
    chunks = await collect(transport, messages)
    assert "hola" in chunks[0]


async def test_scripted_exception_is_raised(messages):
    transport = FakeTransport(script=[TransportError("boom")])
    with pytest.raises(TransportError, match="boom"):
        await collect(transport, messages)


async def test_health_always_ok():
    health = await FakeTransport().health()
    assert health.ok


class TestFiltroDeStreamG4F:
    """El stream real de g4f mezcla texto con objetos de control del proveedor."""

    def test_solo_las_cadenas_son_texto(self):
        from mgm.transport import es_texto

        class JsonResponse:  # como los de g4f.providers.response
            pass

        class Conversation:
            pass

        assert es_texto("hola")
        assert not es_texto(JsonResponse())
        assert not es_texto(Conversation())
        assert not es_texto({"data": [["wrb.fr"]]})
        assert not es_texto(None)
        assert not es_texto("")

    def test_se_descartan_los_objetos_de_control(self):
        from mgm.transport.g4f_cookie import _SENTINEL, G4FCookieTransport

        class Control:
            def __repr__(self):
                return "{'data': [['wrb.fr', None, 'basura']]}"

        stream = iter([Control(), Control(), "hola", Control(), " mundo", Control()])
        t = G4FCookieTransport({"x": "y"})
        recogido = []
        while True:
            pieza = t._next_piece(stream)
            if pieza is _SENTINEL:
                break
            recogido.append(pieza)
        assert recogido == ["hola", " mundo"]

    def test_un_stream_solo_de_control_se_agota_sin_texto(self):
        from mgm.transport.g4f_cookie import _SENTINEL, G4FCookieTransport

        class Control:
            pass

        t = G4FCookieTransport({"x": "y"})
        assert t._next_piece(iter([Control(), Control()])) is _SENTINEL

    async def test_el_stream_no_emite_basura_del_protocolo(self):
        from mgm.transport import Message
        from mgm.transport.g4f_cookie import G4FCookieTransport

        class Control:
            def __str__(self):
                return "{'data': [['wrb.fr', None, 'no debe salir']]}"

        t = G4FCookieTransport({"__Secure-1PSID": "x"})
        t._create_stream = lambda mensajes: iter([Control(), "texto ", Control(), "real"])
        piezas = [c.text async for c in t.stream([Message(role="user", content="hola")])]
        assert piezas == ["texto ", "real"]
        assert "wrb.fr" not in "".join(piezas)
