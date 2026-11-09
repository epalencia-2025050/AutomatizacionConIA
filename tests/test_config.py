"""Prueba la carga de configuración y las precondiciones de la Fase 1."""
import os
from pathlib import Path

import yaml

from src.utils.environment import load_environment

ROOT = Path(__file__).resolve().parents[1]


def load_yaml(rel):
    with open(ROOT / rel, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_settings_completo():
    s = load_yaml("config/settings.yaml")
    assert s["sat"]["portal_url"].startswith("https://")
    assert s["sat"]["timeouts"]["mfa_s"] >= 60
    for d in ("downloads", "processed", "errors", "session"):
        assert d in s["sat"]["dirs"]


def test_selectors_login_real():
    """Selectores verificados contra el HTML real de farm3.sat.gob.gt."""
    y = load_yaml("config/selectors.yaml")
    login = y["login"]
    assert login["username_input"] == 'input[name="formContent:username"]'
    assert login["password_input"] == 'input[name="formContent:password"]'
    assert "cmdbtnIngresar" in login["submit_button"]
    assert "inMaskVerifyCode" in login["mfa_input"]


def test_estructura_proyecto():
    for carpeta in ("config", "src", "data", "logs", "tools"):
        assert (ROOT / carpeta).is_dir()
    for modulo in ("orchestrator.py", "sat/browser.py", "sat/authentication.py",
                   "sat/invoice_search.py", "sat/downloader.py", "utils/logger.py",
                   "utils/file_manager.py"):
        assert (ROOT / "src" / modulo).is_file()


def test_load_environment_carga_src_y_prioriza_raiz(tmp_path, monkeypatch):
    root = tmp_path
    (root / "src").mkdir()
    (root / ".env").write_text("SAT_NIT=desde_raiz\n", encoding="utf-8")
    (root / "src" / ".env").write_text(
        "SAT_NIT=desde_src\nSAT_PASSWORD=clave_de_prueba\n", encoding="utf-8")
    monkeypatch.delenv("SAT_NIT", raising=False)
    monkeypatch.delenv("SAT_PASSWORD", raising=False)

    load_environment(root)

    assert os.environ["SAT_NIT"] == "desde_raiz"
    assert os.environ["SAT_PASSWORD"] == "clave_de_prueba"
