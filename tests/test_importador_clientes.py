"""Importar clientes desde Excel o CSV (app/importador_clientes.py y app/rutas_importar_clientes.py)."""
import io
import os
import re
import time

import pytest
from openpyxl import Workbook

from app import db, importador_clientes as imp, nucleo
from tests.conftest import iniciar_sesion_de_prueba


def _t(nombre="Despacho import"):
    return db.crear_tenant(nombre)


def _csv(texto, codificacion="utf-8"):
    return texto.encode(codificacion)


def _xlsx(filas):
    libro = Workbook()
    hoja = libro.active
    for f in filas:
        hoja.append(f)
    sal = io.BytesIO()
    libro.save(sal)
    return sal.getvalue()


# --- Leer ------------------------------------------------------------------------------------------------------------------------------------------

def test_csv_con_punto_y_coma_y_con_coma_y_con_tabulador():
    for sep in (";", ",", "\t"):
        cab, filas = imp.leer_archivo("c.csv", _csv(f"Nombre{sep}NIF{sep}Email\nAna{sep}12345678Z{sep}a@x.es\n"))
        assert cab == ["Nombre", "NIF", "Email"] and filas == [["Ana", "12345678Z", "a@x.es"]]


def test_csv_en_windows_1252_con_tildes():
    cab, filas = imp.leer_archivo("c.csv", "Nombre;Teléfono\nJosé Muñoz;600123456\n".encode("cp1252"))
    assert cab == ["Nombre", "Teléfono"] and filas[0][0] == "José Muñoz"


def test_xlsx_numeros_enteros_no_quedan_como_decimales():
    cab, filas = imp.leer_archivo("c.xlsx", _xlsx([["Nombre", "Teléfono"], ["Ana", 600123456.0], ["Luis", 612345678]]))
    assert filas == [["Ana", "600123456"], ["Luis", "612345678"]]


@pytest.mark.parametrize("nombre,datos,fragmento", [
    ("c.csv", b"", "vacío"),
    ("c.csv", b"Nombre\n", "al menos un cliente"),
    ("c.pdf", b"Nombre\nAna\n", "Sube un Excel"),
    ("c.xls", b"\xd0\xcf\x11\xe0", "xls"),
    ("c.xlsx", b"esto no es un zip", "no es un Excel"),
])
def test_archivos_que_no_se_pueden_leer_dan_un_mensaje_claro(nombre, datos, fragmento):
    with pytest.raises(imp.ErrorImportacion, match=fragmento):
        imp.leer_archivo(nombre, datos)


def test_limites_de_tamano_y_de_filas(monkeypatch):
    with pytest.raises(imp.ErrorImportacion, match="demasiado grande"):
        imp.leer_archivo("c.csv", b"a" * (imp.MAX_BYTES + 1))
    monkeypatch.setattr(imp, "MAX_FILAS", 3)
    with pytest.raises(imp.ErrorImportacion, match="Demasiados"):
        imp.leer_archivo("c.csv", _csv("Nombre\n" + "\n".join(f"C{i}" for i in range(4))))


def test_un_xlsx_que_ocuparia_demasiado_abierto_se_rechaza(monkeypatch):
    monkeypatch.setattr(imp, "MAX_DESCOMPRIMIDO", 100)
    with pytest.raises(imp.ErrorImportacion, match="demasiado grande una vez abierto"):
        imp.leer_archivo("c.xlsx", _xlsx([["Nombre"], ["Ana"]]))


def test_se_reconocen_las_columnas_por_su_nombre_con_o_sin_tildes():
    c = imp.reconocer_columnas(["Razón Social", "CIF/NIF", "Correo electrónico", "Móvil", "Observaciones", "Cosa rara", "Nombre"])
    assert c == {0: "nombre", 1: "nif", 2: "email", 3: "telefono", 4: "notas"}      # «Nombre» no repite el campo ya asignado


# --- Revisar y crear -----------------------------------------------------------------------------------------------------------------------------

def _imp(filas, cab=("Nombre", "NIF", "Email", "Teléfono", "Tipo", "Idioma", "Etiquetas")):
    return {"nombre": "t.csv", "cabeceras": list(cab), "filas": [list(f) + [""] * (len(cab) - len(f)) for f in filas]}


def test_la_vista_previa_distingue_nuevos_repetidos_y_errores():
    t = _t()
    nucleo.crear_cliente(t, "Ya Existe", nif="12345678Z")
    corr = imp.reconocer_columnas(["Nombre", "NIF", "Email"])
    previa = imp.vista_previa(t, _imp([
        ["Cliente Nuevo", "B12345678", "n@x.es"],
        ["Otro Nombre", "12345678-Z", ""],                 # mismo NIF que uno existente
        ["", "", ""],                                      # sin nombre
        ["Cliente Nuevo", "", ""],                         # repetido dentro del archivo (mismo nombre)
        ["Con Email Malo", "", "no-es-correo"],
    ]), corr)
    assert [f["estado"] for f in previa["filas"]] == ["nuevo", "duplicado", "error", "duplicado", "nuevo"]
    assert previa["cuentas"] == {"nuevo": 2, "duplicado": 2, "error": 1}
    assert previa["filas"][1]["motivo"].startswith("Ya existe") and previa["filas"][3]["motivo"] == "Repetido dentro del archivo."
    assert previa["filas"][4]["datos"]["email"] == "" and "Email no válido" in previa["filas"][4]["avisos"][0]
    assert [f["n"] for f in previa["filas"]] == [2, 3, 4, 5, 6], "se numeran como en Excel (la cabecera es la fila 1)"


def test_hace_falta_una_columna_de_nombre():
    with pytest.raises(imp.ErrorImportacion, match="nombre"):
        imp.vista_previa(_t(), _imp([["x"]]), {1: "nif"})


def test_importar_crea_los_clientes_con_sus_datos_y_la_etiqueta_comun():
    t = _t()
    corr = imp.reconocer_columnas(["Nombre", "NIF", "Email", "Teléfono", "Tipo", "Idioma", "Etiquetas"])
    r = imp.importar(t, db.usuario_local_id(), _imp([
        ["Carmen Soler", "12345678Z", "c@x.es", "600 123 456", "particular", "catalán", "vip; renta"],
        ["Mar S.L.", "B12345678", "", "", "", "", ""],
    ]), corr, etiqueta_comun="importación 2026")
    assert (r["creados"], r["duplicados"], r["errores"]) == (2, 0, [])
    filas, total = nucleo.listar_clientes(t, limite=10)
    assert total == 2
    c = next(f for f in filas if f["nombre"] == "Carmen Soler")
    assert (c["tipo"], c["telefono"], c["idioma"], c["origen"]) == ("persona", "600 123 456", "ca", "Importación")
    assert set(c["etiquetas"].split(",")) == {"vip", "renta", "importación 2026"}
    assert next(f for f in filas if f["nombre"] == "Mar S.L.")["tipo"] == "empresa", "sin tipo, se detecta por el CIF"


def test_importar_dos_veces_el_mismo_archivo_no_duplica():
    t = _t()
    corr = imp.reconocer_columnas(["Nombre", "NIF"])
    datos = _imp([["Ana Ruiz", "12345678Z"], ["Luis Gómez", "87654321X"]], cab=("Nombre", "NIF"))
    assert imp.importar(t, db.usuario_local_id(), datos, corr)["creados"] == 2
    r = imp.importar(t, db.usuario_local_id(), datos, corr)
    assert (r["creados"], r["duplicados"]) == (0, 2) and nucleo.listar_clientes(t, limite=10)[1] == 2


def test_sin_omitir_duplicados_se_crean_aunque_se_parezcan():
    t = _t()
    corr = imp.reconocer_columnas(["Nombre"])
    datos = _imp([["Ana Ruiz"]], cab=("Nombre",))
    imp.importar(t, db.usuario_local_id(), datos, corr)
    assert imp.importar(t, db.usuario_local_id(), datos, corr, omitir_duplicados=False)["creados"] == 1
    assert nucleo.listar_clientes(t, limite=10)[1] == 2


def test_una_fila_mala_no_detiene_las_demas_y_se_cuenta():
    t = _t()
    corr = imp.reconocer_columnas(["Nombre", "NIF"])
    r = imp.importar(t, db.usuario_local_id(), _imp([["A" * 250, ""], ["Buena", ""], ["", "123"]], cab=("Nombre", "NIF")), corr)
    assert r["creados"] == 1 and [(e["n"], e["motivo"]) for e in r["errores"]] == [(2, "El nombre es demasiado largo (máx. 200 caracteres)."), (4, "Falta el nombre.")]


def test_con_gestion_fiscal_crea_tambien_la_ficha_fiscal_y_los_modelos_del_perfil():
    t = _t()
    corr = imp.reconocer_columnas(["Nombre", "NIF"])
    r = imp.importar(t, db.usuario_local_id(), _imp([["Pepe Autónomo", "12345678Z"]], cab=("Nombre", "NIF")), corr, gestion_fiscal=True, perfil_tipo="autonomo", generacion_automatica=True)
    assert r["con_gestion_fiscal"] == 1
    assert len(db.listar_clientes_fiscales(t)) == 1


def test_queda_anotado_en_la_auditoria():
    from app import auditoria
    t = _t()
    imp.importar(t, db.usuario_local_id(), _imp([["Ana"]], cab=("Nombre",)), {0: "nombre"})
    assert [e["accion"] for e in auditoria.listar(t)] == ["clientes.importados"]


# --- Fichero temporal ------------------------------------------------------------------------------------------------------------------------

def test_la_importacion_preparada_es_privada_de_quien_la_subio_y_caduca():
    t = _t()
    ident = imp.preparar(t, 1, "c.csv", _csv("Nombre\nAna\n"))
    ruta = imp._carpeta() / f"{ident}.json"
    assert oct(ruta.stat().st_mode & 0o777) == "0o600"
    assert imp.cargar(t, 1, ident)["filas"] == [["Ana"]]
    assert imp.cargar(t, 2, ident) is None and imp.cargar(t + 1, 1, ident) is None, "ni otra persona ni otro despacho"
    assert imp.cargar(t, 1, "../../etc/passwd") is None and imp.cargar(t, 1, "x") is None
    os.utime(ruta, (time.time() - imp.VIDA_SEGUNDOS - 10,) * 2)
    assert imp.cargar(t, 1, ident) is None and not ruta.exists()


def test_preparar_limpia_las_caducadas():
    t = _t()
    viejo = imp.preparar(t, 1, "c.csv", _csv("Nombre\nAna\n"))
    os.utime(imp._carpeta() / f"{viejo}.json", (time.time() - imp.VIDA_SEGUNDOS - 10,) * 2)
    imp.preparar(t, 1, "c.csv", _csv("Nombre\nLuis\n"))
    assert not (imp._carpeta() / f"{viejo}.json").exists()


# --- Pantallas ------------------------------------------------------------------------------------------------------------------------------

def _con_despacho(cliente, email="imp@ejemplo.com", supervisor=True):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant(f"Despacho {email}")
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, supervisor)
    return uid, t


def _subir(cliente, contenido, nombre="c.csv"):
    r = cliente.post("/clientes/importar/", data={"archivo": (io.BytesIO(contenido), nombre)}, content_type="multipart/form-data")
    return r


def test_flujo_completo_subir_revisar_e_importar(cliente):
    uid, t = _con_despacho(cliente)
    assert 'href="/clientes/importar/"' in cliente.get("/clientes/").get_data(as_text=True)
    assert "Subir y revisar" in cliente.get("/clientes/importar/").get_data(as_text=True)
    r = _subir(cliente, _csv("Razón social;CIF;Correo\nMar S.L.;B12345678;m@x.es\nCarmen Soler;12345678Z;\nMar S.L.;;\n"))
    assert r.status_code == 302
    ruta = r.headers["Location"]
    ident = ruta.rstrip("/").rsplit("/", 1)[1]
    html = cliente.get(ruta).get_data(as_text=True)
    assert "Revisar la importación" in html and "Mar S.L." in html and "Repetido dentro del archivo." in html
    assert 'name="c0" aria-label' in html or 'name="c0"' in html
    r = cliente.post(f"/clientes/importar/{ident}", data={"c0": "nombre", "c1": "nif", "c2": "email", "omitir_duplicados": "1", "etiqueta_comun": "importación hoy"})
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Importación terminada" in html and "2 clientes creados" in html and "1 repetido omitido" in html
    assert nucleo.listar_clientes(t, limite=10)[1] == 2
    # de un solo uso: repetir el envío ya no hace nada
    r2 = cliente.post(f"/clientes/importar/{ident}", data={"c0": "nombre", "omitir_duplicados": "1"})
    assert r2.status_code == 302 and nucleo.listar_clientes(t, limite=10)[1] == 2


def test_la_correspondencia_elegida_a_mano_manda_sobre_la_reconocida(cliente):
    uid, t = _con_despacho(cliente, "corr@ejemplo.com")
    r = _subir(cliente, _csv("Cosa;Otra\nCarmen Soler;12345678Z\n"))
    ruta = r.headers["Location"]
    assert "Elige qué columna es el nombre" in cliente.get(ruta).get_data(as_text=True)
    html = cliente.get(ruta + "?c0=nombre&c1=nif").get_data(as_text=True)
    assert "Elige qué columna" not in html and "12345678Z" in html and "1 nuevo" in html


def test_errores_de_subida_se_muestran_sin_romper(cliente):
    _con_despacho(cliente, "err@ejemplo.com")
    r = _subir(cliente, b"nada", "datos.pdf")
    assert r.status_code == 302
    assert "Sube un Excel" in cliente.get(r.headers["Location"]).get_data(as_text=True)
    r = cliente.post("/clientes/importar/", data={}, content_type="multipart/form-data")
    assert "Elige un archivo" in cliente.get(r.headers["Location"]).get_data(as_text=True)


def test_una_importacion_ajena_o_inexistente_no_se_puede_ver_ni_ejecutar(cliente):
    _con_despacho(cliente, "dueno@ejemplo.com")
    ident = _subir(cliente, _csv("Nombre\nAna\n")).headers["Location"].rstrip("/").rsplit("/", 1)[1]
    assert cliente.get("/clientes/importar/inexistente-inexistente-1234").status_code == 302
    from app.main import app as flask_app
    with flask_app.test_client() as otro:
        uid2, t2 = _con_despacho(otro, "otro@ejemplo.com")
        assert otro.get(f"/clientes/importar/{ident}").status_code == 302
        assert otro.post(f"/clientes/importar/{ident}", data={"c0": "nombre"}).status_code == 302
        assert nucleo.listar_clientes(t2, limite=10)[1] == 0


def test_hay_que_iniciar_sesion(cliente):
    assert cliente.get("/clientes/importar/").status_code in (302, 401)
    assert cliente.post("/clientes/importar/", data={}).status_code in (302, 401, 400)


def test_el_texto_del_archivo_se_escapa_en_la_pantalla(cliente):
    _con_despacho(cliente, "xss@ejemplo.com")
    ruta = _subir(cliente, _csv("Nombre\n<script>alert(1)</script>\n")).headers["Location"]
    html = cliente.get(ruta).get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_solo_la_direccion_o_coordinacion_puede_importar(cliente):
    _con_despacho(cliente, "empleado@ejemplo.com", supervisor=False)
    assert 'href="/clientes/importar/"' not in cliente.get("/clientes/").get_data(as_text=True)
    assert cliente.get("/clientes/importar/").status_code == 403
    assert cliente.post("/clientes/importar/", data={"archivo": (io.BytesIO(b"Nombre\nAna\n"), "c.csv")}, content_type="multipart/form-data").status_code == 403
    assert cliente.get("/clientes/importar/plantilla.csv").status_code == 403


def test_la_plantilla_de_ejemplo_se_descarga_y_se_puede_importar(cliente):
    uid, t = _con_despacho(cliente, "plantilla@ejemplo.com")
    r = cliente.get("/clientes/importar/plantilla.csv")
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]
    cab, filas = imp.leer_archivo("plantilla-clientes.csv", r.data)
    assert imp.reconocer_columnas(cab) == {0: "nombre", 1: "nif", 2: "email", 3: "telefono", 4: "direccion", 5: "tipo", 6: "idioma", 7: "etiquetas", 8: "notas"} and len(filas) == 2


def test_los_duplicados_con_muchos_clientes_no_son_lentos():
    import time
    t = _t()
    conn = db.get_connection()
    conn.executemany("INSERT INTO clientes (tenant_id, tipo, nombre, nif, email, creado_en) VALUES (?, 'empresa', ?, ?, ?, ?)",
                     [(t, f"Cliente {i} S.L.", f"B{10000000 + i}", f"c{i}@x.es", db.now_iso()) for i in range(3000)])
    conn.commit(); conn.close()
    imp_ = _imp([[f"Otro {i}", f"B{10000000 + i}", ""] for i in range(3000)], cab=("Nombre", "NIF", "Email"))
    t0 = time.perf_counter()
    previa = imp.vista_previa(t, imp_, {0: "nombre", 1: "nif", 2: "email"})
    assert previa["cuentas"]["duplicado"] == 3000 and time.perf_counter() - t0 < 5
    assert previa["filas"][0]["motivo"] == "Ya existe: Cliente 0 S.L."


def test_los_clientes_en_la_papelera_no_cuentan_como_duplicados():
    t = _t()
    c = nucleo.crear_cliente(t, "Ana Ruiz", nif="12345678Z")
    conn = db.get_connection(); conn.execute("UPDATE clientes SET papelera_en = ? WHERE id = ?", (db.now_iso(), c)); conn.commit(); conn.close()
    previa = imp.vista_previa(t, _imp([["Ana Ruiz", "12345678Z"]], cab=("Nombre", "NIF")), {0: "nombre", 1: "nif"})
    assert previa["filas"][0]["estado"] == "nuevo"
