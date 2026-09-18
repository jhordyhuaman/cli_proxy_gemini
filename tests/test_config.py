import json
import os
import stat

from mgm.config import (
    Config,
    load_config,
    load_cookies,
    load_credentials,
    save_credentials,
)


def test_defaults_without_any_layer(tmp_path):
    config = load_config(home=tmp_path / "home", cwd=tmp_path / "proj", environ={})
    assert config == Config()


def test_global_layer(tmp_path):
    home = tmp_path / "home"
    (home / ".mgm").mkdir(parents=True)
    (home / ".mgm" / "config.toml").write_text('transport = "fake"\nmodel = "gemini-pro"\n')
    config = load_config(home=home, cwd=tmp_path / "proj", environ={})
    assert config.transport == "fake"
    assert config.model == "gemini-pro"
    assert config.max_retries == 3


def test_conversacion_continua_viene_encendida(tmp_path):
    """Un solo chat en gemini.google.com por sesión, no uno por llamada."""
    config = load_config(home=tmp_path / "home", cwd=tmp_path / "proj", environ={})
    assert config.conversacion_continua is True


def test_conversacion_continua_se_puede_apagar_por_toml(tmp_path):
    home = tmp_path / "home"
    (home / ".mgm").mkdir(parents=True)
    (home / ".mgm" / "config.toml").write_text("conversacion_continua = false\n")
    config = load_config(home=home, cwd=tmp_path / "proj", environ={})
    assert config.conversacion_continua is False


def test_conversacion_continua_se_puede_apagar_por_entorno(tmp_path):
    config = load_config(
        home=tmp_path / "home", cwd=tmp_path / "proj",
        environ={"MGM_CONVERSACION_CONTINUA": "false"},
    )
    assert config.conversacion_continua is False


def test_un_booleano_de_entorno_en_verdadero_se_lee_bien(tmp_path):
    config = load_config(
        home=tmp_path / "home", cwd=tmp_path / "proj",
        environ={"MGM_CONVERSACION_CONTINUA": "true"},
    )
    assert config.conversacion_continua is True


def test_project_layer_overrides_global(tmp_path):
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    (home / ".mgm").mkdir(parents=True)
    (proj / ".mgm").mkdir(parents=True)
    (home / ".mgm" / "config.toml").write_text('transport = "g4f"\nmax_retries = 5\n')
    (proj / ".mgm" / "config.toml").write_text('transport = "fake"\n')
    config = load_config(home=home, cwd=proj, environ={})
    assert config.transport == "fake"
    assert config.max_retries == 5


def test_env_overrides_project(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".mgm").mkdir(parents=True)
    (proj / ".mgm" / "config.toml").write_text('transport = "g4f"\nmax_retries = 5\n')
    config = load_config(
        home=tmp_path / "home",
        cwd=proj,
        environ={"MGM_TRANSPORT": "fake", "MGM_MAX_RETRIES": "9", "MGM_BASE_DELAY": "1.5"},
    )
    assert config.transport == "fake"
    assert config.max_retries == 9
    assert config.base_delay == 1.5


def test_unknown_keys_ignored(tmp_path):
    home = tmp_path / "home"
    (home / ".mgm").mkdir(parents=True)
    (home / ".mgm" / "config.toml").write_text('transport = "fake"\nfuturo = "x"\n')
    config = load_config(home=home, cwd=tmp_path / "proj", environ={})
    assert config.transport == "fake"


def test_save_credentials_writes_0600(tmp_path):
    home = tmp_path / "home"
    path = save_credentials({"__Secure-1PSID": "secreto"}, home=home)
    assert json.loads(path.read_text()) == {"cookies": {"__Secure-1PSID": "secreto"}}
    if os.name != "nt":
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600


def test_load_credentials_roundtrip(tmp_path):
    home = tmp_path / "home"
    save_credentials({"__Secure-1PSID": "abc"}, home=home)
    assert load_cookies(home=home) == {"__Secure-1PSID": "abc"}


def test_load_credentials_missing_file(tmp_path):
    assert load_credentials(home=tmp_path / "home") == {}
    assert load_cookies(home=tmp_path / "home") == {}
