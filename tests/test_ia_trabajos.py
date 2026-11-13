"""Cola de trabajos de IA en segundo plano (R6): lote, reclamar sin repetir, reintentos, ritmo y «leer todas»."""
import json

import pytest

from app import db, facturas_contables as fc, ia_asistente, ia_trabajos as tr, lectura_facturas as lf
from tests.test_facturas_contables import PDF, _despacho, _web
from tests.test_lectura_facturas import RESPUESTA, modelo  # noqa: F401 -- fixture


@pytest.fixture(autouse=True)
def _sin_esperas(monkeypatch):
    monkeypatch.setattr(tr, "_esperar_ritmo", lambda proveedor: None)
    tr._manejadores_originales = dict(tr._manejadores)
    tr._pausas.clear()
    yield
    tr._pausas.clear()
    tr._manejadores.clear(); tr._manejadores.update(tr._manejadores_originales)


def test_encolar_no_repite_lo_que_ya_espera_y_el_progreso_cuenta():
    t, u, c = _despacho()
    lote = tr.encolar(t, u, "prueba", [1, 2, 3, 3])
    assert tr.progreso(t, lote)["total"] == 3
    lote2 = tr.encolar(t, u, "prueba", [2, 3, 4])
    assert tr.progreso(t, lote2)["total"] == 1                               # solo el 4: los otros ya estaban esperando
    assert tr.progreso(t, "inexistente") == {"pausa_hasta": None, "total": 0, "hechas": 0, "errores": 0, "pendientes": 0, "leyendo": 0, "terminado": False, "fallos": []}


def test_cada_trabajo_se_ejecuta_una_sola_vez_y_en_orden():
    t, u, c = _despacho()
    hechos = []
    tr.registrar_manejador("prueba", lambda trabajo: hechos.append(trabajo["referencia"]) or {"ok": trabajo["referencia"]})
    lote = tr.encolar(t, u, "prueba", [10, 11])
    assert tr.procesar_uno() and tr.procesar_uno() and not tr.procesar_uno()
    assert hechos == [10, 11]
    p = tr.progreso(t, lote)
    assert p["hechas"] == 2 and p["terminado"] and p["errores"] == 0


def test_reclamar_marca_el_trabajo_y_un_segundo_trabajador_no_lo_coge():
    t, u, c = _despacho()
    tr.registrar_manejador("prueba", lambda trabajo: {})
    tr.encolar(t, u, "prueba", [1])
    primero = tr.reclamar()
    assert primero["estado"] == "leyendo" and primero["intentos"] == 1 and tr.reclamar() is None


def test_un_fallo_normal_deja_el_trabajo_en_error_y_no_tumba_a_los_demas():
    t, u, c = _despacho()

    def manejador(trabajo):
        if trabajo["referencia"] == 1:
            raise RuntimeError("se rompió")
        return {"ok": True}
    tr.registrar_manejador("prueba", manejador)
    lote = tr.encolar(t, u, "prueba", [1, 2])
    while tr.procesar_uno():
        pass
    p = tr.progreso(t, lote)
    assert p["hechas"] == 1 and p["errores"] == 1 and p["fallos"] == [{"referencia": 1, "error": "se rompió"}] and p["terminado"]


def test_un_fallo_pasajero_se_reintenta_mas_tarde_y_al_tercero_se_rinde():
    t, u, c = _despacho()
    veces = []

    def manejador(trabajo):
        veces.append(trabajo["intentos"])
        raise tr.Transitorio("el proveedor está saturado")
    tr.registrar_manejador("prueba", manejador)
    lote = tr.encolar(t, u, "prueba", [1])
    assert tr.procesar_uno()
    p = tr.progreso(t, lote)
    assert p["pendientes"] == 1 and not p["terminado"]
    assert not tr.procesar_uno()                                            # aún no toca: espera su turno de reintento
    for _ in range(2):                                                      # se adelanta el reloj de los reintentos
        conn = db.get_connection(); conn.execute("UPDATE ia_trabajos SET no_antes_de = '2000-01-01T00:00:00'"); conn.commit(); conn.close()
        assert tr.procesar_uno()
    p = tr.progreso(t, lote)
    assert veces == [1, 2, 3] and p["errores"] == 1 and p["terminado"] and "3 veces" in p["fallos"][0]["error"]


def test_un_trabajo_atascado_vuelve_a_la_cola():
    t, u, c = _despacho()
    tr.registrar_manejador("prueba", lambda trabajo: {})
    tr.encolar(t, u, "prueba", [1])
    tr.reclamar()
    assert tr.reclamar() is None
    conn = db.get_connection(); conn.execute("UPDATE ia_trabajos SET iniciado_en = '2000-01-01T00:00:00' WHERE estado = 'leyendo'"); conn.commit(); conn.close()
    assert tr.reclamar() is not None                                       # el servidor se paró a mitad: pasados 10 minutos se vuelve a intentar


def test_el_tipo_desconocido_se_da_por_fallido():
    t, u, c = _despacho()
    lote = tr.encolar(t, u, "inventado", [1])
    tr.procesar_uno()
    assert tr.progreso(t, lote)["errores"] == 1


def test_leer_todas_lee_en_segundo_plano_y_el_progreso_llega_al_final(cliente, monkeypatch):
    uid, t, c = _web(cliente, "cola1@ejemplo.com")
    monkeypatch.setattr(lf, "configurada", lambda x: True)
    monkeypatch.setattr(ia_asistente, "completar_partes", lambda x, s, p, timeout=90: json.dumps(RESPUESTA))
    ids = [fc.subir_archivos(t, uid, c, "recibida", [("f.pdf", "application/pdf", PDF + bytes([i]))])[0] for i in range(3)]
    r = cliente.post("/contabilidad/leer-todas").get_json()
    assert r["ok"] and r["total"] == 3
    p = cliente.get(f"/contabilidad/lectura/{r['lote']}").get_json()
    assert p["total"] == 3 and p["pendientes"] == 3 and not p["terminado"]
    while tr.procesar_uno():
        pass
    p = cliente.get(f"/contabilidad/lectura/{r['lote']}").get_json()
    assert p["hechas"] == 3 and p["terminado"] and all(fc.obtener(t, uid, i)["lectura"] == "ia" for i in ids)
    assert cliente.post("/contabilidad/leer-todas").get_json()["total"] == 0                    # ya no queda nada por leer


def test_leer_todas_no_repite_lo_que_ya_esta_en_cola_y_exige_ia(cliente, monkeypatch):
    uid, t, c = _web(cliente, "cola2@ejemplo.com")
    monkeypatch.setattr(lf, "configurada", lambda x: False)
    r = cliente.post("/contabilidad/leer-todas")
    assert r.status_code == 400 and "Hace falta" in r.get_json()["error"]
    monkeypatch.setattr(lf, "configurada", lambda x: True)
    fc.subir_archivos(t, uid, c, "recibida", [("f.pdf", "application/pdf", PDF + b"z")])
    assert cliente.post("/contabilidad/leer-todas").get_json()["total"] == 1
    assert cliente.post("/contabilidad/leer-todas").get_json()["total"] == 0                    # ya está en la cola


def test_un_fallo_pasajero_de_la_ia_en_la_lectura_se_reintenta(cliente, monkeypatch):
    uid, t, c = _web(cliente, "cola3@ejemplo.com")
    monkeypatch.setattr(lf, "configurada", lambda x: True)
    respuestas = [ia_asistente.ErrorIA("saturado", codigo_http=503), json.dumps(RESPUESTA)]

    def falso(x, s, p, timeout=90):
        r = respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(ia_asistente, "completar_partes", falso)
    fid = fc.subir_archivos(t, uid, c, "recibida", [("f.pdf", "application/pdf", PDF + b"r")])[0]
    lote = cliente.post("/contabilidad/leer-todas").get_json()["lote"]
    assert tr.procesar_uno() and tr.progreso(t, lote)["pendientes"] == 1
    conn = db.get_connection(); conn.execute("UPDATE ia_trabajos SET no_antes_de = '2000-01-01T00:00:00'"); conn.commit(); conn.close()
    assert tr.procesar_uno()
    assert tr.progreso(t, lote)["hechas"] == 1 and fc.obtener(t, uid, fid)["lectura"] == "ia"


def test_un_error_definitivo_de_la_ia_no_se_reintenta(cliente, monkeypatch):
    uid, t, c = _web(cliente, "cola4@ejemplo.com")
    monkeypatch.setattr(lf, "configurada", lambda x: True)

    def falso(x, s, p, timeout=90):
        raise ia_asistente.ErrorIA("el modelo no ve imágenes", codigo_http=400)
    monkeypatch.setattr(ia_asistente, "completar_partes", falso)
    fc.subir_archivos(t, uid, c, "recibida", [("f.pdf", "application/pdf", PDF + b"s")])
    lote = cliente.post("/contabilidad/leer-todas").get_json()["lote"]
    tr.procesar_uno()
    p = tr.progreso(t, lote)
    assert p["errores"] == 1 and p["pendientes"] == 0 and "no admite imágenes" in p["fallos"][0]["error"]


def test_si_el_proveedor_limita_la_cola_se_pausa_sin_gastar_intentos_y_se_reanuda(cliente, monkeypatch):
    uid, t, c = _web(cliente, "pausa1@ejemplo.com")
    monkeypatch.setattr(lf, "configurada", lambda x: True)
    llamadas = []

    def falso(x, s, p, timeout=90):
        llamadas.append(1)
        if len(llamadas) <= 1:
            raise ia_asistente.ErrorIA("429 demasiadas consultas", codigo_http=429)
        return json.dumps(RESPUESTA)
    monkeypatch.setattr(ia_asistente, "completar_partes", falso)
    tr._pausas.clear()
    ids = [fc.subir_archivos(t, uid, c, "recibida", [("f.pdf", "application/pdf", PDF + bytes([40 + i]))])[0] for i in range(3)]
    lote = cliente.post("/contabilidad/leer-todas").get_json()["lote"]
    assert tr.procesar_uno()                                                   # la primera consulta choca con el límite
    p = tr.progreso(t, lote)
    assert p["pendientes"] == 3 and p["errores"] == 0 and p["pausa_hasta"] and not p["terminado"]
    assert tr.procesar_uno() and tr.procesar_uno() and len(llamadas) == 1      # los demás se aplazan al tocarles, sin hacer otra consulta que fallaría
    assert tr.reclamar() is None and tr.progreso(t, lote)["pendientes"] == 3
    conn = db.get_connection(); conn.execute("UPDATE ia_trabajos SET no_antes_de = '2000-01-01T00:00:00'"); conn.commit(); conn.close()
    assert tr.procesar_uno() and len(llamadas) == 1                            # sigue pausado: de nuevo sin consulta
    tr._pausas.clear()                                                         # (acaba la pausa)
    conn = db.get_connection(); conn.execute("UPDATE ia_trabajos SET no_antes_de = '2000-01-01T00:00:00'"); conn.commit(); conn.close()
    while tr.procesar_uno():
        pass
    p = tr.progreso(t, lote)
    assert p["hechas"] == 3 and p["errores"] == 0 and all(fc.obtener(t, uid, i)["lectura"] == "ia" for i in ids)
    assert tr.MENSAJE_PAUSA.startswith("Pausa")
