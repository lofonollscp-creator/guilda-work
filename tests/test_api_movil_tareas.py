"""Lo que la app móvil espera de la API de tareas (pantallas de lista y detalle, `mobile/lib/funciones/tareas/`): rutas, cuerpos y nombres de campo.
Si falla, la app se rompería: no es una prueba de la lógica de tareas (esa vive en `test_tareas_trabajo.py`), sino del contrato que la app usa."""
import io

from app import db
from tests.test_api_tareas import _tarea, _usuario


def _arranque(cliente, correo="movil-tareas@ejemplo.com"):
    t = db.crear_tenant("Despacho móvil tareas")
    h, uid = _usuario(cliente, correo, t)
    return h, uid


def test_lista_con_ambito_estado_busqueda_y_paginacion(cliente):
    h, _ = _arranque(cliente)
    for n in range(5):
        _tarea(cliente, h, f"Preparar modelo {n}")
    pagina = cliente.get("/api/v1/tareas-outlook?ambito=propias&limit=2&offset=0", headers=h)
    assert pagina.status_code == 200 and len(pagina.get_json()["data"]) == 2 and pagina.headers["X-Total-Count"] == "5"
    resto = cliente.get("/api/v1/tareas-outlook?ambito=propias&limit=2&offset=4", headers=h).get_json()["data"]
    assert len(resto) == 1                                                                         # página corta: la app sabe que no hay más
    fila = pagina.get_json()["data"][0]
    assert {"id", "asunto", "estado", "version", "prioridad", "fecha_vencimiento", "vencida", "motivo_bloqueo"} <= set(fila)
    assert len(cliente.get("/api/v1/tareas-outlook?q=modelo%203", headers=h).get_json()["data"]) >= 1
    assert cliente.get("/api/v1/tareas-outlook?estado=esperando", headers=h).get_json()["data"] == []
    assert cliente.get("/api/v1/tareas-outlook?ambito=inventado", headers=h).status_code == 400


def test_alta_rapida_con_fecha_y_prioridad(cliente):
    h, _ = _arranque(cliente, "alta@ejemplo.com")
    r = cliente.post("/api/v1/tareas-outlook", json={"asunto": "Llamar a Acme", "fecha_vencimiento": "2026-10-30", "prioridad": "alta"}, headers=h)
    assert r.status_code == 201
    d = r.get_json()["data"]
    assert d["asunto"] == "Llamar a Acme" and d["fecha_vencimiento"].startswith("2026-10-30") and d["prioridad"] == "alta" and d["estado"] == "no_iniciada"


def test_cambio_de_estado_con_version_motivo_y_conflicto(cliente):
    h, _ = _arranque(cliente, "estado@ejemplo.com")
    tid = _tarea(cliente, h, "Con estado")
    v = cliente.get(f"/api/v1/tareas-outlook/{tid}", headers=h).get_json()["data"]["version"]
    sin_motivo = cliente.post(f"/api/v1/tareas-outlook/{tid}/transiciones", json={"estado": "esperando", "version": v}, headers=h)
    assert sin_motivo.status_code == 400 and sin_motivo.get_json()["campo"] == "motivo"                 # la app lo pide antes, pero el servidor lo exige
    ok = cliente.post(f"/api/v1/tareas-outlook/{tid}/transiciones", json={"estado": "esperando", "motivo": "Falta el certificado", "version": v}, headers=h)
    assert ok.status_code == 200
    d = ok.get_json()["data"]
    assert d["estado"] == "esperando" and d["motivo_bloqueo"] == "Falta el certificado" and d["version"] > v
    viejo = cliente.post(f"/api/v1/tareas-outlook/{tid}/transiciones", json={"estado": "en_progreso", "version": v}, headers=h)
    assert viejo.status_code == 409
    cuerpo = viejo.get_json()
    assert cuerpo["codigo"] == "version_obsoleta" and cuerpo["version_actual"] == d["version"]          # lo que usa «aplicar igualmente»
    again = cliente.post(f"/api/v1/tareas-outlook/{tid}/transiciones", json={"estado": "en_progreso", "version": cuerpo["version_actual"]}, headers=h)
    assert again.status_code == 200 and again.get_json()["data"]["estado"] == "en_progreso"


def test_subtareas_checklist_y_comentarios_tienen_los_campos_que_lee_la_app(cliente):
    h, _ = _arranque(cliente, "detalle@ejemplo.com")
    tid = _tarea(cliente, h, "Con detalle")
    assert cliente.post(f"/api/v1/tareas-outlook/{tid}/subtareas", json={"asunto": "Pedir certificado"}, headers=h).status_code == 201
    sub = cliente.get(f"/api/v1/tareas-outlook/{tid}/subtareas", headers=h).get_json()["data"]
    assert sub["subtareas"][0]["asunto"] == "Pedir certificado" and {"id", "estado"} <= set(sub["subtareas"][0])
    # la padre no se completa con subtareas abiertas: la app enseña ese mensaje
    bloqueada = cliente.post(f"/api/v1/tareas-outlook/{tid}/transiciones", json={"estado": "completada"}, headers=h)
    assert bloqueada.status_code == 409 and bloqueada.get_json()["codigo"] == "subtareas_abiertas"
    sid = sub["subtareas"][0]["id"]
    assert cliente.post(f"/api/v1/tareas-outlook/{sid}/transiciones", json={"estado": "completada"}, headers=h).status_code == 200

    assert cliente.post(f"/api/v1/tareas-outlook/{tid}/checklist", json={"texto": "Comprobar NIF"}, headers=h).status_code == 201
    punto = cliente.get(f"/api/v1/tareas-outlook/{tid}/checklist", headers=h).get_json()["data"][0]
    assert punto["texto"] == "Comprobar NIF" and punto["hecha"] == 0
    assert cliente.post(f"/api/v1/checklist/{punto['id']}/alternar", headers=h).status_code == 200
    assert cliente.get(f"/api/v1/tareas-outlook/{tid}/checklist", headers=h).get_json()["data"][0]["hecha"] == 1

    assert cliente.post(f"/api/v1/tareas-outlook/{tid}/comentarios", json={"texto": "Ya lo tengo"}, headers=h).status_code in (200, 201)
    com = cliente.get(f"/api/v1/tareas-outlook/{tid}/comentarios", headers=h).get_json()["data"][0]
    assert com["texto"] == "Ya lo tengo" and com["creado_en"]


def test_adjuntos_se_suben_en_el_campo_adjunto_y_se_listan_y_descargan(cliente):
    h, _ = _arranque(cliente, "adjuntos@ejemplo.com")
    tid = _tarea(cliente, h, "Con adjuntos")
    r = cliente.post(f"/api/v1/tareas-outlook/{tid}/adjuntos", data={"adjunto": (io.BytesIO(b"hola"), "notas.txt")}, headers=h, content_type="multipart/form-data")
    assert r.status_code == 201 and r.get_json()["data"][0]["ok"] is True
    lista = cliente.get(f"/api/v1/tareas-outlook/{tid}/adjuntos", headers=h).get_json()["data"]
    assert lista[0]["nombre_archivo"] == "notas.txt" and lista[0]["tamano_bytes"] == 4 and lista[0]["id"]
    assert cliente.get(f"/api/v1/tareas-outlook/adjuntos/{lista[0]['id']}", headers=h).data == b"hola"
    assert cliente.delete(f"/api/v1/tareas-outlook/adjuntos/{lista[0]['id']}", headers=h).status_code == 200
