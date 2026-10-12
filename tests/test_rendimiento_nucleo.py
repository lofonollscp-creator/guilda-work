"""Rendimiento del núcleo con datos grandes: se vigila que no vuelva lo que `scripts/probar.sh --perfil` encontró (un calendario recalculado en cada fila de plazos
y subconsultas sin índice)."""
from datetime import date, timedelta

from app import db, nucleo


def _despacho():
    t = db.crear_tenant("Despacho Grande")
    u = db.crear_usuario_vinculado_a_kratos("grande@ejemplo.com", "kratos-grande")
    db.asignar_tenant(u, t)
    return t, u


def test_listar_plazos_calcula_el_calendario_una_vez_por_tipo_no_por_fila(usuario_id, monkeypatch):
    t, u = _despacho()
    c = nucleo.crear_cliente(t, "Cliente")
    x = nucleo.crear_expediente(t, u, c, "Asunto")
    for i in range(60):
        nucleo.crear_plazo(t, u, f"Plazo {i}", (date.today() + timedelta(days=i + 1)).isoformat(), expediente_id=x, supervisor=True)
    llamadas = []
    original = nucleo.calendario_del_despacho
    monkeypatch.setattr(nucleo, "calendario_del_despacho", lambda *a, **k: llamadas.append(a) or original(*a, **k))
    assert len(nucleo.listar_plazos(t, u, True, estado="abiertos")) == 60
    assert len(llamadas) == 1, f"el calendario se calculó {len(llamadas)} veces para 60 plazos"


def test_las_subconsultas_por_expediente_tienen_indice(usuario_id):
    conn = db.get_connection()
    try:
        nombres = {f[0] for f in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        plan = " ".join(str(f[3]) for f in conn.execute("EXPLAIN QUERY PLAN SELECT MIN(fecha_limite) FROM plazos z WHERE z.expediente_id = 1 AND z.estado = 'pendiente' AND z.papelera_en IS NULL"))
    finally:
        conn.close()
    assert {"idx_plazos_expediente", "idx_partes_expediente"} <= nombres and "idx_plazos_expediente" in plan
