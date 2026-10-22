"""Motor de ingesta durable del corpus jurídico (anexo de flujos, §8).

Idempotente y con checkpoints seguros:
- Cada página descubierta se registra en UNA transacción: registros (`DISCOVERED`), trabajos del `outbox` y el nuevo cursor de la ejecución. El cursor significa «inventario registrado», no «publicado».
- El consumidor del outbox es idempotente: procesar dos veces el mismo trabajo no duplica nada (misma revisión de origen y texto ya publicado = nada que hacer).
- Máquina de estados por registro: DISCOVERED → FETCH_PENDING → FETCHED → PARSED → VALIDATED → INDEX_PENDING → INDEXED → PUBLISHED, y los laterales RETRYABLE_ERROR, QUARANTINED, BLOCKED_POLICY, WITHDRAWN.
- Una ejecución solo es `completa` cuando todos sus elementos están resueltos; con errores o cuarentenas es `parcial` y la cobertura lo enseña. `ultimo_exito_en` solo avanza en las completas.
- Un fallo de la fuente conserva la última versión utilizable; nunca se afirma estar al día por haber ejecutado el worker."""
from __future__ import annotations

import json
import threading
from datetime import datetime

from .. import db
from . import corpus
from .conectores.base import Conector, ErrorConector, RefRegistro

MAX_INTENTOS = 3
_cerrojos: dict[str, threading.Lock] = {}
_cerrojo_global = threading.Lock()


def _cerrojo(fuente_id: str) -> threading.Lock:
    with _cerrojo_global:
        return _cerrojos.setdefault(fuente_id, threading.Lock())


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _contadores(run_id: int, conn) -> dict:
    fila = conn.execute("SELECT contadores FROM jur_sync_runs WHERE id = ?", (run_id,)).fetchone()
    return json.loads(fila["contadores"]) if fila and fila["contadores"] else {}


def _sumar(run_id: int, conn, **kw) -> None:
    c = _contadores(run_id, conn)
    for k, v in kw.items():
        c[k] = c.get(k, 0) + v
    conn.execute("UPDATE jur_sync_runs SET contadores = ? WHERE id = ?", (json.dumps(c), run_id))


def sincronizar(fuente_id: str, conector: Conector, desde: str, hasta: str, *, usuario_id: int | None = None, max_paginas: int | None = None, procesar: bool = True,
                embedder=None, reanudar_run: int | None = None) -> dict:
    """Descubre en la ventana [desde, hasta], registra el inventario y (con `procesar`) descarga, analiza y publica. Devuelve el resumen de la ejecución."""
    if embedder is None:
        from . import modulo
        embedder = modulo.embedder()
    with _cerrojo(fuente_id):
        conn = db.get_connection()
        try:
            f = conn.execute("SELECT * FROM jur_fuentes WHERE id = ?", (fuente_id,)).fetchone()
            if f is None:
                raise corpus.ErrorCorpus("La fuente no existe.")
            if not conector.capacidades.descubrir:
                raise corpus.ErrorCorpus("Este conector no sabe descubrir documentos: no puede sincronizar la fuente.")
            if not f["habilitada"] or not (corpus.operacion_permitida(fuente_id, "almacenar", conn) and corpus.operacion_permitida(fuente_id, "indexar", conn)):
                run_id = conn.execute("INSERT INTO jur_sync_runs (fuente_id, desde, hasta, estado, error, iniciada_en, terminada_en) VALUES (?, ?, ?, 'bloqueada', ?, ?, ?)",
                                      (fuente_id, desde, hasta, "Fuente no habilitada o sin política que permita almacenar e indexar.", _ahora(), _ahora())).lastrowid
                conn.commit()
                return resumen(run_id)
            if reanudar_run:
                run = conn.execute("SELECT * FROM jur_sync_runs WHERE id = ? AND fuente_id = ?", (reanudar_run, fuente_id)).fetchone()
                if run is None:
                    raise corpus.ErrorCorpus("La ejecución a reanudar no existe.")
                run_id, cursor = run["id"], run["cursor"]
                conn.execute("UPDATE jur_sync_runs SET estado = 'en_curso', error = NULL, terminada_en = NULL WHERE id = ?", (run_id,))
            else:
                run_id = conn.execute("INSERT INTO jur_sync_runs (fuente_id, desde, hasta, estado, iniciada_en) VALUES (?, ?, ?, 'en_curso', ?)", (fuente_id, desde, hasta, _ahora())).lastrowid
                cursor = None
            conn.commit()
        finally:
            conn.close()
        error = None
        paginas = 0
        try:
            while True:
                pagina = conector.discover(desde, hasta, cursor)
                _registrar_pagina(fuente_id, run_id, pagina, usuario_id)
                cursor = pagina.siguiente_cursor
                paginas += 1
                if pagina.agotada or cursor is None or (max_paginas and paginas >= max_paginas):
                    break
        except ErrorConector as e:
            error = str(e)
        except Exception as e:  # noqa: BLE001 -- el worker nunca cae por una fuente
            error = f"Error inesperado al descubrir: {e}"
        completo_inventario = error is None and (cursor is None)
        if procesar:
            procesar_pendientes(fuente_id, conector, run_id=run_id, embedder=embedder)
        return _cerrar(fuente_id, run_id, error, completo_inventario)


def _registrar_pagina(fuente_id: str, run_id: int, pagina, usuario_id) -> None:
    """UNA transacción: originales de evidencia, registros nuevos o con revisión distinta, outbox, retiradas y cursor."""
    conn = db.get_connection()
    try:
        for ev in pagina.evidencia:
            corpus.guardar_original(fuente_id, ev.contenido, ev.url, ev.tipo_mime, conn=conn)
        nuevos = cambiados = iguales = 0
        for ref in pagina.registros:
            fila = conn.execute("SELECT id, estado, revision_origen FROM jur_registros_fuente WHERE fuente_id = ? AND id_externo = ?", (fuente_id, ref.id_externo)).fetchone()
            if fila is None:
                conn.execute("INSERT INTO jur_registros_fuente (fuente_id, id_externo, estado, revision_origen, localizador, descubierto_en, actualizado_en) VALUES (?, ?, 'DISCOVERED', ?, ?, ?, ?)",
                             (fuente_id, ref.id_externo, ref.actualizado_origen, ref.localizador, _ahora(), _ahora()))
                nuevos += 1
            elif fila["estado"] == "PUBLISHED" and ref.actualizado_origen is not None and fila["revision_origen"] == ref.actualizado_origen:
                iguales += 1
                continue                                                                 # misma revisión ya publicada: nada que hacer
            elif fila["estado"] in ("WITHDRAWN",):
                continue
            else:
                conn.execute("UPDATE jur_registros_fuente SET estado = 'DISCOVERED', revision_origen = ?, localizador = ?, actualizado_en = ? WHERE id = ?",
                             (ref.actualizado_origen, ref.localizador, _ahora(), fila["id"]))
                cambiados += 1
            conn.execute("INSERT INTO jur_outbox (sync_run_id, fuente_id, id_externo, creada_en) VALUES (?, ?, ?, ?)", (run_id, fuente_id, ref.id_externo, _ahora()))
        for id_externo, motivo in pagina.retiradas:
            corpus.retirar(fuente_id, id_externo, motivo or "retirada por la fuente", usuario_id=usuario_id)
        conn.execute("UPDATE jur_sync_runs SET cursor = ? WHERE id = ?", (pagina.siguiente_cursor, run_id))
        extra = {k: v for k, v in (pagina.notas or {}).items() if isinstance(v, int)}
        _sumar(run_id, conn, descubiertos=len(pagina.registros), nuevos=nuevos, cambiados=cambiados, iguales=iguales, paginas=1, retiradas=len(pagina.retiradas), **extra)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _estado(conn, fuente_id: str, id_externo: str, estado: str, *, error: str | None = None, documento_id: int | None = None, intentos: bool = False) -> None:
    conn.execute("UPDATE jur_registros_fuente SET estado = ?, ultimo_error = ?, actualizado_en = ?, intentos = intentos + ?, documento_id = COALESCE(?, documento_id) WHERE fuente_id = ? AND id_externo = ?",
                 (estado, error, _ahora(), 1 if intentos else 0, documento_id, fuente_id, id_externo))
    conn.commit()


def procesar_pendientes(fuente_id: str, conector: Conector, *, run_id: int | None = None, limite: int = 100000, embedder=None) -> dict:
    """Consume el outbox pendiente de la fuente (y reintenta los `RETRYABLE_ERROR` con intentos disponibles). Idempotente."""
    hechos = {"publicados": 0, "sin_cambios": 0, "reintentables": 0, "cuarentena": 0, "bloqueados": 0}
    conn = db.get_connection()
    try:
        reintentables = [r["id_externo"] for r in conn.execute("SELECT id_externo FROM jur_registros_fuente WHERE fuente_id = ? AND estado = 'RETRYABLE_ERROR' AND intentos < ?", (fuente_id, MAX_INTENTOS))]
        for id_externo in reintentables:
            conn.execute("INSERT INTO jur_outbox (sync_run_id, fuente_id, id_externo, creada_en) VALUES (?, ?, ?, ?)", (run_id, fuente_id, id_externo, _ahora()))
        conn.commit()
        pendientes = conn.execute("SELECT id, id_externo FROM jur_outbox WHERE fuente_id = ? AND estado = 'pendiente' ORDER BY id LIMIT ?", (fuente_id, limite)).fetchall()
        vistos: set[str] = set()
        for trabajo in pendientes:
            if trabajo["id_externo"] in vistos:                                   # el mismo registro dos veces en la cola (reenvío): se procesa UNA vez por pasada
                conn.execute("UPDATE jur_outbox SET estado = 'hecho' WHERE id = ?", (trabajo["id"],))
                conn.commit()
                continue
            vistos.add(trabajo["id_externo"])
            resultado = _procesar_registro(conn, fuente_id, trabajo["id_externo"], conector, embedder)
            conn.execute("UPDATE jur_outbox SET estado = 'hecho' WHERE id = ?", (trabajo["id"],))
            conn.commit()
            hechos[resultado] = hechos.get(resultado, 0) + 1
        if run_id:
            _sumar(run_id, conn, **{k: v for k, v in hechos.items() if v})
            conn.commit()
    finally:
        conn.close()
    return hechos


def _procesar_registro(conn, fuente_id: str, id_externo: str, conector: Conector, embedder) -> str:
    fila = conn.execute("SELECT * FROM jur_registros_fuente WHERE fuente_id = ? AND id_externo = ?", (fuente_id, id_externo)).fetchone()
    if fila is None or fila["estado"] in ("PUBLISHED", "WITHDRAWN", "QUARANTINED"):
        return "sin_cambios"                                                                # trabajo duplicado o ya resuelto: idempotente
    if not (corpus.operacion_permitida(fuente_id, "almacenar", conn) and corpus.operacion_permitida(fuente_id, "indexar", conn)):
        _estado(conn, fuente_id, id_externo, "BLOCKED_POLICY", error="La política de la fuente no permite almacenar e indexar.")
        return "bloqueados"
    ref = RefRegistro(fuente_id, id_externo, fila["revision_origen"], fila["localizador"] or "")
    try:
        _estado(conn, fuente_id, id_externo, "FETCH_PENDING")
        original = conector.fetch(ref)
        hash_original = corpus.guardar_original(fuente_id, original.contenido, original.url, original.tipo_mime, conn=conn)
        _estado(conn, fuente_id, id_externo, "FETCHED")
        parseado = conector.parse(ref, original)
        _estado(conn, fuente_id, id_externo, "PARSED")
        if parseado.documento.fuente_id != fuente_id or parseado.documento.id_externo != id_externo:
            raise ErrorConector("La identidad del documento analizado no coincide con el registro.")
        _estado(conn, fuente_id, id_externo, "VALIDATED")
        _estado(conn, fuente_id, id_externo, "INDEX_PENDING")
        pub = corpus.publicar(parseado.documento, parseado.fragmentos, hash_original=hash_original, relaciones=parseado.relaciones, embedder=embedder, calidad=parseado.calidad)
        if pub.estado == "bloqueada":
            _estado(conn, fuente_id, id_externo, "BLOCKED_POLICY", error=pub.motivo)
            return "bloqueados"
        _estado(conn, fuente_id, id_externo, "INDEXED", documento_id=pub.documento_id)
        _estado(conn, fuente_id, id_externo, "PUBLISHED", documento_id=pub.documento_id)
        return "sin_cambios" if pub.estado == "sin_cambios" else "publicados"
    except ErrorConector as e:
        return _fallo(conn, fuente_id, id_externo, str(e), e.transitorio, fila["intentos"])
    except corpus.ErrorCorpus as e:
        return _fallo(conn, fuente_id, id_externo, str(e), False, fila["intentos"])
    except Exception as e:  # noqa: BLE001
        return _fallo(conn, fuente_id, id_externo, f"Error inesperado: {e}", True, fila["intentos"])


def _fallo(conn, fuente_id: str, id_externo: str, mensaje: str, transitorio: bool, intentos_previos: int) -> str:
    conn.rollback()
    if transitorio and intentos_previos + 1 < MAX_INTENTOS:
        _estado(conn, fuente_id, id_externo, "RETRYABLE_ERROR", error=mensaje[:500], intentos=True)
        return "reintentables"
    _estado(conn, fuente_id, id_externo, "QUARANTINED", error=mensaje[:500], intentos=True)
    return "cuarentena"


def _cerrar(fuente_id: str, run_id: int, error: str | None, inventario_completo: bool) -> dict:
    conn = db.get_connection()
    try:
        sin_resolver = conn.execute(
            "SELECT COUNT(*) FROM jur_registros_fuente r WHERE r.fuente_id = ? AND r.estado NOT IN ('PUBLISHED', 'WITHDRAWN') AND r.id_externo IN "
            "(SELECT id_externo FROM jur_outbox WHERE sync_run_id = ?)", (fuente_id, run_id)).fetchone()[0]
        if error:
            estado = "fallida" if _contadores(run_id, conn).get("descubiertos", 0) == 0 else "parcial"
        elif not inventario_completo or sin_resolver:
            estado = "parcial"
        else:
            estado = "completa"
        conn.execute("UPDATE jur_sync_runs SET estado = ?, error = ?, terminada_en = ? WHERE id = ?", (estado, error, _ahora(), run_id))
        if estado == "completa":
            conn.execute("UPDATE jur_fuentes SET ultimo_exito_en = ?, estado = 'activo' WHERE id = ? AND habilitada = 1", (_ahora(), fuente_id))
        elif error and conn.execute("SELECT habilitada FROM jur_fuentes WHERE id = ?", (fuente_id,)).fetchone()["habilitada"]:
            conn.execute("UPDATE jur_fuentes SET estado = 'incidencia' WHERE id = ?", (fuente_id,))
        conn.execute("INSERT INTO jur_cobertura (fuente_id, capturada_en, datos) VALUES (?, ?, ?)", (fuente_id, _ahora(), json.dumps(corpus.cobertura(fuente_id), default=str)))
        conn.commit()
    finally:
        conn.close()
    return resumen(run_id)


def resumen(run_id: int) -> dict:
    conn = db.get_connection()
    try:
        r = conn.execute("SELECT * FROM jur_sync_runs WHERE id = ?", (run_id,)).fetchone()
        d = dict(r)
        d["contadores"] = json.loads(d["contadores"]) if d.get("contadores") else {}
        return d
    finally:
        conn.close()


def ultimas_ejecuciones(fuente_id: str | None = None, limite: int = 20) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT * FROM jur_sync_runs" + (" WHERE fuente_id = ?" if fuente_id else "") + " ORDER BY id DESC LIMIT ?", ((fuente_id, limite) if fuente_id else (limite,))).fetchall()
        return [{**dict(f), "contadores": json.loads(f["contadores"]) if f["contadores"] else {}} for f in filas]
    finally:
        conn.close()


def registros_con_problemas(fuente_id: str, limite: int = 100) -> list[dict]:
    """Cuarentena, bloqueados y reintentables, con su último error: lo que hay que mirar."""
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT id_externo, estado, intentos, ultimo_error, actualizado_en FROM jur_registros_fuente WHERE fuente_id = ? AND estado IN ('QUARANTINED', 'BLOCKED_POLICY', 'RETRYABLE_ERROR') ORDER BY actualizado_en DESC LIMIT ?", (fuente_id, limite))]
    finally:
        conn.close()
