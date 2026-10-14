"""Ausencias, vacaciones y permisos (app/ausencias.py): días laborables, saldo, solapes, aprobación, cancelación, avisos y aislamiento entre despachos."""
from datetime import date, timedelta

import pytest

from app import ausencias as au, db, nucleo

ANIO = date.today().year + 1                       # año entero por delante: nada ha pasado ya
LUNES = date(ANIO, 3, 2)
while LUNES.weekday() != 0:
    LUNES += timedelta(days=1)


def iso(d):
    return d.isoformat()


@pytest.fixture
def eq(usuario_id):
    t = db.crear_tenant("Despacho Ausencias")
    def u(email, **kw):
        x = db.crear_usuario_vinculado_a_kratos(email, "k-" + email); db.asignar_tenant(x, t)
        if kw.get("gestor"):
            db.asignar_gestor_fichajes(x, True)
        return x
    class E: pass
    e = E(); e.t = t; e.ana = u("ana-au@ejemplo.com"); e.beto = u("beto-au@ejemplo.com"); e.gestora = u("gestora-au@ejemplo.com", gestor=True)
    return e


def test_solo_cuentan_los_dias_laborables(eq):
    assert au.dias_laborables(eq.t, LUNES, LUNES + timedelta(days=6)) == 5            # lunes a domingo
    assert au.dias_laborables(eq.t, LUNES + timedelta(days=5), LUNES + timedelta(days=6)) == 0
    assert au.dias_laborables(eq.t, LUNES, LUNES, medio_dia=True) == 0.5
    nucleo.anadir_festivo(eq.t, iso(LUNES + timedelta(days=2)), "Fiesta local")
    assert au.dias_laborables(eq.t, LUNES, LUNES + timedelta(days=6)) == 4, "los festivos del despacho no cuentan"

def test_pedir_aprobar_y_gastar_saldo(eq):
    aid = au.solicitar(eq.t, eq.ana, "vacaciones", iso(LUNES), iso(LUNES + timedelta(days=4)), motivo="Semana de descanso")
    a = au.obtener(eq.t, aid)
    assert (a["estado"], a["dias"], a["persona"] == "ana-au@ejemplo.com") == ("pendiente", 5.0, True)
    assert au.saldo(eq.t, eq.ana, ANIO) == {"anio": ANIO, "total": 22.0, "aprobadas": 0.0, "pendientes": 5.0, "disponibles": 17.0}
    assert [n["tipo"] for n in db.listar_notificaciones(eq.gestora, 5)] == ["ausencia"], "avisa a quien gestiona"
    assert db.listar_notificaciones(eq.beto, 5) == [], "y solo a quien gestiona"
    au.resolver(eq.t, eq.gestora, aid, True, "Que descanses")
    assert au.obtener(eq.t, aid)["estado"] == "aprobada" and au.saldo(eq.t, eq.ana, ANIO)["aprobadas"] == 5.0
    assert "Ausencia aprobada" in [n["titulo"] for n in db.listar_notificaciones(eq.ana, 5)]
    with pytest.raises(ValueError, match="ya está resuelta"):
        au.resolver(eq.t, eq.gestora, aid, False)


def test_sin_saldo_no_se_puede_pedir_pero_un_permiso_si(eq):
    au.fijar_dias_anuales(eq.t, 3)
    with pytest.raises(ValueError, match="No te quedan días"):
        au.solicitar(eq.t, eq.ana, "vacaciones", iso(LUNES), iso(LUNES + timedelta(days=4)))
    au.solicitar(eq.t, eq.ana, "permiso", iso(LUNES), iso(LUNES + timedelta(days=4)), motivo="Mudanza")
    assert au.saldo(eq.t, eq.ana, ANIO)["disponibles"] == 3.0, "los permisos no gastan vacaciones"
    au.fijar_saldo(eq.t, eq.beto, ANIO, 10)
    assert au.saldo(eq.t, eq.beto, ANIO)["total"] == 10.0 and au.saldo(eq.t, eq.ana, ANIO)["total"] == 3.0
    au.fijar_saldo(eq.t, eq.beto, ANIO, None)
    assert au.saldo(eq.t, eq.beto, ANIO)["total"] == 3.0


def test_validaciones(eq):
    for args, texto in (
        (("vacaciones", "ayer"), "fecha válida"), (("viaje", iso(LUNES)), "tipo"),
        (("vacaciones", iso(LUNES), iso(LUNES - timedelta(days=1))), "anterior"),
        (("vacaciones", iso(LUNES + timedelta(days=5)), iso(LUNES + timedelta(days=6))), "ningún día laborable"),
        (("vacaciones", f"{ANIO}-12-30", f"{ANIO + 1}-01-03"), "cruzar de año")):
        with pytest.raises(ValueError, match=texto):
            au.solicitar(eq.t, eq.ana, *args)
    with pytest.raises(ValueError, match="medio día"):
        au.solicitar(eq.t, eq.ana, "vacaciones", iso(LUNES), iso(LUNES + timedelta(days=1)), medio_dia=True)


def test_no_se_solapan_dos_ausencias_vivas_pero_si_tras_cancelar_o_rechazar(eq):
    aid = au.solicitar(eq.t, eq.ana, "vacaciones", iso(LUNES), iso(LUNES + timedelta(days=2)))
    with pytest.raises(ValueError, match="se solapa"):
        au.solicitar(eq.t, eq.ana, "permiso", iso(LUNES + timedelta(days=2)), iso(LUNES + timedelta(days=3)))
    au.solicitar(eq.t, eq.beto, "vacaciones", iso(LUNES), iso(LUNES + timedelta(days=2)))      # otra persona, sin problema
    au.resolver(eq.t, eq.gestora, aid, False, "Esa semana no")
    au.solicitar(eq.t, eq.ana, "permiso", iso(LUNES + timedelta(days=2)), iso(LUNES + timedelta(days=3)))


def test_solo_gestiona_quien_debe(eq):
    aid = au.solicitar(eq.t, eq.ana, "vacaciones", iso(LUNES), iso(LUNES))
    with pytest.raises(ValueError, match="Solo quien gestiona"):
        au.resolver(eq.t, eq.beto, aid, True)
    with pytest.raises(ValueError, match="de otra persona"):
        au.cancelar(eq.t, eq.beto, aid)
    with pytest.raises(ValueError, match="Solo quien gestiona"):
        au.solicitar(eq.t, eq.ana, "baja", iso(LUNES + timedelta(days=7)), por=eq.beto)
    bid = au.solicitar(eq.t, eq.ana, "baja", iso(LUNES + timedelta(days=7)), por=eq.gestora)
    assert au.obtener(eq.t, bid)["estado"] == "aprobada", "lo que registra quien gestiona queda aprobado"
    assert "Se ha registrado una ausencia tuya" in [n["titulo"] for n in db.listar_notificaciones(eq.ana, 5)]


def test_cancelar(eq):
    aid = au.solicitar(eq.t, eq.ana, "vacaciones", iso(LUNES), iso(LUNES))
    au.resolver(eq.t, eq.gestora, aid, True)
    au.cancelar(eq.t, eq.ana, aid)
    assert au.obtener(eq.t, aid)["estado"] == "cancelada" and au.saldo(eq.t, eq.ana, ANIO)["aprobadas"] == 0
    assert "Ausencia cancelada" in [n["titulo"] for n in db.listar_notificaciones(eq.gestora, 5)]
    with pytest.raises(ValueError, match="ya no está activa"):
        au.cancelar(eq.t, eq.ana, aid)


def test_quien_falta_y_aislamiento_entre_despachos(eq):
    aid = au.solicitar(eq.t, eq.ana, "vacaciones", iso(LUNES), iso(LUNES + timedelta(days=1)))
    assert au.quien_falta(eq.t, LUNES) == []
    au.resolver(eq.t, eq.gestora, aid, True)
    assert [f["persona"] for f in au.quien_falta(eq.t, LUNES)] == ["ana-au@ejemplo.com"] and au.quien_falta(eq.t, LUNES + timedelta(days=2)) == []
    otro = db.crear_tenant("Otro despacho")
    assert au.obtener(otro, aid) is None and au.listar(otro) == []
    with pytest.raises(ValueError, match="No existe"):
        au.cancelar(otro, eq.ana, aid)
    with pytest.raises(ValueError, match="no pertenece"):
        au.solicitar(otro, eq.ana, "permiso", iso(LUNES))


# --- Pantallas -------------------------------------------------------------------------------------------------------------------------------------
from tests.conftest import iniciar_sesion_de_prueba  # noqa: E402


def _persona_en_sesion(cliente, email, gestor=False):
    t = db.crear_tenant("Despacho Web Ausencias " + email)
    u = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    db.asignar_tenant(u, t)
    if gestor:
        db.asignar_gestor_fichajes(u, True)
    return t, u


def test_la_persona_pide_y_ve_su_saldo(cliente):
    t, u = _persona_en_sesion(cliente, "pide-web@ejemplo.com")
    assert cliente.get("/fichaje/ausencias").status_code == 200
    r = cliente.post("/fichaje/ausencias/solicitar", data={"tipo": "vacaciones", "desde": iso(LUNES), "hasta": iso(LUNES + timedelta(days=4)), "motivo": "Playa"})
    assert r.status_code == 302 and "aviso=solicitada" in r.headers["Location"]
    pagina = cliente.get(f"/fichaje/ausencias?anio={ANIO}").get_data(as_text=True)
    assert "Playa" in pagina and "Pendiente" in pagina
    r = cliente.post("/fichaje/ausencias/solicitar", data={"tipo": "vacaciones", "desde": "mañana"})
    assert "error=" in r.headers["Location"]


def test_quien_no_gestiona_no_entra_a_la_pantalla_del_equipo(cliente):
    _persona_en_sesion(cliente, "no-gestiona-web@ejemplo.com")
    assert cliente.get("/fichaje/ausencias/equipo").status_code == 403
    assert cliente.post("/fichaje/ausencias/1/resolver", data={"decision": "aprobar"}).status_code == 403
    assert cliente.post("/fichaje/ausencias/ajustes", data={"dias_vacaciones": "30"}).status_code == 403


def test_quien_gestiona_aprueba_registra_y_ajusta(cliente):
    t, g_ = _persona_en_sesion(cliente, "gestiona-web@ejemplo.com", gestor=True)
    otra = db.crear_usuario_vinculado_a_kratos("otra-web@ejemplo.com", "k-otra-web"); db.asignar_tenant(otra, t)
    aid = au.solicitar(t, otra, "vacaciones", iso(LUNES), iso(LUNES + timedelta(days=1)))
    pagina = cliente.get("/fichaje/ausencias/equipo").get_data(as_text=True)
    assert "otra-web@ejemplo.com" in pagina and "Aprobar" in pagina
    assert cliente.post(f"/fichaje/ausencias/{aid}/resolver", data={"decision": "aprobar", "comentario": "Vale"}).status_code == 302
    assert au.obtener(t, aid)["estado"] == "aprobada"
    cliente.post("/fichaje/ausencias/registrar", data={"usuario_id": otra, "tipo": "baja", "desde": iso(LUNES + timedelta(days=7))})
    assert [a["tipo"] for a in au.listar(t, usuario_id=otra, estado="aprobada")].count("baja") == 1
    cliente.post("/fichaje/ausencias/ajustes", data={"dias_vacaciones": "30"})
    cliente.post("/fichaje/ausencias/ajustes", data={"usuario_id": otra, "anio": ANIO, "dias": "10"})
    assert au.dias_anuales(t) == 30 and au.saldo(t, otra, ANIO)["total"] == 10


def test_una_persona_no_cancela_la_de_otra_por_la_web(cliente):
    t, u = _persona_en_sesion(cliente, "cancela-web@ejemplo.com")
    otra = db.crear_usuario_vinculado_a_kratos("ajena-web@ejemplo.com", "k-ajena-web"); db.asignar_tenant(otra, t)
    aid = au.solicitar(t, otra, "permiso", iso(LUNES))
    r = cliente.post(f"/fichaje/ausencias/{aid}/cancelar")
    assert "error=" in r.headers["Location"] and au.obtener(t, aid)["estado"] == "pendiente"


# --- API ---------------------------------------------------------------------------------------------------------------------------------------
from tests.test_rutas_api import _auth, _registrar  # noqa: E402


def _con_token(cliente, email, tenant, gestor=False):
    datos = _registrar(cliente, email)
    u = db.obtener_usuario_por_email(email)["id"]
    db.asignar_tenant(u, tenant)
    if gestor:
        db.asignar_gestor_fichajes(u, True)
    return u, _auth(datos["token"])


def test_api_pedir_listar_saldo_y_cancelar(cliente):
    t = db.crear_tenant("Despacho API Ausencias")
    u, h = _con_token(cliente, "api-aus@ejemplo.com", t)
    r = cliente.post("/api/v1/fichaje/ausencias", headers=h, json={"tipo": "vacaciones", "desde": iso(LUNES), "hasta": iso(LUNES + timedelta(days=1)), "motivo": "Puente"})
    assert r.status_code == 201 and r.get_json()["data"]["estado"] == "pendiente" and r.get_json()["data"]["dias"] == 2
    aid = r.get_json()["data"]["id"]
    assert [a["id"] for a in cliente.get(f"/api/v1/fichaje/ausencias?anio={ANIO}", headers=h).get_json()["data"]] == [aid]
    assert cliente.get(f"/api/v1/fichaje/ausencias/saldo?anio={ANIO}", headers=h).get_json()["data"]["disponibles"] == 20
    malo = cliente.post("/api/v1/fichaje/ausencias", headers=h, json={"tipo": "vacaciones", "desde": "pronto"})
    assert malo.status_code == 400 and malo.get_json()["codigo"] == "ausencia_invalida"
    assert cliente.post(f"/api/v1/fichaje/ausencias/{aid}/cancelar", headers=h).get_json()["data"]["estado"] == "cancelada"
    assert cliente.post(f"/api/v1/fichaje/ausencias/{aid}/cancelar", headers=h).status_code == 400


def test_api_solo_gestiona_quien_debe(cliente):
    t = db.crear_tenant("Despacho API Gestion")
    u, h = _con_token(cliente, "api-pide@ejemplo.com", t)
    g_, hg = _con_token(cliente, "api-gestiona@ejemplo.com", t, gestor=True)
    aid = cliente.post("/api/v1/fichaje/ausencias", headers=h, json={"tipo": "permiso", "desde": iso(LUNES)}).get_json()["data"]["id"]
    assert cliente.get("/api/v1/fichaje/ausencias/equipo", headers=h).status_code == 403
    assert cliente.post(f"/api/v1/fichaje/ausencias/{aid}/resolver", headers=h, json={"decision": "aprobar"}).status_code == 403
    cola = cliente.get("/api/v1/fichaje/ausencias/equipo", headers=hg).get_json()["data"]
    assert [a["id"] for a in cola] == [aid] and cola[0]["persona"] == "api-pide@ejemplo.com"
    assert cliente.post(f"/api/v1/fichaje/ausencias/{aid}/resolver", headers=hg, json={"decision": "quizá"}).get_json()["codigo"] == "decision_invalida"
    r = cliente.post(f"/api/v1/fichaje/ausencias/{aid}/resolver", headers=hg, json={"decision": "rechazar", "comentario": "Hay inspección"})
    assert r.get_json()["data"]["estado"] == "rechazada" and r.get_json()["data"]["comentario"] == "Hay inspección"
    ya = cliente.post(f"/api/v1/fichaje/ausencias/{aid}/resolver", headers=hg, json={"decision": "aprobar"})
    assert ya.status_code == 409
    assert cliente.post("/api/v1/fichaje/ausencias", headers=hg, json={"tipo": "baja", "desde": iso(LUNES + timedelta(days=7)), "usuario_id": u}).get_json()["data"]["estado"] == "aprobada"
