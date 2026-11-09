"""Pruebas del Reporter (Fase 4): CSV por corrida en data/reports."""
import csv

from src.reporting.reporter import Reporter
from src.database.repository import Repository
from src.processing.xml_reader import XmlReader

from tests.fixtures_fel import XML_FEL_CERTIFICADO, make_xml


def _repo_con_dte(tmp_path, cant=1):
    repo = Repository(tmp_path / "bd.db")
    for i in range(cant):
        data = XmlReader().parse(make_xml(tmp_path, XML_FEL_CERTIFICADO))
        repo.insertar(data, estado="VALIDADA" if i == 0 else "SUBIDA")
    return repo


def test_generar_csv_con_secciones(tmp_path):
    repo = _repo_con_dte(tmp_path)
    out = Reporter(tmp_path / "reports").reporte_ejecucion(
        "01/11/2026 a 09/11/2026", {"descargas": 2, "validos": 1}, repo)
    assert out.exists() and out.name.startswith("reporte_")

    with open(out, encoding="utf-8-sig", newline="") as fh:
        filas = list(csv.reader(fh))

    assert filas[0][:6] == ["tipo", "uuid", "nit_emisor", "nombre_emisor",
                            "total", "estado"]
    tipos = [f[0] for f in filas[1:]]
    assert "EJECUCION" in tipos
    assert "ESTADO_BD" in tipos
    assert tipos.count("DETALLE") == 1, "una línea por factura en BD"

    detalle = next(f for f in filas[1:] if f[0] == "DETALLE")
    assert detalle[1], "DETALLE debe traer el uuid"
    assert detalle[9] == "" or detalle[9], "columna fecha_carga presente"

    ejecucion = next(f for f in filas[1:] if f[0] == "EJECUCION")
    assert "rango=01/11/2026 a 09/11/2026" in ejecucion[6]
    assert "descargas=2" in ejecucion[6]


def test_reporte_sin_bd_solo_resumen(tmp_path):
    out = Reporter(tmp_path / "reports").reporte_ejecucion("n/d", {"errores": 3})
    texto = out.read_text(encoding="utf-8-sig")
    assert "EJECUCION" in texto
    assert "errores=3" in texto
    assert "ESTADO_BD" not in texto, "sin repo no debe haber sección BD"


def test_ultimo_reporte_devuelve_el_mas_reciente(tmp_path):
    rep = Reporter(tmp_path / "reports")
    assert rep.ultimo_reporte() is None          # vacío aún
    rep.reporte_ejecucion("a", {})
    primero = rep.ultimo_reporte()
    rep.reporte_ejecucion("b", {})
    assert rep.ultimo_reporte() >= primero
    assert rep.ultimo_reporte().name.startswith("reporte_")
