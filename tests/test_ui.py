import io

from prompt_toolkit.document import Document
from rich.console import Console

from mgm.agent.loop import ALLOW_ONCE, ALLOW_PROJECT, ALLOW_SESSION, DENY
from mgm.tools import ToolCall
from mgm.ui import MgmCompleter, make_console
from mgm.ui.console import TEMA, acortar, diff_de_llamada, panel_resultado, render_diff
from mgm.ui.prompt import OPCIONES


def texto_de(renderable) -> str:
    buffer = io.StringIO()
    Console(file=buffer, force_terminal=False, width=120, theme=TEMA).print(renderable)
    return buffer.getvalue()


class TestTema:
    def test_los_estilos_propios_no_revientan(self):
        """El bug de la versión vieja: rich moría con MissingStyle."""
        buffer = io.StringIO()
        console = make_console(file=buffer, force_terminal=False)
        for estilo in ("user", "error", "warning", "ok", "tool", "apagado", "marca",
                       "riesgo.read", "riesgo.write", "riesgo.exec"):
            console.print(f"[{estilo}]texto[/{estilo}]")
        assert buffer.getvalue().count("texto") == 10


class TestDiff:
    def test_muestra_lo_que_cambia(self):
        salida = texto_de(render_diff("uno\ndos", "uno\nDOS", "a.txt"))
        assert "-dos" in salida and "+DOS" in salida and "a.txt" in salida

    def test_sin_cambios_no_produce_nada(self):
        assert texto_de(render_diff("igual", "igual", "a.txt")).strip() == ""

    def test_diff_gigante_se_trunca(self):
        viejo = "\n".join(str(i) for i in range(500))
        nuevo = "\n".join(str(i * 2) for i in range(500))
        assert "líneas de diff más" in texto_de(render_diff(viejo, nuevo, "g.txt"))


class TestDiffDeLlamada:
    def test_write_file_sobre_archivo_existente(self, tmp_path):
        (tmp_path / "a.txt").write_text("viejo", encoding="utf-8")
        call = ToolCall("write_file", {"path": "a.txt", "content": "nuevo"})
        assert "+nuevo" in texto_de(diff_de_llamada(call, tmp_path))

    def test_write_file_de_archivo_nuevo(self, tmp_path):
        call = ToolCall("write_file", {"path": "nuevo.txt", "content": "contenido"})
        assert "+contenido" in texto_de(diff_de_llamada(call, tmp_path))

    def test_edit_muestra_el_reemplazo(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
        bloque = "<<<<<<< OLD\nx = 1\n=======\nx = 99\n>>>>>>> NEW"
        call = ToolCall("edit", {"path": "a.py", "block": bloque})
        salida = texto_de(diff_de_llamada(call, tmp_path))
        assert "-x = 1" in salida and "+x = 99" in salida

    def test_edit_con_bloque_invalido_no_revienta(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
        call = ToolCall("edit", {"path": "a.py", "block": "esto no es un bloque"})
        assert diff_de_llamada(call, tmp_path) is None

    def test_bash_no_tiene_diff(self, tmp_path):
        assert diff_de_llamada(ToolCall("bash", {"command": "ls"}), tmp_path) is None

    def test_escritura_identica_no_muestra_diff(self, tmp_path):
        (tmp_path / "a.txt").write_text("igual", encoding="utf-8")
        call = ToolCall("write_file", {"path": "a.txt", "content": "igual"})
        assert diff_de_llamada(call, tmp_path) is None


class TestPanelResultado:
    def test_exito_y_fallo_se_distinguen(self):
        assert "✓" in texto_de(panel_resultado("bash", True, "salida"))
        assert "✗" in texto_de(panel_resultado("bash", False, "error"))

    def test_salida_larga_se_acorta(self):
        assert "caracteres más" in acortar("x" * 5000)

    def test_salida_corta_intacta(self):
        assert acortar("corta") == "corta"


class TestRespuestasDePermiso:
    def test_las_teclas_mapean_a_lo_esperado(self):
        assert OPCIONES["s"] == ALLOW_ONCE and OPCIONES[""] == ALLOW_ONCE
        assert OPCIONES["a"] == ALLOW_SESSION
        assert OPCIONES["p"] == ALLOW_PROJECT
        assert OPCIONES["n"] == DENY and OPCIONES["no"] == DENY

    def test_lo_no_reconocido_se_trata_como_negativa(self):
        assert OPCIONES.get("cualquier cosa", DENY) == DENY


class TestAutocompletado:
    def _completar(self, completer, texto):
        doc = Document(texto, len(texto))
        return [c.text for c in completer.get_completions(doc, None)]

    def test_completa_comandos(self, tmp_path):
        c = MgmCompleter({"/modo": "cambiar modo", "/memoria": "ver memoria", "/salir": "irse"}, tmp_path)
        assert sorted(self._completar(c, "/m")) == ["/memoria", "/modo"]

    def test_completa_archivos_con_arroba(self, tmp_path):
        (tmp_path / "codigo.py").write_text("x", encoding="utf-8")
        (tmp_path / "notas.md").write_text("y", encoding="utf-8")
        c = MgmCompleter({}, tmp_path)
        assert self._completar(c, "revisa @cod") == ["@codigo.py"]

    def test_ignora_carpetas_de_ruido(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
        (tmp_path / "real.txt").write_text("y", encoding="utf-8")
        c = MgmCompleter({}, tmp_path)
        assert self._completar(c, "@") == ["@real.txt"]

    def test_texto_normal_no_completa(self, tmp_path):
        c = MgmCompleter({"/modo": "x"}, tmp_path)
        assert self._completar(c, "hola mundo") == []
