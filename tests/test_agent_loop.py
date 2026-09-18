import pytest

from mgm.agent import AgentLoop, EventRecorder, build_system_prompt
from mgm.agent.events import AssistantText, ToolDecided, ToolExecuted, ToolRequested
from mgm.agent.loop import ALLOW_SESSION, DENY
from mgm.permissions import PermissionEngine
from mgm.tools import ToolContext, default_registry
from mgm.transport import (
    AuthError,
    Chunk,
    FakeTransport,
    InferenceBroker,
    Message,
    TransportError,
)


def build(
    script, *, mode="libre", asker=None, max_iterations=25, workspace=None,
    conversation_state=None,
):
    rec = EventRecorder()
    loop = AgentLoop(
        InferenceBroker(FakeTransport(script=script), max_retries=0),
        default_registry(),
        PermissionEngine(mode),
        ToolContext(workspace=workspace),
        system_prompt="PROMPT DE SISTEMA",
        asker=asker,
        on_event=rec,
        max_iterations=max_iterations,
        conversation_state=conversation_state,
    )
    return loop, rec


@pytest.fixture
def ws(tmp_path):
    return tmp_path


class TestTurnoSimple:
    async def test_sin_herramientas_termina_de_inmediato(self, ws):
        loop, rec = build(["Hola, no necesito herramientas."], workspace=ws)
        out = await loop.run_turn("hola")
        assert out.reason == "respuesta" and out.iterations == 1
        assert rec.text == "Hola, no necesito herramientas."

    async def test_el_prompt_de_sistema_no_ensucia_el_historial(self, ws):
        loop, _ = build(["listo"], workspace=ws)
        await loop.run_turn("hola")
        assert all(m.role != "system" for m in loop.messages)
        assert [m.role for m in loop.messages] == ["user", "assistant"]

    async def test_el_prompt_de_sistema_si_viaja_al_modelo(self, ws):
        loop, _ = build(["listo"], workspace=ws)
        enviados = loop._wire_messages()
        assert enviados[0].role == "system" and enviados[0].content == "PROMPT DE SISTEMA"


class TestCicloConHerramientas:
    async def test_ejecuta_herramienta_y_realimenta(self, ws):
        (ws / "dato.txt").write_text("el secreto es 42", encoding="utf-8")
        loop, rec = build(
            [
                '<tool name="read_file" path="dato.txt"></tool>',
                "El archivo dice 42.",
            ],
            workspace=ws,
        )
        out = await loop.run_turn("¿qué dice dato.txt?")
        assert out.reason == "respuesta" and out.iterations == 2
        ejecutadas = rec.of(ToolExecuted)
        assert len(ejecutadas) == 1 and ejecutadas[0].result.ok
        assert "el secreto es 42" in ejecutadas[0].result.output
        realimentado = loop.messages[2]
        assert realimentado.role == "user" and "el secreto es 42" in realimentado.content

    async def test_escribe_de_verdad_en_el_disco(self, ws):
        loop, _ = build(
            ['<tool name="write_file" path="nuevo.txt">hola mundo</tool>', "Hecho."],
            workspace=ws,
        )
        await loop.run_turn("crea nuevo.txt")
        assert (ws / "nuevo.txt").read_text(encoding="utf-8") == "hola mundo"

    async def test_varias_herramientas_en_un_turno_en_orden(self, ws):
        loop, rec = build(
            [
                '<tool name="write_file" path="a.txt">A</tool>'
                '<tool name="write_file" path="b.txt">B</tool>',
                "Listo.",
            ],
            workspace=ws,
        )
        await loop.run_turn("crea a y b")
        assert (ws / "a.txt").read_text() == "A" and (ws / "b.txt").read_text() == "B"
        assert [e.call.args["path"] for e in rec.of(ToolExecuted)] == ["a.txt", "b.txt"]

    async def test_xml_sin_cerrar_vuelve_como_error_al_modelo(self, ws):
        loop, rec = build(
            ['<tool name="write_file" path="a.txt">sin cierre', "Perdón, reintento."],
            workspace=ws,
        )
        await loop.run_turn("crea algo")
        res = rec.of(ToolExecuted)[0].result
        assert not res.ok and "sin cerrar" in res.output
        assert not (ws / "a.txt").exists()

    async def test_herramienta_inexistente_no_rompe_el_turno(self, ws):
        loop, rec = build(['<tool name="volar">alto</tool>', "Vale."], workspace=ws)
        out = await loop.run_turn("vuela")
        assert out.reason == "respuesta"
        assert "no existe la herramienta" in rec.of(ToolExecuted)[0].result.output


class TestPermisos:
    async def test_modo_plan_deniega_escritura_y_avisa_al_modelo(self, ws):
        loop, rec = build(
            ['<tool name="write_file" path="a.txt">X</tool>', "Entendido, no escribo."],
            mode="plan",
            workspace=ws,
        )
        await loop.run_turn("escribe a.txt")
        res = rec.of(ToolExecuted)[0].result
        assert not res.ok and "DENEGADO" in res.output and "modo plan" in res.output
        assert not (ws / "a.txt").exists()
        assert "DENEGADO" in loop.messages[2].content

    async def test_denegacion_no_aborta_el_turno(self, ws):
        loop, _ = build(
            ['<tool name="bash">rm -rf /</tool>', "Vale, no lo hago."],
            mode="plan",
            workspace=ws,
        )
        out = await loop.run_turn("borra todo")
        assert out.reason == "respuesta" and out.iterations == 2

    async def test_sin_asker_en_modo_ask_se_deniega(self, ws):
        loop, rec = build(
            ['<tool name="write_file" path="a.txt">X</tool>', "ok"],
            mode="ask",
            asker=None,
            workspace=ws,
        )
        await loop.run_turn("escribe")
        assert "no hay nadie a quien preguntar" in rec.of(ToolExecuted)[0].result.output

    async def test_el_usuario_autoriza_una_vez(self, ws):
        async def asker(call, resumen, decision):
            return "once"

        loop, rec = build(
            ['<tool name="write_file" path="a.txt">X</tool>', "listo"],
            mode="ask",
            asker=asker,
            workspace=ws,
        )
        await loop.run_turn("escribe")
        assert (ws / "a.txt").read_text() == "X"
        assert rec.of(ToolDecided)[0].asked is True

    async def test_el_usuario_deniega(self, ws):
        async def asker(call, resumen, decision):
            return DENY

        loop, rec = build(
            ['<tool name="write_file" path="a.txt">X</tool>', "ok"],
            mode="ask",
            asker=asker,
            workspace=ws,
        )
        await loop.run_turn("escribe")
        assert not (ws / "a.txt").exists()
        assert "el usuario denegó" in rec.of(ToolExecuted)[0].result.output

    async def test_autorizar_para_la_sesion_no_vuelve_a_preguntar(self, ws):
        preguntas = []

        async def asker(call, resumen, decision):
            preguntas.append(call.name)
            return ALLOW_SESSION

        loop, _ = build(
            [
                '<tool name="write_file" path="a.txt">A</tool>',
                '<tool name="write_file" path="a.txt">B</tool>',
                "listo",
            ],
            mode="ask",
            asker=asker,
            workspace=ws,
        )
        await loop.run_turn("escribe dos veces")
        assert len(preguntas) == 1
        assert (ws / "a.txt").read_text() == "B"

    async def test_se_pregunta_por_cada_sujeto_distinto(self, ws):
        preguntas = []

        async def asker(call, resumen, decision):
            preguntas.append(call.args.get("path"))
            return ALLOW_SESSION

        loop, _ = build(
            [
                '<tool name="write_file" path="a.txt">A</tool>',
                '<tool name="write_file" path="b.txt">B</tool>',
                "listo",
            ],
            mode="ask",
            asker=asker,
            workspace=ws,
        )
        await loop.run_turn("escribe dos archivos")
        assert preguntas == ["a.txt", "b.txt"]

    async def test_se_emite_lo_que_se_va_a_hacer_antes_de_preguntar(self, ws):
        async def asker(call, resumen, decision):
            return DENY

        loop, rec = build(
            ['<tool name="bash">ls -la</tool>', "ok"], mode="ask", asker=asker, workspace=ws
        )
        await loop.run_turn("lista")
        pedido = rec.of(ToolRequested)[0]
        assert pedido.risk == "exec" and "ls -la" in pedido.summary


class TestLimitesYFallos:
    async def test_limite_de_iteraciones(self, ws):
        bucle = ['<tool name="read_file" path="x.txt"></tool>'] * 10
        loop, _ = build(bucle, max_iterations=3, workspace=ws)
        out = await loop.run_turn("dale vueltas")
        assert out.reason == "limite" and out.iterations == 3
        assert "límite de iteraciones" in loop.messages[-1].content

    async def test_error_de_autenticacion_corta_el_turno(self, ws):
        loop, _ = build([AuthError("cookie vencida")], workspace=ws)
        out = await loop.run_turn("hola")
        assert out.reason == "auth"

    async def test_error_de_transporte_corta_el_turno(self, ws):
        loop, _ = build([TransportError("endpoint caído")], workspace=ws)
        out = await loop.run_turn("hola")
        assert out.reason == "transporte"

    async def test_el_historial_sobrevive_entre_turnos(self, ws):
        loop, _ = build(["uno", "dos"], workspace=ws)
        await loop.run_turn("primero")
        await loop.run_turn("segundo")
        assert [m.role for m in loop.messages] == ["user", "assistant", "user", "assistant"]
        assert loop.messages[2].content == "segundo"


class TestProteccionContraBucles:
    """Si el modelo repite el mismo bloque roto, no tiene sentido gastar las 25
    iteraciones: en una sesión real se comió 14 seguidas sin avanzar nada."""

    async def test_corta_el_turno_si_repite_xml_sin_cerrar(self, ws):
        guion = ['<tool name="bash">curl -s '] * 10
        loop, _ = build(guion, workspace=ws, max_iterations=10)

        salida = await loop.run_turn("levanta el servidor")

        assert salida.reason == "protocolo"
        assert salida.iterations <= 4, "debería rendirse pronto, no agotar el turno"

    async def test_un_fallo_suelto_no_corta_nada(self, ws):
        guion = [
            '<tool name="bash">curl -s ',
            '<tool name="bash">echo hola</tool>',
            "listo",
        ]
        loop, _ = build(guion, workspace=ws, max_iterations=10)

        salida = await loop.run_turn("haz algo")

        assert salida.reason == "respuesta"


class TestContinuidadDeConversacion:
    """El loop debe reenviar y actualizar el conversation_state del transporte,
    para que g4f/Gemini continúe el mismo chat en vez de abrir uno nuevo."""

    async def test_primer_turno_manda_state_none(self, ws):
        loop, _ = build(["hola"], workspace=ws)
        await loop.run_turn("hola")
        assert loop.broker.transport.estados_recibidos == [None]

    async def test_captura_el_state_devuelto_por_el_transporte(self, ws):
        loop, _ = build(
            [["hola", Chunk(text="", state={"conversation_id": "c1"})]], workspace=ws
        )
        await loop.run_turn("hola")
        assert loop.conversation_state == {"conversation_id": "c1"}

    async def test_el_siguiente_turno_reenvia_el_state_capturado(self, ws):
        loop, _ = build(
            [["uno", Chunk(text="", state={"conversation_id": "c1"})], "dos"],
            workspace=ws,
        )
        await loop.run_turn("primero")
        await loop.run_turn("segundo")
        assert loop.broker.transport.estados_recibidos == [None, {"conversation_id": "c1"}]

    async def test_se_puede_sembrar_un_state_inicial(self, ws):
        loop, _ = build(["ok"], workspace=ws, conversation_state={"conversation_id": "previo"})
        await loop.run_turn("hola")
        assert loop.broker.transport.estados_recibidos == [{"conversation_id": "previo"}]


class TestPromptDeSistema:
    def test_incluye_herramientas_y_workspace(self):
        p = build_system_prompt(default_registry(), workspace="/tmp/x", memoria="recuerda esto")
        assert 'name="read_file"' in p and "/tmp/x" in p and "recuerda esto" in p

    def test_explica_el_protocolo_xml(self):
        p = build_system_prompt(default_registry())
        assert "<tool name=" in p and "</tool>" in p

    def test_pide_preguntar_ante_encargos_ambiguos(self):
        p = build_system_prompt(default_registry())
        assert "pregunta" in p.lower() and "ambig" in p.lower()

    def test_prohibe_urls_con_esquema_dentro_de_las_herramientas(self):
        """Verificado en vivo: una URL con http:// dentro de un <tool> hace que
        el proveedor corte el stream justo ahí y el bloque quede sin cerrar."""
        p = build_system_prompt(default_registry()).lower()
        assert "http://" in p and "localhost:" in p

    def test_prohibe_etiquetas_ajenas_al_archivo(self):
        """Gemini escribía </style> al final del .css y </script></body></html>
        al final del .js: creía estar partiendo un único HTML."""
        p = build_system_prompt(default_registry()).lower()
        assert "</style>" in p and "</script>" in p

    def test_pide_una_sola_herramienta_cuando_el_cuerpo_es_largo(self):
        """Respuestas con varios archivos completos se cortaban a la mitad y
        dejaban bloques <tool> sin cerrar."""
        p = build_system_prompt(default_registry()).lower()
        assert "una sola herramienta" in p or "una herramienta por respuesta" in p

    def test_pide_validar_de_verdad_antes_de_terminar(self):
        p = build_system_prompt(default_registry())
        minuscula = p.lower()
        assert "background" in minuscula or "segundo plano" in minuscula
        assert "instala" in minuscula or "instálalas" in minuscula
