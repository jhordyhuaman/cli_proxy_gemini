from mgm.transport import Chunk


def test_chunk_admite_state_opcional():
    chunk = Chunk(text="hola", state={"conversation_id": "c1"})
    assert chunk.state == {"conversation_id": "c1"}


def test_chunk_state_por_defecto_es_none():
    assert Chunk(text="hola").state is None
