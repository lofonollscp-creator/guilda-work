"""Notas con título, formato seguro, fijadas, adjuntos y vínculos."""
import json

import pytest

from app import db, export, importador
from app.notas_formato import nota_a_html
from tests.conftest import iniciar_sesion_de_prueba


# --- Formato ---------------------------------------------------------------------

def test_formato_negrita_cursiva_listas_y_saltos():
    assert str(nota_a_html("Hola **mundo** y *tú*")) == "<p>Hola <strong>mundo</strong> y <em>tú</em></p>"
    assert str(nota_a_html("- uno\n- dos")) == "<ul><li>uno</li><li>dos</li></ul>"
    assert str(nota_a_html("1. a\n2) b")) == "<ol><li>a</li><li>b</li></ol>"
    assert str(nota_a_html("línea 1\nlínea 2")) == "<p>línea 1<br>línea 2</p>"
    assert str(nota_a_html("uno\n\ndos")) == "<p>uno</p><p>dos</p>"
    assert str(nota_a_html("2 * 3 * 4")) == "<p>2 * 3 * 4</p>"  # asteriscos sueltos: no es cursiva
    assert str(nota_a_html(None)) == "" and str(nota_a_html("")) == ""


def test_formato_no_deja_pasar_html_ni_javascript():
    html = str(nota_a_html('<script>alert(1)</script> <img src=x onerror=alert(1)> **ok**'))
    assert "<script" not in html and "<img" not in html and "&lt;script&gt;" in html
    assert "<strong>ok</strong>" in html

    malo = str(nota_a_html("[clic](javascript:alert(1)) y [otro](data:text/html,x)"))
    assert "<a " not in malo  # solo se enlazan direcciones http(s)

    inyeccion = str(nota_a_html('[x](https://a.com" onmouseover="alert(1))'))
    assert 'onmouseover="' not in inyeccion  # las comillas salen escapadas, nunca abren un atributo


def test_formato_enlaces_http_se_abren_de_forma_segura():
    html = str(nota_a_html("Mira [la AEAT](https://sede.agenciatributaria.gob.es/x?a=1&b=2) o https://guildawork.com."))
    assert 'href="https://sede.agenciatributaria.gob.es/x?a=1&amp;b=2"' in html
    assert 'href="https://guildawork.com"' in html and html.rstrip("</p>").endswith("</a>.")
    assert html.count('rel="noopener noreferrer"') == 2 and html.count('target="_blank"') == 2


# --- Título, fijar y vínculos ----------------------------------------------------------

def test_crear_y_editar_nota_con_titulo_y_fijada(usuario_id):
    nota = db.crear_nota(usuario_id, "Cuerpo", titulo="  Reunión   con Soler  ", fijada=True)
    fila = db.obtener_nota(usuario_id, nota)
    assert fila["titulo"] == "Reunión con Soler" and fila["fijada"] == 1

    db.editar_nota(usuario_id, nota, "Otro cuerpo")  # sin tocar título ni fijada
    fila = db.obtener_nota(usuario_id, nota)
    assert fila["texto"] == "Otro cuerpo" and fila["titulo"] == "Reunión con Soler" and fila["fijada"] == 1

    db.editar_nota(usuario_id, nota, "Otro cuerpo", titulo=None, fijada=False)
    fila = db.obtener_nota(usuario_id, nota)
    assert fila["titulo"] is None and fila["fijada"] == 0


def test_titulo_largo_se_recorta(usuario_id):
    nota = db.crear_nota(usuario_id, "x", titulo="t" * 400)
    assert len(db.obtener_nota(usuario_id, nota)["titulo"]) == db.NOTA_TITULO_MAX_CARACTERES


def test_alternar_fijada_y_listar_fijadas_por_proyecto(usuario_id):
    p1, p2 = db.crear_categoria(usuario_id, "A"), db.crear_categoria(usuario_id, "B")
    n1 = db.crear_nota(usuario_id, "en A", categoria_id=p1)
    n2 = db.crear_nota(usuario_id, "en B", categoria_id=p2)
    assert db.alternar_fijada_nota(usuario_id, n1) and db.alternar_fijada_nota(usuario_id, n2)

    assert [n["id"] for n in db.listar_notas_fijadas(usuario_id, p1)] == [n1]
    assert {n["id"] for n in db.listar_notas_fijadas(usuario_id)} == {n1, n2}
    db.alternar_fijada_nota(usuario_id, n1)
    assert db.listar_notas_fijadas(usuario_id, p1) == []
    assert db.alternar_fijada_nota(usuario_id, 99999) is False


def test_vinculos_solo_a_cosas_propias():
    tenant = db.crear_tenant("Despacho notas")
    ana = db.crear_usuario("ana-notas@despacho.com", "contrasena123")
    db.asignar_tenant(ana, tenant)
    otro_tenant = db.crear_tenant("Otro despacho notas")
    mio = db.crear_cliente_fiscal(tenant, "Panadería Soler")
    ajeno = db.crear_cliente_fiscal(otro_tenant, "Ajeno")
    otro = db.crear_usuario("otro-notas@fuera.com", "contrasena123")
    tarea_ajena = db.crear_tarea_outlook(otro, "De otro")
    tarea_mia = db.crear_tarea_outlook(ana, "Mía")

    n = db.crear_nota(ana, "x", cliente_fiscal_id=mio, tarea_outlook_id=tarea_mia)
    assert db.obtener_nota(ana, n)["cliente_fiscal_nombre"] == "Panadería Soler"
    assert db.obtener_nota(ana, n)["tarea_outlook_id"] == tarea_mia
    m = db.crear_nota(ana, "y", cliente_fiscal_id=ajeno, tarea_outlook_id=tarea_ajena, mensaje_correo_id=424242)
    fila = db.obtener_nota(ana, m)
    assert fila["cliente_fiscal_id"] is None and fila["tarea_outlook_id"] is None and fila["mensaje_correo_id"] is None


def test_el_historial_trae_titulo_y_fijada_y_busca_por_titulo(usuario_id):
    db.crear_nota(usuario_id, "algo sin relación", titulo="Modelo 303 de octubre", fijada=True)
    db.crear_nota(usuario_id, "otra cosa")

    todo = db.historial(usuario_id)
    assert {(f["titulo"], f["fijada"]) for f in todo} == {("Modelo 303 de octubre", 1), (None, 0)}
    encontrados = db.historial(usuario_id, texto="octubre")
    assert [f["titulo"] for f in encontrados] == ["Modelo 303 de octubre"]


# --- Adjuntos --------------------------------------------------------------------------

def test_adjuntos_ciclo_y_limites(usuario_id):
    nota = db.crear_nota(usuario_id, "con archivos")
    a1 = db.agregar_adjunto_nota(usuario_id, nota, "../../etc/factura.pdf", "application/pdf", b"%PDF-1.4 ...")
    lista = db.listar_adjuntos_nota(nota)
    assert [x["nombre"] for x in lista] == ["factura.pdf"] and "contenido" not in lista[0].keys()
    assert db.obtener_adjunto_nota(usuario_id, a1)["contenido"] == b"%PDF-1.4 ..."
    assert db.contar_adjuntos_notas([nota]) == {nota: 1}

    with pytest.raises(ValueError, match="no permitido"):
        db.agregar_adjunto_nota(usuario_id, nota, "x.svg", "image/svg+xml", b"<svg onload=alert(1)/>")
    with pytest.raises(ValueError, match="pesa demasiado"):
        db.agregar_adjunto_nota(usuario_id, nota, "x.png", "image/png", b"0" * (db.NOTAS_ADJUNTOS_TAMANO_MAXIMO + 1))
    with pytest.raises(ValueError, match="vacío"):
        db.agregar_adjunto_nota(usuario_id, nota, "x.txt", "text/plain", b"")
    for n in range(db.NOTAS_ADJUNTOS_MAXIMO_POR_NOTA - 1):
        db.agregar_adjunto_nota(usuario_id, nota, f"{n}.txt", "text/plain", b"x")
    with pytest.raises(ValueError, match="máximo"):
        db.agregar_adjunto_nota(usuario_id, nota, "otro.txt", "text/plain", b"x")

    assert db.eliminar_adjunto_nota(usuario_id, a1) is True
    assert db.obtener_adjunto_nota(usuario_id, a1) is None


def test_adjuntos_aislados_por_usuario_y_se_borran_con_la_nota(usuario_id):
    otro = db.crear_usuario("otro-adj@ejemplo.com", "contrasena123")
    nota = db.crear_nota(otro, "privada")
    adjunto = db.agregar_adjunto_nota(otro, nota, "a.txt", "text/plain", b"secreto")

    assert db.obtener_adjunto_nota(usuario_id, adjunto) is None
    assert db.eliminar_adjunto_nota(usuario_id, adjunto) is False
    with pytest.raises(ValueError, match="no existe"):
        db.agregar_adjunto_nota(usuario_id, nota, "intruso.txt", "text/plain", b"x")

    db.eliminar_nota(otro, nota)
    db.eliminar_nota_definitivamente(otro, nota)
    assert db.obtener_adjunto_nota(otro, adjunto) is None


# --- Exportar / importar -----------------------------------------------------------------

def test_exportar_conserva_el_formato_y_anade_el_titulo_en_json(usuario_id):
    db.crear_nota(usuario_id, "cuerpo de la nota", titulo="Con título")
    db.crear_nota(usuario_id, "sin título")

    datos = json.loads(export.a_json(usuario_id))
    assert {r["titulo"] for r in datos["registros"]} == {"Con título", None}
    cabecera = export.a_csv(usuario_id).splitlines()[0]
    assert cabecera == "origen,id,texto_o_nombre,tipo,estado,categoria,timestamp_inicio,timestamp_fin,duracion_segundos"
    assert "**Con título**: cuerpo de la nota" in export.a_markdown(usuario_id)


def test_importar_acepta_formato_antiguo_sin_titulo_y_el_nuevo_con_titulo(usuario_id):
    contenido = json.dumps({"registros": [
        {"origen": "nota", "texto_o_nombre": "antigua", "timestamp_inicio": "2026-01-01T10:00:00"},
        {"origen": "nota", "texto_o_nombre": "nueva", "titulo": "Importada", "timestamp_inicio": "2026-01-02T10:00:00"},
    ]})
    resumen = importador.importar_json(usuario_id, contenido)
    assert resumen["notas"] == 2
    titulos = {f["texto"]: f["titulo"] for f in db.historial(usuario_id)}
    assert titulos == {"antigua": None, "nueva": "Importada"}


# --- Rutas -----------------------------------------------------------------------------------

def _entrar(cliente, email):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    tenant = db.crear_tenant(f"Despacho {email}")
    db.asignar_tenant(uid, tenant)
    return uid, tenant


def test_editor_guarda_titulo_fijada_y_cliente_y_el_registro_las_pinta(cliente):
    uid, tenant = _entrar(cliente, "notas-ruta1@ejemplo.com")
    proyecto = db.crear_categoria(uid, "Lueira")
    cf = db.crear_cliente_fiscal(tenant, "Panadería Soler")
    nota = db.crear_nota(uid, "provisional", categoria_id=proyecto)

    r = cliente.post(f"/nota/{nota}/editar", data={
        "titulo": "Acta de la reunión", "texto": "- punto uno\n- **punto dos**", "fijada": "1",
        "cliente_fiscal_id": cf, "volver_a": f"/menu/{proyecto}",
    })
    assert r.status_code == 302
    fila = db.obtener_nota(uid, nota)
    assert (fila["titulo"], fila["fijada"], fila["cliente_fiscal_id"]) == ("Acta de la reunión", 1, cf)

    pagina = cliente.get(f"/menu/{proyecto}").get_data(as_text=True)
    assert "Notas fijadas" in pagina and "Acta de la reunión" in pagina
    assert "<li>punto uno</li>" in pagina and "<strong>punto dos</strong>" in pagina
    editor = cliente.get(f"/nota/{nota}/editar").get_data(as_text=True)
    assert 'value="Acta de la reunión"' in editor and "Panadería Soler" in editor and "checked" in editor


def test_una_nota_solo_con_titulo_es_valida_y_una_vacia_no(cliente):
    uid, _ = _entrar(cliente, "notas-ruta2@ejemplo.com")
    cliente.post("/notas", data={"texto": "", "titulo": "Solo título"})
    cliente.post("/notas", data={"texto": "  ", "titulo": ""})
    assert [(n["titulo"], n["texto"]) for n in db.historial(uid)] == [("Solo título", "")]


def test_fijar_desde_la_ruta_y_404_si_es_ajena(cliente):
    uid, _ = _entrar(cliente, "notas-ruta3@ejemplo.com")
    nota = db.crear_nota(uid, "x")
    ajena = db.crear_nota(db.crear_usuario("dueno3@ejemplo.com", "contrasena123"), "ajena")

    assert cliente.post(f"/nota/{nota}/fijar").status_code == 302
    assert db.obtener_nota(uid, nota)["fijada"] == 1
    assert cliente.post(f"/nota/{ajena}/fijar").status_code == 404


def test_subir_descargar_y_borrar_adjuntos_por_ruta(cliente):
    import io
    uid, _ = _entrar(cliente, "notas-ruta4@ejemplo.com")
    nota = db.crear_nota(uid, "con adjuntos")

    r = cliente.post(f"/nota/{nota}/adjuntos", content_type="multipart/form-data", data={
        "adjunto": [(io.BytesIO(b"hola"), "uno.txt", "text/plain"), (io.BytesIO(b"<svg/>"), "malo.svg", "image/svg+xml")],
        "volver_a": "/",
    })
    assert r.status_code == 302 and "malo.svg" in r.headers["Location"]  # el error del segundo se avisa
    adjuntos = db.listar_adjuntos_nota(nota)
    assert [a["nombre"] for a in adjuntos] == ["uno.txt"]  # el válido ya quedó

    bajada = cliente.get(f"/nota/adjunto/{adjuntos[0]['id']}")
    assert bajada.status_code == 200 and bajada.data == b"hola"
    assert "attachment" in bajada.headers["Content-Disposition"] and bajada.headers["X-Content-Type-Options"] == "nosniff"
    pagina = cliente.get(f"/nota/{nota}/editar").get_data(as_text=True)
    assert "uno.txt" in pagina

    assert cliente.post(f"/nota/adjunto/{adjuntos[0]['id']}/eliminar").status_code == 302
    assert db.listar_adjuntos_nota(nota) == []


def test_un_usuario_no_descarga_ni_borra_adjuntos_de_otro(cliente):
    uid, _ = _entrar(cliente, "notas-ruta5@ejemplo.com")
    otro = db.crear_usuario("dueno5@ejemplo.com", "contrasena123")
    nota = db.crear_nota(otro, "privada")
    adjunto = db.agregar_adjunto_nota(otro, nota, "secreto.txt", "text/plain", b"no mirar")

    assert cliente.get(f"/nota/adjunto/{adjunto}").status_code == 404
    assert cliente.post(f"/nota/adjunto/{adjunto}/eliminar").status_code == 404
    assert cliente.post(f"/nota/{nota}/adjuntos", data={"adjunto": (__import__("io").BytesIO(b"x"), "i.txt")}, content_type="multipart/form-data").status_code == 404
    assert len(db.listar_adjuntos_nota(nota)) == 1
