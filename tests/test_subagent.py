import asyncio

import pytest

from mgm.agent import SubagentSupervisor
from mgm.ipc import Envelope, memory_pair
from mgm.ipc.protocol import (
    LLM_CHUNK, LLM_END, LLM_ERROR, LLM_REQUEST, PROGRESS, READY, RESULT,
    TASK, TOOL_REQUEST, TOOL_RESPONSE,
)
from mgm.permissions import PermissionEngine
from mgm.tools import ToolContext, default_registry
from mgm.transport import AuthError, FakeTransport, InferenceBroker


def supervisor(tmp_path, *, mode="libre", asker=None, script=None, log_dir=None, progreso=None):
    return SubagentSupervisor(
        InferenceBroker(FakeTransport(script=script or ["respuesta del modelo"]), max_retries=0),
        default_registry(),
        PermissionEngine(mode),
        ToolContext(workspace=tmp_path),
        asker=asker,
        on_progress=progreso,
        log_dir=log_dir,
        timeout=10,
    )


class TestSupervisorEnMemoria:
    async def test_entrega_el_encargo_y_recoge_el_resultado(self, tmp_path):
        padre, hijo = memory_pair()
        sup = supervisor(tmp_path)
        tarea = asyncio.create_task(sup.serve(padre, "haz algo", label="probeta"))

        encargo = await hijo.recv()
        assert encargo.type == TASK and encargo.payload["prompt"] == "haz algo"
        assert encargo.payload["workspace"] == str(tmp_path)

        await hijo.send(Envelope(READY, {"pid": 1}))
        await hijo.send(Envelope(RESULT, {"ok": True, "text": "informe final", "iterations": 2}))
        res = await tarea
        assert res.ok and res.text == "informe final" and res.label == "probeta"
        assert "informe final" in res.render()

    async def test_el_padre_sirve_la_inferencia(self, tmp_path):
        padre, hijo = memory_pair()
        sup = supervisor(tmp_path, script=[["hola ", "mundo"]])
        tarea = asyncio.create_task(sup.serve(padre, "x"))
        await hijo.recv()

        await hijo.send(Envelope(LLM_REQUEST, {"messages": [{"role": "user", "content": "di hola"}]}, id="9"))
        piezas = []
        while True:
            m = await hijo.recv()
            if m.type == LLM_END:
                break
            assert m.type == LLM_CHUNK and m.id == "9"
            piezas.append(m.payload["text"])
        assert "".join(piezas) == "hola mundo"

        await hijo.send(Envelope(RESULT, {"ok": True, "text": "listo"}))
        assert (await tarea).ok

    async def test_error_de_auth_viaja_al_hijo_como_tal(self, tmp_path):
        padre, hijo = memory_pair()
        sup = supervisor(tmp_path, script=[AuthError("cookie vencida")])
        tarea = asyncio.create_task(sup.serve(padre, "x"))
        await hijo.recv()
        await hijo.send(Envelope(LLM_REQUEST, {"messages": []}, id="1"))
        m = await hijo.recv()
        assert m.type == LLM_ERROR and m.payload["kind"] == "auth"
        await hijo.send(Envelope(RESULT, {"ok": False, "text": "me quedé sin modelo"}))
        assert not (await tarea).ok

    async def test_el_padre_ejecuta_las_herramientas_del_hijo(self, tmp_path):
        padre, hijo = memory_pair()
        sup = supervisor(tmp_path)
        tarea = asyncio.create_task(sup.serve(padre, "x"))
        await hijo.recv()

        await hijo.send(Envelope(TOOL_REQUEST, {"name": "write_file",
                                                "args": {"path": "hecho.txt", "content": "por el hijo"}}, id="3"))
        respuesta = await hijo.recv()
        assert respuesta.type == TOOL_RESPONSE and respuesta.payload["ok"] and respuesta.id == "3"
        assert (tmp_path / "hecho.txt").read_text(encoding="utf-8") == "por el hijo"

        await hijo.send(Envelope(RESULT, {"ok": True, "text": "listo"}))
        await tarea

    async def test_los_permisos_del_padre_mandan_sobre_el_hijo(self, tmp_path):
        padre, hijo = memory_pair()
        sup = supervisor(tmp_path, mode="plan")
        tarea = asyncio.create_task(sup.serve(padre, "x"))
        await hijo.recv()

        await hijo.send(Envelope(TOOL_REQUEST, {"name": "write_file",
                                                "args": {"path": "prohibido.txt", "content": "x"}}, id="4"))
        respuesta = await hijo.recv()
        assert not respuesta.payload["ok"] and "DENEGADO" in respuesta.payload["output"]
        assert not (tmp_path / "prohibido.txt").exists()

        await hijo.send(Envelope(RESULT, {"ok": False, "text": "no pude"}))
        await tarea

    async def test_se_pregunta_al_usuario_nombrando_al_subagente(self, tmp_path):
        vistos = []

        async def asker(call, resumen, decision):
            vistos.append(resumen)
            return "deny"

        padre, hijo = memory_pair()
        sup = supervisor(tmp_path, mode="ask", asker=asker)
        tarea = asyncio.create_task(sup.serve(padre, "x", label="explorador"))
        await hijo.recv()
        await hijo.send(Envelope(TOOL_REQUEST, {"name": "bash", "args": {"command": "ls"}}, id="5"))
        await hijo.recv()
        await hijo.send(Envelope(RESULT, {"ok": True, "text": "fin"}))
        await tarea
        assert vistos and "[explorador]" in vistos[0] and "ls" in vistos[0]

    async def test_el_progreso_se_reporta_en_vivo(self, tmp_path):
        recibido = []
        padre, hijo = memory_pair()
        sup = supervisor(tmp_path, progreso=lambda label, texto: recibido.append((label, texto)))
        tarea = asyncio.create_task(sup.serve(padre, "x", label="obrero"))
        await hijo.recv()
        await hijo.send(Envelope(PROGRESS, {"text": "voy por la mitad"}))
        await hijo.send(Envelope(RESULT, {"ok": True, "text": "fin"}))
        await tarea
        assert recibido == [("obrero", "voy por la mitad")]

    async def test_si_el_hijo_se_cae_se_reporta(self, tmp_path):
        padre, hijo = memory_pair()
        sup = supervisor(tmp_path)
        tarea = asyncio.create_task(sup.serve(padre, "x"))
        await hijo.recv()
        hijo._writer.close()
        res = await tarea
        assert not res.ok and res.reason == "desconectado"

    async def test_deja_bitacora_por_subagente(self, tmp_path):
        logs = tmp_path / "logs"
        padre, hijo = memory_pair()
        sup = supervisor(tmp_path, log_dir=logs)
        tarea = asyncio.create_task(sup.serve(padre, "x", label="con/barra"))
        await hijo.recv()
        await hijo.send(Envelope(RESULT, {"ok": True, "text": "fin"}))
        await tarea
        archivo = logs / "con_barra.jsonl"
        assert archivo.is_file()
        assert "task" in archivo.read_text(encoding="utf-8")


class TestProcesoReal:
    """Lanza el proceso hijo de verdad: es la prueba de que la arquitectura B funciona."""

    async def test_el_subagente_escribe_un_archivo_de_punta_a_punta(self, tmp_path):
        guion = [
            '<tool name="write_file" path="desde_subagente.txt">lo hizo el hijo</tool>',
            "Escribí el archivo y lo verifiqué.",
        ]
        sup = supervisor(tmp_path, script=guion)
        res = await sup.run("crea desde_subagente.txt", label="e2e", max_iterations=5)
        assert res.ok, res.text
        assert (tmp_path / "desde_subagente.txt").read_text(encoding="utf-8") == "lo hizo el hijo"
        assert "verifiqué" in res.text

    async def test_el_subagente_lee_localmente_sin_molestar_al_padre(self, tmp_path):
        (tmp_path / "dato.txt").write_text("valor secreto", encoding="utf-8")
        sup = supervisor(tmp_path, script=[
            '<tool name="read_file" path="dato.txt"></tool>',
            "El archivo contiene el valor secreto.",
        ])
        res = await sup.run("lee dato.txt", label="lector", max_iterations=5)
        assert res.ok and "secreto" in res.text

    async def test_el_padre_deniega_y_el_subagente_lo_acata(self, tmp_path):
        sup = supervisor(tmp_path, mode="plan", script=[
            '<tool name="write_file" path="no.txt">x</tool>',
            "No me dejaron escribir.",
        ])
        res = await sup.run("intenta escribir", label="bloqueado", max_iterations=5)
        assert not (tmp_path / "no.txt").exists()
        assert res.ok and "no me dejaron" in res.text.lower()

    async def test_timeout_mata_el_proceso(self, tmp_path):
        # El hijo se queda esperando una inferencia que tarda 30s; el padre
        # debe cortar por timeout y matar el proceso, no quedarse colgado.
        lento = InferenceBroker(
            FakeTransport(script=[["parte1", "parte2"]], chunk_delay=30.0), max_retries=0
        )
        sup = SubagentSupervisor(
            lento,
            default_registry(),
            PermissionEngine("libre"),
            ToolContext(workspace=tmp_path),
            timeout=0.6,
        )
        res = await sup.run("tarda una eternidad", label="lento", max_iterations=2)
        assert not res.ok and res.reason == "timeout"
        assert "detenido" in res.text


class TestDelegacionCompleta:
    """El circuito entero: agente principal → tool task → proceso hijo → padre → disco."""

    async def test_el_agente_principal_delega_en_un_subagente_real(self, tmp_path):
        import io

        from rich.console import Console

        from mgm.app import build_app
        from mgm.ui.console import TEMA

        # Un único guion compartido: el broker del padre sirve a los dos agentes en orden.
        guion = [
            # 1) turno del agente principal: delega
            '<tool name="task" label="obrero">crea saludo.txt con el texto hola</tool>',
            # 2) turno 1 del subagente (su inferencia la sirve el padre)
            '<tool name="write_file" path="saludo.txt">hola</tool>',
            # 3) turno 2 del subagente: informa y termina
            "Creé saludo.txt con el texto hola.",
            # 4) turno 2 del agente principal: cierra
            "Listo, el subagente creó el archivo.",
        ]

        buffer = io.StringIO()
        app = build_app(
            console=Console(file=buffer, force_terminal=False, width=100, theme=TEMA),
            workspace=tmp_path,
            home=tmp_path / "home",
            mode="libre",
            transport="fake",
        )
        app.broker.set_transport(FakeTransport(script=guion))

        await app.run_turn("delega la creación de saludo.txt")

        # El archivo lo escribió el PADRE a petición del hijo, en el workspace correcto.
        assert (tmp_path / "saludo.txt").read_text(encoding="utf-8") == "hola"
        salida = buffer.getvalue()
        assert "obrero" in salida
        assert "SUBAGENTE" in salida or "subagente" in salida.lower()
        # Y quedó bitácora del intercambio padre↔hijo.
        logs = tmp_path / "home" / ".mgm" / "logs" / app.session.meta.id
        assert (logs / "obrero.jsonl").is_file()

    async def test_una_regla_del_padre_ata_al_subagente_ya_lanzado(self, tmp_path):
        """El subagente SÍ arranca, pide escribir, y el padre se lo niega por regla."""
        import io

        from rich.console import Console

        from mgm.app import build_app
        from mgm.ui.console import TEMA

        guion = [
            '<tool name="task" label="atado">escribe prohibido.txt y permitido.txt</tool>',
            '<tool name="write_file" path="prohibido.txt">x</tool>',
            '<tool name="write_file" path="permitido.txt">y</tool>',
            "Uno me lo negaron, el otro lo escribí.",
            "El subagente terminó con una denegación.",
        ]
        app = build_app(
            console=Console(file=io.StringIO(), force_terminal=False, width=100, theme=TEMA),
            workspace=tmp_path,
            home=tmp_path / "home",
            mode="libre",
            transport="fake",
        )
        app.broker.set_transport(FakeTransport(script=guion))
        # Regla del padre: nadie escribe ese archivo, ni siquiera en modo libre.
        app.permissions.deny_rule("write_file(prohibido.txt)", scope="session")

        await app.run_turn("delega dos escrituras")

        # El subagente arrancó de verdad y escribió lo permitido...
        assert (tmp_path / "permitido.txt").read_text(encoding="utf-8") == "y"
        # ...pero la regla del padre lo ató para lo prohibido.
        assert not (tmp_path / "prohibido.txt").exists()
        bitacora = (tmp_path / "home" / ".mgm" / "logs" / app.session.meta.id / "atado.jsonl")
        assert "DENEGADO" in bitacora.read_text(encoding="utf-8")
