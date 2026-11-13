"""Salud de la plataforma: latidos de las tareas periódicas del servidor, el
panel `/salud` del backoffice (semáforo por elemento) y el vigilante diario que
avisa por correo cuando algo está en rojo.

Estados: verde (todo bien), ámbar (atención), rojo (hay que actuar) y gris
(sin datos todavía). Una comprobación que falla nunca rompe el panel: se
muestra en gris con "no se pudo comprobar"."""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import date, datetime, timedelta

from flask_babel import gettext as _gettext

from . import db, notificaciones_email

logger = logging.getLogger("guilda")

VERDE, AMBAR, ROJO, GRIS = "verde", "ambar", "rojo", "gris"
_GRAVEDAD = {VERDE: 0, GRIS: 1, AMBAR: 2, ROJO: 3}

BACKUP_VERDE_HORAS = 36
BACKUP_AMBAR_DIAS = 7
DISCO_ROJO_PORCENTAJE = 10
DISCO_AMBAR_PORCENTAJE = 20
WEBHOOKS_AMBAR = 1
WEBHOOKS_ROJO = 10
ERRORES_VENTANA_MIN = 15
ERRORES_AMBAR = 3
ERRORES_ROJO = 10

# Nombre del latido -> etiqueta. El intervalo esperado lo da cada tarea al registrarse.
# Los textos van como funciones para traducirlos en el momento de mostrarlos.
ETIQUETAS_LATIDOS = {
    "correo_sync": lambda: _("Sincronización de correo"),
    "correo_envios": lambda: _("Cola de envío de correo"),
    "correo_seguimientos": lambda: _("Seguimiento de respuestas de correo"),
    "recordatorios_vencimientos": lambda: _("Recordatorios de vencimientos (equipo)"),
    "recordatorios_portal": lambda: _("Recordatorios del portal (clientes)"),
    "avisos_fichaje": lambda: _("Avisos de fichaje"),
    "resumen_ia_semanal": lambda: _("Resumen semanal de IA"),
    "tareas_recurrentes": lambda: _("Tareas recurrentes"),
    "apuntes_recurrentes": lambda: _("Apuntes recurrentes"),
    "marketing_envios": lambda: _("Envíos de marketing"),
    "firmas_documenso": lambda: _("Firmas de Documenso"),
    "marketing_rebotes": lambda: _("Rebotes de marketing"),
    "recordatorios_tareas": lambda: _("Recordatorios de tareas"),
    "vigilante_salud": lambda: _("Vigilante de salud"),
    "backoffice_tareas": lambda: _("Tareas del backoffice (histórico, cobros y resumen semanal)"),
}

_ultimo_latido_escrito: dict[str, float] = {}


def _(mensaje: str, **valores) -> str:
    """Texto traducible al idioma de quien mira el panel. Sin contexto de
    aplicación (hilo del vigilante, tests) devuelve el texto en español."""
    try:
        return _gettext(mensaje, **valores)
    except (RuntimeError, KeyError, AttributeError):  # sin app/Babel (hilo del vigilante, backoffice independiente, tests)
        return mensaje % valores if valores else mensaje


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


def _item(grupo: str, clave: str, titulo: str, estado: str, detalle: str, valor: float | None = None) -> dict:
    """`valor` es la medida numérica del punto (si la tiene): se guarda en el histórico para dibujar su tendencia (app/salud_historial.py)."""
    return {"grupo": grupo, "clave": clave, "titulo": titulo, "estado": estado, "detalle": detalle, "valor": valor}


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
    etiqueta = ETIQUETAS_LATIDOS[nombre]() if nombre in ETIQUETAS_LATIDOS else nombre
    if fila is None or (not fila["ultimo_ok"] and not fila["ultimo_error"]):
        return _item("Tareas periódicas", f"latido:{nombre}", etiqueta, GRIS, _("Sin datos todavía (no se ha ejecutado desde el último arranque)."))
    ok = datetime.fromisoformat(fila["ultimo_ok"]) if fila["ultimo_ok"] else None
    error = datetime.fromisoformat(fila["ultimo_error"]) if fila["ultimo_error"] else None
    if error and (ok is None or error > ok):
        return _item("Tareas periódicas", f"latido:{nombre}", etiqueta, ROJO,
                     _("Último intento con error hace %(hace)s: %(detalle)s", hace=_legible((ahora - error).total_seconds()), detalle=fila["detalle"] or _("sin detalle")))
    limite = max(2.5 * (fila["intervalo_segundos"] or 0), 120)
    edad = (ahora - ok).total_seconds()
    estado = VERDE if edad <= limite else (AMBAR if edad <= 2 * limite else ROJO)
    return _item("Tareas periódicas", f"latido:{nombre}", etiqueta, estado,
                 _("Última pasada correcta hace %(hace)s.", hace=_legible(edad)) + (f" {fila['detalle']}" if fila["detalle"] else ""))


def _estado_backup(ahora: datetime) -> dict:
    copias = db.listar_backups()
    if not copias:
        return _item("Copias de seguridad", "backup", _("Última copia de seguridad"), ROJO, _("No hay ninguna copia."))
    fichero = db.BACKUPS_DIR / copias[0]["nombre"]
    edad = (ahora - datetime.fromtimestamp(fichero.stat().st_mtime)).total_seconds()
    estado = VERDE if edad <= BACKUP_VERDE_HORAS * 3600 else (AMBAR if edad <= BACKUP_AMBAR_DIAS * 86400 else ROJO)
    return _item("Copias de seguridad", "backup", _("Última copia de seguridad"), estado,
                 _("%(nombre)s — hace %(hace)s (%(mb)s MB).", nombre=copias[0]["nombre"], hace=_legible(edad), mb=copias[0]["tamano_bytes"] // 1024 // 1024))


RESTIC_VERDE_HORAS = 36
RESTIC_ROJO_DIAS = 3


def _estado_restic_fichero(ahora: datetime, fichero: str, clave: str, titulo: str, sin_ejecutar: str, resumen) -> dict:
    """Estado de una copia de Restic a partir del JSON que deja su script: `ultimo_ok` (la última pasada sin errores), `errores` de la última y lo que cuente `resumen(estado)`."""
    ruta = db.BACKUPS_DIR / fichero
    if not ruta.exists():
        return _item("Copias de seguridad", clave, titulo, GRIS, sin_ejecutar)
    estado = json.loads(ruta.read_text(encoding="utf-8"))
    ultimo_ok = estado.get("ultimo_ok")
    errores = estado.get("errores") or []
    if not ultimo_ok:
        return _item("Copias de seguridad", clave, titulo, ROJO, _("Ninguna copia se ha completado: %(errores)s.", errores=", ".join(errores) or "—"))
    edad = (ahora - datetime.fromisoformat(ultimo_ok).replace(tzinfo=None)).total_seconds()
    if edad > RESTIC_ROJO_DIAS * 86400:
        item_estado = ROJO
    elif edad > RESTIC_VERDE_HORAS * 3600 or errores:
        item_estado = AMBAR
    else:
        item_estado = VERDE
    detalle = resumen(estado, _legible(edad))
    if errores:
        detalle += " " + _("Con fallos en la última pasada: %(errores)s.", errores=", ".join(errores))
    return _item("Copias de seguridad", clave, titulo, item_estado, detalle)


def _estado_copia_externa(ahora: datetime) -> dict:
    """Copia de Restic en otro disco (scripts/backup_restic.sh deja su estado en data/backups/restic_estado.json). Sin fichero =
    gris («no configurada»): en un entorno de desarrollo no tiene por qué existir."""
    return _estado_restic_fichero(ahora, "restic_estado.json", "restic", _("Copia de seguridad en otro disco (Restic)"), _("Todavía no se ha ejecutado ninguna copia con Restic."),
                                  lambda e, hace: _("Última copia completa hace %(hace)s (%(n)s objetivos).", hace=hace, n=e.get("objetivos", "?")))


def _estado_copia_documentos(ahora: datetime) -> dict:
    """Copia a Restic de los documentos del almacén de objetos (scripts/backup_objetos_restic.sh → data/backups/restic_objetos_estado.json)."""
    return _estado_restic_fichero(ahora, "restic_objetos_estado.json", "restic_objetos", _("Copia de los documentos del almacén de objetos (Restic)"),
                                  _("Todavía no se ha ejecutado ninguna copia de los documentos."),
                                  lambda e, hace: _("Última copia completa hace %(hace)s (%(n)s documentos nuevos).", hace=hace, n=e.get("nuevos") if e.get("nuevos") is not None else "?"))


S3_TAMANO_AVISO_GB = float(os.environ.get("GUILDA_S3_TAMANO_AVISO_GB", "20"))


def _estado_copia_s3(ahora: datetime) -> dict:
    """Segunda copia de Restic en AWS S3, fuera del servidor (scripts/copia_s3_restic.sh → data/backups/restic_s3_estado.json). Es de solo añadir: avisa cuando pesa más de S3_TAMANO_AVISO_GB (hay que podarla a mano)."""
    item = _estado_copia_s3_basico(ahora)
    try:
        tam = json.loads((db.BACKUPS_DIR / "restic_s3_estado.json").read_text(encoding="utf-8")).get("tamano_bytes")
    except (OSError, ValueError):
        tam = None
    if tam:
        item["detalle"] += " " + _("Tamaño: %(gb)s GB.", gb=f"{tam / 1024**3:.1f}")
        if tam / 1024**3 > S3_TAMANO_AVISO_GB and item["estado"] == VERDE:
            item["estado"] = AMBAR
            item["detalle"] += " " + _("Pasa de %(max)s GB: conviene podarla a mano (HOSTING.md, «Copia fuera del servidor»).", max=f"{S3_TAMANO_AVISO_GB:.0f}")
    return item


def _estado_copia_s3_basico(ahora: datetime) -> dict:
    return _estado_restic_fichero(ahora, "restic_s3_estado.json", "restic_s3", _("Copia de seguridad fuera del servidor (Restic en AWS S3)"),
                                  _("Todavía no se ha ejecutado la copia a S3."),
                                  lambda e, hace: _("Última copia en S3 completa hace %(hace)s (%(n)s snapshots nuevos).", hace=hace, n=e.get("snapshots_copiados") if e.get("snapshots_copiados") is not None else "?"))


def _estado_buzon_facturas(ahora: datetime) -> dict:
    """Buzón de facturas por correo (app/facturas_correo.py): avisa si la cuenta de algún despacho que lo usa deja de sincronizar. Gris si nadie lo usa."""
    from . import facturas_correo
    titulo = _("Buzón de facturas por correo")
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT tenant_id FROM contabilidad_despacho WHERE buzon_cuenta_id IS NOT NULL").fetchall()
    finally:
        conn.close()
    if not filas:
        return _item("Servidor", "buzon_facturas", titulo, GRIS, _("Ningún despacho lo tiene configurado."))
    malos = []
    for f in filas:
        m = facturas_correo.metricas(f["tenant_id"], dias=1)
        if m["estado"] in ("atrasado", "error"):
            malos.append(m["estado"])
    if malos:
        return _item("Servidor", "buzon_facturas", titulo, AMBAR, _("%(n)s buzón(es) sin sincronizar con normalidad: no llegan facturas por correo.", n=len(malos)))
    return _item("Servidor", "buzon_facturas", titulo, VERDE, _("%(n)s buzón(es) sincronizando.", n=len(filas)))


def _estado_uso_modulos(ahora: datetime) -> dict:
    """Qué módulos de la app se usan más (últimos 7 días): solo cuentas por módulo, sin personas ni datos (app/rendimiento.py → data/backups/uso_modulos.json)."""
    from . import rendimiento
    titulo = _("Módulos más usados (7 días)")
    uso = rendimiento.uso_de_modulos(db.BACKUPS_DIR / "uso_modulos.json", 7, ahora)
    if not uso:
        return _item("Servidor", "uso_modulos", titulo, GRIS, _("Todavía no hay datos de uso."))
    top = ", ".join(f"{m} ({n})" for m, n in uso[:6])
    return _item("Servidor", "uso_modulos", titulo, VERDE, _("Pantallas vistas por módulo: %(top)s.", top=top))


def _estado_gasto_aws(ahora: datetime) -> dict:
    """Gasto del mes en AWS frente al umbral (app/aws_costes.py). Sin claves de costes sale en gris: no es obligatorio tener AWS."""
    from . import aws_costes
    titulo = _("Gasto de AWS este mes")
    if not aws_costes.configurado():
        return _item("Servidor", "aws_gasto", titulo, GRIS, _("Sin configurar (GUILDA_AWS_COSTES_ACCESS_KEY / GUILDA_AWS_COSTES_SECRET_KEY)."))
    try:
        d = aws_costes.gasto(ahora.date())
    except aws_costes.ErrorCostes as e:
        return _item("Servidor", "aws_gasto", titulo, AMBAR, _("No se ha podido consultar el gasto: %(error)s", error=str(e)))
    umbral = aws_costes.umbral_usd()
    detalle = _("%(gasto)s USD gastados en %(mes)s", gasto=f"{d['gasto_usd']:.2f}", mes=d["mes"])
    if d["previsto_usd"] is not None:
        detalle += " " + _("(previsión a fin de mes: %(prev)s USD)", prev=f"{d['previsto_usd']:.2f}")
    detalle += _(". Umbral: %(umbral)s USD.", umbral=f"{umbral:.0f}")
    if d["servicios"]:
        detalle += " " + _("Lo que más cuesta: %(servicios)s.", servicios=", ".join(f"{n} {v:.2f}" for n, v in d["servicios"][:3]))
    return _item("Servidor", "aws_gasto", titulo, {"ok": VERDE, "aviso": AMBAR, "excedido": ROJO}[aws_costes.nivel(d, umbral)], detalle, d["gasto_usd"])


RESTAURACION_VERDE_DIAS = 40


def _estado_prueba_restauracion(ahora: datetime, s3: bool = False) -> dict:
    """Prueba mensual de restauración (scripts/verificar_restauracion_restic.sh): una copia que no se puede restaurar no vale. Con `s3`, la de la copia de AWS S3 (GUILDA_VERIFICAR_S3=1)."""
    titulo = _("Prueba de restauración de la copia en S3") if s3 else _("Prueba de restauración de la copia")
    clave = "restauracion_s3" if s3 else "restauracion"
    ruta = db.BACKUPS_DIR / ("restic_s3_restauracion.json" if s3 else "restic_estado_restauracion.json")
    if not ruta.exists():
        return _item("Copias de seguridad", clave, titulo, GRIS, _("Todavía no se ha hecho ninguna prueba de restauración."))
    estado = json.loads(ruta.read_text(encoding="utf-8"))
    fallos = sorted(k for k, v in (estado.get("comprobaciones") or {}).items() if v != "ok")
    if not estado.get("ok"):
        return _item("Copias de seguridad", clave, titulo, ROJO, _("La última prueba falló en: %(fallos)s.", fallos=", ".join(fallos) or "?"))
    edad = (ahora - datetime.fromisoformat(estado["ultimo_ok"]).replace(tzinfo=None)).total_seconds()
    item_estado = VERDE if edad <= RESTAURACION_VERDE_DIAS * 86400 else AMBAR
    return _item("Copias de seguridad", clave, titulo, item_estado, _("Última prueba correcta hace %(hace)s.", hace=_legible(edad)))


def _estado_version(ahora: datetime) -> dict:
    """La versión que corre: el último commit en disco y cuánto lleva arrancado el proceso. En ámbar si hay commits posteriores al arranque (código sin desplegar)."""
    from . import version
    titulo = _("Versión desplegada")
    v = version.estado(ahora)
    if v is None:
        return _item("Servidor", "version", titulo, GRIS, _("No se pudo leer la versión (¿sin repositorio Git?)."))
    detalle = _("%(hash)s «%(asunto)s» (commit de hace %(c)s; este proceso arrancó hace %(a)s).", hash=v["hash"], asunto=v["asunto"][:70], c=_legible(max(v["commit_hace_s"], 0)), a=_legible(max(v["corriendo_desde_s"], 0)))
    if v["pendiente"]:
        return _item("Servidor", "version", titulo, AMBAR, _("Hay código commiteado sin desplegar (falta reiniciar los servicios). ") + detalle)
    return _item("Servidor", "version", titulo, VERDE, detalle)


CALIDAD_IA_AMBAR_DIAS = 14


def _estado_calidad_ia(ahora: datetime) -> dict:
    """Evaluación semanal de la IA (scripts/calidad_ia.py): acierto del asistente y de la lectura de facturas frente a la línea base. En rojo si resiste peor las órdenes escondidas en un correo."""
    titulo = _("Calidad de la IA (evaluación semanal)")
    ruta = db.BACKUPS_DIR / "calidad_ia_estado.json"
    if not ruta.exists():
        return _item("Servidor", "calidad_ia", titulo, GRIS, _("Todavía no se ha evaluado ninguna vez."))
    e = json.loads(ruta.read_text(encoding="utf-8"))
    edad = (ahora - datetime.fromisoformat(e["fecha"]).replace(tzinfo=None)).total_seconds()
    cifra = lambda x: "?" if x is None else x      # noqa: E731 -- una evaluación inconclusa no tiene cifra
    resumen = _("Asistente %(a)s %%, facturas %(f)s %%, órdenes escondidas %(i)s %% (%(modelo)s, hace %(hace)s).", a=cifra(e["asistente"]["acierto_global"]), f=cifra(e["facturas"]["acierto_global"]), i=cifra(e.get("inyeccion")), modelo=e.get("modelo") or "?", hace=_legible(edad))
    if e.get("inyeccion") is not None and e["inyeccion"] < 100:
        return _item("Servidor", "calidad_ia", titulo, ROJO, _("El asistente ya no resiste todas las órdenes escondidas en un correo. ") + resumen, e["inyeccion"])
    if e.get("regresiones"):
        return _item("Servidor", "calidad_ia", titulo, AMBAR, _("Ha empeorado respecto a la base: %(lista)s. ", lista="; ".join(e["regresiones"][:2])) + resumen, e["asistente"]["acierto_global"])
    if e.get("inconclusas"):
        return _item("Servidor", "calidad_ia", titulo, AMBAR, _("Evaluación inconclusa (el proveedor no respondió a muchos casos): %(lista)s. ", lista=", ".join(e["inconclusas"])) + resumen)
    if edad > CALIDAD_IA_AMBAR_DIAS * 86400:
        return _item("Servidor", "calidad_ia", titulo, AMBAR, _("La última evaluación es antigua: el temporizador semanal no está funcionando. ") + resumen)
    return _item("Servidor", "calidad_ia", titulo, VERDE, resumen, e["asistente"]["acierto_global"] or 0)


RENDIMIENTO_P95_AMBAR_MS = 1500
RENDIMIENTO_LENTAS_AMBAR = 5
RENDIMIENTO_COLA_ROJO = 5
RENDIMIENTO_SWAP_AMBAR_MB = 300


def _estado_rendimiento(ahora: datetime) -> dict:
    """Cómo responde la web (app/rendimiento.py): p95 de la última hora, peticiones lentas y avisos de «todos los hilos ocupados» de waitress."""
    titulo = _("Rendimiento de la web")
    ruta = db.BACKUPS_DIR / "rendimiento_estado.json"
    if not ruta.exists():
        return _item("Servidor", "rendimiento", titulo, GRIS, _("Todavía no hay peticiones medidas."))
    e = json.loads(ruta.read_text(encoding="utf-8"))
    edad = (ahora - datetime.fromisoformat(e["fecha"]).replace(tzinfo=None)).total_seconds()
    if edad > 2 * 3600:
        return _item("Servidor", "rendimiento", titulo, GRIS, _("Sin peticiones en las últimas horas."))
    peor = e["peores"][0] if e.get("peores") else None
    resumen = _("%(n)s peticiones en la última hora: p50 %(p50)s ms, p95 %(p95)s ms, máximo %(max)s ms.", n=e["peticiones"], p50=e["p50_ms"], p95=e["p95_ms"], max=e["max_ms"])
    if peor and peor["p95_ms"] >= 1000:
        resumen += " " + _("La más lenta: %(ruta)s (p95 %(ms)s ms).", ruta=peor["ruta"], ms=peor["p95_ms"])
    if e.get("cola_saturada_hora", 0) >= RENDIMIENTO_COLA_ROJO:
        return _item("Servidor", "rendimiento", titulo, ROJO, _("Todos los hilos del servidor estuvieron ocupados %(n)s veces en la última hora: la web se queda esperando. ", n=e["cola_saturada_hora"]) + resumen, e["p95_ms"])
    if e.get("cola_saturada_dia", 0):
        return _item("Servidor", "rendimiento", titulo, AMBAR, _("Todos los hilos del servidor estuvieron ocupados %(n)s veces en las últimas 24 horas. ", n=e["cola_saturada_dia"]) + resumen, e["p95_ms"])
    if e["p95_ms"] >= RENDIMIENTO_P95_AMBAR_MS or e["lentas"] >= RENDIMIENTO_LENTAS_AMBAR:
        return _item("Servidor", "rendimiento", titulo, AMBAR, _("%(n)s peticiones tardaron más de un segundo. ", n=e["lentas"]) + resumen, e["p95_ms"])
    swap = e.get("swap_proceso_mb")
    if swap is not None and swap >= RENDIMIENTO_SWAP_AMBAR_MB:
        return _item("Servidor", "rendimiento", titulo, AMBAR, _("La app tiene %(mb)s MB en swap (memoria lenta). ", mb=swap) + resumen, e["p95_ms"])
    return _item("Servidor", "rendimiento", titulo, VERDE, resumen, e["p95_ms"])


EXPOSICION_AMBAR_HORAS = 6


def _leer_exposicion(ahora: datetime):
    ruta = db.BACKUPS_DIR / "exposicion_estado.json"
    if not ruta.exists():
        return None, None
    estado = json.loads(ruta.read_text(encoding="utf-8"))
    return estado, (ahora - datetime.fromisoformat(estado["fecha"]).replace(tzinfo=None)).total_seconds()


def _estado_exposicion(ahora: datetime) -> dict:
    """Lo que ve el mundo desde fuera (scripts/auditar_exposicion.py, cada hora): cabeceras de seguridad de cada sitio y puertos abiertos al exterior."""
    titulo = _("Exposición pública (cabeceras y puertos)")
    estado, edad = _leer_exposicion(ahora)
    if estado is None:
        return _item("Servidor", "exposicion", titulo, GRIS, _("Todavía no se ha comprobado ninguna vez."))
    if edad > EXPOSICION_AMBAR_HORAS * 3600:
        return _item("Servidor", "exposicion", titulo, AMBAR, _("La última comprobación es de hace %(hace)s: el temporizador no está funcionando.", hace=_legible(edad)))
    fallos = [f for f in estado.get("fallos", []) if not f.startswith("CrowdSec")]
    if fallos:
        return _item("Servidor", "exposicion", titulo, AMBAR, _("%(n)s problema(s): %(lista)s.", n=len(fallos), lista="; ".join(fallos[:3])), len(fallos))
    filtrados = estado.get("puertos_filtrados") or []
    extra = (" " + _("Escuchan hacia fuera, pero el cortafuegos los bloquea: %(p)s.", p=", ".join(filtrados))) if filtrados else ""
    return _item("Servidor", "exposicion", titulo, VERDE, _("%(n)s sitios con las cabeceras en orden y sin puertos inesperados abiertos.", n=len(estado.get("hosts", []))) + extra)


def _estado_crowdsec(ahora: datetime) -> dict:
    """Decisiones activas de CrowdSec. En rojo si ha baneado una IP del propio servidor (se dejaría fuera a sí mismo: ya pasó con las pruebas de 403)."""
    titulo = _("CrowdSec (bloqueos)")
    estado, edad = _leer_exposicion(ahora)
    if estado is None or "crowdsec" not in estado:
        return _item("Servidor", "crowdsec", titulo, GRIS, _("Todavía no se ha comprobado ninguna vez."))
    cs = estado["crowdsec"]
    if "error" in cs:
        return _item("Servidor", "crowdsec", titulo, AMBAR, _("No se pudo consultar CrowdSec: %(error)s", error=cs["error"]))
    if cs.get("propias_baneadas"):
        return _item("Servidor", "crowdsec", titulo, ROJO, _("CrowdSec ha baneado una IP del propio servidor: %(ips)s. Quítala con «cscli decisions delete --ip …».", ips=", ".join(cs["propias_baneadas"])))
    esc = ", ".join(f"{k.split('/')[-1]} ({v})" for k, v in list(cs.get("por_escenario", {}).items())[:3])
    return _item("Servidor", "crowdsec", titulo, VERDE, _("%(n)s bloqueos activos%(esc)s.", n=cs.get("activas", 0), esc=(": " + esc) if esc else ""), cs.get("activas", 0))


CVE_AMBAR_DIAS = 10


def _estado_dependencias(ahora: datetime) -> dict:
    """Escaneo semanal de vulnerabilidades conocidas en las dependencias instaladas (scripts/auditar_dependencias.sh → data/backups/cve_estado.json)."""
    titulo = _("Dependencias con vulnerabilidades conocidas")
    ruta = db.BACKUPS_DIR / "cve_estado.json"
    if not ruta.exists():
        return _item("Servidor", "dependencias", titulo, GRIS, _("Todavía no se ha escaneado ninguna vez."))
    estado = json.loads(ruta.read_text(encoding="utf-8"))
    edad = (ahora - datetime.fromisoformat(estado["fecha"]).replace(tzinfo=None)).total_seconds()
    vulnerables = estado.get("vulnerables") or []
    if vulnerables:
        resumen = ", ".join(f"{v['paquete']} {v['version']}" + (f" → {v['corregida'][0]}" if v.get("corregida") else "") for v in vulnerables[:4])
        return _item("Servidor", "dependencias", titulo, AMBAR, _("%(n)s paquete(s) con vulnerabilidades (escaneo hace %(hace)s): %(resumen)s.", n=len(vulnerables), hace=_legible(edad), resumen=resumen), len(vulnerables))
    if edad > CVE_AMBAR_DIAS * 86400:
        return _item("Servidor", "dependencias", titulo, AMBAR, _("El último escaneo es de hace %(hace)s: el temporizador semanal no está funcionando.", hace=_legible(edad)), 0)
    return _item("Servidor", "dependencias", titulo, VERDE, _("Sin vulnerabilidades conocidas (escaneo hace %(hace)s).", hace=_legible(edad)), 0)


def _tendencia_disco(libre_bytes: int, ahora: datetime, ruta=None) -> int | None:
    """Anota (una vez al día) el espacio libre y estima en cuántos días se llenará el disco al ritmo de los últimos 14 días. None si no crece el uso o aún hay pocos datos."""
    ruta = ruta or db.BACKUPS_DIR / "disco_tendencia.json"
    try:
        muestras = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        muestras = []
    hoy = ahora.strftime("%Y-%m-%d")
    if not muestras or muestras[-1][0] != hoy:
        muestras.append([hoy, libre_bytes])
        muestras = muestras[-30:]
        try:
            ruta.write_text(json.dumps(muestras), encoding="utf-8")
        except OSError:
            pass
    desde = (ahora - timedelta(days=14)).strftime("%Y-%m-%d")
    recientes = [m for m in muestras if m[0] >= desde]
    if len(recientes) < 3:
        return None
    dias = (datetime.fromisoformat(recientes[-1][0]) - datetime.fromisoformat(recientes[0][0])).days
    gastado = recientes[0][1] - recientes[-1][1]
    if dias <= 0 or gastado <= 0:
        return None
    return int(libre_bytes / (gastado / dias))


def _estado_disco(ahora: datetime | None = None) -> dict:
    ahora = ahora or datetime.now()
    uso = shutil.disk_usage(db.DB_PATH.parent if db.DB_PATH.parent.exists() else "/")
    libre = uso.free / uso.total * 100
    estado = VERDE if libre >= DISCO_AMBAR_PORCENTAJE else (AMBAR if libre >= DISCO_ROJO_PORCENTAJE else ROJO)
    detalle = _("%(libre)s %% libre (%(gb)s GB de %(total)s GB).", libre=f"{libre:.0f}", gb=f"{uso.free / 1024**3:.1f}", total=f"{uso.total / 1024**3:.0f}")
    dias = _tendencia_disco(uso.free, ahora)
    if dias is not None and dias < 60:
        detalle += " " + _("Al ritmo de los últimos días se llenaría en unos %(d)s días.", d=dias)
        if dias < 14:
            estado = ROJO
        elif estado == VERDE:
            estado = AMBAR
    return _item("Servidor", "disco", _("Espacio libre en disco"), estado, detalle, round(libre, 1))


def _estado_bd() -> dict:
    tamano = db.DB_PATH.stat().st_size if db.DB_PATH.exists() else 0
    wal = db.DB_PATH.with_name(db.DB_PATH.name + "-wal")
    if wal.exists():
        tamano += wal.stat().st_size
    return _item("Servidor", "bd", _("Tamaño de la base de datos"), VERDE, _("%(mb)s MB.", mb=f"{tamano / 1024 / 1024:.1f}"), round(tamano / 1024 / 1024, 1))


_PASSKEYS_CACHE: dict = {"hasta": 0.0, "ofrece": None}


def _kratos_ofrece_passkeys() -> bool | None:
    """True/False según el flujo de acceso de Kratos traiga o no el método passkey; None si no contesta. Se recuerda 5 minutos: el panel de salud se pinta a menudo."""
    import time
    if time.monotonic() < _PASSKEYS_CACHE["hasta"]:
        return _PASSKEYS_CACHE["ofrece"]
    from . import kratos
    estado, cuerpo, _cab = kratos._peticion(f"{kratos.KRATOS_PUBLIC_URL}/self-service/login/api")
    ofrece = None
    if estado == 200 and isinstance(cuerpo, dict):
        ofrece = any((n.get("attributes") or {}).get("name") == "passkey_login" for n in (cuerpo.get("ui") or {}).get("nodes", []))
    _PASSKEYS_CACHE.update(hasta=time.monotonic() + 300, ofrece=ofrece)
    return ofrece


def _estado_passkeys() -> dict:
    """Las passkeys del equipo dependen de la configuración de Kratos (deploy/kratos/kratos.yml): si tras un cambio o un reinicio dejan de ofrecerse, nadie se entera hasta que alguien las busca."""
    titulo = _("Passkeys del equipo (Kratos)")
    ofrece = _kratos_ofrece_passkeys()
    if ofrece is None:
        return _item("Servidor", "passkeys", titulo, AMBAR, _("Kratos no ha contestado: no se ha podido comprobar."))
    if not ofrece:
        return _item("Servidor", "passkeys", titulo, AMBAR, _("Kratos no ofrece el método passkey: revisa deploy/kratos/kratos.yml y reinicia su contenedor."))
    return _item("Servidor", "passkeys", titulo, VERDE, _("Kratos ofrece el acceso con passkey."))


COLA_IA_AMBAR_MIN, COLA_IA_ROJO_MIN = 15, 60            # un trabajo de IA que lleva tanto esperando sin que nadie lo coja


def _estado_cola_ia(ahora: datetime) -> dict:
    """La cola de trabajos de IA en segundo plano (app/ia_trabajos.py): el más antiguo pendiente, los atascados leyendo y los errores de las últimas 24 h. Un hilo parado se ve aquí antes que por las quejas."""
    from .bd import contexto
    with contexto.como_plataforma():
        conn = db.get_connection()
        try:
            antiguo = conn.execute("SELECT MIN(creado_en) FROM ia_trabajos WHERE estado = 'pendiente' AND (no_antes_de IS NULL OR no_antes_de <= ?)", (ahora.isoformat(timespec="seconds"),)).fetchone()[0]
            pendientes = conn.execute("SELECT COUNT(*) FROM ia_trabajos WHERE estado = 'pendiente'").fetchone()[0]
            errores = conn.execute("SELECT COUNT(*) FROM ia_trabajos WHERE estado = 'error' AND terminado_en >= ?", ((ahora - timedelta(hours=24)).isoformat(timespec="seconds"),)).fetchone()[0]
            hechas = conn.execute("SELECT COUNT(*) FROM ia_trabajos WHERE estado = 'hecha' AND terminado_en >= ?", ((ahora - timedelta(hours=24)).isoformat(timespec="seconds"),)).fetchone()[0]
        finally:
            conn.close()
    espera = max(0, int((ahora - datetime.fromisoformat(antiguo)).total_seconds() // 60)) if antiguo else 0
    estado = VERDE if espera < COLA_IA_AMBAR_MIN else (AMBAR if espera < COLA_IA_ROJO_MIN else ROJO)
    if estado == VERDE and errores and errores * 2 > errores + hechas:        # más de la mitad de lo terminado hoy ha fallado
        estado = AMBAR
    if not pendientes and not errores and not hechas:
        return _item("Servidor", "cola_ia", _("Cola de IA"), VERDE, _("Sin trabajos en las últimas 24 h."), 0)
    detalle = _("%(p)s pendiente(s), la más antigua espera %(m)s min; en 24 h: %(h)s hechas y %(e)s con error.", p=pendientes, m=espera, h=hechas, e=errores)
    return _item("Servidor", "cola_ia", _("Cola de IA"), estado, detalle, espera)


def _estado_errores(ahora: datetime) -> dict:
    """Ráfaga de respuestas 5xx del servidor en los últimos minutos (ámbar desde 3, rojo desde 10)."""
    r = db.resumen_errores_servidor((ahora - timedelta(minutes=ERRORES_VENTANA_MIN)).isoformat(timespec="seconds"))
    n = r["total"]
    estado = VERDE if n < ERRORES_AMBAR else (AMBAR if n < ERRORES_ROJO else ROJO)
    detalle = _("%(n)s error(es) 5xx en los últimos %(min)s min.", n=n, min=ERRORES_VENTANA_MIN)
    if r["ruta"] and n:
        detalle += " " + _("Más repetido: %(ruta)s (%(veces)s).", ruta=r["ruta"], veces=r["repeticiones"])
    return _item("Servidor", "errores_servidor", _("Errores del servidor (5xx)"), estado, detalle, n)


def _estado_correo(ahora: datetime) -> list[dict]:
    minutos = max(int(os.environ.get("GUILDA_CORREO_SYNC_MINUTOS", "5") or 5), 1)
    limite = max(3 * minutos * 60, 900)
    items = []
    for c in db.estado_cuentas_correo_global():
        titulo = _("Correo: %(nombre)s (%(usuario)s)", nombre=c["nombre"], usuario=c["usuario_email"])
        if c["ultimo_error_sincronizacion"]:
            desde = c["ultimo_error_sincronizacion_en"]
            horas = (ahora - datetime.fromisoformat(desde)).total_seconds() / 3600 if desde else 0
            items.append(_item("Correo", f"correo:{c['id']}", titulo, ROJO if horas >= 6 else AMBAR,
                               _("Error de sincronización: %(error)s", error=c["ultimo_error_sincronizacion"])))
        elif not c["ultima_sincronizacion"]:
            items.append(_item("Correo", f"correo:{c['id']}", titulo, GRIS, _("Todavía no se ha sincronizado.")))
        else:
            edad = (ahora - datetime.fromisoformat(c["ultima_sincronizacion"])).total_seconds()
            estado = VERDE if edad <= limite else (AMBAR if edad <= 4 * limite else ROJO)
            items.append(_item("Correo", f"correo:{c['id']}", titulo, estado, _("Última sincronización hace %(hace)s.", hace=_legible(edad))))
    return items


def _estado_webhooks(ahora: datetime) -> dict:
    n = db.contar_entregas_webhook_fallidas((ahora - timedelta(hours=24)).isoformat(timespec="seconds"))
    estado = VERDE if n < WEBHOOKS_AMBAR else (AMBAR if n < WEBHOOKS_ROJO else ROJO)
    return _item("Integraciones", "webhooks", _("Entregas de webhooks fallidas (24 h)"), estado, _("%(n)s intento(s) fallido(s).", n=n))


def _estado_envios(ahora: datetime) -> list[dict]:
    fallidos = db.contar_envios_correo_fallidos((ahora - timedelta(hours=24)).isoformat(timespec="seconds"))
    atascados = db.contar_envios_correo_atascados((ahora - timedelta(minutes=5)).isoformat(timespec="seconds"))
    return [
        _item("Correo", "envios_fallidos", _("Envíos de correo fallidos (24 h)"), VERDE if not fallidos else AMBAR, _("%(n)s envío(s) fallido(s).", n=fallidos)),
        _item("Correo", "envios_atascados", _("Envíos pendientes con la hora vencida"), VERDE if not atascados else ROJO,
              _("%(n)s envío(s) sin enviar pasados 5 minutos de su hora.", n=atascados) if atascados else _("Ninguno.")),
    ]


CERT_AMBAR_DIAS = 21
CERT_ROJO_DIAS = 7
CADUCIDAD_AMBAR_DIAS = 45
CADUCIDAD_ROJO_DIAS = 14
_CACHE_CERTIFICADOS: dict[str, tuple[float, dict]] = {}
CERT_CACHE_SEGUNDOS = 6 * 3600


def _hosts_certificados() -> list[str]:
    """Dominios cuyo certificado se vigila: GUILDA_CERT_HOSTS (separados por comas) o, si no está, el de GUILDA_URL_PUBLICA."""
    explicitos = [h.strip() for h in os.environ.get("GUILDA_CERT_HOSTS", "").split(",") if h.strip()]
    if explicitos:
        return explicitos
    base = os.environ.get("GUILDA_URL_PUBLICA", "").strip()
    host = base.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    return [host] if host else []


def _caducidad_certificado(host: str) -> datetime:
    """Fecha de caducidad del certificado que sirve `host`:443, verificándolo (cadena, nombre y vigencia).
    Lanza ssl.SSLError / OSError si no se puede verificar."""
    import socket
    import ssl

    contexto = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=8) as bruto, contexto.wrap_socket(bruto, server_hostname=host) as seguro:
        cert = seguro.getpeercert()
    return datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]))


def _estado_certificados(ahora: datetime) -> list[dict]:
    items = []
    for host in _hosts_certificados():
        titulo = _("Certificado HTTPS de %(host)s", host=host)
        try:
            en_cache = _CACHE_CERTIFICADOS.get(host)
            if en_cache and time.monotonic() - en_cache[0] < CERT_CACHE_SEGUNDOS:
                resultado = en_cache[1]
            else:
                try:
                    resultado = {"caduca": _caducidad_certificado(host)}
                except Exception as e:  # noqa: BLE001 -- certificado inválido/caducado o sin conexión
                    resultado = {"error": f"{type(e).__name__}: {e}"[:200]}
                _CACHE_CERTIFICADOS[host] = (time.monotonic(), resultado)
            if "error" in resultado:
                items.append(_item("Servidor", f"cert:{host}", titulo, ROJO, _("No se ha podido verificar: %(error)s", error=resultado["error"])))
                continue
            dias = (resultado["caduca"] - ahora).days
            estado = VERDE if dias > CERT_AMBAR_DIAS else (AMBAR if dias > CERT_ROJO_DIAS else ROJO)
            items.append(_item("Servidor", f"cert:{host}", titulo, estado, _("Caduca el %(fecha)s (en %(n)s días).", fecha=resultado["caduca"].strftime("%Y-%m-%d"), n=dias)))
        except Exception:  # noqa: BLE001
            logger.exception("Comprobación del certificado de %s", host)
            items.append(_item("Servidor", f"cert:{host}", titulo, GRIS, _("No se pudo comprobar.")))
    return items


def _caducidades_configuradas() -> list[tuple[str, date]]:
    """GUILDA_CADUCIDADES="Secreto de Microsoft=2028-10-01;Certificado del cliente X=2027-03-15": cosas que caducan y que
    nadie más vigila (secretos de aplicaciones OAuth, dominios, certificados de firma...). Lo mal escrito se ignora."""
    resultado = []
    for trozo in os.environ.get("GUILDA_CADUCIDADES", "").split(";"):
        nombre, _sep, fecha = trozo.rpartition("=")
        try:
            resultado.append((nombre.strip(), datetime.strptime(fecha.strip(), "%Y-%m-%d").date()))
        except ValueError:
            continue
    return [(n, f) for n, f in resultado if n]


def _estado_caducidades(ahora: datetime) -> list[dict]:
    items = []
    for nombre, fecha in _caducidades_configuradas():
        dias = (fecha - ahora.date()).days
        estado = VERDE if dias > CADUCIDAD_AMBAR_DIAS else (AMBAR if dias > CADUCIDAD_ROJO_DIAS else ROJO)
        detalle = _("Caduca el %(fecha)s (en %(n)s días).", fecha=fecha.isoformat(), n=dias) if dias >= 0 else _("Caducó el %(fecha)s (hace %(n)s días).", fecha=fecha.isoformat(), n=-dias)
        items.append(_item("Servidor", f"caduca:{nombre}", nombre, estado, detalle))
    return items


def _motor_postgres() -> bool:
    from . import bd
    return bd.MOTOR == "postgres"


def _estado_ensayo_restauracion_pg(ahora: datetime) -> dict:
    """Ensayo mensual de restauración de la base de datos (scripts/ensayo_restauracion_pg.py): la copia base más reciente y el WAL se restauran en una instancia aparte y se comparan las filas con producción."""
    titulo = _("Ensayo de restauración de la base de datos")
    ruta = db.BACKUPS_DIR / "pg_estado_restauracion.json"
    if not ruta.exists():
        return _item("Copias de seguridad", "restauracion_pg", titulo, GRIS, _("Todavía no se ha hecho ningún ensayo de restauración de la base de datos."))
    estado = json.loads(ruta.read_text(encoding="utf-8"))
    if not estado.get("ok"):
        fallos = sorted(k for k, v in (estado.get("comprobaciones") or {}).items() if v != "ok")
        return _item("Copias de seguridad", "restauracion_pg", titulo, ROJO, _("El último ensayo falló en: %(fallos)s.", fallos=", ".join(fallos) or estado.get("error") or "?"))
    edad = (ahora - datetime.fromisoformat(estado["ultimo_ok"]).replace(tzinfo=None)).total_seconds()
    detalle = _("Último ensayo correcto hace %(hace)s: restaurada en %(seg)s s y con las mismas filas que producción.", hace=_legible(edad), seg=estado.get("segundos_restauracion") or estado.get("segundos") or "?")
    return _item("Copias de seguridad", "restauracion_pg", titulo, VERDE if edad <= RESTAURACION_VERDE_DIAS * 86400 else AMBAR, detalle, round(estado.get("segundos_restauracion") or 0))


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
            items.append(_item(grupo, clave, titulo, GRIS, _("No se pudo comprobar.")))

    _seguro("Copias de seguridad", "backup", _("Última copia de seguridad"), lambda: _estado_backup(ahora))
    _seguro("Copias de seguridad", "restic", _("Copia de seguridad en otro disco (Restic)"), lambda: _estado_copia_externa(ahora))
    if os.environ.get("GUILDA_OBJETOS") == "s3" or (db.BACKUPS_DIR / "restic_objetos_estado.json").exists():      # solo si hay bucket que copiar
        _seguro("Copias de seguridad", "restic_objetos", _("Copia de los documentos del almacén de objetos (Restic)"), lambda: _estado_copia_documentos(ahora))
    _seguro("Copias de seguridad", "restic_s3", _("Copia de seguridad fuera del servidor (Restic en AWS S3)"), lambda: _estado_copia_s3(ahora))
    _seguro("Copias de seguridad", "restauracion", _("Prueba de restauración de la copia"), lambda: _estado_prueba_restauracion(ahora))
    _seguro("Copias de seguridad", "restauracion_s3", _("Prueba de restauración de la copia en S3"), lambda: _estado_prueba_restauracion(ahora, True))
    if _motor_postgres():
        _seguro("Copias de seguridad", "restauracion_pg", _("Ensayo de restauración de la base de datos"), lambda: _estado_ensayo_restauracion_pg(ahora))
        from . import salud_postgres
        _seguro("Base de datos", "postgres", "Base de datos PostgreSQL", salud_postgres.panel_items)
    _seguro("Servidor", "aws_gasto", _("Gasto de AWS este mes"), lambda: _estado_gasto_aws(ahora))
    _seguro("Servidor", "disco", _("Espacio libre en disco"), _estado_disco)
    _seguro("Servidor", "dependencias", _("Dependencias con vulnerabilidades conocidas"), lambda: _estado_dependencias(ahora))
    _seguro("Servidor", "version", _("Versión desplegada"), lambda: _estado_version(ahora))
    _seguro("Servidor", "calidad_ia", _("Calidad de la IA (evaluación semanal)"), lambda: _estado_calidad_ia(ahora))
    _seguro("Servidor", "rendimiento", _("Rendimiento de la web"), lambda: _estado_rendimiento(ahora))
    _seguro("Servidor", "buzon_facturas", _("Buzón de facturas por correo"), lambda: _estado_buzon_facturas(ahora))
    _seguro("Servidor", "uso_modulos", _("Módulos más usados (7 días)"), lambda: _estado_uso_modulos(ahora))
    _seguro("Servidor", "exposicion", _("Exposición pública (cabeceras y puertos)"), lambda: _estado_exposicion(ahora))
    _seguro("Servidor", "crowdsec", _("CrowdSec (bloqueos)"), lambda: _estado_crowdsec(ahora))
    _seguro("Servidor", "bd", _("Tamaño de la base de datos"), _estado_bd)
    _seguro("Servidor", "errores_servidor", _("Errores del servidor (5xx)"), lambda: _estado_errores(ahora))
    _seguro("Servidor", "cola_ia", _("Cola de IA"), lambda: _estado_cola_ia(ahora))
    _seguro("Servidor", "passkeys", _("Passkeys del equipo (Kratos)"), _estado_passkeys)
    _seguro("Servidor", "certificados", _("Certificados HTTPS"), lambda: _estado_certificados(ahora))
    _seguro("Servidor", "caducidades", _("Caducidades configuradas"), lambda: _estado_caducidades(ahora))
    _seguro("Correo", "correo", _("Cuentas de correo"), lambda: _estado_correo(ahora))
    _seguro("Correo", "envios", _("Envíos de correo"), lambda: _estado_envios(ahora))
    _seguro("Integraciones", "webhooks", _("Entregas de webhooks"), lambda: _estado_webhooks(ahora))
    try:
        latidos = db.listar_latidos()
    except Exception:  # noqa: BLE001
        latidos = {}
    for nombre in ETIQUETAS_LATIDOS:
        _seguro("Tareas periódicas", f"latido:{nombre}", ETIQUETAS_LATIDOS[nombre](),
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
    from . import salud_silencios
    items = panel(ahora)
    try:
        from . import salud_historial
        salud_historial.registrar(items, ahora)       # el histórico nunca debe impedir el aviso
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo guardar el histórico de salud")
    try:
        salud_silencios.levantar_los_resueltos({i["clave"] for i in items if i["estado"] == ROJO}, ahora)      # lo arreglado o caducado vuelve a avisar si falla otra vez
        callados = salud_silencios.activos(ahora)
    except Exception:  # noqa: BLE001 -- sin la tabla de silencios (base antigua) se avisa de todo, como antes
        callados = set()
    nuevos = [i for i in items if i["estado"] == ROJO and i["clave"] not in callados and not db.alerta_salud_enviada(i["clave"], dia)]
    if not nuevos:
        return []
    # El correo va siempre en español y sin contexto de petición (lo manda un hilo).
    cuerpo = "El vigilante de salud de Guilda Work ha detectado:\n\n" + "\n".join(
        f"- {i['titulo']}: {i['detalle']}" for i in nuevos
    ) + "\n\nDetalle en el panel Salud del backoffice. Solo se repite el aviso de cada punto una vez al día.\n"
    try:
        notificaciones_email.enviar_alerta_interna(f"[Guilda Work] {len(nuevos)} punto(s) en rojo en el panel de salud", cuerpo)
    except Exception:  # noqa: BLE001 -- sin SMTP/destinatario configurado no se puede avisar: se reintenta en la siguiente pasada
        logger.warning("No se pudo enviar el aviso de salud (¿ALERTAS_ADMIN_EMAIL / PORTAL_SMTP_*?)", exc_info=True)
        return []
    for i in nuevos:
        db.marcar_alerta_salud(i["clave"], dia)
    return [i["clave"] for i in nuevos]
