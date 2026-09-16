import pytest

from mgm.tools import ToolCall, ToolContext, ToolRegistry, default_registry
from mgm.tools.base import Tool, ToolResult


class ToolExplosiva(Tool):
    name = "boom"
    description = "siempre falla"
    required_params = ()

    async def execute(self, args, context):
        raise RuntimeError("kaboom")


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(workspace=tmp_path)


class TestRegistro:
    def test_registro_por_defecto_trae_las_seis(self):
        r = default_registry()
        assert r.names == ["bash", "edit", "glob", "grep", "read_file", "write_file"]
        assert len(r) == 6

    def test_riesgos_declarados(self):
        r = default_registry()
        assert r.get("read_file").risk == "read"
        assert r.get("write_file").risk == "write"
        assert r.get("bash").risk == "exec"

    def test_solo_lectura_es_delegable(self):
        r = default_registry()
        assert r.get("read_file").delegable and r.get("grep").delegable
        assert not r.get("write_file").delegable and not r.get("bash").delegable

    def test_tool_sin_nombre_se_rechaza(self):
        with pytest.raises(ValueError):
            ToolRegistry().register(Tool())

    def test_docs_mencionan_cada_tool(self):
        docs = default_registry().render_docs()
        for nombre in ("bash", "edit", "glob", "grep", "read_file", "write_file"):
            assert f'name="{nombre}"' in docs
        assert "obligatorio" in docs and "opcional" in docs


class TestFusionDeArgumentos:
    def test_cuerpo_va_al_body_param(self):
        r = default_registry()
        call = r.call_from_event("write_file", {"path": "a.txt"}, "hola")
        assert call.args == {"path": "a.txt", "content": "hola"}

    def test_cuerpo_de_bash_es_el_comando(self):
        r = default_registry()
        call = r.call_from_event("bash", {}, "ls -la")
        assert call.args == {"command": "ls -la"}

    def test_tool_desconocida_guarda_cuerpo_como_body(self):
        call = ToolRegistry().call_from_event("fantasma", {"x": "1"}, "cuerpo")
        assert call.args == {"x": "1", "body": "cuerpo"}

    def test_atributo_gana_si_el_cuerpo_viene_vacio(self):
        r = default_registry()
        call = r.call_from_event("bash", {"command": "pwd"}, "")
        assert call.args["command"] == "pwd"


class TestEjecucion:
    async def test_ejecuta_y_devuelve_resultado(self, ctx):
        r = default_registry()
        (ctx.workspace / "f.txt").write_text("contenido", encoding="utf-8")
        res = await r.execute(ToolCall("read_file", {"path": "f.txt"}), ctx)
        assert res.ok and "contenido" in res.output

    async def test_tool_desconocida_da_error_util(self, ctx):
        res = await default_registry().execute(ToolCall("volar", {}), ctx)
        assert not res.ok and "no existe la herramienta" in res.output
        assert "read_file" in res.output

    async def test_falta_parametro_obligatorio(self, ctx):
        res = await default_registry().execute(ToolCall("read_file", {}), ctx)
        assert not res.ok and "obligatorio" in res.output

    async def test_escritura_fuera_del_workspace_se_rechaza(self, ctx):
        res = await default_registry().execute(
            ToolCall("write_file", {"path": "../fuera.txt", "content": "x"}), ctx
        )
        assert not res.ok and "fuera del workspace" in res.output

    async def test_tool_que_revienta_no_tumba_el_agente(self, ctx):
        r = ToolRegistry([ToolExplosiva()])
        res = await r.execute(ToolCall("boom", {}), ctx)
        assert not res.ok and "kaboom" in res.output and "RuntimeError" in res.output
