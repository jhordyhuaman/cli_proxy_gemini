"""Autoactualización desde GitHub, sin depender de que haya git en la máquina
destino — el caso real es la laptop Windows sin permisos de administrador,
donde mgm se copia como carpeta y no siempre es un checkout de git.
"""
import zipfile
from pathlib import Path

import pytest

from mgm.actualizar import (
    actualizar,
    actualizar_por_git,
    actualizar_por_zip,
    es_checkout_git,
    raiz_del_proyecto,
)


@pytest.fixture
def proyecto(tmp_path):
    raiz = tmp_path / "mgm"
    raiz.mkdir()
    (raiz / "pyproject.toml").write_text("[project]\nname = \"mgm\"\n", encoding="utf-8")
    return raiz


class TestRaizDelProyecto:
    def test_encuentra_la_carpeta_con_pyproject(self, proyecto):
        sub = proyecto / "src" / "mgm"
        sub.mkdir(parents=True)
        archivo = sub / "cli.py"
        archivo.write_text("", encoding="utf-8")
        assert raiz_del_proyecto(archivo) == proyecto

    def test_none_si_no_hay_pyproject_en_ningun_ancestro(self, tmp_path):
        suelto = tmp_path / "fuera" / "de" / "todo.py"
        suelto.parent.mkdir(parents=True)
        suelto.write_text("", encoding="utf-8")
        assert raiz_del_proyecto(suelto) is None


class TestEsCheckoutGit:
    def test_true_si_hay_carpeta_git(self, proyecto):
        (proyecto / ".git").mkdir()
        assert es_checkout_git(proyecto)

    def test_false_si_no_la_hay(self, proyecto):
        assert not es_checkout_git(proyecto)


class TestActualizarPorGit:
    def test_reporta_el_cambio_de_commit(self, proyecto, monkeypatch):
        llamadas = []

        def fake_run(cmd, **kwargs):
            llamadas.append(cmd)
            from types import SimpleNamespace

            if cmd[-1] == "HEAD":
                sha = "aaa111" if len(llamadas) == 1 else "bbb222"
                return SimpleNamespace(returncode=0, stdout=sha, stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("mgm.actualizar.subprocess.run", fake_run)
        ok, detalle = actualizar_por_git(proyecto)
        assert ok
        assert "aaa111" in detalle and "bbb222" in detalle

    def test_ya_al_dia_no_lo_reporta_como_error(self, proyecto, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr(
            "mgm.actualizar.subprocess.run",
            lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="ccc333", stderr=""),
        )
        ok, detalle = actualizar_por_git(proyecto)
        assert ok and "al día" in detalle

    def test_pull_fallido_se_reporta_como_error(self, proyecto, monkeypatch):
        from types import SimpleNamespace

        def fake_run(cmd, **kwargs):
            if "pull" in cmd:
                return SimpleNamespace(returncode=1, stdout="", stderr="conflicto local")
            return SimpleNamespace(returncode=0, stdout="ccc333", stderr="")

        monkeypatch.setattr("mgm.actualizar.subprocess.run", fake_run)
        ok, detalle = actualizar_por_git(proyecto)
        assert not ok and "conflicto local" in detalle


class TestActualizarPorZip:
    def _zip_de_prueba(self, tmp_path) -> Path:
        zip_path = tmp_path / "descarga.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("cli_proxy_gemini-main/pyproject.toml", "[project]\nname = \"mgm\"\nversion=\"9.9.9\"\n")
            zf.writestr("cli_proxy_gemini-main/src/mgm/__init__.py", "__version__ = '9.9.9'\n")
            zf.writestr("cli_proxy_gemini-main/README.md", "nuevo readme\n")
        return zip_path

    def test_reemplaza_solo_las_rutas_conocidas(self, proyecto, tmp_path):
        (proyecto / "src" / "mgm").mkdir(parents=True)
        (proyecto / "src" / "mgm" / "__init__.py").write_text("__version__ = '0.1.0'\n", encoding="utf-8")
        # Algo del usuario que NO debe tocarse:
        (proyecto / ".venv").mkdir()
        (proyecto / ".venv" / "marca").write_text("no me borres", encoding="utf-8")
        (proyecto / ".mgm").mkdir()
        (proyecto / ".mgm" / "credentials.json").write_text("{}", encoding="utf-8")

        zip_path = self._zip_de_prueba(tmp_path)

        def descargar_falsa(destino: Path, **kwargs):
            destino.write_bytes(zip_path.read_bytes())

        ok, detalle = actualizar_por_zip(proyecto, descargar=descargar_falsa)

        assert ok
        assert (proyecto / "src" / "mgm" / "__init__.py").read_text(encoding="utf-8") == "__version__ = '9.9.9'\n"
        assert "9.9.9" in (proyecto / "pyproject.toml").read_text(encoding="utf-8")
        assert (proyecto / ".venv" / "marca").read_text(encoding="utf-8") == "no me borres"
        assert (proyecto / ".mgm" / "credentials.json").is_file()

    def test_error_de_descarga_no_rompe_nada(self, proyecto):
        def descargar_rota(destino: Path, **kwargs):
            raise OSError("sin red")

        ok, detalle = actualizar_por_zip(proyecto, descargar=descargar_rota)
        assert not ok
        assert "sin red" in detalle


class TestActualizar:
    def test_usa_git_si_es_un_checkout(self, proyecto, monkeypatch):
        (proyecto / ".git").mkdir()
        monkeypatch.setattr("mgm.actualizar.actualizar_por_git", lambda raiz: (True, "por git"))
        monkeypatch.setattr(
            "mgm.actualizar.actualizar_por_zip", lambda raiz, **kw: (True, "no debería llamarse")
        )
        ok, detalle = actualizar(proyecto)
        assert ok and detalle == "por git"

    def test_usa_zip_si_no_es_checkout_git(self, proyecto, monkeypatch):
        monkeypatch.setattr(
            "mgm.actualizar.actualizar_por_git", lambda raiz: (True, "no debería llamarse")
        )
        monkeypatch.setattr("mgm.actualizar.actualizar_por_zip", lambda raiz, **kw: (True, "por zip"))
        ok, detalle = actualizar(proyecto)
        assert ok and detalle == "por zip"

    def test_sin_proyecto_encontrado_es_un_error_claro(self, tmp_path):
        ok, detalle = actualizar(tmp_path / "no-existe")
        assert not ok and "pyproject.toml" in detalle
