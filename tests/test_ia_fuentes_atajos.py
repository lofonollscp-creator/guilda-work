"""Bloque 5: fuentes citadas, atajos de prompts y modo solo lectura del asistente."""
import json
from contextlib import contextmanager

import pytest

import mcp_tools as mt
from app import db, ia_asistente as a, ia_atajos, ia_fuentes
from app import ia_herramientas as h
from tests.conftest import iniciar_sesion_de_prueba


def _preparar(usuario_id, solo_lectura=False, autonomo=True):
    db.guardar_preferencias_ia(usuario_id, "modelo-de-prueba", autonomo, solo_lectura=solo_lectura)
    a.guardar_api_keys(usuario_id, ["clave-falsa"])


def _texto(t):
    return {"choices": [{"message": {"role": "assistant", "content": t}}]}


def _tool_calls(*llamadas):
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": tid, "type": "function", "function": {"name": n, "arguments": json.dumps(args)}}
        for tid, n, args in llamadas]}}]}


def _encolar(monkeypatch, *respuestas):
    cola = list(respuestas)
    enviados = []

    def falso(url, payload, api_key):
        enviados.append(payload)
        return cola.pop(0)

    monkeypatch.setattr(a, "_post_json", falso)
    return enviados


# --- fuentes ----------------------------------------------------------------

def test_extraer_fuentes_de_cada_tipo_y_solo_de_lectura():
    resultados = [
        ("listar_notas", json.dumps([{"id": 7, "titulo": "Acta", "texto": "x"}, {"id": 8, "texto": "<b>Sin</b> título"}])),
        ("listar_tareas", json.dumps([{"id": 3, "asunto": "Llamar"}])),
        ("listar_tareas_hoy", json.dumps({"vencidas": [{"id": 3, "asunto": "Llamar"}], "hoy": [{"id": 4, "asunto": "Enviar"}]})),
        ("listar_bandeja_entrada", json.dumps([{"id": 9, "cuenta_id": 2, "asunto": "Hola"}])),
        ("listar_clientes_fiscales", json.dumps([{"id": 5, "nombre": "Panadería"}])),
        ("crear_nota", json.dumps({"id": 99, "texto": "no es lectura"})),
        ("listar_notas", "esto no es json"),
        ("listar_notas", json.dumps({"error": "fallo"})),
    ]
    fuentes = ia_fuentes.extraer_fuentes(resultados, h.LECTURA)
    urls = [f["url"] for f in fuentes]
    assert urls == ["/nota/7/editar", "/nota/8/editar", "/tareas/3/editar", "/tareas/4/editar",
                    "/correo/?cuenta_id=2&mensaje_id=9", "/fiscal/clientes/5"]
    assert fuentes[1]["titulo"] == "Sin título"  # sin HTML
    assert all(f["url"].startswith("/") for f in fuentes)


def test_fuentes_tienen_tope_y_buscar_semantico(usuario_id):
    filas = [{"id": i, "asunto": f"T{i}"} for i in range(1, 30)]
    assert len(ia_fuentes.extraer_fuentes([("listar_tareas", json.dumps(filas))], h.LECTURA)) == ia_fuentes.MAX_FUENTES
    hits = [{"id": "nota-4", "texto": "algo"}, {"id": "tarea-2", "texto": "otra"}, {"id": "raro", "texto": "x"}]
    urls = [f["url"] for f in ia_fuentes.extraer_fuentes([("buscar_semantico", json.dumps(hits))], h.LECTURA)]
    assert urls == ["/nota/4/editar", "/tareas/2/editar"]


def test_el_mensaje_final_guarda_las_fuentes_del_turno(monkeypatch, usuario_id):
    _preparar(usuario_id)
    nota = mt.crear_nota("Reunión con el cliente", titulo="Acta")
    _encolar(monkeypatch, _tool_calls(("c1", "listar_notas", {})), _texto("Tienes una nota: Acta."))
    a.procesar_turno(usuario_id, "¿qué notas tengo?")
    ultimo = db.listar_mensajes_ia(usuario_id)[-1]
    fuentes = json.loads(ultimo["fuentes_json"])
    assert fuentes == [{"tipo": "nota", "titulo": "Acta", "url": f"/nota/{nota['id']}/editar"}]


def test_sin_herramientas_no_hay_fuentes_y_no_se_mezclan_turnos(monkeypatch, usuario_id):
    _preparar(usuario_id)
    mt.crear_nota("texto")
    _encolar(monkeypatch, _tool_calls(("c1", "listar_notas", {})), _texto("Una nota."), _texto("Hola de nuevo."))
    a.procesar_turno(usuario_id, "notas")
    a.procesar_turno(usuario_id, "gracias")
    assert db.listar_mensajes_ia(usuario_id)[-1]["fuentes_json"] is None


def test_las_fuentes_viajan_en_el_stream(monkeypatch, usuario_id):
    _preparar(usuario_id)
    nota = mt.crear_nota("x", titulo="T")
    tandas = [
        [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "listar_notas", "arguments": "{}"}}]}}]}],
        [{"choices": [{"delta": {"content": "Hecho."}}]}],
    ]
    cola = [iter(t) for t in tandas]
    monkeypatch.setattr(a, "_post_json_stream_con_fallback", lambda *args: cola.pop(0))
    eventos = list(a.procesar_turno_stream(usuario_id, "notas"))
    finales = [e["mensaje"] for e in eventos if e["tipo"] == "mensaje" and e["mensaje"]["rol"] == "assistant" and e["mensaje"]["contenido"]]
    assert json.loads(finales[-1]["fuentes_json"])[0]["url"] == f"/nota/{nota['id']}/editar"


# --- modo solo lectura ------------------------------------------------------

def test_solo_lectura_ofrece_unicamente_herramientas_de_lectura(monkeypatch, usuario_id):
    _preparar(usuario_id, solo_lectura=True)
    enviados = _encolar(monkeypatch, _texto("ok"))
    a.procesar_turno(usuario_id, "hola")
    nombres = {t["function"]["name"] for t in enviados[0]["tools"]}
    assert nombres == h.LECTURA
    # y sin el modo, se ofrece el catálogo completo
    db.guardar_preferencias_ia(usuario_id, "modelo-de-prueba", True, solo_lectura=False)
    enviados = _encolar(monkeypatch, _texto("ok"))
    a.procesar_turno(usuario_id, "otra vez")
    assert len(enviados[0]["tools"]) == len(h.HERRAMIENTAS)


def test_solo_lectura_rechaza_una_escritura_aunque_el_modelo_la_pida(monkeypatch, usuario_id):
    _preparar(usuario_id, solo_lectura=True, autonomo=True)
    _encolar(monkeypatch, _tool_calls(("c1", "crear_nota", {"texto": "no debería existir"})), _texto("No puedo."))
    resultado = a.procesar_turno(usuario_id, "crea una nota")
    assert resultado["pendiente"] is None  # ni siquiera pide confirmación
    assert db.historial(usuario_id) == [] or not any("no debería existir" in (f["texto"] or "") for f in db.historial(usuario_id))
    tool = [m for m in db.listar_mensajes_ia(usuario_id) if m["rol"] == "tool"][0]
    assert "solo lectura" in tool["contenido"]


def test_solo_lectura_en_stream_y_en_confirmacion_pendiente(monkeypatch, usuario_id):
    _preparar(usuario_id, solo_lectura=True, autonomo=False)
    cola = [iter([{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "crear_nota", "arguments": json.dumps({"texto": "zzz"})}}]}}]}]),
            iter([{"choices": [{"delta": {"content": "No puedo."}}]}])]
    monkeypatch.setattr(a, "_post_json_stream_con_fallback", lambda *args: cola.pop(0))
    eventos = list(a.procesar_turno_stream(usuario_id, "crea"))
    assert not any(e["tipo"] == "pendiente" for e in eventos)
    assert not any("zzz" in (f["texto"] or "") for f in db.historial(usuario_id))

    # Una acción que quedó pendiente ANTES de activar el modo no se ejecuta al confirmarla.
    db.guardar_preferencias_ia(usuario_id, "modelo-de-prueba", False, solo_lectura=False)
    _encolar(monkeypatch, _tool_calls(("c2", "crear_nota", {"texto": "pendiente zzz"})))
    assert a.procesar_turno(usuario_id, "crea otra")["pendiente"] is not None
    db.guardar_preferencias_ia(usuario_id, "modelo-de-prueba", False, solo_lectura=True)
    _encolar(monkeypatch, _texto("Vale."))
    a.confirmar_pendiente(usuario_id, True)
    assert not any("pendiente zzz" in (f["texto"] or "") for f in db.historial(usuario_id))


def test_preferencia_solo_lectura_desde_ajustes_web_y_api_sin_tocarla(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "b5-sl@ejemplo.com", "contrasena123")
    cliente.post("/ia/ajustes", data={"modelo": "m", "solo_lectura": "on"})
    assert db.obtener_preferencias_ia(uid)["solo_lectura"] == 1
    cliente.post("/ia/ajustes", data={"modelo": "m"})
    assert db.obtener_preferencias_ia(uid)["solo_lectura"] == 0
    db.guardar_preferencias_ia(uid, "m", False, solo_lectura=True)
    db.guardar_preferencias_ia(uid, "m2", True)  # cliente antiguo: no envía solo_lectura
    assert db.obtener_preferencias_ia(uid)["solo_lectura"] == 1


# --- atajos -----------------------------------------------------------------

def test_atajos_de_serie_mas_propios_con_limite_y_aislamiento(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "b5-atajos@ejemplo.com", "contrasena123")
    assert len(ia_atajos.atajos_para(uid)) == 6 and not any(x["propio"] for x in ia_atajos.atajos_para(uid))
    with pytest.raises(ValueError):
        db.crear_atajo_ia(uid, "", "algo")
    for i in range(db.IA_MAX_ATAJOS):
        db.crear_atajo_ia(uid, f"A{i}", f"Prompt {i}")
    with pytest.raises(ValueError):
        db.crear_atajo_ia(uid, "Extra", "x")
    assert len(ia_atajos.atajos_para(uid)) == 6 + db.IA_MAX_ATAJOS
    ajeno = db.crear_usuario_vinculado_a_kratos("b5-atajos-otro@ejemplo.com", "kratos-b5-otro")
    propio = db.listar_atajos_ia(uid)[0]["id"]
    assert db.eliminar_atajo_ia(ajeno, propio) is False
    assert db.eliminar_atajo_ia(uid, propio) is True


def test_atajos_en_pagina_ajustes_y_api(cliente):
    iniciar_sesion_de_prueba(cliente, "b5-ui@ejemplo.com", "contrasena123")
    cliente.post("/ia/ajustes/atajos", data={"titulo": "Mi atajo", "prompt": "Dime la hora"})
    html = cliente.get("/ia/").get_data(as_text=True)
    assert 'class="ia-atajo"' in html and "Mi atajo" in html and "Resumen de mi día" in html
    assert "Mi atajo" in cliente.get("/ia/ajustes").get_data(as_text=True)
    r = cliente.post("/ia/ajustes/atajos", data={"titulo": "", "prompt": "x"})
    assert r.status_code == 302 and "error=" in r.headers["Location"]
    atajo = db.listar_atajos_ia(db.usuario_local_id())  # no es el usuario de sesión: debe estar vacío
    assert atajo == []


def test_api_de_atajos_y_fuentes_en_mensajes(cliente):
    r = cliente.post("/api/v1/auth/registro", json={"email": "b5-api@ejemplo.com", "contrasena": "contrasena123"})
    cab = {"Authorization": f"Bearer {r.get_json()['data']['token']}"}
    assert len(cliente.get("/api/v1/ia/atajos", headers=cab).get_json()["data"]) == 6
    nuevo = cliente.post("/api/v1/ia/atajos", json={"titulo": "X", "prompt": "Y"}, headers=cab)
    assert nuevo.status_code == 201
    assert cliente.post("/api/v1/ia/atajos", json={"titulo": "", "prompt": "Y"}, headers=cab).status_code == 400
    assert cliente.delete(f"/api/v1/ia/atajos/{nuevo.get_json()['data']['id']}", headers=cab).status_code == 200
    assert cliente.delete("/api/v1/ia/atajos/99999", headers=cab).status_code == 404
    cliente.post("/api/v1/ia/ajustes", json={"modelo": "m", "modo_autonomo": False, "solo_lectura": True}, headers=cab)
    assert cliente.get("/api/v1/ia/ajustes", headers=cab).get_json()["data"]["solo_lectura"] == 1
