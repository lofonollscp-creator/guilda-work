"""Una persona que trabaja en dos despachos aparece en los equipos, selectores y avisos de AMBOS, con los atributos (dirección, custodia) que tiene en cada uno."""
from app import certificados, db, fiscal_perfiles, nucleo  # noqa: F401
from app import db_fiscal


def _despachos():
    a, b = db.crear_tenant("Despacho Uno"), db.crear_tenant("Despacho Dos")
    solo_a = db.crear_usuario_vinculado_a_kratos("solo-a@ejemplo.com", "k-solo-a"); db.asignar_tenant(solo_a, a)
    solo_b = db.crear_usuario_vinculado_a_kratos("solo-b@ejemplo.com", "k-solo-b"); db.asignar_tenant(solo_b, b)
    viajera = db.crear_usuario_vinculado_a_kratos("viajera@ejemplo.com", "k-viajera"); db.asignar_tenant(viajera, a)
    db.anadir_usuario_a_tenant(viajera, b)
    return a, b, solo_a, solo_b, viajera


def test_el_equipo_de_cada_despacho_incluye_a_quien_trabaja_en_los_dos():
    a, b, solo_a, solo_b, viajera = _despachos()
    assert sorted(db.usuarios_de_tenant(a)) == sorted([solo_a, viajera]) and sorted(db.usuarios_de_tenant(b)) == sorted([solo_b, viajera])
    assert sorted(f["id"] for f in nucleo.equipo(b)) == sorted([solo_b, viajera]) and viajera in [f["id"] for f in nucleo.equipo(a)]
    assert db.usuario_pertenece_a_tenant(viajera, a) and db.usuario_pertenece_a_tenant(viajera, b) and not db.usuario_pertenece_a_tenant(solo_a, b)


def test_los_atributos_se_leen_en_el_despacho_de_que_se_trate():
    a, b, solo_a, solo_b, viajera = _despachos()
    db.fijar_atributos_en_despacho(viajera, b, supervisor_tenant=1, custodio_certificados=1)           # dirige y custodia en el segundo despacho, no en el primero
    assert viajera in db_fiscal.destinatarios_aviso_vencimiento(b, None) and viajera not in db_fiscal.destinatarios_aviso_vencimiento(a, None)
    custodio = lambda t: {f["id"]: f["custodio"] for f in certificados.custodios(t)}
    assert custodio(b)[viajera] == 1 and custodio(a)[viajera] == 0
    db.fijar_atributos_en_despacho(viajera, a, supervisor_tenant=1)                                     # en el principal manda `usuarios`
    assert viajera in db_fiscal.destinatarios_aviso_vencimiento(a, None)
    assert db_fiscal.destinatarios_aviso_vencimiento(a, solo_a) == [solo_a] and db_fiscal.destinatarios_aviso_vencimiento(b, solo_a) != [solo_a]     # el responsable ya no es de ese despacho: avisan los supervisores


def test_los_selectores_de_companeros_incluyen_a_quien_trabaja_en_mas_de_un_despacho():
    from app import db_tareas
    a, b, solo_a, solo_b, viajera = _despachos()
    ids = lambda u: [f["id"] for f in db_tareas.listar_companeros_tenant(u)]
    assert ids(solo_a) == [viajera] and ids(solo_b) == [viajera]                  # antes solo_b no la veía: su principal es el otro despacho
    assert ids(viajera) == [solo_a]                                               # sin contexto de despacho (SQLite) trabaja en el principal
    conn = db.get_connection()
    try:
        assert db_tareas._companero_del_tenant(conn, solo_b, viajera) == viajera and db_tareas._companero_del_tenant(conn, solo_a, solo_b) is None
    finally:
        conn.close()
