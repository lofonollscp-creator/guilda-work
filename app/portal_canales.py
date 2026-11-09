"""Avisos del portal por SMS y WhatsApp, además del correo y las notificaciones del móvil, con Twilio como proveedor (SMS y WhatsApp con la misma cuenta).

**Opt-in estricto**: cada persona añade su móvil en «Mi cuenta», elige SMS o WhatsApp y confirma con un código que le llega a ese móvil; solo entonces se le escribe. Puede darse de baja cuando quiera (en Mi cuenta o contestando
«BAJA» o «STOP» al mensaje) y no se le vuelve a escribir. Cada despacho pone su propia cuenta de Twilio (el token vive en el almacén de credenciales del sistema, nunca en la base de datos) y paga sus mensajes, por eso hay topes:
5 mensajes al día por persona y 300 al día por despacho. Los mensajes son cortos —el título del aviso y un enlace al portal—, respetan el nivel de avisos elegido y la franja de «no molestar», y nunca llevan datos de la factura
ni importes. Para WhatsApp, que exige plantillas aprobadas para escribir primero, se usa la plantilla (Content SID) que el despacho haya dado de alta en Twilio con una variable."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from . import db, ia_claves, portal_personas, portal_silencio

logger = logging.getLogger("guilda")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_canales_config (
    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    sms_activo INTEGER NOT NULL DEFAULT 0,
    whatsapp_activo INTEGER NOT NULL DEFAULT 0,
    account_sid TEXT NOT NULL DEFAULT '',
    remitente_sms TEXT NOT NULL DEFAULT '',
    remitente_whatsapp TEXT NOT NULL DEFAULT '',
    whatsapp_content_sid TEXT NOT NULL DEFAULT '',
    actualizado_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS portal_canales_personas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    telefono TEXT NOT NULL,
    canal TEXT NOT NULL CHECK (canal IN ('sms', 'whatsapp')),
    verificado_en TEXT,
    consentimiento_en TEXT,
    baja_en TEXT,
    codigo_hash TEXT,
    codigo_vence TEXT,
    intentos INTEGER NOT NULL DEFAULT 0,
    codigos_hora TEXT,
    dia TEXT,
    enviados_dia INTEGER NOT NULL DEFAULT 0,
    creado_en TEXT NOT NULL,
    UNIQUE (tenant_id, cliente_fiscal_id, email)
);
CREATE TABLE IF NOT EXISTS portal_canales_envios (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    dia TEXT NOT NULL,
    canal TEXT NOT NULL,
    n INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, dia, canal)
);
"""
MAX_DIA_PERSONA = 5
MAX_DIA_DESPACHO = 300
VIDA_CODIGO = timedelta(minutes=10)
MAX_INTENTOS = 5
MAX_CODIGOS_HORA = 3
PALABRAS_BAJA = {"stop", "baja", "parar", "cancelar", "unsubscribe", "stopall", "para", "no"}
SERVICIO_TOKEN = "twilio"


class ErrorCanal(ValueError):
    """Mensaje legible para quien configura o activa un canal."""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _ahora(ahora: datetime | None = None) -> str:
    return (ahora or datetime.now()).isoformat(timespec="seconds")


def _email(e: str | None) -> str:
    return (e or "").strip().lower()


def telefono_e164(valor: str | None) -> str | None:
    """El móvil en formato internacional (+346…), o None si no vale. Sin prefijo, y con 9 cifras que empiezan por 6, 7 o 9, se entiende de España."""
    v = re.sub(r"[\s.\-()]", "", str(valor or ""))
    if v.startswith("00"):
        v = "+" + v[2:]
    if re.fullmatch(r"[679]\d{8}", v):
        v = "+34" + v
    return v if re.fullmatch(r"\+[1-9]\d{7,14}", v) else None


# --- Configuración del despacho ---------------------------------------------------------------------------------------------------------------------------

def config(tenant_id: int) -> dict:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM portal_canales_config WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    base = {"sms_activo": False, "whatsapp_activo": False, "account_sid": "", "remitente_sms": "", "remitente_whatsapp": "", "whatsapp_content_sid": ""}
    if f:
        base.update({"sms_activo": bool(f["sms_activo"]), "whatsapp_activo": bool(f["whatsapp_activo"]), "account_sid": f["account_sid"], "remitente_sms": f["remitente_sms"],
                     "remitente_whatsapp": f["remitente_whatsapp"], "whatsapp_content_sid": f["whatsapp_content_sid"]})
    return base


def guardar_config(tenant_id: int, *, account_sid: str, token: str, remitente_sms: str, remitente_whatsapp: str, whatsapp_content_sid: str, sms_activo: bool, whatsapp_activo: bool) -> None:
    """Guarda la cuenta de Twilio del despacho. Con el token vacío se conserva el que ya hubiera. `ErrorCanal` si algo no vale."""
    sid = (account_sid or "").strip()
    if (sms_activo or whatsapp_activo) and not re.fullmatch(r"AC[0-9a-fA-F]{32}", sid):
        raise ErrorCanal("El Account SID de Twilio no es válido (empieza por AC y tiene 34 caracteres).")
    token = (token or "").strip()
    if token:
        ia_claves.guardar_de_despacho(SERVICIO_TOKEN, tenant_id, [token])
    if (sms_activo or whatsapp_activo) and not ia_claves.de_despacho(SERVICIO_TOKEN, tenant_id):
        raise ErrorCanal("Falta el token de autenticación de Twilio.")
    rs, rw = (remitente_sms or "").strip()[:20], (remitente_whatsapp or "").strip().replace("whatsapp:", "")[:20]
    if sms_activo and not rs:
        raise ErrorCanal("Indica el remitente de los SMS (un número de Twilio o un nombre).")
    if whatsapp_activo and (not telefono_e164(rw) or not re.fullmatch(r"HX[0-9a-fA-F]{32}", (whatsapp_content_sid or "").strip())):
        raise ErrorCanal("Para WhatsApp indica el número de WhatsApp de Twilio (con prefijo, +34…) y el Content SID de tu plantilla aprobada (empieza por HX).")
    conn = db.get_connection()
    try:
        datos = (1 if sms_activo else 0, 1 if whatsapp_activo else 0, sid, rs, rw, (whatsapp_content_sid or "").strip(), _ahora())
        n = conn.execute("UPDATE portal_canales_config SET sms_activo = ?, whatsapp_activo = ?, account_sid = ?, remitente_sms = ?, remitente_whatsapp = ?, whatsapp_content_sid = ?, actualizado_en = ? WHERE tenant_id = ?", (*datos, tenant_id)).rowcount
        if not n:
            conn.execute("INSERT INTO portal_canales_config (sms_activo, whatsapp_activo, account_sid, remitente_sms, remitente_whatsapp, whatsapp_content_sid, actualizado_en, tenant_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (*datos, tenant_id))
        conn.commit()
    finally:
        conn.close()


def disponibles(tenant_id: int) -> list[str]:
    """Los canales que el despacho ha activado y puede usar: [«sms», «whatsapp»]."""
    c = config(tenant_id)
    if not (c["sms_activo"] or c["whatsapp_activo"]) or not c["account_sid"] or not ia_claves.de_despacho(SERVICIO_TOKEN, tenant_id):
        return []
    return [k for k, ok in (("sms", c["sms_activo"] and c["remitente_sms"]), ("whatsapp", c["whatsapp_activo"] and c["remitente_whatsapp"] and c["whatsapp_content_sid"])) if ok]


# --- Twilio ---------------------------------------------------------------------------------------------------------------------------------------------------

def _enviar(cfg: dict, token: str, canal: str, hacia: str, texto: str) -> tuple[bool, str]:
    """Una petición a la API de Twilio. (ok, código de error o ''). Se sustituye en las pruebas: nunca se llama a Twilio de verdad desde ellas."""
    if canal == "whatsapp":
        datos = {"From": f"whatsapp:{cfg['remitente_whatsapp']}", "To": f"whatsapp:{hacia}", "ContentSid": cfg["whatsapp_content_sid"], "ContentVariables": json.dumps({"1": texto})}
    else:
        datos = {"From": cfg["remitente_sms"], "To": hacia, "Body": texto}
    req = urllib.request.Request(f"https://api.twilio.com/2010-04-01/Accounts/{cfg['account_sid']}/Messages.json", data=urllib.parse.urlencode(datos).encode(), method="POST",
                                 headers={"Authorization": "Basic " + base64.b64encode(f"{cfg['account_sid']}:{token}".encode()).decode()})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status in (200, 201), ""
    except urllib.error.HTTPError as e:
        try:
            return False, str(json.loads(e.read().decode()).get("code", e.code))
        except ValueError:
            return False, str(e.code)
    except (urllib.error.URLError, TimeoutError):
        return False, "red"


def _mandar(tenant_id: int, canal: str, hacia: str, texto: str) -> tuple[bool, str]:
    cfg = config(tenant_id)
    tokens = ia_claves.de_despacho(SERVICIO_TOKEN, tenant_id)
    if canal not in disponibles(tenant_id) or not tokens:
        return False, "no_disponible"
    return _enviar(cfg, tokens[0], canal, hacia, texto)


def probar(tenant_id: int, canal: str, telefono: str) -> None:
    """Un mensaje de prueba a un móvil del equipo para comprobar la cuenta de Twilio. `ErrorCanal` si no sale."""
    tel = telefono_e164(telefono)
    if canal not in disponibles(tenant_id) or tel is None:
        raise ErrorCanal("Elige un canal activado y escribe un móvil válido.")
    from flask_babel import gettext as _
    ok, error = _mandar(tenant_id, canal, tel, _("Mensaje de prueba de tu portal de clientes."))
    if not ok:
        logger.info("Twilio rechazó el mensaje de prueba del despacho %s (código %s)", tenant_id, error)
        raise ErrorCanal("Twilio no ha aceptado el mensaje. Revisa la cuenta, el remitente y la plantilla.")


def _contar(conn, tenant_id: int, canal: str, hoy: str) -> None:
    n = conn.execute("UPDATE portal_canales_envios SET n = n + 1 WHERE tenant_id = ? AND dia = ? AND canal = ?", (tenant_id, hoy, canal)).rowcount
    if not n:
        conn.execute("INSERT INTO portal_canales_envios (tenant_id, dia, canal, n) VALUES (?, ?, ?, 1)", (tenant_id, hoy, canal))


def envios_del_mes(tenant_id: int, hoy: date | None = None) -> dict[str, int]:
    """Cuántos mensajes ha mandado este despacho este mes por canal (para que vea lo que le va a cobrar Twilio)."""
    hoy = hoy or date.today()
    conn = db.get_connection()
    try:
        return {f["canal"]: f["n"] for f in conn.execute("SELECT canal, SUM(n) AS n FROM portal_canales_envios WHERE tenant_id = ? AND dia >= ? GROUP BY canal", (tenant_id, hoy.replace(day=1).isoformat())).fetchall()}
    finally:
        conn.close()


# --- Alta, verificación y baja de cada persona -------------------------------------------------------------------------------------------------------

def de_persona(cliente, email: str) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT id, telefono, canal, verificado_en, baja_en FROM portal_canales_personas WHERE tenant_id = ? AND cliente_fiscal_id = ? AND email = ?", (cliente["tenant_id"], cliente["id"], _email(email))).fetchone()
    finally:
        conn.close()
    return dict(f) if f else None


def pedir_codigo(cliente, email: str, telefono: str, canal: str, ahora: datetime | None = None) -> None:
    """Apunta el móvil y le manda un código de 6 cifras para confirmarlo. `ErrorCanal` si no vale o se pide demasiado."""
    tid = cliente["tenant_id"]
    tel = telefono_e164(telefono)
    if canal not in disponibles(tid):
        raise ErrorCanal("Ese canal no está disponible.")
    if tel is None:
        raise ErrorCanal("Escribe un móvil válido, con prefijo si no es de España (por ejemplo, +33…).")
    ahora = ahora or datetime.now()
    codigo = f"{secrets.randbelow(10 ** 6):06d}"
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT id, codigos_hora FROM portal_canales_personas WHERE tenant_id = ? AND cliente_fiscal_id = ? AND email = ?", (tid, cliente["id"], _email(email))).fetchone()
        recientes = [t for t in (f["codigos_hora"].split(",") if f and f["codigos_hora"] else []) if t and datetime.fromisoformat(t) > ahora - timedelta(hours=1)]
        if len(recientes) >= MAX_CODIGOS_HORA:
            raise ErrorCanal("Has pedido demasiados códigos. Espera un rato antes de pedir otro.")
        marcas = ",".join(recientes + [_ahora(ahora)])
        datos = (tel, canal, hashlib.sha256(codigo.encode()).hexdigest(), _ahora(ahora + VIDA_CODIGO), marcas)
        if f:
            conn.execute("UPDATE portal_canales_personas SET telefono = ?, canal = ?, codigo_hash = ?, codigo_vence = ?, codigos_hora = ?, intentos = 0, verificado_en = NULL, baja_en = NULL WHERE id = ?", (*datos, f["id"]))
        else:
            conn.execute("INSERT INTO portal_canales_personas (telefono, canal, codigo_hash, codigo_vence, codigos_hora, tenant_id, cliente_fiscal_id, email, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (*datos, tid, cliente["id"], _email(email), _ahora(ahora)))
        conn.commit()
    finally:
        conn.close()
    from flask_babel import gettext as _
    ok, _err = _mandar(tid, canal, tel, _("Tu código de confirmación del portal es %(c)s. Caduca en 10 minutos.", c=codigo))
    if not ok:
        raise ErrorCanal("No se ha podido enviar el código ahora mismo. Revisa el móvil o inténtalo más tarde.")


def verificar(cliente, email: str, codigo: str, ahora: datetime | None = None) -> bool:
    """Confirma el móvil con el código recibido y registra el consentimiento. False si no cuadra o caducó (5 intentos como máximo)."""
    ahora = ahora or datetime.now()
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT id, codigo_hash, codigo_vence, intentos FROM portal_canales_personas WHERE tenant_id = ? AND cliente_fiscal_id = ? AND email = ?", (cliente["tenant_id"], cliente["id"], _email(email))).fetchone()
        if f is None or not f["codigo_hash"] or f["intentos"] >= MAX_INTENTOS or datetime.fromisoformat(f["codigo_vence"]) < ahora:
            return False
        if not hmac.compare_digest(f["codigo_hash"], hashlib.sha256((codigo or "").strip().encode()).hexdigest()):
            conn.execute("UPDATE portal_canales_personas SET intentos = intentos + 1 WHERE id = ?", (f["id"],))
            conn.commit()
            return False
        conn.execute("UPDATE portal_canales_personas SET verificado_en = ?, consentimiento_en = ?, codigo_hash = NULL, codigo_vence = NULL, intentos = 0, baja_en = NULL WHERE id = ?", (_ahora(ahora), _ahora(ahora), f["id"]))
        conn.commit()
        return True
    finally:
        conn.close()


def baja(cliente, email: str) -> None:
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM portal_canales_personas WHERE tenant_id = ? AND cliente_fiscal_id = ? AND email = ?", (cliente["tenant_id"], cliente["id"], _email(email)))
        conn.commit()
    finally:
        conn.close()


def baja_por_telefono(tenant_id: int, telefono: str) -> int:
    """Cuando alguien contesta «BAJA» o «STOP» al mensaje: se borra ese móvil de todas las fichas del despacho. Devuelve cuántas personas se dieron de baja."""
    tel = telefono_e164(telefono.replace("whatsapp:", ""))
    if tel is None:
        return 0
    conn = db.get_connection()
    try:
        n = conn.execute("DELETE FROM portal_canales_personas WHERE tenant_id = ? AND telefono = ?", (tenant_id, tel)).rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def firma_valida(token: str, url: str, parametros: dict, firma: str) -> bool:
    """La comprobación de la firma de un aviso entrante de Twilio (HMAC-SHA1 de la URL más los parámetros ordenados)."""
    cadena = url + "".join(k + str(parametros[k]) for k in sorted(parametros))
    esperada = base64.b64encode(hmac.new(token.encode(), cadena.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(esperada, firma or "")


# --- Envío de los avisos -------------------------------------------------------------------------------------------------------------------------------

def enviar(cliente, titulo: str, destino: str, accion: str | None = None, urgente: bool = False, ahora: datetime | None = None) -> int:
    """Avisa por SMS o WhatsApp a quien lo tenga confirmado y le corresponda (perfil, nivel de avisos y «no molestar»). Devuelve a cuántas personas llegó. Nunca lanza: un aviso que no sale no debe romper lo que lo provoca."""
    try:
        tid = cliente["tenant_id"]
        activos = disponibles(tid)
        if not activos:
            return 0
        from . import portal_recordatorios as pr
        url = pr.url_portal(destino, cliente["id"]) or ""
        permitidos = {p["email"] for p in portal_personas.listar(cliente) if p["rol"] in portal_personas.PERFILES_QUE_PUEDEN[accion] and (p["avisos"] == "todo" or (urgente and p["avisos"] == "urgente"))}
        ahora = ahora or datetime.now()
        hoy = ahora.date().isoformat()
        conn = db.get_connection()
        try:
            filas = conn.execute("SELECT id, email, telefono, canal, dia, enviados_dia FROM portal_canales_personas WHERE tenant_id = ? AND cliente_fiscal_id = ? AND verificado_en IS NOT NULL AND baja_en IS NULL", (tid, cliente["id"])).fetchall()
            del_dia = conn.execute("SELECT COALESCE(SUM(n), 0) FROM portal_canales_envios WHERE tenant_id = ? AND dia = ?", (tid, hoy)).fetchone()[0]
        finally:
            conn.close()
        llegados = 0
        texto = f"{titulo[:110]}"[:120] + (f" {url}" if url else "")
        for f in filas:
            if f["email"] not in permitidos or f["canal"] not in activos or portal_silencio.en_silencio(cliente, f["email"], ahora):
                continue
            if del_dia + llegados >= MAX_DIA_DESPACHO or (f["dia"] == hoy and f["enviados_dia"] >= MAX_DIA_PERSONA):
                continue
            ok, error = _mandar(tid, f["canal"], f["telefono"], texto if f["canal"] == "sms" else titulo[:110])
            conn = db.get_connection()
            try:
                if ok:
                    conn.execute("UPDATE portal_canales_personas SET dia = ?, enviados_dia = ? WHERE id = ?", (hoy, (f["enviados_dia"] + 1) if f["dia"] == hoy else 1, f["id"]))
                    _contar(conn, tid, f["canal"], hoy)
                elif error == "21610":                                         # el móvil se dio de baja por su lado en Twilio: no se insiste
                    conn.execute("DELETE FROM portal_canales_personas WHERE id = ?", (f["id"],))
                conn.commit()
            finally:
                conn.close()
            llegados += 1 if ok else 0
        return llegados
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo avisar por SMS o WhatsApp al cliente %s", cliente["id"], exc_info=True)
        return 0
