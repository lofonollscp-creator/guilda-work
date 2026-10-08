"""Correo casi instantáneo con IMAP IDLE: una conexión por cuenta IMAP que se queda esperando en la
bandeja de entrada y, cuando el servidor avisa de un cambio, lanza la sincronización de esa cuenta.
El auto-sync periódico sigue como red de seguridad (IDLE se corta, los servidores lo cierran, etc.).

`esperar_cambios` es el núcleo y se prueba solo; `GestorIdle` mantiene un hilo por cuenta."""
import logging
import os
import re
import select
import socket
import threading
import time

from . import correo, db

logger = logging.getLogger("guilda")

IDLE_MINUTOS_MAX = 20          # los servidores cortan el IDLE a los ~30 min: se renueva antes
ESPERA_ANTES_DE_SINCRONIZAR = 2.0
_CAMBIO = re.compile(rb"^\* \d+ (EXISTS|EXPUNGE|FETCH)\b", re.I)


def esperar_cambios(conn, segundos: float) -> str:
    """Pone la conexión (con una carpeta ya seleccionada) en IDLE hasta `segundos`.
    Devuelve 'cambio' (el servidor avisó de correo nuevo, borrado o banderas), 'timeout' o 'cerrada'.
    Siempre intenta terminar el IDLE con DONE, para poder reutilizar la conexión."""
    etiqueta = conn._new_tag()
    try:
        conn.send(etiqueta + b" IDLE\r\n")
        primera = conn.readline()
    except (OSError, EOFError, correo.imaplib.IMAP4.abort):
        return "cerrada"
    if not primera.startswith(b"+"):
        return "cerrada"
    resultado = "timeout"
    limite = time.monotonic() + segundos
    try:
        while True:
            resto = limite - time.monotonic()
            if resto <= 0:
                break
            listos, _, _ = select.select([conn.sock], [], [], min(resto, 30))
            if not listos:
                continue
            linea = conn.readline()
            if not linea:
                return "cerrada"
            if _CAMBIO.match(linea):
                resultado = "cambio"
                break
            if linea.startswith(etiqueta):         # el servidor terminó el IDLE por su cuenta
                return "cerrada"
        conn.send(b"DONE\r\n")
        # Hasta la respuesta etiquetada; lo que llegue mientras tanto también puede ser un cambio.
        for _ in range(50):
            linea = conn.readline()
            if not linea:
                return "cerrada"
            if _CAMBIO.match(linea):
                resultado = "cambio"
            if linea.startswith(etiqueta):
                break
    except (OSError, EOFError, socket.timeout, correo.imaplib.IMAP4.abort):
        return "cerrada"
    return resultado


class GestorIdle:
    """Mantiene un hilo IDLE por cuenta IMAP. `revisar()` lo llama el hilo del servidor cada minuto."""

    def __init__(self, maximo: int = 100):
        self.maximo = maximo
        self.hilos: dict[int, threading.Thread] = {}
        self.parar = threading.Event()
        self._bloqueo = threading.Lock()

    def revisar(self) -> int:
        """Arranca los hilos de las cuentas nuevas y suelta los que ya no existen. Devuelve cuántos hay vivos."""
        cuentas = {f["id"]: f["usuario_id"] for f in db.listar_todas_las_cuentas_correo() if _es_imap(f)}
        with self._bloqueo:
            for cuenta_id in list(self.hilos):
                if not self.hilos[cuenta_id].is_alive():
                    del self.hilos[cuenta_id]
            for cuenta_id, usuario_id in cuentas.items():
                if cuenta_id in self.hilos or len(self.hilos) >= self.maximo:
                    continue
                hilo = threading.Thread(target=self._trabajar, args=(cuenta_id, usuario_id), daemon=True, name=f"idle-{cuenta_id}")
                self.hilos[cuenta_id] = hilo
                hilo.start()
            return len(self.hilos)

    def _trabajar(self, cuenta_id: int, usuario_id: int) -> None:
        fallos = 0
        while not self.parar.is_set():
            cuenta = db.obtener_cuenta_correo(usuario_id, cuenta_id)
            if cuenta is None or cuenta["protocolo"] != "imap":
                return
            try:
                conn = correo._conectar_imap_cuenta(cuenta)
            except Exception:  # noqa: BLE001 -- contraseña mala, servidor caído...: el auto-sync ya lo cuenta y avisa
                fallos += 1
                self.parar.wait(min(900, 30 * 2 ** min(fallos, 5)))
                continue
            try:
                if "IDLE" not in correo._capacidades(conn):
                    return          # sin IDLE en este servidor: basta el auto-sync periódico
                conn.select("INBOX", readonly=True)
                fallos = 0
                while not self.parar.is_set():
                    estado = esperar_cambios(conn, IDLE_MINUTOS_MAX * 60)
                    if estado == "cerrada":
                        break
                    if estado == "cambio":
                        self.parar.wait(ESPERA_ANTES_DE_SINCRONIZAR)       # agrupa ráfagas de mensajes
                        try:
                            correo.sincronizar_bandeja(usuario_id, cuenta_id)
                        except Exception:  # noqa: BLE001
                            logger.exception("IDLE: fallo sincronizando la cuenta %s", cuenta_id)
                            break
            except Exception:  # noqa: BLE001
                fallos += 1
                logger.exception("IDLE: error en la cuenta %s", cuenta_id)
            finally:
                try:
                    conn.logout()
                except Exception:  # noqa: BLE001
                    pass
            self.parar.wait(min(300, 10 * 2 ** min(fallos, 5)))


def _es_imap(fila) -> bool:
    try:
        return fila["protocolo"] == "imap"
    except (KeyError, IndexError):
        return True


def habilitado() -> bool:
    return os.environ.get("GUILDA_CORREO_IDLE", "1").strip() not in ("0", "no", "false", "")


def maximo_cuentas() -> int:
    try:
        return max(1, int(os.environ.get("GUILDA_CORREO_IDLE_MAX", "100")))
    except ValueError:
        return 100
