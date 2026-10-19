"""Ajustes de la conexión con a3 (facturas_contables: valores del despacho, códigos de empresa de muchos clientes, copiar ajustes; /contabilidad/ajustes)."""
import pytest

from app import db, facturas_contables as fc, nucleo, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_facturas_contables import LINEA, _datos


def _despacho(n=3):
    t = db.crear_tenant("Despacho ajustes")
    u = db.crear_usuario_vinculado_a_kratos("ajustes1@ejemplo.com", "k-ajustes1"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    cs = [crear_cliente_fiscal(t, f"Cliente {i}", nif=nif) for i, nif in enumerate(("B12345678", "B87654321", "12345678Z"), start=1)][:n]
    return t, u, cs


def test_un_cliente_sin_ajustes_propios_hereda_los_del_despacho():
    t, u, (c1, c2, _c3) = _despacho()
    assert fc.configuracion(t, c1)["digitos"] == 8 and fc.configuracion_despacho(t)["cuenta_proveedores"] == "40000000"
    fc.guardar_configuracion_despacho(t, u, {"digitos": "10", "cuenta_proveedores": "4000000000", "cuenta_clientes": "4300000000", "subcuentas_auto": "1"})
    c = fc.configuracion(t, c1)
    assert (c["digitos"], c["cuenta_proveedores"], c["subcuentas_auto"], c["a3_empresa"]) == (10, "4000000000", 1, None)
    fc.guardar_configuracion(t, u, c2, {"a3_empresa": "7", "digitos": "8"})
    fc.guardar_configuracion_despacho(t, u, {"digitos": "9", "cuenta_proveedores": "400000000", "cuenta_clientes": "430000000"})
    assert fc.configuracion(t, c2)["digitos"] == 8, "el que tiene los suyos no cambia"
    assert fc.configuracion(t, c1)["digitos"] == 9 and fc.configuracion(t, c1)["subcuentas_auto"] == 0


def test_el_fichero_usa_las_cuentas_del_despacho_si_el_cliente_no_tiene_las_suyas():
    t, u, (c1, *_r) = _despacho()
    fc.guardar_configuracion_despacho(t, u, {"digitos": "8", "cuenta_proveedores": "41000000", "cuenta_clientes": "43000000", "cuenta_gasto": "60000000"})
    fc.guardar_codigos(t, u, {c1: "5"})
    fid = fc.crear(t, u, c1, _datos(), [LINEA]); fc.cambiar_estado(t, u, fid, "revisada")
    lineas = fc.exportar(t, u, c1)["contenido"].decode("latin-1").split("\r\n")
    assert lineas[0][15:27] == "410000000000" and lineas[1][15:27] == "600000000000"


@pytest.mark.parametrize("datos,fragmento", [({"digitos": "x"}, "número"), ({"digitos": "3"}, "entre 4 y 12"), ({"digitos": "13"}, "entre 4 y 12"), ({"cuenta_gasto": "12"}, "Cuenta de gasto")])
def test_los_valores_del_despacho_se_validan(datos, fragmento):
    t, u, _cs = _despacho()
    with pytest.raises(ValueError, match=fragmento):
        fc.guardar_configuracion_despacho(t, u, datos)
    assert fc.configuracion_despacho(t)["digitos"] == 8


def test_copiar_ajustes_conserva_el_codigo_y_restablecer_vuelve_al_despacho():
    t, u, (c1, c2, _c3) = _despacho()
    fc.guardar_configuracion(t, u, c1, {"a3_empresa": "11", "digitos": "10", "cuenta_proveedores": "4000000000", "cuenta_clientes": "4300000000", "subcuentas_auto": "1"})
    fc.guardar_configuracion(t, u, c2, {"a3_empresa": "22", "digitos": "8"})
    r = fc.copiar_configuracion(t, u, c1, c2)
    assert (r["a3_empresa"], r["digitos"], r["cuenta_proveedores"], r["subcuentas_auto"]) == ("22", 10, "4000000000", 1)
    r = fc.restablecer_configuracion(t, u, c2)
    assert (r["a3_empresa"], r["digitos"], r["subcuentas_auto"]) == ("22", 8, 0)
    por = {c["id"]: c for c in fc.resumen_clientes(t, u)}
    assert por[c1]["propia"] is True and por[c2]["propia"] is False


def test_guardar_codigos_es_todo_o_nada_y_vacio_lo_quita():
    t, u, (c1, c2, _c3) = _despacho()
    assert fc.guardar_codigos(t, u, {c1: "00123", c2: "45"}) == 2
    assert fc.configuracion(t, c1)["a3_empresa"] == "00123"
    assert fc.guardar_codigos(t, u, {c1: "00123", c2: "45"}) == 0, "sin cambios"
    with pytest.raises(ValueError, match="no es válido"):
        fc.guardar_codigos(t, u, {c1: "1", c2: "123456"})
    assert fc.configuracion(t, c1)["a3_empresa"] == "00123", "no se guardó ninguno"
    assert fc.guardar_codigos(t, u, {c1: ""}) == 1 and fc.configuracion(t, c1)["a3_empresa"] is None


def test_un_codigo_vacio_para_un_cliente_sin_ajustes_no_crea_nada():
    t, u, (c1, *_r) = _despacho()
    assert fc.guardar_codigos(t, u, {c1: ""}) == 0
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM contabilidad_clientes WHERE tenant_id = ?", (t,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_los_codigos_pegados_se_asignan_por_nif_aunque_se_escriba_distinto():
    t, u, (c1, c2, c3) = _despacho()
    texto = "b-12345678;101\n b87654321 , 102\n12345678z\t103\n\nZ9999999Z;5\nB12345678 abc\nsolo\n"
    r = fc.codigos_desde_texto(t, u, texto)
    assert r["aplicados"] == 3 and r["no_encontrados"] == ["Z9999999Z"] and len(r["invalidos"]) == 2
    assert [fc.configuracion(t, c)["a3_empresa"] for c in (c1, c2, c3)] == ["101", "102", "103"]


def test_solo_se_toca_a_los_clientes_del_propio_despacho():
    t, u, (c1, *_r) = _despacho()
    t2 = db.crear_tenant("Otro despacho ajustes")
    ajeno = crear_cliente_fiscal(t2, "Ajeno", nif="B99999999")
    with pytest.raises(ValueError, match="no encontrado"):
        fc.guardar_codigos(t, u, {ajeno: "5"})
    assert fc.codigos_desde_texto(t, u, "B99999999;5") == {"aplicados": 0, "no_encontrados": ["B99999999"], "invalidos": []}
    with pytest.raises(ValueError, match="no encontrado"):
        fc.copiar_configuracion(t, u, c1, ajeno)


def test_el_resumen_cuenta_las_facturas_que_esperan():
    t, u, (c1, c2, _c3) = _despacho()
    fc.guardar_codigos(t, u, {c1: "1"})
    fc.crear(t, u, c1, _datos(), [LINEA]); f2 = fc.crear(t, u, c1, _datos(numero="F-2"), [LINEA]); fc.cambiar_estado(t, u, f2, "descartada")
    por = {c["id"]: c for c in fc.resumen_clientes(t, u)}
    assert por[c1]["esperando"] == 1 and por[c1]["a3_empresa"] == "1" and por[c2]["a3_empresa"] is None


def test_borrar_el_despacho_borra_sus_valores_por_defecto():
    t, u, _cs = _despacho()
    fc.guardar_configuracion_despacho(t, u, {"digitos": "9", "cuenta_proveedores": "400000000", "cuenta_clientes": "430000000"})
    conn = db.get_connection()
    try:
        fc.borrar_datos_de_tenant(conn, t); conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM contabilidad_despacho WHERE tenant_id = ?", (t,)).fetchone()[0] == 0
    finally:
        conn.close()


def _web(cliente, email, supervisor=True):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant("Despacho " + email); db.asignar_tenant(uid, t)
    if supervisor:
        db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    return uid, t


def test_la_pagina_de_ajustes_guarda_los_valores_los_codigos_y_los_pegados(cliente):
    uid, t = _web(cliente, "ajustesweb@ejemplo.com")
    c1 = crear_cliente_fiscal(t, "Cliente <b>Web</b>", nif="B12345678"); c2 = crear_cliente_fiscal(t, "Otro Cliente", nif="B87654321")
    html = cliente.get("/contabilidad/ajustes").get_data(as_text=True)
    assert "Ajustes de a3" in html and "0 / 2" in html and "<b>Web</b>" not in html and "Ajustes de a3" in cliente.get("/contabilidad/").get_data(as_text=True)
    r = cliente.post("/contabilidad/ajustes", data={"accion": "despacho", "digitos": "9", "cuenta_proveedores": "400000000", "cuenta_clientes": "430000000"})
    assert "Valores del despacho guardados" in r.get_data(as_text=True) and fc.configuracion_despacho(t)["digitos"] == 9
    r = cliente.post("/contabilidad/ajustes", data={"accion": "despacho", "digitos": "2"})
    assert "entre 4 y 12" in r.get_data(as_text=True) and fc.configuracion_despacho(t)["digitos"] == 9
    r = cliente.post("/contabilidad/ajustes", data={"accion": "codigos", f"codigo_{c1}": "77", f"codigo_{c2}": ""})
    assert "1 cambios" in r.get_data(as_text=True) and fc.configuracion(t, c1)["a3_empresa"] == "77" and "1 / 2" in r.get_data(as_text=True)
    r = cliente.post("/contabilidad/ajustes", data={"accion": "texto", "texto": "B87654321;88\nX1;1"})
    assert "Códigos aplicados: 1" in r.get_data(as_text=True) and "X1" in r.get_data(as_text=True) and fc.configuracion(t, c2)["a3_empresa"] == "88"
    r = cliente.post("/contabilidad/ajustes", data={"accion": "codigos", f"codigo_{c1}": "123456"})
    assert "no es válido" in r.get_data(as_text=True) and fc.configuracion(t, c1)["a3_empresa"] == "77"


def test_quien_no_es_direccion_no_cambia_los_valores_del_despacho_pero_si_los_codigos(cliente):
    uid, t = _web(cliente, "ajustesnosup@ejemplo.com", supervisor=False)
    c1 = crear_cliente_fiscal(t, "Cliente", nif="B12345678")
    from app import acceso
    if acceso.clientes_visibles(t, uid) is not None and c1 not in acceso.clientes_visibles(t, uid):
        pytest.skip("este usuario no ve el cliente")
    assert cliente.post("/contabilidad/ajustes", data={"accion": "despacho", "digitos": "9"}).status_code == 403
    assert fc.configuracion_despacho(t)["digitos"] == 8
    assert cliente.post("/contabilidad/ajustes", data={"accion": "codigos", f"codigo_{c1}": "5"}).status_code == 200


def test_la_configuracion_del_cliente_permite_copiar_y_usar_los_valores_del_despacho(cliente):
    uid, t = _web(cliente, "ajustescopia@ejemplo.com")
    c1 = crear_cliente_fiscal(t, "Con ajustes", nif="B12345678"); c2 = crear_cliente_fiscal(t, "Destino", nif="B87654321")
    fc.guardar_configuracion(t, uid, c1, {"a3_empresa": "1", "digitos": "10", "cuenta_proveedores": "4000000000", "cuenta_clientes": "4300000000"})
    fc.guardar_codigos(t, uid, {c2: "2"})
    html = cliente.get(f"/contabilidad/cliente/{c2}/configuracion").get_data(as_text=True)
    assert "Copiar de Con ajustes" in html and "Usar los valores del despacho" in html
    assert cliente.post(f"/contabilidad/cliente/{c2}/copiar-configuracion", data={"origen": str(c1)}).status_code == 302
    assert fc.configuracion(t, c2)["digitos"] == 10 and fc.configuracion(t, c2)["a3_empresa"] == "2"
    assert cliente.post(f"/contabilidad/cliente/{c2}/copiar-configuracion", data={"origen": "despacho"}).status_code == 302
    assert fc.configuracion(t, c2)["digitos"] == 8
