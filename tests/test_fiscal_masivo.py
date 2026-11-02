"""Cambios en lote de los vencimientos fiscales (app/fiscal_masivo.py): proponer → confirmar → deshacer."""
from datetime import datetime, timedelta

import pytest

from app import acceso, db, fiscal_masivo as fm
from app.db_fiscal import crear_cliente_fiscal, crear_vencimiento_fiscal, editar_vencimiento_fiscal, marcar_presentado_vencimiento_fiscal, obtener_vencimiento_fiscal


def _despacho():
    t = db.crear_tenant("Despacho Lote Fiscal")
    sup = db.crear_usuario_vinculado_a_kratos("sup-lote@ejemplo.com", "k-sup-lote"); db.asignar_tenant(sup, t); db.asignar_supervisor_tenant(sup, True)
    ana = db.crear_usuario_vinculado_a_kratos("ana-lote@ejemplo.com", "k-ana-lote"); db.asignar_tenant(ana, t)
    aud = db.crear_usuario_vinculado_a_kratos("aud-lote@ejemplo.com", "k-aud-lote"); db.asignar_tenant(aud, t)
    acceso.dar_membresia(t, sup, aud, "auditor", "organizacion")
    c = crear_cliente_fiscal(t, "Titular Lote SL", nif=None)
    vs = [crear_vencimiento_fiscal(t, c, "303", f"{i}T 2026", f"2026-{3 * i + 1:02d}-20", usuario_id=sup) for i in (1, 2, 3)]
    return t, sup, ana, aud, vs


def _v(t, i):
    return dict(obtener_vencimiento_fiscal(t, i))


def test_reasignar_propone_sin_cambiar_aplica_y_deshace():
    t, sup, ana, aud, vs = _despacho()
    a = fm.proponer(t, sup, "reasignar", vs, {"usuario_id": ana})
    assert a["estado"] == "propuesta" and len(a["afectados"]) == 3 and a["se_puede_aplicar"] and all(_v(t, i)["usuario_id"] == sup for i in vs)
    fm.aplicar(t, sup, a["id"])
    assert all(_v(t, i)["usuario_id"] == ana for i in vs) and fm.obtener(t, sup, a["id"])["estado"] == "aplicada"
    with pytest.raises(fm.ErrorMasivoFiscal, match="ya se resolvió"):
        fm.aplicar(t, sup, a["id"])
    r = fm.deshacer(t, sup, a["id"])
    assert r["estado"] == "deshecha" and r["devueltos"] == 3 and all(_v(t, i)["usuario_id"] == sup for i in vs)


def test_posponer_exige_motivo_y_solo_toca_los_pendientes_que_no_han_cambiado():
    t, sup, ana, aud, vs = _despacho()
    with pytest.raises(fm.ErrorMasivoFiscal, match="motivo"):
        fm.proponer(t, sup, "posponer", vs, {"dias": 7})
    with pytest.raises(fm.ErrorMasivoFiscal, match="1 a 90"):
        fm.proponer(t, sup, "posponer", vs, {"dias": 400, "motivo": "x" * 5})
    marcar_presentado_vencimiento_fiscal(t, vs[0], sup)
    a = fm.proponer(t, sup, "posponer", vs, {"dias": 7, "motivo": "Falta documentación del cliente"})
    assert [x["id"] for x in a["afectados"]] == vs[1:] and a["omitidos"][0]["motivo"] == "ya no está pendiente"
    editar_vencimiento_fiscal(t, vs[1], usuario_id=ana)                                   # alguien lo toca entre la propuesta y la confirmación
    fm.aplicar(t, sup, a["id"])
    hecho = fm.obtener(t, sup, a["id"])
    assert [x["id"] for x in hecho["afectados"]] == [vs[2]] and any(x["motivo"] == "ha cambiado desde la propuesta" for x in hecho["omitidos"])
    assert _v(t, vs[2])["fecha_limite"][:10] == "2026-10-27" and _v(t, vs[1])["fecha_limite"][:10] == "2026-07-20"
    editar_vencimiento_fiscal(t, vs[2], usuario_id=ana)                                   # se vuelve a cambiar después: deshacer no lo pisa
    r = fm.deshacer(t, sup, a["id"])
    assert r["devueltos"] == 0 and r["sin_tocar"][0]["motivo"] == "se ha vuelto a cambiar después" and _v(t, vs[2])["fecha_limite"][:10] == "2026-10-27"


def test_reglas_de_permiso_y_caducidad():
    t, sup, ana, aud, vs = _despacho()
    with pytest.raises(fm.ErrorMasivoFiscal, match="solo permite consultar"):
        fm.proponer(t, aud, "reasignar", vs, {"usuario_id": ana})
    with pytest.raises(fm.ErrorMasivoFiscal, match="no es de tu despacho"):
        fm.proponer(t, sup, "reasignar", vs, {"usuario_id": 987654})
    with pytest.raises(fm.ErrorMasivoFiscal, match="ningún vencimiento"):
        fm.proponer(t, sup, "reasignar", [], {"usuario_id": ana})
    with pytest.raises(fm.ErrorMasivoFiscal, match="ya es suyo|Ningún vencimiento cambiaría"):
        fm.proponer(t, sup, "reasignar", vs, {"usuario_id": sup})
    a = fm.proponer(t, sup, "reasignar", vs, {"usuario_id": ana})
    assert fm.obtener(t, ana, a["id"]) is None                                            # otra persona no ve la propuesta ajena
    with pytest.raises(fm.ErrorMasivoFiscal, match="no encontrada"):
        fm.aplicar(t, ana, a["id"])
    fm.cancelar(t, sup, a["id"])
    with pytest.raises(fm.ErrorMasivoFiscal, match="ya se resolvió"):
        fm.aplicar(t, sup, a["id"])
    vieja = fm.proponer(t, sup, "reasignar", vs, {"usuario_id": ana})
    conn = db.get_connection()
    conn.execute("UPDATE fiscal_acciones_masivas SET creada_en = ? WHERE id = ?", ((datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds"), vieja["id"]))
    conn.commit(); conn.close()
    with pytest.raises(fm.ErrorMasivoFiscal, match="caducó"):
        fm.aplicar(t, sup, vieja["id"])
    assert [x["id"] for x in fm.historial(t, sup)] == [a["id"]]
