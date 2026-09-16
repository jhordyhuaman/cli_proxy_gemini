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
    ):
        self._cookies = cookies
        self._model = resolver_modelo(model)
        self._provider = (provider or PROVEEDOR_COOKIE).strip()

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

    def _create_stream(self, messages: list[Message]):
        g4f = _import_g4f()
        extra = {}
        if self.usa_tu_cuenta:
            # Forzamos el proveedor que usa la cookie. Sin esto g4f puede caer
            # en silencio a un endpoint libre anónimo, y creerías que estás
            # usando tu cuenta Pro cuando no es así.
            extra["provider"] = self._provider
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

    async def stream(self, messages: list[Message]) -> AsyncIterator[Chunk]:
        if not self._cookies:
            raise AuthError("no hay cookie configurada en ~/.mgm/credentials.json")
        try:
            generator = await asyncio.to_thread(self._create_stream, messages)
            while True:
                piece = await asyncio.to_thread(self._next_piece, generator)
                if piece is _SENTINEL:
                    break
                yield Chunk(text=piece)
        except Exception as exc:
            raise _classify_error(exc) from exc

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
        try:
            _import_g4f()
            probe = [Message(role="user", content="Responde solo: ok")]
            generator = await asyncio.to_thread(self._create_stream, probe)
            piece = await asyncio.to_thread(self._next_piece, generator)
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
