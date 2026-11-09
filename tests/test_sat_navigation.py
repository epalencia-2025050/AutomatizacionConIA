import pytest

from src.sat.invoice_search import InvoiceSearch, SatNavigationError


class MissingLocator:
    @property
    def first(self):
        return self

    def count(self):
        return 0


class MissingMenuPage:
    url = "https://farm3.sat.gob.gt/menu/consulta.jsf"

    def locator(self, _selector):
        return MissingLocator()

    def is_closed(self):
        return False


def test_menu_sat_fallback_manual(monkeypatch):
    search = InvoiceSearch.__new__(InvoiceSearch)
    search.page = MissingMenuPage()
    search.sat = {"timeouts": {"default_ms": 15000}}
    search.sel = {"menu_path": ['button:has-text("Menú")']}
    prompts = []
    monkeypatch.setattr("builtins.input", lambda: prompts.append(True))

    search.open_module()

    assert prompts == [True]


def test_menu_sat_headless_falla_sin_selector():
    search = InvoiceSearch.__new__(InvoiceSearch)
    search.page = MissingMenuPage()
    search.sat = {"headless": True, "timeouts": {"default_ms": 15000}}
    search.sel = {"menu_path": ['button:has-text("Menú")']}

    with pytest.raises(SatNavigationError, match="headless"):
        search.open_module()
