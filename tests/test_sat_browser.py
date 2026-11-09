from src.sat.browser import BrowserManager


def test_navegador_visible_espera_enter_antes_de_cerrar(tmp_path, monkeypatch):
    manager = BrowserManager(False, tmp_path / "session.json", keep_open=True)
    mensajes = []
    cerrado = []
    monkeypatch.setattr("builtins.input", lambda mensaje: mensajes.append(mensaje))
    monkeypatch.setattr(manager, "stop", lambda: cerrado.append(True))

    manager.__exit__(None, None, None)

    assert mensajes
    assert cerrado == [True]


def test_navegador_headless_no_espera_enter(tmp_path, monkeypatch):
    manager = BrowserManager(True, tmp_path / "session.json", keep_open=True)
    cerrado = []
    monkeypatch.setattr(
        "builtins.input",
        lambda _mensaje: (_ for _ in ()).throw(AssertionError("no debe esperar")),
    )
    monkeypatch.setattr(manager, "stop", lambda: cerrado.append(True))

    manager.__exit__(None, None, None)

    assert cerrado == [True]
