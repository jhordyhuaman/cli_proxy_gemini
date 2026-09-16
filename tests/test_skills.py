import pytest

from mgm.skills import SkillLibrary, load_library, parse_frontmatter
from mgm.skills.loader import Skill
from mgm.tools import ToolCall, ToolContext, default_registry


def escribir_skill(carpeta, nombre, descripcion, cuerpo="haz esto y lo otro"):
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{nombre}.md").write_text(
        f"---\nname: {nombre}\ndescription: {descripcion}\n---\n\n{cuerpo}\n", encoding="utf-8"
    )


class TestFrontmatter:
    def test_parsea_cabecera(self):
        meta, cuerpo = parse_frontmatter("---\nname: x\ndescription: hace y\n---\n\ncuerpo aquí")
        assert meta == {"name": "x", "description": "hace y"}
        assert cuerpo == "cuerpo aquí"

    def test_sin_cabecera_todo_es_cuerpo(self):
        meta, cuerpo = parse_frontmatter("solo texto")
        assert meta == {} and cuerpo == "solo texto"

    def test_cabecera_sin_cerrar_es_cuerpo(self):
        meta, cuerpo = parse_frontmatter("---\nname: x\n\nme olvidé de cerrar")
        assert meta == {}

    def test_los_dos_puntos_del_valor_no_rompen(self):
        meta, _ = parse_frontmatter("---\ndescription: usa esto: cuando pase algo\n---\ncuerpo")
        assert meta["description"] == "usa esto: cuando pase algo"


class TestCatalogo:
    def test_las_incluidas_se_cargan(self):
        lib = load_library()
        assert "tdd" in lib and "depurar" in lib and "revisar" in lib

    def test_la_skill_tdd_manda_ejecutar_las_pruebas(self):
        cuerpo = load_library().get("tdd").body
        assert "rojo" in cuerpo.lower() and "bash" in cuerpo

    def test_el_catalogo_no_incluye_los_cuerpos(self):
        lib = load_library()
        catalogo = lib.render_catalog()
        assert "tdd" in catalogo and "refactor" not in catalogo.lower()
        assert len(catalogo) < 1000

    def test_catalogo_vacio_es_cadena_vacia(self):
        assert SkillLibrary().render_catalog() == ""

    def test_el_proyecto_pisa_a_la_del_usuario(self, tmp_path):
        home, ws = tmp_path / "home", tmp_path / "proyecto"
        escribir_skill(home / ".mgm" / "skills", "estilo", "la del usuario", "cuerpo usuario")
        escribir_skill(ws / ".mgm" / "skills", "estilo", "la del proyecto", "cuerpo proyecto")
        lib = load_library(ws, home, include_builtin=False)
        assert lib.get("estilo").body == "cuerpo proyecto"
        assert lib.get("estilo").scope == "proyecto"

    def test_carpeta_con_skill_md(self, tmp_path):
        carpeta = tmp_path / ".mgm" / "skills" / "desplegar"
        carpeta.mkdir(parents=True)
        (carpeta / "SKILL.md").write_text(
            "---\ndescription: cómo desplegar\n---\n\npasos", encoding="utf-8"
        )
        lib = load_library(tmp_path, include_builtin=False)
        assert lib.get("desplegar").description == "cómo desplegar"

    def test_carpetas_inexistentes_no_revientan(self, tmp_path):
        assert len(load_library(tmp_path / "nada", tmp_path / "tampoco", include_builtin=False)) == 0


class TestHerramientaSkill:
    @pytest.fixture
    def ctx(self, tmp_path):
        return ToolContext(workspace=tmp_path)

    async def test_carga_el_cuerpo_completo(self, ctx):
        r = default_registry(load_library())
        res = await r.execute(ToolCall("skill", {"name": "tdd"}), ctx)
        assert res.ok and "rojo" in res.output.lower() and "[SKILL tdd]" in res.output

    async def test_skill_inexistente_lista_las_disponibles(self, ctx):
        r = default_registry(load_library())
        res = await r.execute(ToolCall("skill", {"name": "volar"}), ctx)
        assert not res.ok and "tdd" in res.output

    async def test_sin_biblioteca_no_hay_herramienta_skill(self):
        assert "skill" not in default_registry()

    async def test_la_skill_es_delegable_y_de_solo_lectura(self):
        tool = default_registry(load_library()).get("skill")
        assert tool.risk == "read" and tool.delegable
