"""El generador de g4f SIEMPRE debe cerrarse.

Si se abandona, el recolector de basura lo cierra después y en el hilo
equivocado: g4f intenta apagar su propio event loop y revienta con
"Cannot run the event loop while another loop is running" + "Unclosed client
session". Ese ruido sale por stderr en cualquier momento y en el REPL llega a
comerse lo que el usuario está escribiendo. Verificado en vivo contra Gemini.
"""
import mgm.transport.g4f_cookie as mod
from mgm.transport import Message
from mgm.transport.g4f_cookie import G4FCookieTransport

COOKIES = {"__Secure-1PSID": "x"}
HTML_VALIDO = "<html>SNlM0e correo@ejemplo.com</html>"


class GeneradorFalso:
    """Imita al generador síncrono de g4f: itera piezas y registra su cierre."""

    def __init__(self, piezas):
        self._it = iter(piezas)
        self.cerrado = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._it)

    def close(self):
        self.cerrado = True


async def test_stream_cierra_el_generador_al_terminar():
    generador = GeneradorFalso(["hola", " mundo"])
    transporte = G4FCookieTransport(COOKIES)
    transporte._create_stream = lambda mensajes, state=None: generador

    piezas = [c.text async for c in transporte.stream([Message(role="user", content="hi")])]

    assert piezas == ["hola", " mundo"]
    assert generador.cerrado


async def test_stream_cierra_el_generador_aunque_falle():
    def explota():
        yield "algo"
        raise RuntimeError("el endpoint se cayó")

    class GeneradorQueFalla(GeneradorFalso):
        def __init__(self):
            super().__init__([])
            self._interno = explota()

        def __next__(self):
            return next(self._interno)

    generador = GeneradorQueFalla()
    transporte = G4FCookieTransport(COOKIES)
    transporte._create_stream = lambda mensajes, state=None: generador

    try:
        _ = [c async for c in transporte.stream([Message(role="user", content="hi")])]
    except Exception:
        pass

    assert generador.cerrado


async def test_health_cierra_el_generador_de_la_sonda(monkeypatch):
    generador = GeneradorFalso(["ok", "sobra", "mas"])
    monkeypatch.setattr(mod, "_descargar_app_html", lambda cookies: HTML_VALIDO)
    monkeypatch.setattr(mod, "_import_g4f", lambda: object())
    transporte = G4FCookieTransport(COOKIES)
    transporte._create_stream = lambda mensajes, state=None: generador

    salud = await transporte.health()

    assert salud.ok
    assert generador.cerrado, "health() dejó el generador de g4f abierto"
