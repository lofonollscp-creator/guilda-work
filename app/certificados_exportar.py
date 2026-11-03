"""Salidas de los certificados electrónicos: calendario `.ics` con las caducidades (K2) e informe para auditoría en CSV y PDF (K6). Solo lo que ya ve la dirección del despacho en la pantalla; nada de
archivos de certificado ni claves (el módulo nunca los guarda)."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone

from . import certificados as ce
from . import db

SERVICIOS = {"acceso_buzon": "Buzón de notificaciones", "firma": "Firma", "presentacion": "Presentación de impuestos", "otro": "Otro"}
CABECERAS = ("Titular", "Cliente", "NIF", "Tipo", "Emisor", "Caduca", "Días restantes", "Estado temporal", "Estado operativo", "Custodio", "Servicios que cubre", "Cadena", "Revocación", "Renovación")


def _vivos(tenant_id: int, **filtros) -> list[dict]:
    """Los certificados que importan para controlar caducidades: sin archivados ni sustituidos."""
    return ce.listar(tenant_id, limite=2000, **filtros)


def _servicios_por_certificado(tenant_id: int) -> dict[int, list[str]]:
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT certificado_id, servicio, cliente_fiscal_id FROM certificados_vinculos WHERE tenant_id = ? AND estado = 'activo'", (tenant_id,)).fetchall()
    finally:
        conn.close()
    salida: dict[int, list[str]] = {}
    for f in filas:
        etiqueta = SERVICIOS.get(f["servicio"], f["servicio"])
        if etiqueta not in salida.setdefault(f["certificado_id"], []):
            salida[f["certificado_id"]].append(etiqueta)
    return salida


# --- Calendario ----------------------------------------------------------------------------------------------------------------------------------------

def _escapar(texto: str) -> str:
    return (texto or "").replace("\\", "\\\\").replace(";", "\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _plegar(linea: str) -> str:
    """RFC 5545: líneas de 75 octetos como mucho; la continuación empieza con un espacio. Sin partir un carácter UTF-8 a la mitad."""
    datos = linea.encode("utf-8")
    if len(datos) <= 75:
        return linea
    partes, actual = [], b""
    for caracter in linea:
        b = caracter.encode("utf-8")
        if len(actual) + len(b) > (75 if not partes else 74):
            partes.append(actual)
            actual = b""
        actual += b
    partes.append(actual)
    return "\r\n ".join(p.decode("utf-8") for p in partes)


def ics(tenant_id: int, ahora: datetime | None = None) -> str:
    """Un evento de día completo por certificado (el día en que caduca), con avisos 30 y 7 días antes. Los ya caducados hace más de 30 días no se incluyen: no avisan de nada."""
    ahora = ahora or datetime.now(timezone.utc)
    hoy = ahora.date()
    servicios = _servicios_por_certificado(tenant_id)
    lineas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Guilda Work//Certificados//ES", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:Caducidad de certificados"]
    for c in _vivos(tenant_id):
        caduca = (c.get("caduca_el") or "")[:10]
        if not caduca:
            continue
        dia = date.fromisoformat(caduca)
        if dia < hoy - timedelta(days=30):
            continue
        titular = c.get("cliente_nombre") or c.get("sujeto") or "Certificado"
        descripcion = [f"Certificado: {c.get('sujeto') or ''}", f"Emisor: {c.get('emisor') or ''}"]
        if servicios.get(c["id"]):
            descripcion.append("Lo usa para: " + ", ".join(servicios[c["id"]]))
        if c.get("custodio_nombre"):
            descripcion.append(f"Custodio: {c['custodio_nombre']}")
        lineas += ["BEGIN:VEVENT", f"UID:certificado-{c['id']}-{tenant_id}@guilda.work", f"DTSTAMP:{ahora.strftime('%Y%m%dT%H%M%SZ')}",
                   f"DTSTART;VALUE=DATE:{dia.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{(dia + timedelta(days=1)).strftime('%Y%m%d')}",
                   f"SUMMARY:{_escapar('Caduca el certificado de ' + titular)}", f"DESCRIPTION:{_escapar(chr(10).join(descripcion))}", "TRANSP:TRANSPARENT"]
        for dias in (30, 7):
            lineas += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_escapar(f'Caduca en {dias} días el certificado de ' + titular)}", f"TRIGGER:-P{dias}D", "END:VALARM"]
        lineas.append("END:VEVENT")
    lineas.append("END:VCALENDAR")
    return "\r\n".join(_plegar(l) for l in lineas) + "\r\n"


# --- Informe para auditoría ---------------------------------------------------------------------------------------------------------------------------

TEMPORAL = {"vigente": "Vigente", "caducado": "Caducado", "todavia_no_vigente": "Todavía no vigente", "desconocido": "Sin fecha"}


def _seguro(valor) -> str:
    """Una celda de CSV que empieza por = + - @ la interpretaría una hoja de cálculo como fórmula: se neutraliza."""
    t = "" if valor is None else str(valor)
    return "'" + t if t[:1] in ("=", "+", "-", "@", "\t", "\r") else t


def filas(tenant_id: int) -> list[list]:
    servicios = _servicios_por_certificado(tenant_id)
    salida = []
    for c in _vivos(tenant_id):
        salida.append([c.get("sujeto"), c.get("cliente_nombre"), c.get("nif_confirmado") or c.get("nif_sugerido"), c.get("tipo"), c.get("emisor"), (c.get("caduca_el") or "")[:10],
                       c.get("dias_restantes"), TEMPORAL.get(c.get("temporal"), c.get("temporal")), c.get("estado_operativo"), c.get("custodio_nombre"),
                       ", ".join(servicios.get(c["id"], [])), (c.get("cadena") or {}).get("resultado"), (c.get("revocacion") or {}).get("resultado"), c.get("renovacion")])
    salida.sort(key=lambda f: (f[5] == "", f[5], f[0] or ""))
    return salida


def csv_auditoria(tenant_id: int) -> str:
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(CABECERAS)
    for f in filas(tenant_id):
        escritor.writerow([_seguro(v) for v in f])
    return "\ufeff" + salida.getvalue()


def pdf_auditoria(tenant_id: int, despacho: str | None = None) -> bytes:
    from . import informes
    todas = filas(tenant_id)
    columnas = ["Titular", "Cliente", "Caduca", "Días", "Estado", "Custodio", "Servicios", "Renovación"]
    cuerpo = [[f[0] or "", f[1] or "", f[5], "" if f[6] is None else f[6], f[7] or "", f[9] or "", f[10] or "", f[13] or ""] for f in todas]
    caducados = sum(1 for f in todas if f[7] == "Caducado")
    pronto = sum(1 for f in todas if f[6] is not None and 0 <= f[6] <= 30)
    bloques = [("claves", [("Certificados", str(len(todas))), ("Caducados", str(caducados)), ("Caducan en 30 días o menos", str(pronto))]), ("seccion", "Certificados"), ("tabla", columnas, cuerpo)]
    return informes.construir_pdf("Informe de certificados electrónicos", bloques, despacho=despacho, subtitulo="Caducidades, custodios y servicios que cubre cada certificado", apaisado=True)
