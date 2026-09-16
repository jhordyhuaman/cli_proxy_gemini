"""Verificación real de sesión de G4FCookieTransport contra gemini.google.com/app.

Todo simulado con monkeypatch sobre _descargar_app_html / urlopen: sin red.
"""

import urllib.error
import urllib.request

import pytest

import mgm.transport.g4f_cookie as mod
from mgm.transport import Health, InferenceBroker, TransportError
from mgm.transport.g4f_cookie import G4FCookieTransport

COOKIES = {"__Secure-1PSID": "valor"}
HTML_VALIDO = "<html><head>SNlM0e</head><body>jhordyrx@gmail.com</body></html>"
HTML_SIN_EMAIL = "<html><head>SNlM0e</head><body>sin correo</body></html>"
HTML_ANONIMO = "<html><head>otros tokens</head><body>Inicia sesión</body></html>"


def make_transport(monkeypatch, html=HTML_VALIDO, probe_texto=("ok",)):
    monkeypatch.setattr(mod, "_descargar_app_html", lambda cookies: html)
    monkeypatch.setattr(mod, "_import_g4f", lambda: object())
    transport = G4FCookieTransport(COOKIES)
    transport._create_stream = lambda mensajes: iter(probe_texto)
    return transport


class TestVerificarSesion:
    async def test_valida_con_email(self, monkeypatch):
        transport = make_transport(monkeypatch)
        sesion = await transport.verificar_sesion()
        assert sesion.valida
        assert sesion.email == "jhordyrx@gmail.com"

    async def test_el_email_es_el_mas_frecuente_no_el_primero(self, monkeypatch):
        html = (
            "<html>SNlM0e googlers@google.com jhordyrx@gmail.com "
            "jhordyrx@gmail.com jhordyrx@gmail.com</html>"
        )
        transport = make_transport(monkeypatch, html=html)
        sesion = await transport.verificar_sesion()
        assert sesion.valida
        assert sesion.email == "jhordyrx@gmail.com"

    async def test_valida_sin_email(self, monkeypatch):
        transport = make_transport(monkeypatch, html=HTML_SIN_EMAIL)
        sesion = await transport.verificar_sesion()
        assert sesion.valida
        assert sesion.email is None

    async def test_html_200_sin_token_es_sesion_invalida(self, monkeypatch):
        transport = make_transport(monkeypatch, html=HTML_ANONIMO)
        sesion = await transport.verificar_sesion()
        assert not sesion.valida
        assert "anónima" in sesion.detalle

    async def test_error_de_red_no_es_cookie_vencida(self, monkeypatch):
        def fetch_roto(cookies):
            raise TransportError("no se pudo contactar gemini.google.com (DNS)")

        monkeypatch.setattr(mod, "_descargar_app_html", fetch_roto)
        with pytest.raises(TransportError, match="no se pudo contactar"):
            await G4FCookieTransport(COOKIES).verificar_sesion()

    async def test_sin_cookies(self):
        sesion = await G4FCookieTransport({}).verificar_sesion()
        assert not sesion.valida
        assert "credentials.json" in sesion.detalle


class TestDescargarAppHtml:
    def test_exito_devuelve_html(self, monkeypatch):
        class _Headers:
            def get_content_charset(self):
                return "utf-8"

        class Resp:
            headers = _Headers()

            def read(self):
                return "<html>SNlM0e</html>".encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: Resp())
        assert "SNlM0e" in mod._descargar_app_html(COOKIES)

    def test_http_error_es_transport_error_no_sesion_invalida(self, monkeypatch):
        def urlopen(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 500, "server", None, None)

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        with pytest.raises(TransportError, match="HTTP 500"):
            mod._descargar_app_html(COOKIES)

    def test_url_error_es_transport_error(self, monkeypatch):
        def urlopen(req, timeout):
            raise urllib.error.URLError("sin DNS")

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        with pytest.raises(TransportError, match="no se pudo contactar"):
            mod._descargar_app_html(COOKIES)


class TestHealth:
    async def test_valida_reporta_email_y_sondea_texto(self, monkeypatch):
        transport = make_transport(monkeypatch)
        health = await transport.health()
        assert health.ok
        assert "conectado como jhordyrx@gmail.com (tu cuenta)" in health.detail

    async def test_sesion_invalida_no_sondea_texto(self, monkeypatch):
        transport = make_transport(monkeypatch, html=HTML_ANONIMO)
        transport._create_stream = lambda mensajes: pytest.fail(
            "no debió sondear texto con la sesión inválida"
        )
        health = await transport.health()
        assert not health.ok
        assert "cookie venció o fue rechazada" in health.detail
        assert "mgm --cookie" in health.detail

    async def test_error_de_red_reporta_conexion_no_cookie(self, monkeypatch):
        def fetch_roto(cookies):
            raise TransportError("no se pudo contactar gemini.google.com (timeout)")

        monkeypatch.setattr(mod, "_descargar_app_html", fetch_roto)
        health = await G4FCookieTransport(COOKIES).health()
        assert not health.ok
        assert "no se pudo verificar la sesión" in health.detail
        assert "cookie venció" not in health.detail

    async def test_sesion_valida_pero_sonda_sin_texto(self, monkeypatch):
        transport = make_transport(monkeypatch, probe_texto=())
        health = await transport.health()
        assert not health.ok
        assert "no devolvió texto" in health.detail

    async def test_sin_cookies(self):
        health = await G4FCookieTransport({}).health()
        assert not health.ok
        assert "credentials.json" in health.detail

    async def test_provider_auto_no_verifica_cuenta(self, monkeypatch):
        monkeypatch.setattr(mod, "_import_g4f", lambda: object())

        def fetch_que_falla(cookies):
            pytest.fail("en modo auto no debe verificar sesión")

        monkeypatch.setattr(mod, "_descargar_app_html", fetch_que_falla)
        transport = G4FCookieTransport(COOKIES, provider="auto")
        transport._create_stream = lambda mensajes: iter(["ok"])
        health = await transport.health()
        assert health.ok
        assert "anónimo" in health.detail


class TestBroker:
    async def test_auth_error_llega_con_mensaje_claro(self):
        from mgm.transport import AuthError, FakeTransport, Message

        mensaje = (
            "tu cookie venció o fue rechazada: gemini.google.com devolvió una sesión "
            'anónima. Renuévala con: mgm --cookie "nuevo_valor"'
        )
        broker = InferenceBroker(FakeTransport(script=[AuthError(mensaje)]), sleep=_noop)
        with pytest.raises(AuthError) as excinfo:
            async for _ in broker.stream([Message(role="user", content="hola")]):
                pass
        assert str(excinfo.value) == mensaje

    async def test_health_propaga_sesion_invalida(self):
        class SesionCaida:
            name = "stub"

            async def health(self):
                return Health(ok=False, detail="tu cookie venció o fue rechazada")

        broker = InferenceBroker(SesionCaida())
        health = await broker.health()
        assert not health.ok
        assert "cookie venció" in health.detail


async def _noop(delay):
    pass
