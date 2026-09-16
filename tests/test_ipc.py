import asyncio
import json

import pytest

from mgm.ipc import Envelope, JsonlChannel, ProtocolError, memory_pair
from mgm.ipc.protocol import LLM_CHUNK, RESULT, TASK


class TestProtocolo:
    def test_ida_y_vuelta(self):
        e = Envelope(TASK, {"prompt": "hola", "n": 3}, id="7")
        vuelta = Envelope.decode(e.encode())
        assert vuelta.type == TASK and vuelta.payload == {"prompt": "hola", "n": 3}
        assert vuelta.id == "7" and vuelta.v == 1

    def test_acentos_viajan_bien(self):
        e = Envelope(RESULT, {"text": "compilación terminó ñandú"})
        assert Envelope.decode(e.encode()).payload["text"] == "compilación terminó ñandú"

    def test_una_sola_linea_por_mensaje(self):
        crudo = Envelope(RESULT, {"text": "linea1\nlinea2"}).encode()
        assert crudo.count(b"\n") == 1

    @pytest.mark.parametrize("basura", [b"", b"   ", b"{no es json", b'"texto suelto"'])
    def test_lineas_invalidas(self, basura):
        with pytest.raises(ProtocolError):
            Envelope.decode(basura)

    def test_tipo_desconocido_se_rechaza(self):
        crudo = json.dumps({"v": 1, "type": "hackear", "payload": {}}).encode()
        with pytest.raises(ProtocolError):
            Envelope.decode(crudo)

    def test_payload_no_objeto_se_rechaza(self):
        crudo = json.dumps({"v": 1, "type": TASK, "payload": [1, 2]}).encode()
        with pytest.raises(ProtocolError):
            Envelope.decode(crudo)


class TestCanal:
    async def test_envio_y_recepcion(self):
        a, b = memory_pair()
        await a.send(Envelope(TASK, {"prompt": "x"}, id="1"))
        recibido = await b.recv()
        assert recibido.type == TASK and recibido.id == "1"

    async def test_orden_preservado(self):
        a, b = memory_pair()
        for i in range(5):
            await a.send(Envelope(LLM_CHUNK, {"text": str(i)}, id="1"))
        textos = [(await b.recv()).payload["text"] for _ in range(5)]
        assert textos == ["0", "1", "2", "3", "4"]

    async def test_cierre_devuelve_none(self):
        a, b = memory_pair()
        a._writer.close()
        assert await b.recv() is None

    async def test_basura_en_la_tuberia_no_mata_el_canal(self):
        a, b = memory_pair()
        a._writer.write(b"esto no es json\n")
        await a.send(Envelope(RESULT, {"text": "sobreviví"}))
        recibido = await b.recv()
        assert recibido.payload["text"] == "sobreviví"

    async def test_iteracion_asincrona(self):
        a, b = memory_pair()
        await a.send(Envelope(LLM_CHUNK, {"text": "uno"}))
        await a.send(Envelope(LLM_CHUNK, {"text": "dos"}))
        a._writer.close()
        recibidos = [m.payload["text"] async for m in b]
        assert recibidos == ["uno", "dos"]

    async def test_canal_sin_escritor(self):
        canal = JsonlChannel(asyncio.StreamReader(), None)
        with pytest.raises(RuntimeError):
            await canal.send(Envelope(RESULT, {}))
