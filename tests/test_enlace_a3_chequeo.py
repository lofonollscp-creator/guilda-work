"""Pre-chequeo del SUENLACE.DAT (app/enlace_a3_chequeo.py, facturas_contables.comprobar_exportacion, /contabilidad/comprobar*)."""
import io

import pytest

from app import db, enlace_a3 as a3, enlace_a3_chequeo as chq, facturas_contables as fc, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_enlace_a3 import FACTURA
from tests.test_facturas_contables import LINEA, _datos

EMITIDA = {**FACTURA, "tipo": "emitida", "numero": "E-9", "cuenta_tercero": "43000001", "nif": "A58818501", "nombre": "Cliente SA",
           "lineas": [{"cuenta": "70000000", "subtipo": "01", "base_centimos": 100000, "pct_iva": 2100, "cuota_iva": 21000, "cuenta_iva": "47700000", "pct_retencion": 1500, "cuota_retencion": 15000,
                       "cuenta_retencion": "47510000"}], "total_centimos": 106000}
ABONO = {**FACTURA, "numero": "A-124", "abono": True, "rectifica_fecha": "2026-09-01", "rectifica_numero": "A-100"}
VARIAS = {**FACTURA, "numero": "A-125", "total_centimos": 121000 + 10400, "lineas": [FACTURA["lineas"][0], {"cuenta": "62900000", "subtipo": "01", "base_centimos": 10000, "pct_iva": 400, "cuota_iva": 400, "cuenta_iva": "47200000"}]}


def _bytes(*facturas, digitos=8):
    return a3.generar(list(facturas), empresa=12, digitos=digitos)


def _modificar(contenido: bytes, registro: int, pos: int, texto: str) -> bytes:
    """Cambia, en el registro `registro` (1 = primero), las posiciones desde `pos` (1 a 510) por `texto`."""
    t = contenido.decode("latin-1")
    ini = (registro - 1) * 512 + pos - 1
    return (t[:ini] + texto + t[ini + len(texto):]).encode("latin-1")


def _errores(contenido, digitos=8):
    return [e["mensaje"] for e in chq.chequear(contenido, digitos)["errores"]]


def _avisos(contenido, digitos=8):
    return [e["mensaje"] for e in chq.chequear(contenido, digitos)["avisos"]]


# --- Lo que genera el propio generador debe pasar ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("facturas", [[FACTURA], [EMITIDA], [ABONO], [VARIAS], [FACTURA, EMITIDA, ABONO, VARIAS],
                                      [{**FACTURA, "numero": "2026/PROVEEDOR/00000118", "nombre": "Ñandú ÁÉÍ Sociedad Limitada con un nombre larguísimo S.L."}]])
def test_lo_que_genera_el_generador_pasa_sin_errores(facturas):
    r = chq.chequear(_bytes(*facturas))
    assert r["ok"] and r["errores"] == [] and r["facturas"] == len(facturas), r["errores"]


def test_el_informe_cuenta_registros_facturas_y_abonos():
    r = chq.chequear(_bytes(FACTURA, ABONO))
    assert (r["registros"], r["facturas"], r["totales"]["abonos"], r["totales"]["total"]) == (5, 2, 1, 2420.0)


# --- Estructura ------------------------------------------------------------------------------------------------------------------------------------

def test_vacio_y_tamano_incorrecto():
    assert _errores(b"") == ["El fichero está vacío."]
    assert any("múltiplo" in e for e in _errores(_bytes(FACTURA)[:-5]))
    assert any("no mide 512" in e for e in _errores(_bytes(FACTURA)[:-5]))


def test_un_fin_de_linea_distinto_se_detecta():
    sin_crlf = _bytes(FACTURA).replace(b"\r\n", b"\n\n")
    assert any("CR LF" in e for e in _errores(sin_crlf))


@pytest.mark.parametrize("registro,pos,texto,fragmento", [
    (1, 1, "4", "posición 1 debe ser «5»"),
    (1, 2, "ABCDE", "código de empresa"),
    (1, 7, "20261340", "fecha del registro"),
    (1, 15, "7", "Tipo de registro desconocido"),
    (1, 509, "X", "posición 509"),
    (1, 510, "Q", "posición 510"),
    (1, 16, "40000001ABCD", "subcuenta del tercero"),
    (1, 16, "400000019999", "más de 8 dígitos significativos"),
    (1, 16, "000000000000", "está a cero"),
    (1, 58, "7", "tipo de factura"),
    (1, 59, " " * 10, "Falta el número"),
    (1, 100, "1210.00 EUR  ", "importe total"),
    (1, 237, "20269999", "fecha de operación"),
    (2, 16, " " * 12, "cuenta de gasto o ingreso"),
    (2, 58, "A", "sentido (58)"),
    (2, 59, "OTRO      ", "número de factura del detalle"),
    (2, 69, "M", "último detalle"),
    (2, 69, "X", "marca de último detalle"),
    (2, 102, "abc", "formato de a3"),
    (2, 121, "+0000009999.99", "cuota de IVA"),
    (2, 175, "X", "sujeta a IVA"),
    (2, 192, " " * 12, "cuenta de IVA soportado"),
])
def test_cada_campo_mal_se_detecta(registro, pos, texto, fragmento):
    errores = _errores(_modificar(_bytes(FACTURA), registro, pos, texto))
    assert any(fragmento in e for e in errores), errores


def test_el_numero_del_registro_apunta_al_fallo():
    r = chq.chequear(_modificar(_bytes(FACTURA, EMITIDA), 3, 7, "20261340"))
    assert [e["registro"] for e in r["errores"] if "fecha del registro" in e["mensaje"]] == [3]


# --- Orden de registros y rectificativas ---------------------------------------------------------------------------------------------------------

def test_un_detalle_sin_cabecera_o_dos_ultimos():
    t = _bytes(FACTURA)
    solo_detalle = t[512:]
    assert any("después de la cabecera" in e for e in _errores(solo_detalle))
    dos_u = _bytes(VARIAS)
    assert any("después del que estaba marcado" in e for e in _errores(_modificar(dos_u, 2, 69, "U")))
    sin_u = _modificar(dos_u, 3, 69, "M")
    assert any("debe llevar «U»" in e for e in _errores(sin_u))


def test_una_factura_sin_detalles():
    assert any("no tiene ningún detalle" in e for e in _errores(_bytes(FACTURA)[:512]))


def test_el_abono_necesita_su_ampliacion_y_la_factura_normal_no_la_lleva():
    abono = _bytes(ABONO)
    assert any("necesita su registro de ampliación" in e for e in _errores(abono[:1024]))
    normal_con_4 = _bytes(FACTURA) + abono[1024:]
    assert any("solo los abonos" in e for e in _errores(normal_con_4))
    assert any("tiene que ir después de los detalles" in e for e in _errores(abono[1024:]))


@pytest.mark.parametrize("pos,texto,fragmento", [(59, "        ", "fecha de la factura rectificada"), (67, " " * 60, "número de la factura rectificada"), (157, "X", "tipo de rectificativa"), (304, "E", "tipo de factura de la ampliación")])
def test_campos_de_la_ampliacion(pos, texto, fragmento):
    assert any(fragmento in e for e in _errores(_modificar(_bytes(ABONO), 3, pos, texto)))


# --- Importes y cuadre -----------------------------------------------------------------------------------------------------------------------------

def test_retencion_y_recargo_se_comprueban():
    e = _bytes(EMITIDA)
    assert chq.chequear(e)["ok"]
    assert any("retención" in x and "no es la base" in x for x in _errores(_modificar(e, 2, 159, "+0000000100.00")))
    assert any("falta su cuenta" in x for x in _errores(_modificar(e, 2, 216, " " * 12)))
    assert any("recargo" in x for x in _errores(_modificar(e, 2, 140, "+0000000500.00")))


def test_un_detalle_no_sujeto_con_cuota_es_error():
    assert any("no sujeto" in e for e in _errores(_modificar(_bytes(FACTURA), 2, 175, "N")))


def test_total_que_no_cuadra_es_aviso_no_error():
    t = _modificar(_bytes(FACTURA), 1, 100, "+0000001300.00")
    assert chq.chequear(t)["ok"] and any("no es la suma de sus detalles" in a for a in _avisos(t))


# --- Avisos ------------------------------------------------------------------------------------------------------------------------------------------

def test_sin_nif_o_con_nif_dudoso_es_aviso():
    sin = {**FACTURA, "nif": None}
    assert chq.chequear(_bytes(sin))["ok"] and any("no lleva NIF" in a for a in _avisos(_bytes(sin)))
    assert any("dígito de control" in a for a in _avisos(_bytes({**FACTURA, "nif": "12345678A"})))
    assert not any("NIF" in a for a in _avisos(_bytes({**FACTURA, "nif": "12345678Z"})))


def test_facturas_repetidas_y_varios_ejercicios_y_empresas():
    assert any("está repetida" in e for e in _errores(_bytes(FACTURA, FACTURA)))
    otro_año = {**FACTURA, "numero": "A-9", "fecha": "2025-12-31", "fecha_operacion": "2025-12-31"}
    assert any("varios ejercicios" in a for a in _avisos(_bytes(FACTURA, otro_año)))
    mezcla = _bytes(FACTURA) + _modificar(_bytes(EMITIDA), 1, 2, "99999")
    assert any("varios códigos de empresa" in a for a in _avisos(mezcla))


def test_fecha_lejana_es_aviso():
    lejana = {**FACTURA, "fecha": "2010-01-05", "fecha_operacion": "2010-01-05"}
    assert any("muy lejana" in a for a in _avisos(_bytes(lejana)))


# --- Integrado con la exportación -----------------------------------------------------------------------------------------------------------------

def _despacho():
    t = db.crear_tenant("Despacho chequeo")
    u = db.crear_usuario_vinculado_a_kratos("chequeo1@ejemplo.com", "k-chequeo1"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Chequeo SL", nif="B12345678")
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8"})
    return t, u, c


def _revisada(t, u, c, **kw):
    fid = fc.crear(t, u, c, _datos(**kw), [LINEA]); fc.cambiar_estado(t, u, fid, "revisada")
    return fid


def test_comprobar_antes_no_marca_ni_guarda_nada():
    t, u, c = _despacho()
    fid = _revisada(t, u, c)
    informe = fc.comprobar_exportacion(t, u, c)
    assert informe["ok"] and informe["facturas"] == 1 and informe["numeros"] == ["F-1"] and informe["cliente"] == "Cliente Chequeo SL"
    assert fc.obtener(t, u, fid)["estado"] == "revisada" and fc.listar_lotes(t, u) == []


def test_comprobar_antes_enseña_las_subcuentas_nuevas_que_se_asignarian():
    t, u, c = _despacho()
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8", "subcuentas_auto": "1"})
    _revisada(t, u, c, tercero_nif="B77777777", tercero_nombre="Nuevo SL")
    informe = fc.comprobar_exportacion(t, u, c)
    assert informe["subcuentas_nuevas"] == [{"tipo": "proveedor", "nif": "B77777777", "cuenta": "40000001", "nombre": "Nuevo SL"}]
    assert fc.terceros_del_cliente(t, u, c) == []


def test_exportar_devuelve_los_avisos_y_se_niega_a_entregar_un_fichero_con_errores(monkeypatch):
    t, u, c = _despacho()
    _revisada(t, u, c, tercero_nif="12345678A")                  # dígito de control mal: sale, pero con aviso
    r = fc.exportar(t, u, c)
    assert any("dígito de control" in a["mensaje"] for a in r["avisos"])
    t2, u2, c2 = _despacho_2()
    _revisada(t2, u2, c2)
    malo = a3.generar
    monkeypatch.setattr(a3, "generar", lambda *a, **k: _modificar(malo(*a, **k), 2, 121, "+0000009999.99"))
    with pytest.raises(ValueError, match="no pasa el pre-chequeo"):
        fc.exportar(t2, u2, c2)
    assert fc.listar_lotes(t2, u2) == [] and fc.resumen_por_estado(t2, u2, c2)["revisada"] == 1, "no queda lote ni se marca nada"


def _despacho_2():
    t = db.crear_tenant("Despacho chequeo 2")
    u = db.crear_usuario_vinculado_a_kratos("chequeo2@ejemplo.com", "k-chequeo2"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Dos SL", nif="B12345678")
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "8", "digitos": "8"})
    return t, u, c


def test_comprobar_un_lote_guardado():
    t, u, c = _despacho()
    _revisada(t, u, c)
    lote = fc.exportar(t, u, c)["lote"]
    informe = fc.comprobar_lote(t, u, lote)
    assert informe["ok"] and informe["cliente"] == "Cliente Chequeo SL" and informe["facturas"] == 1
    assert fc.comprobar_lote(t, u, 999999) is None
    t2 = db.crear_tenant("Otro chequeo")
    otro = db.crear_usuario_vinculado_a_kratos("chequeo3@ejemplo.com", "k-chequeo3"); db.asignar_tenant(otro, t2)
    assert fc.comprobar_lote(t2, otro, lote) is None


def test_flujo_web(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "chequeoweb@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho chequeo web"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente <b>Web</b>", nif="B12345678")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})
    _revisada(t, uid, c, fecha="2026-08-15")
    html = cliente.get(f"/contabilidad/?cliente_id={c}").get_data(as_text=True)
    assert "Comprobar antes" in html
    r = cliente.post("/contabilidad/comprobar", data={"cliente_id": c, "trimestre": "2026-T3"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Sin errores" in html and "Generar SUENLACE.DAT" in html and "<b>Web</b>" not in html
    assert fc.resumen_por_estado(t, uid, c)["revisada"] == 1
    r = cliente.post("/contabilidad/comprobar", data={"cliente_id": c, "trimestre": "2025-T1"})
    assert r.status_code == 302 and "error=" in r.headers["Location"]
    lote = cliente.post("/contabilidad/exportar", data={"cliente_id": c, "trimestre": "2026-T3"})
    assert lote.status_code == 200
    lotes = cliente.get("/contabilidad/lotes").get_data(as_text=True)
    assert "Comprobar" in lotes
    id_lote = fc.listar_lotes(t, uid)[0]["id"]
    assert "Sin errores" in cliente.get(f"/contabilidad/lotes/{id_lote}/comprobar").get_data(as_text=True)
    assert cliente.get("/contabilidad/lotes/999999/comprobar").status_code == 404
    assert "Elige un fichero" in cliente.post("/contabilidad/comprobar-fichero", data={}, content_type="multipart/form-data").get_data(as_text=True)
    malo = _modificar(_bytes(FACTURA), 2, 121, "+0000009999.99")
    r = cliente.post("/contabilidad/comprobar-fichero", data={"archivo": (io.BytesIO(malo), "SUENLACE.DAT"), "digitos": "8"}, content_type="multipart/form-data")
    html = r.get_data(as_text=True)
    assert "Errores: 1" in html and "cuota de IVA" in html
    ok = cliente.post("/contabilidad/comprobar-fichero", data={"archivo": (io.BytesIO(_bytes(FACTURA)), "SUENLACE.DAT")}, content_type="multipart/form-data")
    assert "Sin errores" in ok.get_data(as_text=True)
