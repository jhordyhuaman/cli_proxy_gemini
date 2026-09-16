"""Diagnóstico del entorno: ¿funciona mgm en ESTA máquina?

Pensado para el momento de estrenar mgm en otro equipo, sobre todo uno con
restricciones: comprueba el intérprete, las dependencias, si se puede escribir
donde hace falta, si la cookie está puesta y —lo más frágil en un Windows
corporativo— si se pueden lanzar procesos hijo para los subagentes.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import load_cookies, mgm_dir

OK = "ok"
AVISO = "aviso"
FALLO = "fallo"

PYTHON_MINIMO = (3, 11)
DEPENDENCIAS = (
    ("rich", True, "la interfaz de terminal"),
    ("prompt_toolkit", True, "el REPL, el historial y el autocompletado"),
    ("g4f", False, "hablar con Gemini de verdad (sin él solo tienes el transporte 'fake')"),
)


@dataclass
class Chequeo:
    nombre: str
    nivel: str
    detalle: str

    @property
    def ok(self) -> bool:
        return self.nivel == OK


def _version_python() -> Chequeo:
    actual = sys.version_info[:2]
    texto = f"{actual[0]}.{actual[1]}"
    if actual >= PYTHON_MINIMO:
        return Chequeo("Python", OK, f"{texto} en {sys.executable}")
    return Chequeo(
        "Python", FALLO,
        f"{texto}: mgm necesita {PYTHON_MINIMO[0]}.{PYTHON_MINIMO[1]} o superior",
    )


def _dependencias() -> list[Chequeo]:
    resultados = []
    for modulo, obligatorio, para_que in DEPENDENCIAS:
        try:
            importlib.import_module(modulo)
        except ImportError:
            nivel = FALLO if obligatorio else AVISO
            resultados.append(
                Chequeo(f"Dependencia {modulo}", nivel,
                        f"no está instalada; hace falta para {para_que}")
            )
        else:
            resultados.append(Chequeo(f"Dependencia {modulo}", OK, "instalada"))
    return resultados


def _escritura(nombre: str, carpeta: Path) -> Chequeo:
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=carpeta, prefix=".mgm_prueba_", delete=True):
            pass
    except OSError as exc:
        return Chequeo(nombre, FALLO, f"no puedo escribir en {carpeta}: {exc}")
    return Chequeo(nombre, OK, str(carpeta))


def _cookie(home: Path) -> Chequeo:
    cookies = load_cookies(home)
    if not cookies:
        return Chequeo(
            "Cookie de Gemini", AVISO,
            "no configurada; mgm usará el transporte 'fake'. "
            "Guárdala con: mgm --cookie \"VALOR\"",
        )
    nombres = ", ".join(sorted(cookies))
    return Chequeo("Cookie de Gemini", OK, f"configurada ({nombres})")


async def _subagentes(workspace: Path) -> Chequeo:
    """Lanza un subagente de verdad. Es lo que más suele bloquearse."""
    from .agent import SubagentSupervisor
    from .permissions import PermissionEngine
    from .tools import ToolContext, default_registry
    from .transport import FakeTransport, InferenceBroker

    with tempfile.TemporaryDirectory() as tmp:
        supervisor = SubagentSupervisor(
            InferenceBroker(FakeTransport(script=["prueba superada"]), max_retries=0),
            default_registry(),
            PermissionEngine("plan"),
            ToolContext(workspace=Path(tmp)),
            timeout=30,
            mode="plan",
        )
        try:
            resultado = await supervisor.run("responde 'prueba superada'", label="diagnostico",
                                             max_iterations=1)
        except Exception as exc:
            return Chequeo("Subagentes (procesos hijo)", FALLO,
                           f"no pude lanzar el proceso: {type(exc).__name__}: {exc}")
    if resultado.ok:
        return Chequeo("Subagentes (procesos hijo)", OK, "un proceso hijo arrancó y respondió")
    return Chequeo("Subagentes (procesos hijo)", FALLO,
                   f"el proceso hijo no respondió bien: {resultado.reason} — {resultado.text[:120]}")


async def _transporte(home: Path, model: str, provider: str = "Gemini") -> Chequeo:
    from .transport import G4FCookieTransport

    cookies = load_cookies(home)
    if not cookies:
        return Chequeo("Conexión con Gemini", AVISO, "sin cookie, no hay nada que probar")
    salud = await G4FCookieTransport(cookies, model=model, provider=provider).health()
    return Chequeo("Conexión con Gemini", OK if salud.ok else FALLO, salud.detail)


async def diagnosticar(
    home: Path,
    workspace: Path,
    *,
    probar_red: bool = False,
    model: str = "gemini-auto",
    provider: str = "Gemini",
) -> list[Chequeo]:
    chequeos: list[Chequeo] = [_version_python(), *_dependencias()]
    chequeos.append(Chequeo("Sistema", OK, f"{sys.platform} ({os.name})"))
    chequeos.append(_escritura("Carpeta de datos", mgm_dir(home)))
    chequeos.append(_escritura("Carpeta de trabajo", workspace))
    chequeos.append(_cookie(home))
    chequeos.append(await _subagentes(workspace))
    if probar_red:
        chequeos.append(await _transporte(home, model, provider))
    return chequeos


def imprimir(console, chequeos: list[Chequeo]) -> int:
    """Pinta el informe. Devuelve el código de salida (0 si nada falló)."""
    marcas = {OK: ("[ok]✓[/ok]", "ok"), AVISO: ("[warning]![/warning]", "warning"),
              FALLO: ("[error]✗[/error]", "error")}
    console.print("[marca]Diagnóstico de mgm[/marca]\n")
    for chequeo in chequeos:
        marca, _ = marcas[chequeo.nivel]
        console.print(f"  {marca} [bold]{chequeo.nombre}[/bold]: {chequeo.detalle}")

    fallos = [c for c in chequeos if c.nivel == FALLO]
    avisos = [c for c in chequeos if c.nivel == AVISO]
    console.print()
    if fallos:
        console.print(f"[error]{len(fallos)} problema(s) que impiden usar mgm.[/error]")
        return 1
    if avisos:
        console.print(f"[warning]Todo lo esencial funciona, con {len(avisos)} aviso(s).[/warning]")
        return 0
    console.print("[ok]Todo en orden.[/ok]")
    return 0
