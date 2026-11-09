"""Adopción del portal para el despacho (E1) y embudo de uso opcional (E2)."""
from datetime import date, datetime, timedelta

from app import db, portal_adopcion as pa, portal_conversaciones as pc
from app.db_fiscal import crear_cliente_fiscal
from tests.test_facturas_contables import _web
from tests.test_portal_personas_avisos import _despacho


def _sesion(t, c, email, hace_dias):
    ahora = (datetime.now() - timedelta(days=hace_dias)).isoformat(timespec="seconds")
    conn = db.get_connection()
    conn.execute("INSERT INTO portal_sesiones (tenant_id, cliente_fiscal_id, email, sid_hash, dispositivo, ip, creado_en, ultimo_uso_en) VALUES (?, ?, ?, ?, 'Chrome', '1.0.0.0', ?, ?)", (t, c, email, f"h{c}{hace_dias}", ahora, ahora))
    conn.commit(); conn.close()


def _escenario():
    t, u, c_activo = _despacho("Adopcion", cliente_email="activo@ejemplo.com", cliente_nombre="Activo SL")
    c_inactivo = crear_cliente_fiscal(t, "Inactivo SL", nif="B87654323", email="inactivo@ejemplo.com")
    c_nunca = crear_cliente_fiscal(t, "Nunca SL", nif="A11111119", email="nunca@ejemplo.com")
    c_sin = crear_cliente_fiscal(t, "Sin correo SL", nif="B12345678")
    _sesion(t, c_activo, "activo@ejemplo.com", 2)
    _sesion(t, c_inactivo, "inactivo@ejemplo.com", 60)
    return t, u, c_activo, c_inactivo, c_nunca, c_sin


def test_cada_cliente_cae_en_su_estado_y_el_embudo_cuenta_pasos_sin_nombres():
    t, u, a, i, n, s = _escenario()
    pc.iniciar(db.obtener_cliente_fiscal_por_id(a), "Duda", "Hola", "cliente", "activo@ejemplo.com")
    r = pa.resumen(t)
    estados = {f["nombre"]: f["estado"] for f in r["clientes"]}
    assert estados == {"Activo SL": "activo", "Inactivo SL": "inactivo", "Nunca SL": "nunca", "Sin correo SL": "sin_correo"}
    assert r["cuentas"] == {"sin_correo": 1, "nunca": 1, "inactivo": 1, "activo": 1}
    assert r["embudo"] == {"con_acceso": 3, "han_entrado": 2, "activos": 1, "han_subido": 0, "han_escrito": 1}


def test_los_clientes_de_otro_despacho_no_cuentan():
    t, u, *_ = _escenario()
    t2, u2, c2 = _despacho("Adopcion otro", cliente_email="otro@ejemplo.com", cliente_nombre="Otro SL")
    assert [f["nombre"] for f in pa.resumen(t2)["clientes"]] == ["Otro SL"] and all(f["nombre"] != "Otro SL" for f in pa.resumen(t)["clientes"])


def test_el_embudo_esta_apagado_por_defecto_y_se_enciende_y_apaga(cliente):
    uid, t, c = _web(cliente, email="adopcion@ejemplo.com")
    assert pa.embudo_activo(t) is False
    html = cliente.get("/fiscal/portal-adopcion").get_data(as_text=True)
    assert "Adopción del portal" in html and "Embudo de uso" in html and 'class="portal-embudo"' not in html
    cliente.post("/fiscal/portal-adopcion/embudo", data={"activo": "1"})
    assert pa.embudo_activo(t) is True and 'class="portal-embudo"' in cliente.get("/fiscal/portal-adopcion").get_data(as_text=True)
    cliente.post("/fiscal/portal-adopcion/embudo", data={})
    assert pa.embudo_activo(t) is False


def test_reenviar_la_invitacion_manda_un_enlace_nuevo_y_solo_de_su_despacho(cliente, monkeypatch):
    from app import notificaciones_email as ne
    uid, t, c = _web(cliente, email="adopcion2@ejemplo.com")
    destino = crear_cliente_fiscal(t, "Nunca SL", nif="A11111119", email="nunca@ejemplo.com")
    enviados = []
    monkeypatch.setattr(ne, "enviar_enlace_portal", lambda email, enlace, tenant_id=None: enviados.append((email, enlace, tenant_id)))
    r = cliente.post(f"/fiscal/portal-adopcion/{destino}/invitar")
    assert r.status_code == 302 and enviados and enviados[0][0] == "nunca@ejemplo.com" and "/portal/entrar/" in enviados[0][1] and enviados[0][2] == t
    _, _, ajeno = _despacho("Adopcion ajeno", cliente_email="x@ejemplo.com")
    assert cliente.post(f"/fiscal/portal-adopcion/{ajeno}/invitar").status_code == 404
    from app import portal_invitaciones as pi
    cliente.post("/fiscal/portal-adopcion/invitar-pendientes")
    assert pi.pendientes(t) == 1                                                                  # el reenvío masivo se pone en cola: sale escalonado
