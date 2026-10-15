"""Libreta de contactos del despacho (app/contactos.py, app/rutas_contactos.py): alta, grupos, visibilidad, autocompletado y privacidad."""
import pytest

from app import contactos, db, nucleo, rgpd
from tests.conftest import iniciar_sesion_de_prueba


def _despacho(nombre="Despacho contactos"):
    t = db.crear_tenant(nombre)
    u = db.crear_usuario_vinculado_a_kratos(f"con-{nombre.replace(' ', '')}@ejemplo.com", f"k-{nombre}")
    db.asignar_tenant(u, t)
    return t, u


def test_crear_y_listar_un_contacto():
    t, u = _despacho()
    c = contactos.crear(t, u, nombre="  Marta   Luna ", email="Marta@Luna.TEST", telefono="600 111 222", empresa="Luna SL", notas="Proveedora")
    (f,) = contactos.listar(t, u)
    assert f["id"] == c and f["nombre"] == "Marta Luna" and f["email"] == "marta@luna.test" and f["empresa"] == "Luna SL"


@pytest.mark.parametrize("datos,fragmento", [({"nombre": " "}, "nombre"), ({"nombre": "A", "email": "sin-arroba"}, "no es válido"), ({"nombre": "A", "email": "a@b"}, "no es válido")])
def test_validacion_de_contactos(datos, fragmento):
    t, u = _despacho()
    with pytest.raises(ValueError, match=fragmento):
        contactos.crear(t, u, **datos)
    assert contactos.listar(t, u) == []


def test_el_correo_no_se_repite_pero_se_puede_sin_correo_y_tras_borrar():
    t, u = _despacho()
    a = contactos.crear(t, u, nombre="Ana", email="ana@x.test")
    with pytest.raises(ValueError, match="Ya hay un contacto"):
        contactos.crear(t, u, nombre="Otra Ana", email="ANA@x.test")
    contactos.crear(t, u, nombre="Sin correo 1"); contactos.crear(t, u, nombre="Sin correo 2")
    contactos.eliminar(t, u, a)
    contactos.crear(t, u, nombre="Ana de nuevo", email="ana@x.test")
    assert len(contactos.listar(t, u)) == 3


def test_editar_y_eliminar_y_otro_despacho_no_lo_ve():
    t, u = _despacho(); t2, u2 = _despacho("Otro despacho contactos")
    c = contactos.crear(t, u, nombre="Ana", email="ana@x.test")
    contactos.editar(t, u, c, nombre="Ana Ruiz", telefono="600")
    assert contactos.obtener(t, u, c)["nombre"] == "Ana Ruiz"
    assert contactos.obtener(t2, u2, c) is None and contactos.listar(t2, u2) == []
    with pytest.raises(ValueError, match="no encontrado"):
        contactos.editar(t2, u2, c, nombre="Hackeado")
    assert contactos.eliminar(t2, u2, c) is False and contactos.eliminar(t, u, c) is True and contactos.listar(t, u) == []


def test_busqueda_por_nombre_correo_y_empresa():
    t, u = _despacho()
    contactos.crear(t, u, nombre="Marta Luna", email="marta@luna.test", empresa="Luna SL"); contactos.crear(t, u, nombre="Pedro Sol", email="pedro@sol.test")
    assert [c["nombre"] for c in contactos.listar(t, u, "luna")] == ["Marta Luna"]
    assert [c["nombre"] for c in contactos.listar(t, u, "sol.test")] == ["Pedro Sol"] and contactos.listar(t, u, "zzz") == []


def test_grupos_miembros_y_borrado():
    t, u = _despacho()
    a = contactos.crear(t, u, nombre="Ana", email="ana@x.test"); b = contactos.crear(t, u, nombre="Beto", email="beto@x.test")
    g = contactos.crear_grupo(t, "Proveedores")
    with pytest.raises(ValueError, match="Ya hay un grupo"):
        contactos.crear_grupo(t, "proveedores")
    contactos.poner_en_grupo(t, u, g, a); contactos.poner_en_grupo(t, u, g, b); contactos.poner_en_grupo(t, u, g, a)      # repetir no duplica
    assert contactos.listar_grupos(t, u)[0]["n"] == 2 and [c["nombre"] for c in contactos.listar(t, u, grupo_id=g)] == ["Ana", "Beto"]
    contactos.poner_en_grupo(t, u, g, b, dentro=False)
    assert contactos.grupos_de(t, a) == [g] and contactos.grupos_de(t, b) == []
    contactos.eliminar(t, u, a)
    assert contactos.listar_grupos(t, u)[0]["n"] == 0
    contactos.eliminar_grupo(t, g)
    assert contactos.listar_grupos(t, u) == [] and len(contactos.listar(t, u)) == 1          # el contacto que queda no se borra con el grupo


def test_un_grupo_de_otro_despacho_no_se_toca():
    t, u = _despacho(); t2, u2 = _despacho("Otro despacho contactos")
    g2 = contactos.crear_grupo(t2, "Ajeno"); a = contactos.crear(t, u, nombre="Ana", email="ana@x.test")
    with pytest.raises(ValueError, match="Grupo no encontrado"):
        contactos.poner_en_grupo(t, u, g2, a)
    contactos.eliminar_grupo(t, g2)
    assert len(contactos.listar_grupos(t2, u2)) == 1


def test_sugerencias_con_grupos_en_una_sola_entrada():
    t, u = _despacho()
    a = contactos.crear(t, u, nombre="Ana Pro", email="ana@x.test", empresa="Pro SL"); b = contactos.crear(t, u, nombre="Beto Pro", email="beto@x.test"); contactos.crear(t, u, nombre="Sin correo Pro")
    g = contactos.crear_grupo(t, "Proveedores")
    contactos.poner_en_grupo(t, u, g, a); contactos.poner_en_grupo(t, u, g, b)
    s = contactos.sugerencias(t, u, "prov")
    assert s == [{"direccion": "ana@x.test, beto@x.test", "nombre_mostrado": "Grupo: Proveedores (2)"}]
    s = contactos.sugerencias(t, u, "pro")
    assert s[0]["nombre_mostrado"].startswith("Grupo: Proveedores") and {x["direccion"] for x in s[1:]} == {"ana@x.test", "beto@x.test"}
    assert contactos.sugerencias(t, u, "p") == []


def test_guardar_desde_correo_no_duplica_y_rechaza_remitentes_sin_direccion():
    t, u = _despacho()
    i = contactos.guardar_desde_correo(t, u, '"Marta Luna" <Marta@Luna.test>')
    assert contactos.guardar_desde_correo(t, u, "marta@luna.test") == i and len(contactos.listar(t, u)) == 1
    assert contactos.obtener(t, u, i)["nombre"] == "Marta Luna"
    assert contactos.guardar_desde_correo(t, u, "pedro@sol.test") and contactos.listar(t, u, "pedro")[0]["nombre"] == "pedro"
    with pytest.raises(ValueError, match="remitente"):
        contactos.guardar_desde_correo(t, u, "sin direccion")


# --- Cliente, privacidad y RGPD -----------------------------------------------------------------------------------------------------------------

def test_un_contacto_enlazado_a_un_cliente_sale_en_su_exportacion_y_se_purga_con_la_papelera():
    t, u = _despacho()
    cliente = nucleo.crear_cliente(t, "Panadería Luna")
    c = contactos.crear(t, u, nombre="Marta", email="marta@luna.test", cliente_id=cliente)
    contactos.crear(t, u, nombre="Libre", email="libre@x.test")
    datos = rgpd.exportar_cliente(t, u, True, cliente)
    assert [x["email"] for x in datos["libreta_de_contactos"]] == ["marta@luna.test"]
    contactos.eliminar(t, u, c)
    assert rgpd.exportar_cliente(t, u, True, cliente)["libreta_de_contactos"] == []
    assert rgpd.vaciar_papelera(t, u, 0)["contactos"] == 1 and len(contactos.listar(t, u)) == 1


def test_un_cliente_de_otro_despacho_no_se_puede_enlazar():
    t, u = _despacho(); t2, _ = _despacho("Otro despacho contactos")
    ajeno = nucleo.crear_cliente(t2, "Ajeno SL")
    with pytest.raises(ValueError, match="Cliente no encontrado"):
        contactos.crear(t, u, nombre="Ana", email="ana@x.test", cliente_id=ajeno)


# --- Pantalla y Correo ---------------------------------------------------------------------------------------------------------------------------

def test_la_pantalla_crea_edita_y_borra(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "con-web@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho web contactos"); db.asignar_tenant(uid, t)
    assert cliente.post("/contactos/", data={"nombre": "Marta", "email": "marta@luna.test"}).status_code == 302
    (c,) = contactos.listar(t, uid)
    assert "Marta" in cliente.get("/contactos/").get_data(as_text=True)
    r = cliente.post("/contactos/", data={"nombre": "Otra", "email": "marta@luna.test"})
    assert "error=" in r.headers["Location"] and "Ya hay un contacto" in cliente.get(r.headers["Location"]).get_data(as_text=True)
    g = contactos.crear_grupo(t, "Proveedores")
    cliente.post(f"/contactos/{c['id']}", data={"nombre": "Marta Luna", "email": "marta@luna.test", "grupos": [str(g)]})
    assert contactos.obtener(t, uid, c["id"])["nombre"] == "Marta Luna" and contactos.grupos_de(t, c["id"]) == [g]
    assert "Editar contacto" in cliente.get(f"/contactos/?editar={c['id']}").get_data(as_text=True)
    cliente.post(f"/contactos/{c['id']}/eliminar")
    assert contactos.listar(t, uid) == []
    assert cliente.post("/contactos/99999/eliminar").status_code == 404


def test_sin_sesion_o_sin_despacho_no_hay_libreta(cliente):
    assert cliente.get("/contactos/").status_code == 302
    iniciar_sesion_de_prueba(cliente, "con-sin@ejemplo.com", "contrasena123")
    assert cliente.get("/contactos/").status_code == 404


def test_el_autocompletado_de_correo_usa_la_libreta_y_los_grupos(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "con-auto@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho auto contactos"); db.asignar_tenant(uid, t)
    a = contactos.crear(t, uid, nombre="Ana Pro", email="ana@x.test"); b = contactos.crear(t, uid, nombre="Beto Pro", email="beto@x.test")
    g = contactos.crear_grupo(t, "Proveedores"); contactos.poner_en_grupo(t, uid, g, a); contactos.poner_en_grupo(t, uid, g, b)
    r = cliente.get("/correo/destinatarios-recientes?q=prov").get_json()
    assert r[0]["direccion"] == "ana@x.test, beto@x.test"
    r = cliente.get("/correo/destinatarios-recientes?q=beto").get_json()
    assert [x["direccion"] for x in r] == ["beto@x.test"]


def test_guardar_al_remitente_desde_un_correo(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "con-cor@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho cor contactos"); db.asignar_tenant(uid, t)
    cuenta = db.crear_cuenta_correo(uid, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    m = db.guardar_mensaje_correo(cuenta_id=cuenta, uid="1", asunto="Hola", remitente='"Ana Ruiz" <ana@x.test>', destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="x", cuerpo_html=None)
    assert "A contactos" in cliente.get(f"/correo/?cuenta_id={cuenta}&mensaje_id={m}").get_data(as_text=True)
    r = cliente.post(f"/correo/{m}/guardar-contacto")
    assert r.status_code == 302 and [c["email"] for c in contactos.listar(t, uid)] == ["ana@x.test"]
    cliente.post(f"/correo/{m}/guardar-contacto")
    assert len(contactos.listar(t, uid)) == 1
