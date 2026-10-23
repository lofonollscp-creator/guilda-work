"""Cimientos del control fiscal: identificación normalizada y sin duplicados, unicidad de obligaciones, versión y migración sin pérdidas."""
import sqlite3

import pytest
from app.bd.errores import ErrorIntegridad, ErrorOperacional

from app import db, fiscal_base, fiscal_identidad as fi


def test_validacion_de_nif_nie_y_cif():
    for ok in ("12345678Z", "x1234567l", "X1234567L", "Y1234567X", "B12345674", "B16406233", "J21938519", "Q2826000H", "b-16.406 233"):
        assert fi.nif_valido_es(ok), ok
    for mal in ("12345678A", "B123", "", None, "X1234567A", "B12345675", "Q2826000A", "hola"):
        assert not fi.nif_valido_es(mal), mal
    assert fi.normalizar("b-16.406 233") == "B16406233"
    assert fi.clave_unica("B123", "ES") is None and fi.clave_unica("12345678Z", "ES") == "12345678Z"
    assert fi.clave_unica("FR 12-345.678", "FR") == "FR12345678" and fi.clave_unica("12", "FR") is None and fi.clave_unica("ABCDEFG", "FR") is None
    assert fi.formato_dudoso("B123") and not fi.formato_dudoso("B12345674") and not fi.formato_dudoso("")


def test_no_se_duplica_un_cliente_con_la_misma_identificacion_valida(usuario_id):
    t = db.crear_tenant("Despacho Identidad")
    a = db.crear_cliente_fiscal(t, "Empresa Uno SL", nif="B12345674")
    with pytest.raises(fi.ClienteDuplicado, match=r"B12345674.*Empresa Uno SL.*n\.º %d" % a) as e:
        db.crear_cliente_fiscal(t, "Otra con el mismo NIF", nif="b-12.345 674")
    assert e.value.existente_id == a
    assert len(db.listar_clientes_fiscales(t)) == 1, "no se ha creado la segunda"
    otro_despacho = db.crear_tenant("Otro despacho")
    assert db.crear_cliente_fiscal(otro_despacho, "Mismo NIF en otra asesoría", nif="B12345674"), "la unicidad es por asesoría"
    db.crear_cliente_fiscal(t, "Relleno 1", nif="B123"); db.crear_cliente_fiscal(t, "Relleno 2", nif="B123")
    db.crear_cliente_fiscal(t, "Sin nif 1"); db.crear_cliente_fiscal(t, "Sin nif 2")


def test_editar_el_nif_a_uno_repetido_falla_y_cambiar_de_pais_lo_permite(usuario_id):
    t = db.crear_tenant("Despacho Identidad 2")
    a = db.crear_cliente_fiscal(t, "A SL", nif="B12345674"); b = db.crear_cliente_fiscal(t, "B SL", nif="J21938519")
    with pytest.raises(fi.ClienteDuplicado):
        db.editar_cliente_fiscal(t, b, nif="B12345674")
    assert db.obtener_cliente_fiscal(t, b)["nif"] == "J21938519", "el cambio no se aplicó"
    db.editar_cliente_fiscal(t, b, nif="B12345674", pais="FR")
    assert db.obtener_cliente_fiscal(t, b)["nif_normalizado"] == "B12345674" and db.obtener_cliente_fiscal(t, a)["nif_normalizado"] == "B12345674", "mismo texto, otro país"
    db.editar_cliente_fiscal(t, a, nif="")
    assert db.obtener_cliente_fiscal(t, a)["nif_normalizado"] is None


def test_restaurar_de_la_papelera_no_deja_un_duplicado(usuario_id):
    t = db.crear_tenant("Despacho Identidad 3")
    a = db.crear_cliente_fiscal(t, "A SL", nif="B12345674")
    db.eliminar_cliente_fiscal(t, a)
    b = db.crear_cliente_fiscal(t, "Nueva con el mismo NIF", nif="B12345674")
    with pytest.raises(fi.ClienteDuplicado):
        db.restaurar_cliente_fiscal(t, a)
    assert db.obtener_cliente_fiscal(t, a) is None and db.obtener_cliente_fiscal(t, b)


def test_una_excepcion_documentada_permite_el_duplicado(usuario_id):
    t = db.crear_tenant("Despacho Identidad 4")
    a = db.crear_cliente_fiscal(t, "A SL", nif="B12345674"); b = db.crear_cliente_fiscal(t, "A SL (histórico)", nif="B12345674") if False else None
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO clientes_fiscales (tenant_id, nombre, nif, nif_normalizado, nif_duplicado_autorizado, creado_en) VALUES (?, 'Perfil histórico', 'B12345674', 'B12345674', 'Ficha histórica de 2019', '2026-01-01')", (t,))
        conn.commit()
    finally:
        conn.close()
    assert len(db.listar_clientes_fiscales(t)) == 2


def test_un_vencimiento_por_cliente_modelo_y_periodo_salvo_rectificaciones(usuario_id):
    t = db.crear_tenant("Despacho Unicidad")
    c = db.crear_cliente_fiscal(t, "Cliente SL")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20")
    with pytest.raises(ErrorIntegridad):
        db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20")
    r = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-11-30", rectifica_a=v)
    assert db.obtener_vencimiento_fiscal(t, r)["rectifica_a"] == v
    db.crear_vencimiento_fiscal(t, c, "303", "2026-T4", "2027-01-20"); db.crear_vencimiento_fiscal(t, c, "111", "2026-T3", "2026-10-20")
    db.eliminar_vencimiento_fiscal(t, v)
    assert db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20"), "el de la papelera no cuenta"
    with pytest.raises(ErrorIntegridad):
        db.restaurar_vencimiento_fiscal(t, v)


def test_la_version_sube_con_cada_cambio(usuario_id):
    t = db.crear_tenant("Despacho Versión")
    c = db.crear_cliente_fiscal(t, "Cliente SL", nif="B12345674")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20")
    assert db.obtener_cliente_fiscal(t, c)["version"] == 1 and db.obtener_vencimiento_fiscal(t, v)["version"] == 1
    db.editar_cliente_fiscal(t, c, notas="x"); db.editar_vencimiento_fiscal(t, v, notas="y")
    assert db.obtener_cliente_fiscal(t, c)["version"] == 2 and db.obtener_vencimiento_fiscal(t, v)["version"] == 2
    db.marcar_presentado_vencimiento_fiscal(t, v)
    x = db.obtener_vencimiento_fiscal(t, v)
    assert x["version"] == 3 and x["estado"] == "presentado" and x["fase"] == "presentada"


def test_marcar_presentado_tarde_se_anota_y_reabrir_vuelve_al_principio(usuario_id):
    t = db.crear_tenant("Despacho Tarde")
    c = db.crear_cliente_fiscal(t, "Cliente SL")
    atrasado = db.crear_vencimiento_fiscal(t, c, "303", "2020-T1", "2020-04-20")
    a_tiempo = db.crear_vencimiento_fiscal(t, c, "303", "2099-T1", "2099-04-20")
    db.marcar_presentado_vencimiento_fiscal(t, atrasado); db.marcar_presentado_vencimiento_fiscal(t, a_tiempo)
    assert db.obtener_vencimiento_fiscal(t, atrasado)["presentada_tarde"] == 1 and db.obtener_vencimiento_fiscal(t, a_tiempo)["presentada_tarde"] == 0
    db.editar_vencimiento_fiscal(t, a_tiempo, estado="pendiente")
    assert db.obtener_vencimiento_fiscal(t, a_tiempo)["fase"] == "pendiente"
    db.editar_vencimiento_fiscal(t, a_tiempo, estado="presentado")
    assert db.obtener_vencimiento_fiscal(t, a_tiempo)["fase"] == "presentada"


def test_la_migracion_no_pierde_nada_aunque_haya_duplicados_antiguos(usuario_id):
    """Simula una base anterior a la regla: dos clientes con el mismo NIF y dos vencimientos repetidos. La migración los conserva y los marca."""
    t = db.crear_tenant("Despacho Migración")
    conn = db.get_connection()
    try:
        conn.execute("DROP INDEX idx_clientes_fiscales_nif_unico"); conn.execute("DROP INDEX idx_vencimientos_unico")
        for nombre in ("Vieja uno", "Vieja dos"):
            conn.execute("INSERT INTO clientes_fiscales (tenant_id, nombre, nif, creado_en) VALUES (?, ?, 'B12345674', '2020-01-01')", (t, nombre))
        cid = conn.execute("SELECT id FROM clientes_fiscales WHERE nombre = 'Vieja uno'").fetchone()["id"]
        for _ in range(2):
            conn.execute("INSERT INTO vencimientos_fiscales (tenant_id, cliente_fiscal_id, modelo, periodo, fecha_limite, creado_en) VALUES (?, ?, '303', '2020-T1', '2020-04-20', '2020-01-01')", (t, cid))
        conn.execute("UPDATE vencimientos_fiscales SET estado = 'presentado' WHERE id = (SELECT MIN(id) FROM vencimientos_fiscales WHERE cliente_fiscal_id = ?)", (cid,))
        conn.commit()
        fiscal_base.crear_esquema(conn); conn.commit()
        fiscal_base.crear_esquema(conn); conn.commit()           # idempotente
        cl = conn.execute("SELECT nombre, nif_normalizado, nif_duplicado_autorizado FROM clientes_fiscales WHERE tenant_id = ? ORDER BY id", (t,)).fetchall()
        assert [(c["nombre"], c["nif_normalizado"], c["nif_duplicado_autorizado"] is not None) for c in cl] == [("Vieja uno", "B12345674", False), ("Vieja dos", "B12345674", True)]
        v = conn.execute("SELECT rectifica_a, fase FROM vencimientos_fiscales WHERE cliente_fiscal_id = ? ORDER BY id", (cid,)).fetchall()
        assert v[0]["rectifica_a"] is None and v[1]["rectifica_a"] is not None and v[0]["fase"] == "presentada", "el segundo queda como relacionado con el primero; el presentado, en su fase"
    finally:
        conn.close()
