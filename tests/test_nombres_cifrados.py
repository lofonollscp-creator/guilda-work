"""Nombres de archivo de los documentos según el nivel de reserva: en claro en Laxo, sellados en Medio y Estricto; sin colarse en eventos ni registros; reversibles al cambiar de nivel."""
import pytest

from app import almacen_documentos as alm
from app import cifrado_despacho as cd
from app import db, nucleo

FRASE = "una frase de paso larga y segura"
NOMBRE = "nomina-secreta-QW3.pdf"


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setattr(cd, "ARGON2", {"time_cost": 1, "memory_cost": 8, "parallelism": 1})
    alm.fijar_cifrador(None)


def _despacho(nivel):
    t = db.crear_tenant(f"Despacho nombres {nivel}")
    u = db.crear_usuario_vinculado_a_kratos(f"nombres-{nivel}@ejemplo.com", f"k-nombres-{nivel}")
    db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    c = nucleo.crear_cliente(t, "Cliente")
    x = nucleo.crear_expediente(t, u, c, "Asunto")
    f = db.crear_cliente_fiscal(t, "Fiscal")
    antes = alm.guardar(u, "antes-" + NOMBRE, "application/pdf", b"%PDF antes", cliente_id=c)[1]
    antes_fiscal = alm.guardar_de_cliente_fiscal(u, f, "fiscal-antes-" + NOMBRE, "application/pdf", b"%PDF fiscal antes")[1]
    cd.activar(t, u, FRASE, nivel)
    return t, u, c, x, f, antes, antes_fiscal


def _cruda(tabla, i):
    conn = db.get_connection()
    try:
        return dict(conn.execute(f"SELECT nombre_archivo, nombre_cifrado, cifrado FROM {tabla} WHERE id = ?", (i,)).fetchone())
    finally:
        conn.close()


@pytest.mark.parametrize("nivel,sellado", [("laxo", False), ("medio", True), ("estricto", True)])
def test_el_nombre_va_sellado_solo_en_medio_y_estricto(usuario_id, nivel, sellado):
    t, u, c, x, f, antes, antes_fiscal = _despacho(nivel)
    nuevo = alm.guardar(u, NOMBRE, "application/pdf", b"%PDF nuevo", expediente_id=x)[1]
    nuevo_fiscal = alm.guardar_de_cliente_fiscal(u, f, NOMBRE, "application/pdf", b"%PDF fiscal nuevo")[1]
    for tabla, ids in (("documentos", (antes, nuevo)), ("cliente_documentos", (antes_fiscal, nuevo_fiscal))):
        for i in ids:
            fila = _cruda(tabla, i)
            assert fila["cifrado"] == 1 and bool(fila["nombre_cifrado"]) == sellado and (fila["nombre_archivo"] == "") == sellado, f"{tabla} #{i}: {fila}"
    # con clave se ve el nombre real, siempre
    assert {d["nombre_archivo"] for d in alm.listar(t, u, expediente_id=x)} == {NOMBRE}
    assert alm.leer(t, u, nuevo)["nombre_archivo"] == NOMBRE
    assert alm.leer_de_cliente_fiscal(t, f, nuevo_fiscal, u)["nombre_archivo"] == NOMBRE
    assert {d["nombre_archivo"] for d in alm.listar(t, u, cliente_id=c)} == {"antes-" + NOMBRE, NOMBRE}, "los que ya estaban también (se sellan al activar)"
    cd.bloquear(t)
    esperado = cd.NOMBRE_PROTEGIDO if sellado else NOMBRE
    assert {d["nombre_archivo"] for d in alm.listar(t, u, expediente_id=x)} == {esperado}
    assert {d["nombre_archivo"] for d in alm.listar_de_cliente_fiscal(t, f) if d["id"] == nuevo_fiscal} == {esperado}


@pytest.mark.parametrize("nivel", ["medio", "estricto"])
def test_el_nombre_no_se_cuela_en_eventos_registros_ni_en_el_fichero(usuario_id, nivel):
    t, u, c, x, f, antes, antes_fiscal = _despacho(nivel)
    d = alm.guardar(u, NOMBRE, "application/pdf", b"%PDF nuevo", expediente_id=x)[1]
    alm.eliminar(t, u, d)
    db.registrar_acceso_cliente(t, f, u, "documento_descargado", NOMBRE)
    db.registrar_acceso_cliente(t, f, u, "documento_eliminado", NOMBRE)
    linea = " ".join(e["texto"] for e in nucleo.linea_de_tiempo(t, u, x))
    assert "Documento añadido" in linea and "Documento eliminado" in linea and "QW3" not in linea
    conn = db.get_connection()
    detalles = [r[0] for r in conn.execute("SELECT detalle FROM cliente_accesos WHERE accion LIKE 'documento%'")]
    conn.close()
    assert detalles and all("QW3" not in (x or "") for x in detalles)
    c2 = db.get_connection(); c2.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall(); c2.close()
    assert b"QW3" not in db.DB_PATH.read_bytes() and b"qw3" not in db.DB_PATH.read_bytes()


def test_en_laxo_el_nombre_si_se_ve_en_los_eventos(usuario_id):
    t, u, c, x, f, antes, antes_fiscal = _despacho("laxo")
    alm.guardar(u, NOMBRE, "application/pdf", b"%PDF nuevo", expediente_id=x)
    assert NOMBRE in " ".join(e["texto"] for e in nucleo.linea_de_tiempo(t, u, x))


def test_cambiar_de_nivel_sella_y_devuelve_los_nombres(usuario_id):
    t, u, c, x, f, antes, antes_fiscal = _despacho("laxo")
    assert _cruda("documentos", antes)["nombre_archivo"] == "antes-" + NOMBRE
    cd.bloquear(t)
    assert cd.cambiar_nivel(t, u, "estricto")["documentos"] == 2                      # subir: sin clave
    assert _cruda("documentos", antes)["nombre_archivo"] == "" and _cruda("cliente_documentos", antes_fiscal)["nombre_cifrado"]
    with pytest.raises(cd.DespachoBloqueado):
        cd.cambiar_nivel(t, u, "laxo")                                                # bajar: hace falta la clave
    assert _cruda("documentos", antes)["nombre_archivo"] == "", "el intento fallido no cambia nada"
    assert cd.estado(t)["nivel"] == "estricto"
    cd.desbloquear(t, u, FRASE)
    assert cd.cambiar_nivel(t, u, "laxo")["documentos"] == 2
    assert _cruda("documentos", antes) == {"nombre_archivo": "antes-" + NOMBRE, "nombre_cifrado": None, "cifrado": 1}
    assert alm.leer_de_cliente_fiscal(t, f, antes_fiscal, u)["nombre_archivo"] == "fiscal-antes-" + NOMBRE


def test_rotar_la_clave_recifra_tambien_los_nombres(usuario_id):
    t, u, c, x, f, antes, antes_fiscal = _despacho("medio")
    previo = _cruda("documentos", antes)["nombre_cifrado"]
    cd.rotar_clave(t, u, FRASE)
    assert _cruda("documentos", antes)["nombre_cifrado"] != previo
    assert alm.leer(t, u, antes)["nombre_archivo"] == "antes-" + NOMBRE and alm.leer_de_cliente_fiscal(t, f, antes_fiscal, u)["nombre_archivo"] == "fiscal-antes-" + NOMBRE


def test_las_paginas_publicas_enseñan_el_nombre_solo_si_hay_clave(usuario_id):
    t, u, c, x, f, antes, _ = _despacho("estricto")
    d = alm.guardar(u, NOMBRE, "application/pdf", b"%PDF c", expediente_id=x)[1]
    conn = db.get_connection(); conn.execute("UPDATE documentos SET compartido_cliente = 1 WHERE id = ?", (d,)); conn.commit(); conn.close()
    assert [x_["nombre_archivo"] for x_ in alm.compartidos_de_expediente(t, x)] == [NOMBRE]
    cd.bloquear(t)
    assert [x_["nombre_archivo"] for x_ in alm.compartidos_de_expediente(t, x)] == [cd.NOMBRE_PROTEGIDO]


def test_el_registro_de_accesos_muestra_el_nombre_con_clave_y_sin_ella_el_numero(usuario_id):
    t, u, c, x, f, antes, _ = _despacho("medio")
    alm.leer(t, u, antes)
    assert cd.accesos_recientes(t)[0]["nombre_archivo"] == "antes-" + NOMBRE
    cd.bloquear(t)
    assert cd.accesos_recientes(t)[0]["nombre_archivo"] == ""


def test_el_asunto_del_correo_de_origen_no_se_copia_al_archivar_en_medio_y_estricto(usuario_id):
    t, u, c, x, f, antes, _ = _despacho("medio")
    r, i = alm.guardar_de_cliente_fiscal(u, f, "adj.pdf", "application/pdf", b"%PDF correo", origen="correo", asunto_origen="Asunto confidencial del correo")
    conn = db.get_connection()
    assert conn.execute("SELECT asunto_origen FROM cliente_documentos WHERE id = ?", (i,)).fetchone()[0] is None
    conn.close()
