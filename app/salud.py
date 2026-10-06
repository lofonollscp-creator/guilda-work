"""Salud de la plataforma: latidos de las tareas periódicas del servidor, el
panel `/backoffice/salud` (semáforo por elemento) y el vigilante diario que
avisa por correo cuando algo está en rojo.

Estados: verde (todo bien), ámbar (atención), rojo (hay que actuar) y gris
(sin datos todavía). Una comprobación que falla nunca rompe el panel: se
muestra en gris con "no se pudo comprobar"."""
from __future__ import annotations

import logging
import os
import shutil
import time
from datetime import datetime, timedelta

from . import db, notificaciones_email

logger = logging.getLogger("guilda")

VERDE, AMBAR, ROJO, GRIS = "verde", "ambar", "rojo", "gris"
_GRAVEDAD = {VERDE: 0, GRIS: 1, AMBAR: 2, ROJO: 3}

BACKUP_VERDE_HORAS = 36
BACKUP_AMBAR_DIAS = 7
DISCO_ROJO_PORCENTAJE = 5
DISCO_AMBAR_PORCENTAJE = 15
WEBHOOKS_AMBAR = 1
WEBHOOKS_ROJO = 10

# Nombre del latido -> etiqueta. El intervalo esperado lo da cada tarea al registrarse.
ETIQUETAS_LATIDOS = {
    "correo_sync": "Sincronización de correo",
    "correo_envios": "Cola de envío de correo",
    "recordatorios_vencimientos": "Recordatorios de vencimientos (equipo)",
    "recordatorios_portal": "Recordatorios del portal (clientes)",
    "avisos_fichaje": "Avisos de fichaje",
    "resumen_ia_semanal": "Resumen semanal de IA",
    "tareas_recurrentes": "Tareas recurrentes",
    "vigilante_salud": "Vigilante de salud",
}

_ultimo_latido_escrito: dict[str, float] = {}


def registrar_ok(nombre: str, intervalo_segundos: int, detalle: str | None = None, minimo_segundos: int = 0) -> None:
    """Anota una pasada correcta. `minimo_segundos` limita la frecuencia de escritura
    (la cola de envíos pasa cada 10 s y no hace falta escribir en cada una)."""
    ahora = time.monotonic()
    if minimo_segundos and ahora - _ultimo_latido_escrito.get(nombre, -1e9) < minimo_segundos:
        return
    try:
        db.registrar_latido(nombre, True, intervalo_segundos, detalle)
        _ultimo_latido_escrito[nombre] = ahora
    except Exception:  # noqa: BLE001 -- el latido es un extra: nunca debe romper la tarea
        logger.debug("No se pudo escribir el latido %s", nombre, exc_info=True)


def registrar_error(nombre: str, intervalo_segundos: int, detalle: str) -> None:
    try:
        db.registrar_latido(nombre, False, intervalo_segundos, detalle)
    except Exception:  # noqa: BLE001
        logger.debug("No se pudo escribir el latido %s", nombre, exc_info=True)


def _item(grupo: str, clave: str, titulo: str, estado: str, detalle: str) -> dict:
    return {"grupo": grupo, "clave": clave, "titulo": titulo, "estado": estado, "detalle": detalle}


def _legible(segundos: float) -> str:
    segundos = max(0, int(segundos))
    if segundos < 120:
        return f"{segundos} s"
    if segundos < 7200:
        return f"{segundos // 60} min"
    if segundos < 172800:
        return f"{segundos // 3600} h"
    return f"{segundos // 86400} d"


def _estado_latido(nombre: str, fila, ahora: datetime) -> dict:
    etiqueta = ETIQUETAS_LATIDOS.get(nombre, nombre)
    if fila is None or (not fila["ultimo_ok"] and not fila["ultimo_error"]):
        return _item("Tareas periódicas", f"latido:{nombre}", etiqueta, GRIS, "Sin datos todavía (no se ha ejecutado desde el último arranque).")
    ok = datetime.fromisoformat(fila["ultimo_ok"]) if fila["ultimo_ok"] else None
    error = datetime.fromisoformat(fila["ultimo_error"]) if fila["ultimo_error"] else None
    if error and (ok is None or error > ok):
        return _item("Tareas periódicas", f"latido:{nombre}", etiqueta, ROJO,
                     f"Último intento con error hace {_legible((ahora - error).total_seconds())}: {fila['detalle'] or 'sin detalle'}")
    limite = max(2.5 * (fila["intervalo_segundos"] or 0), 120)
    edad = (ahora - ok).total_seconds()
    estado = VERDE if edad <= limite else (AMBAR if edad <= 2 * limite else ROJO)
    return _item("Tareas periódicas", f"latido:{nombre}", etiqueta, estado,
                 f"Última pasada correcta hace {_legible(edad)}." + (f" {fila['detalle']}" if fila["detalle"] else ""))


def _estado_backup(ahora: datetime) -> dict:
    copias = db.listar_backups()
    if not copias:
        return _item("Copias de seguridad", "backup", "Última copia de seguridad", ROJO, "No hay ninguna copia.")
    fichero = db.BACKUPS_DIR / copias[0]["nombre"]
    edad = (ahora - datetime.fromtimestamp(fichero.stat().st_mtime)).total_seconds()
    estado = VERDE if edad <= BACKUP_VERDE_HORAS * 3600 else (AMBAR if edad <= BACKUP_AMBAR_DIAS * 86400 else ROJO)
    return _item("Copias de seguridad", "backup", "Última copia de seguridad", estado,
                 f"{copias[0]['nombre']} — hace {_legible(edad)} ({copias[0]['tamano_bytes'] // 1024 // 1024} MB).")


def _estado_disco() -> dict:
    uso = shutil.disk_usage(db.DB_PATH.parent if db.DB_PATH.parent.exists() else "/")
    libre = uso.free / uso.total * 100
    estado = VERDE if libre >= DISCO_AMBAR_PORCENTAJE else (AMBAR if libre >= DISCO_ROJO_PORCENTAJE else ROJO)
    return _item("Servidor", "disco", "Espacio libre en disco", estado, f"{libre:.0f} % libre ({uso.free / 1024**3:.1f} GB de {uso.total / 1024**3:.0f} GB).")


def _estado_bd() -> dict:
    tamano = db.DB_PATH.stat().st_size if db.DB_PATH.exists() else 0
    wal = db.DB_PATH.with_name(db.DB_PATH.name + "-wal")
    if wal.exists():
        tamano += wal.stat().st_size
    return _item("Servidor", "bd", "Tamaño de la base de datos", VERDE, f"{tamano / 1024 / 1024:.1f} MB.")


def _estado_correo(ahora: datetime) -> list[dict]:
    minutos = max(int(os.environ.get("GUILDA_CORREO_SYNC_MINUTOS", "5") or 5), 1)
    limite = max(3 * minutos * 60, 900)
    items = []
    for c in db.estado_cuentas_correo_global():
        titulo = f"Correo: {c['nombre']} ({c['usuario_email']})"
        if c["ultimo_error_sincronizacion"]:
            desde = c["ultimo_error_sincronizacion_en"]
            horas = (ahora - datetime.fromisoformat(desde)).total_seconds() / 3600 if desde else 0
            items.append(_item("Correo", f"correo:{c['id']}", titulo, ROJO if horas >= 6 else AMBAR,
                               f"Error de sincronización: {c['ultimo_error_sincronizacion']}"))
        elif not c["ultima_sincronizacion"]:
            items.append(_item("Correo", f"correo:{c['id']}", titulo, GRIS, "Todavía no se ha sincronizado."))
        else:
            edad = (ahora - datetime.fromisoformat(c["ultima_sincronizacion"])).total_seconds()
            estado = VERDE if edad <= limite else (AMBAR if edad <= 4 * limite else ROJO)
            items.append(_item("Correo", f"correo:{c['id']}", titulo, estado, f"Última sincronización hace {_legible(edad)}."))
    return items


def _estado_webhooks(ahora: datetime) -> dict:
    n = db.contar_entregas_webhook_fallidas((ahora - timedelta(hours=24)).isoformat(timespec="seconds"))
    estado = VERDE if n < WEBHOOKS_AMBAR else (AMBAR if n < WEBHOOKS_ROJO else ROJO)
    return _item("Integraciones", "webhooks", "Entregas de webhooks fallidas (24 h)", estado, f"{n} intento(s) fallido(s).")


def _estado_envios(ahora: datetime) -> list[dict]:
    fallidos = db.contar_envios_correo_fallidos((ahora - timedelta(hours=24)).isoformat(timespec="seconds"))
    atascados = db.contar_envios_correo_atascados((ahora - timedelta(minutes=5)).isoformat(timespec="seconds"))
    return [
        _item("Correo", "envios_fallidos", "Envíos de correo fallidos (24 h)", VERDE if not fallidos else AMBAR, f"{fallidos} envío(s) fallido(s)."),
        _item("Correo", "envios_atascados", "Envíos pendientes con la hora vencida", VERDE if not atascados else ROJO,
              f"{atascados} envío(s) sin enviar pasados 5 minutos de su hora." if atascados else "Ninguno."),
    ]


def panel(ahora: datetime | None = None) -> list[dict]:
    """Todos los elementos del panel, cada comprobación aislada: si una falla,
    sale en gris y el resto sigue."""
    ahora = ahora or datetime.now()
    items: list[dict] = []

    def _seguro(grupo, clave, titulo, funcion):
        try:
            resultado = funcion()
            items.extend(resultado if isinstance(resultado, list) else [resultado])
        except Exception:  # noqa: BLE001
            logger.exception("Comprobación de salud fallida: %s", clave)
            items.append(_item(grupo, clave, titulo, GRIS, "No se pudo comprobar."))

    _seguro("Copias de seguridad", "backup", "Última copia de seguridad", lambda: _estado_backup(ahora))
    _seguro("Servidor", "disco", "Espacio libre en disco", _estado_disco)
    _seguro("Servidor", "bd", "Tamaño de la base de datos", _estado_bd)
    _seguro("Correo", "correo", "Cuentas de correo", lambda: _estado_correo(ahora))
    _seguro("Correo", "envios", "Envíos de correo", lambda: _estado_envios(ahora))
    _seguro("Integraciones", "webhooks", "Entregas de webhooks", lambda: _estado_webhooks(ahora))
    try:
        latidos = db.listar_latidos()
    except Exception:  # noqa: BLE001
        latidos = {}
    for nombre in ETIQUETAS_LATIDOS:
        _seguro("Tareas periódicas", f"latido:{nombre}", ETIQUETAS_LATIDOS[nombre],
                lambda n=nombre: _estado_latido(n, latidos.get(n), ahora))
    return items


def peor_estado(items: list[dict]) -> str:
    return max((i["estado"] for i in items), key=lambda e: _GRAVEDAD[e], default=VERDE)


def vigilar(ahora: datetime | None = None) -> list[str]:
    """Avisa por correo de lo que esté en ROJO, como máximo una vez al día por
    motivo. Un solo correo por pasada con los motivos nuevos. Devuelve las
    claves avisadas (vacío si no hay nada nuevo o no se pudo enviar)."""
    ahora = ahora or datetime.now()
    dia = ahora.strftime("%Y-%m-%d")
    nuevos = [i for i in panel(ahora) if i["estado"] == ROJO and not db.alerta_salud_enviada(i["clave"], dia)]
    if not nuevos:
        return []
    cuerpo = "El vigilante de salud de Guilda Work ha detectado:\n\n" + "\n".join(
        f"- {i['titulo']}: {i['detalle']}" for i in nuevos
    ) + "\n\nDetalle en /backoffice/salud. Solo se repite el aviso de cada punto una vez al día.\n"
    try:
        notificaciones_email.enviar_alerta_interna(f"[Guilda Work] {len(nuevos)} punto(s) en rojo en el panel de salud", cuerpo)
    except Exception:  # noqa: BLE001 -- sin SMTP/destinatario configurado no se puede avisar: se reintenta en la siguiente pasada
        logger.warning("No se pudo enviar el aviso de salud (¿ALERTAS_ADMIN_EMAIL / PORTAL_SMTP_*?)", exc_info=True)
        return []
    for i in nuevos:
        db.marcar_alerta_salud(i["clave"], dia)
    return [i["clave"] for i in nuevos]
