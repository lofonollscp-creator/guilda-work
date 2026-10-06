"""Backoffice: visión global de tenants, usuarios y roles (resumen, filtros,
agrupación por tenant y mapa de acceso)."""
from app import db, herramientas
from tests.conftest import iniciar_sesion_de_prueba


def _admin(cliente, email="bo-vision-admin@ejemplo.com"):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    db.hacer_admin(email)
    return uid


def _usuario(email, tenant_id=None, gestor=False, supervisor=False):
    uid = db.crear_usuario_vinculado_a_kratos(email, "kratos-" + email)
    if tenant_id:
        db.asignar_tenant(uid, tenant_id)
    if gestor:
        db.asignar_gestor_fichajes(uid, True)
    if supervisor:
        db.asignar_supervisor_tenant(uid, True)
    return uid


def test_resumen_equipos_cuenta_roles_clientes_y_plan():
    t = db.crear_tenant("Equipo A")
    _usuario("a1@ejemplo.com", t, gestor=True)
    _usuario("a2@ejemplo.com", t, supervisor=True)
    _usuario("a3@ejemplo.com", t)
    db.hacer_admin("a3@ejemplo.com")
    db.crear_cliente_fiscal(t, "Cliente 1")
    vacio = db.crear_tenant("Equipo vacío")
    r = db.resumen_equipos_tenants()
    assert r[t]["usuarios"] == 3 and r[t]["admins"] == 1 and r[t]["gestores"] == 1 and r[t]["supervisores"] == 1
    assert r[t]["clientes"] == 1 and r[vacio]["usuarios"] == 0


def test_panel_de_tenants_muestra_kpis_y_roles(cliente):
    _admin(cliente)
    t = db.crear_tenant("Gestoría Visión")
    _usuario("vision1@ejemplo.com", t, gestor=True)
    html = cliente.get("/backoffice/").get_data(as_text=True)
    assert "bo-resumen" in html and "usuarios sin tenant" in html and "tenants sin usuarios" in html
    assert "Gestoría Visión" in html and "1 gestor" in html and f"{len(herramientas.HERRAMIENTAS)}/{len(herramientas.HERRAMIENTAS)}" in html
    assert "/backoffice/mapa" in html


def test_usuarios_filtra_por_texto_tenant_y_rol_y_agrupa(cliente):
    _admin(cliente)
    t1, t2 = db.crear_tenant("Alfa Gestión"), db.crear_tenant("Beta Asesores")
    _usuario("alfa-uno@ejemplo.com", t1, gestor=True)
    _usuario("beta-uno@ejemplo.com", t2, supervisor=True)
    _usuario("huerfano@ejemplo.com")
    todos = cliente.get("/backoffice/usuarios").get_data(as_text=True)
    assert "Alfa Gestión" in todos and "Beta Asesores" in todos and "hay que asignarlos" in todos
    assert todos.index('<tr class="bo-grupo bo-grupo-aviso">') < todos.index('<tr class="bo-grupo ">')  # los sin tenant, primero
    solo_alfa = cliente.get(f"/backoffice/usuarios?tenant={t1}").get_data(as_text=True)
    assert "alfa-uno@ejemplo.com" in solo_alfa and "beta-uno@ejemplo.com" not in solo_alfa
    assert "huerfano@ejemplo.com" in cliente.get("/backoffice/usuarios?tenant=ninguno").get_data(as_text=True)
    sup = cliente.get("/backoffice/usuarios?rol=supervisor").get_data(as_text=True)
    assert "beta-uno@ejemplo.com" in sup and "alfa-uno@ejemplo.com" not in sup
    gest = cliente.get("/backoffice/usuarios?rol=gestor&q=ALFA").get_data(as_text=True)
    assert "alfa-uno@ejemplo.com" in gest and "beta-uno@ejemplo.com" not in gest
    assert "Ningún usuario coincide" in cliente.get("/backoffice/usuarios?q=zzz").get_data(as_text=True)


def test_los_permisos_se_cambian_desde_las_pastillas(cliente):
    _admin(cliente)
    t = db.crear_tenant("Pastillas")
    uid = _usuario("pastilla@ejemplo.com", t)
    html = cliente.get("/backoffice/usuarios").get_data(as_text=True)
    assert 'aria-pressed="false"' in html
    cliente.post(f"/backoffice/usuarios/{uid}/gestor-fichajes")
    cliente.post(f"/backoffice/usuarios/{uid}/supervisor-tenant")
    u = db.obtener_usuario(uid)
    assert u["gestor_fichajes"] and u["supervisor_tenant"]


def test_mapa_de_acceso_matriz_de_modulos_y_roles(cliente):
    _admin(cliente)
    t1, t2 = db.crear_tenant("Mapa Uno"), db.crear_tenant("Mapa Dos")
    _usuario("mapa-gestor@ejemplo.com", t1, gestor=True)
    modulo = herramientas.HERRAMIENTAS[0]
    db.ocultar_herramienta(t2, modulo["id"])
    html = cliente.get("/backoffice/mapa").get_data(as_text=True)
    assert "Mapa Uno" in html and "Mapa Dos" in html and "mapa-gestor@ejemplo.com" in html and "Gestor de fichajes" in html
    fila = html[html.index(modulo["nombre"]):]
    assert "is-on" in fila and "is-off" in fila
    assert "/backoffice/tenants/" in html


def test_mapa_y_usuarios_solo_para_admin(cliente):
    iniciar_sesion_de_prueba(cliente, "bo-vision-noadmin@ejemplo.com", "contrasena123")
    assert cliente.get("/backoffice/mapa").status_code == 403
    assert cliente.get("/backoffice/usuarios?rol=admin").status_code == 403


def test_ficha_del_tenant_muestra_resumen_y_permisos(cliente):
    _admin(cliente)
    t = db.crear_tenant("Ficha Visión")
    _usuario("ficha-vision@ejemplo.com", t, supervisor=True)
    html = cliente.get(f"/backoffice/tenants/{t}").get_data(as_text=True)
    assert "bo-resumen" in html and "supervisores" in html and "bo-permiso is-on" in html
