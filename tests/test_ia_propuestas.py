"""Bandeja de propuestas (W3): proponer sin repetir, aprobar ejecuta una sola vez, rechazar silencia, y las alertas de clientes llegan solas."""
from datetime import date, timedelta

import pytest

from app import db, ia_propuestas as ip


def _eq(n=1):
    t = db.crear_tenant(f"Propuestas {n}")
    u = db.crear_usuario_vinculado_a_kratos(f"prop{n}@ejemplo.com", f"k-prop{n}")
    db.asignar_tenant(u, t)
    return t, u, db.crear_cliente_fiscal(t, f"Cliente {n} SL", email=f"c{n}@ejemplo.com")


def _p(t, c, clave="x:1", **kw):
    return ip.proponer(t, clave=clave, tipo="tarea", titulo="Revisar el 303 de Cliente", detalle="Faltan facturas", origen="prueba", cliente_fiscal_id=c, **kw)


def test_una_propuesta_igual_no_se_repite_mientras_este_pendiente():
    t, u, c = _eq()
    assert _p(t, c) is not None and _p(t, c) is None
    assert [p["clave"] for p in ip.pendientes(t)] == ["x:1"] and ip.contar(t) == 1
    assert _p(t, c, clave="x:2") is not None


def test_aprobar_crea_la_tarea_a_nombre_de_quien_aprueba_y_solo_una_vez():
    t, u, c = _eq(2)
    pid = _p(t, c, prioridad="alta")
    resultado = ip.aprobar(t, u, pid)
    assert resultado.startswith("tarea:")
    conn = db.get_connection()
    fila = conn.execute("SELECT usuario_id, asunto, prioridad, cliente_fiscal_id FROM tareas_outlook WHERE asunto = 'Revisar el 303 de Cliente'").fetchall()
    conn.close()
    assert len(fila) == 1 and fila[0]["usuario_id"] == u and fila[0]["prioridad"] == "alta" and fila[0]["cliente_fiscal_id"] == c
    with pytest.raises(ip.ErrorPropuesta):
        ip.aprobar(t, u, pid)                                                          # ya resuelta: no se ejecuta otra vez
    assert ip.obtener(t, pid)["estado"] == "aprobada" and ip.obtener(t, pid)["resuelta_por"] == u and ip.contar(t) == 0


def test_rechazar_silencia_la_misma_propuesta_durante_un_mes():
    t, u, c = _eq(3)
    pid = _p(t, c)
    ip.rechazar(t, u, pid)
    assert ip.obtener(t, pid)["estado"] == "rechazada" and _p(t, c) is None             # la bandeja aprende: no insiste
    conn = db.get_connection()
    conn.execute("UPDATE ia_propuestas SET creada_en = ? WHERE id = ?", ((date.today() - timedelta(days=45)).isoformat() + "T10:00:00", pid))
    conn.commit(); conn.close()
    assert _p(t, c) is not None                                                         # pasado el mes, vuelve a poder proponerse
    with pytest.raises(ip.ErrorPropuesta):
        ip.rechazar(t, u, pid)


def test_un_fallo_al_ejecutar_deja_la_propuesta_pendiente(monkeypatch):
    t, u, c = _eq(4)
    pid = _p(t, c)
    monkeypatch.setitem(ip.MANEJADORES, "tarea", lambda p, uid: (_ for _ in ()).throw(RuntimeError("no se pudo")))
    with pytest.raises(RuntimeError):
        ip.aprobar(t, u, pid)
    assert ip.obtener(t, pid)["estado"] == "pendiente"                                  # se puede volver a intentar


def test_cada_despacho_solo_ve_las_suyas_y_un_tipo_desconocido_se_rechaza():
    t1, u1, c1 = _eq(5)
    t2, u2, c2 = _eq(6)
    pid = _p(t1, c1)
    assert ip.pendientes(t2) == [] and ip.obtener(t2, pid) is None
    with pytest.raises(ip.ErrorPropuesta):
        ip.aprobar(t2, u2, pid)
    with pytest.raises(ip.ErrorPropuesta):
        ip.proponer(t1, clave="z", tipo="inventado", titulo="x")


def test_las_alertas_de_clientes_llegan_a_la_bandeja_una_sola_vez():
    t, u, c = _eq(7)
    db.crear_vencimiento_fiscal(t, c, "303", "3T", (date.today() - timedelta(days=2)).isoformat())
    assert ip.generar_desde_alertas(t) == 1 and ip.generar_desde_alertas(t) == 0
    p = ip.pendientes(t)[0]
    assert p["origen"] == "alerta" and p["prioridad"] == "alta" and p["titulo"] == "Modelo 303 de Cliente 7 SL sin presentar" and p["cliente_fiscal_id"] == c


def test_la_pantalla_recoge_las_alertas_y_permite_aprobar_y_rechazar(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    t = db.crear_tenant("Propuestas web")
    u = iniciar_sesion_de_prueba(cliente, "propuestas-web@ejemplo.com", "contrasena123")
    db.asignar_tenant(u, t)
    c = db.crear_cliente_fiscal(t, "Cliente Web SL", email="w@ejemplo.com")
    db.crear_vencimiento_fiscal(t, c, "303", "3T", (date.today() - timedelta(days=2)).isoformat())
    db.crear_vencimiento_fiscal(t, c, "111", "3T", (date.today() - timedelta(days=3)).isoformat())
    html = cliente.get("/ia/propuestas").get_data(as_text=True)
    assert "Modelo 303 de Cliente Web SL sin presentar" in html and "Modelo 111 de Cliente Web SL sin presentar" in html
    pendientes = ip.pendientes(t)
    r = cliente.post(f"/ia/propuestas/{pendientes[0]['id']}/aprobar")
    assert r.status_code == 302 and "aviso=aprobada" in r.headers["Location"]
    r = cliente.post(f"/ia/propuestas/{pendientes[1]['id']}/rechazar")
    assert "aviso=rechazada" in r.headers["Location"]
    html = cliente.get("/ia/propuestas").get_data(as_text=True)
    assert "No hay propuestas pendientes." in html and "Aprobada" in html and "Rechazada" in html            # y al reabrirla no reaparecen
    assert "error=" in cliente.post(f"/ia/propuestas/{pendientes[0]['id']}/aprobar").headers["Location"]       # ya resuelta
    assert cliente.post("/ia/propuestas/1/otra").status_code == 404


def test_pedir_documentacion_y_escribir_al_cliente_por_el_portal_solo_al_aprobar():
    from app import portal_conversaciones, portal_peticiones
    t, u, c = _eq(8)
    ficha = db.obtener_cliente_fiscal_por_id(c)
    p1 = ip.proponer(t, clave="doc:1", tipo="peticion_portal", titulo="Extracto del banco", detalle="Del tercer trimestre, en PDF", cliente_fiscal_id=c, datos={"titulo": "Extracto del banco del 3T", "descripcion": "En PDF"})
    p2 = ip.proponer(t, clave="msg:1", tipo="mensaje_portal", titulo="Falta una factura", cliente_fiscal_id=c, datos={"asunto": "Falta una factura de septiembre", "texto": "Hola, no nos consta la factura de septiembre. ¿Nos la mandas?"})
    assert portal_peticiones.listar(ficha) == [] and portal_conversaciones.listar(ficha) == []                          # proponer no manda nada al cliente
    assert ip.aprobar(t, u, p1).startswith("peticion:") and ip.aprobar(t, u, p2).startswith("hilo:")
    assert [x["titulo"] for x in portal_peticiones.listar(ficha)] == ["Extracto del banco del 3T"]
    hilos = portal_conversaciones.listar(ficha)
    assert len(hilos) == 1 and hilos[0]["asunto"] == "Falta una factura de septiembre"


def test_un_cliente_borrado_o_de_otro_despacho_no_recibe_nada():
    t, u, c = _eq(9)
    t2, u2, c2 = _eq(10)
    pid = ip.proponer(t, clave="msg:x", tipo="mensaje_portal", titulo="Hola", cliente_fiscal_id=c2, datos={"asunto": "Hola", "texto": "texto"})       # cliente de otro despacho
    with pytest.raises(ip.ErrorPropuesta):
        ip.aprobar(t, u, pid)
    assert ip.obtener(t, pid)["estado"] == "pendiente"


def test_la_subcuenta_del_plan_de_a3_se_propone_y_se_fija_al_aprobar():
    from app import facturas_contables as fc, verticales
    t, u, c = _eq(11)
    verticales.fijar_activo(t, "contabilizacion", True)
    fc.crear_desde_portal(c, {"tipo": "recibida", "fecha": date.today().isoformat(), "numero": "P-1", "tercero_nombre": "Ferretería Paco", "tercero_nif": "B11111111", "total": "121,00", "pct_iva": "21"})
    cuenta = "4000".ljust(fc.configuracion(t, c)["digitos"] - 1, "0") + "1"                       # con los dígitos que usa este cliente
    assert ip.generar_cuentas_de_terceros(t) == 0                                                    # sin la cuenta en el plan no hay nada que proponer
    conn = db.get_connection()
    conn.execute("INSERT INTO contabilidad_plan (tenant_id, cliente_fiscal_id, cuenta, nombre, tipo, nif, importado_en) VALUES (?, ?, ?, 'FERRETERIA PACO', 'proveedor', 'B11111111', '2026-11-01T10:00:00')", (t, c, cuenta))
    conn.commit(); conn.close()
    assert ip.generar_cuentas_de_terceros(t) == 1 and ip.generar_cuentas_de_terceros(t) == 0
    p = ip.pendientes(t)[0]
    assert p["tipo"] == "cuenta_tercero" and p["datos"]["cuenta"] == cuenta and "Ferretería Paco" in p["titulo"]
    ip.aprobar(t, u, p["id"])
    assert fc.cuenta_del_tercero(t, c, "recibida", "B11111111") == cuenta
