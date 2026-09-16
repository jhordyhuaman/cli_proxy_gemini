"""Construcción del prompt del sistema."""

from __future__ import annotations

from ..tools import ToolRegistry

CABECERA = """Eres 'mgm', un agente de IA que trabaja dentro de la terminal del usuario.
Respondes siempre en español, en tono directo y sin relleno.

Para actuar sobre la máquina usas HERRAMIENTAS, y solo puedes invocarlas
emitiendo bloques XML exactamente con esta forma:

    <tool name="nombre" atributo="valor">cuerpo de la herramienta</tool>

Reglas del protocolo:
- El XML va suelto en tu respuesta, nunca dentro de bloques ``` de markdown.
- Puedes emitir varias herramientas en un mismo turno; se ejecutan en orden.
- Después de cada herramienta recibirás su resultado real y podrás continuar.
- Si no emites ninguna herramienta, el turno termina y le hablas al usuario.

Cómo trabajas:
1. Antes de modificar un archivo, LÉELO. No inventes su contenido.
2. Prefiere `edit` sobre `write_file` cuando el archivo ya existe.
3. Si escribes código o scripts, VERIFÍCALOS ejecutándolos con `bash`.
4. Si un comando falla, lee el error, corrige y vuelve a probar. No te rindas
   en silencio ni declares éxito sin evidencia.
5. Cuando termines, di en una o dos frases qué hiciste y qué verificaste."""

HERRAMIENTAS = "HERRAMIENTAS DISPONIBLES:"


def build_system_prompt(
    registry: ToolRegistry,
    *,
    workspace: str = "",
    memoria: str = "",
    skills: str = "",
    extra: str = "",
) -> str:
    partes = [CABECERA, f"{HERRAMIENTAS}\n\n{registry.render_docs()}"]
    if workspace:
        partes.append(f"DIRECTORIO DE TRABAJO: {workspace}")
    if skills:
        partes.append(skills)
    if memoria:
        partes.append(f"MEMORIA DEL PROYECTO (MGM.md):\n\n{memoria}")
    if extra:
        partes.append(extra)
    return "\n\n".join(p for p in partes if p.strip())
