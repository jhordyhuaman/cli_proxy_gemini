"""Entrada de mgm: argumentos, bucle de teclado y modo no interactivo."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.panel import Panel

from . import __version__
from .app import App, build_app
from .commands import AYUDA_COMANDOS, SALIR, ejecutar_comando
from .config import load_cookies, load_credentials, mgm_dir, save_credentials
from .permissions import DEFAULT_MODE, MODES
from .session import SessionStore
from .transport import TransportError
from .ui import MgmCompleter, PermissionAsker, make_console

COOKIE_DEFECTO = "__Secure-1PSID"

#: Un gema pequeña — guiño a Gemini — en ASCII puro para que se vea bien en
#: cualquier terminal, incluida una consola de Windows sin nada configurado.
MASCOTA = r"""
    /\
   /  \
  /----\
  \    /
   \  /
    \/
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="mgm",
        description="mgm — agente de IA de terminal, en español.",
        epilog="Sin argumentos abre la sesión interactiva.",
    )
    p.add_argument("prompt", nargs="*", help="pregunta suelta; con esto no se abre el REPL")
    p.add_argument("-p", "--print", dest="imprimir", metavar="TEXTO",
                   help="responde una sola vez y termina (para scripts)")
    p.add_argument("-c", "--continue", dest="continuar", action="store_true",
                   help="retoma la última sesión de esta carpeta (ya es el comportamiento "
                        "por defecto; se mantiene por compatibilidad)")
    p.add_argument("-r", "--resume", dest="resume", metavar="ID", help="retoma una sesión por id")
    p.add_argument("-n", "--nueva", dest="nueva", action="store_true",
                   help="empieza una sesión nueva en esta carpeta, ignorando la anterior")
    p.add_argument("--modo", choices=MODES, default=DEFAULT_MODE, help="modo de permisos")
    p.add_argument("--transporte", choices=("fake", "g4f", "gemini-cli"),
                   help="fuerza un transporte concreto")
    p.add_argument("--workspace", metavar="RUTA", help="carpeta de trabajo (defecto: la actual)")
    p.add_argument("--modelo", metavar="NOMBRE",
                   help="modelo de g4f a usar (defecto: gemini-auto)")
    p.add_argument("--cookie", metavar="VALOR",
                   help=f"guarda la cookie de Gemini ({COOKIE_DEFECTO}) y termina. "
                        "También acepta el header Cookie: completo ('a=1; b=2; ...')")
    p.add_argument("--cookie-nombre", default=COOKIE_DEFECTO, help="nombre de la cookie a guardar")
    p.add_argument("--sesiones", action="store_true", help="lista las sesiones guardadas y termina")
    p.add_argument("--actualizar", action="store_true",
                   help="trae la última versión desde GitHub y termina")
    p.add_argument("--diagnostico", action="store_true",
                   help="comprueba que mgm funciona en esta máquina y termina")
    p.add_argument("--con-red", action="store_true",
                   help="en el diagnóstico, prueba también la conexión real con Gemini")
    p.add_argument("--max-iteraciones", type=int, default=25, help="tope de iteraciones por turno")
    p.add_argument("-V", "--version", action="version", version=f"mgm {__version__}")
    return p.parse_args(argv)


def parsear_volcado_cookies(texto: str) -> dict[str, str]:
    """Separa un header 'Cookie:' completo ('a=1; b=2; ...') en pares nombre→valor.

    Devuelve {} si el texto no parece un volcado (sin '='), señal de que es un
    valor suelto para una sola cookie.
    """
    texto = texto.strip()
    if "=" not in texto:
        return {}
    pares: dict[str, str] = {}
    for trozo in texto.split(";"):
        nombre, sep, valor = trozo.partition("=")
        if sep and nombre.strip():
            pares[nombre.strip()] = valor.strip()
    return pares


def guardar_cookie(valor: str, nombre: str, home: Path, console) -> int:
    creds = load_credentials(home)
    cookies = dict(creds.get("cookies", {}))
    volcado = parsear_volcado_cookies(valor)
    if volcado:
        cookies.update(volcado)
        ruta = save_credentials(cookies, home)
        console.print(f"[ok]{len(volcado)} cookies guardadas en[/ok] {ruta}")
        console.print(f"[apagado]Nombres: {', '.join(sorted(volcado))}[/apagado]")
    else:
        cookies[nombre] = valor.strip()
        ruta = save_credentials(cookies, home)
        console.print(f"[ok]Cookie '{nombre}' guardada en[/ok] {ruta}")
    console.print("[apagado]Compruébala con: mgm --transporte g4f  y luego /salud[/apagado]")
    return 0


def listar_sesiones(home: Path, workspace: Path, console) -> int:
    store = SessionStore(mgm_dir(home) / "sessions")
    metas = store.list(workspace=workspace, limit=30)
    if not metas:
        console.print("[apagado]No hay sesiones guardadas para esta carpeta.[/apagado]")
        return 0
    for meta in metas:
        console.print(
            f"[bold]{meta.id}[/bold]  {meta.updated_label}  {meta.turns} turno(s)  "
            f"{meta.title or '(sin título)'}"
        )
    return 0


def recuperar_sesion(args, home: Path, workspace: Path, console):
    """Decide con qué sesión arrancar: --resume > --nueva > auto-continuar (defecto)."""
    store = SessionStore(mgm_dir(home) / "sessions")
    if args.resume:
        sesion = store.load(args.resume)
        if sesion is None:
            console.print(f"[error]No existe la sesión[/error] {args.resume}")
            raise SystemExit(2)
        return sesion
    if args.nueva:
        return None
    return store.latest(workspace=workspace)


def banner(app: App) -> Panel:
    mascota = MASCOTA.strip("\n")
    lineas = [
        f"[marca]{mascota}[/marca]",
        f"[marca]mgm v{__version__}[/marca] — tu agente de terminal",
    ]
    if app.session.meta.turns > 0:
        lineas.append(
            f"[apagado]Retomando sesión del {app.session.meta.updated_label} · "
            f"{app.session.meta.turns} turno(s) previos · usa -n para empezar de cero[/apagado]"
        )
    lineas.append(f"[apagado]{app.resumen_estado()}[/apagado]")
    lineas.append(
        "[apagado]/ayuda para los comandos · @archivo para adjuntar · Ctrl-D para salir[/apagado]"
    )
    return Panel("\n".join(lineas), border_style="marca")


async def mostrar_estado_de_cuenta(app: App) -> None:
    """Aviso al arrancar: con qué cuenta de Gemini se está hablando, si es que hay alguna.

    El objetivo del proyecto entero es no usar sin darte cuenta el endpoint
    anónimo de g4f en vez de tu cuenta Pro — por eso esto se muestra siempre
    que hay un transporte 'g4f' en juego, no solo en /diagnóstico.
    """
    transporte = app.broker.transport
    if getattr(transporte, "name", "") != "g4f":
        return
    if not transporte.usa_tu_cuenta:
        app.console.print(
            "[warning]Usando el endpoint automático de g4f: NO es tu cuenta de Gemini.[/warning]"
        )
        return
    try:
        sesion = await transporte.verificar_sesion()
    except TransportError as exc:
        app.console.print(f"[apagado]No se pudo verificar la sesión de Gemini ({exc}).[/apagado]")
        return
    if sesion.valida:
        app.console.print(f"[ok]Conectado a Gemini como {sesion.email or '(correo no detectado)'}[/ok]")
    else:
        app.console.print(
            f"[error]Tu cookie de Gemini venció o fue rechazada.[/error] [apagado]{sesion.detalle}[/apagado]"
        )


async def run_repl(app: App, home: Path) -> int:
    historial = mgm_dir(home)
    historial.mkdir(parents=True, exist_ok=True)
    session: PromptSession = PromptSession(
        history=FileHistory(str(historial / "history")),
        completer=MgmCompleter(AYUDA_COMANDOS, app.workspace),
    )
    app.loop.asker = PermissionAsker(app.console, session, app.workspace)
    app.supervisor.asker = app.loop.asker

    app.console.print(banner(app))
    if app.broker.transport.name == "fake" and not load_cookies(home):
        app.console.print(
            "[warning]Sin cookie configurada: estás usando Gemini sin tu cuenta (transporte "
            "'fake', sin red).[/warning]\n"
            "[apagado]Guárdala con: mgm --cookie 'TU_VALOR'[/apagado]"
        )
    else:
        await mostrar_estado_de_cuenta(app)

    while True:
        try:
            entrada = (await session.prompt_async("\nmgm> ")).strip()
        except KeyboardInterrupt:
            continue
        except EOFError:
            app.console.print("[apagado]Hasta luego.[/apagado]")
            return 0

        if not entrada:
            continue
        if entrada.startswith("/"):
            if await ejecutar_comando(app, entrada) == SALIR:
                return 0
            continue

        try:
            await app.run_turn(entrada)
        except KeyboardInterrupt:
            app.console.print("\n[warning]Turno cancelado.[/warning]")
        except asyncio.CancelledError:
            app.console.print("\n[warning]Turno cancelado.[/warning]")


async def run_once(app: App, texto: str) -> int:
    await app.run_turn(texto)
    return 0


async def _main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    console = make_console()
    home = Path.home()
    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else Path.cwd()

    if args.cookie:
        return guardar_cookie(args.cookie, args.cookie_nombre, home, console)
    if args.sesiones:
        return listar_sesiones(home, workspace, console)
    if args.actualizar:
        from .actualizar import actualizar

        console.print("[apagado]Buscando la última versión en GitHub…[/apagado]")
        ok, detalle = await asyncio.to_thread(actualizar)
        console.print(f"[ok]{detalle}[/ok]" if ok else f"[error]No se pudo actualizar:[/error] {detalle}")
        return 0 if ok else 1
    if args.diagnostico:
        from .config import load_config
        from .diagnostico import diagnosticar, imprimir

        config = load_config(home=home, cwd=workspace)
        chequeos = await diagnosticar(
            home, workspace, probar_red=args.con_red,
            model=config.model, provider=config.provider,
        )
        return imprimir(console, chequeos)

    sesion = recuperar_sesion(args, home, workspace, console)
    app = build_app(
        console=console,
        workspace=workspace,
        home=home,
        mode=args.modo,
        transport=args.transporte,
        modelo=args.modelo,
        session=sesion,
        max_iterations=args.max_iteraciones,
    )

    suelto = " ".join(args.prompt).strip()
    unico = args.imprimir or suelto
    if unico:
        return await run_once(app, unico)
    return await run_repl(app, home)


def main() -> None:
    try:
        sys.exit(asyncio.run(_main()))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
