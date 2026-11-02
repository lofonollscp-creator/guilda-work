"""Cambios en lote del Comercial: proponer → confirmar → deshacer (app/comercial_masivo.py)."""
from datetime import datetime, timedelta

import pytest

from app import acceso, comercial as co, comercial_masivo as cm, db, verticales
from app.comercial import ErrorComercial


@pytest.fixture
def d(base_de_datos_temporal):
    t = db.crear_tenant("Despacho masivo")
    verticales.fijar_activo(t, "comercial", True)

    class E:
        pass
    e = E()
    e.t = t

    def u(mail, sup=False):
        x = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail)
        db.asignar_tenant(x, t)
        if sup:
            db.asignar_supervisor_tenant(x, True)
        return x
    e.sup, e.ana, e.beto, e.aud = u("sup-cm@ejemplo.com", True), u("ana-cm@ejemplo.com"), u("beto-cm@ejemplo.com"), u("aud-cm@ejemplo.com")
    acceso.dar_membresia(t, e.sup, e.aud, "auditor", "organizacion")
    return e


def _ops(d, n=3, **kw):
    return [co.crear_oportunidad(d.t, d.ana, f"Oportunidad {i}", contacto_nombre=f"Persona {i}", **kw) for i in range(n)]


def _etapa(d, oid):
    return co.obtener_oportunidad(d.t, d.ana, oid)["etapa"]


def test_proponer_no_cambia_nada_y_resume(d):
    ids = _ops(d)
    co.mover_oportunidad(d.t, d.ana, ids[0], "contactado")
    a = cm.proponer(d.t, d.ana, "mover_etapa", {"ids": ids}, {"etapa": "contactado"})
    assert a["estado"] == "propuesta" and len(a["afectados"]) == 2 and [x["motivo"] for x in a["omitidos"]] == ["ya está en esa etapa"]
    assert [_etapa(d, i) for i in ids] == ["contactado", "nuevo", "nuevo"]
    assert "2 oportunidades" in cm.resumen_para_confirmar(d.t, d.ana, a["id"]) and "90 días" in cm.resumen_para_confirmar(d.t, d.ana, a["id"])


def test_aplicar_cambia_las_oportunidades_con_sus_reglas_y_se_deshace(d):
    ids = _ops(d)
    a = cm.proponer(d.t, d.ana, "mover_etapa", {"ids": ids}, {"etapa": "reunion"})
    r = cm.aplicar(d.t, d.ana, a["id"])
    assert r["estado"] == "aplicada" and len(r["afectados"]) == 3 and r["se_puede_deshacer"]
    assert [_etapa(d, i) for i in ids] == ["reunion"] * 3
    assert any(x["tipo"] == "etapa" for x in co.cronologia(d.t, d.ana, oportunidad_id=ids[0]))        # queda en la cronología como un cambio normal
    with pytest.raises(ErrorComercial):
        cm.aplicar(d.t, d.ana, a["id"])                                                                # una propuesta se aplica una sola vez
    u = cm.deshacer(d.t, d.ana, a["id"])
    assert u["estado"] == "deshecha" and u["devueltas"] == 3 and [_etapa(d, i) for i in ids] == ["nuevo"] * 3
    with pytest.raises(ErrorComercial):
        cm.deshacer(d.t, d.ana, a["id"])


def test_perder_exige_motivo_y_se_reabre_al_deshacer(d):
    ids = _ops(d, 2)
    with pytest.raises(ErrorComercial):
        cm.proponer(d.t, d.ana, "mover_etapa", {"ids": ids}, {"etapa": "perdida"})
    a = cm.proponer(d.t, d.ana, "mover_etapa", {"ids": ids}, {"etapa": "perdida", "motivo": "Precio"})
    cm.aplicar(d.t, d.ana, a["id"])
    assert co.obtener_oportunidad(d.t, d.ana, ids[0])["estado"] == "perdida"
    cm.deshacer(d.t, d.ana, a["id"])
    assert co.obtener_oportunidad(d.t, d.ana, ids[0])["estado"] == "abierta"


def test_lo_que_cambia_entre_la_propuesta_y_la_confirmacion_no_se_pisa(d):
    ids = _ops(d)
    a = cm.proponer(d.t, d.ana, "mover_etapa", {"ids": ids}, {"etapa": "reunion"})
    co.mover_oportunidad(d.t, d.beto, ids[1], "propuesta")                                             # otra persona la mueve antes
    r = cm.aplicar(d.t, d.ana, a["id"])
    assert len(r["afectados"]) == 2 and [x["motivo"] for x in r["omitidos"]] == ["ha cambiado desde la propuesta"]
    assert _etapa(d, ids[1]) == "propuesta"


def test_deshacer_respeta_lo_cambiado_despues(d):
    ids = _ops(d)
    a = cm.proponer(d.t, d.ana, "mover_etapa", {"ids": ids}, {"etapa": "reunion"})
    cm.aplicar(d.t, d.ana, a["id"])
    co.mover_oportunidad(d.t, d.beto, ids[0], "negociacion")
    u = cm.deshacer(d.t, d.ana, a["id"])
    assert u["devueltas"] == 2 and len(u["sin_tocar"]) == 1 and _etapa(d, ids[0]) == "negociacion" and _etapa(d, ids[1]) == "nuevo"


def test_reasignar_y_posponer(d):
    ids = _ops(d, 3)
    co.editar_oportunidad(d.t, d.ana, ids[0], cierre_previsto="2026-12-10")
    co.editar_oportunidad(d.t, d.ana, ids[1], cierre_previsto="2026-12-20")
    a = cm.proponer(d.t, d.ana, "posponer_cierre", {"ids": ids}, {"dias": 10})
    assert len(a["afectados"]) == 2 and a["omitidos"][0]["motivo"] == "no tiene cierre previsto"
    cm.aplicar(d.t, d.ana, a["id"])
    assert co.obtener_oportunidad(d.t, d.ana, ids[0])["cierre_previsto"][:10] == "2026-12-20" and co.obtener_oportunidad(d.t, d.ana, ids[1])["cierre_previsto"][:10] == "2026-12-30"
    cm.deshacer(d.t, d.ana, a["id"])
    assert co.obtener_oportunidad(d.t, d.ana, ids[0])["cierre_previsto"][:10] == "2026-12-10"

    r = cm.proponer(d.t, d.ana, "reasignar", {"ids": ids}, {"responsable_id": d.beto})
    assert len(r["afectados"]) == 3
    cm.aplicar(d.t, d.ana, r["id"])
    assert all(co.obtener_oportunidad(d.t, d.ana, i)["responsable_id"] == d.beto for i in ids)
    cm.deshacer(d.t, d.ana, r["id"])
    assert all(co.obtener_oportunidad(d.t, d.ana, i)["responsable_id"] == d.ana for i in ids)
    with pytest.raises(ErrorComercial):
        cm.proponer(d.t, d.ana, "reasignar", {"ids": ids}, {"responsable_id": 999999})                # no es del despacho


def test_la_papelera_pide_escribir_el_recuento_y_se_restaura(d):
    ids = _ops(d, 2)
    a = cm.proponer(d.t, d.ana, "papelera", {"ids": ids})
    assert a["requiere_texto"] and a["texto_confirmacion"] == "2 oportunidades"
    with pytest.raises(ErrorComercial):
        cm.aplicar(d.t, d.ana, a["id"])
    with pytest.raises(ErrorComercial):
        cm.aplicar(d.t, d.ana, a["id"], "una cosa cualquiera")
    assert len(co.listar_oportunidades(d.t, d.ana)) == 2
    cm.aplicar(d.t, d.ana, a["id"], "2 Oportunidades")
    assert co.listar_oportunidades(d.t, d.ana) == []
    cm.deshacer(d.t, d.ana, a["id"])
    assert len(co.listar_oportunidades(d.t, d.ana)) == 2


def test_una_propuesta_caduca_a_la_hora(d):
    ids = _ops(d, 1)
    a = cm.proponer(d.t, d.ana, "mover_etapa", {"ids": ids}, {"etapa": "reunion"})
    conn = db.get_connection()
    conn.execute("UPDATE crm_acciones_masivas SET creada_en = ? WHERE id = ?", ((datetime.now() - timedelta(minutes=61)).isoformat(timespec="seconds"), a["id"]))
    conn.commit(); conn.close()
    with pytest.raises(ErrorComercial) as e:
        cm.aplicar(d.t, d.ana, a["id"])
    assert "caducó" in str(e.value)


def test_seleccion_por_filtro_permisos_y_aislamiento(d):
    _ops(d, 3)
    a = cm.proponer(d.t, d.ana, "mover_etapa", {"estado": "abierta", "etapa": "nuevo"}, {"etapa": "contactado"})
    assert len(a["afectados"]) == 3
    with pytest.raises(ErrorComercial):
        cm.proponer(d.t, d.aud, "mover_etapa", {"estado": "abierta"}, {"etapa": "contactado"})          # quien solo audita no propone
    assert cm.obtener(d.t, d.beto, a["id"]) is None and cm.obtener(d.t, d.sup, a["id"])["id"] == a["id"]    # ve la propuesta su autora y la dirección
    with pytest.raises(ErrorComercial):
        cm.aplicar(d.t, d.sup, a["id"])                                                                 # pero solo la autora la confirma
    t2 = db.crear_tenant("Otro")
    verticales.fijar_activo(t2, "comercial", True)
    x = db.crear_usuario_vinculado_a_kratos("x-cm@ejemplo.com", "k-x-cm"); db.asignar_tenant(x, t2)
    ajena = co.crear_oportunidad(t2, x, "Ajena", contacto_nombre="Z")
    with pytest.raises(ErrorComercial):
        cm.proponer(d.t, d.ana, "mover_etapa", {"ids": [ajena]}, {"etapa": "contactado"})              # una oportunidad de otro despacho no existe aquí
    assert [h["id"] for h in cm.historial(d.t, d.ana)] == []
    cm.aplicar(d.t, d.ana, a["id"])
    assert [h["id"] for h in cm.historial(d.t, d.ana)] == [a["id"]] and cm.historial(d.t, d.beto) == [] and len(cm.historial(d.t, d.sup)) == 1


def test_el_asistente_propone_aplica_y_deshace(d):
    from app import ia_herramientas as ih
    ids = _ops(d)
    assert "comercial_proponer_cambio_masivo" in ih.LECTURA and "comercial_aplicar_cambio_masivo" in ih.SIEMPRE_CONFIRMAR and "comercial_deshacer_cambio_masivo" in ih.SIEMPRE_CONFIRMAR
    assert ih.necesita_confirmacion("comercial_aplicar_cambio_masivo", True) and not ih.necesita_confirmacion("comercial_proponer_cambio_masivo", False)
    p = ih.ejecutar(d.ana, "comercial_proponer_cambio_masivo", {"tipo": "mover_etapa", "ids": ids, "etapa_destino": "contactado"})
    assert p["cambiarian"] == 3 and p["accion_id"] and all(_etapa(d, i) == "nuevo" for i in ids)                  # proponer no cambia nada
    resumen = ih.resumen_de_confirmacion(d.ana, "comercial_aplicar_cambio_masivo", {"accion_id": p["accion_id"]})
    assert "3 oportunidades" in resumen and "90 días" in resumen and ih.resumen_de_confirmacion(d.ana, "listar_notas", {}) == ""
    r = ih.ejecutar(d.ana, "comercial_aplicar_cambio_masivo", {"accion_id": p["accion_id"]})
    assert r["aplicadas"] == 3 and all(_etapa(d, i) == "contactado" for i in ids)
    u = ih.ejecutar(d.ana, "comercial_deshacer_cambio_masivo", {"accion_id": p["accion_id"]})
    assert u["devueltas"] == 3 and all(_etapa(d, i) == "nuevo" for i in ids)


def test_el_asistente_no_manda_a_la_papelera_sin_que_la_persona_lo_confirme_en_pantalla(d):
    from app import ia_herramientas as ih
    from app.ia_herramientas import ErrorHerramientaIA
    ids = _ops(d, 2)
    p = ih.ejecutar(d.ana, "comercial_proponer_cambio_masivo", {"tipo": "papelera", "ids": ids})
    assert p["requiere_escribir_en_pantalla"]
    with pytest.raises(ErrorHerramientaIA) as e:
        ih.ejecutar(d.ana, "comercial_aplicar_cambio_masivo", {"accion_id": p["accion_id"]})
    assert "en pantalla" in str(e.value) and len(co.listar_oportunidades(d.t, d.ana)) == 2
    with pytest.raises(ErrorHerramientaIA):
        ih.ejecutar(d.aud, "comercial_proponer_cambio_masivo", {"tipo": "mover_etapa", "ids": ids, "etapa_destino": "contactado"})      # solo lectura
