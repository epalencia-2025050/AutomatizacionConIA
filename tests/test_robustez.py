"""Pruebas de la Fase 6: reintentos con backoff y backup diario."""
import pytest

from src.orchestrator import Orchestrator
from src.sat.invoice_search import SatNavigationError
from src.utils.backup import BackupManager

SETTINGS = {
    "sat": {"dirs": {}},
    "database": {"ruta": "x.db"},   # no se usa: tests van a tmp_path
    "reintentos": {"activar": True, "esperas_min": [1, 2, 5]},
}


@pytest.fixture(name="orch")
def _orch(monkeypatch):
    orch = Orchestrator.__new__(Orchestrator)
    orch.settings = {k: (dict(v) if isinstance(v, dict) else v)
                     for k, v in SETTINGS.items()}
    orch.escala_espera = 0.0          # no dormir de verdad en tests
    monkeypatch.setattr(orch, "_backup_bd", lambda: None)
    return orch


def test_reintenta_y_exitoso(orch):
    llamadas = []

    def fn():
        llamadas.append(1)
        if len(llamadas) < 3:
            raise ConnectionError("red caida")
        return "OK"

    assert orch._con_reintentos("prueba", fn) == "OK"
    assert len(llamadas) == 3, "el reintento 2 recuperó el flujo"


def test_agota_reintentos_y_levanta(orch):
    def fn():
        raise ValueError("fallo permanente")

    with pytest.raises(ValueError):
        orch._con_reintentos("prueba", fn)


def test_desactivado_no_reintenta(orch):
    orch.settings["reintentos"]["activar"] = False
    llamadas = []

    def fn():
        llamadas.append(1)
        raise RuntimeError("aun asi no reintenta")

    with pytest.raises(RuntimeError):
        orch._con_reintentos("prueba", fn)
    assert len(llamadas) == 1


def test_error_de_selectores_sat_no_reintenta(orch):
    llamadas = []

    def fn():
        llamadas.append(1)
        raise SatNavigationError("selector no configurado")

    with pytest.raises(SatNavigationError):
        orch._con_reintentos("Fase 1 (SAT)", fn)
    assert len(llamadas) == 1


def test_espera_progresiva_en_orden(orch, monkeypatch):
    esperadas = []
    monkeypatch.setattr(orch, "_dormir", lambda m: esperadas.append(m))

    def fn():
        raise OSError("siempre falla")

    with pytest.raises(OSError):
        orch._con_reintentos("prueba", fn)
    assert esperadas == [1, 2, 5]


# ----------------------------------------------------------------
# Backup diario
# ----------------------------------------------------------------
def test_backup_crea_copia_del_dia(tmp_path):
    db = tmp_path / "automatizacion.db"
    db.write_bytes(b"contenido-bd")
    bm = BackupManager(db, directorio=tmp_path / "backups", retencion=3)
    out = bm.backup_diario()
    assert out.exists() and out.name.startswith("automatizacion_2026")
    assert out.read_bytes() == b"contenido-bd"


def test_backup_mismo_dia_no_duplica(tmp_path):
    db = tmp_path / "bd.db"
    db.write_bytes(b"x")
    bm = BackupManager(db, directorio=tmp_path / "backups")
    primero = bm.backup_diario()
    db.write_bytes(b"y")   # la BD cambia después
    segundo = bm.backup_diario()
    assert primero == segundo, "una sola copia por día de calendario"
    assert segundo.read_bytes() == b"x", "copia del momento de la 1a corrida"


def test_backup_sin_bd_omite(tmp_path):
    bm = BackupManager(tmp_path / "inexistente.db",
                       directorio=tmp_path / "backups")
    assert bm.backup_diario() is None


def test_backup_retencion_borra_viejos(tmp_path):
    db = tmp_path / "bd.db"
    db.write_bytes(b"x")
    bm = BackupManager(db, directorio=tmp_path / "backups", retencion=2)
    dirb = tmp_path / "backups"
    dirb.mkdir()
    for d in ("20261101", "20261102", "20261103"):
        (dirb / f"automatizacion_{d}.db").write_bytes(b"old")
    bm.backup_diario()
    nombres = [p.name for p in bm.lista()]
    assert len(nombres) == 2, f"retención 2 deja 2: {nombres}"
    assert "automatizacion_20261101.db" not in nombres
