"""Herramientas de IA y MCP de ausencias, turnos y bolsa de horas: mismas reglas que las pantallas (la IA nunca puede más que la persona)."""
from datetime import date, timedelta

import pytest

import mcp_tools
from app import db, herramientas_grupos as hg, ia_herramientas as ih

LECTURA = ("listar_mis_ausencias", "saldo_vacaciones", "listar_ausencias_equipo", "ver_mis_turnos", "ver_cuadrante", "ver_bolsa_de_horas")
ESCRITURA = ("pedir_ausencia", "cancelar_ausencia", "resolver_ausencia", "asignar_turno", "ajustar_bolsa_de_horas")
LUNES = date.today() + timedelta(days=90)
while LUNES.weekday() != 0:
    LUNES += timedelta(days=1)


def test_estan_registradas_en_su_grupo_y_la_escritura_pide_confirmacion():
    for n in LECTURA:
        assert n in ih.LECTURA and not ih.necesita_confirmacion(n, modo_autonomo=False)
    for n in ESCRITURA:
        assert n in ih.ESCRITURA and ih.necesita_confirmacion(n, modo_autonomo=False)
    for n in LECTURA + ESCRITURA:
        assert hg.grupo_de(n) == "fichaje" and any(t.__name__ == n for t in mcp_tools.TOOLS)


@pytest.fixture
def eq(usuario_id):
    t = db.crear_tenant("Despacho IA Ausencias")
    def u(mail, gestor=False):
        x = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail); db.asignar_tenant(x, t)
        if gestor:
            db.asignar_gestor_fichajes(x, True)
        return x
    class E: pass
    e = E(); e.t = t; e.ana = u("ana-ia-au@ejemplo.com"); e.g = u("gestora-ia-au@ejemplo.com", True)
    return e


def test_la_persona_pide_consulta_y_cancela_con_la_ia(eq):
    r = ih.ejecutar(eq.ana, "pedir_ausencia", {"tipo": "vacaciones", "desde": LUNES.isoformat(), "hasta": (LUNES + timedelta(days=2)).isoformat()})
    assert (r["estado"], r["dias"]) == ("pendiente", 3.0)
    assert ih.ejecutar(eq.ana, "saldo_vacaciones", {"anio": LUNES.year})["pendientes"] == 3.0
    assert [a["id"] for a in ih.ejecutar(eq.ana, "listar_mis_ausencias", {})] == [r["id"]]
    assert ih.ejecutar(eq.ana, "cancelar_ausencia", {"ausencia_id": r["id"]})["estado"] == "cancelada"


def test_gestionar_solo_lo_hace_quien_gestiona(eq):
    r = ih.ejecutar(eq.ana, "pedir_ausencia", {"tipo": "permiso", "desde": LUNES.isoformat()})
    for nombre, args in (("listar_ausencias_equipo", {}), ("resolver_ausencia", {"ausencia_id": r["id"], "decision": "aprobar"}), ("asignar_turno", {"usuario_id": eq.ana, "fecha": LUNES.isoformat()}),
                         ("ajustar_bolsa_de_horas", {"usuario_id": eq.ana, "minutos": 30, "motivo": "x"}), ("ver_bolsa_de_horas", {"usuario_id": eq.g})):
        with pytest.raises(ih.ErrorHerramientaIA, match="[Ss]olo quien gestiona"):
            ih.ejecutar(eq.ana, nombre, args)
    assert [a["persona"] for a in ih.ejecutar(eq.g, "listar_ausencias_equipo", {})] == ["ana-ia-au@ejemplo.com"]
    assert ih.ejecutar(eq.g, "resolver_ausencia", {"ausencia_id": r["id"], "decision": "aprobar", "comentario": "Vale"})["estado"] == "aprobada"
    with pytest.raises(ih.ErrorHerramientaIA, match="decision"):
        ih.ejecutar(eq.g, "resolver_ausencia", {"ausencia_id": r["id"], "decision": "quizá"})


def test_turnos_y_bolsa_con_la_ia(eq):
    from app import turnos
    tid = turnos.crear_tipo(eq.t, eq.g, "Mañana", "08:00", "15:00")
    assert ih.ejecutar(eq.g, "asignar_turno", {"usuario_id": eq.ana, "fecha": LUNES.isoformat(), "turno_id": tid}) == {"cambiado": True}
    assert [x["nombre"] for x in ih.ejecutar(eq.ana, "ver_mis_turnos", {"desde": LUNES.isoformat(), "hasta": LUNES.isoformat()})] == ["Mañana"]
    c = ih.ejecutar(eq.ana, "ver_cuadrante", {"desde": LUNES.isoformat(), "hasta": LUNES.isoformat()})
    assert len(c["personas"]) == 2
    assert "id" in ih.ejecutar(eq.g, "ajustar_bolsa_de_horas", {"usuario_id": eq.ana, "minutos": 45, "motivo": "Cierre"})
    b = ih.ejecutar(eq.g, "ver_bolsa_de_horas", {"usuario_id": eq.ana, "desde": "2026-01-05", "hasta": "2026-01-09"})
    assert b["usuario_id"] == eq.ana and b["sin_jornada"] is True
    assert ih.ejecutar(eq.ana, "ver_bolsa_de_horas", {"desde": "2026-01-05", "hasta": "2026-01-09"})["usuario_id"] == eq.ana


def test_sin_despacho_dan_error_legible(usuario_id):
    with pytest.raises(ih.ErrorHerramientaIA, match="despacho"):
        ih.ejecutar(usuario_id, "ver_cuadrante", {})
