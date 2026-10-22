"""El panel fiscal calcula sus indicadores en SQL (no carga todos los vencimientos en Python). Estos tests comparan sus cifras con un cálculo de referencia hecho a mano sobre todas las filas, con y sin restricción de clientes."""
import itertools
import random
import time
from datetime import date, timedelta

import pytest

from app import acceso, db, obligaciones, panel_fiscal

FASES = ("pendiente", "en_preparacion", "en_revision", "aprobada", "presentada", "cerrada", "no_aplica", "anulada")


def _montar(n_clientes=40, n_venc=600):
    random.seed(5)
    t = db.crear_tenant("Despacho panel rendimiento")
    us = []
    for i in range(3):
        u = db.crear_usuario_vinculado_a_kratos(f"pr{i}@ejemplo.com", f"k-pr{i}")
        db.asignar_tenant(u, t)
        us.append(u)
    db.asignar_supervisor_tenant(us[0], True)
    clientes = [db.crear_cliente_fiscal(t, f"Cliente {i}", email=f"c{i}@cli.com") for i in range(n_clientes)]
    conn = db.get_connection()
    for c in clientes[::4]:
        conn.execute("UPDATE clientes_fiscales SET responsable_id = ? WHERE id = ?", (random.choice(us), c))
    conn.execute("UPDATE clientes_fiscales SET papelera_en = '2026-01-01T00:00:00' WHERE id = ?", (clientes[1],))        # un cliente en la papelera: sus vencimientos no cuentan
    hoy = date.today()
    combos = list(itertools.product(clientes, ["303", "130", "111", "115", "390"], [f"{a}-{q}T" for a in (2025, 2026) for q in (1, 2, 3, 4)]))
    random.shuffle(combos)
    ids = []
    for c, mod, per in combos[:n_venc]:
        fase = random.choice(FASES)
        cur = conn.execute(
            "INSERT INTO vencimientos_fiscales (tenant_id, cliente_fiscal_id, usuario_id, modelo, periodo, fecha_limite, estado, fase, bloqueada, presentada_tarde, creado_en, papelera_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (t, c, random.choice(us), mod, per, (hoy + timedelta(days=random.randint(-140, 40))).isoformat() + random.choice(["", "T10:00:00"]), "presentado" if fase in obligaciones.PRESENTADAS else "pendiente",
             fase, random.choice([0, 0, 1]), random.choice([0, 0, 1]), "2026-01-01T00:00:00", random.choice([None] * 30 + ["2026-02-01T00:00:00"])))
        ids.append((cur.lastrowid, fase))
    for vid, fase in ids:
        if fase in obligaciones.PRESENTADAS and random.random() < 0.4:
            conn.execute("INSERT INTO obligaciones_evidencias (tenant_id, vencimiento_id, presentado_en, creado_en) VALUES (?, ?, '2026-02-01', '2026-02-01T00:00:00')", (t, vid))
    conn.commit()
    conn.close()
    return t, us, clientes


def _referencia(t, visibles, hoy):
    """Lo mismo que hacía el panel antes: cargar todas las filas y contar en Python."""
    conn = db.get_connection()
    filtro, p = ("", [])
    if visibles is not None:
        filtro, p = f" AND v.cliente_fiscal_id IN ({','.join('?' * len(visibles)) or 'NULL'})", list(visibles)
    filas = conn.execute("SELECT v.id, v.fase, v.presentada_tarde, substr(v.fecha_limite, 1, 10) AS limite, v.bloqueada FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id "
                         "WHERE v.tenant_id = ? AND v.papelera_en IS NULL AND c.papelera_en IS NULL" + filtro, [t, *p]).fetchall()
    ids_pres = [f["id"] for f in filas if f["fase"] in obligaciones.PRESENTADAS]
    con = {r[0] for r in conn.execute("SELECT DISTINCT vencimiento_id FROM obligaciones_evidencias")}
    conn.close()
    desde, hoy_s = (hoy - timedelta(days=panel_fiscal.DIAS_INDICADOR)).isoformat(), hoy.isoformat()
    periodo = [f for f in filas if desde <= f["limite"] < hoy_s]
    aplicables = [f for f in periodo if f["fase"] not in ("no_aplica", "anulada")]
    buenas = [f for f in aplicables if f["fase"] in obligaciones.PRESENTADAS and not f["presentada_tarde"]]
    activas = [f for f in filas if f["fase"] in obligaciones.ACTIVAS]
    return {"n": len(aplicables), "buenas": len(buenas), "excluidas": len(periodo) - len(aplicables),
            "sin_evidencia": {"n": len(ids_pres), "sin": len([i for i in ids_pres if i not in con])} if ids_pres else None,
            "vencidas": len([f for f in activas if f["limite"] < hoy_s]), "bloqueadas": len([f for f in activas if f["bloqueada"]])}


@pytest.mark.parametrize("restringido", [False, True])
def test_las_cifras_del_panel_coinciden_con_el_calculo_de_referencia(base_de_datos_temporal, monkeypatch, restringido):
    t, us, clientes = _montar()
    visibles = set(clientes[::2]) if restringido else None
    if restringido:
        monkeypatch.setattr(acceso, "clientes_visibles", lambda *a, **k: visibles)
    hoy = date.today()
    ref = _referencia(t, visibles, hoy)
    panel = panel_fiscal.construir(t, us[0], hoy)
    ind = panel["indicadores"]
    assert ind["en_plazo"]["n"] == ref["n"] and ind["en_plazo"]["buenas"] == ref["buenas"] and ind["en_plazo"]["excluidas"] == ref["excluidas"]
    assert ind["en_plazo"]["porcentaje"] == (round(100 * ref["buenas"] / ref["n"]) if ref["n"] else None)
    assert ind["sin_evidencia"] == ref["sin_evidencia"]
    assert panel["totales"]["vencidas"] == ref["vencidas"] and panel["totales"]["bloqueadas"] == ref["bloqueadas"] and ind["bloqueadas"] == ref["bloqueadas"]
    assert ref["n"] > 10 and ref["vencidas"] > 5                                                  # el conjunto de datos ejercita de verdad las cifras


def test_con_muchos_vencimientos_el_panel_no_los_carga_todos(base_de_datos_temporal):
    t, us, clientes = _montar(n_clientes=400, n_venc=3000)
    a = time.perf_counter()
    panel_fiscal.construir(t, us[0])
    assert time.perf_counter() - a < 1.5                                                           # margen amplio: la regresión sería de varios segundos con 50.000


def test_los_riesgos_de_certificados_no_hacen_una_consulta_por_vencimiento(base_de_datos_temporal):
    from app import certificados
    t, us, clientes = _montar(n_clientes=60, n_venc=500)
    consultas: list[str] = []
    conn = db.get_connection()
    conn.set_trace_callback(consultas.append)
    conn.close()                                                       # vuelve al grupo de conexiones: la siguiente petición del hilo la reutiliza
    try:
        riesgos = certificados.riesgos(t)
    finally:
        conn = db.get_connection()
        conn.set_trace_callback(None)
        conn.close()
    assert riesgos and len(consultas) < 10, len(consultas)             # antes: ~una por obligación pendiente (cientos)
