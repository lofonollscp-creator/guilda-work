"""Correo C4: contexto de cada mensaje con clientes, vencimientos y tareas, y «Escribir» desde las demás pantallas."""
from app import correo, correo_contexto, db, nucleo
from tests.conftest import iniciar_sesion_de_prueba


def _montar(cliente, email):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(uid, t)
    cuenta = db.crear_cuenta_correo(uid, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    return uid, t, cuenta


def _msg(cuenta, uid="1", remitente="ana@cliente.test", destinatarios="yo@ejemplo.com"):
    return db.guardar_mensaje_correo(cuenta_id=cuenta, uid=uid, asunto="Consulta IVA", remitente=remitente, destinatarios=destinatarios, fecha="2026-10-01T10:00:00", cuerpo_texto="hola", cuerpo_html=None)


def _contacto(cliente_nucleo_id, nombre, email):
    conn = db.get_connection()
    conn.execute("INSERT INTO cliente_contactos (cliente_id, nombre, email, creado_en) VALUES (?, ?, ?, '2026-01-01')", (cliente_nucleo_id, nombre, email)); conn.commit(); conn.close()


# --- vínculo por contactos y por destinatario ----------------------------------------------------------------------------------------------------

def test_un_contacto_del_cliente_tambien_vincula_sus_correos(cliente):
    uid, t, cuenta = _montar(cliente, "ctx-1@ejemplo.com")
    f = db.crear_cliente_fiscal(t, "Panadería Luna", email="info@luna.test")
    _contacto(db.obtener_cliente_fiscal(t, f)["cliente_id"], "Marta", "marta@luna.test")
    assert db.cliente_fiscal_id_por_email(t, "marta@luna.test") == f and db.cliente_fiscal_id_por_email(t, "INFO@luna.test") == f
    assert db.cliente_fiscal_id_por_email(t, "otra@luna.test") is None


def test_si_el_correo_es_de_dos_clientes_no_se_adivina(cliente):
    uid, t, cuenta = _montar(cliente, "ctx-2@ejemplo.com")
    a = db.crear_cliente_fiscal(t, "A SL", email="comun@x.test"); b = db.crear_cliente_fiscal(t, "B SL")
    _contacto(db.obtener_cliente_fiscal(t, b)["cliente_id"], "Pepe", "comun@x.test")
    assert db.cliente_fiscal_id_por_email(t, "comun@x.test") is None


def test_un_correo_enviado_por_nosotros_se_vincula_por_su_destinatario(cliente):
    uid, t, cuenta = _montar(cliente, "ctx-3@ejemplo.com")
    f = db.crear_cliente_fiscal(t, "Panadería Luna", email="info@luna.test")
    m = _msg(cuenta, remitente="yo@ejemplo.com", destinatarios="Luna <info@luna.test>, otro@z.test")
    correo._aplicar_categoria_automatica(uid, m, "yo@ejemplo.com", "Hola", destinatarios="Luna <info@luna.test>, otro@z.test", propias={"yo@ejemplo.com"})
    assert correo.obtener_mensaje(m)["cliente_fiscal_id"] == f
    m2 = _msg(cuenta, "2", remitente="info@luna.test")                       # uno recibido sigue vinculándose por remitente
    correo._aplicar_categoria_automatica(uid, m2, "info@luna.test", "Hola", destinatarios="yo@ejemplo.com", propias={"yo@ejemplo.com"})
    assert correo.obtener_mensaje(m2)["cliente_fiscal_id"] == f


# --- contexto -----------------------------------------------------------------------------------------------------------------------------------

def test_el_contexto_trae_vencimientos_y_tareas_abiertos_del_cliente(cliente):
    uid, t, cuenta = _montar(cliente, "ctx-4@ejemplo.com")
    f = db.crear_cliente_fiscal(t, "Panadería Luna", email="info@luna.test")
    db.crear_vencimiento_fiscal(t, f, "303", "2026-3T", "2026-10-20")
    cerrado = db.crear_vencimiento_fiscal(t, f, "111", "2026-3T", "2026-10-20"); db.marcar_presentado_vencimiento_fiscal(t, cerrado, uid)
    db.crear_tarea_outlook(uid, "Pedir facturas", cliente_fiscal_id=f, fecha_vencimiento="2026-10-18")
    hecha = db.crear_tarea_outlook(uid, "Ya hecha", cliente_fiscal_id=f); db.completar_tarea_outlook(uid, hecha)
    m = _msg(cuenta); db.asignar_cliente_fiscal_correo(t, m, f)
    ctx = correo_contexto.contexto_de_mensaje(uid, t, correo.obtener_mensaje(m), "ana@cliente.test")
    assert ctx["cliente"]["nombre"] == "Panadería Luna" and [v["modelo"] for v in ctx["vencimientos"]] == ["303"]
    assert [x["asunto"] for x in ctx["tareas"]] == ["Pedir facturas"] and ctx["candidatos"] == []


def test_sin_cliente_vinculado_propone_candidatos_por_email(cliente):
    uid, t, cuenta = _montar(cliente, "ctx-5@ejemplo.com")
    c = nucleo.crear_cliente(t, "Taller Ruiz", email="taller@ruiz.test")
    m = _msg(cuenta, remitente="Taller <taller@ruiz.test>")
    ctx = correo_contexto.contexto_de_mensaje(uid, t, correo.obtener_mensaje(m), "taller@ruiz.test")
    assert ctx["cliente"] is None and [k["id"] for k in ctx["candidatos"]] == [c]
    assert correo_contexto.contexto_de_mensaje(uid, None, correo.obtener_mensaje(m), "taller@ruiz.test") is None


def test_el_contexto_no_enseña_clientes_de_otro_despacho(cliente):
    uid, t, cuenta = _montar(cliente, "ctx-6@ejemplo.com")
    otro = db.crear_tenant("Otro"); ajeno = db.crear_cliente_fiscal(otro, "Ajeno SL", email="a@ajeno.test")
    m = _msg(cuenta)
    conn = db.get_connection(); conn.execute("UPDATE correo_mensajes SET cliente_fiscal_id = ? WHERE id = ?", (ajeno, m)); conn.commit(); conn.close()
    ctx = correo_contexto.contexto_de_mensaje(uid, t, correo.obtener_mensaje(m), "a@ajeno.test")
    assert ctx["cliente"] is None and ctx["vencimientos"] == [] and ctx["candidatos"] == []


# --- Pantallas ----------------------------------------------------------------------------------------------------------------------------------

def test_la_bandeja_enseña_el_panel_de_contexto(cliente):
    uid, t, cuenta = _montar(cliente, "ctx-7@ejemplo.com")
    f = db.crear_cliente_fiscal(t, "Panadería Luna", email="info@luna.test")
    db.crear_vencimiento_fiscal(t, f, "303", "2026-3T", "2026-10-20")
    m = _msg(cuenta); db.asignar_cliente_fiscal_correo(t, m, f)
    html = cliente.get(f"/correo/?cuenta_id={cuenta}&mensaje_id={m}").get_data(as_text=True)
    assert '<details class="correo-contexto"' in html and "Panadería Luna" in html and "303 2026-3T" in html and "Escribir al cliente" in html
    sin = _msg(cuenta, "2", remitente="nadie@x.test")
    assert '<details class="correo-contexto"' not in cliente.get(f"/correo/?cuenta_id={cuenta}&mensaje_id={sin}").get_data(as_text=True)


def test_redactar_acepta_destinatario_asunto_y_cliente(cliente):
    uid, t, cuenta = _montar(cliente, "ctx-8@ejemplo.com")
    conn = db.get_connection(); conn.execute("UPDATE correo_cuentas SET smtp_host = 'smtp.ejemplo.com', smtp_puerto = 587 WHERE id = ?", (cuenta,)); conn.commit(); conn.close()
    f = db.crear_cliente_fiscal(t, "Panadería Luna", email="info@luna.test")
    html = cliente.get(f"/correo/redactar?para=info@luna.test&asunto=303 2026-3T&cliente_fiscal_id={f}").get_data(as_text=True)
    assert 'value="info@luna.test"' in html and "303 2026-3T" in html
    otro = db.crear_tenant("Otro"); ajeno = db.crear_cliente_fiscal(otro, "Ajeno SL")
    assert cliente.get(f"/correo/redactar?cliente_fiscal_id={ajeno}").status_code == 200       # un cliente que no es del despacho se ignora sin error


def test_la_ficha_del_cliente_ofrece_escribir(cliente):
    uid, t, cuenta = _montar(cliente, "ctx-9@ejemplo.com")
    f = db.crear_cliente_fiscal(t, "Panadería Luna", email="info@luna.test")
    db.crear_vencimiento_fiscal(t, f, "303", "2026-3T", "2026-10-20")
    cid = db.obtener_cliente_fiscal(t, f)["cliente_id"]
    html = cliente.get(f"/clientes/{cid}").get_data(as_text=True)
    assert f"para=info%40luna.test" in html or "para=info@luna.test" in html
    fiscal = cliente.get(f"/clientes/{cid}?pestana=fiscal").get_data(as_text=True)
    assert "Escribir al cliente sobre este vencimiento" in fiscal
