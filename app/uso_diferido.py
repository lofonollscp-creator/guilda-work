"""Registro de uso de la API y del MCP **fuera de la ruta caliente**.

Hasta ahora cada petición escribía, en su propia transacción, tres cosas en tablas que en Citus son **de referencia** (replicadas): `tokens_api.ultimo_uso_en`, el contador diario
`tokens_api_uso` y, en el MCP, `mcp_uso`. Escribir en una tabla de referencia toma un bloqueo exclusivo que dura hasta confirmar (docs/adr-postgresql-citus.md) y, con peticiones
simultáneas, Citus las resuelve con `DeadlockDetected` («distributed deadlock»): medido con 4 clientes a la vez el 7 % de las peticiones daba 500, con 12 el 65 %
(docs/anexos-app-movil/medida_concurrencia_uso.json). Sin esas escrituras: 0 errores y 5–10 veces más peticiones por segundo.

Aquí el uso **se suma en memoria** (microsegundos, sin base de datos) y un único hilo lo **vuelca cada `GUILDA_USO_VOLCADO_SEG` segundos (30)** en UNA transacción corta, con las filas
ordenadas por clave para que dos procesos que vuelquen a la vez no se crucen. Coste asumido: si el proceso muere de golpe se pierden como mucho esos 30 s de contadores (son
estadística y detección de tokens inactivos). Quien LEE esos datos (`uso_de_token`, el panel de tokens y el resumen del MCP) llama antes a `volcar()`, así que dentro del mismo proceso
siempre ven lo último; con varios procesos, el retraso máximo es el del volcado.

    GUILDA_USO_DIFERIDO=1|0      (por defecto 1 con PostgreSQL y 0 con SQLite, donde no hay problema y las pruebas leen al instante)
    GUILDA_USO_VOLCADO_SEG=30
    GUILDA_USO_HILO=1|0          (0 = sin hilo de fondo: solo se vuelca al leer o al llamar a `volcar()`; lo usan las pruebas)
"""
from __future__ import annotations

import atexit
import logging
import os
import signal
import sys
import threading
from datetime import date, datetime

logger = logging.getLogger(__name__)

# Con lo que ha pasado en 30 s ya hay de sobra; este tope evita que un volcado que falle sin parar acumule memoria sin límite.
MAX_PENDIENTES = 50_000
REFRESCO_ULTIMO_USO_SEG = 60       # `ultimo_uso_en` no se escribe más de una vez por minuto y token

_lock = threading.RLock()
_tokens: dict[tuple[str, int, str], list[int]] = {}               # (base, token_id, día) -> [llamadas, errores]
_mcp: dict[tuple[str, str, int, str], list[int]] = {}             # (base, día, usuario_id, herramienta) -> [llamadas, errores]
_ultimo: dict[tuple[str, int], tuple[str, str | None]] = {}       # (base, token_id) -> (momento ISO, ip)
_hilo: threading.Thread | None = None
_parar = threading.Event()
_instalado = False
_volcados = 0                                                      # para las pruebas y el panel de salud


def _activo() -> bool:
    valor = os.environ.get("GUILDA_USO_DIFERIDO")
    if valor is not None:
        return valor.strip() not in ("0", "", "no", "false")
    from . import bd
    return bd.MOTOR == "postgres"


def _intervalo() -> float:
    try:
        return max(1.0, float(os.environ.get("GUILDA_USO_VOLCADO_SEG", "30")))
    except ValueError:
        return 30.0


def _identidad() -> str:
    """Qué base de datos es la actual: lo pendiente de otra (una prueba anterior) se descarta en vez de escribirse donde no toca."""
    from . import bd, db
    if bd.MOTOR == "postgres":
        try:
            from .bd import postgres as pg
            return "pg:" + pg._url("app")
        except Exception:                                          # noqa: BLE001
            return "pg"
    return "sqlite:" + str(db.DB_PATH)


def _ahora_iso() -> str:
    from . import db
    return db.now_iso()


# --- Anotar ---------------------------------------------------------------------------------------------------------------------------------

def sumar_uso_token(token_id: int, status: int) -> None:
    """Una llamada (y un error si `status >= 400`) en el contador del día de ese token."""
    if not _activo():
        _escribir_directo_token(token_id, status)
        return
    clave = (_identidad(), token_id, date.today().isoformat())
    with _lock:
        if len(_tokens) + len(_mcp) >= MAX_PENDIENTES and clave not in _tokens:
            return
        fila = _tokens.setdefault(clave, [0, 0])
        fila[0] += 1
        fila[1] += 1 if status >= 400 else 0
    _asegurar_hilo()


def sumar_uso_mcp(usuario_id: int, herramienta: str, error: bool) -> None:
    """Una llamada a una herramienta MCP en el contador diario de esa persona."""
    if not _activo():
        _escribir_directo_mcp(usuario_id, herramienta, error)
        return
    clave = (_identidad(), date.today().isoformat(), usuario_id, herramienta)
    with _lock:
        if len(_tokens) + len(_mcp) >= MAX_PENDIENTES and clave not in _mcp:
            return
        fila = _mcp.setdefault(clave, [0, 0])
        fila[0] += 1
        fila[1] += 1 if error else 0
    _asegurar_hilo()


def tocar_token(token_id: int, ultimo_uso_leido: str | None, ip: str | None, ahora: str) -> bool:
    """¿Hay que escribir ya `ultimo_uso_en` y `ultima_ip` del token? Con el diferido apagado, siempre (como antes). Con él activo, solo se anota en memoria y se escribe en el volcado,
    y como mucho una vez por minuto y token: devuelve False (nada que escribir ahora)."""
    if not _activo():
        return True
    if ultimo_uso_leido:
        try:
            if (datetime.fromisoformat(ahora) - datetime.fromisoformat(ultimo_uso_leido)).total_seconds() < REFRESCO_ULTIMO_USO_SEG:
                return False
        except ValueError:
            pass
    with _lock:
        _ultimo[(_identidad(), token_id)] = (ahora, ip)
    _asegurar_hilo()
    return False


# --- Escritura directa (SQLite o diferido apagado: el comportamiento de siempre) -----------------------------------------------------------

def _escribir_directo_token(token_id: int, status: int) -> None:
    from . import db
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO tokens_api_uso (token_id, dia, llamadas, errores) VALUES (?, ?, 1, ?) "
            "ON CONFLICT(token_id, dia) DO UPDATE SET llamadas = tokens_api_uso.llamadas + 1, errores = tokens_api_uso.errores + excluded.errores",
            (token_id, date.today().isoformat(), 1 if status >= 400 else 0),
        )
        conn.commit()
    finally:
        conn.close()


def _escribir_directo_mcp(usuario_id: int, herramienta: str, error: bool) -> None:
    from . import db
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO mcp_uso (dia, usuario_id, herramienta, llamadas, errores) VALUES (?, ?, ?, 1, ?) "
            "ON CONFLICT(dia, usuario_id, herramienta) DO UPDATE SET llamadas = mcp_uso.llamadas + 1, errores = mcp_uso.errores + excluded.errores",
            (date.today().isoformat(), usuario_id, herramienta, 1 if error else 0),
        )
        _purgar_mcp(conn)
        conn.commit()
    finally:
        conn.close()


# --- Volcado --------------------------------------------------------------------------------------------------------------------------------

def volcar() -> int:
    """Escribe lo pendiente en UNA transacción corta (filas ordenadas por clave). Devuelve cuántas filas escribió. Nunca lanza: si falla, lo pendiente se conserva para el siguiente intento."""
    global _volcados
    with _lock:
        if not (_tokens or _mcp or _ultimo):
            return 0
        tokens, mcp, ultimo = dict(_tokens), dict(_mcp), dict(_ultimo)
        _tokens.clear(), _mcp.clear(), _ultimo.clear()
    actual = _identidad()
    tokens = {k: v for k, v in tokens.items() if k[0] == actual}
    mcp = {k: v for k, v in mcp.items() if k[0] == actual}
    ultimo = {k: v for k, v in ultimo.items() if k[0] == actual}
    if not (tokens or mcp or ultimo):
        return 0
    from . import db
    escritas = 0
    try:
        conn = db.get_connection()
        try:
            if ultimo:
                conn.executemany(
                    "UPDATE tokens_api SET ultimo_uso_en = ?, ultima_ip = COALESCE(?, ultima_ip) WHERE id = ?",
                    [(momento, ip, token_id) for (_b, token_id), (momento, ip) in sorted(ultimo.items(), key=lambda x: x[0][1])])
                escritas += len(ultimo)
            if tokens:
                conn.executemany(
                    "INSERT INTO tokens_api_uso (token_id, dia, llamadas, errores) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(token_id, dia) DO UPDATE SET llamadas = tokens_api_uso.llamadas + excluded.llamadas, errores = tokens_api_uso.errores + excluded.errores",
                    [(token_id, dia, n[0], n[1]) for (_b, token_id, dia), n in sorted(tokens.items(), key=lambda x: (x[0][1], x[0][2]))])
                escritas += len(tokens)
            if mcp:
                conn.executemany(
                    "INSERT INTO mcp_uso (dia, usuario_id, herramienta, llamadas, errores) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(dia, usuario_id, herramienta) DO UPDATE SET llamadas = mcp_uso.llamadas + excluded.llamadas, errores = mcp_uso.errores + excluded.errores",
                    [(dia, usuario_id, herramienta, n[0], n[1]) for (_b, dia, usuario_id, herramienta), n in sorted(mcp.items(), key=lambda x: (x[0][1], x[0][2], x[0][3]))])
                escritas += len(mcp)
                _purgar_mcp(conn)
            conn.commit()
        finally:
            conn.close()
        _volcados += 1
        return escritas
    except Exception as e:                                         # noqa: BLE001 -- el uso es estadística: nunca debe tumbar a quien lo lee ni al hilo
        logger.warning("No se pudo volcar el uso de la API/MCP (se reintentará): %s", e)
        with _lock:                                                # se devuelve a lo pendiente para el siguiente intento
            for k, v in tokens.items():
                f = _tokens.setdefault(k, [0, 0]); f[0] += v[0]; f[1] += v[1]
            for k, v in mcp.items():
                f = _mcp.setdefault(k, [0, 0]); f[0] += v[0]; f[1] += v[1]
            for k, v in ultimo.items():
                _ultimo.setdefault(k, v)
        return 0


def _purgar_mcp(conn) -> None:
    """La limpieza del contador del MCP, que antes hacía una de cada cien llamadas con un DELETE sobre la tabla de referencia, ahora cuelga del volcado (una de cada cien)."""
    import random
    from . import db
    if random.random() < 0.01:
        limite = (db.datetime.now() - db.timedelta(days=db.MCP_AUDITORIA_RETENCION_DIAS)).isoformat(timespec="seconds")
        conn.execute("DELETE FROM mcp_uso WHERE dia < ?", (limite[:10],))


def pendientes() -> dict:
    with _lock:
        return {"tokens": len(_tokens), "mcp": len(_mcp), "ultimo_uso": len(_ultimo), "volcados": _volcados, "activo": _activo()}


def reiniciar() -> None:
    """Descarta lo pendiente (solo para las pruebas)."""
    with _lock:
        _tokens.clear(), _mcp.clear(), _ultimo.clear()


# --- Hilo y cierre limpio -------------------------------------------------------------------------------------------------------------------

def _bucle() -> None:
    while not _parar.wait(_intervalo()):
        volcar()


def _asegurar_hilo() -> None:
    global _hilo
    if os.environ.get("GUILDA_USO_HILO", "1").strip() in ("0", "no", "false"):
        return
    if _hilo is not None and _hilo.is_alive():
        return
    with _lock:
        if _hilo is not None and _hilo.is_alive():
            return
        _parar.clear()
        _hilo = threading.Thread(target=_bucle, name="uso-diferido", daemon=True)
        _hilo.start()


def instalar() -> None:
    """Vuelca al salir (`atexit`) y al recibir SIGTERM (systemd/Docker paran así; sin esto Python muere sin ejecutar `atexit`). Llamar una vez, desde el hilo principal."""
    global _instalado
    if _instalado or "pytest" in sys.modules:
        return
    _instalado = True
    atexit.register(volcar)
    try:
        anterior = signal.getsignal(signal.SIGTERM)

        def _al_terminar(signum, frame):
            volcar()
            if callable(anterior):
                anterior(signum, frame)
            else:
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
                os.kill(os.getpid(), signal.SIGTERM)

        signal.signal(signal.SIGTERM, _al_terminar)
    except (ValueError, OSError):                                   # fuera del hilo principal (pruebas, WSGI): vale con atexit
        pass
