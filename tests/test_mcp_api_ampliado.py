"""Bloque 4: herramientas MCP nuevas, tokens con permisos, paginación opcional
y nuevos eventos de webhook."""
import pytest

import mcp_tools as mt
from app import correo, db, eventos, ia_herramientas


def _cuenta(usuario_id):
    return db.crear_cuenta_correo(usuario_id, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")


def _msg(cuenta, uid="1", asunto="Consulta", **kw):
    return db.guardar_mensaje_correo(
        cuenta_id=cuenta, uid=uid, asunto=asunto, remitente="ana@ejemplo.com", destinatarios="yo@ejemplo.com",
        fecha="2026-03-10T10:00:00", cuerpo_texto="Cuerpo del correo", cuerpo_html=None, **kw,
    )


# --- herramientas MCP -------------------------------------------------------

def test_proyectos_ciclo_completo_y_papelera(usuario_id):
    p = mt.crear_proyecto("Auditoría", "#4f8cff")
    assert any(x["nombre"] == "Auditoría" for x in mt.listar_proyectos())
    assert mt.renombrar_proyecto("Auditoría", "Auditoría 2026")["nombre"] == "Auditoría 2026"
    with pytest.raises(ValueError):
        mt.crear_proyecto("   ")
    with pytest.raises(ValueError):
        mt.eliminar_proyecto("No existe")
    assert mt.eliminar_proyecto(p["id"])["en_papelera"] is True
    assert not any(x["id"] == p["id"] for x in mt.listar_proyectos())
    assert any(x["id"] == p["id"] and x["origen"] == "menu" for x in mt.listar_papelera())
    mt.restaurar_de_papelera("menu", p["id"])
    assert any(x["id"] == p["id"] for x in mt.listar_proyectos())


def test_eliminar_nota_y_tarea_van_a_la_papelera_y_se_restauran(usuario_id):
    nota = mt.crear_nota("Texto **importante**", titulo="Mi título")
    assert nota["titulo"] == "Mi título"
    assert mt.editar_nota(nota["id"], "Nuevo", titulo="Otro")["titulo"] == "Otro"
    assert mt.fijar_nota(nota["id"])["fijada"] == 1
    assert mt.fijar_nota(nota["id"], False)["fijada"] == 0
    tarea = mt.crear_tarea("Llamar")
    assert mt.eliminar_nota(nota["id"])["origen"] == "nota"
    assert mt.eliminar_tarea(tarea["id"])["origen"] == "tarea_outlook"
    with pytest.raises(ValueError):
        mt.eliminar_nota(nota["id"])
    origenes = {(x["origen"], x["id"]) for x in mt.listar_papelera()}
    assert {("nota", nota["id"]), ("tarea_outlook", tarea["id"])} <= origenes
    mt.restaurar_de_papelera("tarea_outlook", tarea["id"])
    assert any(t["id"] == tarea["id"] for t in mt.listar_tareas())


def test_acciones_de_correo_y_aislamiento(usuario_id, monkeypatch):
    cuenta = _cuenta(usuario_id)
    m = _msg(cuenta)
    assert mt.destacar_correo(m, True, "2026-12-01")["destacado"] == 1
    assert mt.destacar_correo(m, False)["destacado"] == 0
    assert mt.posponer_correo(m, "2099-01-01")["pospuesto_hasta"].startswith("2099-01-01")
    assert mt.posponer_correo(m)["pospuesto_hasta"] is None
    movidos = []
    monkeypatch.setattr(correo, "mover_mensaje", lambda uid, mid, carpeta: movidos.append((mid, carpeta)))
    assert mt.mover_correo(m, "Archivo")["movido"] is True and movidos == [(m, "Archivo")]
    with pytest.raises(ValueError):
        mt.mover_correo(999999, "Archivo")
    with pytest.raises(ValueError):
        mt.destacar_correo(999999)


def test_reglas_y_conversacion_de_correo(usuario_id):
    cuenta = _cuenta(usuario_id)
    a = _msg(cuenta, "1", "Presupuesto")
    b = _msg(cuenta, "2", "Re: Presupuesto")
    assert [x["id"] for x in mt.listar_conversacion_correo(b)] == [a, b]
    regla = mt.crear_regla_correo(remitente="@aeat.es", destacar=True)
    assert mt.listar_reglas_correo()[0]["id"] == regla["id"]
    with pytest.raises(ValueError):
        mt.crear_regla_correo(destacar=True)  # sin condición
    assert mt.eliminar_regla_correo(regla["id"]) == {"eliminada": True}
    assert mt.listar_reglas_correo() == []


def test_tarea_y_nota_desde_correo_y_filtros_de_bandeja(usuario_id):
    cuenta = _cuenta(usuario_id)
    m = _msg(cuenta, "1", "Enviar el 303")
    db.guardar_adjuntos_correo(m, [{"nombre": "a.pdf", "tipo": "application/pdf", "bytes": b"x"}])
    _msg(cuenta, "2", "Otro")
    tarea = mt.crear_tarea_desde_correo(m, "2026-12-31")
    assert tarea["asunto"] == "Enviar el 303" and tarea["mensaje_correo_id"] == m
    nota = mt.guardar_nota_desde_correo(m)
    assert nota["titulo"] == "Enviar el 303" and nota["mensaje_correo_id"] == m
    assert [x["id"] for x in mt.listar_bandeja_entrada(cuenta, con_adjuntos=True)] == [m]
    assert len(mt.listar_bandeja_entrada(cuenta, texto="Cuerpo del correo")) == 2  # busca en el cuerpo


def test_mi_dia_checklist_y_asignacion(usuario_id):
    tarea = mt.crear_tarea("Preparar cierre", fecha_vencimiento="2000-01-01")
    assert any(t["id"] == tarea["id"] for t in mt.listar_tareas_hoy()["vencidas"])
    item = mt.agregar_item_checklist(tarea["id"], "Revisar bancos")
    assert [i["texto"] for i in item["checklist"]] == ["Revisar bancos"]
    assert mt.alternar_item_checklist(item["id"]) == {"alternada": True}
    assert mt.listar_checklist_tarea(tarea["id"])[0]["hecha"] == 1
    with pytest.raises(ValueError):
        mt.agregar_item_checklist(tarea["id"], "   ")
    assert mt.listar_companeros() == []  # sin despacho
    with pytest.raises(ValueError):
        mt.asignar_tarea(tarea["id"], 12345)


def test_ia_puede_ejecutar_las_nuevas_y_pide_confirmacion_en_las_de_escritura(usuario_id):
    assert ia_herramientas.ejecutar(usuario_id, "listar_proyectos", {}) == mt.listar_proyectos()
    for nombre in ("eliminar_proyecto", "eliminar_nota", "eliminar_tarea", "mover_correo", "crear_regla_correo"):
        assert ia_herramientas.necesita_confirmacion(nombre, False) is True
    for nombre in ("listar_proyectos", "listar_tareas_hoy", "listar_conversacion_correo"):
        assert ia_herramientas.necesita_confirmacion(nombre, False) is False


# --- tokens con permisos ----------------------------------------------------

def _registrar(cliente, email):
    resp = cliente.post("/api/v1/auth/registro", json={"email": email, "contrasena": "contrasena123"})
    assert resp.status_code == 201
    return resp.get_json()["data"]["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_token_de_solo_lectura_permite_get_y_rechaza_el_resto(cliente):
    completo = _registrar(cliente, "b4-tokens@ejemplo.com")
    creado = cliente.post("/api/v1/tokens", json={"nombre": "Panel", "permisos": "solo_lectura"}, headers=_auth(completo))
    assert creado.status_code == 201
    lectura = creado.get_json()["data"]["token"]
    assert cliente.get("/api/v1/tareas-outlook", headers=_auth(lectura)).status_code == 200
    r = cliente.post("/api/v1/tareas-outlook", json={"asunto": "x"}, headers=_auth(lectura))
    assert r.status_code == 403 and "solo lectura" in r.get_json()["error"]
    assert cliente.post("/api/v1/tokens", json={}, headers=_auth(lectura)).status_code == 403
    # el token completo sigue pudiendo escribir
    assert cliente.post("/api/v1/tareas-outlook", json={"asunto": "x"}, headers=_auth(completo)).status_code == 201
    # y el de solo lectura puede cerrar su propia sesión
    assert cliente.post("/api/v1/auth/logout", headers=_auth(lectura)).status_code == 200
    assert cliente.get("/api/v1/tareas-outlook", headers=_auth(lectura)).status_code == 401


def test_listar_y_revocar_tokens_sin_exponer_el_token(cliente):
    completo = _registrar(cliente, "b4-lista@ejemplo.com")
    cliente.post("/api/v1/tokens", json={"nombre": "A", "permisos": "solo_lectura"}, headers=_auth(completo))
    lista = cliente.get("/api/v1/tokens", headers=_auth(completo)).get_json()["data"]
    assert {t["permisos"] for t in lista} == {"completo", "solo_lectura"}
    assert all("token" not in t and "token_hash" not in t for t in lista)
    assert cliente.post("/api/v1/tokens", json={"permisos": "root"}, headers=_auth(completo)).status_code == 400
    ajeno = next(t["id"] for t in lista if t["permisos"] == "solo_lectura")
    assert cliente.delete(f"/api/v1/tokens/{ajeno}", headers=_auth(completo)).status_code == 200
    assert cliente.delete(f"/api/v1/tokens/{ajeno}", headers=_auth(completo)).status_code == 404


def test_crear_token_desde_la_web_lo_muestra_una_vez(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "b4-web@ejemplo.com", "contrasena123")
    resp = cliente.post("/mis-dispositivos/token", data={"nombre": "Grafana", "permisos": "solo_lectura"})
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200 and "Grafana" in html and "no se volverá a mostrar" in html
    token = db.listar_tokens_api(uid)[0]
    assert token["permisos"] == "solo_lectura"
    assert cliente.post("/mis-dispositivos/token", data={"permisos": "root"}).status_code == 400
    assert "Solo lectura" in cliente.get("/mis-dispositivos").get_data(as_text=True)


# --- paginación opcional ----------------------------------------------------

def test_paginacion_opcional_con_cabecera_total(cliente):
    token = _registrar(cliente, "b4-pag@ejemplo.com")
    for i in range(5):
        cliente.post("/api/v1/tareas-outlook", json={"asunto": f"T{i}"}, headers=_auth(token))
    todo = cliente.get("/api/v1/tareas-outlook", headers=_auth(token))
    assert len(todo.get_json()["data"]) == 5 and todo.headers["X-Total-Count"] == "5"
    pagina = cliente.get("/api/v1/tareas-outlook?limit=2&offset=1", headers=_auth(token))
    assert len(pagina.get_json()["data"]) == 2 and pagina.headers["X-Total-Count"] == "5"
    assert [t["asunto"] for t in pagina.get_json()["data"]] == [t["asunto"] for t in todo.get_json()["data"][1:3]]
    assert cliente.get("/api/v1/tareas-outlook?offset=4", headers=_auth(token)).get_json()["data"].__len__() == 1


# --- eventos de webhook -----------------------------------------------------

@pytest.fixture
def eventos_emitidos(monkeypatch):
    registro = []
    monkeypatch.setattr(eventos, "emitir", lambda evento, tenant, payload: registro.append((evento, payload)))
    return registro


def test_eventos_de_tareas_y_notas(usuario_id, eventos_emitidos):
    tarea_id = db.crear_tarea_outlook(usuario_id, "Hacer algo")
    db.completar_tarea_outlook(usuario_id, tarea_id)
    nota_id = db.crear_nota(usuario_id, "texto")
    db.editar_nota(usuario_id, nota_id, "texto editado")
    nombres = [e for e, _ in eventos_emitidos]
    assert nombres.count("tarea.creada") == 1 and nombres.count("tarea.completada") == 1
    assert "nota.editada" in nombres
    assert dict(eventos_emitidos)["tarea.creada"]["tarea_id"] == tarea_id


def test_evento_tarea_asignada_solo_al_asignar(usuario_id, eventos_emitidos):
    tenant = db.crear_tenant("Despacho Ev")
    db.asignar_tenant(usuario_id, tenant)
    otro = db.crear_usuario_vinculado_a_kratos("b4-comp@ejemplo.com", "kratos-b4-comp")
    db.asignar_tenant(otro, tenant)
    tarea_id = db.crear_tarea_outlook(usuario_id, "Para ti")
    assert db.asignar_tarea_outlook(usuario_id, tarea_id, otro) is True
    assert db.asignar_tarea_outlook(usuario_id, tarea_id, None) is True
    asignadas = [p for e, p in eventos_emitidos if e == "tarea.asignada"]
    assert asignadas == [{"tarea_id": tarea_id, "asignada_a": otro}]


def test_evento_correo_enviado_sin_cuerpo(usuario_id, eventos_emitidos, monkeypatch):
    cuenta = db.crear_cuenta_correo(
        usuario_id, "T", "imap", "imap.x.com", 993, "yo@x.com", smtp_host="smtp.x.com", smtp_puerto=587,
    )

    class _Smtp:
        def send_message(self, *a, **k): pass
        def quit(self): pass

    monkeypatch.setattr(correo, "_conectar_smtp", lambda *a, **k: _Smtp())
    monkeypatch.setattr(correo, "_contrasena", lambda *_: "x")
    correo.construir_y_enviar(usuario_id, cuenta, "a@b.com", "Asunto", "<p>Secreto</p>")
    evento, payload = [x for x in eventos_emitidos if x[0] == "correo.enviado"][0]
    assert payload["asunto"] == "Asunto" and "Secreto" not in str(payload)


def test_los_eventos_nuevos_son_suscribibles():
    for e in ("tarea.creada", "tarea.completada", "tarea.asignada", "correo.enviado", "nota.editada", "vencimiento.presentado"):
        assert e in eventos.EVENTOS
