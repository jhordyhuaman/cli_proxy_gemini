"""edit: reemplazo exacto de texto con bloque OLD/NEW en el cuerpo del tag."""

from __future__ import annotations

from .base import Tool, ToolContext, ToolResult, resolve_write_path

OLD_MARK = "<<<<<<< OLD"
SEP_MARK = "======="
NEW_MARK = ">>>>>>> NEW"


def parse_edit_block(body: str) -> tuple[str, str]:
    lines = body.split("\n")
    try:
        i_old = lines.index(OLD_MARK)
        i_new = lines.index(NEW_MARK)
    except ValueError:
        raise ValueError(
            f"bloque edit inválido: faltan las marcas {OLD_MARK!r} y/o {NEW_MARK!r}"
        ) from None
    for i in range(i_old + 1, i_new):
        if lines[i].startswith(SEP_MARK):
            return "\n".join(lines[i_old + 1 : i]), "\n".join(lines[i + 1 : i_new])
    raise ValueError(f"bloque edit inválido: falta el separador {SEP_MARK!r}")


class EditTool(Tool):
    name = "edit"
    description = "Reemplaza texto exacto de un archivo (coincidencia única salvo replace_all)"
    body_param = "block"
    parameters_schema = {
        "path": "ruta del archivo, siempre dentro del workspace",
        "replace_all": "'true' para reemplazar todas las coincidencias (opcional)",
        "block": f"(CUERPO del tag) bloque {OLD_MARK} texto viejo {SEP_MARK} texto nuevo {NEW_MARK}",
    }
    required_params = ("path", "block")
    risk = "write"

    async def execute(self, args: dict[str, str], context: ToolContext) -> ToolResult:
        path = resolve_write_path(context.workspace, args["path"])
        if not path.is_file():
            return ToolResult(False, f"[ERROR] no existe el archivo: {args['path']}")
        try:
            old, new = parse_edit_block(args["block"])
        except ValueError as exc:
            return ToolResult(False, f"[ERROR] {exc}")
        if not old:
            return ToolResult(False, "[ERROR] el bloque OLD está vacío")

        content = path.read_text(encoding="utf-8")
        occurrences = content.count(old)
        replace_all = (args.get("replace_all") or "").lower() == "true"
        if occurrences == 0:
            return ToolResult(
                False, "[ERROR] old_string no aparece en el archivo; revisa el texto exacto"
            )
        if occurrences > 1 and not replace_all:
            return ToolResult(
                False,
                f"[ERROR] old_string aparece {occurrences} veces; hazlo más específico "
                "o usa replace_all=\"true\"",
            )
        updated = content.replace(old, new) if replace_all else content.replace(old, new, 1)
        path.write_text(updated, encoding="utf-8")
        n = occurrences if replace_all else 1
        return ToolResult(True, f"[ÉXITO] {path} editado ({n} reemplazo(s)).")
