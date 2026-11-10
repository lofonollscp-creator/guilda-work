"""Proveedor o cliente ya conocido (L8): cuando la factura leída trae un NIF con el que este cliente de la gestoría ya tiene una factura revisada por una persona, se aprovecha lo que ya se decidió entonces:
el nombre con el que figura y, línea a línea (mismo tipo de IVA), la cuenta y el tipo de operación. Solo rellena lo que la lectura deja en blanco y nunca pisa la regla del proveedor (que es más firme). Todo
se cuenta en los avisos para que quien revisa lo compruebe. Las facturas que revisó la IA sola no cuentan como ejemplo: así un error no se repite."""
from __future__ import annotations

import re
import unicodedata

from . import db, facturas_contables as fc

PALABRAS_SIN_VALOR = {"sl", "sa", "slu", "sau", "scp", "cb", "sociedad", "limitada", "anonima", "de", "del", "la", "el", "los", "las", "y", "e"}


def _palabras(nombre: str) -> set[str]:
    plano = unicodedata.normalize("NFKD", str(nombre or "")).encode("ascii", "ignore").decode().lower()
    return {p for p in re.findall(r"[a-z0-9]+", plano) if len(p) >= 3 and p not in PALABRAS_SIN_VALOR}


def _mismo_nombre(a: str, b: str) -> bool:
    """¿Pueden ser el mismo proveedor escrito de otra manera? Basta con compartir una palabra con significado (o que alguno no tenga palabras que comparar)."""
    pa, pb = _palabras(a), _palabras(b)
    return not pa or not pb or bool(pa & pb)


def factura_anterior(tenant_id: int, cliente_fiscal_id: int, tipo: str, nif: str | None) -> dict | None:
    """La última factura de ese NIF (misma clase) revisada o exportada por una persona, o None."""
    nif = fc._nif(nif)
    if not nif:
        return None
    conn = db.get_connection()
    try:
        fila = conn.execute("SELECT id FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND tipo = ? AND tercero_nif = ? AND estado IN ('revisada', 'exportada') "
                            "AND COALESCE(revision_auto, 0) = 0 ORDER BY fecha DESC, id DESC LIMIT 1", (tenant_id, cliente_fiscal_id, tipo, nif)).fetchone()
    finally:
        conn.close()
    return dict(fila) if fila else None


MIN_FACTURAS_PARA_SUGERIR = 2
PALABRAS_SIN_VALOR_DEL_CONCEPTO = PALABRAS_SIN_VALOR | {"factura", "fra", "servicio", "servicios", "compra", "venta", "gasto", "pago", "cliente", "varios", "para", "con", "por", "mes"}


def sugerir_cuenta(tenant_id: int, cliente_fiscal_id: int, tipo: str, concepto: str | None, nombre: str | None) -> tuple[str, int] | None:
    """La cuenta de gasto o ingreso que este cliente ya usó en facturas revisadas por una persona con un concepto o un proveedor parecidos (comparten alguna palabra con significado): (cuenta, cuántas facturas).
    Solo si al menos dos facturas coinciden y esa cuenta es la de más del 60 % de ellas. Es una sugerencia: nunca se aplica sola."""
    palabras = {p for p in _palabras(concepto) | _palabras(nombre) if p not in PALABRAS_SIN_VALOR_DEL_CONCEPTO and len(p) >= 4}
    if not palabras:
        return None
    conn = db.get_connection()
    try:
        filas = [dict(r) for r in conn.execute(
            "SELECT x.id, x.concepto, x.tercero_nombre, l.cuenta FROM facturas_contables x JOIN facturas_contables_lineas l ON l.factura_id = x.id WHERE x.tenant_id = ? AND x.cliente_fiscal_id = ? AND x.tipo = ? "
            "AND x.estado IN ('revisada', 'exportada') AND COALESCE(x.revision_auto, 0) = 0 AND l.cuenta IS NOT NULL ORDER BY x.id DESC LIMIT 3000", (tenant_id, cliente_fiscal_id, tipo))]
    finally:
        conn.close()
    por_cuenta: dict[str, set[int]] = {}
    for f in filas:
        if palabras & (_palabras(f["concepto"]) | _palabras(f["tercero_nombre"])):
            por_cuenta.setdefault(f["cuenta"], set()).add(f["id"])
    total = len(set().union(*por_cuenta.values())) if por_cuenta else 0
    if total < MIN_FACTURAS_PARA_SUGERIR:
        return None
    cuenta, ids = max(por_cuenta.items(), key=lambda kv: (len(kv[1]), kv[0]))
    return (cuenta, len(ids)) if len(ids) >= MIN_FACTURAS_PARA_SUGERIR and len(ids) / total > 0.6 else None


def completar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, tipo: str, nuevos: dict, lineas: list[dict], fuente: str) -> list[str]:
    """Rellena `nuevos` y `lineas` (en su sitio) con lo decidido en la factura anterior de ese proveedor o cliente y devuelve los avisos de lo que cambió. Nada si no hay factura anterior revisada."""
    ref = factura_anterior(tenant_id, cliente_fiscal_id, tipo, nuevos.get("tercero_nif"))
    anterior = fc.obtener(tenant_id, usuario_id, ref["id"]) if ref else None
    if anterior is None:
        if any(not str(l.get("cuenta") or "").strip() for l in lineas) and not fc.regla_del_tercero(tenant_id, cliente_fiscal_id, tipo, nuevos.get("tercero_nif")):
            sugerida = sugerir_cuenta(tenant_id, cliente_fiscal_id, tipo, nuevos.get("concepto"), nuevos.get("tercero_nombre"))
            if sugerida:
                return [f"Sugerencia: la cuenta {sugerida[0]}, que usaste en {sugerida[1]} facturas con un concepto o un proveedor parecidos. No se ha aplicado: ponla en las líneas si es la que toca."]
        return []
    avisos = []
    if fuente != "xml" and anterior["tercero_nombre"] and nuevos.get("tercero_nombre") != anterior["tercero_nombre"]:
        if _mismo_nombre(nuevos.get("tercero_nombre"), anterior["tercero_nombre"]):
            avisos.append(f"Se ha puesto el nombre «{anterior['tercero_nombre']}», con el que ya figura este NIF en este cliente (la lectura decía «{nuevos.get('tercero_nombre')}»).")
            nuevos["tercero_nombre"] = anterior["tercero_nombre"]
        else:
            avisos.append(f"El NIF {nuevos.get('tercero_nif')} ya figura en este cliente como «{anterior['tercero_nombre']}» y la lectura dice «{nuevos.get('tercero_nombre')}»: comprueba el NIF.")
    if fc.regla_del_tercero(tenant_id, cliente_fiscal_id, tipo, nuevos.get("tercero_nif")):
        return avisos                                           # con regla propia manda ella, que es lo que se decidió a propósito
    previas = {l["pct_iva"]: l for l in anterior["lineas"]}
    copiadas = []
    for l in lineas:
        previa = previas.get(fc.porcentaje_a_centesimas(l.get("pct_iva")))
        if not previa:
            continue
        if not str(l.get("cuenta") or "").strip() and previa.get("cuenta"):
            l["cuenta"] = previa["cuenta"]
            copiadas.append(f"la cuenta {previa['cuenta']}")
        if not str(l.get("subtipo") or "").strip() and previa.get("subtipo") not in (None, "", "01"):
            l["subtipo"] = previa["subtipo"]
            copiadas.append(f"el tipo de operación {previa['subtipo']}")
    if copiadas:
        avisos.append(f"Se ha copiado {' y '.join(dict.fromkeys(copiadas))} de la factura {anterior['numero']}, la última de este proveedor que revisó una persona: compruébalo.")
    return avisos
