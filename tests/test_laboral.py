"""Gestión laboral, primera rebanada (app/laboral.py): trabajadores de cada cliente, su pestaña en la ficha única, permisos, registro de accesos y privacidad."""
import pytest

from app import acceso, db, laboral
from tests.conftest import iniciar_sesion_de_prueba


def _despacho(nombre="Despacho laboral"):
    t = db.crear_tenant(nombre)
    u = db.crear_usuario_vinculado_a_kratos(f"lab-{nombre.replace(' ', '')}@ejemplo.com", f"k-{nombre}")
    db.asignar_tenant(u, t)
    return t, u, db.crear_cliente_fiscal(t, "Panadería SL")


def test_crear_y_listar_un_trabajador_con_sus_datos():
    t, u, c = _despacho()
    w = laboral.crear(t, u, c, "Ana Ruiz", nif="12345678-z", naf="28 1234567 89", puesto="Dependienta", tipo_contrato="indefinido", jornada_horas_semana="37,5",
                      fecha_alta="2025-03-01", notas="Turno de mañana")
    (t1,) = laboral.listar(t, c)
    assert t1["id"] == w and t1["nombre"] == "Ana Ruiz" and t1["nif_normalizado"] == "12345678Z" and t1["naf"] == "28123456789"
    assert t1["jornada_horas_semana"] == 37.5 and t1["tipo_contrato"] == "indefinido" and t1["fecha_alta"] == "2025-03-01" and t1["de_baja"] is False


@pytest.mark.parametrize("datos,fragmento", [
    ({"nombre": "  "}, "nombre"),
    ({"nombre": "A", "naf": "abc"}, "afiliación"),
    ({"nombre": "A", "naf": "123"}, "afiliación"),
    ({"nombre": "A", "jornada_horas_semana": "mucha"}, "horas a la semana"),
    ({"nombre": "A", "jornada_horas_semana": "90"}, "entre 0 y 60"),
    ({"nombre": "A", "tipo_contrato": "inventado"}, "contrato"),
    ({"nombre": "A", "fecha_alta": "ayer"}, "fecha no válida"),
    ({"nombre": "A", "fecha_alta": "2025-05-01", "fecha_baja": "2025-04-30"}, "anterior al alta"),
])
def test_los_datos_no_validos_se_rechazan_con_un_mensaje(datos, fragmento):
    t, u, c = _despacho()
    nombre = datos.pop("nombre")
    with pytest.raises(ValueError, match=fragmento):
        laboral.crear(t, u, c, nombre, **datos)
    assert laboral.listar(t, c) == []


def test_un_mismo_nif_no_se_repite_en_un_cliente_pero_si_en_otro_o_tras_borrar():
    t, u, c = _despacho()
    otro = db.crear_cliente_fiscal(t, "Taller SL")
    w = laboral.crear(t, u, c, "Ana", nif="12345678Z")
    with pytest.raises(ValueError, match="mismo NIF|ese NIF"):
        laboral.crear(t, u, c, "Ana otra vez", nif="12.345.678-z")
    laboral.crear(t, u, otro, "Ana en otro cliente", nif="12345678Z")
    laboral.eliminar(t, w)
    laboral.crear(t, u, c, "Ana de nuevo", nif="12345678Z")


def test_el_cliente_debe_ser_del_despacho():
    t, u, c = _despacho()
    t2, _, c2 = _despacho("Otro despacho laboral")
    with pytest.raises(ValueError, match="Cliente no encontrado"):
        laboral.crear(t, u, c2, "Intruso")


def test_los_que_ya_han_causado_baja_van_despues_y_una_baja_futura_sigue_de_alta():
    t, u, c = _despacho()
    laboral.crear(t, u, c, "Zoe", fecha_alta="2020-01-01")
    laboral.crear(t, u, c, "Berta", fecha_alta="2020-01-01", fecha_baja="2026-01-31")
    laboral.crear(t, u, c, "Carla", fecha_alta="2020-01-01", fecha_baja="2026-12-31")
    nombres = [(w["nombre"], w["de_baja"]) for w in laboral.listar(t, c, hoy="2026-06-15")]
    assert nombres == [("Carla", False), ("Zoe", False), ("Berta", True)]


def test_editar_cambia_solo_lo_pedido_y_permite_reactivar():
    t, u, c = _despacho()
    w = laboral.crear(t, u, c, "Ana", puesto="Dependienta", fecha_alta="2020-01-01", fecha_baja="2026-01-31")
    laboral.editar(t, w, puesto="Encargada", fecha_baja="")
    fila = laboral.obtener(t, w)
    assert fila["puesto"] == "Encargada" and fila["fecha_baja"] is None and fila["nombre"] == "Ana" and fila["actualizado_en"]
    with pytest.raises(ValueError):
        laboral.editar(t, w, nombre="")
    t2, _, _ = _despacho("Despacho ajeno laboral")
    with pytest.raises(ValueError, match="no encontrado"):
        laboral.editar(t2, w, puesto="Hackeo")


def test_eliminar_manda_a_la_papelera_y_el_vaciado_lo_borra_de_verdad():
    from app import rgpd           # (se importa aquí, como en los demás tests: importarlo el primero crea un ciclo con el almacén de documentos)
    t, u, c = _despacho()
    w = laboral.crear(t, u, c, "Ana")
    assert laboral.eliminar(t, w) is True and laboral.eliminar(t, w) is False
    assert laboral.listar(t, c) == [] and laboral.obtener(t, w) is None
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM trabajadores_cliente").fetchone()[0] == 1
    conn.close()
    rgpd.vaciar_papelera(t, u, 0)
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM trabajadores_cliente").fetchone()[0] == 0
    conn.close()


def test_la_exportacion_rgpd_del_cliente_incluye_sus_trabajadores():
    from app import rgpd
    t, u, c = _despacho()
    laboral.crear(t, u, c, "Ana Ruiz", nif="12345678Z")
    cliente_nucleo = db.obtener_cliente_fiscal(t, c)["cliente_id"]
    datos = rgpd.exportar_cliente(t, u, True, cliente_nucleo)
    assert [w["nombre"] for w in datos["trabajadores"]] == ["Ana Ruiz"] and "nif_normalizado" not in datos["trabajadores"][0]


def test_borrar_el_cliente_definitivamente_se_lleva_a_sus_trabajadores():
    t, u, c = _despacho()
    laboral.crear(t, u, c, "Ana")
    db.eliminar_cliente_fiscal(t, c)
    db.eliminar_cliente_fiscal_definitivamente(t, c)
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM trabajadores_cliente").fetchone()[0] == 0
    conn.close()


# --- Pantallas ------------------------------------------------------------------------------------------------------------------------------

def _con_cliente(cliente_http, email):
    uid = iniciar_sesion_de_prueba(cliente_http, email, "contrasena123")
    t = db.crear_tenant(f"Despacho {email}")
    db.asignar_tenant(uid, t)
    fid = db.crear_cliente_fiscal(t, "Cliente Laboral")
    return uid, t, fid, db.obtener_cliente_fiscal(t, fid)["cliente_id"]


def _acciones(t, fid):
    return [a["accion"] for a in reversed(db.listar_accesos_cliente(t, fid))]


def test_la_pestana_laboral_solo_existe_con_gestion_fiscal(cliente):
    uid, t, fid, cid = _con_cliente(cliente, "lab-pest@ejemplo.com")
    assert "pestana=laboral" in cliente.get(f"/clientes/{cid}").get_data(as_text=True)
    from app import nucleo
    solo = nucleo.crear_cliente(t, "Solo núcleo")
    html = cliente.get(f"/clientes/{solo}?pestana=laboral").get_data(as_text=True)
    assert "pestana=laboral" not in html and "Trabajadores" not in html


def test_alta_edicion_y_baja_desde_la_web_con_registro_de_accesos(cliente):
    uid, t, fid, cid = _con_cliente(cliente, "lab-web@ejemplo.com")
    assert "todavía no tiene trabajadores" in cliente.get(f"/clientes/{cid}?pestana=laboral").get_data(as_text=True)
    r = cliente.post(f"/fiscal/clientes/{fid}/trabajadores", data={"nombre": "Ana Ruiz", "puesto": "Dependienta", "tipo_contrato": "indefinido", "jornada_horas_semana": "40"})
    assert r.status_code == 302 and f"/clientes/{cid}" in r.headers["Location"] and "pestana=laboral" in r.headers["Location"] and "error" not in r.headers["Location"]
    (w,) = laboral.listar(t, fid)
    html = cliente.get(f"/clientes/{cid}?pestana=laboral").get_data(as_text=True)
    assert "Ana Ruiz" in html and "Dependienta" in html and "Indefinido" in html and "40 h/semana" in html
    assert cliente.post(f"/fiscal/clientes/{fid}/trabajadores/{w['id']}", data={"nombre": "Ana Ruiz", "puesto": "Encargada"}).status_code == 302
    assert laboral.obtener(t, w["id"])["puesto"] == "Encargada"
    assert cliente.post(f"/fiscal/clientes/{fid}/trabajadores/{w['id']}/eliminar").status_code == 302
    assert laboral.listar(t, fid) == []
    acc = _acciones(t, fid)
    assert acc.count("trabajador_creado") == 1 and acc.count("trabajador_editado") == 1 and acc.count("trabajador_eliminado") == 1 and "laboral_visto" in acc
    assert all("Ana" not in (a["detalle"] or "") for a in db.listar_accesos_cliente(t, fid)), "el registro de accesos no copia nombres de trabajadores"


def test_abrir_la_pestana_dos_veces_seguidas_se_anota_una_vez(cliente):
    uid, t, fid, cid = _con_cliente(cliente, "lab-dedup@ejemplo.com")
    cliente.get(f"/clientes/{cid}?pestana=laboral"); cliente.get(f"/clientes/{cid}?pestana=laboral")
    assert _acciones(t, fid).count("laboral_visto") == 1


def test_un_error_de_validacion_se_ve_en_la_ficha_y_no_crea_nada(cliente):
    uid, t, fid, cid = _con_cliente(cliente, "lab-err@ejemplo.com")
    r = cliente.post(f"/fiscal/clientes/{fid}/trabajadores", data={"nombre": "Ana", "naf": "abc"}, follow_redirects=True)
    assert "solo lleva dígitos" in r.get_data(as_text=True) and laboral.listar(t, fid) == []


def test_no_se_toca_un_trabajador_de_otro_cliente_ni_de_otro_despacho(cliente):
    uid, t, fid, cid = _con_cliente(cliente, "lab-aislado@ejemplo.com")
    otro_cliente = db.crear_cliente_fiscal(t, "Otro cliente")
    w_otro = laboral.crear(t, uid, otro_cliente, "De otro cliente")
    assert cliente.post(f"/fiscal/clientes/{fid}/trabajadores/{w_otro}", data={"nombre": "x"}).status_code == 404
    assert cliente.post(f"/fiscal/clientes/{fid}/trabajadores/{w_otro}/eliminar").status_code == 404
    ajeno_t, ajeno_u, ajeno_c = _despacho("Despacho ajeno web")
    assert cliente.post(f"/fiscal/clientes/{ajeno_c}/trabajadores", data={"nombre": "Intruso"}).status_code == 404
    assert laboral.obtener(t, w_otro)["nombre"] == "De otro cliente"


def test_el_auditor_ve_los_trabajadores_pero_no_los_toca(cliente):
    uid, t, fid, cid = _con_cliente(cliente, "lab-aud@ejemplo.com")
    jefe = db.crear_usuario_vinculado_a_kratos("jefe-lab@ejemplo.com", "k-jefe-lab"); db.asignar_tenant(jefe, t); db.asignar_supervisor_tenant(jefe, True)
    w = laboral.crear(t, jefe, fid, "Ana Ruiz")
    acceso.dar_membresia(t, jefe, uid, "auditor", "organizacion")
    html = cliente.get(f"/clientes/{cid}?pestana=laboral").get_data(as_text=True)
    assert "Ana Ruiz" in html and "Dar de alta a un trabajador" not in html and "Guardar" not in html
    assert cliente.post(f"/fiscal/clientes/{fid}/trabajadores", data={"nombre": "Intento"}).status_code == 403
    assert cliente.post(f"/fiscal/clientes/{fid}/trabajadores/{w}/eliminar").status_code == 403


def test_quien_no_ve_el_cliente_por_oficina_no_ve_sus_trabajadores(cliente):
    uid, t, fid, cid = _con_cliente(cliente, "lab-of@ejemplo.com")
    jefe = db.crear_usuario_vinculado_a_kratos("jefe-of-lab@ejemplo.com", "k-jefe-of-lab"); db.asignar_tenant(jefe, t); db.asignar_supervisor_tenant(jefe, True)
    laboral.crear(t, jefe, fid, "Ana Ruiz")
    girona, bcn = acceso.crear_oficina(t, jefe, "Girona"), acceso.crear_oficina(t, jefe, "Barcelona")
    acceso.asignar_cliente_a_oficina(t, jefe, fid, bcn)
    acceso.dar_membresia(t, jefe, uid, "gestor", "oficina", girona)
    assert cliente.get(f"/clientes/{cid}?pestana=laboral").status_code == 404
    assert cliente.post(f"/fiscal/clientes/{fid}/trabajadores", data={"nombre": "Intento"}).status_code == 404


def test_el_menu_lateral_llama_gestoria_al_modulo(cliente):
    uid, t, fid, cid = _con_cliente(cliente, "lab-menu@ejemplo.com")
    html = cliente.get("/clientes/").get_data(as_text=True)
    assert "Expandir Gestoría" in html and "Expandir Fiscal" not in html


def test_vaciar_la_papelera_desde_privacidad_cuenta_a_los_trabajadores_borrados(cliente):
    uid, t, fid, cid = _con_cliente(cliente, "lab-papelera@ejemplo.com")
    db.asignar_supervisor_tenant(uid, True)
    w = laboral.crear(t, uid, fid, "Ana")
    laboral.eliminar(t, w)
    r = cliente.post("/seguridad/privacidad/vaciar-papelera", data={"dias": "0"}, follow_redirects=True)
    assert r.status_code == 200 and "También 1 trabajadores de clientes." in r.get_data(as_text=True)
