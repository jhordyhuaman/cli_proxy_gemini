import io

import pytest
from rich.console import Console

from mgm.config import save_credentials
from mgm.diagnostico import AVISO, FALLO, OK, Chequeo, diagnosticar, imprimir
from mgm.ui.console import TEMA


def consola():
    buffer = io.StringIO()
    return Console(file=buffer, force_terminal=False, width=120, theme=TEMA), buffer


def por_nombre(chequeos, trozo):
    return next(c for c in chequeos if trozo.lower() in c.nombre.lower())


class TestChequeos:
    async def test_lo_esencial_pasa_en_esta_maquina(self, tmp_path):
        chequeos = await diagnosticar(tmp_path / "home", tmp_path)
        assert por_nombre(chequeos, "Python").ok
        assert por_nombre(chequeos, "rich").ok
        assert por_nombre(chequeos, "prompt_toolkit").ok
        assert por_nombre(chequeos, "Carpeta de datos").ok
        assert por_nombre(chequeos, "Carpeta de trabajo").ok

    async def test_lanza_un_subagente_de_verdad(self, tmp_path):
        """El chequeo que importa en una máquina con restricciones."""
        chequeos = await diagnosticar(tmp_path / "home", tmp_path)
        subagentes = por_nombre(chequeos, "Subagentes")
        assert subagentes.ok, subagentes.detalle
        assert "respondió" in subagentes.detalle

    async def test_sin_cookie_avisa_pero_no_falla(self, tmp_path):
        chequeos = await diagnosticar(tmp_path / "home", tmp_path)
        cookie = por_nombre(chequeos, "Cookie")
        assert cookie.nivel == AVISO and "--cookie" in cookie.detalle
        assert not [c for c in chequeos if c.nivel == FALLO]

    async def test_con_cookie_lo_detecta(self, tmp_path):
        home = tmp_path / "home"
        save_credentials({"__Secure-1PSID": "algo"}, home)
        chequeos = await diagnosticar(home, tmp_path)
        cookie = por_nombre(chequeos, "Cookie")
        assert cookie.ok and "__Secure-1PSID" in cookie.detalle

    async def test_carpeta_no_escribible_se_detecta(self, tmp_path):
        bloqueada = tmp_path / "bloqueada"
        bloqueada.mkdir()
        bloqueada.chmod(0o500)
        try:
            chequeos = await diagnosticar(tmp_path / "home", bloqueada)
            assert por_nombre(chequeos, "Carpeta de trabajo").nivel == FALLO
        finally:
            bloqueada.chmod(0o700)

    async def test_sin_probar_red_no_consulta_gemini(self, tmp_path):
        chequeos = await diagnosticar(tmp_path / "home", tmp_path, probar_red=False)
        assert not [c for c in chequeos if "Conexión" in c.nombre]

    async def test_con_red_y_sin_cookie_no_intenta_conectarse(self, tmp_path):
        chequeos = await diagnosticar(tmp_path / "home", tmp_path, probar_red=True)
        conexion = por_nombre(chequeos, "Conexión")
        assert conexion.nivel == AVISO and "nada que probar" in conexion.detalle


class TestInforme:
    def test_todo_ok_devuelve_cero(self):
        console, buffer = consola()
        assert imprimir(console, [Chequeo("Algo", OK, "bien")]) == 0
        assert "Todo en orden" in buffer.getvalue()

    def test_un_fallo_devuelve_uno(self):
        console, buffer = consola()
        codigo = imprimir(console, [Chequeo("Algo", OK, "bien"), Chequeo("Otro", FALLO, "mal")])
        assert codigo == 1 and "1 problema" in buffer.getvalue()

    def test_los_avisos_no_hacen_fallar(self):
        console, buffer = consola()
        codigo = imprimir(console, [Chequeo("Algo", AVISO, "ojo")])
        assert codigo == 0 and "1 aviso" in buffer.getvalue()

    def test_se_ve_el_detalle_de_cada_chequeo(self):
        console, buffer = consola()
        imprimir(console, [Chequeo("Cookie", AVISO, "no configurada")])
        salida = buffer.getvalue()
        assert "Cookie" in salida and "no configurada" in salida
