"""Controles de una factura antes de darla por buena (L2 y L3): posibles duplicados y avisos que no impiden exportar pero conviene mirar (NIF mal escrito, numeración con huecos, fechas raras,
proveedor igual al propio cliente, NIF intracomunitario sin formato). Los `problemas` de `facturas_contables` bloquean; esto avisa. Sin tablas: se calcula al vuelo con las facturas del cliente."""
from __future__ import annotations

import re
from datetime import date, timedelta

from flask_babel import gettext as _

from . import db, vies
from .fiscal_modelos.validacion_apuntes import FORMATOS_NIF_IVA, nif_espanol_valido  # noqa: F401 -- el mismo dígito de control que usan los apuntes fiscales

OPERACIONES_INTRACOMUNITARIAS = {"emitida": ("03", "04"), "recibida": ("03", "08")}
LIMITE_SIMPLIFICADA_CENTIMOS = 40000                # una factura simplificada no puede pasar de 400 euros (3.000 en comercio al por menor, hostelería y otros sectores)
ANIOS_MAXIMOS = 4                                   # pasado ese tiempo el IVA de una factura ya no se puede deducir


def _nif(valor) -> str:
    return re.sub(r"[\s.\-]", "", str(valor or "")).upper()


def nif_ue_con_formato(nif: str) -> bool | None:
    """True/False según el NIF-IVA lleve (o no) el prefijo de un país de la UE con el formato de ese país; None si está vacío."""
    n = _nif(nif)
    if not n:
        return None
    patron = FORMATOS_NIF_IVA.get(n[:2])
    return bool(patron and re.fullmatch(patron, n))


def comprobar_vies(nif: str) -> dict:
    """Pregunta al VIES si el NIF-IVA de otro país de la UE está dado de alta (con la caché de `app/vies.py`): {valido: bool|None, error}. `valido` es None si el servicio no contestó (no es un «no»)."""
    if vies.separar(nif) is None:
        return {"valido": None, "error": _("El NIF debe empezar por el código del país de la UE (por ejemplo FR o DE).")}
    valido = vies.valido(nif)
    return {"valido": valido, "error": "" if valido is not None else _("El servicio VIES no contestó: inténtalo más tarde.")}


# --- Duplicados ---------------------------------------------------------------------------------------------------------------------------------------

def duplicados(tenant_id: int, f: dict) -> list[dict]:
    """Facturas del mismo cliente (no descartadas) que pueden ser esta misma: [{id, numero, fecha, estado, motivo, contabilizada}].
    Motivos: «mismo número» (mismo NIF y número), «mismo importe y fecha» (mismo NIF, tres días de margen) y «mismo número e importe» (cuando a alguna le falta el NIF). Un abono y su factura no se
    consideran repetidas. `contabilizada` es True si la otra ya está revisada o exportada: dar por buena esta duplicaría el apunte."""
    nif = _nif(f.get("tercero_nif"))
    conn = db.get_connection()
    try:
        otras = [dict(o) for o in conn.execute(
            "SELECT id, numero, fecha, estado, total_centimos, tercero_nif, abono FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND id != ? AND estado != 'descartada' AND tipo = ? "
            "ORDER BY id LIMIT 2000", (tenant_id, f["cliente_fiscal_id"], f.get("id") or 0, f["tipo"]))]
    finally:
        conn.close()
    numero = str(f.get("numero") or "").strip().upper()
    con_numero = bool(numero) and numero != "(POR LEER)"
    total = f.get("total_centimos") or 0
    res = []
    for o in otras:
        if bool(o["abono"]) != bool(f.get("abono")):
            continue
        nif_o = _nif(o["tercero_nif"])
        mismo_numero = con_numero and o["numero"].strip().upper() == numero
        if nif and nif_o and nif == nif_o:
            if mismo_numero:
                motivo = "mismo número"
            elif total and o["total_centimos"] == total and _dias_entre(o["fecha"], f.get("fecha")) <= 3:
                motivo = "mismo importe y fecha"
            else:
                continue
        elif (not nif or not nif_o) and mismo_numero and total and o["total_centimos"] == total:
            motivo = "mismo número e importe"
        else:
            continue
        res.append({"id": o["id"], "numero": o["numero"], "fecha": o["fecha"], "estado": o["estado"], "motivo": motivo, "contabilizada": o["estado"] in ("revisada", "exportada")})
    return res


def _dias_entre(a, b) -> int:
    try:
        return abs((date.fromisoformat(str(a)[:10]) - date.fromisoformat(str(b)[:10])).days)
    except ValueError:
        return 9999


def ya_contabilizada(tenant_id: int, f: dict) -> dict | None:
    """La primera factura ya revisada o exportada de la que esta parece copia, o None. Solo cuenta el mismo número: el mismo importe y fecha es un aviso, porque hay compras repetidas legítimas."""
    return next((d for d in duplicados(tenant_id, f) if d["contabilizada"] and d["motivo"] != "mismo importe y fecha"), None)


# --- Avisos ---------------------------------------------------------------------------------------------------------------------------------------------

def _hueco_de_numeracion(tenant_id: int, f: dict) -> str | None:
    """En una factura emitida con número acabado en cifras, avisa si no existe la anterior de su misma serie habiendo otras anteriores (¿falta una factura?)."""
    m = re.fullmatch(r"(.*?)(\d+)", str(f.get("numero") or "").strip())
    if not m or f["tipo"] != "emitida" or f.get("abono"):
        return None
    prefijo, cifras = m.group(1), m.group(2)
    n = int(cifras)
    if n <= 1:
        return None
    conn = db.get_connection()
    try:
        numeros = [r["numero"] for r in conn.execute("SELECT numero FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND tipo = 'emitida' AND abono = 0 AND estado != 'descartada' AND id != ?",
                                                      (tenant_id, f["cliente_fiscal_id"], f.get("id") or 0))]
    finally:
        conn.close()
    de_la_serie = set()
    for x in numeros:
        mx = re.fullmatch(r"(.*?)(\d+)", x.strip())
        if mx and mx.group(1) == prefijo:
            de_la_serie.add(int(mx.group(2)))
    anteriores = [x for x in de_la_serie if x < n]
    if not anteriores or (n - 1) in de_la_serie:
        return None
    return _("En la numeración falta la factura %(falta)s: la anterior que hay es la %(anterior)s.", falta=f"{prefijo}{str(n - 1).zfill(len(cifras))}", anterior=f"{prefijo}{str(max(anteriores)).zfill(len(cifras))}")


def _clave_numero(numero) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(numero or "").upper()).lstrip("0")


def _avisos_del_abono(tenant_id: int, f: dict) -> list[str]:
    """Un abono o rectificativa frente a la factura que rectifica, si está en este cliente: que exista, que no la supere y que entre todos sus abonos no pasen de lo facturado. Solo avisa: la
    factura original puede estar ya contabilizada en a3 y no estar aquí."""
    numero = _clave_numero(f.get("rectifica_numero"))
    if not f.get("abono") or not numero:
        return []
    nif = _nif(f.get("tercero_nif"))
    conn = db.get_connection()
    try:
        filas = [dict(r) for r in conn.execute("SELECT id, numero, total_centimos, abono, tercero_nif, rectifica_numero, estado FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND tipo = ? "
                                              "AND id != ? AND estado != 'descartada' ORDER BY id LIMIT 3000", (tenant_id, f["cliente_fiscal_id"], f["tipo"], f.get("id") or 0))]
    finally:
        conn.close()
    mismas = [r for r in filas if not nif or not _nif(r["tercero_nif"]) or _nif(r["tercero_nif"]) == nif]
    original = next((r for r in mismas if not r["abono"] and _clave_numero(r["numero"]) == numero), None)
    if original is None:
        return [_("No tengo en este cliente la factura %(numero)s que rectifica: si ya está contabilizada en a3 no pasa nada, si no, falta anotarla.", numero=f["rectifica_numero"])]
    total = abs(f.get("total_centimos") or 0)
    res = []
    if total > original["total_centimos"]:
        res.append(_("El abono (%(abono)s) es mayor que la factura que rectifica (%(original)s).", abono=f"{total / 100:.2f}", original=f"{original['total_centimos'] / 100:.2f}"))
    otros = sum(abs(r["total_centimos"]) for r in mismas if r["abono"] and _clave_numero(r["rectifica_numero"]) == numero)
    if total <= original["total_centimos"] and otros + total > original["total_centimos"]:
        res.append(_("Entre este abono y los anteriores (%(suma)s) se supera lo facturado en la factura %(numero)s (%(original)s).", suma=f"{(otros + total) / 100:.2f}", numero=original["numero"],
                     original=f"{original['total_centimos'] / 100:.2f}"))
    return res


def avisos(tenant_id: int, f: dict, hoy: date | None = None) -> list[str]:
    """Lo que conviene mirar de esta factura aunque no impida exportarla (lista vacía = nada que señalar)."""
    from . import facturas_contables as fc
    hoy = hoy or date.today()
    res = []
    nif = _nif(f.get("tercero_nif"))
    if nif:
        if nif_espanol_valido(nif) is False:
            res.append(_("El NIF %(nif)s no supera su dígito de control: puede estar mal escrito o mal leído.", nif=nif))
        cliente = db.obtener_cliente_fiscal_por_id(f["cliente_fiscal_id"])
        if cliente is not None and _nif(cliente["nif"]) == nif:
            res.append(_("El NIF del proveedor o cliente es el del propio titular: ¿se han cruzado el emisor y el receptor?"))
    intracomunitarias = OPERACIONES_INTRACOMUNITARIAS.get(f["tipo"], ())
    if any(l.get("subtipo") in intracomunitarias for l in f.get("lineas") or []):
        if not nif:
            res.append(_("Es una operación intracomunitaria y no tiene NIF-IVA: hace falta para el modelo 349."))
        elif nif_ue_con_formato(nif) is False:
            res.append(_("Es una operación intracomunitaria y el NIF no tiene el prefijo y el formato de un país de la UE (por ejemplo FR12345678901)."))
    try:
        fecha = date.fromisoformat(str(f["fecha"])[:10])
    except ValueError:
        fecha = None
    if fecha:
        if fecha > hoy + timedelta(days=1):
            res.append(_("La fecha de la factura es futura."))
        elif fecha < hoy - timedelta(days=365 * ANIOS_MAXIMOS):
            res.append(_("Tiene más de %(anios)s años: el IVA de una factura tan antigua ya no se puede deducir.", anios=ANIOS_MAXIMOS))
        cierre = fc.periodos_cerrados(tenant_id, f["cliente_fiscal_id"], [fc.trimestre_de(f["fecha"])]).get(fc.trimestre_de(f["fecha"]))
        if cierre:
            res.append(_("Es de un periodo ya cerrado (%(trimestre)s): para exportarla habrá que confirmarlo.", trimestre=fc.trimestre_de(f["fecha"])))
    if not f.get("total_centimos"):
        res.append(_("El total es cero."))
    hueco = _hueco_de_numeracion(tenant_id, f)
    if hueco:
        res.append(hueco)
    res.extend(_avisos_del_abono(tenant_id, f))
    if f["tipo"] == "emitida" and (f.get("a3") or {}).get("clave_340") == "1" and abs(f.get("total_centimos") or 0) > LIMITE_SIMPLIFICADA_CENTIMOS:
        res.append(_("Una factura simplificada (tique) no puede pasar de %(limite)s euros salvo en algunos sectores: ¿falta el NIF del cliente?", limite=f"{LIMITE_SIMPLIFICADA_CENTIMOS // 100:,}".replace(",", ".")))
    for d in duplicados(tenant_id, f):
        if d["contabilizada"]:
            res.append((_("Parece repetida: la factura %(numero)s (%(fecha)s) ya está exportada (%(motivo)s).") if d["estado"] == "exportada" else _("Parece repetida: la factura %(numero)s (%(fecha)s) ya está revisada (%(motivo)s)."))
                       % {"numero": d["numero"], "fecha": d["fecha"], "motivo": {"mismo número": _("mismo número"), "mismo importe y fecha": _("mismo importe y fecha"), "mismo número e importe": _("mismo número e importe")}[d["motivo"]]})
    return res
