"""Antivirus (ClamAV) para los archivos que suben los clientes desde su portal.

Un cliente es un tercero: sus archivos pueden venir de un ordenador infectado. Antes de guardarlos se pasan por ClamAV (el demonio `clamd`, en su propio contenedor), hablándole directamente por su
protocolo `INSTREAM` (sin dependencias nuevas). Política, explícita:

- **Apagado por defecto**: sin `CLAMAV_HOST` no se escanea nada y todo funciona como siempre. Se enciende poniendo `CLAMAV_HOST` (y `CLAMAV_PUERTO`, 3310 por defecto) en `/etc/guilda-work.env`.
- **Si detecta algo**: el archivo se rechaza, no se guarda, el cliente recibe un mensaje claro (sin el nombre de la amenaza) y el despacho recibe un aviso y una anotación en la auditoría
  (el ordenador del cliente puede estar comprometido).
- **Si el antivirus no responde** (configurado pero caído): por defecto **se rechaza** la subida con un «inténtalo más tarde» (`CLAMAV_SI_FALLA=rechazar`); con `CLAMAV_SI_FALLA=aceptar` se acepta sin
  escanear. Siempre queda anotado en el panel de salud (latido `antivirus`) para que se vea en rojo.
- **Dónde se aplica**: documentos de un vencimiento, archivos de los comentarios de tareas y facturas que sube el cliente. Los archivos del propio equipo y el correo entrante no pasan por aquí.
- Solo se manda a ClamAV el contenido (nunca nombres ni datos del cliente) y no se guarda ni se registra el contenido."""
from __future__ import annotations

import logging
import os
import socket
import struct

logger = logging.getLogger(__name__)

TROZO = 64 * 1024
MENSAJE_PELIGROSO = "El archivo no se ha podido aceptar: nuestro antivirus ha detectado en él algo peligroso. Revisa tu equipo antes de volver a enviarlo."
MENSAJE_NO_DISPONIBLE = "Ahora mismo no podemos comprobar el archivo con el antivirus. Inténtalo de nuevo dentro de unos minutos."


class ArchivoRechazado(ValueError):
    """El archivo no se acepta (amenaza detectada o antivirus no disponible). El mensaje es apto para enseñárselo al cliente."""

    def __init__(self, mensaje: str, codigo: str):
        super().__init__(mensaje)
        self.codigo = codigo


def configurado() -> bool:
    return bool(os.environ.get("CLAMAV_HOST"))


def _destino() -> tuple[str, int, float]:
    return os.environ["CLAMAV_HOST"], int(os.environ.get("CLAMAV_PUERTO", "3310")), float(os.environ.get("CLAMAV_TIMEOUT", "20"))


def _hablar(orden: bytes, datos: bytes | None = None) -> str:
    host, puerto, espera = _destino()
    with socket.create_connection((host, puerto), timeout=espera) as s:
        s.settimeout(espera)
        s.sendall(orden)
        if datos is not None:
            for i in range(0, len(datos), TROZO):
                trozo = datos[i:i + TROZO]
                s.sendall(struct.pack("!I", len(trozo)) + trozo)
            s.sendall(struct.pack("!I", 0))
        respuesta = b""
        while not respuesta.endswith(b"\0") and len(respuesta) < 4096:
            parte = s.recv(1024)
            if not parte:
                break
            respuesta += parte
    return respuesta.rstrip(b"\0\n").decode("utf-8", "replace")


def escanear(contenido: bytes) -> tuple[str, str]:
    """('limpio', '') | ('infectado', firma) | ('error', motivo). Nunca lanza."""
    try:
        r = _hablar(b"zINSTREAM\0", contenido)
    except (OSError, ValueError) as e:
        return "error", f"{type(e).__name__}: {e}"
    if r.endswith("OK"):
        return "limpio", ""
    if r.endswith("FOUND"):
        return "infectado", r.split(":", 1)[-1].replace("FOUND", "").strip()
    return "error", r[:200] or "respuesta vacía"


def disponible() -> bool:
    """¿Responde el demonio? (`PING` → `PONG`)."""
    try:
        return _hablar(b"zPING\0") == "PONG"
    except (OSError, ValueError):
        return False


def _latido(ok: bool, detalle: str) -> None:
    try:
        from . import salud
        if ok:
            salud.registrar_ok("antivirus", 7 * 24 * 3600, detalle, minimo_segundos=300)
        else:
            salud.registrar_error("antivirus", 7 * 24 * 3600, detalle)
    except Exception:  # noqa: BLE001 -- un extra: nunca rompe la subida
        logger.debug("No se pudo anotar el latido del antivirus", exc_info=True)


def exigir_limpio(nombre: str, contenido: bytes, tenant_id: int | None = None, cliente_fiscal_id: int | None = None) -> None:
    """No hace nada si el antivirus está apagado o el archivo está limpio. Lanza `ArchivoRechazado` si hay una amenaza o (según `CLAMAV_SI_FALLA`) si no se puede comprobar."""
    if not configurado():
        return
    resultado, detalle = escanear(contenido)
    if resultado == "limpio":
        _latido(True, "ClamAV responde")
        return
    if resultado == "infectado":
        _latido(True, "ClamAV responde")
        logger.warning("Antivirus: archivo de un cliente rechazado (%s)", detalle)
        _avisar_a_la_direccion(nombre, detalle, tenant_id, cliente_fiscal_id)
        raise ArchivoRechazado(MENSAJE_PELIGROSO, "virus")
    _latido(False, detalle)
    logger.error("Antivirus no disponible: %s", detalle)
    if os.environ.get("CLAMAV_SI_FALLA", "rechazar").strip().lower() == "aceptar":
        return
    raise ArchivoRechazado(MENSAJE_NO_DISPONIBLE, "antivirus_no_disponible")


def _avisar_a_la_direccion(nombre: str, firma: str, tenant_id: int | None, cliente_fiscal_id: int | None) -> None:
    """Auditoría y aviso a la dirección: el ordenador de un cliente puede estar comprometido. Nunca rompe el rechazo."""
    if not tenant_id:
        return
    try:
        from . import auditoria, db, notificaciones
        cliente = db.obtener_cliente_fiscal(tenant_id, cliente_fiscal_id) if cliente_fiscal_id else None
        quien = cliente["nombre"] if cliente else "un cliente"
        auditoria.registrar(tenant_id, None, "antivirus.rechazado", "cliente", cliente_fiscal_id, {"archivo": nombre[:150], "firma": firma[:100]})
        conn = db.get_connection()
        try:
            direccion = [f["id"] for f in conn.execute("SELECT id FROM usuarios WHERE tenant_id = ? AND supervisor_tenant = 1", (tenant_id,))]
        finally:
            conn.close()
        for u in direccion:
            notificaciones.crear_y_enviar(u, "antivirus", f"Archivo rechazado por el antivirus: {quien}", f"«{nombre[:80]}» ({firma[:60]}). Conviene avisarle: su equipo podría estar infectado.", url=f"/fiscal/clientes/{cliente_fiscal_id}" if cliente_fiscal_id else None)
    except Exception:  # noqa: BLE001
        logger.debug("No se pudo avisar del archivo rechazado", exc_info=True)
