"""Ensamblado de la aplicación: junta transporte, permisos, sesión, skills y loop.

Está separado del `cli` (que solo se ocupa de argumentos y del bucle de
teclado) para poder probar la aplicación entera sin terminal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from .agent import AgentLoop, SubagentSupervisor, build_system_prompt
from .agent.events import (
    AssistantText,
    LoopError,
    ToolDecided,
    ToolExecuted,
    ToolRequested,
    TurnEnd,
)
from .config import Config, load_config, load_cookies, mgm_dir
from .permissions import PermissionEngine, load_engine
from .session import ContextBudget, SessionStore, compact, load_memory, messages_tokens
from .skills import load_library
from .tools import ToolContext, default_registry
from .transport import (
    FakeTransport,
    G4FCookieTransport,
    GeminiCLITransport,
    InferenceBroker,
    Transport,
)
from .ui.console import acortar, panel_resultado

TRANSPORTES = ("fake", "g4f", "gemini-cli")
RE_ARCHIVO = re.compile(r"@([^\s@]+)")
MAX_BYTES_ADJUNTO = 100_000


def build_transport(nombre: str, config: Config, cookies: dict[str, str]) -> Transport:
    if nombre == "fake":
        return FakeTransport()
    if nombre == "g4f":
        return G4FCookieTransport(cookies, model=config.model, provider=config.provider)
    if nombre == "gemini-cli":
        return GeminiCLITransport()
    raise ValueError(f"transporte desconocido: {nombre!r}. Opciones: {', '.join(TRANSPORTES)}")


def elegir_transporte(config: Config, cookies: dict[str, str]) -> str:
    if config.transport != "auto":
        return config.transport
    return "g4f" if cookies else "fake"


def expandir_archivos(texto: str, workspace: Path) -> str:
    """Sustituye @ruta por el contenido real del archivo."""
    adjuntos: list[str] = []

    def reemplazo(match: re.Match) -> str:
        crudo = match.group(1)
        destino = (workspace / crudo).resolve()
        try:
            if not destino.is_file() or destino.stat().st_size > MAX_BYTES_ADJUNTO:
                return match.group(0)
            contenido = destino.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            return match.group(0)
        adjuntos.append(f"--- contenido de {crudo} ---\n{contenido}")
        return crudo

    cuerpo = RE_ARCHIVO.sub(reemplazo, texto)
    if not adjuntos:
        return texto
    return cuerpo + "\n\n" + "\n\n".join(adjuntos)


@dataclass
class App:
    console: Console
    config: Config
    workspace: Path
    home: Path
    broker: InferenceBroker
    permissions: PermissionEngine
    store: SessionStore
    session: object
    loop: AgentLoop
    budget: ContextBudget
    skills: object
    supervisor: SubagentSupervisor
    mostrar_herramientas: bool = True

    # ------------------------------------------------------------- eventos UI

    def on_event(self, evento) -> None:
        if isinstance(evento, AssistantText):
            self.console.print(evento.text, end="", markup=False, highlight=False)
        elif isinstance(evento, ToolRequested):
            if self.mostrar_herramientas:
                self.console.print(
                    f"\n[tool]⚒ {evento.summary}[/tool] "
                    f"[riesgo.{evento.risk}]({evento.risk})[/riesgo.{evento.risk}]"
                )
        elif isinstance(evento, ToolDecided):
            if evento.decision.outcome == "deny":
                self.console.print(f"  [error]denegado:[/error] {evento.decision.reason}")
        elif isinstance(evento, ToolExecuted):
            if self.mostrar_herramientas:
                self.console.print(panel_resultado(evento.call.name, evento.result.ok, evento.result.output))
        elif isinstance(evento, LoopError):
            if evento.kind == "auth":
                self.console.print(
                    f"\n[error]La cookie de sesión venció o fue rechazada.[/error] ({evento.detail})\n"
                    f"[apagado]Pégala de nuevo con: mgm --cookie 'valor' — o edita "
                    f"{mgm_dir(self.home) / 'credentials.json'}[/apagado]"
                )
            else:
                self.console.print(f"\n[error]Falló el transporte:[/error] {evento.detail}")
        elif isinstance(evento, TurnEnd):
            self.console.print()
            if evento.reason == "limite":
                self.console.print(
                    f"[warning]Se alcanzó el límite de {evento.iterations} iteraciones "
                    "y pausé el turno por seguridad.[/warning]"
                )

    def on_progress(self, label: str, texto: str) -> None:
        self.console.print(f"[apagado][{label}][/apagado] {acortar(texto, 300)}", markup=True)

    # ---------------------------------------------------------------- turnos

    async def run_turn(self, texto: str) -> None:
        pedido = expandir_archivos(texto, self.workspace)
        antes = len(self.loop.messages)
        await self.loop.run_turn(pedido)
        for mensaje in self.loop.messages[antes:]:
            self.store.append(self.session, mensaje)
        self.session.meta.conversation_state = self.loop.conversation_state
        self.store.bump_turn(self.session)
        await self.compactar_si_hace_falta()

    async def compactar_si_hace_falta(self) -> bool:
        if not self.budget.needs_compaction(self.loop.messages):
            return False
        antes = self.budget.used(self.loop.messages)
        self.console.print("\n[apagado]Contexto casi lleno: compactando…[/apagado]")
        nuevos = await compact(self.loop.messages, self.broker)
        despues = messages_tokens(nuevos)

        if despues >= antes:
            # Pasa con conversaciones cortas de mensajes enormes: no hay medio
            # que resumir. Decirlo, en vez de fingir que se compactó.
            self.console.print(
                "[warning]El contexto está lleno pero no hay nada que compactar[/warning] "
                "[apagado](la conversación es corta y los mensajes son enormes). "
                "Usa /limpiar para empezar de cero.[/apagado]"
            )
            return False

        self.loop.messages[:] = nuevos
        self.store.replace_messages(self.session, nuevos)
        self.console.print(
            f"[ok]Compactado:[/ok] {antes} → {despues} tokens estimados "
            f"({len(nuevos)} mensajes)."
        )
        return True

    # --------------------------------------------------------------- estado

    def refrescar_prompt_sistema(self) -> None:
        self.loop.system_prompt = build_system_prompt(
            self.loop.registry,
            workspace=str(self.workspace),
            memoria=load_memory(self.workspace, self.home),
            skills=self.skills.render_catalog(),
        )

    def resumen_estado(self) -> str:
        usado = self.budget.used(self.loop.messages)
        pct = int(self.budget.ratio(self.loop.messages) * 100)
        return (
            f"transporte {self.broker.transport.name} · modo {self.permissions.mode} · "
            f"contexto {usado}/{self.budget.limit} ({pct}%) · sesión {self.session.meta.id}"
        )


def build_app(
    *,
    console: Console,
    workspace: Path,
    home: Path,
    mode: str = "ask",
    transport: str | None = None,
    modelo: str | None = None,
    session=None,
    environ: dict | None = None,
    max_iterations: int = 25,
    asker=None,
) -> App:
    config = load_config(home=home, cwd=workspace, environ=environ)
    if transport:
        config.transport = transport
    if modelo:
        config.model = modelo
    cookies = load_cookies(home)
    broker = InferenceBroker(
        build_transport(elegir_transporte(config, cookies), config, cookies),
        max_retries=config.max_retries,
        base_delay=config.base_delay,
    )

    permissions = load_engine(mode, home, workspace)
    tool_context = ToolContext(workspace=workspace)
    skills = load_library(workspace, home)
    store = SessionStore(mgm_dir(home) / "sessions")
    session = session or store.create(workspace)

    app_ref: dict[str, App] = {}

    async def lanzar_subagente(prompt: str, *, label: str = "", max_iterations: int = 15):
        return await app_ref["app"].supervisor.run(
            prompt, label=label, max_iterations=max_iterations
        )

    registry = default_registry(skills, task_runner=lanzar_subagente)

    loop = AgentLoop(
        broker,
        registry,
        permissions,
        tool_context,
        messages=list(getattr(session, "messages", []) or []),
        asker=asker,
        max_iterations=max_iterations,
        conversation_state=getattr(session.meta, "conversation_state", None),
    )
    supervisor = SubagentSupervisor(
        broker,
        registry,
        permissions,
        tool_context,
        asker=asker,
        log_dir=mgm_dir(home) / "logs" / session.meta.id,
        mode=mode,
    )

    app = App(
        console=console,
        config=config,
        workspace=workspace,
        home=home,
        broker=broker,
        permissions=permissions,
        store=store,
        session=session,
        loop=loop,
        budget=ContextBudget(),
        skills=skills,
        supervisor=supervisor,
    )
    app_ref["app"] = app
    app.supervisor.on_progress = app.on_progress
    loop.on_event = app.on_event
    app.refrescar_prompt_sistema()
    return app
