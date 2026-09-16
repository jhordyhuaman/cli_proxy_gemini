"""bash: ejecuta un comando en el workspace con captura y timeout."""

from __future__ import annotations

import asyncio

from .base import Tool, ToolContext, ToolResult

DEFAULT_TIMEOUT = 120.0
MAX_OUTPUT_CHARS = 30_000


class BashTool(Tool):
    name = "bash"
    description = "Ejecuta un comando de terminal en el workspace y devuelve su salida"
    body_param = "command"
    parameters_schema = {
        "command": "(CUERPO del tag) comando a ejecutar",
        "timeout": f"segundos máximos (opcional, defecto {int(DEFAULT_TIMEOUT)})",
    }
    required_params = ("command",)
    risk = "exec"

    def subject(self, args: dict[str, str]) -> str:
        return args.get("command", "")

    def summary(self, args: dict[str, str]) -> str:
        return f"ejecutar: {args.get('command', '')}"

    async def execute(self, args: dict[str, str], context: ToolContext) -> ToolResult:
        command = args["command"]
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
