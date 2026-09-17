"""Autoactualización desde GitHub.

No asume que hay `git` en la máquina destino: el caso real que motiva esto es
la laptop Windows sin permisos de administrador, donde mgm normalmente se
copia como carpeta suelta, no se clona. Por eso hay dos caminos:

- Si la instalación ES un checkout de git (como este mismo repo en desarrollo):
  `git pull --ff-only`, que es el camino más seguro y rápido.
- Si NO lo es: se baja el .zip de la rama principal por HTTPS (sin git) y se
  reemplazan solo las rutas del propio proyecto — nunca `.venv/` ni `.mgm/`,
  que son datos de la máquina del usuario.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO = "jhordyhuaman/cli_proxy_gemini"
RAMA = "main"
URL_ZIP = f"https://github.com/{REPO}/archive/refs/heads/{RAMA}.zip"
TIMEOUT_DESCARGA = 30

#: Lo único que una actualización por zip toca. Todo lo demás en la carpeta
#: del proyecto (.venv, .mgm, cualquier cosa del usuario) se deja intacto.
RUTAS_ACTUALIZABLES = (
    "src",
    "installer",
    "pyproject.toml",
    "README.md",
    "CLAUDE.md",
    "mgm.bat",
    "instalar.bat",
)


def raiz_del_proyecto(desde: Path | None = None) -> Path | None:
    """Sube desde `desde` buscando la carpeta con pyproject.toml."""
    actual = (desde or Path(__file__)).resolve()
    for candidato in (actual, *actual.parents):
        if (candidato / "pyproject.toml").is_file():
            return candidato
    return None


def es_checkout_git(raiz: Path) -> bool:
    return (raiz / ".git").is_dir()


def _git_rev_parse_head(raiz: Path) -> str:
    resultado = subprocess.run(
        ["git", "-C", str(raiz), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True,
    )
    return resultado.stdout.strip()


def actualizar_por_git(raiz: Path) -> tuple[bool, str]:
    antes = _git_rev_parse_head(raiz)
    resultado = subprocess.run(
        ["git", "-C", str(raiz), "pull", "--ff-only"],
        capture_output=True, text=True,
    )
    if resultado.returncode != 0:
        return False, f"git pull falló:\n{resultado.stderr.strip() or resultado.stdout.strip()}"
    despues = _git_rev_parse_head(raiz)
    if antes == despues:
        return True, f"ya estabas al día ({antes})"
    return True, f"actualizado: {antes} → {despues}"


def descargar_zip(destino: Path, *, url: str = URL_ZIP) -> None:
    with urllib.request.urlopen(url, timeout=TIMEOUT_DESCARGA) as resp:
        destino.write_bytes(resp.read())


def actualizar_por_zip(raiz: Path, *, descargar=descargar_zip) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "mgm.zip"
        try:
            descargar(zip_path)
        except OSError as exc:
            return False, f"no se pudo descargar la actualización: {exc}"

        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_path)

        extraidos = [p for p in tmp_path.iterdir() if p.is_dir()]
        if not extraidos:
            return False, "el zip descargado no tenía la carpeta esperada"
        origen = extraidos[0]  # GitHub nombra la carpeta "<repo>-<rama>"

        copiadas = []
        for nombre in RUTAS_ACTUALIZABLES:
            src = origen / nombre
            if not src.exists():
                continue
            dst = raiz / nombre
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            copiadas.append(nombre)

    if not copiadas:
        return False, "el zip no traía ninguna de las rutas esperadas del proyecto"
    return True, f"actualizado desde GitHub ({', '.join(copiadas)})"


def actualizar(raiz: Path | None = None) -> tuple[bool, str]:
    encontrada = raiz_del_proyecto(raiz)
    if encontrada is None:
        return False, "no encontré la carpeta del proyecto (falta pyproject.toml)"
    if es_checkout_git(encontrada):
        return actualizar_por_git(encontrada)
    return actualizar_por_zip(encontrada)
