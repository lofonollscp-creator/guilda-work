"""Proyectos, fase 3: notas compartidas, actividad, plantillas y datos del cliente en el resumen."""
from datetime import date

from app import db, proyecto_plantillas
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_proyectos_paginas import _dueno, _miembro, _otro_cliente


def _equipo(*emails):
    tenant = db.crear_tenant(f"Despacho f3 {emails[0]}")
    ids = []
    for email in emails:
        uid = db.crear_usuario(email, "contrasena123")
        db.asignar_tenant(uid, tenant)
        ids.append(uid)
    return tenant, ids


# --- notas compartidas ---------------------------------------------------------------------------

def test_notas_compartidas_permisos():
    _, (ana, luis, eva, ajeno) = _equipo("f3-1@x.com", "f3-2@x.com", "f3-3@x.com", "f3-4@x.com")
    p = db.crear_categoria(ana, "P")
    db.compartir_proyecto(ana, p, luis, "colabora")
    db.compartir_proyecto(ana, p, eva, "observa")
    n1 = db.crear_nota_proyecto(ana, p, "  Decisión: se factura en octubre  ")
    n2 = db.crear_nota_proyecto(luis, p, "Nota de Luis")
    assert n1 and n2
    assert db.crear_nota_proyecto(eva, p, "no puede") is None and db.crear_nota_proyecto(ajeno, p, "ni este") is None
    assert db.crear_nota_proyecto(ana, p, "   ") is None
    vistas = [n["texto"] for n in db.listar_notas_proyecto(eva, p)]
    assert vistas == ["Nota de Luis", "Decisión: se factura en octubre"]          # recientes primero
    assert db.listar_notas_proyecto(ajeno, p) == []
    assert db.fijar_nota_proyecto(luis, p, n1, True) and db.listar_notas_proyecto(ana, p)[0]["id"] == n1
    assert db.fijar_nota_proyecto(eva, p, n1, False) is False
    # borrar: el autor colaborador o el dueño; un observador o un tercero no
    assert db.eliminar_nota_proyecto(eva, p, n2) is False and db.eliminar_nota_proyecto(luis, p, n1) is False
    assert db.eliminar_nota_proyecto(luis, p, n2) and db.eliminar_nota_proyecto(ana, p, n1)
    assert db.listar_notas_proyecto(ana, p) == []


def test_limite_de_notas(monkeypatch):
    _, (ana,) = _equipo("f3-5@x.com")
    p = db.crear_categoria(ana, "P")
    monkeypatch.setattr(db, "MAX_NOTAS_PROYECTO", 2)
    assert db.crear_nota_proyecto(ana, p, "1") and db.crear_nota_proyecto(ana, p, "2") and db.crear_nota_proyecto(ana, p, "3") is None


def test_pagina_de_notas(cliente):
    uid, tenant, p = _dueno(cliente, "f3-n1@x.com")
    assert cliente.post(f"/proyecto/{p}/notas", data={"texto": "<b>Acuerdo</b> con el cliente"}).status_code == 302
    html = cliente.get(f"/proyecto/{p}/notas").get_data(as_text=True)
    assert "&lt;b&gt;Acuerdo&lt;/b&gt; con el cliente" in html and "<b>Acuerdo</b>" not in html
    assert 'class="activa"' in html
    r = cliente.post(f"/proyecto/{p}/notas", data={"texto": ""})
    assert r.status_code == 302 and "error=" in r.headers["Location"]
    with _otro_cliente("f3-n2@x.com") as (eva, id_eva):
        _miembro(eva, id_eva, tenant)
        db.compartir_proyecto(uid, p, id_eva, "observa")
        assert "Acuerdo" in eva.get(f"/proyecto/{p}/notas").get_data(as_text=True)
        assert eva.post(f"/proyecto/{p}/notas", data={"texto": "x"}).status_code == 403
        nota = db.listar_notas_proyecto(uid, p)[0]["id"]
        assert eva.post(f"/proyecto/{p}/notas/{nota}/eliminar").status_code == 403
        assert eva.post(f"/proyecto/{p}/notas/{nota}/fijar", data={"fijada": "1"}).status_code == 403
    with _otro_cliente("f3-n3@x.com") as (ajeno, id_ajeno):
        db.asignar_tenant(id_ajeno, db.crear_tenant("Despacho ajeno f3"))
        assert ajeno.get(f"/proyecto/{p}/notas").status_code == 404
        assert ajeno.post(f"/proyecto/{p}/notas", data={"texto": "x"}).status_code == 404


# --- actividad -----------------------------------------------------------------------------------

def test_actividad_junta_tareas_comentarios_y_notas():
    _, (ana, luis) = _equipo("f3-6@x.com", "f3-7@x.com")
    p = db.crear_categoria(ana, "P")
    db.compartir_proyecto(ana, p, luis, "colabora")
    t = db.crear_tarea_en_proyecto(ana, p, "Pedir extractos")
    db.comentar_tarea_outlook(luis, t, "Ya los he pedido")
    db.crear_nota_proyecto(luis, p, "Nota importante")
    otra = db.crear_categoria(ana, "Otro")
    db.crear_tarea_en_proyecto(ana, otra, "De otro proyecto")
    act = db.actividad_proyecto(luis, p)
    tipos = [(a["tipo"], a["quien"]) for a in act]
    assert ("comentario", "f3-7@x.com") in tipos and ("nota", "f3-7@x.com") in tipos and ("actividad", "f3-6@x.com") in tipos
    assert all(a["tarea"] in (None, "Pedir extractos") for a in act)
    assert [a["cuando"] for a in act] == sorted((a["cuando"] for a in act), reverse=True)
    assert db.actividad_proyecto(luis, otra) == []                 # no es miembro de ese
    assert len(db.actividad_proyecto(ana, p, limite=1)) == 1


def test_pagina_de_actividad(cliente):
    uid, _, p = _dueno(cliente, "f3-a1@x.com")
    t = db.crear_tarea_en_proyecto(uid, p, "Hacer algo")
    db.crear_nota_proyecto(uid, p, "Una nota del equipo")
    html = cliente.get(f"/proyecto/{p}/actividad").get_data(as_text=True)
    assert "creó la tarea" in html and "Hacer algo" in html and "Una nota del equipo" in html and f"/tareas/{t}" in html
    assert 'class="activa"' in html
    vacia = db.crear_categoria(uid, "Vacía")
    assert "Aún no hay actividad" in cliente.get(f"/proyecto/{vacia}/actividad").get_data(as_text=True)


# --- plantillas ----------------------------------------------------------------------------------

def test_aplicar_plantilla_crea_secciones_y_tareas_con_fechas():
    _, (ana, eva) = _equipo("f3-8@x.com", "f3-9@x.com")
    p = db.crear_categoria(ana, "P")
    db.compartir_proyecto(ana, p, eva, "observa")
    estructura = [{"nombre": "Fase 1", "tareas": [{"asunto": "A", "dias": 3}, {"asunto": "B", "dias": None}, {"asunto": "  "}]}, {"nombre": ""}, {"nombre": "Fase 2", "tareas": []}]
    assert db.aplicar_plantilla_proyecto(eva, p, estructura) is None
    assert db.aplicar_plantilla_proyecto(ana, p, estructura, hoy=date(2026, 10, 7)) == {"secciones": 2, "tareas": 2}
    assert [s["nombre"] for s in db.listar_secciones(p)] == ["Fase 1", "Fase 2"]
    tareas = {t["asunto"]: t for t in db.tareas_de_proyecto(ana, p)}
    assert tareas["A"]["fecha_vencimiento"] == "2026-10-10" and tareas["B"]["fecha_vencimiento"] is None
    assert db.aplicar_plantilla_proyecto(ana, p, "basura") == {"secciones": 0, "tareas": 0}
    assert len(db.listar_secciones(p)) == 2                                    # añadir no borra ni duplica lo anterior


def test_guardar_y_reutilizar_plantilla_del_despacho():
    _, (ana, luis, eva) = _equipo("f3-10@x.com", "f3-11@x.com", "f3-12@x.com")
    p = db.crear_categoria(ana, "Origen")
    db.compartir_proyecto(ana, p, luis, "colabora")
    s = db.crear_seccion(ana, p, "Recoger")
    db.crear_tarea_en_proyecto(ana, p, "Pedir extractos", seccion_id=s, fecha_vencimiento="2026-10-20", asignada_a=luis)
    hecha = db.crear_tarea_en_proyecto(ana, p, "Ya hecha", seccion_id=s)
    db.completar_tarea_outlook(ana, hecha)
    db.crear_tarea_en_proyecto(ana, p, "Suelta")
    assert db.guardar_plantilla_desde_proyecto(luis, p, "No dueño") is None
    pid = db.guardar_plantilla_desde_proyecto(ana, p, "Mi cierre")
    assert pid
    guardadas = db.listar_plantillas_proyecto(luis)                            # la ve todo el despacho
    assert [g["nombre"] for g in guardadas] == ["Mi cierre"]
    nombres = {sec["nombre"]: [t["asunto"] for t in sec["tareas"]] for sec in guardadas[0]["estructura"]}
    assert "Pedir extractos" in nombres["Recoger"] and "Suelta" in nombres["Mi cierre"]
    assert all(t.get("dias") is None for sec in guardadas[0]["estructura"] for t in sec["tareas"])      # sin fechas ni personas
    nuevo = db.crear_categoria(luis, "Nuevo")
    assert db.aplicar_plantilla_proyecto(luis, nuevo, guardadas[0]["estructura"])["tareas"] >= 2
    # otro despacho no la ve ni la borra
    otro = db.crear_usuario("f3-otro@x.com", "contrasena123")
    db.asignar_tenant(otro, db.crear_tenant("Otro despacho f3"))
    assert db.listar_plantillas_proyecto(otro) == [] and db.eliminar_plantilla_proyecto(otro, pid) is False
    assert db.eliminar_plantilla_proyecto(luis, pid) and db.listar_plantillas_proyecto(ana) == []


def test_catalogo_incluye_las_de_serie_y_las_resuelve():
    _, (ana,) = _equipo("f3-13@x.com")
    cat = proyecto_plantillas.catalogo(ana)
    claves = [c["clave"] for c in cat]
    assert {"s:cierre-trimestral", "s:alta-cliente", "s:renta"} <= set(claves)
    est = proyecto_plantillas.estructura_de(ana, "s:cierre-trimestral")
    assert est and all(isinstance(s["nombre"], str) and all(isinstance(t["asunto"], str) for t in s["tareas"]) for s in est)
    assert proyecto_plantillas.estructura_de(ana, "s:inventada") is None and proyecto_plantillas.estructura_de(ana, "u:99999") is None


def test_crear_proyecto_desde_plantilla_y_aplicarla_desde_la_pagina(cliente):
    uid, tenant, p = _dueno(cliente, "f3-p1@x.com")
    r = cliente.post("/menus", data={"nombre": "Cliente nuevo SL", "plantilla": "s:alta-cliente"})
    assert r.status_code == 302 and "/proyecto/" in r.headers["Location"]
    nuevo = int(r.headers["Location"].rstrip("/").split("/")[-2])
    assert len(db.listar_secciones(nuevo)) == 3 and len(db.tareas_de_proyecto(uid, nuevo)) == 5
    # nombre válido pero plantilla inexistente: el proyecto se crea vacío
    r = cliente.post("/menus", data={"nombre": "Sin plantilla", "plantilla": "s:no-existe"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    # aplicarla en uno existente, desde el resumen
    assert 's:renta' in cliente.get(f"/proyecto/{p}").get_data(as_text=True)
    assert cliente.post(f"/proyecto/{p}/plantilla", data={"plantilla": "s:renta"}).status_code == 302
    assert len(db.listar_secciones(p)) == 3
    r = cliente.post(f"/proyecto/{p}/plantilla", data={"plantilla": "s:no-existe"})
    assert r.status_code == 302 and "error=" in r.headers["Location"]
    # guardar y borrar
    cliente.post(f"/proyecto/{p}/plantilla/guardar", data={"nombre": "Mi renta"})
    guardada = db.listar_plantillas_proyecto(uid)[0]
    assert "Mi renta" in cliente.get("/").get_data(as_text=True)               # sale en el formulario de «Nuevo proyecto»
    assert cliente.post(f"/proyecto/plantillas/{guardada['id']}/eliminar").status_code == 302 and db.listar_plantillas_proyecto(uid) == []


def test_observador_no_puede_aplicar_ni_guardar_plantillas(cliente):
    uid, tenant, p = _dueno(cliente, "f3-p2@x.com")
    with _otro_cliente("f3-p2b@x.com") as (eva, id_eva):
        _miembro(eva, id_eva, tenant)
        db.compartir_proyecto(uid, p, id_eva, "observa")
        assert eva.post(f"/proyecto/{p}/plantilla", data={"plantilla": "s:renta"}).status_code == 403
        assert eva.post(f"/proyecto/{p}/plantilla/guardar", data={"nombre": "x"}).status_code == 403
        assert "s:renta" not in eva.get(f"/proyecto/{p}").get_data(as_text=True)


# --- cliente en el resumen -----------------------------------------------------------------------

def test_resumen_muestra_vencimientos_y_solo_los_correos_propios(cliente):
    uid, tenant, p = _dueno(cliente, "f3-c1@x.com")
    cli = db.crear_cliente_fiscal(tenant, "Cliente SL")
    assert db.actualizar_proyecto(uid, p, cliente_fiscal_id=cli, cambiar_cliente=True)
    conn = db.get_connection()
    conn.execute("INSERT INTO vencimientos_fiscales (tenant_id, cliente_fiscal_id, modelo, periodo, fecha_limite, estado, creado_en) VALUES (?, ?, '303', '3T', '2026-10-20', 'pendiente', '2026-10-01')", (tenant, cli))
    cuenta = conn.execute("INSERT INTO correo_cuentas (usuario_id, nombre, protocolo, host, puerto, usuario, creada_en) VALUES (?, 'c', 'imap', 'h', 993, 'u', '2026-10-01')", (uid,)).lastrowid
    conn.execute("INSERT INTO correo_mensajes (cuenta_id, carpeta, uid, asunto, remitente, fecha, cliente_fiscal_id, descargado_en) VALUES (?, 'INBOX', 1, 'Extractos de septiembre', 'a@b.c', '2026-10-01', ?, '2026-10-01')", (cuenta, cli))
    conn.commit()
    conn.close()
    html = cliente.get(f"/proyecto/{p}").get_data(as_text=True)
    assert "Modelo 303" in html and "2026-10-20" in html and "Extractos de septiembre" in html
    with _otro_cliente("f3-c2@x.com") as (eva, id_eva):
        _miembro(eva, id_eva, tenant)
        db.compartir_proyecto(uid, p, id_eva, "colabora")
        html = eva.get(f"/proyecto/{p}").get_data(as_text=True)
        assert "Modelo 303" in html and "Extractos de septiembre" not in html          # el correo de Ana es privado
