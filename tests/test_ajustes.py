"""Mi perfil ampliado (cargo, teléfono, «no molestar», todas las notificaciones, apariencia, seguridad, mis datos) y el centro de /ajustes."""
from datetime import datetime

import pytest

from app import db, push
from tests.conftest import iniciar_sesion_de_prueba


def _uid(cliente, email="aj-1@x.com"):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    db.asignar_tenant(uid, db.crear_tenant("Despacho ajustes " + email))
    return uid


def test_el_centro_de_ajustes_existe_y_enlaza_todo(cliente):
    _uid(cliente)
    for ruta in ("/ajustes", "/ajustes/"):
        r = cliente.get(ruta)
        assert r.status_code == 200
    html = cliente.get("/ajustes").get_data(as_text=True)
    for destino in ("/ajustes/perfil", "/ajustes/cuenta", "/mis-dispositivos", "/correo/ajustes", "/correo/cuentas", "/ia/ajustes", "/export",
                    "/importar", "/papelera", "/tareas/plantillas", "/tareas/recurrentes", "/fichaje/mis-datos", "/herramientas"):
        assert f'href="{destino}' in html, destino
    assert 'id="ajustes-filtro"' in html and "ajustes.js" in html and "data-ajuste-tema" in html


def test_ajustes_requiere_sesion(cliente):
    assert cliente.get("/ajustes").status_code in (301, 302)


def test_perfil_muestra_todas_las_preferencias_de_notificacion(cliente):
    """Regresión: el formulario no traía las casillas de correo y portal, y cada «Guardar» las desactivaba sin avisar."""
    _uid(cliente)
    html = cliente.get("/ajustes/perfil").get_data(as_text=True)
    for campo in ("notificar_push_vencimientos", "notificar_push_tiquets", "notificar_push_correo", "notificar_push_portal_mensajes",
                  "notificar_resumen_semanal", "silencio_activo", "cargo", "telefono"):
        assert f'name="{campo}"' in html, campo
    for seccion in ('id="perfil"', 'id="notificaciones"', 'id="apariencia"', 'id="seguridad"', 'id="datos"'):
        assert seccion in html


def test_guardar_perfil_guarda_cargo_telefono_silencio_y_notificaciones(cliente):
    uid = _uid(cliente)
    r = cliente.post("/ajustes/perfil", data={
        "nombre_mostrado": "Ana", "cargo": "Gestora fiscal", "telefono": "+34 600 111 222",
        "notificar_push_correo": "on", "silencio_activo": "on", "silencio_desde": "22:00", "silencio_hasta": "08:00",
    })
    assert r.status_code == 302 and "aviso=guardado" in r.headers["Location"]
    p = db.obtener_perfil_usuario(uid)
    assert (p["nombre_mostrado"], p["cargo"], p["telefono"]) == ("Ana", "Gestora fiscal", "+34 600 111 222")
    assert p["notificar_push_correo"] == 1 and p["notificar_push_vencimientos"] == 0 and p["notificar_push_portal_mensajes"] == 0
    assert (p["silencio_desde"], p["silencio_hasta"]) == ("22:00", "08:00")
    html = cliente.get("/ajustes/perfil?aviso=guardado").get_data(as_text=True)
    assert "Cambios guardados." in html and "Gestora fiscal" in html and 'value="+34 600 111 222"' in html
    # sin la casilla «no molestar» la franja se borra; una franja a medias o inválida tampoco vale
    cliente.post("/ajustes/perfil", data={"nombre_mostrado": "Ana"})
    p = db.obtener_perfil_usuario(uid)
    assert p["silencio_desde"] is None and p["silencio_hasta"] is None
    cliente.post("/ajustes/perfil", data={"silencio_activo": "on", "silencio_desde": "25:99", "silencio_hasta": "08:00"})
    assert db.obtener_perfil_usuario(uid)["silencio_desde"] is None
    cliente.post("/ajustes/perfil", data={"silencio_activo": "on", "silencio_desde": "09:00", "silencio_hasta": "09:00"})
    assert db.obtener_perfil_usuario(uid)["silencio_desde"] is None


def test_no_molestar_cruza_la_medianoche(cliente):
    uid = _uid(cliente)
    db.guardar_perfil_usuario(uid, silencio_desde="22:00", silencio_hasta="08:00")
    esta = lambda h, m: db.en_horas_de_silencio(uid, ahora=datetime(2026, 10, 12, h, m))  # noqa: E731
    assert esta(23, 30) and esta(3, 0) and esta(7, 59) and esta(22, 0)
    assert not esta(8, 0) and not esta(12, 0) and not esta(21, 59)
    db.guardar_perfil_usuario(uid, silencio_desde="13:00", silencio_hasta="15:00")        # franja normal, sin cruzar
    assert esta(14, 0) and not esta(12, 59) and not esta(15, 0)
    db.guardar_perfil_usuario(uid, silencio_desde="", silencio_hasta="")
    assert not esta(14, 0)


def test_el_push_respeta_no_molestar_pero_la_prueba_lo_ignora(cliente, monkeypatch):
    uid = _uid(cliente)
    enviados = []
    monkeypatch.setattr(push, "configurado", lambda: True)
    monkeypatch.setattr(db, "tokens_push_de_usuario", lambda u: ["tok"])
    monkeypatch.setattr(push, "_enviar_a_token", lambda t, ti, cu, da: enviados.append(ti) or True)
    monkeypatch.setattr(db, "en_horas_de_silencio", lambda u, ahora=None: True)
    push.enviar_a_usuario(uid, "Aviso", "cuerpo")
    assert enviados == []
    push.enviar_a_usuario(uid, "Prueba", "cuerpo", ignorar_silencio=True)
    assert enviados == ["Prueba"]


def test_notificacion_de_prueba_llega_a_la_campana(cliente):
    uid = _uid(cliente)
    antes = db.contar_notificaciones_no_leidas(uid)
    r = cliente.post("/ajustes/perfil/prueba-notificacion")
    assert r.status_code == 302 and "aviso=prueba" in r.headers["Location"] and r.headers["Location"].endswith("#notificaciones")
    assert db.contar_notificaciones_no_leidas(uid) == antes + 1
    assert "Notificación de prueba enviada" in cliente.get("/ajustes/perfil?aviso=prueba").get_data(as_text=True)


def test_perfil_mis_datos_enlaza_las_exportaciones_que_existen(cliente):
    _uid(cliente)
    html = cliente.get("/ajustes/perfil").get_data(as_text=True)
    for destino in ("/export", "/tareas/exportar.csv", "/tareas/exportar.ics", "/papelera", "/mis-dispositivos", "/fichaje/mis-datos"):
        assert f'href="{destino}' in html, destino
        assert cliente.get(destino).status_code in (200, 302), destino


@pytest.mark.parametrize("valor,esperado", [("08:30", "08:30"), ("8:30", None), ("24:00", None), ("12:60", None), ("", None), (None, None), (" 07:05 ", "07:05")])
def test_hora_valida(valor, esperado):
    assert db._hora_valida(valor) == esperado


def test_ningun_script_en_linea_sale_con_el_nonce_vacio(cliente):
    """Regresión de la CSP forzada: `{% from "x.html" import macro %}` importa SIN el contexto de la petición, así que `{{ csp_nonce }}` salía vacío
    dentro de las macros (los comentarios de tareas) y el navegador bloqueaba su script. Las plantillas usan `g.csp_nonce`, que siempre existe."""
    import re
    from pathlib import Path

    for fichero in (Path(__file__).resolve().parent.parent / "app" / "templates").glob("*.html"):
        assert 'nonce="{{ csp_nonce }}"' not in fichero.read_text(encoding="utf-8"), f"{fichero.name}: usa g.csp_nonce"
    uid = _uid(cliente, "aj-nonce@x.com")
    tarea = db.crear_tarea_outlook(uid, "Con comentarios")
    for ruta in ("/", "/tareas/", f"/tareas/{tarea}/editar", f"/tareas/{tarea}", "/ajustes", "/ajustes/perfil", "/tareas/tablero"):
        r = cliente.get(ruta)
        if r.status_code != 200:
            continue
        html = r.get_data(as_text=True)
        assert 'nonce=""' not in html, ruta
        nonce_cabecera = re.search(r"nonce-([A-Za-z0-9_-]+)", r.headers.get("Content-Security-Policy", "") + r.headers.get("Content-Security-Policy-Report-Only", ""))
        for n in re.findall(r"<script nonce=\"([^\"]+)\"", html):
            assert nonce_cabecera and n == nonce_cabecera.group(1), ruta


# ---- Recuperar contraseña (flujo de Kratos) --------------------------------------------------------------------------------------
def _flujo_codigo_enviado():
    """Lo que devuelve Kratos tras pedir la recuperación con un email: paso «introduce el código»."""
    return {"ui": {
        "action": "http://127.0.0.1:4433/self-service/recovery?flow=abc",
        "messages": [{"id": 1060003, "type": "info", "text": "An email containing a recovery code has been sent to the email address you provided. If you have not received an email, check the spelling of the address and make sure to use the address you registered with."}],
        "nodes": [
            {"type": "input", "group": "default", "attributes": {"name": "csrf_token", "type": "hidden", "value": "tok", "node_type": "input"}, "messages": [], "meta": {}},
            {"type": "input", "group": "code", "attributes": {"name": "code", "type": "text", "node_type": "input", "required": True}, "messages": [], "meta": {"label": {"id": 1070010, "text": "Recovery code", "type": "info"}}},
            {"type": "input", "group": "code", "attributes": {"name": "method", "type": "hidden", "value": "code", "node_type": "input"}, "messages": [], "meta": {}},
            {"type": "input", "group": "code", "attributes": {"name": "method", "type": "submit", "value": "code", "node_type": "input"}, "messages": [], "meta": {"label": {"id": 1070009, "text": "Continue", "type": "info"}}},
            {"type": "input", "group": "code", "attributes": {"name": "email", "type": "submit", "value": "x@y.z", "node_type": "input"}, "messages": [], "meta": {"label": {"id": 1070008, "text": "Resend code", "type": "info"}}},
        ]}}


def test_la_pagina_de_recuperar_contrasena_sale_en_castellano_y_sin_campos_sueltos(cliente, monkeypatch):
    from app import kratos
    monkeypatch.setattr(kratos, "obtener_flujo", lambda tipo, flow_id, cookies: _flujo_codigo_enviado())
    html = cliente.get("/recuperar-contrasena?flow=abc").get_data(as_text=True)
    assert "Código de recuperación" in html and "Continuar" in html and "Reenviar el código" in html
    assert "Recovery code" not in html and ">Continue<" not in html and "Resend code" not in html
    assert "te hemos mandado un código de recuperación" in html
    assert '<div class="auth-info">' in html and 'class="ia-error"' not in html, "el aviso informativo no puede verse como un error"
    assert '<input type="hidden" name="method" value="code">' in html and 'for="recuperar-method"' not in html, "el campo oculto «method» ya no sale como etiqueta"
    assert "btn-ghost auth-submit" in html, "«Reenviar» es secundario"


def test_los_errores_de_recuperacion_siguen_siendo_errores_y_se_traducen(cliente, monkeypatch):
    from app import kratos
    flujo = _flujo_codigo_enviado()
    flujo["ui"]["messages"] = [{"id": 4060006, "type": "error", "text": "The recovery code is invalid or has already been used. Please try again."}]
    monkeypatch.setattr(kratos, "obtener_flujo", lambda tipo, flow_id, cookies: flujo)
    html = cliente.get("/recuperar-contrasena?flow=abc").get_data(as_text=True)
    assert 'class="ia-error" role="alert"' in html and "El código de recuperación no es válido o ya se ha usado" in html


def test_al_terminar_la_recuperacion_kratos_aterriza_en_una_ruta_que_existe(cliente):
    """Kratos redirige a /ajustes-cuenta (SELFSERVICE_FLOWS_SETTINGS_UI_URL) con el flujo de cambiar la contraseña; esa ruta daba 404."""
    r = cliente.get("/ajustes-cuenta?flow=abc")
    assert r.status_code != 404 and r.status_code in (301, 302), r.status_code     # sin sesión: al login, no un 404
    assert "/login" in r.headers["Location"]
    _uid(cliente, "aj-rec@x.com")
    from app import kratos
    assert cliente.get("/ajustes/cuenta").status_code in (200, 302)


def test_los_mensajes_de_kratos_se_traducen_a_cada_idioma(cliente):
    from app.main import _msg_kratos
    from flask_babel import force_locale
    from app.main import app
    with app.test_request_context("/"):
        with force_locale("es"):
            assert _msg_kratos({"text": "Continue"}) == "Continuar" and _msg_kratos("Resend code") == "Reenviar el código"
            assert _msg_kratos({"text": "Algo que no conocemos"}) == "Algo que no conocemos"
            assert _msg_kratos({"text": "The recovery flow expired 2.00 minutes ago, please try again."}).startswith("Ha pasado demasiado tiempo")
        with force_locale("en"):
            assert _msg_kratos({"text": "Continue"}) == "Continue"
        with force_locale("fr"):
            assert _msg_kratos({"text": "Recovery code"}) == "Code de récupération"
