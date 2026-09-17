"""bash con background="true": lanzar procesos de larga duración (servidores,
watchers) sin bloquear el turno, para que el agente pueda arrancarlos,
verificarlos (p. ej. con curl) y avisar que ya están corriendo — en vez de
decirle al usuario que los arranque él mismo.
"""
import asyncio
import re
from pathlib import Path

import pytest

from mgm.tools import ToolContext
from mgm.tools.bash import BashTool


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(workspace=tmp_path)


def _ruta_log(salida: str) -> Path:
    m = re.search(r"(\S+\.log)", salida)
    assert m, f"no se encontró la ruta del log en: {salida!r}"
    return Path(m.group(1))


class TestBashEnSegundoPlano:
    async def test_regresa_de_inmediato_sin_esperar_a_que_termine(self, ctx):
        tool = BashTool()
        inicio = asyncio.get_event_loop().time()
        resultado = await tool.execute({"command": "sleep 5", "background": "true"}, ctx)
        duracion = asyncio.get_event_loop().time() - inicio
        assert resultado.ok
        assert duracion < 1.0

    async def test_informa_pid_y_dónde_leer_la_salida(self, ctx):
        tool = BashTool()
        resultado = await tool.execute({"command": "echo hola", "background": "true"}, ctx)
        assert "pid" in resultado.output.lower()
        assert ".log" in resultado.output

    async def test_la_salida_del_proceso_queda_en_un_log_legible(self, ctx):
        tool = BashTool()
        resultado = await tool.execute(
            {"command": "echo hola-de-fondo", "background": "true"}, ctx
        )
        log = _ruta_log(resultado.output)
        for _ in range(20):
            if log.is_file() and log.read_text(encoding="utf-8").strip():
                break
            await asyncio.sleep(0.05)
        assert "hola-de-fondo" in log.read_text(encoding="utf-8")

    async def test_sin_background_se_comporta_como_siempre(self, ctx):
        tool = BashTool()
        resultado = await tool.execute({"command": "echo hola"}, ctx)
        assert resultado.ok and "hola" in resultado.output

    async def test_en_windows_sugiere_comandos_de_windows(self, ctx, monkeypatch):
        """El modelo copia literalmente lo que le sugerimos: en cmd.exe no
        existen 'cat' ni 'kill'."""
        import mgm.tools.bash as mod

        monkeypatch.setattr(mod, "_es_windows", lambda: True)
        tool = BashTool()
        salida = (await tool.execute({"command": "echo x", "background": "true"}, ctx)).output
        assert "type " in salida and "taskkill" in salida
        assert "cat " not in salida

    async def test_en_mac_linux_sugiere_comandos_posix(self, ctx, monkeypatch):
        import mgm.tools.bash as mod

        monkeypatch.setattr(mod, "_es_windows", lambda: False)
        tool = BashTool()
        salida = (await tool.execute({"command": "echo x", "background": "true"}, ctx)).output
        assert "cat " in salida and "kill " in salida
        assert "taskkill" not in salida

    def test_el_resumen_indica_que_es_en_segundo_plano(self):
        tool = BashTool()
        resumen = tool.summary({"command": "npm run dev", "background": "true"})
        assert "segundo plano" in resumen.lower()

    def test_el_resumen_normal_no_menciona_segundo_plano(self):
        tool = BashTool()
        resumen = tool.summary({"command": "npm run dev"})
        assert "segundo plano" not in resumen.lower()
