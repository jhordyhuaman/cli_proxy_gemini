"""bash: ejecuta un comando en el workspace con captura y timeout.

Con background="true" no se espera a que termine: sirve para servidores o
watchers que deben seguir corriendo. Su salida se redirige a un log en vez de
capturarse, porque el proceso sigue vivo después de que la tool retorna.
"""

from __future__ import annotations

import asyncio
import uuid

from .base import Tool, ToolContext, ToolResult

DEFAULT_TIMEOUT = 120.0
MAX_OUTPUT_CHARS = 30_000


class BashTool(Tool):
    name = "bash"
    description = (
        "Ejecuta un comando de terminal en el workspace y devuelve su salida. "
        "Con background=\"true\" lo deja corriendo en segundo plano (para "
        "servidores o watchers) y devuelve el control de inmediato."
    )
    body_param = "command"
    parameters_schema = {
        "command": "(CUERPO del tag) comando a ejecutar",
        "timeout": f"segundos máximos (opcional, defecto {int(DEFAULT_TIMEOUT)})",
        "background": "\"true\" para no esperar a que termine (servidores, watchers)",
    }
    required_params = ("command",)
    risk = "exec"

    def _es_en_segundo_plano(self, args: dict[str, str]) -> bool:
        return (args.get("background") or "").strip().lower() == "true"

    def subject(self, args: dict[str, str]) -> str:
        return args.get("command", "")

    def summary(self, args: dict[str, str]) -> str:
        comando = args.get("command", "")
        if self._es_en_segundo_plano(args):
            return f"ejecutar en segundo plano: {comando}"
        return f"ejecutar: {comando}"

    async def execute(self, args: dict[str, str], context: ToolContext) -> ToolResult:
        command = args["command"]
        if self._es_en_segundo_plano(args):
            return await self._ejecutar_en_segundo_plano(command, context)

        try:
            timeout = float(args.get("timeout") or DEFAULT_TIMEOUT)
        except ValueError:
            return ToolResult(False, "[ERROR] timeout debe ser un número de segundos")

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(context.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult(
                False, f"[ERROR] el comando superó el timeout de {timeout:g}s: {command!r}"
            )

        text = out.decode("utf-8", errors="replace")
        if len(text) > MAX_OUTPUT_CHARS:
            text = text[:MAX_OUTPUT_CHARS] + "\n[... salida truncada ...]"
        if not text.strip():
            text = "[comando ejecutado sin salida]"
        ok = proc.returncode == 0
        status = "[ÉXITO]" if ok else f"[ERROR] código de salida {proc.returncode}"
        return ToolResult(ok, f"{status}\n{text}")

    async def _ejecutar_en_segundo_plano(self, command: str, context: ToolContext) -> ToolResult:
        carpeta = context.workspace / ".mgm" / "bg"
        carpeta.mkdir(parents=True, exist_ok=True)
        log_path = carpeta / f"{uuid.uuid4().hex[:8]}.log"
        log_file = open(log_path, "wb")
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(context.workspace),
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
            )
        finally:
            # El hijo ya heredó el descriptor; el padre no necesita mantenerlo abierto.
            log_file.close()
        return ToolResult(
            True,
            f"[EN SEGUNDO PLANO] pid={proc.pid}\n"
            f"salida: {log_path}\n"
            f"Para revisarla: bash \"cat {log_path}\" · Para detenerlo: bash \"kill {proc.pid}\"",
        )
