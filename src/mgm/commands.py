"""Comandos de barra del REPL. Separados para poder probarlos sin terminal."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from .actualizar import actualizar
from .app import TRANSPORTES, App, build_transport
from .permissions import MODE_HELP, MODES
from .session import compact

SALIR = "__salir__"


@dataclass
class Comando:
    nombre: str
    ayuda: str
    handler: Callable[[App, str], Awaitable[str | None]]


async def cmd_ayuda(app: App, resto: str) -> None:
    app.console.print("[marca]Comandos disponibles[/marca]")
    for nombre in sorted(COMANDOS):
        app.console.print(f"  [bold]{nombre:<14}[/bold] {COMANDOS[nombre].ayuda}")
    app.console.print(
        "\n[apagado]Escribe @ruta/al/archivo para adjuntar su contenido. "
        "Ctrl-C cancela el turno, Ctrl-D sale.[/apagado]"
    )


async def cmd_salir(app: App, resto: str) -> str:
    app.console.print("[apagado]Hasta luego.[/apagado]")
    return SALIR


async def cmd_modo(app: App, resto: str) -> None:
    nuevo = resto.strip().lower()
    if not nuevo:
        app.console.print(f"Modo actual: [bold]{app.permissions.mode}[/bold]")
        for modo in MODES:
            marca = "→" if modo == app.permissions.mode else " "
            app.console.print(f"  {marca} [bold]{modo:<11}[/bold] {MODE_HELP[modo]}")
        return
    if nuevo not in MODES:
        app.console.print(f"[error]Modo desconocido:[/error] {nuevo}. Opciones: {', '.join(MODES)}")
        return
    app.permissions.set_mode(nuevo)
    app.supervisor.mode = nuevo
    app.console.print(f"[ok]Modo cambiado a '{nuevo}':[/ok] {MODE_HELP[nuevo]}")


async def cmd_permisos(app: App, resto: str) -> None:
    reglas = app.permissions.effective
    if not reglas.allow and not reglas.deny:
        app.console.print("[apagado]No hay reglas guardadas: se pregunta según el modo.[/apagado]")
        return
    if reglas.allow:
        app.console.print("[ok]Permitidas:[/ok]")
        for regla in reglas.allow:
            app.console.print(f"  · {regla}")
    if reglas.deny:
        app.console.print("[error]Prohibidas:[/error]")
        for regla in reglas.deny:
            app.console.print(f"  · {regla}")


async def cmd_transporte(app: App, resto: str) -> None:
    nuevo = resto.strip().lower()
    if not nuevo:
        app.console.print(f"Transporte activo: [bold]{app.broker.transport.name}[/bold]")
        app.console.print(f"[apagado]Opciones: {', '.join(TRANSPORTES)}[/apagado]")
        return
    from .config import load_cookies

    try:
        app.broker.set_transport(build_transport(nuevo, app.config, load_cookies(app.home)))
    except ValueError as exc:
        app.console.print(f"[error]{exc}[/error]")
        return
    app.console.print(f"[ok]Transporte cambiado a '{nuevo}'.[/ok]")


async def cmd_modelo(app: App, resto: str) -> None:
    from .transport import modelos_gemini_disponibles, resolver_modelo

    nuevo = resto.strip()
    if not nuevo:
        app.console.print(f"Modelo actual: [bold]{app.config.model}[/bold]")
        if app.modelo_real:
            app.console.print(f"[apagado]Respondiendo de verdad: {app.modelo_real}[/apagado]")
            if "flash" in app.modelo_real.lower():
                app.console.print(
                    "[warning]Estás en un modelo rápido (flash): para tareas de código "
                    "rinde bastante menos.[/warning]\n"
                    "[apagado]Prueba: /modelo gemini-3.8-pro  (o gemini-2.5-pro)[/apagado]"
                )
        disponibles = modelos_gemini_disponibles()
        if disponibles:
            app.console.print("[apagado]Disponibles en tu g4f:[/apagado]")
            for nombre in disponibles:
                marca = "→" if nombre == app.config.model else " "
                app.console.print(f"  {marca} {nombre}")
        else:
            app.console.print(
                "[apagado]g4f no está instalado, así que no puedo listar modelos.[/apagado]"
            )
        return

    app.config.model = resolver_modelo(nuevo)
    # Si el transporte vivo es g4f, hay que reconstruirlo para que lo use.
    if app.broker.transport.name == "g4f":
        from .config import load_cookies

        app.broker.set_transport(build_transport("g4f", app.config, load_cookies(app.home)))
    app.console.print(
        f"[ok]Modelo cambiado a '{app.config.model}'.[/ok] "
        "[apagado]Compruébalo con /salud.[/apagado]"
    )


async def cmd_salud(app: App, resto: str) -> None:
    salud = await app.broker.health()
    estilo = "ok" if salud.ok else "error"
    estado = "OK" if salud.ok else "FALLO"
    app.console.print(
        f"[{estilo}]Transporte '{app.broker.transport.name}': {estado}[/{estilo}]"
        + (f" — {salud.detail}" if salud.detail else "")
    )


async def cmd_contexto(app: App, resto: str) -> None:
    app.console.print(app.resumen_estado())
    app.console.print(f"[apagado]{len(app.loop.messages)} mensajes en la conversación.[/apagado]")


async def cmd_compactar(app: App, resto: str) -> None:
    antes = app.budget.used(app.loop.messages)
    nuevos = await compact(app.loop.messages, app.broker)
    app.loop.messages[:] = nuevos
    app.store.replace_messages(app.session, nuevos)
    app.console.print(
        f"[ok]Compactado:[/ok] {antes} → {app.budget.used(app.loop.messages)} tokens estimados."
    )


async def cmd_sesiones(app: App, resto: str) -> None:
    metas = app.store.list(workspace=app.workspace, limit=15)
    if not metas:
        app.console.print("[apagado]No hay sesiones guardadas para esta carpeta.[/apagado]")
        return
    app.console.print("[marca]Sesiones de esta carpeta[/marca] [apagado](reanuda con: mgm --resume ID)[/apagado]")
    for meta in metas:
        actual = " [ok]← actual[/ok]" if meta.id == app.session.meta.id else ""
        app.console.print(
            f"  [bold]{meta.id}[/bold]  {meta.updated_label}  "
            f"{meta.turns} turno(s)  {meta.title or '(sin título)'}{actual}"
        )


async def cmd_skills(app: App, resto: str) -> None:
    if not len(app.skills):
        app.console.print("[apagado]No hay skills cargadas.[/apagado]")
        return
    app.console.print("[marca]Skills cargadas[/marca]")
    for skill in app.skills.all():
        app.console.print(
            f"  [bold]{skill.name:<12}[/bold] [apagado]({skill.scope})[/apagado] {skill.description}"
        )


async def cmd_memoria(app: App, resto: str) -> None:
    from .session import discover

    archivos = discover(app.workspace, app.home)
    if not archivos:
        app.console.print(
            "[apagado]No hay MGM.md. Crea uno en esta carpeta con lo que mgm "
            "deba recordar siempre.[/apagado]"
        )
        return
    for archivo in archivos:
        app.console.print(f"[marca]{archivo.path}[/marca] [apagado]({archivo.scope})[/apagado]")
        app.console.print(archivo.content[:600], markup=False)


async def cmd_limpiar(app: App, resto: str) -> None:
    app.loop.messages.clear()
    app.loop.conversation_state = None
    app.session = app.store.create(app.workspace)
    app.console.print(f"[ok]Sesión nueva:[/ok] {app.session.meta.id}")


async def cmd_actualizar(app: App, resto: str) -> None:
    app.console.print("[apagado]Buscando la última versión en GitHub…[/apagado]")
    ok, detalle = await asyncio.to_thread(actualizar)
    if ok:
        app.console.print(f"[ok]{detalle}[/ok] [apagado](reinicia mgm para usarla)[/apagado]")
    else:
        app.console.print(f"[error]No se pudo actualizar:[/error] {detalle}")


async def cmd_herramientas(app: App, resto: str) -> None:
    app.mostrar_herramientas = not app.mostrar_herramientas
    estado = "visibles" if app.mostrar_herramientas else "ocultas"
    app.console.print(f"[ok]Salida de herramientas: {estado}.[/ok]")


COMANDOS: dict[str, Comando] = {
    "/ayuda": Comando("/ayuda", "esta lista", cmd_ayuda),
    "/salir": Comando("/salir", "termina la sesión", cmd_salir),
    "/exit": Comando("/exit", "alias de /salir", cmd_salir),
    "/modo": Comando("/modo", "ver o cambiar el modo de permisos", cmd_modo),
    "/permisos": Comando("/permisos", "reglas de permiso guardadas", cmd_permisos),
    "/transporte": Comando("/transporte", "ver o cambiar el transporte", cmd_transporte),
    "/salud": Comando("/salud", "probar que el transporte responde", cmd_salud),
    "/modelo": Comando("/modelo", "ver o cambiar el modelo de Gemini", cmd_modelo),
    "/contexto": Comando("/contexto", "cuánto contexto llevas gastado", cmd_contexto),
    "/compactar": Comando("/compactar", "resumir la conversación ahora", cmd_compactar),
    "/sesiones": Comando("/sesiones", "sesiones guardadas de esta carpeta", cmd_sesiones),
    "/skills": Comando("/skills", "skills disponibles", cmd_skills),
    "/memoria": Comando("/memoria", "qué MGM.md se cargó", cmd_memoria),
    "/herramientas": Comando("/herramientas", "mostrar u ocultar la salida de las tools", cmd_herramientas),
    "/limpiar": Comando("/limpiar", "empezar una sesión nueva", cmd_limpiar),
    "/actualizar": Comando("/actualizar", "traer la última versión desde GitHub", cmd_actualizar),
}

AYUDA_COMANDOS = {nombre: c.ayuda for nombre, c in COMANDOS.items()}


async def ejecutar_comando(app: App, texto: str) -> str | None:
    nombre, _, resto = texto.partition(" ")
    comando = COMANDOS.get(nombre.lower())
    if comando is None:
        app.console.print(
            f"[warning]Comando desconocido:[/warning] {nombre} "
            "[apagado](usa /ayuda)[/apagado]"
        )
        return None
    return await comando.handler(app, resto)
