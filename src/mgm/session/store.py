"""Persistencia de sesiones en JSONL: una sesión por archivo.

Formato: la primera línea es la metadata, cada línea siguiente un mensaje.
Append-only, así que sobrevive a que cierres la terminal de golpe.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..transport import Message


@dataclass
class SessionMeta:
    id: str
    created_at: float
    updated_at: float
    workspace: str
    title: str = ""
    turns: int = 0

    @property
    def created_label(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.created_at))

    @property
    def updated_label(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.updated_at))


@dataclass
class Session:
    meta: SessionMeta
    messages: list[Message] = field(default_factory=list)


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


class SessionStore:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.jsonl"

    # ------------------------------------------------------------- escritura

    def create(self, workspace: Path | str, *, session_id: str | None = None) -> Session:
        now = time.time()
        meta = SessionMeta(
            id=session_id or new_session_id(),
            created_at=now,
            updated_at=now,
            workspace=str(workspace),
        )
        self.root.mkdir(parents=True, exist_ok=True)
        with self._path(meta.id).open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "meta", **asdict(meta)}, ensure_ascii=False) + "\n")
        return Session(meta=meta)

    def append(self, session: Session, message: Message) -> None:
        session.messages.append(message)
        session.meta.updated_at = time.time()
        titulo_nuevo = False
        if message.role == "user" and not session.meta.title and message.content.strip():
            session.meta.title = message.content.strip().splitlines()[0][:70]
            titulo_nuevo = True
        self.root.mkdir(parents=True, exist_ok=True)
        with self._path(session.meta.id).open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {"type": "msg", "role": message.role, "content": message.content},
                    ensure_ascii=False,
                )
                + "\n"
            )
        if titulo_nuevo:
            # El título vive en la metadata: hay que reescribir la cabecera.
            self._rewrite_meta(session)

    def bump_turn(self, session: Session) -> None:
        session.meta.turns += 1
        self._rewrite_meta(session)

    def _rewrite_meta(self, session: Session) -> None:
        """Reescribe la primera línea (metadata) conservando los mensajes."""
        path = self._path(session.meta.id)
        if not path.is_file():
            return
        lineas = path.read_text(encoding="utf-8").splitlines()
        cabecera = json.dumps({"type": "meta", **asdict(session.meta)}, ensure_ascii=False)
        cuerpo = [ln for ln in lineas[1:] if ln.strip()]
        path.write_text("\n".join([cabecera, *cuerpo]) + "\n", encoding="utf-8")

    def replace_messages(self, session: Session, messages: list[Message]) -> None:
        """Reescribe el archivo entero (lo usa la compactación)."""
        session.messages = list(messages)
        session.meta.updated_at = time.time()
        self.root.mkdir(parents=True, exist_ok=True)
        lineas = [json.dumps({"type": "meta", **asdict(session.meta)}, ensure_ascii=False)]
        lineas += [
            json.dumps({"type": "msg", "role": m.role, "content": m.content}, ensure_ascii=False)
            for m in messages
        ]
        self._path(session.meta.id).write_text("\n".join(lineas) + "\n", encoding="utf-8")

    # ------------------------------------------------------------- lectura

    def load(self, session_id: str) -> Session | None:
        path = self._path(session_id)
        if not path.is_file():
            return None
        meta: SessionMeta | None = None
        mensajes: list[Message] = []
        for linea in path.read_text(encoding="utf-8").splitlines():
            if not linea.strip():
                continue
            try:
                dato = json.loads(linea)
            except json.JSONDecodeError:
                continue
            if dato.get("type") == "meta":
                campos = {k: v for k, v in dato.items() if k != "type"}
                try:
                    meta = SessionMeta(**campos)
                except TypeError:
                    return None
            elif dato.get("type") == "msg":
                mensajes.append(Message(role=dato.get("role", "user"), content=dato.get("content", "")))
        if meta is None:
            return None
        return Session(meta=meta, messages=mensajes)

    def list(self, *, workspace: Path | str | None = None, limit: int = 20) -> list[SessionMeta]:
        if not self.root.is_dir():
            return []
        metas: list[SessionMeta] = []
        for path in self.root.glob("*.jsonl"):
            sesion = self.load(path.stem)
            if sesion is None:
                continue
            if workspace is not None and sesion.meta.workspace != str(workspace):
                continue
            metas.append(sesion.meta)
        metas.sort(key=lambda m: m.updated_at, reverse=True)
        return metas[:limit]

    def latest(self, *, workspace: Path | str | None = None) -> Session | None:
        metas = self.list(workspace=workspace, limit=1)
        return self.load(metas[0].id) if metas else None
