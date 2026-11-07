"""Cola de trabajos de IA en segundo plano (R6): «leer todas las facturas», comparar modelos… Quien lo pide recibe al instante un número de lote y sigue el avance (cuántas van, cuántas fallaron);
el trabajo lo hace un hilo del servidor (`bucle`), de uno en uno por trabajador y respetando el ritmo máximo de cada proveedor, con reintentos cuando el fallo es pasajero (límite de peticiones,
proveedor caído) y sin repetirse nunca: cada trabajo se «reclama» con una actualización atómica, así que dos procesos o un reinicio no lo ejecutan dos veces.

La cola vive en la base de datos: sobrevive a los reinicios. Un trabajo que se quedó «leyendo» (el servidor se paró en mitad) vuelve a la cola pasados 10 minutos."""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta

from . import db

logger = logging.getLogger("guilda")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ia_trabajos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    usuario_id INTEGER,
    tipo TEXT NOT NULL,
    referencia INTEGER,
    lote TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'leyendo', 'hecha', 'error')),
    intentos INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    datos TEXT,
    resultado TEXT,
    no_antes_de TEXT,
    creado_en TEXT NOT NULL,
    iniciado_en TEXT,
    terminado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_ia_trabajos_lote ON ia_trabajos(tenant_id, lote);
CREATE INDEX IF NOT EXISTS idx_ia_trabajos_estado ON ia_trabajos(estado, no_antes_de);
"""

MAX_INTENTOS = 3
ESPERA_REINTENTO_SEGUNDOS = (30, 120)                 # tras el 1.º y el 2.º fallo pasajero
MINUTOS_ATASCADO = 10
SEGUNDOS_ENTRE_COMPROBACIONES = 2.0
DIAS_CONSERVAR = 14
RITMO_MINIMO_SEGUNDOS = {"openrouter": 3.0, "ollama": 0.0}          # entre consultas del mismo proveedor (los modelos gratuitos de OpenRouter admiten unas 20 por minuto)
RITMO_POR_DEFECTO_SEGUNDOS = 0.4
MAX_POR_LOTE = 500

_manejadores: dict = {}
_ultima_consulta: dict[str, float] = {}
_candado_ritmo = threading.Lock()


class Transitorio(Exception):
    """El trabajo falló por algo pasajero (el proveedor está saturado o caído): vale la pena reintentarlo más tarde."""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def registrar_manejador(tipo: str, funcion) -> None:
    """`funcion(trabajo: dict) -> dict | None` hace el trabajo y devuelve su resultado (se guarda como JSON); `Transitorio` pide reintento y cualquier otra excepción lo da por fallido."""
    _manejadores[tipo] = funcion


def _ahora() -> datetime:
    return datetime.now()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def encolar(tenant_id: int, usuario_id: int | None, tipo: str, referencias: list[int | None], lote: str | None = None, datos: dict | None = None) -> str:
    """Pone en cola un trabajo por referencia (las que ya estén esperando o en marcha no se repiten). Devuelve el identificador del lote."""
    import secrets
    lote = lote or secrets.token_hex(6)
    ahora = _iso(_ahora())
    conn = db.get_connection()
    try:
        ya = {r["referencia"] for r in conn.execute("SELECT referencia FROM ia_trabajos WHERE tenant_id = ? AND tipo = ? AND estado IN ('pendiente', 'leyendo')", (tenant_id, tipo)).fetchall()}
        nuevas = [r for r in dict.fromkeys(referencias) if r not in ya][:MAX_POR_LOTE]
        for r in nuevas:
            conn.execute("INSERT INTO ia_trabajos (tenant_id, usuario_id, tipo, referencia, lote, datos, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (tenant_id, usuario_id, tipo, r, lote, json.dumps(datos, ensure_ascii=False) if datos else None, ahora))
        conn.execute("DELETE FROM ia_trabajos WHERE terminado_en IS NOT NULL AND terminado_en < ?", (_iso(_ahora() - timedelta(days=DIAS_CONSERVAR)),))
        conn.commit()
    finally:
        conn.close()
    return lote


def _recuperar_atascados(conn) -> None:
    limite = _iso(_ahora() - timedelta(minutes=MINUTOS_ATASCADO))
    conn.execute("UPDATE ia_trabajos SET estado = 'pendiente', no_antes_de = NULL WHERE estado = 'leyendo' AND iniciado_en < ?", (limite,))


def reclamar() -> dict | None:
    """El siguiente trabajo que toca, ya marcado como «leyendo» (nadie más lo cogerá), o None si no hay ninguno listo."""
    from .bd import contexto
    with contexto.como_plataforma():
        conn = db.get_connection()
        try:
            _recuperar_atascados(conn)
            conn.commit()
            ahora = _iso(_ahora())
            for fila in conn.execute("SELECT id FROM ia_trabajos WHERE estado = 'pendiente' AND (no_antes_de IS NULL OR no_antes_de <= ?) ORDER BY id LIMIT 5", (ahora,)).fetchall():
                n = conn.execute("UPDATE ia_trabajos SET estado = 'leyendo', iniciado_en = ?, intentos = intentos + 1 WHERE id = ? AND estado = 'pendiente'", (ahora, fila["id"])).rowcount
                conn.commit()
                if n:
                    return dict(conn.execute("SELECT * FROM ia_trabajos WHERE id = ?", (fila["id"],)).fetchone())
        finally:
            conn.close()
    return None


def _terminar(trabajo: dict, estado: str, error: str | None = None, resultado: dict | None = None, reintentar_en: int | None = None) -> None:
    from .bd import contexto
    with contexto.como_plataforma():
        conn = db.get_connection()
        try:
            if reintentar_en is not None:
                conn.execute("UPDATE ia_trabajos SET estado = 'pendiente', error = ?, no_antes_de = ? WHERE id = ?", ((error or "")[:300], _iso(_ahora() + timedelta(seconds=reintentar_en)), trabajo["id"]))
            else:
                conn.execute("UPDATE ia_trabajos SET estado = ?, error = ?, resultado = ?, terminado_en = ? WHERE id = ?",
                             (estado, (error or "")[:300] or None, json.dumps(resultado, ensure_ascii=False) if resultado is not None else None, _iso(_ahora()), trabajo["id"]))
            conn.commit()
        finally:
            conn.close()


def _esperar_ritmo(proveedor: str | None) -> None:
    """Respeta el intervalo mínimo entre consultas al mismo proveedor (compartido por todos los hilos del proceso)."""
    clave = proveedor or "?"
    minimo = RITMO_MINIMO_SEGUNDOS.get(clave, RITMO_POR_DEFECTO_SEGUNDOS)
    if minimo <= 0:
        return
    with _candado_ritmo:
        espera = _ultima_consulta.get(clave, 0.0) + minimo - time.monotonic()
        if espera > 0:
            time.sleep(espera)
        _ultima_consulta[clave] = time.monotonic()


def ejecutar(trabajo: dict) -> None:
    """Hace un trabajo ya reclamado, dentro del despacho al que pertenece."""
    from .bd import contexto
    manejador = _manejadores.get(trabajo["tipo"])
    if manejador is None:
        _terminar(trabajo, "error", f"Tipo de trabajo desconocido: {trabajo['tipo']}")
        return
    try:
        datos = json.loads(trabajo["datos"]) if trabajo.get("datos") else {}
    except ValueError:
        datos = {}
    _esperar_ritmo(datos.get("proveedor"))
    try:
        with contexto.en_despacho(trabajo["tenant_id"]):
            resultado = manejador({**trabajo, "datos": datos})
        _terminar(trabajo, "hecha", resultado=resultado if isinstance(resultado, dict) else None)
    except Transitorio as e:
        if trabajo["intentos"] < MAX_INTENTOS:
            _terminar(trabajo, "pendiente", str(e), reintentar_en=ESPERA_REINTENTO_SEGUNDOS[min(trabajo["intentos"], len(ESPERA_REINTENTO_SEGUNDOS)) - 1])
        else:
            _terminar(trabajo, "error", f"{e} (se probó {MAX_INTENTOS} veces)")
    except Exception as e:  # noqa: BLE001 -- un trabajo que falla nunca tumba al trabajador
        logger.warning("Trabajo de IA %s fallido", trabajo["id"], exc_info=True)
        _terminar(trabajo, "error", str(e) or e.__class__.__name__)


def procesar_uno() -> bool:
    """Reclama y ejecuta un trabajo. Devuelve si había alguno (para los tests y para el bucle)."""
    trabajo = reclamar()
    if trabajo is None:
        return False
    ejecutar(trabajo)
    return True


def bucle(trabajadores: int = 2) -> None:
    """Hilos del servidor: cada uno reclama y ejecuta trabajos, y duerme un par de segundos cuando no hay ninguno."""
    def _trabajar() -> None:
        while True:
            try:
                if not procesar_uno():
                    time.sleep(SEGUNDOS_ENTRE_COMPROBACIONES)
            except Exception:  # noqa: BLE001
                logger.warning("Fallo en el trabajador de IA", exc_info=True)
                time.sleep(SEGUNDOS_ENTRE_COMPROBACIONES * 3)
    for i in range(trabajadores):
        threading.Thread(target=_trabajar, daemon=True, name=f"ia-trabajos-{i}").start()


def progreso(tenant_id: int, lote: str) -> dict:
    """{total, hechas, errores, pendientes, leyendo, terminado, fallos: [{referencia, error}]} de un lote."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT referencia, estado, error FROM ia_trabajos WHERE tenant_id = ? AND lote = ? ORDER BY id", (tenant_id, lote)).fetchall()
    finally:
        conn.close()
    c = {"hecha": 0, "error": 0, "pendiente": 0, "leyendo": 0}
    for f in filas:
        c[f["estado"]] += 1
    return {"total": len(filas), "hechas": c["hecha"], "errores": c["error"], "pendientes": c["pendiente"], "leyendo": c["leyendo"], "terminado": bool(filas) and not (c["pendiente"] or c["leyendo"]),
            "fallos": [{"referencia": f["referencia"], "error": f["error"]} for f in filas if f["estado"] == "error"][:10]}
