"""Régimen de IVA del cliente y tipo de operación de cada línea (facturas_contables, enlace_a3, enlace_a3_chequeo)."""
import pytest

from app import db, facturas_contables as fc, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.test_facturas_contables import LINEA, _datos


def _despacho(**ajustes):
    t = db.crear_tenant("Despacho regimen")
    u = db.crear_usuario_vinculado_a_kratos("regimen1@ejemplo.com", "k-regimen1"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Regimen SL", nif="B12345678")
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8", **ajustes})
    return t, u, c


def _lineas(t, u, fid):
    return fc.obtener(t, u, fid)["lineas"]


def _detalles(contenido: bytes):
    return [l for l in contenido.decode("latin-1").split("\r\n") if l[:1] == "5" and l[14] == "9"]


# --- Ajustes ------------------------------------------------------------------------------------------------------------------------------------

def test_por_defecto_es_regimen_general_sin_retencion():
    t, u, c = _despacho()
    cfg = fc.configuracion(t, c)
    assert (cfg["regimen_iva"], cfg["retencion_emitidas"]) == ("general", 0)


@pytest.mark.parametrize("datos,fragmento", [({"regimen_iva": "raro"}, "régimen"), ({"retencion_emitidas": "70"}, "entre 0 y 60")])
def test_los_ajustes_de_regimen_se_validan(datos, fragmento):
    t, u, c = _despacho()
    with pytest.raises(ValueError, match=fragmento):
        fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8", **datos})


def test_la_retencion_se_escribe_en_porcentaje_y_se_guarda_en_centesimas():
    t, u, c = _despacho(retencion_emitidas="15,5", regimen_iva="recargo")
    cfg = fc.configuracion(t, c)
    assert (cfg["retencion_emitidas"], cfg["regimen_iva"]) == (1550, "recargo")
    c2 = crear_cliente_fiscal(t, "Otro", nif="B87654321")           # copiar no reinterpreta las centésimas como si fueran un porcentaje
    usuario = db.get_connection().execute("SELECT id FROM usuarios WHERE tenant_id = ?", (t,)).fetchone()["id"]
    assert fc.copiar_configuracion(t, usuario, c, c2)["retencion_emitidas"] == 1550


def test_los_clientes_heredan_el_regimen_del_despacho():
    t, u, c = _despacho()
    fc.guardar_configuracion_despacho(t, u, {"digitos": "8", "regimen_iva": "exento", "retencion_emitidas": "7"})
    c2 = crear_cliente_fiscal(t, "Sin ajustes", nif="B87654321")
    cfg = fc.configuracion(t, c2)
    assert (cfg["regimen_iva"], cfg["retencion_emitidas"]) == ("exento", 700)
    assert fc.configuracion(t, c)["regimen_iva"] == "general", "el que ya tenía los suyos no cambia"


# --- Valores que aplica el régimen -----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("pct_iva,recargo", [("21", 520), ("10", 140), ("4", 50), ("0", 0)])
def test_recargo_de_equivalencia_en_las_compras(pct_iva, recargo):
    t, u, c = _despacho(regimen_iva="recargo")
    fid = fc.crear(t, u, c, _datos(), [{"base": "100", "pct_iva": pct_iva}])
    l = _lineas(t, u, fid)[0]
    assert l["pct_recargo"] == recargo and l["cuota_recargo"] == recargo


def test_el_recargo_escrito_manda_y_cero_lo_quita_y_en_las_ventas_no_se_aplica():
    t, u, c = _despacho(regimen_iva="recargo")
    assert _lineas(t, u, fc.crear(t, u, c, _datos(numero="2"), [{"base": "100", "pct_iva": "21", "pct_recargo": "1,4"}]))[0]["pct_recargo"] == 140
    assert _lineas(t, u, fc.crear(t, u, c, _datos(numero="3"), [{"base": "100", "pct_iva": "21", "pct_recargo": "0"}]))[0]["pct_recargo"] == 0
    assert _lineas(t, u, fc.crear(t, u, c, _datos(numero="4", tipo="emitida"), [{"base": "100", "pct_iva": "21"}]))[0]["pct_recargo"] == 0


def test_el_total_incluye_el_recargo_automatico():
    t, u, c = _despacho(regimen_iva="recargo")
    assert fc.obtener(t, u, fc.crear(t, u, c, _datos(), [{"base": "100", "pct_iva": "21"}]))["total_centimos"] == 12620


def test_retencion_por_defecto_solo_en_las_emitidas_y_si_no_se_escribe_otra():
    t, u, c = _despacho(retencion_emitidas="15")
    e = _lineas(t, u, fc.crear(t, u, c, _datos(tipo="emitida", numero="E1"), [{"base": "1000", "pct_iva": "21"}]))[0]
    assert (e["pct_retencion"], e["cuota_retencion"]) == (1500, 15000)
    assert _lineas(t, u, fc.crear(t, u, c, _datos(tipo="emitida", numero="E2"), [{"base": "1000", "pct_iva": "21", "pct_retencion": "7"}]))[0]["pct_retencion"] == 700
    assert _lineas(t, u, fc.crear(t, u, c, _datos(tipo="emitida", numero="E3"), [{"base": "1000", "pct_iva": "21", "pct_retencion": "0"}]))[0]["pct_retencion"] == 0
    assert _lineas(t, u, fc.crear(t, u, c, _datos(numero="R1"), [{"base": "1000", "pct_iva": "21"}]))[0]["pct_retencion"] == 0, "una factura recibida no lleva la del cliente"


def test_actividad_exenta_pone_las_operaciones_por_defecto():
    t, u, c = _despacho(regimen_iva="exento")
    assert _lineas(t, u, fc.crear(t, u, c, _datos(tipo="emitida", numero="E1"), [{"base": "100"}]))[0]["subtipo"] == "02"
    assert _lineas(t, u, fc.crear(t, u, c, _datos(numero="R1"), [{"base": "100", "pct_iva": "21"}]))[0]["subtipo"] == "07"
    assert _lineas(t, u, fc.crear(t, u, c, _datos(numero="R2"), [{"base": "100", "pct_iva": "21", "subtipo": "01"}]))[0]["subtipo"] == "01", "lo elegido manda"


def test_sin_regimen_el_tipo_de_operacion_en_blanco_es_01():
    t, u, c = _despacho()
    assert _lineas(t, u, fc.crear(t, u, c, _datos(), [{"base": "100", "pct_iva": "21"}]))[0]["subtipo"] == "01"


def test_editar_vuelve_a_aplicar_el_regimen_a_lo_que_se_deja_en_blanco():
    t, u, c = _despacho(regimen_iva="recargo")
    fid = fc.crear(t, u, c, _datos(), [{"base": "100", "pct_iva": "21"}])
    fc.actualizar(t, u, fid, _datos(), [{"base": "200", "pct_iva": "21"}])
    assert _lineas(t, u, fid)[0]["cuota_recargo"] == 1040


# --- Lo que sale en el fichero ---------------------------------------------------------------------------------------------------------------------

def test_el_impreso_349_sale_solo_en_las_operaciones_intracomunitarias():
    t, u, c = _despacho()
    casos = [("emitida", "03", "02"), ("emitida", "04", "02"), ("recibida", "03", "02"), ("recibida", "08", "11"), ("recibida", "01", "  "), ("emitida", "01", "  ")]
    for i, (tipo, subtipo, impreso) in enumerate(casos):
        fid = fc.crear(t, u, c, _datos(tipo=tipo, numero=f"I{i}"), [{"base": "100", "pct_iva": "0" if subtipo != "01" else "21", "subtipo": subtipo}]); fc.cambiar_estado(t, u, fid, "revisada")
    detalles = _detalles(fc.exportar(t, u, c)["contenido"])
    assert [(d[99:101], d[172:174]) for d in detalles] == [(s, i) for _t, s, i in casos]


def test_el_criterio_de_caja_marca_la_posicion_177_solo_en_recibidas():
    t, u, c = _despacho()
    ids = [fc.crear(t, u, c, _datos(numero="C1", criterio_caja="1"), [LINEA]), fc.crear(t, u, c, _datos(numero="C2"), [LINEA]),
           fc.crear(t, u, c, _datos(numero="C3", tipo="emitida", criterio_caja="1"), [LINEA])]
    for fid in ids:
        fc.cambiar_estado(t, u, fid, "revisada")
    assert [d[176] for d in _detalles(fc.exportar(t, u, c)["contenido"])] == ["S", " ", " "]
    assert fc.obtener(t, u, ids[2])["criterio_caja"] == 0, "una emitida no guarda la marca"


def test_el_criterio_de_caja_se_conserva_al_editar():
    t, u, c = _despacho()
    fid = fc.crear(t, u, c, _datos(criterio_caja="1"), [LINEA])
    assert fc.obtener(t, u, fid)["criterio_caja"] == 1
    fc.actualizar(t, u, fid, _datos(criterio_caja="1"), [LINEA])
    assert fc.obtener(t, u, fid)["criterio_caja"] == 1
    fc.actualizar(t, u, fid, _datos(), [LINEA])
    assert fc.obtener(t, u, fid)["criterio_caja"] == 0
