"""AC6: buzón de facturas por correo, solo en los clientes que el despacho active."""
import pytest

from app import db, db_correo, facturas_contables as fc, facturas_correo as fcor, ia_trabajos as tr, lectura_facturas as lf
from tests.test_facturas_contables import PDF, _despacho, _web

DOMINIO = "facturas@despacho.example"


def _mensaje(cuenta, uid, remitente, destino, adjuntos, cc=""):
    mid = db_correo.guardar_mensaje_correo(cuenta, uid, "Mis facturas", remitente, destino, db.now_iso(), "adjunto", None, cc=cc)
    db_correo.guardar_adjuntos_correo(mid, [{"nombre": n, "tipo": t, "bytes": b} for n, t, b in adjuntos])
    return mid


@pytest.fixture
def buzon(monkeypatch):
    tr._pausas.clear()
    monkeypatch.setattr(lf, "configurada", lambda x: False)
    t, u, c = _despacho()
    cuenta = db.crear_cuenta_correo(u, "Buzón facturas", "imap", "imap.example", 993, "facturas@despacho.example")
    fcor.guardar_config(t, u, cuenta, DOMINIO)
    return t, u, c, cuenta


def test_configurar_exige_cuenta_propia_y_direccion_sin_mas():
    t, u, c = _despacho()
    cuenta = db.crear_cuenta_correo(u, "B", "imap", "h", 993, "facturas@despacho.example")
    with pytest.raises(ValueError):
        fcor.guardar_config(t, u, cuenta, "")
    with pytest.raises(ValueError):
        fcor.guardar_config(t, u, cuenta, "facturas+x@despacho.example")
    with pytest.raises(ValueError):
        fcor.guardar_config(t, u, 99999, DOMINIO)
    assert not fcor.configurado(t)
    fcor.guardar_config(t, u, cuenta, DOMINIO)
    assert fcor.configurado(t) and fcor.config(t)["direccion"] == DOMINIO
    fcor.guardar_config(t, u, None, "")
    assert not fcor.configurado(t)


def test_activar_por_cliente_da_una_direccion_estable_y_nada_por_defecto(buzon):
    t, u, c, cuenta = buzon
    assert fcor.estado_del_cliente(t, c) == {"activo": False, "codigo": None, "direccion": None}
    e = fcor.activar(t, u, c, True)
    assert e["activo"] and e["direccion"].startswith("facturas+") and e["direccion"].endswith("@despacho.example")
    codigo = e["codigo"]
    assert fcor.activar(t, u, c, False)["direccion"] is None
    assert fcor.activar(t, u, c, True)["codigo"] == codigo                        # reactivar no cambia la dirección que el cliente ya tiene
    assert [x["cliente_fiscal_id"] for x in fcor.activados(t)] == [c]


def test_sin_buzon_del_despacho_no_se_puede_activar():
    t, u, c = _despacho()
    with pytest.raises(ValueError):
        fcor.activar(t, u, c, True)


def test_un_mensaje_del_titular_a_la_direccion_del_cliente_crea_facturas_por_leer_y_no_se_repite(buzon):
    t, u, c, cuenta = buzon
    ficha = db.obtener_cliente_fiscal_por_id(c)
    conn = db.get_connection(); conn.execute("UPDATE clientes_fiscales SET email = ? WHERE id = ?", ("titular@cliente.example", c)); conn.commit(); conn.close()
    direccion = fcor.activar(t, u, c, True)["direccion"]
    _mensaje(cuenta, "1", "Titular <titular@cliente.example>", f"Facturas <{direccion}>", [("f1.pdf", "application/pdf", PDF + b"correo1"), ("firma.png", "image/png", b"x" * 500)])
    r = fcor.procesar_cuenta(cuenta)
    assert r == {"facturas": 1, "mensajes": 1, "rechazados": 0}
    f = fc.listar(t, u, cliente_fiscal_id=c)[0]
    assert f["origen"] == "correo" and f["lectura"] == "pendiente" and f["tipo"] == "recibida"
    assert fcor.procesar_cuenta(cuenta) == {"facturas": 0, "mensajes": 0, "rechazados": 0}      # el mismo mensaje no se procesa dos veces
    assert len(fc.listar(t, u, cliente_fiscal_id=c)) == 1
    fila = fcor.registro(t)[0]
    assert fila["resultado"] == "anotadas" and fila["detalle"]["facturas"] == 1 and fila["cliente"] == ficha["nombre"]


def test_el_remitente_desconocido_se_rechaza_y_se_anota(buzon):
    t, u, c, cuenta = buzon
    direccion = fcor.activar(t, u, c, True)["direccion"]
    _mensaje(cuenta, "2", "Spam <spam@malo.example>", direccion, [("f.pdf", "application/pdf", PDF + b"spam")])
    assert fcor.procesar_cuenta(cuenta) == {"facturas": 0, "mensajes": 1, "rechazados": 1}
    assert fc.listar(t, u, cliente_fiscal_id=c) == []
    assert fcor.registro(t)[0]["resultado"] == "remitente_no_autorizado"


def test_el_equipo_si_puede_y_en_copia_tambien_vale(buzon):
    t, u, c, cuenta = buzon
    direccion = fcor.activar(t, u, c, True)["direccion"]
    yo = db.obtener_usuario_por_id(u)["email"] if hasattr(db, "obtener_usuario_por_id") else "conta1@ejemplo.com"
    _mensaje(cuenta, "3", yo, "otra@persona.example", [("f.pdf", "application/pdf", PDF + b"equipo")], cc=direccion)
    assert fcor.procesar_cuenta(cuenta)["facturas"] == 1


def test_lo_que_no_va_a_un_cliente_activado_se_ignora_sin_dejar_rastro(buzon):
    t, u, c, cuenta = buzon
    fcor.activar(t, u, c, True)
    _mensaje(cuenta, "4", "titular@cliente.example", "facturas+nocodigo1@despacho.example", [("f.pdf", "application/pdf", PDF + b"x4")])
    _mensaje(cuenta, "5", "titular@cliente.example", "facturas@despacho.example", [("f.pdf", "application/pdf", PDF + b"x5")])
    assert fcor.procesar_cuenta(cuenta) == {"facturas": 0, "mensajes": 0, "rechazados": 0} and fcor.registro(t) == []
    fcor.activar(t, u, c, False)                                                    # con el cliente desactivado, ni su propia dirección vale
    assert fcor.procesar_cuenta(cuenta)["mensajes"] == 0


def test_sin_adjuntos_validos_se_anota_y_otra_cuenta_no_es_el_buzon(buzon):
    t, u, c, cuenta = buzon
    direccion = fcor.activar(t, u, c, True)["direccion"]
    conn = db.get_connection(); conn.execute("UPDATE clientes_fiscales SET email = ? WHERE id = ?", ("titular@cliente.example", c)); conn.commit(); conn.close()
    _mensaje(cuenta, "6", "titular@cliente.example", direccion, [("logo.png", "image/png", b"x" * 400), ("nota.txt", "text/plain", b"hola")])
    assert fcor.procesar_cuenta(cuenta)["facturas"] == 0
    assert fcor.registro(t)[0]["resultado"] == "sin_adjuntos_validos"
    otra = db.crear_cuenta_correo(u, "Otra", "imap", "h", 993, "otra@despacho.example")
    _mensaje(otra, "7", "titular@cliente.example", direccion, [("f.pdf", "application/pdf", PDF + b"x7")])
    assert fcor.procesar_cuenta(otra) == {"facturas": 0, "mensajes": 0, "rechazados": 0}


def test_con_ia_configurada_las_facturas_entran_en_la_cola_de_lectura(buzon, monkeypatch):
    t, u, c, cuenta = buzon
    monkeypatch.setattr(lf, "configurada", lambda x: True)
    direccion = fcor.activar(t, u, c, True)["direccion"]
    conn = db.get_connection(); conn.execute("UPDATE clientes_fiscales SET email = ? WHERE id = ?", ("titular@cliente.example", c)); conn.commit(); conn.close()
    _mensaje(cuenta, "8", "titular@cliente.example", direccion, [("f.pdf", "application/pdf", PDF + b"x8")])
    assert fcor.procesar_cuenta(cuenta)["facturas"] == 1
    fid = fc.listar(t, u, cliente_fiscal_id=c)[0]["id"]
    assert tr.lote_en_curso(t, "lectura", fid)


def test_pantallas_del_despacho_y_del_portal(cliente):
    from tests.test_portal_personas_avisos import _despacho as _d, _entrar
    uid, t, c = _web(cliente, "buzonweb@ejemplo.com")
    cuenta = db.crear_cuenta_correo(uid, "Buzón", "imap", "h", 993, "facturas@despacho.example")
    html = cliente.get(f"/contabilidad/cliente/{c}/configuracion").get_data(as_text=True)
    assert "Buzón de facturas por correo" in html and "Primero configura el buzón" in html
    assert cliente.post("/contabilidad/ajustes", data={"accion": "buzon", "buzon_cuenta_id": cuenta, "buzon_direccion": DOMINIO}).status_code in (200, 302)
    assert fcor.configurado(t)
    assert cliente.post(f"/contabilidad/cliente/{c}/buzon", data={"activo": "1"}).status_code == 302
    direccion = fcor.estado_del_cliente(t, c)["direccion"]
    assert direccion in cliente.get(f"/contabilidad/cliente/{c}/configuracion").get_data(as_text=True)
    assert "Todavía no ha llegado nada" in cliente.get("/contabilidad/buzon").get_data(as_text=True)


# --- AC8: proveedores habituales que faltan en el trimestre que se cierra ---------------------------------------------------------------------------

def test_los_proveedores_habituales_que_faltan_en_el_trimestre(monkeypatch):
    from datetime import date
    from app import cierre_trimestre, facturas_periodicas as fp, panel_cierre
    t, u, c = _despacho()

    def factura(mes, dia=5, nif="A58818501", nombre="Eléctrica Sol"):
        fc.crear(t, u, c, {"tipo": "recibida", "fecha": f"2026-{mes:02d}-{dia:02d}", "numero": f"E-{mes}-{nif}", "tercero_nombre": nombre, "tercero_nif": nif, "concepto": "Luz"}, [{"base": "100,00", "pct_iva": "21"}])
    for mes in (1, 2, 3, 4, 5, 6):
        factura(mes)                                              # abril-junio: la factura de la luz llega siempre, hasta junio
    factura(7); factura(9)                                        # en el T3 falta la de agosto
    factura(8, nif="B12345674", nombre="Otro")                    # un proveedor suelto (una sola vez): no es habitual
    hoy = date(2026, 10, 20)
    r = fp.por_cliente_del_trimestre(t, "2026-T3", hoy)
    assert list(r) == [c] and len(r[c]) == 1 and r[c][0]["nombre"] == "Eléctrica Sol" and r[c][0]["faltan"] == ["2026-08"]
    assert fp.por_cliente_del_trimestre(t, "2026-T3", date(2026, 8, 5)) == {}                           # aún no ha pasado el día 10 de agosto: no se avisa
    assert fp.por_cliente_del_trimestre(t, "2026-T2", hoy) == {}                                        # abril, mayo y junio están completos
    p = panel_cierre.panel(t, u, "2026-T3", hoy)
    assert next(x for x in p["clientes"] if x["cliente_fiscal_id"] == c)["periodicas_trimestre"] == 1
    punto = next(x for x in cierre_trimestre.checklist(t, u, c, "2026-T3")["puntos"] if x["clave"] == "periodicas_trimestre")
    assert punto["estado"] in ("aviso", "ok")                                                           # es un aviso: nunca bloquea el cierre
