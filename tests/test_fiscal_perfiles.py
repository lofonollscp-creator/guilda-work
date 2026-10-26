"""Guilda Fiscal · F1 (app/fiscal_perfiles.py): perfiles fiscales versionados y relaciones gestora↔titular. Corre en SQLite y, con GUILDA_TEST_MOTOR=postgres, en PostgreSQL."""
import pytest

from app import db, fiscal_perfiles as fp, verticales
from app.db_fiscal import crear_cliente_fiscal

BASE = {"forma_juridica": "sociedad"}


def _despacho(nombre="Despacho fiscal"):
    t = db.crear_tenant(nombre)
    u = db.crear_usuario_vinculado_a_kratos(f"{nombre.replace(' ', '').lower()}@ejemplo.com", f"k-{nombre.replace(' ', '').lower()}"); db.asignar_tenant(u, t)
    return t, u


def _titular(t, nombre="Titular SL", nif="B12345678"):
    return crear_cliente_fiscal(t, nombre, nif=nif)


def test_los_verticales_fiscales_estan_dados_de_alta():
    assert verticales.VERTICALES["fiscal"].disponible is True               # con pantallas (F4); se activa por despacho
    assert verticales.VERTICALES["fiscal"].entradas_menu[0].endpoint == "guilda_fiscal.cartera"
    assert verticales.VERTICALES["alquileres"].disponible is False


def test_alta_y_perfil_vigente_en_los_limites():
    t, u = _despacho(); c = _titular(t)
    p1 = fp.guardar_perfil(t, u, c, BASE, vigente_desde="2026-01-01", vigente_hasta="2026-06-30")
    p2 = fp.guardar_perfil(t, u, c, {**BASE, "regimen_iva": "simplificado"}, vigente_desde="2026-07-01")
    assert fp.perfil_en(t, c, "2025-12-31") is None
    assert fp.perfil_en(t, c, "2026-01-01")["id"] == p1["id"]
    assert fp.perfil_en(t, c, "2026-06-30")["id"] == p1["id"]
    assert fp.perfil_en(t, c, "2026-07-01")["id"] == p2["id"]
    assert fp.perfil_en(t, c, "2030-01-01")["regimen_iva"] == "simplificado"


def test_un_alta_posterior_cierra_el_perfil_abierto_el_dia_anterior():
    t, u = _despacho(); c = _titular(t)
    a = fp.guardar_perfil(t, u, c, BASE, vigente_desde="2026-01-01")
    fp.guardar_perfil(t, u, c, {**BASE, "periodicidad": "mensual"}, vigente_desde="2026-04-01")
    filas = fp.perfiles_de(t, c)
    assert [f["vigente_desde"] for f in filas] == ["2026-01-01", "2026-04-01"]
    assert filas[0]["id"] == a["id"] and filas[0]["vigente_hasta"] == "2026-03-31" and filas[0]["version"] == 2


def test_no_se_admiten_solapes_ni_fechas_invertidas():
    t, u = _despacho(); c = _titular(t)
    fp.guardar_perfil(t, u, c, BASE, vigente_desde="2026-01-01", vigente_hasta="2026-12-31")
    with pytest.raises(fp.ErrorFiscal) as e:
        fp.guardar_perfil(t, u, c, BASE, vigente_desde="2026-06-01", vigente_hasta="2026-08-31")
    assert e.value.codigo == "solapa"
    with pytest.raises(fp.ErrorFiscal):
        fp.guardar_perfil(t, u, c, BASE, vigente_desde="2027-05-01", vigente_hasta="2027-04-01")
    assert len(fp.perfiles_de(t, c)) == 1


def test_validaciones_de_campos():
    t, u = _despacho(); c = _titular(t)
    with pytest.raises(fp.ErrorFiscal):
        fp.guardar_perfil(t, u, c, {"forma_juridica": "inventada"}, vigente_desde="2026-01-01")
    with pytest.raises(fp.ErrorFiscal):                                                    # no residente sin país
        fp.guardar_perfil(t, u, c, {**BASE, "residencia": "otro"}, vigente_desde="2026-01-01")
    with pytest.raises(fp.ErrorFiscal):
        fp.guardar_perfil(t, u, c, BASE, vigente_desde="01/01/2026")
    ok = fp.guardar_perfil(t, u, c, {**BASE, "residencia": "UE", "pais": "fr", "tributacion_foral": "1", "actividades": [{"epigrafe": "861", "descripcion": "Alquiler"}]}, vigente_desde="2026-01-01")
    assert ok["pais"] == "FR" and ok["tributacion_foral"] == 1 and "861" in ok["actividades"]


def test_la_version_obsoleta_se_rechaza():
    t, u = _despacho(); c = _titular(t)
    p = fp.guardar_perfil(t, u, c, BASE, vigente_desde="2026-01-01")
    q = fp.guardar_perfil(t, u, c, {**BASE, "sii": 1}, vigente_desde="2026-01-01", perfil_id=p["id"], version=p["version"])
    assert q["version"] == p["version"] + 1 and q["sii"] == 1
    with pytest.raises(fp.ErrorFiscal) as e:
        fp.guardar_perfil(t, u, c, BASE, vigente_desde="2026-01-01", perfil_id=p["id"], version=p["version"])
    assert e.value.codigo == "version_obsoleta" and e.value.extra["version_actual"] == q["version"]


def test_aislamiento_entre_despachos():
    t1, u1 = _despacho("Despacho uno"); t2, u2 = _despacho("Despacho dos")
    c1, c2 = _titular(t1, "Uno SL", "B11111111"), _titular(t2, "Dos SL", "B22222222")
    fp.guardar_perfil(t1, u1, c1, BASE, vigente_desde="2026-01-01")
    with pytest.raises(fp.ErrorFiscal) as e:                                               # apuntar a un titular de otro despacho
        fp.guardar_perfil(t2, u2, c1, BASE, vigente_desde="2026-01-01")
    assert e.value.codigo == "no_encontrado"
    assert fp.perfiles_de(t2, c1) == [] and fp.perfil_en(t2, c1, "2026-02-01") is None
    with pytest.raises(fp.ErrorFiscal):
        fp.relacionar(t2, u2, c2, c1, vigente_desde="2026-01-01")
    assert fp.titulares_de(t2, c2) == []


def test_una_gestora_con_muchos_titulares_y_un_titular_en_dos_gestoras_sin_fusionarse():
    t, u = _despacho(); g1, g2 = _titular(t, "Gestora 1", "B10000001"), _titular(t, "Gestora 2", "B10000002")
    titulares = [_titular(t, f"Titular {i}", f"A{i:07d}") for i in range(30)]
    for x in titulares:
        fp.relacionar(t, u, g1, x, vigente_desde="2026-01-01")
    assert fp.titulares_de(t, g1, "2026-05-01") == sorted(titulares)
    fp.relacionar(t, u, g1, titulares[0], vigente_desde="2026-01-01", tipo="grupo")      # otro tipo, misma pareja: no es duplicado
    # un titular cambia de gestora: se cierra una relación y se abre la otra
    conn = db.get_connection()
    try:
        conn.execute("UPDATE fiscal_relaciones SET vigente_hasta = '2026-06-30' WHERE tenant_id = ? AND hasta_cliente_id = ? AND desde_cliente_id = ? AND tipo = 'gestora_titular'", (t, titulares[1], g1))
        conn.commit()
    finally:
        conn.close()
    fp.relacionar(t, u, g2, titulares[1], vigente_desde="2026-07-01")
    assert titulares[1] in fp.titulares_de(t, g1, "2026-06-30") and titulares[1] not in fp.titulares_de(t, g1, "2026-07-01")
    assert fp.gestoras_de(t, titulares[1], "2026-08-01") == [g2] and fp.gestoras_de(t, titulares[1], "2026-02-01") == [g1]
    assert fp.perfiles_de(t, titulares[0]) == [] and titulares[0] != titulares[1]


def test_relaciones_no_validas():
    t, u = _despacho(); a, b = _titular(t, "A", "B10000001"), _titular(t, "B", "B10000002")
    with pytest.raises(fp.ErrorFiscal):
        fp.relacionar(t, u, a, a, vigente_desde="2026-01-01")
    with pytest.raises(fp.ErrorFiscal):
        fp.relacionar(t, u, a, b, tipo="rara", vigente_desde="2026-01-01")
    fp.relacionar(t, u, a, b, vigente_desde="2026-01-01")
    with pytest.raises(fp.ErrorFiscal):
        fp.relacionar(t, u, a, b, vigente_desde="2026-01-01")


def test_borrar_el_despacho_borra_lo_fiscal():
    t, u = _despacho(); c = _titular(t); d = _titular(t, "Otro", "B99999999")
    fp.guardar_perfil(t, u, c, BASE, vigente_desde="2026-01-01"); fp.relacionar(t, u, c, d, vigente_desde="2026-01-01")
    conn = db.get_connection()
    try:
        fp.borrar_datos_de_tenant(conn, t)
        conn.commit()
    finally:
        conn.close()
    assert fp.perfiles_de(t, c) == [] and fp.titulares_de(t, c) == []


def test_el_proceso_del_backoffice_ofrece_guilda_fiscal():
    """El backoffice es OTRO proceso y no importa las pantallas de la aplicación: si no da de alta el módulo él mismo, «Guilda Fiscal» no sale en su lista de módulos (pasó en el primer despliegue)."""
    import subprocess
    import sys
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "-c", "import backoffice.main as m; m.create_app(testing=True); from app import verticales; print(verticales.VERTICALES['fiscal'].disponible)"], cwd=raiz,
                       capture_output=True, text=True, timeout=120)
    assert r.stdout.strip().splitlines()[-1] == "True", r.stderr[-400:]
