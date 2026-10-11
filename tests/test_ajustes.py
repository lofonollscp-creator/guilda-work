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
