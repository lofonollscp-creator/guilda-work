"""Conectores de envío de marketing con **Brevo** y **Mailchimp** (ver app/marketing.py). Cada despacho usa su propia cuenta y su propia clave.

Qué hace cada conector, siempre en este orden:
1. **Subir solo a quien Guilda autoriza.** Guilda decide la audiencia (consentimiento vigente, sin bajas ni rebotes) y sube SOLO esos contactos: en Brevo, a una lista nueva por envío; en Mailchimp,
   a la audiencia que indica el despacho y a un segmento estático por envío. El proveedor nunca recibe a alguien sin consentimiento registrado.
2. **Crear la campaña con el HTML de Guilda** y enviarla. El enlace de baja y el nombre son las etiquetas del propio proveedor (cada uno gestiona su baja).
3. **Traer de vuelta las bajas y los rebotes** (`bajas()`), que Guilda aplica a su registro de consentimientos: lo que se da de baja allí queda de baja aquí.

Los puntos de acceso y los campos están tomados de la documentación oficial de cada API (Brevo v3: `api-key`, `/contacts/lists`, `/contacts`, `/emailCampaigns/{id}/sendNow`; Mailchimp Marketing 3.0:
`/lists/{id}/members/{hash}`, `/lists/{id}/segments`, `/campaigns`, `/campaigns/{id}/content`, `/campaigns/{id}/actions/send`). **No se han probado contra las cuentas reales**: el botón «Probar conexión» de
la pantalla de canales es el primer contraste, y un primer envío a una audiencia pequeña de prueba, el segundo. Las claves se guardan como el resto de claves de integración del despacho (texto en su base de datos)."""
from __future__ import annotations

import base64
import hashlib
import json
import urllib.error
import urllib.request

TIMEOUT_SEGUNDOS = 20
MAX_CONTACTOS_POR_ENVIO = 2000           # se suben de uno en uno (sin importación masiva): para más, usar el CSV de la audiencia en la propia herramienta


class ErrorProveedor(Exception):
    """Un error del proveedor con un texto legible para la persona."""


def _peticion(metodo: str, url: str, cabeceras: dict, cuerpo: dict | None = None):
    """(estado HTTP, JSON de la respuesta o {}). Los errores de red se convierten en `ErrorProveedor`."""
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo, headers={"Accept": "application/json", **({"Content-Type": "application/json"} if datos else {}), **cabeceras})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as r:
            crudo = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(crudo) if crudo.strip() else {})
    except urllib.error.HTTPError as e:
        crudo = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(crudo)
        except ValueError:
            return e.code, {"message": crudo[:300]}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErrorProveedor(f"No se ha podido conectar con el proveedor: {getattr(e, 'reason', e)}") from e


def _mensaje(cuerpo) -> str:
    if isinstance(cuerpo, dict):
        return str(cuerpo.get("message") or cuerpo.get("detail") or cuerpo.get("title") or cuerpo)[:300]
    return str(cuerpo)[:300]


class Brevo:
    nombre = "brevo"
    base = "https://api.brevo.com/v3"
    etiquetas = {"nombre": "{{ contact.FIRSTNAME }}", "email": "{{ contact.EMAIL }}", "enlace_baja": "{{ unsubscribe }}"}

    def __init__(self, clave: str, ajustes: dict):
        self.clave, self.ajustes = clave, ajustes

    def _llamar(self, metodo, ruta, cuerpo=None, ok=(200, 201, 204)):
        estado, r = _peticion(metodo, self.base + ruta, {"api-key": self.clave}, cuerpo)
        if estado not in ok:
            raise ErrorProveedor(f"Brevo respondió {estado}: {_mensaje(r)}")
        return r

    def verificar(self) -> str:
        r = self._llamar("GET", "/account")
        return str(r.get("companyName") or r.get("email") or "cuenta de Brevo")

    def _carpeta(self) -> int:
        if self.ajustes.get("carpeta_id"):
            return int(self.ajustes["carpeta_id"])
        r = self._llamar("GET", "/contacts/folders?limit=50&offset=0")
        carpetas = r.get("folders") or []
        if not carpetas:
            raise ErrorProveedor("La cuenta de Brevo no tiene ninguna carpeta de contactos: crea una en Brevo (Contactos → Listas).")
        return int(carpetas[0]["id"])

    def enviar(self, nombre: str, asunto: str, html: str, destinatarios: list[dict]) -> dict:
        """Sube los destinatarios a una lista nueva, crea la campaña y la envía. Devuelve la referencia `{lista, campana}`."""
        if len(destinatarios) > MAX_CONTACTOS_POR_ENVIO:
            raise ErrorProveedor(f"Más de {MAX_CONTACTOS_POR_ENVIO} destinatarios: divide el grupo o usa el CSV en Brevo.")
        remitente = {"name": self.ajustes.get("remitente_nombre") or "", "email": self.ajustes.get("remitente_email") or ""}
        if not remitente["email"]:
            raise ErrorProveedor("Falta el correo remitente de Brevo.")
        lista = int(self._llamar("POST", "/contacts/lists", {"name": nombre[:100], "folderId": self._carpeta()}, ok=(200, 201))["id"])
        for d in destinatarios:
            cuerpo = {"email": d["email"], "listIds": [lista], "updateEnabled": True, "attributes": {"FIRSTNAME": d["nombre"] or ""}}
            estado, r = _peticion("POST", self.base + "/contacts", {"api-key": self.clave}, cuerpo)
            if estado == 400:                                         # el atributo puede no existir en la cuenta: se reintenta sin él
                estado, r = _peticion("POST", self.base + "/contacts", {"api-key": self.clave}, {k: v for k, v in cuerpo.items() if k != "attributes"})
            if estado not in (200, 201, 204):
                raise ErrorProveedor(f"Brevo no aceptó a {d['email']}: {_mensaje(r)}")
        campana = int(self._llamar("POST", "/emailCampaigns", {"name": nombre[:100], "subject": asunto, "sender": remitente, "htmlContent": html, "recipients": {"listIds": [lista]}}, ok=(200, 201))["id"])
        self._llamar("POST", f"/emailCampaigns/{campana}/sendNow", ok=(200, 201, 204))
        return {"lista": lista, "campana": campana}

    def bajas(self, ref: dict) -> dict:
        """Los correos de la lista del envío que ya no pueden recibir correo (bajas, y en Brevo también rebotes duros): `{baja: [...], rebotado: []}`."""
        baja, offset = [], 0
        while True:
            r = self._llamar("GET", f"/contacts/lists/{ref['lista']}/contacts?limit=500&offset={offset}")
            contactos = r.get("contacts") or []
            baja += [c["email"].lower() for c in contactos if c.get("emailBlacklisted") and c.get("email")]
            offset += 500
            if offset >= int(r.get("count") or 0) or not contactos:
                return {"baja": baja, "rebotado": []}


class Mailchimp:
    nombre = "mailchimp"
    etiquetas = {"nombre": "*|FNAME|*", "email": "*|EMAIL|*", "enlace_baja": "*|UNSUB|*"}

    def __init__(self, clave: str, ajustes: dict):
        self.clave, self.ajustes = clave, ajustes
        servidor = clave.rsplit("-", 1)[-1] if "-" in clave else ""
        self.base = f"https://{servidor}.api.mailchimp.com/3.0"

    def _llamar(self, metodo, ruta, cuerpo=None, ok=(200, 204)):
        if not self.clave or "-" not in self.clave:
            raise ErrorProveedor("La clave de Mailchimp debe terminar en el centro de datos, p. ej. «…-us21».")
        autorizacion = "Basic " + base64.b64encode(f"guilda:{self.clave}".encode()).decode()
        estado, r = _peticion(metodo, self.base + ruta, {"Authorization": autorizacion}, cuerpo)
        if estado not in ok:
            raise ErrorProveedor(f"Mailchimp respondió {estado}: {_mensaje(r)}")
        return r

    def verificar(self) -> str:
        self._llamar("GET", "/ping")
        if self.ajustes.get("audiencia_id"):
            r = self._llamar("GET", f"/lists/{self.ajustes['audiencia_id']}?fields=name")
            return f"audiencia «{r.get('name', self.ajustes['audiencia_id'])}»"
        return "conexión correcta (falta indicar la audiencia)"

    def enviar(self, nombre: str, asunto: str, html: str, destinatarios: list[dict]) -> dict:
        """Sube los destinatarios a la audiencia, los agrupa en un segmento estático nuevo, crea la campaña solo para ese segmento y la envía."""
        audiencia = self.ajustes.get("audiencia_id")
        if not audiencia:
            raise ErrorProveedor("Falta el identificador de la audiencia de Mailchimp.")
        if len(destinatarios) > MAX_CONTACTOS_POR_ENVIO:
            raise ErrorProveedor(f"Más de {MAX_CONTACTOS_POR_ENVIO} destinatarios: divide el grupo o usa el CSV en Mailchimp.")
        if not self.ajustes.get("remitente_email"):
            raise ErrorProveedor("Falta el correo de respuesta de Mailchimp.")
        for d in destinatarios:
            huella = hashlib.md5(d["email"].lower().encode()).hexdigest()           # noqa: S324 -- lo exige la API de Mailchimp (hash del correo)
            self._llamar("PUT", f"/lists/{audiencia}/members/{huella}", {"email_address": d["email"], "status_if_new": "subscribed", "merge_fields": {"FNAME": d["nombre"] or ""}})
        segmento = int(self._llamar("POST", f"/lists/{audiencia}/segments", {"name": nombre[:100], "static_segment": [d["email"] for d in destinatarios]})["id"])
        campana = self._llamar("POST", "/campaigns", {"type": "regular", "recipients": {"list_id": audiencia, "segment_opts": {"saved_segment_id": segmento}},
                                                       "settings": {"subject_line": asunto, "title": nombre[:100], "from_name": self.ajustes.get("remitente_nombre") or "", "reply_to": self.ajustes["remitente_email"]}})["id"]
        self._llamar("PUT", f"/campaigns/{campana}/content", {"html": html})
        self._llamar("POST", f"/campaigns/{campana}/actions/send", ok=(200, 204))
        return {"audiencia": audiencia, "segmento": segmento, "campana": campana}

    def bajas(self, ref: dict) -> dict:
        """Bajas (`unsubscribed`) y rebotes duros (`cleaned`) de la audiencia."""
        salida = {"baja": [], "rebotado": []}
        for estado, clave in (("unsubscribed", "baja"), ("cleaned", "rebotado")):
            offset = 0
            while True:
                r = self._llamar("GET", f"/lists/{ref['audiencia']}/members?status={estado}&count=1000&offset={offset}&fields=members.email_address,total_items")
                miembros = r.get("members") or []
                salida[clave] += [m["email_address"].lower() for m in miembros if m.get("email_address")]
                offset += 1000
                if offset >= int(r.get("total_items") or 0) or not miembros:
                    break
        return salida


PROVEEDORES = {"brevo": Brevo, "mailchimp": Mailchimp}
NOMBRES = {"brevo": "Brevo", "mailchimp": "Mailchimp"}
