import pytest

from mgm.session import (
    ContextBudget,
    SessionStore,
    compact,
    discover,
    estimate_tokens,
    load_memory,
    messages_tokens,
)
from mgm.session.context import MARCA_RESUMEN
from mgm.transport import FakeTransport, InferenceBroker, Message, TransportError


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "sessions")


class TestAlmacen:
    def test_crear_y_cargar(self, store, tmp_path):
        s = store.create(tmp_path)
        store.append(s, Message(role="user", content="hola"))
        store.append(s, Message(role="assistant", content="qué tal"))
        recargada = store.load(s.meta.id)
        assert [m.content for m in recargada.messages] == ["hola", "qué tal"]
        assert recargada.meta.workspace == str(tmp_path)

    def test_el_titulo_sale_del_primer_mensaje(self, store, tmp_path):
        s = store.create(tmp_path)
        store.append(s, Message(role="user", content="arregla el login\ny lo demás"))
        assert store.load(s.meta.id).meta.title == "arregla el login"

    def test_conversation_state_por_defecto_es_none(self, store, tmp_path):
        s = store.create(tmp_path)
        assert s.meta.conversation_state is None
        assert store.load(s.meta.id).meta.conversation_state is None

    def test_conversation_state_sobrevive_a_guardar_y_cargar(self, store, tmp_path):
        s = store.create(tmp_path)
        s.meta.conversation_state = {"conversation_id": "c1", "turn_index": 2}
        store.bump_turn(s)
        recargada = store.load(s.meta.id)
        assert recargada.meta.conversation_state == {"conversation_id": "c1", "turn_index": 2}

    def test_sesion_inexistente_devuelve_none(self, store):
        assert store.load("nohay") is None

    def test_listar_ordena_por_reciente(self, store, tmp_path):
        a = store.create(tmp_path)
        b = store.create(tmp_path)
        store.append(a, Message(role="user", content="vieja"))
        store.append(b, Message(role="user", content="nueva"))
        ids = [m.id for m in store.list()]
        assert ids[0] == b.meta.id and set(ids) == {a.meta.id, b.meta.id}

    def test_listar_filtra_por_workspace(self, store, tmp_path):
        propia = store.create(tmp_path / "proyecto")
        store.create(tmp_path / "otro")
        metas = store.list(workspace=tmp_path / "proyecto")
        assert [m.id for m in metas] == [propia.meta.id]

    def test_latest_devuelve_la_ultima(self, store, tmp_path):
        store.create(tmp_path)
        b = store.create(tmp_path)
        store.append(b, Message(role="user", content="x"))
        assert store.latest(workspace=tmp_path).meta.id == b.meta.id

    def test_latest_sin_sesiones(self, store, tmp_path):
        assert store.latest(workspace=tmp_path) is None

    def test_lineas_corruptas_se_ignoran(self, store, tmp_path):
        s = store.create(tmp_path)
        store.append(s, Message(role="user", content="buena"))
        path = store._path(s.meta.id)
        path.write_text(path.read_text() + "{basura no json\n", encoding="utf-8")
        assert [m.content for m in store.load(s.meta.id).messages] == ["buena"]

    def test_reemplazar_mensajes_reescribe_el_archivo(self, store, tmp_path):
        s = store.create(tmp_path)
        for i in range(5):
            store.append(s, Message(role="user", content=f"m{i}"))
        store.replace_messages(s, [Message(role="user", content="resumen")])
        recargada = store.load(s.meta.id)
        assert [m.content for m in recargada.messages] == ["resumen"]

    def test_contador_de_turnos_persiste(self, store, tmp_path):
        s = store.create(tmp_path)
        store.append(s, Message(role="user", content="hola"))
        store.bump_turn(s)
        store.bump_turn(s)
        recargada = store.load(s.meta.id)
        assert recargada.meta.turns == 2
        assert [m.content for m in recargada.messages] == ["hola"]


class TestPresupuesto:
    def test_estimacion_de_tokens(self):
        assert estimate_tokens("a" * 400) == 100

    def test_suma_de_mensajes(self):
        msgs = [Message(role="user", content="a" * 400)] * 3
        assert messages_tokens(msgs) == 300

    def test_dispara_compactacion_al_pasar_el_umbral(self):
        b = ContextBudget(limit=1000, threshold=0.8)
        pequeno = [Message(role="user", content="a" * 400)]
        grande = [Message(role="user", content="a" * 4000)]
        assert not b.needs_compaction(pequeno)
        assert b.needs_compaction(grande)

    def test_ratio(self):
        b = ContextBudget(limit=100)
        assert b.ratio([Message(role="user", content="a" * 200)]) == 0.5


class TestCompactacion:
    async def test_conserva_cabeza_y_cola_y_resume_el_medio(self):
        msgs = [Message(role="user", content=f"mensaje {i}") for i in range(12)]
        broker = InferenceBroker(FakeTransport(script=["hicimos X y falta Y"]))
        out = await compact(msgs, broker, keep_head=2, keep_tail=3)
        assert len(out) == 6
        assert out[0].content == "mensaje 0" and out[1].content == "mensaje 1"
        assert MARCA_RESUMEN in out[2].content and "hicimos X y falta Y" in out[2].content
        assert [m.content for m in out[3:]] == ["mensaje 9", "mensaje 10", "mensaje 11"]

    async def test_conversacion_corta_no_se_toca(self):
        msgs = [Message(role="user", content="uno"), Message(role="assistant", content="dos")]
        assert await compact(msgs, None, keep_head=2, keep_tail=3) == msgs

    async def test_sin_broker_usa_resumen_mecanico(self):
        msgs = [Message(role="user", content=f"m{i}") for i in range(12)]
        out = await compact(msgs, None, keep_head=1, keep_tail=1)
        assert MARCA_RESUMEN in out[1].content and "mecánico" in out[1].content

    async def test_si_falla_el_modelo_cae_al_resumen_mecanico(self):
        msgs = [Message(role="user", content=f"m{i}") for i in range(12)]
        broker = InferenceBroker(FakeTransport(script=[TransportError("caído")]), max_retries=0)
        out = await compact(msgs, broker, keep_head=1, keep_tail=1)
        assert "mecánico" in out[1].content


class TestMemoria:
    def test_carga_mgm_del_proyecto(self, tmp_path):
        (tmp_path / "MGM.md").write_text("usa tabs, no espacios", encoding="utf-8")
        assert "usa tabs" in load_memory(tmp_path, home=tmp_path / "home")

    def test_sin_archivos_devuelve_vacio(self, tmp_path):
        assert load_memory(tmp_path, home=tmp_path / "home") == ""

    def test_precedencia_usuario_ancestro_proyecto(self, tmp_path):
        home = tmp_path / "home"
        (home / ".mgm").mkdir(parents=True)
        (home / ".mgm" / "MGM.md").write_text("regla de usuario", encoding="utf-8")
        proyecto = tmp_path / "padre" / "hijo"
        proyecto.mkdir(parents=True)
        (tmp_path / "padre" / "MGM.md").write_text("regla del padre", encoding="utf-8")
        (proyecto / "MGM.md").write_text("regla del proyecto", encoding="utf-8")
        encontrados = discover(proyecto, home)
        assert [f.scope for f in encontrados] == ["usuario", "ancestro", "proyecto"]
        texto = load_memory(proyecto, home)
        assert texto.index("regla de usuario") < texto.index("regla del padre") < texto.index("regla del proyecto")

    def test_archivo_vacio_se_ignora(self, tmp_path):
        (tmp_path / "MGM.md").write_text("   \n", encoding="utf-8")
        assert load_memory(tmp_path, home=tmp_path / "home") == ""

    def test_archivo_gigante_se_ignora(self, tmp_path):
        (tmp_path / "MGM.md").write_text("x" * 70_000, encoding="utf-8")
        assert load_memory(tmp_path, home=tmp_path / "home") == ""
