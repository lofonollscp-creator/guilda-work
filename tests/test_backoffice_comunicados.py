"""Comunicados del backoffice (banner en la app) y buscador global del backoffice."""
from datetime import datetime, timedelta

import pytest

from app import comunicados, db
from tests.test_backoffice_app import bo, entrar, post  # noqa: F401 -- fixture


def _iso(**delta):
    return (datetime.now() + timedelta(**delta)).isoformat(timespec="minutes")


def _usuario(email, tenant=None):
    uid = db.crear_usuario_vinculado_a_kratos(email, "kratos-" + email)
    if tenant:
        db.asignar_tenant(uid, tenant)
    return uid


def test_vigencia_destino_y_orden():
    a, b = db.crear_tenant("Despacho A"), db.crear_tenant("Despacho B")
    ua, ub = _usuario("a@x.com", a), _usuario("b@x.com", b)
    comunicados.crear("Para todos", nivel="info")
    comunicados.crear("Solo A", nivel="aviso", tenant_id=a)
    comunicados.crear("Futuro", desde=_iso(days=1))
    comunicados.crear("Pasado", hasta=_iso(days=-1))
    comunicados.crear("Caída", nivel="critico")
    titulos_a = [c["titulo"] for c in comunicados.activos_para(ua, a)]
    assert titulos_a == ["Caída", "Solo A", "Para todos"]          # críticos primero; futuro y pasado fuera
    assert [c["titulo"] for c in comunicados.activos_para(ub, b)] == ["Caída", "Para todos"]
    assert [c["titulo"] for c in comunicados.activos_para(ub, None)] == ["Caída", "Para todos"]


def test_cerrar_solo_los_no_criticos_y_por_usuario():
    t = db.crear_tenant("Cierre")
    u1, u2 = _usuario("c1@x.com", t), _usuario("c2@x.com", t)
    info, crit = comunicados.crear("Info"), comunicados.crear("Crítico", nivel="critico")
    assert comunicados.cerrar(u1, info) and not comunicados.cerrar(u1, crit) and not comunicados.cerrar(u1, 9999)
    assert [c["titulo"] for c in comunicados.activos_para(u1, t)] == ["Crítico"]
    assert [c["titulo"] for c in comunicados.activos_para(u2, t)] == ["Crítico", "Info"]


def test_validaciones_y_estados():
    with pytest.raises(ValueError):
        comunicados.crear("   ")
    with pytest.raises(ValueError):
        comunicados.crear("x", nivel="raro")
    with pytest.raises(ValueError):
        comunicados.crear("x", tenant_id=424242)
    with pytest.raises(ValueError):
        comunicados.crear("x", desde=_iso(days=2), hasta=_iso(days=1))
    cid = comunicados.crear("Pausable")
    assert comunicados.listar()[0]["estado"] == "activo"
    comunicados.cambiar_activo(cid, False)
    assert comunicados.listar()[0]["estado"] == "pausado"
    u = _usuario("p@x.com")
    assert comunicados.activos_para(u, None) == []
    assert comunicados.eliminar(cid) and not comunicados.eliminar(cid)


def test_backoffice_crea_pausa_y_borra_con_auditoria(bo):
    entrar(bo)
    t = db.crear_tenant("Destino")
    r = post(bo, "/comunicados", titulo="Mantenimiento", texto="Esta noche", nivel="aviso", tenant_id=str(t), desde="", hasta="")
    assert r.status_code == 302
    html = bo.get("/comunicados").get_data(as_text=True)
    assert "Mantenimiento" in html and "Destino" in html and "ACTIVO" in html
    cid = comunicados.listar()[0]["id"]
    post(bo, f"/comunicados/{cid}/activo", activo="0")
    assert comunicados.listar()[0]["estado"] == "pausado"
    # entrada inválida: no se crea y se avisa
    post(bo, "/comunicados", titulo="", nivel="info")
    assert len(comunicados.listar()) == 1
    assert post(bo, f"/comunicados/{cid}/borrar").status_code == 302 and comunicados.listar() == []
    assert post(bo, "/comunicados/999/borrar").status_code == 404
    assert "comunicado.crear" in bo.get("/actividad").get_data(as_text=True)


def test_buscador_global_agrupa_y_exige_sesion(bo):
    assert bo.get("/buscar?q=x").status_code == 302
    entrar(bo)
    t = db.crear_tenant("Gestoría Ejemplo")
    _usuario("lucia@ejemplo.com", t)
    r = bo.get("/buscar?q=ejemplo").get_json()["resultados"]
    assert {x["tipo"] for x in r} == {"Tenant", "Usuario"}
    assert any(x["titulo"] == "Gestoría Ejemplo" for x in r)
    paginas = bo.get("/buscar?q=comunic").get_json()["resultados"]
    assert paginas and paginas[0]["tipo"] == "Página" and paginas[0]["url"].endswith("/comunicados")
    assert len(bo.get("/buscar").get_json()["resultados"]) == 8          # sin consulta: atajos
    assert bo.get("/buscar?q=%25_%5C").status_code == 200                # comodines de LIKE escapados


def test_banner_en_la_app_y_cierre(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "banner@ejemplo.com", "una-clave-larga-1234")
    db.asignar_tenant(uid, db.crear_tenant("Despacho banner"))
    comunicados.crear("Mantenimiento nocturno", "Entre las 02:00 y las 03:00", nivel="aviso")
    critico = comunicados.crear("Incidencia en curso", nivel="critico")
    html = cliente.get("/").get_data(as_text=True)
    assert "Mantenimiento nocturno" in html and "Incidencia en curso" in html
    assert f"/comunicados/{critico}/cerrar" not in html            # el crítico no tiene botón de cierre
    aviso = next(c["id"] for c in comunicados.activos_para(uid, db.obtener_usuario(uid)["tenant_id"]) if c["nivel"] == "aviso")
    assert cliente.post(f"/comunicados/{aviso}/cerrar").status_code == 302
    html = cliente.get("/").get_data(as_text=True)
    assert "Mantenimiento nocturno" not in html and "Incidencia en curso" in html
