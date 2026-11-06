"""Panel del almacén de documentos del backoffice: totales por despacho y tabla, lo que sigue en la base, coste y comprobación de una muestra."""
import pytest

from app import almacen_objetos as ao, db, db_fiscal
from backoffice import almacen
from tests.test_almacen_objetos import PDF, _despacho  # noqa: F401
from tests.test_backoffice_app import bo, entrar, post  # noqa: F401 -- fixture


@pytest.fixture(autouse=True)
def _sin_almacen_al_terminar():
    yield
    ao.fijar_almacen(None, fijo=False)


def _doc(u, c, nombre, contenido):
    r, i = db_fiscal.archivar_documento_cliente(u, c, nombre, "application/pdf", contenido)
    assert r == "ok"
    return i


def test_sin_almacen_todo_cuenta_como_dentro(tmp_path):
    t, u, c = _despacho("Dentro")
    _doc(u, c, "a.pdf", PDF)
    assert almacen.estado_almacen()["configurado"] is False
    r = almacen.resumen()
    assert r["objetos"] == 0 and r["dentro"] == 1
    assert [d["nombre"] for d in r["por_despacho"]] == ["Dentro"] and r["por_despacho"][0]["dentro"] == 1


def test_con_almacen_cuenta_fuera_por_despacho_y_tabla(tmp_path):
    ao.fijar_almacen(ao.AlmacenFichero(tmp_path / "o"))
    ta, ua, ca = _despacho("Despacho Uno")
    tb, ub, cb = _despacho("Despacho Dos")
    _doc(ua, ca, "a.pdf", PDF)
    _doc(ua, ca, "b.pdf", PDF + b"otro")
    _doc(ub, cb, "c.pdf", PDF + b"tres")
    r = almacen.resumen()
    por = {d["nombre"]: d for d in r["por_despacho"]}
    assert por["Despacho Uno"]["fuera"] == 2 and por["Despacho Dos"]["fuera"] == 1
    assert next(t for t in r["por_tabla"] if t["tabla"] == "cliente_documentos")["fuera"] == 3
    assert r["objetos"] == 3 and r["dentro"] == 0 and r["sin_verificar"] == 3 and r["coste_mes_usd"] >= 0
    assert almacen.estado_almacen()["configurado"] is True


def test_verificar_muestra_anota_la_fecha_y_detecta_un_objeto_alterado(tmp_path):
    a = ao.AlmacenFichero(tmp_path / "o")
    ao.fijar_almacen(a)
    t, u, c = _despacho("Verifica")
    _doc(u, c, "a.pdf", PDF)
    _doc(u, c, "b.pdf", PDF + b"distinto")
    ok = almacen.verificar_muestra(10)
    assert ok == {"revisados": 2, "problemas": []} and almacen.resumen()["sin_verificar"] == 0
    conn = db.get_connection()
    clave = conn.execute("SELECT clave FROM objetos_almacenados ORDER BY id LIMIT 1").fetchone()["clave"]
    conn.close()
    a.poner(clave, b"manipulado")
    mal = almacen.verificar_muestra(10)
    assert mal["revisados"] == 2 and len(mal["problemas"]) == 1 and "Distinto" in mal["problemas"][0]


def test_verificar_sin_almacen_falla_con_mensaje():
    with pytest.raises(ao.ErrorAlmacenObjetos):
        almacen.verificar_muestra()


def test_la_pantalla_y_la_accion_en_el_backoffice(bo, tmp_path):
    entrar(bo)
    ao.fijar_almacen(ao.AlmacenFichero(tmp_path / "o"))
    t, u, c = _despacho("Pantalla")
    _doc(u, c, "a.pdf", PDF)
    html = bo.get("/almacen").get_data(as_text=True)
    assert "Almacén de documentos" in html and "Pantalla" in html and "Comprobar muestra" in html
    r = post(bo, "/almacen/verificar", n="5")
    assert r.status_code == 302
    assert "todos coinciden" in bo.get("/almacen").get_data(as_text=True)
    ao.fijar_almacen(None, fijo=False)
    assert "No hay almacén de objetos activo" in bo.get("/almacen").get_data(as_text=True)
