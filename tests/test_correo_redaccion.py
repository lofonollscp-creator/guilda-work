"""Correo C3: autocompletado desde clientes, identidades de envío y respuesta automática."""
from datetime import date, datetime
from email.message import EmailMessage

import pytest

from app import correo, correo_autorespuesta as ar, db, nucleo
from app.correo import ErrorCorreo
from tests.conftest import iniciar_sesion_de_prueba


def _cuenta(cliente, email, smtp=True):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(uid, t)
    cuenta = db.crear_cuenta_correo(uid, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    if smtp:
        conn = db.get_connection(); conn.execute("UPDATE correo_cuentas SET smtp_host = 'smtp.ejemplo.com', smtp_puerto = 587 WHERE id = ?", (cuenta,)); conn.commit(); conn.close()
    return uid, t, cuenta


class _Smtp:
    def __init__(self): self.enviados = []
    def send_message(self, msg, from_addr=None, to_addrs=None): self.enviados.append((msg, from_addr, to_addrs))
    def quit(self): pass


@pytest.fixture
def smtp(monkeypatch):
    s = _Smtp()
    monkeypatch.setattr(correo, "_conectar_smtp", lambda *a, **k: s)
    monkeypatch.setattr(correo, "_credencial", lambda cuenta, recurso="imap": "x")
    return s


# --- Autocompletado desde clientes ---------------------------------------------------------------------------------------------------------------

def test_el_autocompletado_incluye_clientes_y_contactos(cliente):
    uid, t, cuenta = _cuenta(cliente, "red-1@ejemplo.com")
    c = nucleo.crear_cliente(t, "Panadería Luna", email="info@panaderialuna.test")
    conn = db.get_connection()
    conn.execute("INSERT INTO cliente_contactos (cliente_id, nombre, email, creado_en) VALUES (?, 'Marta Luna', 'marta@panaderialuna.test', '2026-01-01')", (c,)); conn.commit(); conn.close()
    db.registrar_destinatario_reciente(uid, "luna.proveedor@ejemplo.com", "Proveedor Luna")
    r = cliente.get("/correo/destinatarios-recientes?q=luna").get_json()
    direcciones = [x["direccion"] for x in r]
    assert direcciones[0] == "luna.proveedor@ejemplo.com" and {"info@panaderialuna.test", "marta@panaderialuna.test"} <= set(direcciones)
    assert nucleo.direcciones_de_clientes(t, "l") == []                     # menos de 2 letras no busca en clientes


def test_el_autocompletado_no_enseña_clientes_de_otro_despacho(cliente):
    uid, t, cuenta = _cuenta(cliente, "red-2@ejemplo.com")
    otro = db.crear_tenant("Otro despacho")
    nucleo.crear_cliente(otro, "Secreto SL", email="secreto@otro.test")
    assert nucleo.direcciones_de_clientes(t, "secreto") == []


# --- Identidades ---------------------------------------------------------------------------------------------------------------------------------

def test_crear_identidad_valida_y_no_se_repite(cliente):
    uid, t, cuenta = _cuenta(cliente, "red-3@ejemplo.com")
    i = correo.crear_identidad(uid, cuenta, "Gestoría Guilda", "Info@Guilda.Test")
    assert db.obtener_identidad_correo(uid, i)["direccion"] == "info@guilda.test"
    for nombre, direccion in (("", "a@b.co"), ("X", "sin-arroba"), ("X", "a@b")):
        with pytest.raises(ErrorCorreo, match="válida"):
            correo.crear_identidad(uid, cuenta, nombre, direccion)
    with pytest.raises(ErrorCorreo, match="ya está"):
        correo.crear_identidad(uid, cuenta, "Otra", "info@guilda.test")
    with pytest.raises(ErrorCorreo, match="no existe"):
        correo.crear_identidad(uid, 99999, "X", "a@b.co")


def test_el_envio_con_identidad_pone_el_alias_en_from_y_la_cuenta_en_el_sobre(cliente, smtp):
    uid, t, cuenta = _cuenta(cliente, "red-4@ejemplo.com")
    i = correo.crear_identidad(uid, cuenta, "Gestoría Guilda", "info@guilda.test")
    correo.construir_y_enviar(uid, cuenta, "ana@b.com", "Hola", "<p>Hola</p>", identidad_id=i)
    msg, from_addr, to = smtp.enviados[0]
    assert msg["From"] == "Gestoría Guilda <info@guilda.test>" or "info@guilda.test" in msg["From"]
    assert from_addr == "yo@ejemplo.com" and to == ["ana@b.com"]
    correo.construir_y_enviar(uid, cuenta, "ana@b.com", "Hola", "<p>Hola</p>")
    assert smtp.enviados[1][0]["From"] == "yo@ejemplo.com"


def test_una_identidad_de_otra_cuenta_o_persona_no_vale(cliente, smtp):
    uid, t, cuenta = _cuenta(cliente, "red-5@ejemplo.com")
    otra = db.crear_cuenta_correo(uid, "Otra", "imap", "imap.ejemplo.com", 993, "otra@ejemplo.com")
    i = correo.crear_identidad(uid, otra, "Otra", "otra@guilda.test")
    with pytest.raises(ErrorCorreo, match="identidad"):
        correo.construir_y_enviar(uid, cuenta, "ana@b.com", "Hola", "<p>Hola</p>", identidad_id=i)


def test_las_identidades_se_gestionan_desde_ajustes_y_se_ofrecen_al_redactar(cliente):
    uid, t, cuenta = _cuenta(cliente, "red-6@ejemplo.com")
    r = cliente.post("/correo/ajustes/identidades", data={"cuenta_id": str(cuenta), "nombre": "Gestoría", "direccion": "info@guilda.test"})
    assert r.status_code == 302
    assert "info@guilda.test" in cliente.get("/correo/ajustes").get_data(as_text=True)
    assert "info@guilda.test" in cliente.get(f"/correo/redactar?cuenta_id={cuenta}").get_data(as_text=True)
    (i,) = db.listar_identidades_correo(uid)
    cliente.post(f"/correo/ajustes/identidades/{i['id']}/eliminar")
    assert db.listar_identidades_correo(uid) == []


def test_enviar_con_identidad_desde_la_ruta_guarda_la_identidad_en_la_cola(cliente):
    uid, t, cuenta = _cuenta(cliente, "red-7@ejemplo.com")
    i = correo.crear_identidad(uid, cuenta, "Gestoría", "info@guilda.test")
    db.guardar_preferencias_correo(uid, "normal", True, 50, deshacer_segundos=10)
    cliente.post("/correo/enviar", data={"cuenta_id": str(cuenta), "destinatarios": "ana@b.com", "asunto": "Hola", "cuerpo_html": "<p>Hola</p>", "identidad_id": str(i)})
    conn = db.get_connection()
    assert conn.execute("SELECT identidad_id FROM correo_envios").fetchone()[0] == i
    conn.close()


# --- Respuesta automática ------------------------------------------------------------------------------------------------------------------------

def _entrante(de="ana@b.com", asunto="Consulta", **cabeceras):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = de, "yo@ejemplo.com", asunto, "<x1@b.com>"
    m["Date"] = datetime.now().astimezone().strftime("%a, %d %b %Y %H:%M:%S %z")
    for k, v in cabeceras.items():
        m[k.replace("_", "-")] = v
    m.set_content("hola")
    return m


def test_las_cabeceras_automaticas_se_reconocen():
    assert not ar.es_automatico(_entrante())
    for c in ({"Auto_Submitted": "auto-generated"}, {"Precedence": "bulk"}, {"List_Id": "<l.b.com>"}, {"List_Unsubscribe": "<mailto:x>"}, {"X_Auto_Response_Suppress": "All"}, {"Return_Path": "<>"}):
        assert ar.es_automatico(_entrante(**c)), c
    assert not ar.es_automatico(_entrante(Auto_Submitted="no"))
    assert ar.direccion_de_sistema("noreply@x.com") and ar.direccion_de_sistema("MAILER-DAEMON@x.com") and ar.direccion_de_sistema("no-reply+abc@x.com") and not ar.direccion_de_sistema("ana@x.com")


def test_guardar_valida_y_reinicia_la_lista_de_contestados(cliente):
    uid, t, cuenta = _cuenta(cliente, "red-8@ejemplo.com")
    with pytest.raises(ValueError, match="asunto y el mensaje"):
        ar.guardar(uid, cuenta, activa=True, desde="", hasta="", asunto="", cuerpo="")
    with pytest.raises(ValueError, match="anterior"):
        ar.guardar(uid, cuenta, activa=True, desde="2026-10-10", hasta="2026-10-01", asunto="Ausente", cuerpo="Vuelvo pronto")
    with pytest.raises(ValueError, match="fecha no válida"):
        ar.guardar(uid, cuenta, activa=False, desde="mañana", hasta="", asunto="", cuerpo="")
    with pytest.raises(ValueError, match="no existe"):
        ar.guardar(uid, 99999, activa=False, desde="", hasta="", asunto="", cuerpo="")
    ar.guardar(uid, cuenta, activa=True, desde="", hasta="", asunto="Ausente", cuerpo="Vuelvo pronto")
    assert ar.vigente(cuenta)["asunto"] == "Ausente"


def test_vigencia_por_fechas(cliente):
    uid, t, cuenta = _cuenta(cliente, "red-9@ejemplo.com")
    ar.guardar(uid, cuenta, activa=True, desde="2026-12-20", hasta="2026-12-31", asunto="Ausente", cuerpo="Vuelvo en enero")
    assert ar.vigente(cuenta, date(2026, 12, 19)) is None and ar.vigente(cuenta, date(2026, 12, 25)) and ar.vigente(cuenta, date(2027, 1, 1)) is None
    ar.guardar(uid, cuenta, activa=False, desde="", hasta="", asunto="Ausente", cuerpo="x")
    assert ar.vigente(cuenta, date(2026, 12, 25)) is None


def test_contesta_una_sola_vez_por_remitente_y_con_cabeceras_de_respuesta_automatica(cliente, smtp):
    uid, t, cuenta = _cuenta(cliente, "red-10@ejemplo.com")
    ar.guardar(uid, cuenta, activa=True, desde="", hasta="", asunto="Fuera de la oficina", cuerpo="Vuelvo el lunes.")
    fila = db.obtener_cuenta_correo(uid, cuenta)
    assert ar.responder_si_procede(fila, _entrante()) is True
    msg = smtp.enviados[0][0]
    assert msg["To"] == "ana@b.com" and msg["Subject"] == "Fuera de la oficina" and msg["Auto-Submitted"] == "auto-replied" and msg["In-Reply-To"] == "<x1@b.com>"
    assert ar.responder_si_procede(fila, _entrante()) is False and len(smtp.enviados) == 1               # la segunda vez no
    assert ar.responder_si_procede(fila, _entrante(de="otra@b.com")) is True and len(smtp.enviados) == 2


@pytest.mark.parametrize("de,cabeceras", [("noreply@b.com", {}), ("yo@ejemplo.com", {}), ("ana@b.com", {"Auto_Submitted": "auto-replied"}), ("ana@b.com", {"Precedence": "bulk"})])
def test_no_contesta_a_automaticos_ni_a_si_misma(cliente, smtp, de, cabeceras):
    uid, t, cuenta = _cuenta(cliente, "red-11@ejemplo.com")
    ar.guardar(uid, cuenta, activa=True, desde="", hasta="", asunto="Ausente", cuerpo="Vuelvo")
    assert ar.responder_si_procede(db.obtener_cuenta_correo(uid, cuenta), _entrante(de=de, **cabeceras)) is False and smtp.enviados == []


def test_no_contesta_a_correo_antiguo_ni_con_la_respuesta_desactivada(cliente, smtp):
    uid, t, cuenta = _cuenta(cliente, "red-12@ejemplo.com")
    fila = db.obtener_cuenta_correo(uid, cuenta)
    assert ar.responder_si_procede(fila, _entrante()) is False                              # sin configurar
    ar.guardar(uid, cuenta, activa=True, desde="", hasta="", asunto="Ausente", cuerpo="Vuelvo")
    viejo = _entrante(); del viejo["Date"]; viejo["Date"] = "Mon, 01 Jan 2024 10:00:00 +0000"
    assert ar.responder_si_procede(fila, viejo) is False and smtp.enviados == []


def test_si_el_envio_falla_no_se_da_por_contestado(cliente, monkeypatch):
    uid, t, cuenta = _cuenta(cliente, "red-13@ejemplo.com")
    ar.guardar(uid, cuenta, activa=True, desde="", hasta="", asunto="Ausente", cuerpo="Vuelvo")
    def falla(*a, **k): raise ErrorCorreo("sin SMTP")
    monkeypatch.setattr(correo, "construir_y_enviar", falla)
    fila = db.obtener_cuenta_correo(uid, cuenta)
    assert ar.responder_si_procede(fila, _entrante()) is False
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM correo_autorespuesta_enviadas").fetchone()[0] == 0
    conn.close()


def test_la_autorespuesta_se_configura_desde_ajustes(cliente):
    uid, t, cuenta = _cuenta(cliente, "red-14@ejemplo.com")
    r = cliente.post("/correo/ajustes/autorespuesta", data={"cuenta_id": str(cuenta), "activa": "on", "asunto": "Ausente", "cuerpo": "Vuelvo el lunes"})
    assert r.status_code == 302 and ar.vigente(cuenta)["cuerpo"] == "Vuelvo el lunes"
    r = cliente.post("/correo/ajustes/autorespuesta", data={"cuenta_id": str(cuenta), "activa": "on", "asunto": "", "cuerpo": ""})
    assert "asunto y el mensaje" in r.get_data(as_text=True)
    assert cliente.post("/correo/ajustes/autorespuesta", data={"cuenta_id": "99999"}).status_code == 404


def test_un_correo_nuevo_en_la_bandeja_dispara_la_autorespuesta(cliente, smtp):
    uid, t, cuenta = _cuenta(cliente, "red-15@ejemplo.com")
    ar.guardar(uid, cuenta, activa=True, desde="", hasta="", asunto="Ausente", cuerpo="Vuelvo")
    fila = db.obtener_cuenta_correo(uid, cuenta)
    crudo = _entrante().as_bytes()
    correo._guardar_mensaje_imap(fila, "INBOX", "10", crudo, set())
    assert len(smtp.enviados) == 1
    correo._guardar_mensaje_imap(fila, "Enviados", "11", crudo, set())              # otra carpeta: no
    correo._guardar_mensaje_imap(fila, "INBOX", "12", crudo, {"\\seen"})            # ya leído: no
    assert len(smtp.enviados) == 1
