"""¿Es una factura? Se aparta lo que claramente no lo es antes de gastar IA (app/lectura_clasificacion.py)."""
import json

import pytest

from app import facturas_contables as fc, lectura_clasificacion as lcl, lectura_facturas as lf
from tests.test_facturas_contables import PDF, _despacho
from tests.test_lectura_facturas import RESPUESTA, modelo  # noqa: F401 -- fixture

RELLENO = " Calle Mayor 12 Madrid 28001 teléfono 910000000 referencia 2026 0001 0002 0003 " * 4
EXTRACTO = "EXTRACTO DE CUENTA IBAN ES91 2100 0418 4502 0005 1332. Saldo anterior 1.200,00. Movimientos del periodo. Fecha valor. Cargos y abonos. Saldo final 900,00." + RELLENO
NOMINA = "RECIBO DE SALARIOS. Devengos: salario base 1.800,00. Deducciones: IRPF 15 %. Cotización a la Seguridad Social. Líquido a percibir 1.350,00." + RELLENO
CONTRATO = "CONTRATO DE ARRENDAMIENTO. REUNIDOS de una parte el arrendador y de otra el arrendatario, en lo sucesivo las partes. CLÁUSULA primera. Ambas partes acuerdan." + RELLENO
FACTURA = "FACTURA nº 2026/118 Base imponible 100,00 Cuota IVA 21,00 Total factura 121,00" + RELLENO


@pytest.mark.parametrize("texto,clave", [(EXTRACTO, "extracto"), (NOMINA, "nomina"), (CONTRATO, "contrato")])
def test_se_reconoce_lo_que_claramente_no_es_una_factura(texto, clave):
    assert lcl.tipo_de_documento(texto)[0] == clave


def test_ante_la_duda_es_una_factura():
    assert lcl.tipo_de_documento(FACTURA) is None
    assert lcl.tipo_de_documento(EXTRACTO + " Pago de la factura 118 de Papelería") is None          # un rastro de factura basta para leerla como siempre
    assert lcl.tipo_de_documento("Saldo anterior 100. Movimientos." + RELLENO) is None               # solo dos señales
    assert lcl.tipo_de_documento("") is None and lcl.tipo_de_documento(None) is None and lcl.tipo_de_documento("extracto saldo anterior movimientos") is None   # sin texto suficiente


def test_un_extracto_subido_como_factura_se_aparta_sin_gastar_ia(modelo, monkeypatch):
    t, u, c = _despacho()
    modelo.respuesta = json.dumps(RESPUESTA)
    llamadas = []
    monkeypatch.setattr(lf, "_leer_con_ia", lambda *a, **k: llamadas.append(1))
    monkeypatch.setattr(lf, "_texto_del_pdf", lambda contenido, mime: EXTRACTO)
    fid = fc.subir_archivos(t, u, c, "recibida", [("e.pdf", "application/pdf", PDF + b"1")])[0]
    avisos = lf.leer(t, u, fid)
    f = fc.obtener(t, u, fid)
    assert f["estado"] == "descartada" and "No es una factura" in f["notas"] and not llamadas
    assert avisos and "un extracto del banco" in avisos[0]
    assert fc.historial(t, u, fid)[1]["que"] == "Apartada: no era una factura" or any(h["que"] == "Apartada: no era una factura" for h in fc.historial(t, u, fid))
    from app import almacen_documentos
    assert len(almacen_documentos.listar_de_cliente_fiscal(t, c)) == 1                              # el archivo sigue en los documentos del cliente


def test_una_factura_de_verdad_se_lee_como_siempre(modelo, monkeypatch):
    t, u, c = _despacho()
    modelo.respuesta = json.dumps(RESPUESTA)
    monkeypatch.setattr(lf, "_texto_del_pdf", lambda contenido, mime: FACTURA)
    fid = fc.subir_archivos(t, u, c, "recibida", [("f.pdf", "application/pdf", PDF + b"2")])[0]
    lf.leer(t, u, fid)
    assert fc.obtener(t, u, fid)["estado"] == "pendiente"
