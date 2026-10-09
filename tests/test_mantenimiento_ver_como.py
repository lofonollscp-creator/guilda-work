"""Modo mantenimiento y «ver como» (soporte en solo lectura)."""
from datetime import datetime, timedelta

import pytest

from app import db, mantenimiento, ver_como
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_backoffice_app import bo, entrar, post  # noqa: F401 -- fixture


def _iso(**d):
    return (datetime.now() + timedelta(**d)).isoformat(timespec="minutes")


def _con_tenant(cliente, email):
    uid = iniciar_sesion_de_prueba(cliente, email, "una-clave-larga-1234")
    t = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(uid, t)
    return uid, t


# --- Mantenimiento -----------------------------------------------------------------

def test_cierre_de_un_despacho_solo_afecta_a_ese_despacho(cliente):
    uid, t = _con_tenant(cliente, "m1@ejemplo.com")
    assert cliente.get("/").status_code == 200
    otro = db.crear_tenant("Otro")
    mantenimiento.activar(otro, "No te afecta")
    assert cliente.get("/").status_code == 200
    mantenimiento.activar(t, "Actualizando tu despacho")
    r = cliente.get("/")
    assert r.status_code == 503 and "Actualizando tu despacho" in r.get_data(as_text=True) and r.headers["Retry-After"]
    j = cliente.get("/api/v1/tareas")
    assert j.status_code == 503 and j.get_json()["mantenimiento"] is True


def test_admin_global_pasa_y_finalizar_reabre(cliente):
    uid, t = _con_tenant(cliente, "m2@ejemplo.com")
    cierre = mantenimiento.activar(None, "Todo cerrado")
    assert cliente.get("/").status_code == 503
    assert cliente.get("/login").status_code != 503                      # el login sigue abierto
    db.hacer_admin("m2@ejemplo.com")
    mantenimiento._invalidar()
    assert cliente.get("/").status_code == 200
    db.quitar_admin("m2@ejemplo.com")
    assert mantenimiento.finalizar(cierre) and not mantenimiento.finalizar(cierre)
    assert cliente.get("/").status_code == 200


def test_activar_valida_y_no_duplica_ambito():
    t = db.crear_tenant("Dup")
    mantenimiento.activar(t)
    with pytest.raises(ValueError):
        mantenimiento.activar(t)
    with pytest.raises(ValueError):
        mantenimiento.activar(None, hasta="no es fecha")
    with pytest.raises(ValueError):
        mantenimiento.activar(None, hasta=_iso(days=-1))
    with pytest.raises(ValueError):
        mantenimiento.activar(99999)
    c = mantenimiento.activar(None, hasta=_iso(hours=1))
    assert mantenimiento.vigente_para(None)["id"] == c
    assert mantenimiento.vigente_para(t)["id"] == c                     # el global manda


def test_cierre_caducado_no_cuenta():
    conn = db.get_connection()
    conn.execute("INSERT INTO mantenimiento (tenant_id, mensaje, hasta, activo, creado_en) VALUES (NULL, 'x', ?, 1, ?)", (_iso(days=-1), _iso(days=-2)))
    conn.commit(); conn.close()
    mantenimiento._invalidar()
    assert mantenimiento.vigente_para(None) is None
    assert not mantenimiento.listar()[0]["vigente"]


# --- Ver como ----------------------------------------------------------------------

def test_enlace_un_solo_uso_caduca_y_no_vale_para_admins():
    u = db.crear_usuario_vinculado_a_kratos("v1@ejemplo.com", "k-v1")
    with pytest.raises(ValueError):
        ver_como.crear_enlace(u, "jorge", "no")                          # motivo demasiado corto
    with pytest.raises(ValueError):
        ver_como.crear_enlace(9999, "jorge", "motivo válido")
    a = db.crear_usuario_vinculado_a_kratos("adm@ejemplo.com", "k-adm")
    db.hacer_admin("adm@ejemplo.com")
    with pytest.raises(ValueError):
        ver_como.crear_enlace(a, "jorge", "motivo válido")
    tok = ver_como.crear_enlace(u, "jorge", "Ticket 1")
    assert ver_como.canjear(tok)["usuario_id"] == u and ver_como.canjear(tok) is None and ver_como.canjear("inventado") is None
    tok2 = ver_como.crear_enlace(u, "jorge", "Ticket 2")
    conn = db.get_connection()
    conn.execute("UPDATE ver_como_tokens SET expira_en = ?", (_iso(minutes=-5),)); conn.commit(); conn.close()
    assert ver_como.canjear(tok2) is None
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM ver_como_tokens WHERE token_hash = ?", (tok,)).fetchone()[0] == 0   # solo hash
    conn.close()


def test_sesion_ver_como_es_solo_lectura_y_se_audita(cliente):
    t = db.crear_tenant("Cliente soporte")
    u = db.crear_usuario_vinculado_a_kratos("cliente@ejemplo.com", "k-cli")
    db.asignar_tenant(u, t)
    tok = ver_como.crear_enlace(u, "jorge", "Ticket 77: revisar calendario")
    assert cliente.get("/soporte/ver-como/inventado").status_code == 404
    assert cliente.get(f"/soporte/ver-como/{tok}").status_code == 302
    r = cliente.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "cliente@ejemplo.com" in html and "jorge" in html
    assert cliente.post("/onboarding/ocultar").status_code == 403         # nada de escrituras
    assert cliente.get(f"/soporte/ver-como/{tok}").status_code == 404      # enlace consumido
    mantenimiento.activar(t, "Cerrado")
    assert cliente.get("/").status_code == 200                            # soporte puede ver aun con cierre
    assert cliente.post("/soporte/ver-como/salir").status_code == 302
    assert cliente.get("/").status_code in (302, 503)                      # ya no hay sesión
    acciones = [f["accion"] for f in db.listar_auditoria_backoffice()]
    assert "ver_como.inicio" in acciones and "ver_como.fin" in acciones


def test_sesion_ver_como_caducada_se_descarta(cliente):
    u = db.crear_usuario_vinculado_a_kratos("cad@ejemplo.com", "k-cad")
    db.asignar_tenant(u, db.crear_tenant("Cad"))
    tok = ver_como.crear_enlace(u, "jorge", "motivo válido")
    cliente.get(f"/soporte/ver-como/{tok}")
    with cliente.session_transaction() as s:
        s["ver_como"] = {**s["ver_como"], "hasta": (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds")}
    assert "cad@ejemplo.com" not in cliente.get("/").get_data(as_text=True)
    with cliente.session_transaction() as s:
        assert "ver_como" not in s


# --- Backoffice -----------------------------------------------------------------------

def test_backoffice_mantenimiento_y_ver_como(bo):
    entrar(bo)
    t = db.crear_tenant("BO cierre")
    r = post(bo, "/mantenimiento", tenant_id=str(t), mensaje="Volvemos pronto", hasta="")
    assert r.status_code == 302 and mantenimiento.vigente_para(t) is None        # falta confirmar
    post(bo, "/mantenimiento", tenant_id=str(t), mensaje="Volvemos pronto", hasta="", confirmar="1")
    mantenimiento._invalidar()
    assert mantenimiento.vigente_para(t)["mensaje"] == "Volvemos pronto"
    assert "CERRADO" in bo.get("/mantenimiento").get_data(as_text=True)
    cid = mantenimiento.listar()[0]["id"]
    post(bo, f"/mantenimiento/{cid}/finalizar")
    assert mantenimiento.vigente_para(t) is None and post(bo, "/mantenimiento/999/finalizar").status_code == 404

    u = db.crear_usuario_vinculado_a_kratos("soporte@ejemplo.com", "k-sop")
    r = post(bo, f"/usuarios/{u}/ver-como", motivo="ab")
    assert r.status_code == 302 and "/soporte/ver-como/" not in r.headers["Location"]     # motivo corto: rechazado
    r = post(bo, f"/usuarios/{u}/ver-como", motivo="Ticket 5: revisar facturas")
    assert "/soporte/ver-como/" in r.headers["Location"]
    acciones = bo.get("/actividad").get_data(as_text=True)
    assert "ver_como.emitir" in acciones and "mantenimiento.activar" in acciones
    assert "Ver como este usuario" in bo.get(f"/usuarios/{u}").get_data(as_text=True)
