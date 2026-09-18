"""Configuración en tres capas y credenciales.

Prioridad (de menor a mayor):
1. ~/.mgm/config.toml        (global)
2. .mgm/config.toml          (proyecto, cwd)
3. Variables MGM_*           (entorno)

La cookie NUNCA vive en el código: se guarda en ~/.mgm/credentials.json
con permisos 0600 y se carga en memoria al arrancar.
"""

from __future__ import annotations

import json
import os
import stat
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Mapping

_ENV_PREFIX = "MGM_"


@dataclass
class Config:
    transport: str = "auto"
    model: str = "gemini-auto"
    #: Proveedor de g4f. "Gemini" es el que usa TU cookie (tu cuenta Pro).
    #: "auto" deja elegir a g4f, que puede caer en endpoints libres anónimos.
    provider: str = "Gemini"
    max_retries: int = 3
    base_delay: float = 0.5
    #: Reutilizar la MISMA conversación en el servidor de Gemini entre llamadas,
    #: en vez de abrir un chat nuevo en gemini.google.com por cada una.
    #: mgm sigue mandando el contexto él mismo (prompt de sistema + lo que el
    #: modelo aún no vio), así que no pierde el contrato de herramientas.
    conversacion_continua: bool = True


_FIELD_CASTS = {f.name: f.type for f in fields(Config)}


def mgm_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".mgm"


def _read_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


_VERDADEROS = ("1", "true", "si", "sí", "yes", "on")


def _cast(key: str, raw: str):
    target = _FIELD_CASTS.get(key, str)
    if target == "int":
        return int(raw)
    if target == "float":
        return float(raw)
    if target == "bool":
        return str(raw).strip().lower() in _VERDADEROS
    return raw


def load_config(
    home: Path | None = None,
    cwd: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Config:
    home = home or Path.home()
    cwd = cwd or Path.cwd()
    environ = os.environ if environ is None else environ

    data: dict = {}
    for layer in (mgm_dir(home) / "config.toml", cwd / ".mgm" / "config.toml"):
        data.update(_read_toml(layer))

    for key in _FIELD_CASTS:
        env_name = f"{_ENV_PREFIX}{key.upper()}"
        if env_name in environ:
            data[key] = _cast(key, environ[env_name])

    known = {key: value for key, value in data.items() if key in _FIELD_CASTS}
    return Config(**known)


def credentials_path(home: Path | None = None) -> Path:
    return mgm_dir(home) / "credentials.json"


def load_credentials(home: Path | None = None) -> dict:
    path = credentials_path(home)
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_cookies(home: Path | None = None) -> dict[str, str]:
    creds = load_credentials(home)
    cookies = creds.get("cookies", {})
    return {str(k): str(v) for k, v in cookies.items()}


def save_credentials(cookies: dict[str, str], home: Path | None = None) -> Path:
    directory = mgm_dir(home)
    directory.mkdir(parents=True, exist_ok=True)
    path = credentials_path(home)
    with path.open("w", encoding="utf-8") as fh:
        json.dump({"cookies": cookies}, fh, indent=2)
    if os.name != "nt":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path
