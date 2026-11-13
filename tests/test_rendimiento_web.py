"""AB: medición del rendimiento de la web, fila de Salud y lectura de facturas en segundo plano."""
import json
import logging
import threading
from datetime import datetime

from app import db, ia_trabajos as tr, lectura_facturas as lf, rendimiento as r, salud
from tests.test_facturas_contables import PDF, _despacho, _web
from tests.test_lectura_facturas import modelo  # noqa: F401 -- fixture

AHORA = datetime(2026, 11, 20, 12, 0)


def _limpio():
    with r._lock:
        r._peticiones.clear(); r._colas.clear()


def test_el_resumen_da_percentiles_lentas_y_rutas_peores():
    _limpio()
    t = 1_000_000.0
    for i in range(100):
        r.registrar("/rapida", "GET", 200, 20.0, t + i)
    r.registrar("/lenta", "GET", 200, 4000.0, t + 1)
    r.registrar("/rota", "POST", 500, 50.0, t + 2)
    r.registrar("/vieja", "GET", 200, 9000.0, t - 7200)            # fuera de la ventana de una hora
    s = r.resumen(t + 120)
    assert s["peticiones"] == 102 and s["lentas"] == 1 and s["errores_5xx"] == 1 and s["max_ms"] == 4000
    assert s["p50_ms"] == 20 and s["peores"][0]["ruta"] == "GET /lenta"


def test_la_cola_saturada_de_waitress_se_cuenta():
    _limpio()
    r.instalar(__import__("app.main", fromlist=["app"]).app, db.BACKUPS_DIR / "rendimiento_estado.json")
    logging.getLogger("waitress.queue").warning("Task queue depth is %d", 3)
    logging.getLogger("waitress.queue").warning("otra cosa")
    assert r.resumen()["cola_saturada_hora"] == 1


def test_cada_respuesta_lleva_server_timing_y_la_lenta_se_avisa(cliente, monkeypatch, caplog):
    _limpio()
    monkeypatch.setattr(r, "LENTA_MS", 0)
    with caplog.at_level(logging.WARNING, logger="guilda"):
        resp = cliente.get("/login")
    assert resp.headers["Server-Timing"].startswith("app;dur=")
    avisos = [x.getMessage() for x in caplog.records if "Petición lenta" in x.getMessage()]
    assert avisos and "/login" in avisos[0] and "?" not in avisos[0].split("->")[0]
    assert r.resumen()["peticiones"] >= 1


def test_los_estaticos_no_cuentan_en_la_medicion(cliente):
    _limpio()
    cliente.get("/static/style.css")
    assert r.resumen()["peticiones"] == 0


def test_volcar_escribe_el_resumen_como_mucho_una_vez_por_minuto(tmp_path):
    _limpio()
    r.registrar("/x", "GET", 200, 10.0)
    destino = tmp_path / "estado.json"
    assert r.volcar(destino, forzar=True) and json.loads(destino.read_text())["peticiones"] == 1
    assert not r.volcar(destino)                                                # acaba de volcarse


def _fila(tmp_path, monkeypatch, estado, fecha=AHORA):
    monkeypatch.setattr(db, "BACKUPS_DIR", tmp_path)
    base = {"fecha": fecha.isoformat(), "peticiones": 50, "p50_ms": 30, "p95_ms": 200, "max_ms": 900, "lentas": 0, "errores_5xx": 0,
            "peores": [], "cola_saturada_hora": 0, "cola_saturada_dia": 0, "swap_proceso_mb": 10}
    base.update(estado)
    (tmp_path / "rendimiento_estado.json").write_text(json.dumps(base))
    return salud._estado_rendimiento(AHORA)["estado"]


def test_la_fila_de_salud_pasa_de_verde_a_rojo(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "BACKUPS_DIR", tmp_path)
    assert salud._estado_rendimiento(AHORA)["estado"] == salud.GRIS
    assert _fila(tmp_path, monkeypatch, {}) == salud.VERDE
    assert _fila(tmp_path, monkeypatch, {"p95_ms": 2500}) == salud.AMBAR
    assert _fila(tmp_path, monkeypatch, {"lentas": 7}) == salud.AMBAR
    assert _fila(tmp_path, monkeypatch, {"swap_proceso_mb": 500}) == salud.AMBAR
    assert _fila(tmp_path, monkeypatch, {"cola_saturada_dia": 2}) == salud.AMBAR
    assert _fila(tmp_path, monkeypatch, {"cola_saturada_hora": 5, "cola_saturada_dia": 5}) == salud.ROJO
    assert _fila(tmp_path, monkeypatch, {}, fecha=datetime(2026, 11, 20, 6, 0)) == salud.GRIS      # sin peticiones desde hace horas


def test_leer_con_ia_desde_la_ficha_va_a_la_cola_y_no_retiene_la_peticion(cliente, modelo, monkeypatch):
    tr._pausas.clear()
    uid, t, c = _web(cliente, "rend1@ejemplo.com")
    from app import facturas_contables as fc
    monkeypatch.setattr(lf, "configurada", lambda x: True)
    fid = fc.subir_archivos(t, uid, c, "recibida", [("f.pdf", "application/pdf", PDF + b"rend")])[0]
    resp = cliente.post(f"/contabilidad/{fid}/leer")
    assert resp.status_code == 302 and "leyendo=" in resp.headers["Location"]
    assert fc.obtener(t, uid, fid)["lectura"] != "ia"                            # todavía no se ha leído: está en la cola
    lote = resp.headers["Location"].split("leyendo=")[1]
    pagina = cliente.get(resp.headers["Location"]).get_data(as_text=True)
    assert "contabilidad_leyendo.js" in pagina and "leyendo-estado" in pagina
    otra = cliente.post(f"/contabilidad/{fid}/leer")                             # un segundo clic sigue el mismo trabajo, no crea otro
    assert otra.headers["Location"].split("leyendo=")[1] == lote
    while tr.procesar_uno():
        pass
    assert cliente.get(f"/contabilidad/lectura/{lote}").get_json()["terminado"] is True
    assert fc.obtener(t, uid, fid)["lectura"] == "ia"


def test_encolar_despierta_a_los_trabajadores_dormidos():
    t, u, c = _despacho()
    tr._despertar.clear()
    despertado = []
    hilo = threading.Thread(target=lambda: despertado.append(tr._despertar.wait(5)))
    hilo.start()
    tr.encolar(t, u, "prueba_despertar", [1])
    hilo.join(3)
    assert despertado == [True]


def test_la_lista_de_facturas_no_trae_las_columnas_pesadas_y_cubre_el_resto():
    from app import facturas_contables as fc
    conn = db.get_connection()
    try:
        todas = {r["name"] for r in conn.execute("PRAGMA table_info(facturas_contables)")}
    finally:
        conn.close()
    usadas = {c.split(".")[1] for c in fc.COLUMNAS_LISTA.split(", ")}
    assert todas - usadas == set(fc._COLUMNAS_PESADAS), "si se añade una columna a la tabla, hay que añadirla también a COLUMNAS_LISTA"


def test_periodos_cerrados_de_varios_da_lo_mismo_que_uno_a_uno():
    from app import facturas_contables as fc
    t, u, c = _despacho()
    c2 = __import__("app.db_fiscal", fromlist=["crear_cliente_fiscal"]).crear_cliente_fiscal(t, "Otra S.L.", nif="B87654321")
    fc.cerrar_periodo(t, u, c, "2026-T1")
    pedido = {c: {"2026-T1", "2026-T2"}, c2: {"2026-T1"}}
    varios = fc.periodos_cerrados_de_varios(t, pedido)
    for cid, ts in pedido.items():
        assert varios.get(cid, {}) == fc.periodos_cerrados(t, cid, ts)
    assert fc.periodos_cerrados_de_varios(t, {}) == {}
