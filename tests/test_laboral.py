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
    w = laboral.crear(t, u, c, "Ana Ruiz", nif="12345678-z", naf="28 1234567 89", puesto="Dependienta", categoria="Oficial 1.ª", convenio="Convenio de comercio de Girona",
                      tipo_contrato="indefinido", jornada_horas_semana="37,5", fecha_alta="2025-03-01", notas="Turno de mañana")
    (t1,) = laboral.listar(t, c)
    assert t1["id"] == w and t1["nombre"] == "Ana Ruiz" and t1["nif_normalizado"] == "12345678Z" and t1["naf"] == "28 1234567 89"
    assert t1["categoria"] == "Oficial 1.ª" and t1["convenio"] == "Convenio de comercio de Girona"
    assert t1["jornada_horas_semana"] == 37.5 and t1["tipo_contrato"] == "indefinido" and t1["fecha_alta"] == "2025-03-01" and t1["de_baja"] is False


@pytest.mark.parametrize("datos,fragmento", [
    ({"nombre": "  "}, "nombre"),
    ({"nombre": "A", "jornada_horas_semana": "mucha"}, "horas a la semana"),
    ({"nombre": "A", "jornada_horas_semana": "-5"}, "horas a la semana"),
    ({"nombre": "A", "tipo_contrato": "inventado"}, "contrato"),
    ({"nombre": "A", "fecha_alta": "ayer"}, "fecha no válida"),
])
def test_solo_se_rechaza_lo_que_no_se_puede_interpretar(datos, fragmento):
    t, u, c = _despacho()
    nombre = datos.pop("nombre")
    with pytest.raises(ValueError, match=fragmento):
        laboral.crear(t, u, c, nombre, **datos)
    assert laboral.listar(t, c) == []


def test_solo_el_nombre_es_obligatorio_y_el_resto_se_guarda_aunque_no_cuadre():
    t, u, c = _despacho()
    laboral.crear(t, u, c, "Solo nombre")
    w = laboral.crear(t, u, c, "Datos raros", naf="ES-sin-digitos", jornada_horas_semana="70", tipo_contrato="", fecha_alta="2025-05-01", fecha_baja="2025-04-30", nif="¿?")
    fila = laboral.obtener(t, w)
    assert fila["naf"] == "ES-sin-digitos" and fila["jornada_horas_semana"] == 70 and fila["fecha_baja"] == "2025-04-30"
    assert len(laboral.listar(t, c)) == 2


def test_un_nif_repetido_no_impide_guardar_solo_se_senala():
    t, u, c = _despacho()
    otro = db.crear_cliente_fiscal(t, "Taller SL")
    w = laboral.crear(t, u, c, "Ana", nif="12345678Z", fecha_alta="2020-01-01", fecha_baja="2021-01-01")
    nuevo = laboral.crear(t, u, c, "Ana (recontratada)", nif="12.345.678-z", fecha_alta="2024-01-01")        # el caso real: se vuelve a contratar a quien ya causó baja
    solo_otro = laboral.crear(t, u, otro, "Ana en otro cliente", nif="12345678Z")
    marcas = {x["id"]: x["nif_repetido"] for x in laboral.listar(t, c)}
    assert marcas == {w: True, nuevo: True} and laboral.listar(t, otro)[0]["id"] == solo_otro and laboral.listar(t, otro)[0]["nif_repetido"] is False
    laboral.eliminar(t, w)
    assert [x["nif_repetido"] for x in laboral.listar(t, c)] == [False]


def test_una_baja_anterior_al_alta_se_guarda_con_aviso():
    t, u, c = _despacho()
    laboral.crear(t, u, c, "Revés", fecha_alta="2025-05-01", fecha_baja="2025-04-30")
    laboral.crear(t, u, c, "Bien", fecha_alta="2025-05-01", fecha_baja="2025-06-01")
    assert {x["nombre"]: x["baja_antes_del_alta"] for x in laboral.listar(t, c)} == {"Revés": True, "Bien": False}


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
    r = cliente.post(f"/fiscal/clientes/{fid}/trabajadores", data={"nombre": "Ana", "fecha_alta": "ayer"}, follow_redirects=True)
    assert "fecha no válida" in r.get_data(as_text=True) and laboral.listar(t, fid) == []


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


def test_las_bases_creadas_antes_ganan_convenio_y_categoria_y_pierden_la_unicidad_de_nif():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE trabajadores_cliente (id INTEGER PRIMARY KEY, tenant_id INTEGER, cliente_fiscal_id INTEGER, nombre TEXT, nif_normalizado TEXT, papelera_en TEXT)")
    conn.execute("CREATE UNIQUE INDEX ux_trabajadores_cliente_nif ON trabajadores_cliente(cliente_fiscal_id, nif_normalizado)")
    conn.execute("CREATE TABLE vencimientos_fiscales (id INTEGER PRIMARY KEY)")
    laboral.crear_esquema(conn)
    assert "trabajador_id" in {f["name"] for f in conn.execute("PRAGMA table_info(vencimientos_fiscales)")}
    laboral.crear_esquema(conn)                                           # idempotente
    assert {"categoria", "convenio"} <= {f["name"] for f in conn.execute("PRAGMA table_info(trabajadores_cliente)")}
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'ux_trabajadores_cliente_nif'").fetchone()


def test_la_exportacion_rgpd_incluye_convenio_y_categoria():
    from app import rgpd
    t, u, c = _despacho()
    laboral.crear(t, u, c, "Ana", categoria="Oficial 1.ª", convenio="Comercio")
    datos = rgpd.exportar_cliente(t, u, True, db.obtener_cliente_fiscal(t, c)["cliente_id"])
    assert datos["trabajadores"][0]["categoria"] == "Oficial 1.ª" and datos["trabajadores"][0]["convenio"] == "Comercio"


def test_la_pantalla_deja_rellenar_convenio_y_categoria_y_avisa_sin_bloquear(cliente):
    uid, t, fid, cid = _con_cliente(cliente, "lab-opc@ejemplo.com")
    for nombre in ("Ana Ruiz", "Ana Ruiz (otra vez)"):
        r = cliente.post(f"/fiscal/clientes/{fid}/trabajadores", data={"nombre": nombre, "nif": "12345678Z", "naf": "sin dígitos", "categoria": "Oficial 1.ª", "convenio": "Comercio de Girona",
                                                                      "fecha_alta": "2025-05-01", "fecha_baja": "2025-04-01"})
        assert r.status_code == 302 and "error" not in r.headers["Location"]
    html = cliente.get(f"/clientes/{cid}?pestana=laboral").get_data(as_text=True)
    assert "Categoría profesional" in html and "Convenio colectivo" in html and "Comercio de Girona" in html and "Oficial 1.ª" in html
    assert "NIF repetido" in html and "Baja anterior al alta" in html and "Solo el nombre es obligatorio" in html
    assert len(laboral.listar(t, fid)) == 2
