"""Los avisos que la gestoría manda a las personas de un cliente, en un solo sitio.

- `avisar()` / `correo_a()`: mandan un correo (y, si lo tienen activado, un aviso en el móvil) solo a quien, según su perfil y lo que ha elegido recibir, debe enterarse; cada correo lleva al pie el enlace para cambiar eso.
- `procesar()` (lo llama el vigilante de los recordatorios cada pocas horas): el **resumen de los lunes** para quien lo eligió y los **recordatorios escalonados** de lo que sigue esperando una respuesta del cliente
  (un documento por firmar, un modelo por revisar, movimientos del banco sin explicar): a los 3, 7 y 14 días, y al llegar a los 14 también avisa al equipo. Cada envío queda anotado y no se repite."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Callable

from . import db, notificaciones_email as ne, portal_personas, portal_push, portal_recordatorios as pr, verticales

logger = logging.getLogger("guilda")

PASOS_DIAS = (3, 7, 14)
MARGEN_DIAS = 5                  # un paso solo se envía si no han pasado más de 5 días desde que tocaba: lo que ya venía muy atrasado no se recuerda de golpe al instalar esto
MAX_PUNTOS_RESUMEN = 8
DIAS_DE_RESUMEN = (0, 1)         # lunes (y martes, por si el lunes no pudo salir)


def _idioma(cliente) -> str:
    return cliente["idioma"] if "idioma" in cliente.keys() and cliente["idioma"] else "es"


def correo_a(cliente, emails: list[str], enviar: Callable[[str], None], errores: list[str] | None = None) -> int:
    """Llama a `enviar(email)` para cada destinatario con su enlace de preferencias al pie. Un buzón roto no frena a los demás. Devuelve cuántos salieron."""
    n = 0
    for e in emails:
        try:
            with ne.con_preferencias(pr.url_preferencias(cliente["id"], e)):
                enviar(e)
            n += 1
        except ne.ErrorNotificacionesEmail as err:
            logger.warning("No se pudo mandar el aviso del portal a un contacto del cliente %s", cliente["id"])
            if errores is not None:
                errores.append(str(err)[:120])
    return n


def avisar(cliente, destino: str, texto: Callable[[], dict], *, urgente: bool = False, accion: str | None = None) -> int:
    """Avisa de algo que lleva a `destino` (una ruta del portal). `texto()` se llama ya en el idioma del cliente y devuelve {asunto, lineas, boton, push}.
    `accion`: «decidir» (firmar, pagar, dar su conformidad: solo el perfil completo) o «subir» (pedir documentos: quien puede subirlos); sin ella, todos. Devuelve cuántos correos salieron."""
    url = pr.url_portal(destino, cliente["id"])
    with pr._en_idioma(_idioma(cliente)):
        t = texto()
        enviados = 0
        if url and ne.configurado():
            enviados = correo_a(cliente, portal_personas.destinatarios(cliente, urgente, accion),
                                lambda e: ne.enviar_aviso_portal(e, t["asunto"], t["lineas"], t["boton"], url, tenant_id=cliente["tenant_id"]))
        portal_push.enviar(cliente, t["asunto"], t.get("push") or "", destino, accion, urgente)
    return enviados


def correo_directo(cliente, enviar: Callable[[str], None], *, urgente: bool = False, accion: str | None = None, push: tuple[str, str, str] | None = None, errores: list[str] | None = None) -> int:
    """Para los avisos que ya se montan con su propia función de `notificaciones_email`: la llama para quien corresponda según su perfil y lo que ha elegido recibir.
    `push`: (título, texto, ruta del portal) para avisar también en el móvil de quien lo tenga activado. Devuelve cuántos correos salieron."""
    n = correo_a(cliente, portal_personas.destinatarios(cliente, urgente, accion), enviar, errores)
    if push:
        portal_push.enviar(cliente, push[0], push[1], push[2], accion, urgente)
    return n


# --- Lo que se ha mandado ya (para no repetir nada) ---------------------------------------------------------------------------------------------------------

def _ya_enviado(conn, cliente, destinatario: str, tipo: str, referencia: str) -> bool:
    return conn.execute("SELECT 1 FROM portal_avisos_enviados WHERE tenant_id = ? AND cliente_fiscal_id = ? AND destinatario = ? AND tipo = ? AND referencia = ?",
                        (cliente["tenant_id"], cliente["id"], destinatario, tipo, referencia)).fetchone() is not None


def _anotar(conn, cliente, destinatario: str, tipo: str, referencia: str, ahora: datetime) -> bool:
    """True si lo anota ahora (nadie lo había anotado antes)."""
    try:
        conn.execute("INSERT INTO portal_avisos_enviados (tenant_id, cliente_fiscal_id, destinatario, tipo, referencia, enviado_en) VALUES (?, ?, ?, ?, ?, ?)",
                     (cliente["tenant_id"], cliente["id"], destinatario, tipo, referencia, ahora.isoformat(timespec="seconds")))
        conn.commit()
        return True
    except Exception:  # noqa: BLE001 -- el índice único: otro proceso ya lo anotó
        conn.rollback()
        return False


def paso_que_toca(edad_dias: int) -> int | None:
    """El paso (3, 7 o 14 días) que toca recordar con esta antigüedad, o None si aún es pronto o ya venía demasiado atrasado."""
    alcanzados = [p for p in PASOS_DIAS if edad_dias >= p]
    if not alcanzados or edad_dias - alcanzados[-1] > MARGEN_DIAS:
        return None
    return alcanzados[-1]


def _edad(fecha_iso: str | None, hoy: date) -> int | None:
    try:
        return (hoy - datetime.fromisoformat(str(fecha_iso)[:19]).date()).days
    except (TypeError, ValueError):
        return None


# --- Recordatorios escalonados de lo que espera al cliente ------------------------------------------------------------------------------------------------

def _esperas(cliente, hoy: date, ahora: datetime) -> list[dict]:
    """Lo que el cliente tiene pendiente de contestar y desde cuándo: [{tipo, referencia, desde, destino, accion, texto}]."""
    esperas: list[dict] = []
    vencimientos = db.listar_vencimientos_fiscales(cliente["tenant_id"], cliente_fiscal_id=cliente["id"], sin_internos=True)
    from . import portal_firma
    for v in portal_firma.pendientes(vencimientos):
        esperas.append({"tipo": "firma", "referencia": str(v["id"]), "desde": _visto_por_primera_vez(cliente, "firma_visto", str(v["id"]), ahora), "destino": f"/portal/vencimientos/{v['id']}/firma", "accion": "decidir",
                        "texto": lambda v=v: {"asunto": pr._("Tienes un documento por firmar: %(m)s", m=f"{v['modelo']} {v['periodo']}"), "boton": pr._("Firmar el documento"),
                                              "lineas": [pr._("Hola, %(nombre)s.", nombre=cliente["nombre"]), pr._("Tu gestoría te envió un documento a firmar y todavía no consta tu firma."), pr._("Te lleva directo a la página de firma.")],
                                              "push": pr._("Tienes un documento por firmar.")}})
    from . import portal_peticiones
    for pet in portal_peticiones.pendientes_del_cliente(cliente["id"])[:10]:
        esperas.append({"tipo": "peticion", "referencia": str(pet["id"]), "desde": pet["creado_en"], "destino": f"/portal/peticiones/{pet['id']}", "accion": "subir",
                        "texto": lambda pet=pet: {"asunto": pr._("Tu gestoría sigue esperando un documento: %(titulo)s", titulo=pet["titulo"]), "boton": pr._("Subir el documento"),
                                                  "lineas": [pr._("Hola, %(nombre)s.", nombre=cliente["nombre"]), pr._("Tu gestoría te pidió «%(titulo)s» y todavía no lo ha recibido.", titulo=pet["titulo"]),
                                                             pr._("Fecha límite: %(fecha)s.", fecha=pet["fecha_limite"]) if pet["fecha_limite"] else "", pet["nota"] or ""],
                                                  "push": pr._("Falta un documento que pidió tu gestoría.")}})
    if verticales.esta_activo(cliente["tenant_id"], "fiscal"):
        from . import conformidad_declaracion
        for p in conformidad_declaracion.pendientes_del_cliente(cliente["id"]):
            periodo = f"{p['periodo']} {p['ejercicio']}"
            esperas.append({"tipo": "conformidad", "referencia": str(p["id"]), "desde": p["pedida_en"], "destino": f"/portal/declaraciones/{p['id']}", "accion": "decidir",
                            "texto": lambda periodo=periodo: {"asunto": pr._("Revisa tu modelo 303 de %(periodo)s", periodo=periodo), "boton": pr._("Revisar mi modelo 303"),
                                                              "lineas": [pr._("Hola, %(nombre)s.", nombre=cliente["nombre"]), pr._("Tu gestoría te pidió que revisaras tu modelo 303 de %(periodo)s antes de presentarlo y aún no nos has contestado.", periodo=periodo),
                                                                         pr._("Si todo está bien, pulsa «De acuerdo»; si no cuadra, dínoslo desde ahí.")],
                                                              "push": pr._("Tu modelo 303 espera tu revisión.")}})
    if verticales.esta_activo(cliente["tenant_id"], "contabilizacion"):
        from . import justificantes
        sin_explicar = justificantes.pendientes_del_cliente(cliente["id"])
        if sin_explicar:
            mas_antiguo = min(sin_explicar, key=lambda j: (j["creado_en"], j["id"]))
            esperas.append({"tipo": "justificantes", "referencia": str(mas_antiguo["id"]), "desde": mas_antiguo["creado_en"], "destino": "/portal/justificantes", "accion": "subir",
                            "texto": lambda n=len(sin_explicar): {"asunto": pr._("Tu gestoría sigue esperando que le expliques unos movimientos del banco"), "boton": pr._("Ver los movimientos"),
                                                                  "lineas": [pr._("Hola, %(nombre)s.", nombre=cliente["nombre"]), pr._("Hay %(n)s movimientos de tu banco para los que tu gestoría aún no tiene factura ni justificante.", n=n),
                                                                             pr._("Cuéntanos qué son: puedes subir la factura, indicar que es un tiquet o que es algo personal.")],
                                                                  "push": pr._("Faltan por explicar movimientos de tu banco.")}})
        from . import facturas_portal
        for f in facturas_portal.devueltas_sin_atender(cliente["id"])[:5]:
            esperas.append({"tipo": "factura_devuelta", "referencia": str(f["id"]), "desde": f.get("devuelta_en"), "destino": f"/portal/facturas?trimestre={f['trimestre']}", "accion": "subir",
                            "texto": lambda f=f: {"asunto": pr._("Tienes una factura por corregir"), "boton": pr._("Corregir la factura"),
                                                  "lineas": [pr._("Hola, %(nombre)s.", nombre=cliente["nombre"]), pr._("Tu gestoría te devolvió una factura (%(tercero)s) y todavía está pendiente de que la corrijas.", tercero=f["tercero_nombre"]), f["devuelta"] or ""],
                                                  "push": pr._("Tienes una factura por corregir.")}})
    return [e for e in esperas if e["desde"]]


def _visto_por_primera_vez(cliente, tipo: str, referencia: str, ahora: datetime) -> str:
    """Para lo que no guarda cuándo empezó a esperar (un documento enviado a firmar): la primera vez que el vigilante lo ve pendiente."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT enviado_en FROM portal_avisos_enviados WHERE tenant_id = ? AND cliente_fiscal_id = ? AND destinatario = '' AND tipo = ? AND referencia = ?",
                         (cliente["tenant_id"], cliente["id"], tipo, referencia)).fetchone()
        if f is not None:
            return f["enviado_en"]
        _anotar(conn, cliente, "", tipo, referencia, ahora)
        return ahora.isoformat(timespec="seconds")
    finally:
        conn.close()


def recordar_esperas(cliente, hoy: date, ahora: datetime) -> int:
    """Un recordatorio a quien puede actuar, por cada cosa que lleva 3, 7 o 14 días esperando. Devuelve cuántos correos salieron."""
    enviados = 0
    for espera in _esperas(cliente, hoy, ahora):
        edad = _edad(espera["desde"], hoy)
        paso = paso_que_toca(edad) if edad is not None else None
        if paso is None:
            continue
        referencia = f"{espera['referencia']}:{paso}"
        conn = db.get_connection()
        try:
            pendientes = [e for e in portal_personas.destinatarios(cliente, urgente=paso >= PASOS_DIAS[-1], accion=espera["accion"]) if not _ya_enviado(conn, cliente, e, espera["tipo"], referencia)]
            # el paso se anota aunque nadie quiera correos (todos en «resumen»): así no se reintenta cada 6 horas
            if not pendientes:
                _anotar(conn, cliente, "", f"{espera['tipo']}_paso", referencia, ahora)
                continue
        finally:
            conn.close()
        url = pr.url_portal(espera["destino"], cliente["id"])
        with pr._en_idioma(_idioma(cliente)):
            t = espera["texto"]()
            t["lineas"] = [ln for ln in t["lineas"] if ln]
            if url and ne.configurado():
                def mandar(e, t=t, url=url):
                    ne.enviar_aviso_portal(e, t["asunto"], t["lineas"], t["boton"], url, tenant_id=cliente["tenant_id"])
                    c = db.get_connection()
                    try:
                        _anotar(c, cliente, e, espera["tipo"], referencia, ahora)
                    finally:
                        c.close()
                enviados += correo_a(cliente, pendientes, mandar)
            portal_push.enviar(cliente, t["asunto"], t.get("push") or "", espera["destino"], espera["accion"], paso >= PASOS_DIAS[-1])
        if paso == PASOS_DIAS[-1]:
            _avisar_al_equipo(cliente, espera, t["asunto"], ahora)
    return enviados


def _avisar_al_equipo(cliente, espera: dict, asunto: str, ahora: datetime) -> None:
    conn = db.get_connection()
    try:
        if not _anotar(conn, cliente, "", f"{espera['tipo']}_equipo", espera["referencia"], ahora):
            return
    finally:
        conn.close()
    from . import facturas_contables
    facturas_contables.avisar_al_equipo(cliente, f"{cliente['nombre']} lleva {PASOS_DIAS[-1]} días sin contestar", asunto, f"/fiscal/clientes/{cliente['id']}/editar", {"cliente_fiscal_id": cliente["id"]})


# --- El resumen de los lunes ----------------------------------------------------------------------------------------------------------------------------------

def semana(hoy: date) -> str:
    iso = hoy.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def resumen_semanal(cliente, hoy: date, ahora: datetime) -> int:
    """El resumen de lo pendiente a quien lo eligió, una vez por semana y solo si hay algo que contar (cada perfil ve lo que puede hacer). Devuelve cuántos correos salieron."""
    personas = portal_personas.para_resumen(cliente)
    if not personas or not ne.configurado():
        return 0
    referencia = semana(hoy)
    conn = db.get_connection()
    try:
        personas = [p for p in personas if not _ya_enviado(conn, cliente, p["email"], "resumen", referencia)]
    finally:
        conn.close()
    url = pr.url_portal("/portal/", cliente["id"])
    if not personas or not url:
        return 0
    from .main import app
    from . import portal_inicio
    enviados = 0
    for rol_resumen, grupo in (("completo", [p for p in personas if p["rol"] == "completo"]), ("otro", [p for p in personas if p["rol"] != "completo"])):
        if not grupo:
            continue
        with app.test_request_context("/portal/"), pr._en_idioma(_idioma(cliente)):
            puntos = portal_inicio.datos(cliente, "completo" if rol_resumen == "completo" else "administracion", hoy)["para_hacer"]
            if not puntos:
                continue
            from flask_babel import gettext as _, ngettext
            lineas = [_("Hola, %(nombre)s.", nombre=cliente["nombre"]),
                      ngettext("Esto es lo que tienes pendiente con tu gestoría: %(n)s cosa.", "Esto es lo que tienes pendiente con tu gestoría: %(n)s cosas.", len(puntos), n=len(puntos))]
            for p in puntos[:MAX_PUNTOS_RESUMEN]:
                lineas.append(f"• {p['titulo']}" + (f" ({p['detalle']})" if p["detalle"] else ""))
            if len(puntos) > MAX_PUNTOS_RESUMEN:
                lineas.append(_("…y %(n)s más.", n=len(puntos) - MAX_PUNTOS_RESUMEN))
            asunto, boton = _("Tu resumen semanal"), _("Ver mi portal")

        def mandar(e, asunto=asunto, lineas=lineas, boton=boton):
            ne.enviar_aviso_portal(e, asunto, lineas, boton, url, tenant_id=cliente["tenant_id"])
            c = db.get_connection()
            try:
                _anotar(c, cliente, e, "resumen", referencia, ahora)
            finally:
                c.close()
        enviados += correo_a(cliente, [p["email"] for p in grupo], mandar)
    return enviados


# --- Lo que lanza el vigilante ----------------------------------------------------------------------------------------------------------------------------------

def procesar(ahora: datetime | None = None) -> dict:
    """Recorre los clientes con portal: recordatorios escalonados siempre; resumen semanal los lunes (y martes). Devuelve {recordatorios, resumenes}."""
    ahora = ahora or datetime.now()
    hoy = ahora.date()
    totales = {"recordatorios": 0, "resumenes": 0}
    if not ne.configurado():
        return totales
    for tenant in db.listar_tenants():
        for cliente in db.listar_clientes_fiscales(tenant["id"]):
            try:
                if not (cliente["email"] or "").strip() and not portal_personas.listar(cliente):
                    continue
                if cliente["recordatorios_portal"] == 0:
                    continue                                              # fuera de los avisos automáticos desde su ficha
                totales["recordatorios"] += recordar_esperas(cliente, hoy, ahora)
                if hoy.weekday() in DIAS_DE_RESUMEN:
                    totales["resumenes"] += resumen_semanal(cliente, hoy, ahora)
            except Exception:  # noqa: BLE001 -- un cliente con datos raros no debe frenar a los demás
                logger.exception("No se pudieron procesar los avisos del portal del cliente %s", cliente["id"])
    return totales
