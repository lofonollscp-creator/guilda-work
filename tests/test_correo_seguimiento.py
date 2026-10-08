"""«Avísame si no responde»: seguimiento de correos enviados (Message-ID propio, cierre al llegar la respuesta, aviso único)."""
from datetime import datetime, timedelta
from email import message_from_bytes

import pytest

from app import correo, db, notificaciones
from tests.conftest import iniciar_sesion_de_prueba

AHORA = datetime(2026, 10, 7, 9, 0)


@pytest.fixture
def avisos(monkeypatch):
    registro = []
    monkeypatch.setattr(notificaciones, "crear_y_enviar", lambda uid, tipo, titulo, cuerpo, url=None, datos=None: registro.append((uid, tipo, titulo, cuerpo, url)))
    return registro


def _cuenta(cliente, email):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    cuenta = db.crear_cuenta_correo(uid, "c", "imap", "h", 993, "yo@despacho.com", smtp_host="smtp.h", smtp_puerto=587)
    return uid, cuenta


def _recibido(cuenta, uid_imap, remitente, in_reply_to=None, referencias=None, asunto="Re: Hola", descargado="2026-10-08"):
    conn = db.get_connection()
    mid = conn.execute(
        "INSERT INTO correo_mensajes (cuenta_id, carpeta, uid, asunto, remitente, in_reply_to, referencias, message_id, descargado_en) VALUES (?, 'INBOX', ?, ?, ?, ?, ?, ?, ?)",
        (cuenta, uid_imap, asunto, remitente, in_reply_to, referencias, f"<recibido-{uid_imap}@x>", descargado),
    ).lastrowid
    conn.commit()
    conn.close()
    return mid


def test_validacion_de_dias():
    assert [db.seguimiento_dias_valido(v) for v in (None, "", "x", 0, -2, 31, "3", 30, 1)] == [None, None, None, None, None, None, 3, 30, 1]


def test_crear_listar_y_cancelar(cliente):
    uid, cuenta = _cuenta(cliente, "sg-1@x.com")
    sid = db.crear_seguimiento_correo(uid, cuenta, "<abc@x>", "Presupuesto", "ana@x.com", 3, AHORA)
    assert sid and db.crear_seguimiento_correo(uid, cuenta, "<abc@x>", "Presupuesto", "ana@x.com", 3, AHORA) == sid        # no se duplica
    assert db.crear_seguimiento_correo(uid, cuenta, "<abc@x>", "x", "y", 0) is None and db.crear_seguimiento_correo(uid, cuenta, "", "x", "y", 3) is None
    otro = db.crear_usuario("sg-1b@x.com", "contrasena123")
    assert db.crear_seguimiento_correo(otro, cuenta, "<z@x>", "x", "y", 3) is None                        # cuenta ajena
    s = db.listar_seguimientos_correo(uid)[0]
    assert s["avisar_en"] == "2026-10-10T09:00:00" and s["estado"] == "esperando"
    assert db.cancelar_seguimiento_correo(otro, sid) is False and db.cancelar_seguimiento_correo(uid, sid) is True
    assert db.listar_seguimientos_correo(uid) == [] and db.seguimiento_de_mensaje(uid, "<abc@x>")["estado"] == "cancelado"
    assert db.cancelar_seguimiento_correo(uid, sid) is False


def test_aviso_cuando_pasa_el_plazo_sin_respuesta_y_una_sola_vez(cliente, avisos):
    uid, cuenta = _cuenta(cliente, "sg-2@x.com")
    db.crear_seguimiento_correo(uid, cuenta, "<enviado@x>", "Presupuesto", "ana@x.com", 3, AHORA)
    assert correo.procesar_seguimientos(AHORA + timedelta(days=2)) == {"respondidos": 0, "avisados": 0}      # aún hay plazo
    assert correo.procesar_seguimientos(AHORA + timedelta(days=3, hours=1)) == {"respondidos": 0, "avisados": 1}
    assert [(a[0], a[1]) for a in avisos] == [(uid, "correo_sin_respuesta")] and "Presupuesto" in avisos[0][3] and "ana@x.com" in avisos[0][3]
    assert correo.procesar_seguimientos(AHORA + timedelta(days=9)) == {"respondidos": 0, "avisados": 0} and len(avisos) == 1
    assert db.seguimiento_de_mensaje(uid, "<enviado@x>")["estado"] == "sin_respuesta"


def test_la_respuesta_cierra_el_seguimiento_aunque_aun_no_toque(cliente, avisos):
    uid, cuenta = _cuenta(cliente, "sg-3@x.com")
    db.crear_seguimiento_correo(uid, cuenta, "<uno@x>", "Uno", "ana@x.com", 7, AHORA)
    db.crear_seguimiento_correo(uid, cuenta, "<dos@x>", "Dos", "luis@x.com", 1, AHORA)
    db.crear_seguimiento_correo(uid, cuenta, "<tres@x>", "Tres", "eva@x.com", 1, AHORA)
    _recibido(cuenta, 1, "Ana <ana@x.com>", in_reply_to="<uno@x>")
    _recibido(cuenta, 2, "Luis <luis@x.com>", referencias="<raiz@x> <dos@x>")
    _recibido(cuenta, 3, "Yo <YO@despacho.com>", in_reply_to="<tres@x>")           # una respuesta mía no cuenta
    _recibido(cuenta, 4, "Otro <otro@x.com>", in_reply_to="<tres@x>", descargado="2026-10-01")   # anterior al envío: no cuenta
    r = correo.procesar_seguimientos(AHORA + timedelta(days=2))
    assert r == {"respondidos": 2, "avisados": 1}
    estados = {s["message_id"]: s["estado"] for s in db.listar_seguimientos_correo(uid, solo_esperando=False)}
    assert estados == {"<uno@x>": "respondido", "<dos@x>": "respondido", "<tres@x>": "sin_respuesta"}
    assert len(avisos) == 1 and "Tres" in avisos[0][3]


def test_un_message_id_parecido_no_se_confunde(cliente, avisos):
    uid, cuenta = _cuenta(cliente, "sg-4@x.com")
    db.crear_seguimiento_correo(uid, cuenta, "<a_b@x>", "Guion bajo", "ana@x.com", 1, AHORA)
    _recibido(cuenta, 1, "ana@x.com", in_reply_to="<aXb@x>")                       # «_» no es un comodín
    assert correo.procesar_seguimientos(AHORA + timedelta(days=2)) == {"respondidos": 0, "avisados": 1}


def test_cuenta_borrada_cancela_el_seguimiento(cliente, avisos):
    uid, cuenta = _cuenta(cliente, "sg-5@x.com")
    db.crear_seguimiento_correo(uid, cuenta, "<x@x>", "x", "y", 1, AHORA)
    conn = db.get_connection()
    conn.execute("DELETE FROM correo_cuentas WHERE id = ?", (cuenta,))
    conn.commit()
    conn.close()
    assert correo.procesar_seguimientos(AHORA + timedelta(days=5)) == {"respondidos": 0, "avisados": 0} and avisos == []
    assert db.listar_seguimientos_correo(uid) == []


def test_el_envio_lleva_message_id_propio_y_crea_el_seguimiento(cliente, monkeypatch):
    uid, cuenta = _cuenta(cliente, "sg-6@x.com")
    monkeypatch.setattr(correo, "_contrasena", lambda c: "p")
    enviados = []

    class SmtpFalso:
        def send_message(self, mensaje, to_addrs=None):
            enviados.append(mensaje)

        def quit(self):
            pass
    monkeypatch.setattr(correo, "_conectar_smtp", lambda *a, **k: SmtpFalso())
    mid = correo.construir_y_enviar(uid, cuenta, "ana@x.com", "Hola", "<p>Hola</p>", seguimiento_dias=4)
    assert mid.startswith("<") and mid.endswith("@despacho.com>") and enviados[0]["Message-ID"] == mid
    s = db.seguimiento_de_mensaje(uid, mid)
    assert s["estado"] == "esperando" and s["asunto"] == "Hola" and s["destinatarios"] == "ana@x.com"
    mid2 = correo.construir_y_enviar(uid, cuenta, "ana@x.com", "Sin seguimiento", "<p>x</p>")
    assert mid2 != mid and db.seguimiento_de_mensaje(uid, mid2) is None


def test_la_cola_de_envios_conserva_el_seguimiento(cliente, monkeypatch):
    uid, cuenta = _cuenta(cliente, "sg-7@x.com")
    monkeypatch.setattr(correo, "_contrasena", lambda c: "p")

    class SmtpFalso:
        def send_message(self, mensaje, to_addrs=None): pass
        def quit(self): pass
    monkeypatch.setattr(correo, "_conectar_smtp", lambda *a, **k: SmtpFalso())
    envio = correo.encolar_envio(uid, cuenta, "ana@x.com", "En cola", "<p>x</p>", enviar_en="2026-10-07T09:00:00", seguimiento_dias=3)
    assert db.obtener_envio_correo(uid, envio)["seguimiento_dias"] == 3
    assert correo.procesar_envios_pendientes(AHORA + timedelta(minutes=1)) == 1
    assert [s["asunto"] for s in db.listar_seguimientos_correo(uid)] == ["En cola"]
    envio2 = correo.encolar_envio(uid, cuenta, "ana@x.com", "Basura", "<p>x</p>", enviar_en="2026-10-07T09:00:00", seguimiento_dias=999)
    assert db.obtener_envio_correo(uid, envio2)["seguimiento_dias"] is None


def test_pantallas(cliente):
    uid, cuenta = _cuenta(cliente, "sg-8@x.com")
    conn = db.get_connection()
    mid = conn.execute("INSERT INTO correo_mensajes (cuenta_id, carpeta, uid, asunto, remitente, destinatarios, message_id, descargado_en) VALUES (?, 'Sent', 1, 'Enviado', 'yo@despacho.com', 'ana@x.com', '<sent1@x>', '2026-10-01')", (cuenta,)).lastrowid
    sin_id = conn.execute("INSERT INTO correo_mensajes (cuenta_id, carpeta, uid, asunto, remitente, descargado_en) VALUES (?, 'INBOX', 2, 'Sin id', 'a@b.c', '2026-10-01')", (cuenta,)).lastrowid
    conn.commit()
    conn.close()
    html = cliente.get("/correo/", query_string={"cuenta_id": cuenta, "carpeta": "Sent", "mensaje_id": mid}).get_data(as_text=True)
    assert "Esperar respuesta" in html and "Avisarme si no responden en" in html
    assert cliente.post(f"/correo/{mid}/seguimiento", data={"dias": "3"}).status_code == 302
    html = cliente.get("/correo/", query_string={"cuenta_id": cuenta, "carpeta": "Sent", "mensaje_id": mid}).get_data(as_text=True)
    assert "Esperando respuesta hasta el" in html and "Cancelar el seguimiento" in html
    ajustes = cliente.get("/correo/ajustes").get_data(as_text=True)
    assert "Correos esperando respuesta" in ajustes and "Enviado" in ajustes
    seg = db.listar_seguimientos_correo(uid)[0]
    assert cliente.post(f"/correo/seguimientos/{seg['id']}/cancelar").status_code == 302 and db.listar_seguimientos_correo(uid) == []
    # sin Message-ID o con días absurdos no se activa
    assert "aviso=" in cliente.post(f"/correo/{sin_id}/seguimiento", data={"dias": "3"}).headers["Location"] and db.listar_seguimientos_correo(uid) == []
    cliente.post(f"/correo/{mid}/seguimiento", data={"dias": "500"})
    assert db.listar_seguimientos_correo(uid) == []
    assert cliente.post("/correo/99999/seguimiento", data={"dias": "3"}).status_code == 404
    assert 'name="seguimiento_dias"' in cliente.get(f"/correo/redactar?cuenta_id={cuenta}").get_data(as_text=True)


# --- Plantillas con modelo fiscal y variables del vencimiento ------------------------------------

def test_plantilla_por_modelo_usa_el_vencimiento_de_ese_modelo(cliente, monkeypatch):
    monkeypatch.setenv("GUILDA_URL_PUBLICA", "https://app.ejemplo.com/")
    uid = iniciar_sesion_de_prueba(cliente, "sg-9@x.com", "contrasena123")
    tenant = db.crear_tenant("Despacho plantillas")
    db.asignar_tenant(uid, tenant)
    cli = db.crear_cliente_fiscal(tenant, "Panadería López", nif="B123")
    pronto = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    lejos = (datetime.now() + timedelta(days=20)).strftime("%Y-%m-%d")
    v1 = db.crear_vencimiento_fiscal(tenant, cli, "130", "2T", pronto)
    v2 = db.crear_vencimiento_fiscal(tenant, cli, "303", "2T", lejos)
    conn = db.get_connection()
    conn.execute("UPDATE vencimientos_fiscales SET documento_solicitado = 'los extractos de junio' WHERE id = ?", (v2,))
    conn.commit()
    conn.close()
    sin_modelo = correo.crear_plantilla(uid, "General", "Aviso {{modelo}}", "Vence el {{modelo}}")
    del_303 = correo.crear_plantilla(uid, "Para el 303", "{{modelo}} de {{cliente}}", "Faltan {{dias}} días. Necesitamos: {{documento}}. {{enlace_portal}}", "303")
    import json
    # sin modelo: el vencimiento más próximo, sea el que sea
    r = cliente.get(f"/correo/plantillas/{sin_modelo}.json?cliente_fiscal_id={cli}").get_json()
    assert r["asunto"] == "Aviso 130"
    # con modelo: el 303, aunque haya otro más cercano
    r = cliente.get(f"/correo/plantillas/{del_303}.json?cliente_fiscal_id={cli}").get_json()
    assert r["asunto"] == "303 de Panadería López" and "Faltan 20 días" in r["cuerpo"] and "los extractos de junio" in r["cuerpo"]
    assert "https://app.ejemplo.com/portal/entrar" in r["cuerpo"] and r["sin_resolver"] == []
    # un modelo sin vencimiento deja las variables sin resolver (se ve qué falta)
    sin_venc = correo.crear_plantilla(uid, "Para el 111", "{{modelo}}", "{{documento}}", "111")
    r = cliente.get(f"/correo/plantillas/{sin_venc}.json?cliente_fiscal_id={cli}").get_json()
    assert set(r["sin_resolver"]) == {"modelo", "documento"}
    # en el editor: ★ en la plantilla del modelo del próximo vencimiento de ese cliente
    assert correo.contexto_plantilla(uid, cli, "130")["fecha_limite"] == datetime.strptime(pronto, "%Y-%m-%d").strftime("%d/%m/%Y")
    ajustes = cliente.get("/correo/ajustes").get_data(as_text=True)
    assert "Modelo 303" in ajustes and 'name="modelo"' in ajustes
    assert "documento" in dict(correo.VARIABLES_PLANTILLA) and "enlace_portal" in dict(correo.VARIABLES_PLANTILLA)
    assert db.listar_plantillas_correo(uid)[0]["modelo"] in (None, "303", "111")
