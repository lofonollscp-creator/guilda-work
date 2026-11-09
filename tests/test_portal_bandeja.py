"""Bandeja del portal para el equipo (C4): todo lo que esperan los clientes, por orden de espera y con filtros."""
from datetime import datetime, timedelta

from app import db, portal_bandeja as pb, portal_citas, portal_conversaciones as pc, portal_cuestionarios, portal_peticiones, portal_dossier
from app.db_fiscal import crear_cliente_fiscal
from tests.test_facturas_contables import _web


def _lista(cliente, *args, **kw):
    with cliente.application.test_request_context():
        return pb.listar(*args, **kw)


def _escenario():
    from tests.test_portal_personas_avisos import _despacho
    t, u, c = _despacho("Bandeja", cliente_email="uno@ejemplo.com", cliente_nombre="Uno SL")
    ficha = db.obtener_cliente_fiscal_por_id(c)
    c2 = crear_cliente_fiscal(t, "Dos SL", nif="B87654323", email="dos@ejemplo.com")
    return t, u, c, ficha, c2, db.obtener_cliente_fiscal_por_id(c2)


def test_recoge_cada_cosa_pendiente_y_las_ordena_por_antiguedad(cliente):
    t, u, c, f1, c2, f2 = _escenario()
    hace = lambda d: (datetime.now() - timedelta(days=d)).isoformat(timespec="seconds")
    pc.iniciar(f1, "Una duda", "Hola", "cliente", "uno@ejemplo.com")
    pc.iniciar(f1, "Solicitud: Copia de un modelo presentado", "Modelo: 303", "cliente", "uno@ejemplo.com")
    pc.iniciar(f2, "Ya contestado", "x", "despacho", "eq@d.com")                               # lo inició la gestoría: no espera nada
    pid = portal_peticiones.crear(f2, "Extracto", por=u)
    cita = portal_citas.solicitar(f2, "dos@ejemplo.com", "llamada", "Revisar el cierre")
    conn = db.get_connection()
    conn.execute("UPDATE portal_peticiones SET estado = 'enviada', enviada_en = ? WHERE id = ?", (hace(5), pid))
    conn.execute("UPDATE portal_citas SET creado_en = ? WHERE id = ?", (hace(2), cita))
    conn.commit(); conn.close()
    items = _lista(cliente, t, u)
    assert [i["tipo"] for i in items][0] == "documentos" and items[0]["dias"] == 5 and items[0]["cliente"] == "Dos SL"
    tipos = {i["tipo"] for i in items}
    assert tipos == {"documentos", "cita", "mensaje", "solicitud"} and pb.cuentas(items)["solicitud"] == 1
    sol = next(i for i in items if i["tipo"] == "solicitud")
    assert sol["titulo"] == "Copia de un modelo presentado" and f"#conversacion-" in sol["url"]
    assert all(i["desde"] for i in items) and [i["desde"] for i in items] == sorted(i["desde"] for i in items)


def test_filtra_por_tipo_y_por_mis_clientes_y_no_enseña_lo_ya_atendido(cliente):
    t, u, c, f1, c2, f2 = _escenario()
    conn = db.get_connection(); conn.execute("UPDATE clientes_fiscales SET responsable_id = ? WHERE id = ?", (u, c)); conn.commit(); conn.close()
    cid = pc.iniciar(f1, "De Uno", "Hola", "cliente", "uno@ejemplo.com")
    pc.iniciar(f2, "De Dos", "Hola", "cliente", "dos@ejemplo.com")
    assert len(_lista(cliente, t, u)) == 2 and [i["cliente"] for i in _lista(cliente, t, u, solo_mios=True)] == ["Uno SL"] and _lista(cliente, t, u, tipo="cita") == []
    pc.marcar_leida(f1, cid, "despacho")                                                          # el equipo lo abre: ya no espera
    assert [i["cliente"] for i in _lista(cliente, t, u)] == ["Dos SL"]
    pc.cambiar_estado(f2, pc.listar(f2)[0]["id"], abierta=False)
    assert _lista(cliente, t, u) == []


def test_cuestionarios_y_dossiers_pendientes_entran_en_la_bandeja(cliente):
    t, u, c, f1, c2, f2 = _escenario()
    q = portal_cuestionarios.crear(f1, "Datos del trimestre", portal_cuestionarios.preguntas_desde_texto("¿Algo nuevo?"), por=u)
    portal_cuestionarios.responder(f1, q, {"p1": "No"}, "uno@ejemplo.com") if False else None
    conn = db.get_connection(); conn.execute("UPDATE portal_cuestionarios SET estado = 'respondido', respondido_en = ? WHERE id = ?", (datetime.now().isoformat(timespec="seconds"), q)); conn.commit(); conn.close()
    conn = db.get_connection()
    conn.execute("INSERT INTO portal_dossiers (tenant_id, cliente_fiscal_id, desde, hasta, creado_en, datos, huella, estado, pedido_en) VALUES (?, ?, '2026-01-01', '2026-06-30', ?, '{}', 'x', 'pendiente', ?)", (t, c2, datetime.now().isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds")))
    conn.commit(); conn.close()
    assert {i["tipo"] for i in _lista(cliente, t, u)} == {"cuestionario", "dossier"}


def test_la_pagina_lista_filtra_y_dice_cuando_no_hay_nada(cliente):
    uid, t, c = _web(cliente, email="bandeja-web@ejemplo.com")
    assert "No hay nada esperando" in cliente.get("/fiscal/bandeja-portal").get_data(as_text=True)
    pc.iniciar(db.obtener_cliente_fiscal_por_id(c), "Necesito ayuda urgente", "Hola", "cliente", "x@ejemplo.com")
    html = cliente.get("/fiscal/bandeja-portal").get_data(as_text=True)
    assert "Necesito ayuda urgente" in html and "Mensajes (1)" in html and "Todo (1)" in html
    assert "Necesito ayuda urgente" not in cliente.get("/fiscal/bandeja-portal?tipo=cita").get_data(as_text=True) and "Necesito ayuda urgente" in cliente.get("/fiscal/bandeja-portal?tipo=mensaje&mios=0").get_data(as_text=True)
