"""Derechos RGPD de la persona usuaria sobre sus datos (app/rgpd_persona.py, app/rutas_mis_datos.py) y retención automática (app/retencion.py)."""
import json
from datetime import datetime, timedelta

from app import db, retencion, rgpd_persona
from tests.conftest import iniciar_sesion_de_prueba


def _con_despacho(cliente, correo, supervisor=False):
    uid = iniciar_sesion_de_prueba(cliente, correo, "contrasena123")
    db.asignar_tenant(uid, db.crear_tenant(f"Despacho {correo}"))
    db.asignar_supervisor_tenant(uid, supervisor)
    return uid


def test_descargar_mis_datos_incluye_lo_mio_y_ningun_secreto(cliente):
    uid = _con_despacho(cliente, "mis-datos@ejemplo.com")
    db.crear_notificacion(uid, "tarea", "Vence el 303", "mañana", None)
    db.registrar_dispositivo_push(uid, "token-secreto-fcm-123", "android")
    db.agregar_mensaje_ia(uid, "user", contenido="Hola asistente")
    resp = cliente.get("/cuenta/privacidad/descargar.json")
    assert resp.status_code == 200 and "attachment" in resp.headers["Content-Disposition"] and resp.headers["Cache-Control"] == "no-store"
    cuerpo = resp.get_data(as_text=True)
    datos = json.loads(cuerpo)
    assert datos["cuenta"]["email"] == "mis-datos@ejemplo.com"
    assert [a["titulo"] for a in datos["avisos"]] == ["Vence el 303"]
    assert datos["dispositivos_avisos"][0]["plataforma"] == "android"
    assert "Hola asistente" in cuerpo
    for secreto in ("token-secreto-fcm-123", "contrasena_hash", "pbkdf2", "scrypt"):
        assert secreto not in cuerpo
    assert any(r["tipo"] == "exportacion_propia" for r in __import__("app.rgpd", fromlist=["x"]).registro(db.tenant_de_usuario(uid)["id"]))


def test_los_datos_de_otra_persona_no_salen(cliente):
    otra = db.crear_usuario("otra-persona@ejemplo.com", "contrasena123")
    db.crear_notificacion(otra, "tarea", "Aviso de otra persona", "x", None)
    _con_despacho(cliente, "yo-mismo@ejemplo.com")
    assert "Aviso de otra persona" not in cliente.get("/cuenta/privacidad/descargar.json").get_data(as_text=True)


def test_olvidar_dispositivos_y_borrar_historial_ia(cliente):
    uid = _con_despacho(cliente, "olvidar@ejemplo.com")
    db.registrar_dispositivo_push(uid, "t1", "android")
    db.registrar_suscripcion_web(uid, '{"endpoint":"https://x.example/1","keys":{"p256dh":"a","auth":"b"}}', "https://x.example/1")
    db.agregar_mensaje_ia(uid, "user", contenido="privado")
    assert cliente.post("/cuenta/privacidad/olvidar-dispositivos").status_code == 302
    assert db.tokens_push_de_usuario(uid) == [] and db.suscripciones_web_de_usuario(uid) == []
    assert cliente.post("/cuenta/privacidad/borrar-historial-ia").status_code == 302
    assert db.listar_mensajes_ia(uid) == []


def test_solicitar_baja_se_registra_una_vez_y_avisa_a_la_direccion(cliente):
    tenant = db.crear_tenant("Despacho baja")
    jefe = db.crear_usuario("jefe-baja@ejemplo.com", "contrasena123")
    db.asignar_tenant(jefe, tenant)
    db.asignar_supervisor_tenant(jefe, True)
    uid = iniciar_sesion_de_prueba(cliente, "empleada-baja@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, tenant)
    assert cliente.post("/cuenta/privacidad/solicitar-baja").status_code == 302
    assert rgpd_persona.solicitud_abierta(uid)
    avisos = db.listar_notificaciones(jefe)
    assert len(avisos) == 1 and "baja" in avisos[0]["titulo"].lower()
    assert cliente.post("/cuenta/privacidad/solicitar-baja").status_code == 302
    assert len(db.listar_notificaciones(jefe)) == 1                    # no se duplica
    assert "Ya hay una solicitud" in cliente.get("/cuenta/privacidad/").get_data(as_text=True)


def test_la_pantalla_pide_sesion(cliente):
    assert cliente.get("/cuenta/privacidad/").status_code in (302, 401)


def test_retencion_borra_lo_caduco_y_conserva_lo_reciente(usuario_id):
    ahora = datetime.now()
    viejo, reciente = (ahora - timedelta(days=400)).isoformat(timespec="seconds"), (ahora - timedelta(days=5)).isoformat(timespec="seconds")
    conn = db.get_connection()
    try:
        for titulo, fecha in (("vieja", viejo), ("reciente", reciente)):
            cid = conn.execute("INSERT INTO ia_conversaciones (usuario_id, titulo, creada_en, actualizada_en, activa) VALUES (?, ?, ?, ?, 0)", (usuario_id, titulo, fecha, fecha)).lastrowid
            conn.execute("INSERT INTO ia_mensajes (usuario_id, conversacion_id, rol, contenido, creado_en) VALUES (?, ?, 'user', ?, ?)", (usuario_id, cid, titulo, fecha))
        conn.execute("INSERT INTO notificaciones (usuario_id, tipo, titulo, cuerpo, url, creado_en, leido_en) VALUES (?, 'x', 'leida vieja', NULL, NULL, ?, ?)", (usuario_id, (ahora - timedelta(days=200)).isoformat(timespec="seconds"), viejo))
        conn.execute("INSERT INTO notificaciones (usuario_id, tipo, titulo, cuerpo, url, creado_en, leido_en) VALUES (?, 'x', 'no leida reciente', NULL, NULL, ?, NULL)", (usuario_id, reciente))
        conn.execute("INSERT INTO notificaciones (usuario_id, tipo, titulo, cuerpo, url, creado_en, leido_en) VALUES (?, 'x', 'no leida muy vieja', NULL, NULL, ?, NULL)", (usuario_id, viejo))
        conn.commit()
    finally:
        conn.close()
    r = retencion.purgar(ahora)
    assert r["ia_conversaciones"] == 1 and r["ia_mensajes"] == 1 and r["avisos"] == 2
    assert [c["titulo"] for c in db.listar_conversaciones_ia(usuario_id)] == ["reciente"]
    assert [n["titulo"] for n in db.listar_notificaciones(usuario_id)] == ["no leida reciente"]
    assert retencion.purgar(ahora) == {"ia_conversaciones": 0, "ia_mensajes": 0, "avisos": 0, "accesos_portal": 0, "ia_salidas": 0}      # idempotente
