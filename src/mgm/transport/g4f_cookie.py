"""Transporte primario: Gemini vía g4f (gpt4free) usando la cookie de sesión del usuario."""

from __future__ import annotations

import asyncio
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from typing import AsyncIterator

from .base import AuthError, Chunk, Health, Message, TransportError

_AUTH_HINTS = ("401", "403", "cookie", "auth", "login", "permission", "unauthorized")
_SENTINEL = object()

URL_APP = "https://gemini.google.com/app"
TOKEN_SESION = "SNlM0e"
TIMEOUT_SESION = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


@dataclass
class SesionInfo:
    valida: bool
    email: str | None = None
    detalle: str = ""


def _descargar_app_html(cookies: dict[str, str]) -> str:
    """GET a gemini.google.com/app con las cookies; devuelve el HTML.

    urllib sigue los redirects por defecto. Los errores de red o de HTTP se
    traducen a TransportError: NO significan "cookie vencida" — solo un HTML
    200 sin el token de sesión cuenta como sesión inválida/anónima.
    """
    cabecera = "; ".join(f"{k}={v}" for k, v in cookies.items())
    request = urllib.request.Request(
        URL_APP, headers={"Cookie": cabecera, "User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SESION) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise TransportError(
            f"gemini.google.com respondió HTTP {exc.code} al verificar la sesión"
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise TransportError(f"no se pudo contactar gemini.google.com ({exc})") from exc


def _extraer_email(html: str) -> str | None:
    """El correo de la cuenta es el email MÁS frecuente de la página.

    El HTML contiene otros correos aislados (p. ej. googlers@google.com en
    textos de ayuda); el de la cuenta aparece repetido en los datos de sesión.
    Verificado en vivo: 5 ocurrencias del correo real vs 1 del espurio.
    """
    emails = _EMAIL_RE.findall(html)
    if not emails:
        return None
    return Counter(emails).most_common(1)[0][0]

#: El modelo que enruta al proveedor Gemini con cookie de sesión. En g4f el
#: nombre suelto "gemini" NO existe: el objeto g4f.models.gemini se llama
#: "gemini-auto". Aceptamos los alias cómodos y traducimos.
MODELO_DEFECTO = "gemini-auto"
ALIAS_MODELOS = {
    "gemini": MODELO_DEFECTO,
    "auto": MODELO_DEFECTO,
    "": MODELO_DEFECTO,
}


def es_texto(pieza: object) -> bool:
    """True solo para las piezas del stream que son texto de la respuesta."""
    return isinstance(pieza, str) and pieza != ""


#: Atributos que identifican al objeto Conversation que g4f/Gemini devuelve
#: (g4f.Provider.needs_auth.Gemini.Conversation). Se detecta por duck-typing
#: en vez de importarlo: es una clase interna de un paquete que cambia rápido.
_ATRIBUTOS_CONVERSACION = ("conversation_id", "response_id", "choice_id")


def _es_conversacion(pieza: object) -> bool:
    return not es_texto(pieza) and all(hasattr(pieza, a) for a in _ATRIBUTOS_CONVERSACION)


@dataclass
class _EstadoConversacion:
    """Objeto mínimo que g4f acepta como `conversation=`: solo mira atributos."""

    conversation_id: str
    response_id: str
    choice_id: str
    model: str
    turn_index: int = 0


def _conversacion_desde_estado(state: dict | None) -> "_EstadoConversacion | None":
    if not state:
        return None
    return _EstadoConversacion(
        conversation_id=state.get("conversation_id", ""),
        response_id=state.get("response_id", ""),
        choice_id=state.get("choice_id", ""),
        model=state.get("model", ""),
        turn_index=state.get("turn_index", 0),
    )


def _formatear_para_gemini(mensajes: list[Message]) -> str:
    """Mismo formato que el `format_prompt` de g4f: 'Rol: contenido' por línea.

    Importa que sea idéntico: si a mitad de una conversación le cambiamos el
    formato al modelo, se desorienta.
    """
    return "\n".join(
        f"{m.role.capitalize()}: {m.content}" for m in mensajes if m.content.strip()
    )


def _mensajes_no_sistema(mensajes: list[Message]) -> list[Message]:
    return [m for m in mensajes if m.role != "system"]


def _prompt_incremental(mensajes: list[Message], state: dict | None) -> str:
    """El prompt de sistema (el contrato) + lo que Gemini todavía no ha visto.

    Sin esto hay que elegir entre dos males: con `conversation=` a secas g4f
    manda solo el último mensaje y el modelo pierde el contrato de
    herramientas; con el transcript entero, el hilo del servidor crece al
    cuadrado. Mandando sistema + delta se conserva un solo chat, el contrato
    siempre presente, y crecimiento lineal.
    """
    sistema = [m for m in mensajes if m.role == "system"]
    resto = _mensajes_no_sistema(mensajes)
    ya_vistos = int((state or {}).get("enviados") or 0)
    nuevos = resto[ya_vistos:] or resto[-1:]
    return _formatear_para_gemini(sistema + nuevos)


def _estado_desde_conversacion(conversacion: object) -> dict:
    return {
        "conversation_id": conversacion.conversation_id,
        "response_id": conversacion.response_id,
        "choice_id": conversacion.choice_id,
        "model": getattr(conversacion, "model", ""),
        "turn_index": getattr(conversacion, "turn_index", 0),
    }


def resolver_modelo(nombre: str) -> str:
    limpio = (nombre or "").strip()
    return ALIAS_MODELOS.get(limpio.lower(), limpio)


def modelos_gemini_disponibles() -> list[str]:
    """Nombres de modelo con 'gemini' que conoce el g4f instalado."""
    try:
        from g4f.models import ModelUtils
    except ImportError:
        return []
    return sorted(n for n in ModelUtils.convert if "gemini" in n.lower())


PROVEEDOR_COOKIE = "Gemini"
PROVEEDOR_AUTO = "auto"


def _import_g4f():
    try:
        import g4f
    except ImportError as exc:
        raise TransportError(
            "g4f no está instalado en este entorno. Instálalo con: pip install g4f"
        ) from exc
    try:  # g4f imprime avisos de versión en stdout y ensucian el REPL
        import g4f.debug

        g4f.debug.version_check = False
    except Exception:
        pass
    return g4f


def _classify_error(exc: BaseException) -> TransportError:
    text = str(exc).lower()
    if isinstance(exc, (AuthError, TransportError)):
        return exc
    if "model not found" in text or "modelo no encontrado" in text:
        disponibles = modelos_gemini_disponibles()
        sugerencia = f" Modelos disponibles: {', '.join(disponibles)}." if disponibles else ""
        return TransportError(
            f"g4f no conoce ese modelo ({exc}). Cámbialo con /modelo o con "
            f"MGM_MODEL.{sugerencia}"
        )
    if any(hint in text for hint in _AUTH_HINTS):
        return AuthError(f"la cookie de sesión fue rechazada ({exc})")
    return TransportError(f"falló el endpoint de g4f ({exc})")


class G4FCookieTransport:
    name = "g4f"

    def __init__(
        self,
        cookies: dict[str, str],
        *,
        model: str = MODELO_DEFECTO,
        provider: str = PROVEEDOR_COOKIE,
        conversacion_continua: bool = False,
    ):
        self._cookies = cookies
        self._model = resolver_modelo(model)
        self._provider = (provider or PROVEEDOR_COOKIE).strip()
        self._conversacion_continua = bool(conversacion_continua)

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def usa_tu_cuenta(self) -> bool:
        """True si vamos por tu sesión autenticada y no por un endpoint anónimo."""
        return self._provider.lower() != PROVEEDOR_AUTO

    def _create_stream(self, messages: list[Message], state: dict | None = None):
        g4f = _import_g4f()
        extra = {}
        if self.usa_tu_cuenta:
            # Forzamos el proveedor que usa la cookie. Sin esto g4f puede caer
            # en silencio a un endpoint libre anónimo, y creerías que estás
            # usando tu cuenta Pro cuando no es así.
            extra["provider"] = self._provider
        if self._conversacion_continua and self._provider.lower() == PROVEEDOR_COOKIE.lower():
            # Continuar el MISMO chat en el servidor de Gemini en vez de abrir
            # uno nuevo por llamada.
            conversacion = _conversacion_desde_estado(state)
            extra["conversation"] = conversacion
            extra["return_conversation"] = True
            if conversacion is not None:
                # `prompt` explícito le gana a la lógica de g4f, que con una
                # conversación activa mandaría SOLO el último mensaje del
                # usuario y dejaría al modelo sin el contrato de herramientas.
                extra["prompt"] = _prompt_incremental(messages, state)
        return g4f.ChatCompletion.create(
            model=self._model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            cookies=self._cookies,
            stream=True,
            **extra,
        )

    @staticmethod
    def _next_piece(iterator) -> object:
        """Siguiente pieza de TEXTO, saltando los objetos de control.

        El stream de g4f mezcla el texto con objetos internos del proveedor
        (JsonResponse, Conversation, etc.). Convertirlos a str metería basura
        del protocolo en la conversación, así que se descartan.
        """
        for pieza in iterator:
            if es_texto(pieza):
                return pieza
        return _SENTINEL

    @staticmethod
    def _next_relevante(iterator) -> object:
        """Como _next_piece, pero sin descartar la Conversation de Gemini."""
        for pieza in iterator:
            if es_texto(pieza) or _es_conversacion(pieza):
                return pieza
        return _SENTINEL

    @staticmethod
    def _cerrar(generator) -> None:
        """Cierra el generador de g4f en ESTE hilo, pase lo que pase.

        Si se abandona, lo cierra el recolector de basura más tarde y en otro
        hilo: g4f intenta apagar ahí su propio event loop y revienta con
        "Cannot run the event loop while another loop is running" + deja la
        sesión de aiohttp abierta. Ese ruido sale por stderr en cualquier
        momento y en el REPL se come lo que el usuario está escribiendo.
        """
        cerrar = getattr(generator, "close", None)
        if cerrar is None:
            return
        try:
            cerrar()
        except Exception:
            pass

    async def stream(
        self, messages: list[Message], *, state: dict | None = None
    ) -> AsyncIterator[Chunk]:
        if not self._cookies:
            raise AuthError("no hay cookie configurada en ~/.mgm/credentials.json")
        generator = None
        try:
            generator = await asyncio.to_thread(self._create_stream, messages, state)
            ultimo_estado: dict | None = None
            while True:
                piece = await asyncio.to_thread(self._next_relevante, generator)
                if piece is _SENTINEL:
                    break
                if es_texto(piece):
                    yield Chunk(text=piece)
                else:
                    ultimo_estado = _estado_desde_conversacion(piece)
                    # Lo que a partir de ahora ya vive del lado de Gemini: en la
                    # próxima llamada solo hay que mandarle lo que venga después.
                    ultimo_estado["enviados"] = len(_mensajes_no_sistema(messages))
            if ultimo_estado is not None:
                yield Chunk(text="", state=ultimo_estado)
        except Exception as exc:
            raise _classify_error(exc) from exc
        finally:
            if generator is not None:
                await asyncio.to_thread(self._cerrar, generator)

    async def verificar_sesion(self) -> SesionInfo:
        """Verificación real de sesión contra gemini.google.com/app.

        El proveedor Gemini de g4f responde incluso con cookie inválida (cae
        en silencio a sesión anónima), así que la única señal fiable es la
        página de la app: con sesión autenticada el HTML incluye el token
        SNlM0e y el correo de la cuenta; sin ella, ninguno de los dos.
        Errores de red se propagan como TransportError (no son "cookie vencida").
        """
        if not self._cookies:
            return SesionInfo(
                valida=False,
                detalle="no hay cookie configurada en ~/.mgm/credentials.json",
            )
        html = await asyncio.to_thread(_descargar_app_html, self._cookies)
        if TOKEN_SESION not in html:
            return SesionInfo(
                valida=False,
                detalle=(
                    "gemini.google.com devolvió una sesión anónima: "
                    "la cookie venció o fue rechazada"
                ),
            )
        email = _extraer_email(html)
        return SesionInfo(
            valida=True,
            email=email,
            detalle=f"sesión autenticada como {email}" if email else "sesión autenticada",
        )

    async def health(self) -> Health:
        if not self._cookies:
            return Health(ok=False, detail="no hay cookie configurada en ~/.mgm/credentials.json")
        cuenta = ""
        if self.usa_tu_cuenta:
            try:
                sesion = await self.verificar_sesion()
            except TransportError as exc:
                return Health(ok=False, detail=f"no se pudo verificar la sesión ({exc})")
            if not sesion.valida:
                return Health(
                    ok=False,
                    detail=(
                        "tu cookie venció o fue rechazada: gemini.google.com devolvió "
                        'una sesión anónima. Renuévala con: mgm --cookie "nuevo_valor"'
                    ),
                )
            cuenta = (
                f"conectado como {sesion.email} (tu cuenta)"
                if sesion.email
                else "sesión autenticada (tu cuenta; email no detectado)"
            )
        generator = None
        try:
            _import_g4f()
            probe = [Message(role="user", content="Responde solo: ok")]
            generator = await asyncio.to_thread(self._create_stream, probe)
            piece = await asyncio.to_thread(self._next_piece, generator)
            # La sonda solo necesita la PRIMERA pieza de texto; el resto del
            # stream se descarta, así que hay que cerrarlo aquí mismo.
            await asyncio.to_thread(self._cerrar, generator)
            generator = None
            if piece is _SENTINEL:
                return Health(
                    ok=False,
                    detail="el endpoint no devolvió texto; la sesión puede estar vencida",
                )
            if self.usa_tu_cuenta:
                detalle = (
                    f"{cuenta}; el modelo {self._model!r} responde texto "
                    f"vía el proveedor {self._provider!r}"
                )
            else:
                detalle = (
                    f"responde texto con el modelo {self._model!r} vía proveedor automático "
                    "— puede ser un endpoint libre anónimo, NO tu cuenta"
                )
            return Health(ok=True, detail=detalle)
        except TransportError as exc:
            return Health(ok=False, detail=str(exc))
        except Exception as exc:
            return Health(ok=False, detail=str(_classify_error(exc)))
        finally:
            if generator is not None:
                await asyncio.to_thread(self._cerrar, generator)
