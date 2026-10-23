"""API de tareas completa (`app/rutas_api_tareas.py`) y las herramientas MCP de tareas nuevas."""
from datetime import datetime, timedelta
import pytest

import mcp_tools as mt
from app import db
from tests.test_rutas_api import _auth, _registrar


def _usuario(cliente, email, despacho=None):
    datos = _registrar(cliente, email=email)
    uid = datos["usuario"]["id"]
    if despacho is not None:
        db.asignar_tenant(uid, despacho)
    return _auth(datos["token"]), uid


def _tarea(cliente, h, asunto="Tarea", **extra):
    return cliente.post("/api/v1/tareas-outlook", json={"asunto": asunto, **extra}, headers=h).get_json()["data"]["id"]


def test_estado_respeta_dependencias_y_valida(cliente):
    h, _ = _usuario(cliente, "e@ejemplo.com")
    a, b = _tarea(cliente, h, "A"), _tarea(cliente, h, "B")
    assert cliente.post(f"/api/v1/tareas-outlook/{b}/dependencias", json={"depende_de_id": a}, headers=h).get_json()["data"]["bloqueada"] is True
    r = cliente.post(f"/api/v1/tareas-outlook/{b}/estado", json={"estado": "en_progreso"}, headers=h)
    assert r.status_code == 409 and r.get_json()["codigo"] == "tarea_bloqueada"
    assert cliente.post(f"/api/v1/tareas-outlook/{b}/completar", headers=h).get_json()["codigo"] == "tarea_bloqueada"      # también el endpoint antiguo
    assert cliente.post(f"/api/v1/tareas-outlook/{a}/estado", json={"estado": "completada"}, headers=h).get_json()["data"]["estado"] == "completada"
    assert cliente.post(f"/api/v1/tareas-outlook/{b}/estado", json={"estado": "en_progreso"}, headers=h).get_json()["data"]["estado"] == "en_progreso"
    assert cliente.post(f"/api/v1/tareas-outlook/{b}/estado", json={"estado": "inventado"}, headers=h).get_json()["codigo"] == "estado_invalido"
    assert cliente.get(f"/api/v1/tareas-outlook/{b}/dependencias", headers=h).get_json()["data"]["bloqueada"] is False
    assert cliente.post(f"/api/v1/tareas-outlook/{a}/dependencias", json={"depende_de_id": b}, headers=h).get_json()["codigo"] == "dependencia_invalida"   # ciclo
    assert cliente.delete(f"/api/v1/tareas-outlook/{b}/dependencias/{a}", headers=h).status_code == 200
    assert cliente.delete(f"/api/v1/tareas-outlook/{b}/dependencias/{a}", headers=h).status_code == 404
    assert cliente.post("/api/v1/tareas-outlook/9999/estado", json={"estado": "completada"}, headers=h).status_code == 404


def test_comentarios_visibilidad_y_menciones(cliente):
    t = db.crear_tenant("Despacho comentarios")
    h1, u1 = _usuario(cliente, "c1@ejemplo.com", t)
    h2, u2 = _usuario(cliente, "c2@ejemplo.com", t)
    h3, _ = _usuario(cliente, "c3@ejemplo.com", db.crear_tenant("Otro"))
    tarea = _tarea(cliente, h1)
    assert cliente.post(f"/api/v1/tareas-outlook/{tarea}/comentarios", json={"texto": "  "}, headers=h1).get_json()["codigo"] == "comentario_vacio"
    assert cliente.post(f"/api/v1/tareas-outlook/{tarea}/comentarios", json={"texto": "hola"}, headers=h2).status_code == 404       # no la ve
    cliente.post(f"/api/v1/tareas-outlook/{tarea}/asignar", json={"companero_id": u2}, headers=h1)
    r = cliente.post(f"/api/v1/tareas-outlook/{tarea}/comentarios", json={"texto": "lo miro hoy"}, headers=h2)
    assert r.status_code == 201 and r.get_json()["data"]["texto"] == "lo miro hoy"
    lista = cliente.get(f"/api/v1/tareas-outlook/{tarea}/comentarios", headers=h1).get_json()["data"]
    assert [c["texto"] for c in lista] == ["lo miro hoy"]
    assert cliente.get(f"/api/v1/tareas-outlook/{tarea}/comentarios", headers=h3).status_code == 404
    assert cliente.delete(f"/api/v1/tareas-outlook/{tarea}/comentarios/{lista[0]['id']}", headers=h3).status_code == 404
    assert cliente.delete(f"/api/v1/tareas-outlook/{tarea}/comentarios/{lista[0]['id']}", headers=h2).status_code == 200
    assert cliente.get(f"/api/v1/tareas-outlook/{tarea}/actividad", headers=h1).status_code == 200
    avisos = [n["titulo"] for n in db.listar_notificaciones(u2, 20)]
    assert "Tarea asignada" in avisos                                                                                        # la asignación por API avisa


def test_compartir_y_participantes(cliente):
    t = db.crear_tenant("Despacho compartir")
    h1, u1 = _usuario(cliente, "s1@ejemplo.com", t)
    h2, u2 = _usuario(cliente, "s2@ejemplo.com", t)
    _, u3 = _usuario(cliente, "s3@ejemplo.com", db.crear_tenant("Otro2"))
    tarea = _tarea(cliente, h1)
    assert cliente.post(f"/api/v1/tareas-outlook/{tarea}/compartir", json={"usuario_id": u3}, headers=h1).status_code == 403          # otro despacho
    assert cliente.post(f"/api/v1/tareas-outlook/{tarea}/compartir", json={"usuario_id": u2, "rol": "jefe"}, headers=h1).status_code == 403
    r = cliente.post(f"/api/v1/tareas-outlook/{tarea}/compartir", json={"usuario_id": u2, "rol": "observa"}, headers=h1)
    assert r.status_code == 201 and len(r.get_json()["data"]) == 1
    assert cliente.get(f"/api/v1/tareas-outlook/{tarea}", headers=h2).status_code == 200
    assert cliente.post(f"/api/v1/tareas-outlook/{tarea}/compartir", json={"usuario_id": u1}, headers=h2).status_code == 403          # solo el dueño
    assert cliente.delete(f"/api/v1/tareas-outlook/{tarea}/compartir/{u2}", headers=h2).status_code == 200                           # él mismo se sale
    assert cliente.get(f"/api/v1/tareas-outlook/{tarea}", headers=h2).status_code == 404


def test_recordatorios_y_cronometro(cliente):
    h, _ = _usuario(cliente, "r@ejemplo.com")
    proyecto = cliente.post("/api/v1/proyectos", json={"nombre": "P"}, headers=h).get_json()["data"]["id"]
    tarea = _tarea(cliente, h, fecha_vencimiento="2030-01-10")
    assert cliente.post(f"/api/v1/tareas-outlook/{tarea}/recordatorios", json={"avisar_en": "no es fecha"}, headers=h).get_json()["codigo"] == "recordatorio_invalido"
    r = cliente.post(f"/api/v1/tareas-outlook/{tarea}/recordatorios", json={"avisar_en": "2030-01-09T09:00", "canales": ["app"]}, headers=h)
    assert r.status_code == 201 and len(r.get_json()["data"]) == 1
    rid = r.get_json()["data"][0]["id"]
    assert cliente.delete(f"/api/v1/tareas-outlook/recordatorios/{rid}", headers=h).status_code == 200
    assert cliente.delete(f"/api/v1/tareas-outlook/recordatorios/{rid}", headers=h).status_code == 404
    sin_proyecto = cliente.post(f"/api/v1/tareas-outlook/{tarea}/cronometro/iniciar", json={}, headers=h)
    assert sin_proyecto.status_code == 400 and sin_proyecto.get_json()["codigo"] == "cronometro_no_iniciado"
    ok = cliente.post(f"/api/v1/tareas-outlook/{tarea}/cronometro/iniciar", json={"proyecto_id": proyecto}, headers=h)
    assert ok.status_code == 201 and ok.get_json()["data"]["tarea_cronometro_id"]
    assert cliente.get(f"/api/v1/tareas-outlook/{tarea}/tiempo", headers=h).status_code == 200
    assert cliente.get(f"/api/v1/tareas", headers=h).status_code == 200                                                              # la tarea con duración existe


def test_lote_tablero_y_restaurar(cliente):
    t = db.crear_tenant("Despacho lote")
    h, u = _usuario(cliente, "l@ejemplo.com", t)
    _, otro = _usuario(cliente, "l2@ejemplo.com", t)
    ids = [_tarea(cliente, h, f"T{i}") for i in range(3)]
    assert cliente.post("/api/v1/tareas-outlook/lote", json={"ids": [], "accion": "completar"}, headers=h).get_json()["codigo"] == "peticion_invalida"
    assert cliente.post("/api/v1/tareas-outlook/lote", json={"ids": ids, "accion": "inventada"}, headers=h).get_json()["codigo"] == "accion_invalida"
    r = cliente.post("/api/v1/tareas-outlook/lote", json={"ids": ids[:2] + [9999], "accion": "prioridad", "valor": "alta"}, headers=h).get_json()["data"]
    assert r == {"ok": 2, "fallos": 1}
    cliente.post("/api/v1/tareas-outlook/lote", json={"ids": [ids[2]], "accion": "asignar", "valor": str(otro)}, headers=h)
    assert any(n["titulo"] == "Tarea asignada" for n in db.listar_notificaciones(otro, 10))
    cliente.post("/api/v1/tareas-outlook/lote", json={"ids": ids[:1], "accion": "completar"}, headers=h)
    tablero = cliente.get("/api/v1/tareas-outlook/tablero", headers=h).get_json()["data"]
    assert [x["id"] for x in tablero["completada"]] == [ids[0]] and len(tablero["no_iniciada"]) == 2 and set(tablero) >= {"esperando", "aplazada", "en_progreso"}
    cliente.delete(f"/api/v1/tareas-outlook/{ids[1]}", headers=h)
    assert cliente.get(f"/api/v1/tareas-outlook/{ids[1]}", headers=h).status_code == 404
    assert cliente.post(f"/api/v1/tareas-outlook/{ids[1]}/restaurar", headers=h).status_code == 200
    assert cliente.get(f"/api/v1/tareas-outlook/{ids[1]}", headers=h).status_code == 200


def test_vistas_y_plantillas(cliente):
    t = db.crear_tenant("Despacho vistas")
    h1, _ = _usuario(cliente, "v1@ejemplo.com", t)
    h2, _ = _usuario(cliente, "v2@ejemplo.com", t)
    assert cliente.post("/api/v1/tareas-outlook/vistas", json={"nombre": "x", "filtros": {}}, headers=h1).get_json()["codigo"] == "vista_invalida"
    v = cliente.post("/api/v1/tareas-outlook/vistas", json={"nombre": "Urgentes", "filtros": {"prioridad": "alta", "basura": "x"}, "compartida": True}, headers=h1).get_json()["data"]
    assert v["filtros"] == {"prioridad": "alta"} and v["compartida"] is True and v["mia"] is True
    assert [x["nombre"] for x in cliente.get("/api/v1/tareas-outlook/vistas", headers=h2).get_json()["data"]] == ["Urgentes"]      # compartida con el despacho
    assert cliente.delete(f"/api/v1/tareas-outlook/vistas/{v['id']}", headers=h2).status_code == 404                                # no es suya
    assert cliente.delete(f"/api/v1/tareas-outlook/vistas/{v['id']}", headers=h1).status_code == 200
    assert cliente.post("/api/v1/tareas-plantillas", json={"nombre": "", "items": []}, headers=h1).get_json()["codigo"] == "plantilla_invalida"
    p = cliente.post("/api/v1/tareas-plantillas", json={"nombre": "Alta de cliente", "items": ["Pedir DNI", "Firmar mandato", "Dar de alta"]}, headers=h1).get_json()["data"]
    assert len(p["items"]) == 3
    assert cliente.put(f"/api/v1/tareas-plantillas/{p['id']}", json={"nombre": "Alta cliente v2"}, headers=h1).get_json()["data"]["nombre"] == "Alta cliente v2"
    assert cliente.put(f"/api/v1/tareas-plantillas/{p['id']}", json={"nombre": "x"}, headers=h2).status_code == 404
    r = cliente.post(f"/api/v1/tareas-plantillas/{p['id']}/aplicar", json={"fecha_inicio": "2030-03-01", "nuevo_proyecto": "Alta Acme", "encadenar": True}, headers=h1)
    assert r.status_code == 201 and len(r.get_json()["data"]["tareas_creadas"]) == 3
    ultima = r.get_json()["data"]["tareas_creadas"][-1]
    assert cliente.get(f"/api/v1/tareas-outlook/{ultima}/dependencias", headers=h1).get_json()["data"]["bloqueada"] is True      # encadenadas
    assert cliente.post("/api/v1/tareas-plantillas/9999/aplicar", json={}, headers=h1).status_code == 404
    assert cliente.delete(f"/api/v1/tareas-plantillas/{p['id']}", headers=h1).status_code == 200


def test_recurrentes_y_reglas_por_vencimiento(cliente):
    t = db.crear_tenant("Despacho reglas")
    h, u = _usuario(cliente, "rr@ejemplo.com", t)
    for malo in ({"asunto": "", "periodicidad": "diaria"}, {"asunto": "x", "periodicidad": "cada_rato"}, {"asunto": "x", "periodicidad": "semanal", "dia": 9},
                 {"asunto": "x", "periodicidad": "mensual", "dia": 0}, {"asunto": "x", "periodicidad": "anual", "dia": 5}):
        assert cliente.post("/api/v1/tareas-recurrentes", json=malo, headers=h).status_code == 400, malo
    r = cliente.post("/api/v1/tareas-recurrentes", json={"asunto": "Revisar IVA", "periodicidad": "trimestral", "dia": 15}, headers=h)
    assert r.status_code == 201
    rid = r.get_json()["data"]["id"]
    assert cliente.post("/api/v1/tareas-recurrentes", json={"asunto": "Diaria", "periodicidad": "diaria"}, headers=h).status_code == 201
    assert len(cliente.get("/api/v1/tareas-recurrentes", headers=h).get_json()["data"]) == 2
    assert cliente.post(f"/api/v1/tareas-recurrentes/{rid}/alternar", headers=h).get_json()["data"]["activa"] == 0
    assert cliente.post("/api/v1/tareas-recurrentes/999/alternar", headers=h).status_code == 404
    assert cliente.delete(f"/api/v1/tareas-recurrentes/{rid}", headers=h).status_code == 200
    # reglas por vencimiento
    assert cliente.post("/api/v1/tareas-reglas-vencimiento", json={"modelo": "", "asunto": ""}, headers=h).get_json()["codigo"] == "regla_invalida"
    assert cliente.post("/api/v1/tareas-reglas-vencimiento", json={"modelo": "303", "asunto": "x", "crear_dias_antes": 2, "vence_dias_antes": 9}, headers=h).status_code == 400
    c = db.crear_cliente_fiscal(t, "Acme SL")
    conn = db.get_connection()
    conn.execute("INSERT INTO vencimientos_fiscales (tenant_id, cliente_fiscal_id, modelo, periodo, fecha_limite, estado, creado_en) VALUES (?, ?, '303', '3T', ?, 'pendiente', ?)", (t, c, (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d"), db.now_iso()))
    conn.commit(); conn.close()
    r = cliente.post("/api/v1/tareas-reglas-vencimiento", json={"modelo": "303", "asunto": "Preparar {modelo} de {cliente}", "estimacion": "2h", "prioridad": "alta"}, headers=h)
    assert r.status_code == 201 and r.get_json()["data"]["estimacion_min"] == 120
    regla = r.get_json()["data"]["id"]
    asuntos = [x["asunto"] for x in cliente.get("/api/v1/tareas-outlook", headers=h).get_json()["data"]]
    assert any("Preparar 303 de Acme SL" in a for a in asuntos)                                                                      # se generó al momento
    assert cliente.post(f"/api/v1/tareas-reglas-vencimiento/{regla}/alternar", headers=h).get_json()["data"]["activa"] == 0
    assert cliente.delete(f"/api/v1/tareas-reglas-vencimiento/{regla}", headers=h).status_code == 200
    assert cliente.get("/api/v1/tareas-reglas-vencimiento", headers=h).get_json()["data"] == []


def test_carga_semanal_y_mover(cliente):
    t = db.crear_tenant("Despacho carga")
    h, u = _usuario(cliente, "ca@ejemplo.com", t)
    _, otro = _usuario(cliente, "ca2@ejemplo.com", t)
    _, ajeno = _usuario(cliente, "ca3@ejemplo.com", db.crear_tenant("Otro3"))
    tarea = _tarea(cliente, h, fecha_vencimiento="2030-01-08", estimacion_min=60)
    c = cliente.get("/api/v1/tareas-outlook/carga?semana=2030-01-09", headers=h).get_json()["data"]
    assert c["lunes"] == "2030-01-07" and len(c["dias"]) == 7 and c["personas"]
    assert cliente.get("/api/v1/tareas-outlook/carga?semana=xx", headers=h).get_json()["codigo"] == "peticion_invalida"
    assert cliente.post(f"/api/v1/tareas-outlook/{tarea}/mover", json={}, headers=h).status_code == 400
    assert cliente.post(f"/api/v1/tareas-outlook/{tarea}/mover", json={"persona_id": ajeno}, headers=h).status_code == 403
    r = cliente.post(f"/api/v1/tareas-outlook/{tarea}/mover", json={"persona_id": otro, "fecha": "2030-01-10"}, headers=h).get_json()["data"]
    assert r["asignada_a"] == otro and r["fecha_vencimiento"].startswith("2030-01-10")


def test_checklist_borrar_y_permisos_de_solo_lectura(cliente):
    h, _ = _usuario(cliente, "ck@ejemplo.com")
    tarea = _tarea(cliente, h)
    item = cliente.post(f"/api/v1/tareas-outlook/{tarea}/checklist", json={"texto": "x"}, headers=h).get_json()["data"]["id"]
    ro = _auth(cliente.post("/api/v1/tokens", json={"permisos": "solo_lectura", "areas": ["tareas"]}, headers=h).get_json()["data"]["token"])
    for ruta in ("/api/v1/tareas-outlook/lote", f"/api/v1/tareas-outlook/{tarea}/estado", f"/api/v1/tareas-outlook/{tarea}/comentarios"):
        assert cliente.post(ruta, json={"estado": "completada"}, headers=ro).get_json()["codigo"] == "token_solo_lectura", ruta
    assert cliente.get("/api/v1/tareas-recurrentes", headers=ro).status_code == 200                                                  # área tareas cubre las rutas nuevas
    assert cliente.get("/api/v1/tareas-plantillas", headers=ro).status_code == 200
    assert cliente.delete(f"/api/v1/checklist/{item}", headers=h).status_code == 200
    assert cliente.delete(f"/api/v1/checklist/{item}", headers=h).status_code == 404
    solo_notas = _auth(cliente.post("/api/v1/tokens", json={"areas": ["notas"]}, headers=h).get_json()["data"]["token"])
    assert cliente.get("/api/v1/tareas-plantillas", headers=solo_notas).get_json()["codigo"] == "token_area_no_permitida"


def test_openapi_incluye_las_rutas_de_tareas(cliente):
    paths = cliente.get("/api/v1/openapi.json").get_json()["paths"]
    for ruta in ("/api/v1/tareas-outlook/{tarea_id}/estado", "/api/v1/tareas-outlook/lote", "/api/v1/tareas-plantillas/{plantilla_id}/aplicar",
                 "/api/v1/tareas-recurrentes", "/api/v1/tareas-reglas-vencimiento", "/api/v1/tareas-outlook/carga", "/api/v1/tareas-outlook/vistas"):
        assert ruta in paths, ruta


# --- MCP ---------------------------------------------------------------------------------------------------------------------

def test_herramientas_mcp_de_tareas():
    t = db.crear_tenant("Despacho MCP tareas")
    u = db.crear_usuario_vinculado_a_kratos("m@ejemplo.com", "k-m"); db.asignar_tenant(u, t)
    ctx = mt._usuario_id_actual.set(u)
    try:
        a, b = db.crear_tarea_outlook(u, "A"), db.crear_tarea_outlook(u, "B")
        db.anadir_dependencia_tarea(u, b, a)
        with pytest.raises(ValueError, match="espera a otras"):
            mt.cambiar_estado_tarea(b, "completada")
        with pytest.raises(ValueError, match="estado debe ser"):
            mt.cambiar_estado_tarea(a, "raro")
        assert mt.cambiar_estado_tarea(a, "completada")["estado"] == "completada"
        assert mt.cambiar_estado_tarea(b, "en_progreso")["estado"] == "en_progreso"
        assert mt.comentar_tarea(a, "hecho")["comentarios"][-1]["texto"] == "hecho"
        with pytest.raises(ValueError, match="vacío"):
            mt.comentar_tarea(a, " ")
        assert [c["texto"] for c in mt.listar_comentarios_tarea(a)] == ["hecho"]
        with pytest.raises(ValueError, match="No existe"):
            mt.listar_comentarios_tarea(9999)
        p = db.crear_categoria(u, "Proyecto X", None)
        assert mt.iniciar_cronometro_tarea(b, proyecto="Proyecto X")["tarea_cronometro_id"]
    finally:
        mt._usuario_id_actual.reset(ctx)
