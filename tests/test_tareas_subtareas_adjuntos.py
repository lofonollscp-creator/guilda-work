"""Fase 3 del plan: subtareas con reglas de cierre y adjuntos de tarea (app/tareas_trabajo.py)."""
import io

from app import db, tareas_trabajo as tt
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_api_tareas import _tarea, _usuario


def _despacho(cliente, correo, nombre):
    t = db.crear_tenant(nombre)
    h, uid = _usuario(cliente, correo, t)
    return t, h, uid


def _sub(cliente, h, padre, asunto="Subtarea", **extra):
    return cliente.post(f"/api/v1/tareas-outlook/{padre}/subtareas", json={"asunto": asunto, **extra}, headers=h)


def _estado(cliente, h, tid, estado):
    return cliente.post(f"/api/v1/tareas-outlook/{tid}/estado", json={"estado": estado}, headers=h)


def _subir(cliente, h, tid, nombre, contenido=b"%PDF-1.4 contenido", campo="adjunto"):
    return cliente.post(f"/api/v1/tareas-outlook/{tid}/adjuntos", data={campo: (io.BytesIO(contenido), nombre)}, headers=h, content_type="multipart/form-data")


# --- Subtareas -------------------------------------------------------------------------------------------------------

def test_crear_subtarea_hereda_cliente_y_solo_un_nivel(cliente):
    t, h, uid = _despacho(cliente, "s1@ejemplo.com", "Despacho subtareas")
    c = db.crear_cliente_fiscal(t, "Cliente Padre SL")
    padre = db.crear_tarea_outlook(uid, asunto="Padre", cliente_fiscal_id=c)
    r = _sub(cliente, h, padre, "Pedir el certificado", fecha_vencimiento="2026-11-05")
    assert r.status_code == 201
    hija = r.get_json()["data"]
    assert hija["cliente_fiscal_id"] == c and hija["fecha_vencimiento"].startswith("2026-11-05")
    assert [x["id"] for x in tt.clientes_de_tarea(hija["id"])] == [c]               # el vínculo principal se crea solo
    r = _sub(cliente, h, hija["id"], "Nieta")
    assert r.status_code == 409 and r.get_json()["codigo"] == "subtarea_de_subtarea"
    assert _sub(cliente, h, padre, "   ").get_json()["codigo"] == "asunto_vacio"
    assert _sub(cliente, h, 999999).status_code == 404
    datos = cliente.get(f"/api/v1/tareas-outlook/{padre}/subtareas", headers=h).get_json()["data"]
    assert datos["progreso"] == {"total": 1, "hechas": 0, "abiertas": 1} and datos["subtareas"][0]["id"] == hija["id"]


def test_el_padre_no_se_completa_con_subtareas_abiertas_por_ningun_camino(cliente):
    t, h, uid = _despacho(cliente, "s2@ejemplo.com", "Despacho cierre")
    padre = _tarea(cliente, h, "Padre")
    hija = _sub(cliente, h, padre).get_json()["data"]["id"]
    for r in (_estado(cliente, h, padre, "completada"),
              cliente.post(f"/api/v1/tareas-outlook/{padre}/completar", headers=h),
              cliente.post(f"/api/v1/tareas-outlook/{padre}/transiciones", json={"estado": "completada"}, headers=h)):
        assert r.status_code == 409 and r.get_json()["codigo"] == "subtareas_abiertas"
    assert db.obtener_tarea_outlook(uid, padre)["estado"] == "no_iniciada"
    assert db.cambiar_estado_tarea_outlook(uid, padre, "completada") is False            # tampoco por el núcleo (MCP, lote, web)
    db.completar_tarea_outlook(uid, padre)
    assert db.obtener_tarea_outlook(uid, padre)["estado"] == "no_iniciada"
    assert _estado(cliente, h, padre, "en_progreso").status_code == 200                  # el padre sí puede estar en curso
    assert _estado(cliente, h, hija, "completada").status_code == 200
    assert db.obtener_tarea_outlook(uid, padre)["estado"] == "en_progreso"                # completar la última NO completa el padre solo
    assert _estado(cliente, h, padre, "completada").status_code == 200


def test_reabrir_una_subtarea_reabre_el_padre_completado(cliente):
    t, h, uid = _despacho(cliente, "s3@ejemplo.com", "Despacho reapertura")
    padre = _tarea(cliente, h, "Padre")
    hija = _sub(cliente, h, padre).get_json()["data"]["id"]
    _estado(cliente, h, hija, "completada")
    _estado(cliente, h, padre, "completada")
    assert _estado(cliente, h, hija, "en_progreso").status_code == 200
    p = db.obtener_tarea_outlook(uid, padre)
    assert p["estado"] == "en_progreso" and p["fecha_completada"] is None
    assert any(a["tipo"] == "reabierta_por_subtarea" for a in cliente.get(f"/api/v1/tareas-outlook/{padre}/actividad", headers=h).get_json()["data"])
    # reabrir una subtarea cuyo padre no estaba completado no toca al padre
    otra = _sub(cliente, h, padre, "Otra").get_json()["data"]["id"]
    _estado(cliente, h, otra, "completada")
    _estado(cliente, h, otra, "no_iniciada")
    assert db.obtener_tarea_outlook(uid, padre)["estado"] == "en_progreso"


def test_no_se_anaden_subtareas_a_una_completada_ni_sin_permiso(cliente):
    t, h, uid = _despacho(cliente, "s4@ejemplo.com", "Despacho permisos sub")
    h2, u2 = _usuario(cliente, "s4b@ejemplo.com", t)
    padre = _tarea(cliente, h, "Padre")
    cliente.post(f"/api/v1/tareas-outlook/{padre}/compartir", json={"usuario_id": u2, "rol": "observa"}, headers=h)
    r = _sub(cliente, h2, padre)
    assert r.status_code == 403 and r.get_json()["codigo"] == "sin_permiso"
    _estado(cliente, h, padre, "completada")
    r = _sub(cliente, h, padre)
    assert r.status_code == 409 and r.get_json()["codigo"] == "padre_completada"
    ajeno = _despacho(cliente, "s4c@ejemplo.com", "Despacho ajeno sub")[1]
    assert _sub(cliente, ajeno, padre).status_code == 404


def test_papelera_arrastra_las_subtareas_y_restaurar_solo_las_que_se_fueron_con_el_padre(cliente):
    t, h, uid = _despacho(cliente, "s5@ejemplo.com", "Despacho papelera")
    padre = _tarea(cliente, h, "Padre")
    a = _sub(cliente, h, padre, "A").get_json()["data"]["id"]
    b = _sub(cliente, h, padre, "B").get_json()["data"]["id"]
    db.eliminar_tarea_outlook(uid, b)                                    # B se borró antes, aparte
    assert tt.subtareas_abiertas(padre) == 1                             # una subtarea en la papelera no cuenta
    db.eliminar_tarea_outlook(uid, padre)
    assert db.obtener_tarea_outlook(uid, a) is None
    db.restaurar_tarea_outlook(uid, padre)
    assert db.obtener_tarea_outlook(uid, a) is not None                   # A volvió con el padre
    assert db.obtener_tarea_outlook(uid, b) is None                       # B sigue donde la dejaron
    db.eliminar_tarea_outlook(uid, padre)
    db.eliminar_tarea_outlook_definitivamente(uid, padre)
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM tareas_outlook WHERE id IN (?, ?, ?)", (padre, a, b)).fetchone()[0] == 0       # el borrado definitivo del padre no deja subtareas huérfanas, ni siquiera la ya enviada a la papelera
    finally:
        conn.close()


def test_web_no_deja_completar_el_padre_con_subtareas_abiertas(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "s6@ejemplo.com", "contrasena123")
    padre = db.crear_tarea_outlook(uid, asunto="Padre web")
    tt.crear_subtarea(uid, padre, "Pendiente")
    cliente.post(f"/tareas/{padre}/estado", data={"estado": "completada"})
    assert db.obtener_tarea_outlook(uid, padre)["estado"] == "no_iniciada"
    datos = {"asunto": "Padre web", "estado": "completada", "prioridad": "normal", "porcentaje_completado": "0", "version": str(db.obtener_tarea_outlook(uid, padre)["version"])}
    r = cliente.post(f"/tareas/{padre}/editar", data=datos)
    assert "tiene subtareas sin completar" in r.get_data(as_text=True)
    assert db.obtener_tarea_outlook(uid, padre)["estado"] == "no_iniciada"
    html = cliente.get(f"/tareas/{padre}").get_data(as_text=True)
    assert 'id="subtareas"' in html and "Pendiente" in html and "0/1" in html
    r = cliente.post(f"/tareas/{padre}/subtareas", data={"asunto": "Desde la web"})
    assert r.status_code == 302 and tt.progreso_subtareas(tt.subtareas_de(padre))["total"] == 2


# --- Adjuntos --------------------------------------------------------------------------------------------------------

def test_subir_listar_y_descargar_un_adjunto_con_cabeceras_seguras(cliente):
    t, h, uid = _despacho(cliente, "a1@ejemplo.com", "Despacho adjuntos")
    tid = _tarea(cliente, h, "Con archivos")
    r = _subir(cliente, h, tid, "Justificante.pdf")
    assert r.status_code == 201 and r.get_json()["data"][0]["ok"] is True
    aid = r.get_json()["data"][0]["id"]
    lista = cliente.get(f"/api/v1/tareas-outlook/{tid}/adjuntos", headers=h).get_json()["data"]
    assert [(a["nombre_archivo"], a["tipo_mime"]) for a in lista] == [("Justificante.pdf", "application/pdf")] and "contenido" not in lista[0]
    d = cliente.get(f"/api/v1/tareas-outlook/adjuntos/{aid}", headers=h)
    assert d.data == b"%PDF-1.4 contenido" and d.headers["X-Content-Type-Options"] == "nosniff"
    assert d.headers["Content-Disposition"].startswith("attachment") and "sandbox" in d.headers["Content-Security-Policy"]
    assert cliente.get(f"/api/v1/tareas-outlook/adjuntos/{aid}?ver=1", headers=h).headers["Content-Disposition"].startswith("attachment")     # un PDF nunca en línea
    img = _subir(cliente, h, tid, "foto.PNG", b"\x89PNG\r\n\x1a\n datos").get_json()["data"][0]["id"]
    assert cliente.get(f"/api/v1/tareas-outlook/adjuntos/{img}?ver=1", headers=h).headers["Content-Disposition"].startswith("inline")
    assert any(a["tipo"] == "adjunto" and a["detalle"] == "Justificante.pdf" for a in cliente.get(f"/api/v1/tareas-outlook/{tid}/actividad", headers=h).get_json()["data"])


def test_tipos_vacio_grande_duplicado_y_claves_privadas_se_rechazan(cliente):
    t, h, uid = _despacho(cliente, "a2@ejemplo.com", "Despacho rechazos")
    tid = _tarea(cliente, h, "Rechazos")

    def codigo(nombre, contenido=b"x contenido"):
        return _subir(cliente, h, tid, nombre, contenido).get_json()["data"][0].get("codigo")
    for nombre in ("pagina.html", "dibujo.svg", "programa.exe", "script.js", "doble.pdf.html", "sin_extension", "enlace.htm"):
        assert codigo(nombre) == "tipo_no_admitido", nombre
    assert codigo("vacio.pdf", b"") == "archivo_vacio" or _subir(cliente, h, tid, "vacio.pdf", b"").status_code == 400
    assert codigo("cert.txt", b"-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----") == "clave_privada"
    assert codigo("cert.pdf", b"x" * 20) is None                                        # válido
    assert codigo("copia.pdf", b"x" * 20) == "duplicado"                                 # mismo contenido
    assert codigo("grande.pdf", b"y" * (tt.MAX_ADJUNTO_BYTES + 1)) == "archivo_grande"
    assert [a["nombre_archivo"] for a in tt.listar_adjuntos(tid)] == ["cert.pdf"]
    assert _subir(cliente, h, tid, "a.pdf", campo="otro").get_json()["codigo"] == "sin_archivos"


def test_limite_de_adjuntos_por_tarea(cliente):
    t, h, uid = _despacho(cliente, "a3@ejemplo.com", "Despacho límite")
    tid = _tarea(cliente, h, "Muchos")
    for i in range(tt.MAX_ADJUNTOS_POR_TAREA):
        tt.subir_adjunto(uid, tid, f"f{i}.txt", f"contenido {i}".encode())
    r = _subir(cliente, h, tid, "uno_mas.txt", b"otro")
    assert r.get_json()["data"][0]["codigo"] == "limite"


def test_nombre_malicioso_se_sanea(cliente):
    t, h, uid = _despacho(cliente, "a4@ejemplo.com", "Despacho nombres")
    tid = _tarea(cliente, h, "Nombres")
    aid = tt.subir_adjunto(uid, tid, '../../etc/pa"sswd\r\n.txt', b"hola")
    d = cliente.get(f"/api/v1/tareas-outlook/adjuntos/{aid}", headers=h)
    cab = d.headers["Content-Disposition"]
    assert ".." not in cab and "\r" not in cab and "\n" not in cab and "/" not in cab and cab.count('"') == 2


def test_permisos_y_aislamiento_de_los_adjuntos(cliente):
    t, h, uid = _despacho(cliente, "a5@ejemplo.com", "Despacho permisos adj")
    h2, u2 = _usuario(cliente, "a5b@ejemplo.com", t)
    h3, u3 = _usuario(cliente, "a5c@ejemplo.com", t)
    ajeno = _despacho(cliente, "a5d@ejemplo.com", "Despacho ajeno adj")[1]
    tid = _tarea(cliente, h, "Compartida")
    aid = tt.subir_adjunto(uid, tid, "dueno.pdf", b"%PDF dueno")
    cliente.post(f"/api/v1/tareas-outlook/{tid}/compartir", json={"usuario_id": u2, "rol": "observa"}, headers=h)
    cliente.post(f"/api/v1/tareas-outlook/{tid}/compartir", json={"usuario_id": u3, "rol": "colabora"}, headers=h)
    assert cliente.get(f"/api/v1/tareas-outlook/{tid}/adjuntos", headers=h2).status_code == 200          # el observador ve
    assert cliente.get(f"/api/v1/tareas-outlook/adjuntos/{aid}", headers=h2).status_code == 200
    r = _subir(cliente, h2, tid, "intruso.pdf")
    assert r.get_json()["data"][0]["codigo"] == "sin_permiso"                                            # pero no sube
    assert _subir(cliente, h3, tid, "colabora.pdf", b"%PDF colabora").status_code == 201
    assert cliente.delete(f"/api/v1/tareas-outlook/adjuntos/{aid}", headers=h2).status_code == 404       # el observador no borra
    assert cliente.delete(f"/api/v1/tareas-outlook/adjuntos/{aid}", headers=h3).status_code == 404       # ni el colaborador borra lo del dueño
    for url in (f"/api/v1/tareas-outlook/{tid}/adjuntos", f"/api/v1/tareas-outlook/adjuntos/{aid}"):
        assert cliente.get(url, headers=ajeno).status_code == 404                                         # otro despacho: ni existe
    assert _subir(cliente, ajeno, tid, "x.pdf").status_code == 404
    assert cliente.delete(f"/api/v1/tareas-outlook/adjuntos/{aid}", headers=h).status_code == 200      # el dueño sí
    assert cliente.get(f"/api/v1/tareas-outlook/adjuntos/{aid}", headers=h).status_code == 404
    mio = [a["id"] for a in tt.listar_adjuntos(tid) if a["nombre_archivo"] == "colabora.pdf"][0]
    assert cliente.delete(f"/api/v1/tareas-outlook/adjuntos/{mio}", headers=h3).status_code == 200      # quien subió, borra lo suyo
    assert tt.listar_adjuntos(tid) == []


def test_web_sube_descarga_y_quita_adjuntos(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "a6@ejemplo.com", "contrasena123")
    tid = db.crear_tarea_outlook(uid, asunto="Web adjuntos")
    r = cliente.post(f"/tareas/{tid}/adjuntos", data={"adjunto": (io.BytesIO(b"%PDF web"), "web.pdf")}, content_type="multipart/form-data")
    assert r.status_code == 302
    aid = tt.listar_adjuntos(tid)[0]["id"]
    html = cliente.get(f"/tareas/{tid}").get_data(as_text=True)
    assert 'id="adjuntos"' in html and "web.pdf" in html
    assert cliente.get(f"/tareas/adjuntos/{aid}").data == b"%PDF web"
    r = cliente.post(f"/tareas/{tid}/adjuntos", data={"adjunto": (io.BytesIO(b"<html>"), "malo.html")}, content_type="multipart/form-data", follow_redirects=True)
    assert "Tipo de archivo no admitido" in r.get_data(as_text=True)
    assert cliente.post(f"/tareas/adjuntos/{aid}/eliminar").status_code == 302 and tt.listar_adjuntos(tid) == []
    assert cliente.get(f"/tareas/adjuntos/{aid}").status_code == 404


def test_migracion_idempotente_de_subtareas_y_adjuntos(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "a7@ejemplo.com", "contrasena123")
    conn = db.get_connection()
    try:
        tt.crear_esquema(conn)
        tt.crear_esquema(conn)
        columnas = {f["name"] for f in conn.execute("PRAGMA table_info(tareas_outlook)")}
        tablas = {f["name"] for f in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()
    assert {"tarea_padre_id", "version", "motivo_bloqueo"} <= columnas and "tarea_adjuntos" in tablas
