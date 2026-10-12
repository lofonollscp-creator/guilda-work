"""Almacén único de documentos (app/almacen_documentos.py): guardar, leer, listar, eliminar, permisos, cifrado enchufable y que nadie lo esquive."""
import hashlib
import re
from pathlib import Path

import pytest

from app import almacen_documentos as alm
from app import db, nucleo

RAIZ = Path(__file__).resolve().parent.parent


def _despacho(nombre="Despacho Docs", n=2):
    t = db.crear_tenant(nombre)
    us = []
    for i in range(n):
        u = db.crear_usuario_vinculado_a_kratos(f"{nombre.lower().replace(' ', '')}-{i}@ejemplo.com", f"kratos-{nombre}-{i}")
        db.asignar_tenant(u, t)
        us.append(u)
    return t, us


@pytest.fixture(autouse=True)
def sin_cifrador():
    alm.fijar_cifrador(None)
    yield
    alm.fijar_cifrador(None)


def test_guardar_leer_listar_y_eliminar_un_documento_de_cliente(usuario_id):
    t, (u1, u2) = _despacho()
    c = nucleo.crear_cliente(t, "Cliente")
    r, did = alm.guardar(u1, "../contrato final.pdf", "application/pdf", b"%PDF-1.4 contenido", cliente_id=c, categoria="Contratos")
    assert r == "ok" and did
    d = alm.leer(t, u2, did)
    assert d["contenido"] == b"%PDF-1.4 contenido" and d["nombre_archivo"] == "contrato final.pdf" and d["categoria"] == "Contratos" and not d["cifrado"]
    assert d["hash_sha256"] == hashlib.sha256(b"%PDF-1.4 contenido").hexdigest() and d["tamano_bytes"] == 18
    assert [x["id"] for x in alm.listar(t, u1, cliente_id=c)] == [did] and "contenido" not in alm.listar(t, u1, cliente_id=c)[0]
    assert alm.guardar(u1, "otra.pdf", "application/pdf", b"%PDF-1.4 contenido", cliente_id=c) == ("duplicado", did)
    assert not alm.eliminar(t, u2, did), "solo quien lo subió o un responsable"
    assert alm.eliminar(t, u1, did) and alm.leer(t, u1, did) is None and alm.listar(t, u1, cliente_id=c) == []


@pytest.mark.parametrize("kw,esperado", [({}, "destino"), ({"cliente_id": 999999}, "cliente")])
def test_destinos_no_validos(usuario_id, kw, esperado):
    t, (u1, _) = _despacho()
    assert alm.guardar(u1, "a.txt", "text/plain", b"x", **kw)[0] == esperado


def test_vacio_grande_y_limite(usuario_id, monkeypatch):
    t, (u1, _) = _despacho()
    c = nucleo.crear_cliente(t, "Cliente")
    assert alm.guardar(u1, "a.txt", "text/plain", b"", cliente_id=c)[0] == "vacio"
    monkeypatch.setattr(db, "MAX_DOCUMENTO_CLIENTE_BYTES", 10)
    assert alm.guardar(u1, "a.txt", "text/plain", b"x" * 11, cliente_id=c)[0] == "grande"
    monkeypatch.setattr(db, "MAX_DOCUMENTOS_POR_CLIENTE", 1)
    assert alm.guardar(u1, "a.txt", "text/plain", b"uno", cliente_id=c)[0] == "ok" and alm.guardar(u1, "b.txt", "text/plain", b"dos", cliente_id=c)[0] == "limite"


def test_los_documentos_de_un_expediente_siguen_sus_permisos(usuario_id):
    t, (u1, u2) = _despacho()
    c = nucleo.crear_cliente(t, "Cliente")
    x = nucleo.crear_expediente(t, u1, c, "Reservado", confidencial=True)
    r, did = alm.guardar(u1, "escrito.docx", "application/octet-stream", b"secreto", expediente_id=x)
    assert r == "ok" and alm.leer(t, u1, did)["cliente_id"] == c, "hereda el cliente del expediente"
    assert alm.leer(t, u2, did) is None and alm.listar(t, u2, expediente_id=x) == [] and alm.listar(t, u2, cliente_id=c) == []
    assert alm.guardar(u2, "colado.txt", "text/plain", b"x", expediente_id=x)[0] == "expediente"
    assert any(e["tipo"] == "documento" for e in nucleo.linea_de_tiempo(t, u1, x))
    nucleo.anadir_miembro(t, u1, x, u2)
    assert alm.leer(t, u2, did)["contenido"] == b"secreto"


def test_un_despacho_no_lee_los_documentos_de_otro(usuario_id):
    t1, (u1, _) = _despacho("Despacho Uno Docs")
    t2, (u2, _) = _despacho("Despacho Dos Docs")
    c1 = nucleo.crear_cliente(t1, "Cliente de uno")
    _, did = alm.guardar(u1, "a.txt", "text/plain", b"privado", cliente_id=c1)
    assert alm.leer(t2, u2, did) is None and alm.listar(t2, u2, cliente_id=c1) == []
    assert alm.guardar(u2, "x.txt", "text/plain", b"x", cliente_id=c1)[0] == "cliente"
    assert not alm.eliminar(t2, u2, did)


class _CifradorDePrueba:
    """No es cifrado de verdad: invierte los bytes y firma, para probar el cableado (el real llega el Día 7)."""
    def sellar(self, tenant_id, contenido):
        return b"SELLADO:" + contenido[::-1], f"sobre-{tenant_id}"

    def abrir(self, tenant_id, contenido, sobre):
        assert sobre == f"sobre-{tenant_id}" and contenido.startswith(b"SELLADO:")
        return contenido[len(b"SELLADO:"):][::-1]


def test_con_un_cifrador_el_contenido_se_guarda_sellado_y_se_lee_igual(usuario_id):
    t, (u1, u2) = _despacho()
    c = nucleo.crear_cliente(t, "Cliente")
    alm.fijar_cifrador(_CifradorDePrueba())
    _, did = alm.guardar(u1, "nota.txt", "text/plain", b"texto en claro", cliente_id=c)
    conn = db.get_connection()
    fila = conn.execute("SELECT * FROM documentos WHERE id = ?", (did,)).fetchone()
    conn.close()
    assert fila["cifrado"] == 1 and bytes(fila["contenido"]) != b"texto en claro" and b"texto en claro" not in bytes(fila["contenido"])
    assert fila["hash_sha256"] == hashlib.sha256(b"texto en claro").hexdigest(), "la huella es la del contenido sin cifrar"
    assert alm.leer(t, u2, did)["contenido"] == b"texto en claro" and alm.listar(t, u1, cliente_id=c)[0]["cifrado"] == 1
    assert alm.guardar(u1, "copia.txt", "text/plain", b"texto en claro", cliente_id=c) == ("duplicado", did), "detecta duplicados aunque se guarde cifrado"
    alm.fijar_cifrador(None)
    with pytest.raises(RuntimeError, match="clave"):
        alm.leer(t, u1, did)


def test_un_documento_alterado_se_detecta_al_leer(usuario_id):
    t, (u1, _) = _despacho()
    c = nucleo.crear_cliente(t, "Cliente")
    alm.fijar_cifrador(_CifradorDePrueba())
    _, did = alm.guardar(u1, "nota.txt", "text/plain", b"original", cliente_id=c)
    conn = db.get_connection()
    conn.execute("UPDATE documentos SET contenido = ? WHERE id = ?", (b"SELLADO:" + b"manipulado"[::-1], did)); conn.commit(); conn.close()
    with pytest.raises(RuntimeError, match="alterado"):
        alm.leer(t, u1, did)


def test_el_expediente_documental_de_la_ficha_fiscal_pasa_por_la_misma_puerta(usuario_id):
    t, (u1, u2) = _despacho()
    f = db.crear_cliente_fiscal(t, "Fiscal")
    r, did = alm.guardar_de_cliente_fiscal(u1, f, "modelo303.pdf", "application/pdf", b"%PDF-modelo", categoria="Modelos")
    assert r == "ok" and [d["id"] for d in alm.listar_de_cliente_fiscal(t, f)] == [did]
    assert bytes(alm.leer_de_cliente_fiscal(t, f, did)["contenido"]) == b"%PDF-modelo"
    assert not alm.eliminar_de_cliente_fiscal(u2, f, did) and alm.eliminar_de_cliente_fiscal(u1, f, did)


def test_borrar_el_despacho_borra_sus_documentos(usuario_id):
    t, (u1, _) = _despacho()
    c = nucleo.crear_cliente(t, "Cliente")
    alm.guardar(u1, "a.txt", "text/plain", b"x", cliente_id=c)
    db.borrar_tenant(t)
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM documentos").fetchone()[0] == 0
    conn.close()


# --- candado: nadie esquiva la puerta --------------------------------------------------------------------------------------------------------------
def _fuentes():
    for p in sorted((RAIZ / "app").rglob("*.py")):
        yield p.relative_to(RAIZ).as_posix(), p.read_text(encoding="utf-8")
    yield "mcp_tools.py", (RAIZ / "mcp_tools.py").read_text(encoding="utf-8")


def test_solo_el_almacen_escribe_el_contenido_de_los_documentos():
    permitidos = {"app/db.py", "app/db_fiscal.py", "app/almacen_documentos.py"}
    for ruta, texto in _fuentes():
        if re.search(r"INSERT\s+INTO\s+(documentos|cliente_documentos)\b|UPDATE\s+(documentos|cliente_documentos)\s+SET\s+contenido", texto, re.I):
            assert ruta in permitidos, f"{ruta} escribe documentos sin pasar por app/almacen_documentos.py"


def test_las_funciones_antiguas_de_documentos_solo_las_llama_el_almacen():
    funciones = ("archivar_documento_cliente", "obtener_documento_cliente", "listar_documentos_cliente", "eliminar_documento_cliente")
    for ruta, texto in _fuentes():
        if ruta in ("app/db.py", "app/db_fiscal.py", "app/almacen_documentos.py", "app/openapi_catalogo.py"):
            continue
        for f in funciones:
            assert not re.search(rf"\bdb\.{f}\(", texto), f"{ruta} llama a db.{f}: usa app/almacen_documentos.py"
