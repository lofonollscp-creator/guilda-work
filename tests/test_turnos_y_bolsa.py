"""Cuadrante de turnos (app/turnos.py) y bolsa de horas (app/bolsa_horas.py)."""
from datetime import date, datetime, timedelta

import pytest

from app import ausencias as au, bolsa_horas as bh, db, turnos as tu

LUNES = date.today() + timedelta(days=60)
while LUNES.weekday() != 0:
    LUNES += timedelta(days=1)


def iso(d):
    return d.isoformat()


@pytest.fixture
def eq(usuario_id):
    t = db.crear_tenant("Despacho Turnos")
    class E: pass
    e = E(); e.t = t
    def u(mail, gestor=False):
        x = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail); db.asignar_tenant(x, t)
        if gestor:
            db.asignar_gestor_fichajes(x, True)
        return x
    e.ana = u("ana-tu@ejemplo.com"); e.beto = u("beto-tu@ejemplo.com"); e.g = u("gestora-tu@ejemplo.com", True)
    return e


# --- Turnos ----------------------------------------------------------------------------------------------------------------------------------
def test_tipos_de_turno(eq):
    m = tu.crear_tipo(eq.t, eq.g, "Mañana", "8:00", "15:00", "#ff0000")
    n = tu.crear_tipo(eq.t, eq.g, "Noche", "22:00", "06:00")
    assert [t["nombre"] for t in tu.listar_tipos(eq.t)] == ["Mañana", "Noche"] and {t["nombre"]: t["horas"] for t in tu.listar_tipos(eq.t)} == {"Mañana": 7.0, "Noche": 8.0}
    assert tu.listar_tipos(eq.t)[1]["color"] == "#6c8cff", "un color no válido cae al de por defecto"
    with pytest.raises(ValueError, match="Ya hay un turno"):
        tu.crear_tipo(eq.t, eq.g, "mañana", "09:00", "10:00")
    for args, texto in ((("", "08:00", "09:00"), "nombre"), (("X", "25:00", "09:00"), "hora válida"), (("X", "08:00", "08:00"), "misma hora")):
        with pytest.raises(ValueError, match=texto):
            tu.crear_tipo(eq.t, eq.g, *args)
    with pytest.raises(ValueError, match="Solo quien gestiona"):
        tu.crear_tipo(eq.t, eq.ana, "Tarde", "15:00", "22:00")
    assert m and n


def test_asignar_sustituir_quitar_y_avisar(eq):
    m = tu.crear_tipo(eq.t, eq.g, "Mañana", "08:00", "15:00"); tarde = tu.crear_tipo(eq.t, eq.g, "Tarde", "15:00", "22:00")
    assert tu.asignar(eq.t, eq.g, eq.ana, iso(LUNES), m) is True
    assert tu.asignar(eq.t, eq.g, eq.ana, iso(LUNES), m) is False, "sin cambios, no hay aviso"
    assert [n["tipo"] for n in db.listar_notificaciones(eq.ana, 5)] == ["turno"]
    tu.asignar(eq.t, eq.g, eq.ana, iso(LUNES), tarde)
    assert [x["nombre"] for x in tu.mis_turnos(eq.t, eq.ana, iso(LUNES))] == ["Tarde"], "un turno por día: el nuevo sustituye"
    assert tu.asignar(eq.t, eq.g, eq.ana, iso(LUNES), None) is True and tu.mis_turnos(eq.t, eq.ana, iso(LUNES)) == []
    with pytest.raises(ValueError, match="no existe"):
        tu.asignar(eq.t, eq.g, eq.ana, iso(LUNES), 9999)
    with pytest.raises(ValueError, match="Solo quien gestiona"):
        tu.asignar(eq.t, eq.beto, eq.ana, iso(LUNES), m)


def test_el_cuadrante_junta_turnos_y_ausencias_y_las_ausencias_mandan(eq):
    m = tu.crear_tipo(eq.t, eq.g, "Mañana", "08:00", "15:00")
    tu.asignar(eq.t, eq.g, eq.ana, iso(LUNES), m); tu.asignar(eq.t, eq.g, eq.ana, iso(LUNES + timedelta(days=1)), m)
    aid = au.solicitar(eq.t, eq.ana, "permiso", iso(LUNES + timedelta(days=1)))
    au.resolver(eq.t, eq.g, aid, True)
    assert [x["fecha"] for x in tu.mis_turnos(eq.t, eq.ana, iso(LUNES), iso(LUNES + timedelta(days=6)))] == [iso(LUNES)], "al aprobar la ausencia se quita el turno de ese día"
    with pytest.raises(ValueError, match="ausencia aprobada"):
        tu.asignar(eq.t, eq.g, eq.ana, iso(LUNES + timedelta(days=1)), m)
    c = tu.cuadrante(eq.t, iso(LUNES), iso(LUNES + timedelta(days=2)))
    ana = next(p for p in c["personas"] if p["usuario_id"] == eq.ana)
    assert ana["dias"][iso(LUNES)]["nombre"] == "Mañana" and ana["dias"][iso(LUNES + timedelta(days=1))] == {"ausencia": "permiso"} and iso(LUNES + timedelta(days=2)) not in ana["dias"]
    assert len(c["personas"]) == 3 and len(c["dias"]) == 3


def test_semana_y_copiar_semana(eq):
    m = tu.crear_tipo(eq.t, eq.g, "Mañana", "08:00", "15:00"); t = tu.crear_tipo(eq.t, eq.g, "Tarde", "15:00", "22:00")
    n = tu.asignar_semana(eq.t, eq.g, eq.ana, iso(LUNES), {iso(LUNES + timedelta(days=i)): (m if i < 3 else t) for i in range(5)})
    assert n == 5 and len(db.listar_notificaciones(eq.ana, 10)) == 1, "un solo aviso con lo cambiado"
    sig = LUNES + timedelta(days=7)
    assert tu.copiar_semana(eq.t, eq.g, iso(LUNES), iso(sig)) == 5
    assert [x["nombre"] for x in tu.mis_turnos(eq.t, eq.ana, iso(sig), iso(sig + timedelta(days=4)))] == ["Mañana"] * 3 + ["Tarde"] * 2
    assert tu.copiar_semana(eq.t, eq.g, iso(LUNES), iso(sig)) == 0, "sin sobrescribir, lo ya asignado se respeta"
    with pytest.raises(ValueError, match="lunes"):
        tu.copiar_semana(eq.t, eq.g, iso(LUNES + timedelta(days=1)), iso(sig))
    with pytest.raises(ValueError, match="distintas"):
        tu.copiar_semana(eq.t, eq.g, iso(LUNES), iso(LUNES))


def test_archivar_un_turno_quita_los_futuros(eq):
    m = tu.crear_tipo(eq.t, eq.g, "Mañana", "08:00", "15:00")
    tu.asignar(eq.t, eq.g, eq.ana, iso(LUNES), m)
    tu.archivar_tipo(eq.t, eq.g, m)
    assert tu.listar_tipos(eq.t) == [] and len(tu.listar_tipos(eq.t, incluir_archivados=True)) == 1 and tu.mis_turnos(eq.t, eq.ana, iso(LUNES)) == []
    with pytest.raises(ValueError, match="archivado"):
        tu.asignar(eq.t, eq.g, eq.ana, iso(LUNES), m)


def test_un_despacho_no_toca_los_turnos_de_otro(eq):
    otro = db.crear_tenant("Otro Despacho Turnos")
    m = tu.crear_tipo(eq.t, eq.g, "Mañana", "08:00", "15:00")
    with pytest.raises(ValueError, match="Solo quien gestiona"):
        tu.asignar(otro, eq.g, eq.ana, iso(LUNES), m)
    assert tu.listar_tipos(otro) == [] and tu.cuadrante(otro, iso(LUNES))["personas"] == []


# --- Bolsa de horas ----------------------------------------------------------------------------------------------------------------------------
def _ficha(u, t, dia: date, entrada="09:00", salida="17:00"):
    """Un fichaje de entrada y salida ese día (directo en la tabla: el registro real es solo-inserción)."""
    conn = db.get_connection()
    for tipo, hora in (("entrada", entrada), ("salida", salida)):
        conn.execute("INSERT INTO fichajes (usuario_id, tenant_id, tipo, marca_tiempo, origen, creado_por, creado_en) VALUES (?, ?, ?, ?, 'web', ?, ?)",
                     (u, t, tipo, f"{iso(dia)}T{hora}:00", u, db.now_iso()))
    conn.commit(); conn.close()


HOY = date(2026, 3, 18)             # miércoles
LUN, MAR, MIE = date(2026, 3, 16), date(2026, 3, 17), date(2026, 3, 18)


def test_la_bolsa_compara_lo_trabajado_con_lo_que_tocaba(eq):
    db.guardar_fichaje_datos(eq.ana, nombre_completo="Ana", dni_nie="1X", jornada_semanal_horas=40)
    _ficha(eq.ana, eq.t, LUN, "09:00", "18:00"); _ficha(eq.ana, eq.t, MAR, "09:00", "16:00")      # 9 h y 7 h; tocaba 8 + 8
    b = bh.calcular(eq.t, eq.ana, "2026-03-16", None, hoy=HOY)
    assert (b["desde"], b["hasta"], b["dias_laborables"]) == ("2026-03-16", "2026-03-17", 2)
    assert (b["esperado_seg"], b["trabajado_seg"], b["saldo_seg"]) == (16 * 3600, 16 * 3600, 0)
    _ficha(eq.ana, eq.t, MIE, "09:00", "19:00")
    b = bh.calcular(eq.t, eq.ana, "2026-03-16", "2026-03-18", hoy=HOY)
    assert b["saldo_seg"] == 2 * 3600 and bh.texto_horas(b["saldo_seg"], True) == "+2 h 00 min" and bh.texto_horas(-4500, True) == "−1 h 15 min"
    assert [m["mes"] for m in b["por_mes"]] == ["2026-03"] and b["por_mes"][0]["saldo_seg"] == 2 * 3600


def test_las_ausencias_aprobadas_no_se_esperan_y_el_medio_dia_cuenta_la_mitad(eq):
    db.guardar_fichaje_datos(eq.ana, nombre_completo="Ana", dni_nie="1X", jornada_semanal_horas=40)
    a = au.solicitar(eq.t, eq.ana, "permiso", iso(MAR), motivo="Médico"); au.resolver(eq.t, eq.g, a, True)
    m = au.solicitar(eq.t, eq.ana, "asuntos_propios", iso(MIE), medio_dia=True); au.resolver(eq.t, eq.g, m, True)
    pendiente = au.solicitar(eq.t, eq.ana, "vacaciones", iso(LUN)); assert pendiente           # sin aprobar no cuenta
    b = bh.calcular(eq.t, eq.ana, "2026-03-16", "2026-03-18", hoy=HOY)
    assert b["dias_justificados"] == 1.5 and b["esperado_seg"] == (8 + 0 + 4) * 3600 and b["saldo_seg"] == -12 * 3600


def test_sin_jornada_no_hay_bolsa_y_los_ajustes_suman(eq):
    _ficha(eq.ana, eq.t, LUN)
    b = bh.calcular(eq.t, eq.ana, "2026-03-16", "2026-03-17", hoy=HOY)
    assert b["sin_jornada"] is True and b["saldo_seg"] is None and b["trabajado_seg"] == 8 * 3600
    db.guardar_fichaje_datos(eq.beto, nombre_completo="Beto", dni_nie="2X", jornada_semanal_horas=40)
    bh.anadir_ajuste(eq.t, eq.g, eq.beto, 90, "Horas extra del cierre", fecha=iso(LUN))
    bh.anadir_ajuste(eq.t, eq.g, eq.beto, -30, "Tarde libre", fecha=iso(MAR))
    assert bh.calcular(eq.t, eq.beto, "2026-03-16", "2026-03-17", hoy=HOY)["ajustes_seg"] == 3600
    assert [a["motivo"] for a in bh.listar_ajustes(eq.t, eq.beto)] == ["Tarde libre", "Horas extra del cierre"]
    assert "Ajuste en tu bolsa de horas" in [n["titulo"] for n in db.listar_notificaciones(eq.beto, 5)]
    for args, texto in (((0, "x"), "distinto de cero"), ((10, ""), "motivo"), (("abc", "x"), "minutos")):
        with pytest.raises(ValueError, match=texto):
            bh.anadir_ajuste(eq.t, eq.g, eq.beto, *args)
    with pytest.raises(ValueError, match="Solo quien gestiona"):
        bh.anadir_ajuste(eq.t, eq.ana, eq.beto, 10, "x")


def test_resumen_del_equipo_ordena_por_quien_mas_debe(eq):
    for u, h in ((eq.ana, 9), (eq.beto, 7)):
        db.guardar_fichaje_datos(u, nombre_completo=str(u), dni_nie=f"{u}X", jornada_semanal_horas=40)
        _ficha(u, eq.t, LUN, "09:00", f"{9 + h - 1:02d}:00")
    r = bh.resumen_equipo(eq.t, "2026-03-16", "2026-03-16", hoy=HOY)
    assert [x["usuario_id"] for x in r][:2] == [eq.beto, eq.ana] and r[-1]["sin_jornada"] is True


# --- Pantallas ---------------------------------------------------------------------------------------------------------------------------------
from tests.conftest import iniciar_sesion_de_prueba  # noqa: E402


def _en_sesion(cliente, email, gestor=False):
    t = db.crear_tenant("Despacho Web Turnos " + email)
    u = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    db.asignar_tenant(u, t)
    if gestor:
        db.asignar_gestor_fichajes(u, True)
    return t, u


def test_la_gestora_organiza_turnos_por_la_web_y_el_equipo_los_ve(cliente):
    t, g_ = _en_sesion(cliente, "gestora-web-tu@ejemplo.com", gestor=True)
    otra = db.crear_usuario_vinculado_a_kratos("otra-web-tu@ejemplo.com", "k-otra-web-tu"); db.asignar_tenant(otra, t)
    r = cliente.post("/fichaje/turnos/tipos", data={"nombre": "Mañana", "inicio": "08:00", "fin": "15:00", "color": "#00aa00"})
    assert r.status_code == 302 and "aviso=tipo-creado" in r.headers["Location"]
    tid = tu.listar_tipos(t)[0]["id"]
    r = cliente.post("/fichaje/turnos/semana", data={"usuario_id": otra, "lunes": iso(LUNES), f"t_{iso(LUNES)}": tid, f"t_{iso(LUNES + timedelta(days=1))}": ""})
    assert "aviso=guardado-1" in r.headers["Location"]
    pagina = cliente.get(f"/fichaje/turnos?semana={iso(LUNES)}").get_data(as_text=True)
    assert "Mañana" in pagina and "otra-web-tu@ejemplo.com" in pagina and "Copiar una semana" in pagina
    assert "error=" in cliente.post("/fichaje/turnos/semana", data={"usuario_id": otra, "lunes": iso(LUNES), f"t_{iso(LUNES)}": 9999}).headers["Location"]


def test_quien_no_gestiona_ve_el_cuadrante_pero_no_lo_cambia(cliente):
    t, u = _en_sesion(cliente, "no-gestiona-web-tu@ejemplo.com")
    assert cliente.get("/fichaje/turnos").status_code == 200
    assert "Copiar una semana" not in cliente.get("/fichaje/turnos").get_data(as_text=True)
    r = cliente.post("/fichaje/turnos/tipos", data={"nombre": "X", "inicio": "08:00", "fin": "09:00"})
    assert "error=" in r.headers["Location"] and tu.listar_tipos(t) == []


def test_la_bolsa_por_la_web(cliente):
    t, u = _en_sesion(cliente, "bolsa-web@ejemplo.com", gestor=True)
    db.guardar_fichaje_datos(u, nombre_completo="Gestora", dni_nie="9X", jornada_semanal_horas=40)
    assert cliente.get("/fichaje/bolsa").status_code == 200
    assert cliente.get("/fichaje/bolsa?desde=2026-01-01&hasta=2026-01-31").status_code == 200
    assert "error=" not in cliente.post("/fichaje/bolsa/ajustes", data={"usuario_id": u, "sentido": "sumar", "horas": "1,5", "motivo": "Cierre"}).headers["Location"]
    assert [a["minutos"] for a in bh.listar_ajustes(t, u)] == [90]
    assert "error=" in cliente.post("/fichaje/bolsa/ajustes", data={"usuario_id": u, "sentido": "restar", "horas": "1", "motivo": ""}).headers["Location"]
    assert "Bolsa del equipo" in cliente.get("/fichaje/bolsa").get_data(as_text=True)


# --- API ---------------------------------------------------------------------------------------------------------------------------------------
from tests.test_rutas_api import _auth, _registrar  # noqa: E402


def _tok(cliente, email, t, gestor=False):
    d = _registrar(cliente, email); u = db.obtener_usuario_por_email(email)["id"]
    db.asignar_tenant(u, t)
    if gestor:
        db.asignar_gestor_fichajes(u, True)
    return u, _auth(d["token"])


def test_api_turnos_y_bolsa(cliente):
    t = db.crear_tenant("Despacho API Turnos")
    u, h = _tok(cliente, "api-tu@ejemplo.com", t); g_, hg = _tok(cliente, "api-tu-gestora@ejemplo.com", t, gestor=True)
    assert cliente.post("/api/v1/fichaje/turnos/tipos", headers=h, json={"nombre": "X", "inicio": "08:00", "fin": "09:00"}).status_code == 403
    r = cliente.post("/api/v1/fichaje/turnos/tipos", headers=hg, json={"nombre": "Mañana", "inicio": "08:00", "fin": "15:00"})
    assert r.status_code == 201 and r.get_json()["data"]["horas"] == 7.0
    tid = r.get_json()["data"]["id"]
    assert cliente.post("/api/v1/fichaje/turnos/tipos", headers=hg, json={"nombre": "Mañana", "inicio": "08:00", "fin": "15:00"}).get_json()["codigo"] == "turno_invalido"
    assert cliente.post("/api/v1/fichaje/turnos/asignar", headers=hg, json={"usuario_id": u, "fecha": iso(LUNES), "turno_id": tid}).get_json()["data"] == {"cambiado": True}
    assert cliente.post("/api/v1/fichaje/turnos/asignar", headers=h, json={"usuario_id": u, "fecha": iso(LUNES), "turno_id": None}).status_code == 403
    assert [x["nombre"] for x in cliente.get(f"/api/v1/fichaje/turnos?desde={iso(LUNES)}&hasta={iso(LUNES)}", headers=h).get_json()["data"]] == ["Mañana"]
    c = cliente.get(f"/api/v1/fichaje/turnos/cuadrante?desde={iso(LUNES)}&hasta={iso(LUNES + timedelta(days=1))}", headers=h).get_json()["data"]
    assert len(c["dias"]) == 2 and {p["usuario_id"] for p in c["personas"]} == {u, g_}
    assert cliente.get("/api/v1/fichaje/turnos/cuadrante?desde=2026-01-01&hasta=2027-12-31", headers=h).get_json()["codigo"] == "rango_invalido"
    assert [x["nombre"] for x in cliente.get("/api/v1/fichaje/turnos/tipos", headers=h).get_json()["data"]] == ["Mañana"]
    # bolsa
    b = cliente.get("/api/v1/fichaje/bolsa-horas?desde=2026-03-16&hasta=2026-03-17", headers=h).get_json()["data"]
    assert b["sin_jornada"] is True and b["saldo_seg"] is None
    assert cliente.get("/api/v1/fichaje/bolsa-horas/equipo", headers=h).status_code == 403
    assert cliente.post("/api/v1/fichaje/bolsa-horas/ajustes", headers=hg, json={"usuario_id": u, "minutos": 60, "motivo": "Cierre"}).status_code == 201
    assert cliente.post("/api/v1/fichaje/bolsa-horas/ajustes", headers=hg, json={"usuario_id": u, "minutos": 0, "motivo": "x"}).get_json()["codigo"] == "ajuste_invalido"
    assert len(cliente.get("/api/v1/fichaje/bolsa-horas/equipo", headers=hg).get_json()["data"]) == 2


def test_por_defecto_la_bolsa_empieza_en_el_primer_fichaje(eq):
    db.guardar_fichaje_datos(eq.ana, nombre_completo="Ana", dni_nie="1X", jornada_semanal_horas=40)
    hoy = date.today()
    sin = bh.calcular(eq.t, eq.ana, hoy=hoy)
    assert sin["dias_laborables"] == 0 and sin["saldo_seg"] == 0, "sin ningún fichaje no hay nada que contar"
    hace = hoy - timedelta(days=10)
    _ficha(eq.ana, eq.t, hace, "09:00", "17:00")
    b = bh.calcular(eq.t, eq.ana, hoy=hoy)
    assert b["desde"] == max(date(hoy.year, 1, 1), hace).isoformat() and b["trabajado_seg"] == 8 * 3600


def test_borrar_un_despacho_con_ausencias_turnos_y_bolsa_no_se_bloquea(eq):
    m = tu.crear_tipo(eq.t, eq.g, "Mañana", "08:00", "15:00")
    tu.asignar(eq.t, eq.g, eq.ana, iso(LUNES), m)
    au.solicitar(eq.t, eq.ana, "permiso", iso(LUNES + timedelta(days=1)))
    bh.anadir_ajuste(eq.t, eq.g, eq.ana, 30, "Cierre")
    db.borrar_tenant(eq.t)
    conn = db.get_connection()
    try:
        for tabla in ("ausencias", "turnos_tipos", "turnos_asignados", "bolsa_horas_ajustes"):
            assert conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0] == 0, tabla
    finally:
        conn.close()
