"""Capa BD del blindaje del fichaje (Fase G3): encadenado de hashes y
geolocalización opcional por tenant."""
from app import db


def _usuario() -> int:
    return db.crear_usuario_vinculado_a_kratos("fichaje-hash-test@ejemplo.com", "kratos-fichaje-hash-test")


def test_cadena_integra_tras_varios_fichajes():
    usuario_id = _usuario()
    db.fichar(usuario_id, None, "entrada")
    db.fichar(usuario_id, None, "pausa_inicio")
    db.fichar(usuario_id, None, "pausa_fin")
    db.fichar(usuario_id, None, "salida")

    resultado = db.verificar_integridad_fichajes()
    assert resultado["integra"] is True
    assert resultado["primera_fila_rota"] is None


def test_manipular_tipo_directamente_en_bd_rompe_la_cadena():
    usuario_id = _usuario()
    v1 = db.fichar(usuario_id, None, "entrada")
    db.fichar(usuario_id, None, "salida")

    conn = db.get_connection()
    conn.execute("UPDATE fichajes SET tipo = ? WHERE id = ?", ("pausa_inicio", v1))
    conn.commit()
    conn.close()

    resultado = db.verificar_integridad_fichajes()
    assert resultado["integra"] is False
    assert resultado["primera_fila_rota"] == v1


def test_backfill_de_hash_para_filas_creadas_antes_de_la_migracion():
    usuario_id = _usuario()
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO fichajes (usuario_id, tenant_id, tipo, marca_tiempo, origen, creado_por, creado_en, hash) "
        "VALUES (?, NULL, 'entrada', ?, 'web', ?, ?, NULL)",
        (usuario_id, db.now_iso(), usuario_id, db.now_iso()),
    )
    conn.commit()
    conn.close()

    assert db.verificar_integridad_fichajes()["integra"] is False  # hash NULL != esperado

    db.init_db()  # re-ejecutar la migración rellena el hash que faltaba

    resultado = db.verificar_integridad_fichajes()
    assert resultado["integra"] is True


def test_geolocalizacion_solo_se_guarda_si_se_pasa_explicita():
    usuario_id = _usuario()
    sin_geo = db.fichar(usuario_id, None, "entrada")
    con_geo = db.fichar(usuario_id, None, "salida", latitud=41.38, longitud=2.17)

    conn = db.get_connection()
    fila_sin = conn.execute("SELECT latitud, longitud FROM fichajes WHERE id = ?", (sin_geo,)).fetchone()
    fila_con = conn.execute("SELECT latitud, longitud FROM fichajes WHERE id = ?", (con_geo,)).fetchone()
    conn.close()
    assert fila_sin["latitud"] is None and fila_sin["longitud"] is None
    assert fila_con["latitud"] == 41.38 and fila_con["longitud"] == 2.17


def test_fijar_fichaje_geolocalizacion_por_tenant():
    tenant_id = db.crear_tenant("Gestoria Geo Test")
    assert db.obtener_tenant(tenant_id)["fichaje_geolocalizacion"] == 0
    db.fijar_fichaje_geolocalizacion(tenant_id, True)
    assert db.obtener_tenant(tenant_id)["fichaje_geolocalizacion"] == 1
    db.fijar_fichaje_geolocalizacion(tenant_id, False)
    assert db.obtener_tenant(tenant_id)["fichaje_geolocalizacion"] == 0
