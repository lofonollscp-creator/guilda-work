"""Conversaciones del Asistente IA: varias por usuario, una activa. El resto
del código (y la app móvil) sigue usando "la conversación" = la activa."""
import json
import sqlite3

import pytest

from app import db, ia_asistente as a
from tests.conftest import iniciar_sesion_de_prueba


def _escribir(usuario_id, *textos):
    for t in textos:
        db.agregar_mensaje_ia(usuario_id, "user", contenido=t)
        db.agregar_mensaje_ia(usuario_id, "assistant", contenido=f"re: {t}")


def _contenidos(usuario_id):
    return [m["contenido"] for m in db.listar_mensajes_ia(usuario_id)]


def test_el_primer_mensaje_abre_una_conversacion_activa_con_titulo(usuario_id):
    assert db.listar_mensajes_ia(usuario_id) == []
    assert db.conversacion_ia_activa_id(usuario_id, crear=False) is None

    _escribir(usuario_id, "¿Qué vence esta semana?\nOtra línea")

    convs = db.listar_conversaciones_ia(usuario_id)
    assert len(convs) == 1 and convs[0]["activa"] == 1
    assert convs[0]["titulo"] == "¿Qué vence esta semana?"
    assert convs[0]["mensajes"] == 1


def test_titulo_largo_se_recorta_y_el_titulo_no_cambia_con_mensajes_posteriores(usuario_id):
    _escribir(usuario_id, "x" * 200, "segundo mensaje")
    titulo = db.listar_conversaciones_ia(usuario_id)[0]["titulo"]
    assert len(titulo) <= db.IA_TITULO_MAX_CARACTERES and titulo.endswith("…")


def test_nueva_conversacion_conserva_la_anterior(usuario_id):
    _escribir(usuario_id, "primera")
    primera = db.conversacion_ia_activa_id(usuario_id)

    db.vaciar_mensajes_ia(usuario_id)  # "Nueva conversación"

    assert db.listar_mensajes_ia(usuario_id) == []
    assert db.conversacion_ia_activa_id(usuario_id) != primera
    assert [m["contenido"] for m in db.listar_mensajes_ia(usuario_id, primera)][0] == "primera"
    _escribir(usuario_id, "segunda")
    assert _contenidos(usuario_id)[0] == "segunda"
    assert len(db.listar_conversaciones_ia(usuario_id)) == 2


def test_no_se_acumulan_conversaciones_vacias(usuario_id):
    _escribir(usuario_id, "algo")
    db.vaciar_mensajes_ia(usuario_id)
    db.vaciar_mensajes_ia(usuario_id)
    db.crear_conversacion_ia(usuario_id)
    assert len(db.listar_conversaciones_ia(usuario_id)) == 2


def test_activar_cambia_los_mensajes_que_ven_el_chat_y_el_asistente(usuario_id):
    _escribir(usuario_id, "tema A")
    a_id = db.conversacion_ia_activa_id(usuario_id)
    db.vaciar_mensajes_ia(usuario_id)
    _escribir(usuario_id, "tema B")

    assert db.activar_conversacion_ia(usuario_id, a_id) is True

    assert _contenidos(usuario_id) == ["tema A", "re: tema A"]
    # y los mensajes nuevos van a la conversación recién activada
    db.agregar_mensaje_ia(usuario_id, "user", contenido="sigo con A")
    assert _contenidos(usuario_id)[-1] == "sigo con A"
    assert sum(1 for c in db.listar_conversaciones_ia(usuario_id) if c["activa"]) == 1


def test_no_se_puede_tocar_la_conversacion_de_otro_usuario(usuario_id):
    otro = db.crear_usuario("otro-ia@ejemplo.com", "contrasena123")
    _escribir(otro, "privado")
    ajena = db.conversacion_ia_activa_id(otro)

    assert db.activar_conversacion_ia(usuario_id, ajena) is False
    assert db.renombrar_conversacion_ia(usuario_id, ajena, "mía") is False
    assert db.eliminar_conversacion_ia(usuario_id, ajena) is False
    assert _contenidos(otro) == ["privado", "re: privado"]
    assert db.listar_mensajes_ia(usuario_id) == []


def test_renombrar_limpia_el_titulo_y_rechaza_uno_vacio(usuario_id):
    _escribir(usuario_id, "algo")
    cid = db.conversacion_ia_activa_id(usuario_id)

    assert db.renombrar_conversacion_ia(usuario_id, cid, "  Cierre   del  trimestre  ") is True
    assert db.listar_conversaciones_ia(usuario_id)[0]["titulo"] == "Cierre del trimestre"
    with pytest.raises(ValueError):
        db.renombrar_conversacion_ia(usuario_id, cid, "   ")


def test_eliminar_la_activa_activa_la_mas_reciente_que_quede(usuario_id):
    _escribir(usuario_id, "uno")
    uno = db.conversacion_ia_activa_id(usuario_id)
    db.vaciar_mensajes_ia(usuario_id)
    _escribir(usuario_id, "dos")
    dos = db.conversacion_ia_activa_id(usuario_id)

    assert db.eliminar_conversacion_ia(usuario_id, dos) is True

    assert db.conversacion_ia_activa_id(usuario_id) == uno
    assert _contenidos(usuario_id)[0] == "uno"
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM ia_mensajes WHERE conversacion_id = ?", (dos,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_eliminar_la_unica_conversacion_deja_el_chat_vacio_y_se_abre_otra_al_escribir(usuario_id):
    _escribir(usuario_id, "solo")
    assert db.eliminar_conversacion_ia(usuario_id, db.conversacion_ia_activa_id(usuario_id)) is True

    assert db.listar_mensajes_ia(usuario_id) == []
    _escribir(usuario_id, "de nuevo")
    assert _contenidos(usuario_id)[0] == "de nuevo"


def test_tope_de_conversaciones_por_usuario_descarta_las_mas_antiguas(usuario_id, monkeypatch):
    monkeypatch.setattr(db, "IA_MAX_CONVERSACIONES_POR_USUARIO", 3)
    for n in range(5):
        _escribir(usuario_id, f"conv {n}")
        db.vaciar_mensajes_ia(usuario_id)
    _escribir(usuario_id, "última")

    convs = db.listar_conversaciones_ia(usuario_id)
    assert len(convs) == 3
    assert any(c["titulo"] == "última" and c["activa"] for c in convs)
    assert not any(c["titulo"] == "conv 0" for c in convs)


def test_migracion_agrupa_los_mensajes_anteriores_en_una_conversacion_activa(usuario_id):
    conn = db.get_connection()
    try:
        for rol, texto in (("user", "Resumen del día, por favor"), ("assistant", "Claro"), ("user", "Gracias")):
            conn.execute(
                "INSERT INTO ia_mensajes (usuario_id, rol, contenido, creado_en) VALUES (?, ?, ?, '2026-09-01T10:00:00')",
                (usuario_id, rol, texto),
            )
        conn.commit()
    finally:
        conn.close()
    assert db.conversacion_ia_activa_id(usuario_id, crear=False) is None  # aún sin migrar

    db.init_db()  # arranque del servidor: migración idempotente
    db.init_db()

    convs = db.listar_conversaciones_ia(usuario_id)
    assert len(convs) == 1 and convs[0]["activa"] == 1
    assert convs[0]["titulo"] == "Resumen del día, por favor"
    assert convs[0]["mensajes"] == 2
    assert _contenidos(usuario_id) == ["Resumen del día, por favor", "Claro", "Gracias"]


def test_una_confirmacion_pendiente_pertenece_a_su_conversacion(monkeypatch, usuario_id):
    db.guardar_preferencias_ia(usuario_id, "modelo-de-prueba", False)
    a.guardar_api_keys(usuario_id, ["clave-falsa"])
    llamada = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_1", "type": "function", "function": {"name": "crear_nota", "arguments": json.dumps({"texto": "x"})}}]}}]}
    monkeypatch.setattr(a, "_post_json", lambda url, payload, api_key: llamada)
    a.procesar_turno(usuario_id, "crea una nota")
    con_pendiente = db.conversacion_ia_activa_id(usuario_id)
    assert a.pendiente_actual(usuario_id) is not None

    db.vaciar_mensajes_ia(usuario_id)  # otra conversación: ya no hay nada pendiente
    assert a.pendiente_actual(usuario_id) is None
    respuesta = {"choices": [{"message": {"role": "assistant", "content": "hola"}}]}
    monkeypatch.setattr(a, "_post_json", lambda url, payload, api_key: respuesta)
    assert a.procesar_turno(usuario_id, "otra cosa")["pendiente"] is None

    db.activar_conversacion_ia(usuario_id, con_pendiente)  # al volver, la acción sigue esperando
    assert a.pendiente_actual(usuario_id)["tool_call_id"] == "call_1"


# --- Rutas web ---------------------------------------------------------------

def test_rutas_web_de_conversaciones(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "conv-web@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, db.crear_tenant("Despacho conv"))
    _escribir(uid, "primera charla")
    primera = db.conversacion_ia_activa_id(uid)
    cliente.post("/ia/vaciar")
    _escribir(uid, "segunda charla")

    datos = cliente.get("/ia/conversaciones").get_json()
    assert datos["ok"] and len(datos["conversaciones"]) == 2
    assert datos["activa"] != primera

    pagina = cliente.get("/ia/").get_data(as_text=True)
    assert 'id="ia-conv-select"' in pagina and "primera charla" in pagina and "segunda charla" in pagina

    assert cliente.post(f"/ia/conversaciones/{primera}/activar").status_code == 204
    assert _contenidos(uid)[0] == "primera charla"
    assert cliente.post(f"/ia/conversaciones/{primera}/renombrar", json={"titulo": "Charla A"}).status_code == 204
    assert cliente.post(f"/ia/conversaciones/{primera}/renombrar", json={"titulo": " "}).status_code == 400
    assert cliente.post(f"/ia/conversaciones/{primera}/eliminar").status_code == 204
    assert cliente.post(f"/ia/conversaciones/{primera}/activar").status_code == 404


def test_rutas_web_no_dejan_tocar_conversaciones_ajenas(cliente):
    iniciar_sesion_de_prueba(cliente, "conv-web2@ejemplo.com", "contrasena123")
    otro = db.crear_usuario("dueno-conv@ejemplo.com", "contrasena123")
    _escribir(otro, "privado")
    ajena = db.conversacion_ia_activa_id(otro)

    assert cliente.post(f"/ia/conversaciones/{ajena}/activar").status_code == 404
    assert cliente.post(f"/ia/conversaciones/{ajena}/eliminar").status_code == 404
    assert _contenidos(otro) == ["privado", "re: privado"]
