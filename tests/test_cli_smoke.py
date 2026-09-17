"""Humo de punta a punta sobre la app completa: entrada → loop → tools → disco → UI."""

import io

import pytest
from rich.console import Console

from mgm.app import build_app, expandir_archivos
from mgm.cli import parse_args
from mgm.commands import SALIR, ejecutar_comando
from mgm.transport import FakeTransport, InferenceBroker
from mgm.ui.console import TEMA


def consola():
    buffer = io.StringIO()
    return Console(file=buffer, force_terminal=False, width=100, theme=TEMA), buffer


def app_de_prueba(tmp_path, guion, *, mode="libre"):
    console, buffer = consola()
    app = build_app(
        console=console,
        workspace=tmp_path,
        home=tmp_path / "home",
        mode=mode,
        transport="fake",
    )
    app.broker.set_transport(FakeTransport(script=guion))
    return app, buffer


class TestTurnoCompleto:
    async def test_el_agente_escribe_un_archivo_y_lo_verifica(self, tmp_path):
        app, buffer = app_de_prueba(
            tmp_path,
            [
                "Voy a crearlo. "
                '<tool name="write_file" path="hola.py">print("hola")</tool>',
                '<tool name="bash">python3 hola.py</tool>',
                "Creé hola.py y lo ejecuté: imprime hola.",
            ],
        )
        await app.run_turn("crea hola.py y compruébalo")
        salida = buffer.getvalue()

        assert (tmp_path / "hola.py").read_text(encoding="utf-8") == 'print("hola")'
        assert "Voy a crearlo." in salida
        assert "write_file" in salida and "bash" in salida
        assert "hola" in salida

    async def test_la_conversacion_queda_guardada_en_disco(self, tmp_path):
        app, _ = app_de_prueba(tmp_path, ["listo"])
        await app.run_turn("hola")
        recargada = app.store.load(app.session.meta.id)
        assert [m.role for m in recargada.messages] == ["user", "assistant"]
        assert recargada.meta.turns == 1
        assert recargada.meta.title == "hola"

    async def test_el_conversation_state_se_persiste_tras_el_turno(self, tmp_path):
        from mgm.transport import Chunk

        app, _ = app_de_prueba(
            tmp_path, [["listo", Chunk(text="", state={"conversation_id": "c1"})]]
        )
        await app.run_turn("hola")
        recargada = app.store.load(app.session.meta.id)
        assert recargada.meta.conversation_state == {"conversation_id": "c1"}

    async def test_reanudar_la_sesion_siembra_el_conversation_state(self, tmp_path):
        from mgm.transport import Chunk

        app, _ = app_de_prueba(
            tmp_path, [["listo", Chunk(text="", state={"conversation_id": "c1"})]]
        )
        await app.run_turn("hola")
        recuperada = app.store.load(app.session.meta.id)

        console, _ = consola()
        app2 = build_app(
            console=console, workspace=tmp_path, home=tmp_path / "home",
            mode="libre", transport="fake", session=recuperada,
        )
        assert app2.loop.conversation_state == {"conversation_id": "c1"}

    async def test_se_puede_retomar_la_sesion(self, tmp_path):
        app, _ = app_de_prueba(tmp_path, ["primera respuesta"])
        await app.run_turn("recuerda el número 7")
        sesion_id = app.session.meta.id

        recuperada = app.store.load(sesion_id)
        console, _ = consola()
        app2 = build_app(
            console=console, workspace=tmp_path, home=tmp_path / "home",
            mode="libre", transport="fake", session=recuperada,
        )
        assert any("número 7" in m.content for m in app2.loop.messages)

    async def test_modo_plan_no_deja_escribir(self, tmp_path):
        app, buffer = app_de_prueba(
            tmp_path,
            ['<tool name="write_file" path="no.txt">x</tool>', "No pude escribir."],
            mode="plan",
        )
        await app.run_turn("escribe no.txt")
        assert not (tmp_path / "no.txt").exists()
        assert "DENEGADO" in buffer.getvalue()

    async def test_compactacion_automatica_al_llenarse_el_contexto(self, tmp_path):
        app, buffer = app_de_prueba(tmp_path, ["a" * 2000] * 8 + ["resumen breve del modelo"])
        app.budget.limit = 4000
        for i in range(8):
            await app.run_turn(f"turno {i}")
        salida = buffer.getvalue()
        assert "Compactado" in salida
        assert app.budget.used(app.loop.messages) < 4000
        assert any("RESUMEN" in m.content for m in app.loop.messages)

    async def test_no_finge_haber_compactado_cuando_no_puede(self, tmp_path):
        app, buffer = app_de_prueba(tmp_path, ["a" * 5000, "ok"])
        app.budget.limit = 1000
        await app.run_turn("dime algo largo")
        salida = buffer.getvalue()
        assert "no hay nada que compactar" in salida
        assert "Compactado:" not in salida


class TestAdjuntos:
    def test_arroba_mete_el_contenido_del_archivo(self, tmp_path):
        (tmp_path / "datos.txt").write_text("valor importante", encoding="utf-8")
        salida = expandir_archivos("revisa @datos.txt por favor", tmp_path)
        assert "valor importante" in salida and "datos.txt" in salida

    def test_arroba_de_archivo_inexistente_se_deja_igual(self, tmp_path):
        texto = "mira @no_existe.txt"
        assert expandir_archivos(texto, tmp_path) == texto

    def test_sin_arroba_no_toca_nada(self, tmp_path):
        assert expandir_archivos("hola mundo", tmp_path) == "hola mundo"


class TestComandos:
    async def test_salir(self, tmp_path):
        app, _ = app_de_prueba(tmp_path, ["x"])
        assert await ejecutar_comando(app, "/salir") == SALIR

    async def test_cambiar_modo(self, tmp_path):
        app, buffer = app_de_prueba(tmp_path, ["x"])
        await ejecutar_comando(app, "/modo plan")
        assert app.permissions.mode == "plan" and app.supervisor.mode == "plan"

    async def test_modo_invalido_avisa(self, tmp_path):
        app, buffer = app_de_prueba(tmp_path, ["x"])
        await ejecutar_comando(app, "/modo turbo")
        assert "desconocido" in buffer.getvalue()
        assert app.permissions.mode == "libre"

    async def test_comando_desconocido_no_revienta(self, tmp_path):
        app, buffer = app_de_prueba(tmp_path, ["x"])
        await ejecutar_comando(app, "/bailar")
        assert "Comando desconocido" in buffer.getvalue()

    async def test_ayuda_lista_los_comandos(self, tmp_path):
        app, buffer = app_de_prueba(tmp_path, ["x"])
        await ejecutar_comando(app, "/ayuda")
        salida = buffer.getvalue()
        assert "/modo" in salida and "/sesiones" in salida and "/skills" in salida
        assert "/actualizar" in salida

    async def test_actualizar_reporta_el_resultado(self, tmp_path, monkeypatch):
        import mgm.commands as mod

        monkeypatch.setattr(mod, "actualizar", lambda: (True, "actualizado: aaa → bbb"))
        app, buffer = app_de_prueba(tmp_path, ["x"])
        await ejecutar_comando(app, "/actualizar")
        assert "actualizado: aaa → bbb" in buffer.getvalue()

    async def test_actualizar_muestra_el_error_con_claridad(self, tmp_path, monkeypatch):
        import mgm.commands as mod

        monkeypatch.setattr(mod, "actualizar", lambda: (False, "git pull falló"))
        app, buffer = app_de_prueba(tmp_path, ["x"])
        await ejecutar_comando(app, "/actualizar")
        assert "git pull falló" in buffer.getvalue()

    async def test_skills_se_listan(self, tmp_path):
        app, buffer = app_de_prueba(tmp_path, ["x"])
        await ejecutar_comando(app, "/skills")
        assert "tdd" in buffer.getvalue()

    async def test_limpiar_abre_sesion_nueva(self, tmp_path):
        app, _ = app_de_prueba(tmp_path, ["uno", "dos"])
        await app.run_turn("hola")
        vieja = app.session.meta.id
        await ejecutar_comando(app, "/limpiar")
        assert app.session.meta.id != vieja and app.loop.messages == []

    async def test_limpiar_tambien_olvida_el_conversation_state(self, tmp_path):
        from mgm.transport import Chunk

        app, _ = app_de_prueba(
            tmp_path, [["listo", Chunk(text="", state={"conversation_id": "c1"})]]
        )
        await app.run_turn("hola")
        assert app.loop.conversation_state == {"conversation_id": "c1"}
        await ejecutar_comando(app, "/limpiar")
        assert app.loop.conversation_state is None

    async def test_contexto_muestra_el_gasto(self, tmp_path):
        app, buffer = app_de_prueba(tmp_path, ["x"])
        await ejecutar_comando(app, "/contexto")
        assert "contexto" in buffer.getvalue() and "modo" in buffer.getvalue()

    async def test_salud_del_transporte_fake(self, tmp_path):
        app, buffer = app_de_prueba(tmp_path, ["x"])
        await ejecutar_comando(app, "/salud")
        assert "OK" in buffer.getvalue()

    async def test_permisos_muestra_reglas_guardadas(self, tmp_path):
        app, buffer = app_de_prueba(tmp_path, ["x"])
        app.permissions.remember("bash(git status:*)", scope="session")
        await ejecutar_comando(app, "/permisos")
        assert "git status" in buffer.getvalue()


class TestArgumentos:
    def test_prompt_suelto(self):
        args = parse_args(["arregla", "el", "login"])
        assert args.prompt == ["arregla", "el", "login"]

    def test_modo_y_transporte(self):
        args = parse_args(["--modo", "plan", "--transporte", "fake"])
        assert args.modo == "plan" and args.transporte == "fake"

    def test_continuar_y_resume(self):
        assert parse_args(["-c"]).continuar is True
        assert parse_args(["-r", "abc123"]).resume == "abc123"

    def test_nueva_fuerza_sesion_limpia(self):
        assert parse_args(["-n"]).nueva is True
        assert parse_args([]).nueva is False

    def test_bandera_actualizar(self):
        assert parse_args(["--actualizar"]).actualizar is True
        assert parse_args([]).actualizar is False

    def test_modo_invalido_muere(self):
        with pytest.raises(SystemExit):
            parse_args(["--modo", "turbo"])

    def test_cookie(self):
        args = parse_args(["--cookie", "SECRETO"])
        assert args.cookie == "SECRETO" and args.cookie_nombre == "__Secure-1PSID"


class TestRecuperarSesion:
    def test_sin_flags_retoma_la_ultima_sesion_de_la_carpeta(self, tmp_path):
        from mgm.cli import parse_args, recuperar_sesion
        from mgm.session import SessionStore

        home = tmp_path / "home"
        store = SessionStore(home / ".mgm" / "sessions")
        previa = store.create(tmp_path)
        store.bump_turn(previa)

        console, _ = consola()
        sesion = recuperar_sesion(parse_args([]), home, tmp_path, console)
        assert sesion is not None and sesion.meta.id == previa.meta.id

    def test_nueva_ignora_la_sesion_previa(self, tmp_path):
        from mgm.cli import parse_args, recuperar_sesion
        from mgm.session import SessionStore

        home = tmp_path / "home"
        SessionStore(home / ".mgm" / "sessions").create(tmp_path)

        console, _ = consola()
        sesion = recuperar_sesion(parse_args(["-n"]), home, tmp_path, console)
        assert sesion is None

    def test_sin_sesion_previa_no_hay_nada_que_retomar(self, tmp_path):
        from mgm.cli import parse_args, recuperar_sesion

        console, _ = consola()
        sesion = recuperar_sesion(parse_args([]), tmp_path / "home", tmp_path, console)
        assert sesion is None


class TestVolcadoCookies:
    def test_valor_suelto_no_es_volcado(self):
        from mgm.cli import parsear_volcado_cookies

        assert parsear_volcado_cookies("g.a000CgmJ8ORRj7QIkESekY2") == {}

    def test_header_completo_se_separa_en_pares(self):
        from mgm.cli import parsear_volcado_cookies

        pares = parsear_volcado_cookies("__Secure-1PSID=abc; __Secure-1PSIDTS=def ; NID=ghi")
        assert pares == {"__Secure-1PSID": "abc", "__Secure-1PSIDTS": "def", "NID": "ghi"}

    def test_valores_con_igual_sobreviven(self):
        from mgm.cli import parsear_volcado_cookies

        pares = parsear_volcado_cookies("COMPASS=gemini-pd=CjwACWuJ; SID=xyz")
        assert pares["COMPASS"] == "gemini-pd=CjwACWuJ"
        assert pares["SID"] == "xyz"

    def test_guardar_volcado_fusiona_sin_borrar_las_demas(self, tmp_path):
        from mgm.cli import guardar_cookie
        from mgm.config import load_cookies

        consola = Console(file=io.StringIO())
        guardar_cookie("valor_viejo", "__Secure-1PSID", tmp_path, consola)
        guardar_cookie("__Secure-1PSIDTS=nuevo_ts; SID=el_sid", "__Secure-1PSID", tmp_path, consola)
        cookies = load_cookies(tmp_path)
        assert cookies["__Secure-1PSID"] == "valor_viejo"
        assert cookies["__Secure-1PSIDTS"] == "nuevo_ts"
        assert cookies["SID"] == "el_sid"


class TestModelo:
    def test_el_defecto_es_el_nombre_que_g4f_entiende(self):
        from mgm.config import Config
        from mgm.transport import MODELO_DEFECTO

        assert Config().model == MODELO_DEFECTO == "gemini-auto"

    def test_los_alias_comodos_se_traducen(self):
        from mgm.transport import resolver_modelo

        assert resolver_modelo("gemini") == "gemini-auto"
        assert resolver_modelo("GEMINI ") == "gemini-auto"
        assert resolver_modelo("") == "gemini-auto"

    def test_un_nombre_explicito_se_respeta(self):
        from mgm.transport import resolver_modelo

        assert resolver_modelo("gemini-2.5-pro") == "gemini-2.5-pro"

    def test_el_transporte_resuelve_el_alias_al_construirse(self):
        from mgm.transport import G4FCookieTransport

        assert G4FCookieTransport({"x": "y"}, model="gemini").model == "gemini-auto"

    async def test_comando_modelo_lo_cambia(self, tmp_path):
        app, buffer = app_de_prueba(tmp_path, ["x"])
        await ejecutar_comando(app, "/modelo gemini-2.5-pro")
        assert app.config.model == "gemini-2.5-pro"
        assert "gemini-2.5-pro" in buffer.getvalue()

    async def test_comando_modelo_sin_argumento_muestra_el_actual(self, tmp_path):
        app, buffer = app_de_prueba(tmp_path, ["x"])
        await ejecutar_comando(app, "/modelo")
        assert "gemini-auto" in buffer.getvalue()

    def test_bandera_modelo(self):
        assert parse_args(["--modelo", "gemini-2.5-pro"]).modelo == "gemini-2.5-pro"

    def test_error_de_modelo_desconocido_es_util(self):
        from mgm.transport.g4f_cookie import _classify_error

        error = _classify_error(RuntimeError("Model not found: gemini"))
        assert "/modelo" in str(error) and "MGM_MODEL" in str(error)


class TestBanner:
    def test_avisa_al_retomar_una_sesion_con_turnos_previos(self, tmp_path):
        from mgm.cli import banner

        app, _ = app_de_prueba(tmp_path, ["ok"])
        app.session.meta.turns = 3
        texto = str(banner(app).renderable)
        assert "Retomando sesión" in texto and "3 turno" in texto

    def test_no_avisa_en_una_sesion_recien_creada(self, tmp_path):
        from mgm.cli import banner

        app, _ = app_de_prueba(tmp_path, ["ok"])
        texto = str(banner(app).renderable)
        assert "Retomando sesión" not in texto

    def test_incluye_la_mascota_ascii(self, tmp_path):
        from mgm.cli import MASCOTA, banner

        app, _ = app_de_prueba(tmp_path, ["ok"])
        texto = str(banner(app).renderable)
        assert MASCOTA.strip("\n") in texto


class TestEstadoDeCuenta:
    async def test_cookie_configurada_no_hace_llamadas_de_red(self, tmp_path, monkeypatch):
        """Abrir mgm nunca debe depender de la red: eso es lo que rompió antes.

        Si mostrar_estado_de_cuenta llamara a verificar_sesion (red real), esta
        prueba fallaría porque _descargar_app_html reventaría al invocarse.
        """
        import mgm.transport.g4f_cookie as mod
        from mgm.cli import mostrar_estado_de_cuenta
        from mgm.transport import G4FCookieTransport

        def explota(cookies):
            raise AssertionError("mostrar_estado_de_cuenta no debe tocar la red")

        monkeypatch.setattr(mod, "_descargar_app_html", explota)
        app, buffer = app_de_prueba(tmp_path, ["x"])
        app.broker.set_transport(G4FCookieTransport({"__Secure-1PSID": "x"}))
        await mostrar_estado_de_cuenta(app)
        assert "/salud" in buffer.getvalue()

    async def test_proveedor_automatico_avisa_que_no_es_tu_cuenta(self, tmp_path):
        from mgm.cli import mostrar_estado_de_cuenta
        from mgm.transport import G4FCookieTransport

        app, buffer = app_de_prueba(tmp_path, ["x"])
        app.broker.set_transport(G4FCookieTransport({"__Secure-1PSID": "x"}, provider="auto"))
        await mostrar_estado_de_cuenta(app)
        assert "no es tu cuenta" in buffer.getvalue().lower()

    async def test_transporte_fake_no_hace_nada(self, tmp_path):
        from mgm.cli import mostrar_estado_de_cuenta

        app, buffer = app_de_prueba(tmp_path, ["x"])
        await mostrar_estado_de_cuenta(app)
        assert buffer.getvalue() == ""
