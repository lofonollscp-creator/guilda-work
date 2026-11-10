"""D4 (el equipo ve el portal como lo ve el cliente, en solo lectura), E3 (buzón único de mensajes) y D2 (honorarios visibles con su estado y listado del año)."""
from datetime import datetime, timedelta

import pytest

from app import auditoria, db, facturas_contables as fc, facturas_portal, portal_buzon, portal_pagos, stripe_pagos, tareas_trabajo as tt, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_portal_conformidad_cola_cierre import _como_cliente


def _despacho(cliente, email):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant("Despacho " + email); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    verticales.fijar_activo(t, "fiscal", True)
    c = crear_cliente_fiscal(t, "Cliente Vista SL", nif="A12345674", email="vista@ejemplo.com")
    return uid, t, c


def _html(cliente, ruta):
    r = cliente.get(ruta)
    assert r.status_code == 200, ruta
    return r.get_data(as_text=True)


def _factura(c, numero="V-1"):
    return fc.crear_desde_portal(c, {"tipo": "recibida", "fecha": "2026-08-10", "numero": numero, "tercero_nombre": "Ferretería Paco", "tercero_nif": "B11111111", "total": "121,00", "pct_iva": "21"})


# --- D4: vista previa ----------------------------------------------------------------------------------------------------------------------------------

def test_el_equipo_abre_el_portal_del_cliente_en_solo_lectura(cliente):
    uid, t, c = _despacho(cliente, "vp1@ejemplo.com")
    r = cliente.post(f"/fiscal/clientes/{c}/ver-portal")
    assert r.status_code == 302 and r.headers["Location"].endswith("/portal/")
    inicio = _html(cliente, "/portal/")
    assert "Estás viendo el portal como lo ve Cliente Vista SL" in inicio and "Salir de la vista previa" in inicio and "portal-solo-lectura" in inicio
    assert 'action="/portal/salir"' in inicio and inicio.count("Salir</button>") == 0, "en la vista previa no hay «Salir» de cliente"
    assert {e["accion"] for e in auditoria.listar(t, entidad="cliente_fiscal", entidad_id=c)} >= {"portal.vista_previa"}
    f = _factura(c)
    assert cliente.post(f"/portal/facturas/{f}/mensajes", data={"texto": "hola"}).status_code == 403
    assert cliente.post("/portal/justificantes/tiquet", data={"fecha": "2026-08-10", "importe": "5", "concepto": "x"}).status_code == 403
    assert facturas_portal.mensajes(t, f) == []


def test_mirar_no_marca_como_leidos_los_mensajes_del_cliente(cliente):
    uid, t, c = _despacho(cliente, "vp2@ejemplo.com")
    f = _factura(c)
    facturas_portal.escribir_como_despacho(t, uid, f, "¿Puedes mandarme la original?")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20", usuario_id=uid)
    db.crear_mensaje_vencimiento(v, "empleado", "Falta el extracto", usuario_id=uid)
    cliente.post(f"/fiscal/clientes/{c}/ver-portal")
    _html(cliente, f"/portal/facturas/{f}")
    _html(cliente, f"/portal/vencimientos/{v}/mensajes")
    assert portal_buzon.sin_leer_total(db.obtener_cliente_fiscal_por_id(c)) == 2


def test_salir_de_la_vista_previa_vuelve_al_despacho_y_cierra_el_portal(cliente):
    uid, t, c = _despacho(cliente, "vp3@ejemplo.com")
    cliente.post(f"/fiscal/clientes/{c}/ver-portal")
    r = cliente.post("/portal/salir")
    assert r.status_code == 302 and r.headers["Location"].endswith("/fiscal/clientes")
    assert "/portal/entrar" in cliente.get("/portal/").headers["Location"]


def test_la_vista_previa_caduca_sola_y_no_deja_la_sesion_como_la_del_cliente(cliente):
    uid, t, c = _despacho(cliente, "vp4@ejemplo.com")
    cliente.post(f"/fiscal/clientes/{c}/ver-portal")
    with cliente.session_transaction() as s:
        s["portal_vista_previa"]["hasta"] = (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds")
        s.modified = True
    assert "/portal/entrar" in cliente.get("/portal/").headers["Location"]
    with cliente.session_transaction() as s:
        assert "portal_vista_previa" not in s and "cliente_fiscal_id" not in s


def test_solo_quien_ve_al_cliente_puede_abrir_su_portal(cliente):
    uid, t, c = _despacho(cliente, "vp5@ejemplo.com")
    ajeno = crear_cliente_fiscal(db.crear_tenant("Otro despacho"), "Ajeno SL", nif="B55555555", email="ajeno@ejemplo.com")
    assert cliente.post(f"/fiscal/clientes/{ajeno}/ver-portal").status_code == 404
    with cliente.session_transaction() as s:
        assert "portal_vista_previa" not in s and "cliente_fiscal_id" not in s


def test_un_cliente_de_verdad_sigue_pudiendo_escribir(cliente):
    uid, t, c = _despacho(cliente, "vp6@ejemplo.com")
    f = _factura(c)
    _como_cliente(cliente, c)
    assert "Estás viendo el portal" not in _html(cliente, "/portal/")
    assert cliente.post(f"/portal/facturas/{f}/mensajes", data={"texto": "hola"}).status_code == 302
    assert len(facturas_portal.mensajes(t, f)) == 1


def test_una_vista_previa_vieja_no_vale_para_otro_cliente(cliente):
    uid, t, c = _despacho(cliente, "vp7@ejemplo.com")
    otro = crear_cliente_fiscal(t, "Otro SL", nif="B87654321", email="otro-vp@ejemplo.com")
    cliente.post(f"/fiscal/clientes/{c}/ver-portal")
    with cliente.session_transaction() as s:
        s["cliente_fiscal_id"] = otro                           # la sesión ya no cuadra con la vista previa abierta
    assert "/portal/entrar" in cliente.get("/portal/").headers["Location"]


def test_los_botones_de_ver_su_portal_estan_en_la_lista_y_la_ficha(cliente):
    uid, t, c = _despacho(cliente, "vp8@ejemplo.com")
    assert f"/fiscal/clientes/{c}/ver-portal" in _html(cliente, "/fiscal/clientes") and f"/fiscal/clientes/{c}/ver-portal" in _html(cliente, f"/fiscal/clientes/{c}/editar")


# --- E3: buzón -----------------------------------------------------------------------------------------------------------------------------------------

def test_el_buzon_reune_modelos_facturas_y_trabajos(cliente, portal_antiguo):
    uid, t, c = _despacho(cliente, "bz1@ejemplo.com")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20", usuario_id=uid)
    interno = db.crear_vencimiento_fiscal(t, c, "NOMINAS", "2026-10", "2026-10-30", usuario_id=uid)
    f = _factura(c)
    db.crear_mensaje_vencimiento(v, "empleado", "¿Nos mandas el extracto?", usuario_id=uid)
    db.crear_mensaje_vencimiento(interno, "empleado", "interno no sale", usuario_id=uid)
    facturas_portal.escribir_como_cliente(c, f, "¿Os falta algo?")
    facturas_portal.escribir_como_despacho(t, uid, f, "Todo recibido")
    tarea = db.crear_tarea_outlook(uid, asunto="Alta censal", cliente_fiscal_id=c)
    tt.fijar_visible_cliente(uid, tarea, True, comentarios=True)
    tt.responder_al_cliente(uid, tarea, c, "Necesitamos tu DNI")
    _como_cliente(cliente, c)
    cli = db.obtener_cliente_fiscal_por_id(c)
    conv = portal_buzon.conversaciones(cli)
    assert {(x["tipo"], x["titulo"]) for x in conv} == {("modelo", "303 2026-T3"), ("factura", "V-1 Ferretería Paco"), ("tarea", "Alta censal")}
    por = {x["tipo"]: x for x in conv}
    assert por["modelo"]["sin_leer"] == 1 and por["factura"]["sin_leer"] == 1 and por["tarea"]["sin_leer"] == 0 and por["tarea"]["espera_respuesta"]
    assert portal_buzon.sin_leer_total(cli) == 2
    pagina = _html(cliente, "/portal/mensajes")
    assert "¿Nos mandas el extracto?" in pagina and "Todo recibido" in pagina and "Necesitamos tu DNI" in pagina and "interno no sale" not in pagina and "Espera tu respuesta" in pagina
    assert 'class="portal-nav"' in pagina and "/portal/mensajes" in pagina and 'title="Mensajes sin leer"' in pagina


def test_leer_un_hilo_apaga_su_aviso_en_el_buzon(cliente):
    uid, t, c = _despacho(cliente, "bz2@ejemplo.com")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20", usuario_id=uid)
    db.crear_mensaje_vencimiento(v, "empleado", "Mira esto", usuario_id=uid)
    _como_cliente(cliente, c)
    assert portal_buzon.sin_leer_total(db.obtener_cliente_fiscal_por_id(c)) == 1
    _html(cliente, f"/portal/vencimientos/{v}/mensajes")
    assert portal_buzon.sin_leer_total(db.obtener_cliente_fiscal_por_id(c)) == 0
    assert "Tú: " not in _html(cliente, "/portal/mensajes") and "Tu gestoría: Mira esto" in _html(cliente, "/portal/mensajes")


def test_el_buzon_es_solo_del_cliente_y_sin_el_modulo_no_hay_facturas(cliente):
    uid, t, c = _despacho(cliente, "bz3@ejemplo.com")
    otro = crear_cliente_fiscal(t, "Otro SL", nif="B87654321", email="otro-bz@ejemplo.com")
    f = fc.crear_desde_portal(otro, {"tipo": "recibida", "fecha": "2026-08-10", "numero": "AJ-1", "tercero_nombre": "Y", "tercero_nif": "B2", "total": "10", "pct_iva": "21"})
    facturas_portal.escribir_como_despacho(t, uid, f, "mensaje del otro")
    _como_cliente(cliente, c)
    assert "mensaje del otro" not in _html(cliente, "/portal/mensajes") and "Todavía no hay conversaciones" in _html(cliente, "/portal/mensajes")
    propia = _factura(c)
    facturas_portal.escribir_como_despacho(t, uid, propia, "mensaje propio")
    verticales.fijar_activo(t, "contabilizacion", False)
    assert "mensaje propio" not in _html(cliente, "/portal/mensajes")


# --- D2: honorarios -------------------------------------------------------------------------------------------------------------------------------------

def _con_honorarios(cliente, email, estado="confirmado", referencia=None):
    uid, t, c = _despacho(cliente, email)
    v = db.crear_vencimiento_fiscal(t, c, "303", "2T 2026", "2026-07-20", usuario_id=uid)
    conn = db.get_connection()
    conn.execute("INSERT INTO honorarios_aplicados (tenant_id, vencimiento_id, cliente_fiscal_id, regla_nombre, concepto, importe_centimos, estado, referencia_factura, confirmado_en) VALUES (?, ?, ?, 'Fija', 'Honorarios 303 2T 2026', 4500, ?, ?, ?)",
                 (t, v, c, estado, referencia, db.now_iso()))
    conn.execute("UPDATE clientes_fiscales SET portal_honorarios = 1 WHERE id = ?", (c,))
    conn.commit(); conn.close()
    return uid, t, c, v


def test_el_cliente_ve_si_los_honorarios_estan_confirmados_o_facturados(cliente, monkeypatch):
    monkeypatch.setattr(stripe_pagos, "configurado", lambda: False)
    uid, t, c, v = _con_honorarios(cliente, "hon1@ejemplo.com")
    _como_cliente(cliente, c)
    assert "Confirmados por tu gestoría" in _html(cliente, "/portal/impuestos")
    conn = db.get_connection(); conn.execute("UPDATE honorarios_aplicados SET estado = 'facturado', referencia_factura = 'F-2026-31' WHERE vencimiento_id = ?", (v,)); conn.commit(); conn.close()
    pagina = _html(cliente, "/portal/impuestos")
    assert "Facturados" in pagina and "F-2026-31" in pagina


def test_la_carpeta_lista_los_honorarios_del_año(cliente, monkeypatch):
    monkeypatch.setattr(stripe_pagos, "configurado", lambda: False)
    uid, t, c, v = _con_honorarios(cliente, "hon2@ejemplo.com", estado="facturado", referencia="F-1")
    _como_cliente(cliente, c)
    pagina = _html(cliente, "/portal/carpeta?anio=2026")
    assert "Honorarios de 2026" in pagina and "45.00 €" in pagina and "Facturado · F-1" in pagina
    db.registrar_pago_vencimiento(v, "cs_h2", 4500)
    assert "Pagado" in _html(cliente, "/portal/carpeta?anio=2026")
    assert portal_pagos.del_anio(db.obtener_cliente_fiscal_por_id(c), 2025) == []


def test_sin_activarlo_el_cliente_no_ve_honorarios_en_ninguna_pantalla(cliente, monkeypatch):
    monkeypatch.setattr(stripe_pagos, "configurado", lambda: False)
    uid, t, c, v = _con_honorarios(cliente, "hon3@ejemplo.com")
    conn = db.get_connection(); conn.execute("UPDATE clientes_fiscales SET portal_honorarios = 0 WHERE id = ?", (c,)); conn.commit(); conn.close()
    _como_cliente(cliente, c)
    assert "Honorarios" not in _html(cliente, "/portal/impuestos") and "Honorarios de" not in _html(cliente, "/portal/carpeta?anio=2026")
