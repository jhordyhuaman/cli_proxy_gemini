import pytest

from mgm.permissions import PermissionEngine, Rule, RuleError, RuleSet, load_ruleset, save_ruleset
from mgm.permissions.engine import ModeError


class TestRuleParsing:
    def test_regla_sin_patron_cubre_toda_la_herramienta(self):
        r = Rule.parse("read_file")
        assert r.tool == "read_file" and r.pattern is None
        assert r.matches("read_file", "lo/que/sea.txt")
        assert not r.matches("write_file", "lo/que/sea.txt")

    def test_prefijo_con_dos_puntos_asterisco(self):
        r = Rule.parse("bash(git status:*)")
        assert r.matches("bash", "git status --short")
        assert r.matches("bash", "git status")
        assert not r.matches("bash", "git push")

    def test_exacto(self):
        r = Rule.parse("bash(npm test)")
        assert r.matches("bash", "npm test")
        assert not r.matches("bash", "npm test -- --watch")

    def test_glob(self):
        r = Rule.parse("write_file(src/*.py)")
        assert r.matches("write_file", "src/cli.py")
        assert not r.matches("write_file", "otros/cli.py")

    def test_roundtrip_str(self):
        for raw in ("read_file", "bash(git status:*)", "write_file(src/**)"):
            assert str(Rule.parse(raw)) == raw

    @pytest.mark.parametrize("raw", ["", "   ", "bash(git", "bash)"])
    def test_reglas_invalidas(self, raw):
        with pytest.raises(RuleError):
            Rule.parse(raw)


class TestRuleSet:
    def test_allow_y_deny(self):
        rs = RuleSet()
        rs.add_allow("bash(git status:*)")
        rs.add_deny("bash(git push:*)")
        assert rs.allows("bash", "git status -s")
        assert rs.denies("bash", "git push origin")
        assert not rs.allows("bash", "git push origin")

    def test_no_duplica(self):
        rs = RuleSet()
        rs.add_allow("read_file")
        rs.add_allow("read_file")
        assert len(rs.allow) == 1

    def test_persistencia_roundtrip(self, tmp_path):
        rs = RuleSet()
        rs.add_allow("bash(ls:*)")
        rs.add_deny("bash(rm:*)")
        path = save_ruleset(tmp_path / ".mgm" / "permissions.json", rs)
        cargado = load_ruleset(path)
        assert [str(r) for r in cargado.allow] == ["bash(ls:*)"]
        assert [str(r) for r in cargado.deny] == ["bash(rm:*)"]

    def test_archivo_corrupto_no_revienta(self, tmp_path):
        path = tmp_path / "permissions.json"
        path.write_text("{no es json", encoding="utf-8")
        assert load_ruleset(path).allow == []

    def test_ruleset_inexistente_es_vacio(self, tmp_path):
        assert load_ruleset(tmp_path / "nada.json").allow == []


class TestEngineModes:
    def test_modo_ask_permite_leer_y_pregunta_lo_demas(self):
        e = PermissionEngine("ask")
        assert e.evaluate("read_file", "read", "x.py").outcome == "allow"
        assert e.evaluate("write_file", "write", "x.py").outcome == "ask"
        assert e.evaluate("bash", "exec", "ls").outcome == "ask"

    def test_modo_plan_niega_escritura_y_ejecucion(self):
        e = PermissionEngine("plan")
        assert e.evaluate("read_file", "read", "x.py").outcome == "allow"
        assert e.evaluate("write_file", "write", "x.py").outcome == "deny"
        assert e.evaluate("bash", "exec", "ls").outcome == "deny"

    def test_modo_auto_edits_escribe_pero_pregunta_para_ejecutar(self):
        e = PermissionEngine("auto-edits")
        assert e.evaluate("write_file", "write", "x.py").outcome == "allow"
        assert e.evaluate("bash", "exec", "ls").outcome == "ask"

    def test_modo_libre_permite_todo(self):
        e = PermissionEngine("libre")
        assert e.evaluate("bash", "exec", "rm -rf /").outcome == "allow"

    def test_modo_invalido(self):
        with pytest.raises(ModeError):
            PermissionEngine("turbo")


class TestEnginePrecedence:
    def test_deny_gana_sobre_allow(self):
        e = PermissionEngine("libre")
        e.remember("bash(git push:*)", scope="session")
        e.deny_rule("bash(git push:*)", scope="session")
        d = e.evaluate("bash", "exec", "git push origin main")
        assert d.outcome == "deny"

    def test_deny_gana_incluso_en_modo_libre(self):
        e = PermissionEngine("libre")
        e.deny_rule("bash(rm:*)", scope="session")
        assert e.evaluate("bash", "exec", "rm -rf build").outcome == "deny"

    def test_plan_gana_sobre_regla_de_permiso(self):
        e = PermissionEngine("plan")
        e.remember("write_file", scope="session")
        assert e.evaluate("write_file", "write", "x.py").outcome == "deny"

    def test_allow_gana_sobre_defecto_del_modo(self):
        e = PermissionEngine("ask")
        e.remember("bash(git status:*)", scope="session")
        assert e.evaluate("bash", "exec", "git status -s").outcome == "allow"
        assert e.evaluate("bash", "exec", "git push").outcome == "ask"


class TestEnginePersistence:
    def test_recordar_en_proyecto_escribe_archivo(self, tmp_path):
        ppath = tmp_path / ".mgm" / "permissions.json"
        e = PermissionEngine("ask", project_path=ppath)
        e.remember("bash(pytest:*)", scope="project")
        assert [str(r) for r in load_ruleset(ppath).allow] == ["bash(pytest:*)"]

    def test_recordar_en_usuario_escribe_archivo(self, tmp_path):
        upath = tmp_path / "user.json"
        e = PermissionEngine("ask", user_path=upath)
        e.remember("read_file", scope="user")
        assert [str(r) for r in load_ruleset(upath).allow] == ["read_file"]

    def test_sesion_no_persiste(self, tmp_path):
        upath = tmp_path / "user.json"
        e = PermissionEngine("ask", user_path=upath)
        e.remember("bash(ls:*)", scope="session")
        assert not upath.exists()

    def test_alcance_desconocido(self):
        with pytest.raises(ValueError):
            PermissionEngine("ask").remember("read_file", scope="galaxia")
