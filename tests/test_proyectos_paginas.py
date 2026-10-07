"""Página de proyecto (fase 1): resumen, lista con secciones, compartir y permisos por rol."""
from contextlib import contextmanager
from datetime import datetime, timedelta

from app import db
from tests.conftest import iniciar_sesion_de_prueba


@contextmanager
def _otro_cliente(email):
    from app.auth import limiter
    from app.main import app as flask_app

    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    limiter.reset()
    # Sin `with`: dos clientes que conservan su contexto de petición a la vez se estorban al cerrarse si se alternan.
    otro = flask_app.test_client()
    yield otro, iniciar_sesion_de_prueba(otro, email, "contrasena123")


def _dueno(cliente, email, nombre="Cierre trimestral"):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    tenant = db.crear_tenant(f"Despacho {email}")
    db.asignar_tenant(uid, tenant)
    return uid, tenant, db.crear_categoria(uid, nombre)


def _miembro(otro, uid_otro, tenant):
    db.asignar_tenant(uid_otro, tenant)


def test_el_dueno_ve_su_proyecto_y_la_ruta_antigua_redirige(cliente):
    uid, _, p = _dueno(cliente, "pg-1@x.com")
    db.crear_tarea_en_proyecto(uid, p, "Pedir extractos", fecha_vencimiento=(datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"))
    html = cliente.get(f"/proyecto/{p}").get_data(as_text=True)
    assert "Cierre trimestral" in html and "Próximas tareas" in html and "Pedir extractos" in html
    assert "Ajustes y miembros" in html and "Solo tuyo" in html and "0 % · 0 de 1 tareas" in html
    r = cliente.get(f"/menu/{p}")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/proyecto/{p}")
    assert cliente.get(f"/menu/{p}?registro=1").status_code == 200          # el registro de siempre sigue ahí
    assert cliente.get(f"/menu/99999").status_code == 404


def test_un_desconocido_no_ve_el_proyecto_ni_otro_despacho(cliente):
    uid, tenant, p = _dueno(cliente, "pg-2@x.com")
    with _otro_cliente("pg-2b@x.com") as (otro, uid_otro):
        db.asignar_tenant(uid_otro, db.crear_tenant("Despacho ajeno pg2"))
        for ruta in (f"/proyecto/{p}", f"/proyecto/{p}/lista"):
            assert otro.get(ruta).status_code == 404
        assert otro.post(f"/proyecto/{p}/tareas", data={"asunto": "intruso"}).status_code == 404
        mismo_despacho = db.crear_usuario("pg-2c@x.com", "contrasena123")
        db.asignar_tenant(mismo_despacho, tenant)
        assert db.rol_en_proyecto(mismo_despacho, p) is None            # compañero, pero el proyecto es privado
        assert otro.get(f"/menu/{p}").status_code == 404


def test_compartir_desde_la_pagina_y_ver_como_colaborador(cliente):
    uid, tenant, p = _dueno(cliente, "pg-3@x.com")
    with _otro_cliente("pg-3b@x.com") as (otro, luis):
        _miembro(otro, luis, tenant)
        assert cliente.post(f"/proyecto/{p}/miembros", data={"usuario_id": luis, "rol": "colabora"}).status_code == 302
        assert cliente.post(f"/proyecto/{p}/miembros", data={"usuario_id": 99999, "rol": "colabora"}).status_code == 400
        html = otro.get(f"/proyecto/{p}").get_data(as_text=True)
        assert "Cierre trimestral" in html and "Ajustes y miembros" not in html and "Salir del proyecto" in html and "colabora" in html
        assert "Compartidos conmigo" in otro.get("/").get_data(as_text=True)          # aparece en su dashboard
        assert otro.post(f"/proyecto/{p}/ajustes", data={"estado": "archivado"}).status_code == 403   # solo el dueño edita los datos
        assert otro.post(f"/proyecto/{p}/miembros", data={"usuario_id": uid, "rol": "observa"}).status_code == 400
        assert otro.post(f"/proyecto/{p}/miembros/{uid}/quitar").status_code == 403
        r = otro.post(f"/proyecto/{p}/miembros/{luis}/quitar")                          # se sale él mismo
        assert r.status_code == 302 and otro.get(f"/proyecto/{p}").status_code == 404


def test_la_lista_junta_las_tareas_de_todos_y_los_colaboradores_crean(cliente):
    uid, tenant, p = _dueno(cliente, "pg-4@x.com")
    with _otro_cliente("pg-4b@x.com") as (otro, luis):
        _miembro(otro, luis, tenant)
        db.compartir_proyecto(uid, p, luis, "colabora")
        db.crear_tarea_en_proyecto(uid, p, "Tarea de la dueña")
        assert otro.post(f"/proyecto/{p}/tareas", data={"asunto": "Tarea de Luis", "asignada_a": uid}).status_code == 302
        assert otro.post(f"/proyecto/{p}/tareas", data={"asunto": "   "}).status_code == 302            # vacío: vuelve con aviso
        for c in (cliente, otro):
            html = c.get(f"/proyecto/{p}/lista").get_data(as_text=True)
            assert "Tarea de la dueña" in html and "Tarea de Luis" in html
        # la dueña puede abrir y editar la tarea que creó Luis; Luis la de ella
        t_luis = [t for t in db.tareas_de_proyecto(uid, p) if t["asunto"] == "Tarea de Luis"][0]["id"]
        assert cliente.get(f"/tareas/{t_luis}/editar").status_code == 200
        assert cliente.post(f"/tareas/{t_luis}/completar").status_code == 302
        assert db.obtener_tarea_outlook_visible(uid, t_luis)["estado"] == "completada"
        assert "50 %" in cliente.get(f"/proyecto/{p}").get_data(as_text=True) or "100 %" in cliente.get(f"/proyecto/{p}").get_data(as_text=True)


def test_el_observador_ve_pero_no_puede_cambiar_nada(cliente):
    uid, tenant, p = _dueno(cliente, "pg-5@x.com")
    t = db.crear_tarea_en_proyecto(uid, p, "Solo mirar")
    with _otro_cliente("pg-5b@x.com") as (otro, eva):
        _miembro(otro, eva, tenant)
        db.compartir_proyecto(uid, p, eva, "observa")
        html = otro.get(f"/proyecto/{p}/lista").get_data(as_text=True)
        assert "Solo mirar" in html and "Añadir una tarea" not in html and "Nueva sección" not in html
        assert otro.post(f"/proyecto/{p}/tareas", data={"asunto": "No debería"}).status_code == 403
        assert otro.post(f"/proyecto/{p}/secciones", data={"nombre": "No"}).status_code == 400
        assert otro.post(f"/tareas/{t}/completar").status_code == 302
        assert db.obtener_tarea_outlook_visible(uid, t)["estado"] != "completada"      # el servidor lo ignora
        assert otro.get(f"/tareas/{t}/editar").status_code in (302, 403, 404)


def test_secciones_desde_la_pagina(cliente):
    uid, _, p = _dueno(cliente, "pg-6@x.com")
    assert cliente.post(f"/proyecto/{p}/secciones", data={"nombre": "1. Recoger documentación"}).status_code == 302
    assert cliente.post(f"/proyecto/{p}/secciones", data={"nombre": "2. Contabilizar"}).status_code == 302
    a, b = [s["id"] for s in db.listar_secciones(p)]
    t = db.crear_tarea_en_proyecto(uid, p, "Pedir extractos")
    assert cliente.post(f"/proyecto/{p}/tareas/{t}/seccion", data={"seccion_id": a}).status_code == 302
    html = cliente.get(f"/proyecto/{p}/lista").get_data(as_text=True)
    assert html.index("<h2>1. Recoger documentación") < html.index("Pedir extractos") < html.index("<h2>2. Contabilizar")
    assert cliente.post(f"/proyecto/{p}/secciones/{b}/mover", data={"direccion": "arriba"}).status_code == 302
    assert [s["id"] for s in db.listar_secciones(p)] == [b, a]
    assert cliente.post(f"/proyecto/{p}/secciones/{a}/renombrar", data={"nombre": "1. Documentación"}).status_code == 302
    assert cliente.post(f"/proyecto/{p}/secciones/999/renombrar", data={"nombre": "x"}).status_code == 404
    assert cliente.post(f"/proyecto/{p}/secciones/{a}/eliminar").status_code == 302
    assert db.obtener_tarea_outlook(uid, t)["seccion_id"] is None
    otro_proyecto = db.crear_categoria(uid, "Otro")
    seccion_ajena = db.crear_seccion(uid, otro_proyecto, "Ajena")
    assert cliente.post(f"/proyecto/{p}/secciones/{seccion_ajena}/eliminar").status_code == 404   # no se opera sobre secciones de otro proyecto


def test_ajustes_del_proyecto_desde_la_pagina(cliente):
    uid, tenant, p = _dueno(cliente, "pg-7@x.com")
    cli = db.crear_cliente_fiscal(tenant, "Panadería Sol")
    r = cliente.post(f"/proyecto/{p}/ajustes", data={"estado": "en_pausa", "fecha_objetivo": "2026-07-20", "descripcion": "Cierre del 2T", "cliente_fiscal_id": cli, "responsable_id": uid})
    assert r.status_code == 302
    html = cliente.get(f"/proyecto/{p}").get_data(as_text=True)
    assert "En pausa" in html and "2026-07-20" in html and "Panadería Sol" in html and "Cierre del 2T" in html
    assert cliente.post(f"/proyecto/{p}/ajustes", data={"estado": "inventado"}).status_code == 400
    assert cliente.post(f"/proyecto/{p}/ajustes", data={"estado": "activo", "fecha_objetivo": "mañana"}).status_code == 400


def test_proyecto_en_la_papelera_ya_no_se_ve(cliente):
    uid, tenant, p = _dueno(cliente, "pg-8@x.com")
    with _otro_cliente("pg-8b@x.com") as (otro, luis):
        _miembro(otro, luis, tenant)
        db.compartir_proyecto(uid, p, luis)
        assert otro.get(f"/proyecto/{p}").status_code == 200
        db.eliminar_categoria(uid, p)
        assert otro.get(f"/proyecto/{p}").status_code == 404 and cliente.get(f"/proyecto/{p}").status_code == 404


def test_los_formularios_de_tareas_ofrecen_los_proyectos_compartidos_donde_se_colabora(cliente):
    uid, tenant, p = _dueno(cliente, "pg-9@x.com", nombre="Proyecto compartido X")
    with _otro_cliente("pg-9b@x.com") as (otro, luis):
        _miembro(otro, luis, tenant)
        db.compartir_proyecto(uid, p, luis, "colabora")
        assert "Proyecto compartido X" in otro.get("/tareas/").get_data(as_text=True)
        t = db.crear_tarea_outlook(luis, "Suya", categoria_id=p)
        assert db.obtener_tarea_outlook(luis, t)["categoria_id"] == p
        db.compartir_proyecto(uid, p, luis, "observa")
        assert "Proyecto compartido X" not in otro.get("/tareas/nueva").get_data(as_text=True) if otro.get("/tareas/nueva").status_code == 200 else True
