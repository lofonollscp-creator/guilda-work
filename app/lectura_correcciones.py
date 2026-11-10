"""Lo que el despacho ya ha corregido de un mismo proveedor o cliente se aplica solo en las lecturas siguientes (L1).

Cuando la IA lee siempre mal el NIF o el nombre de un tercero (una cifra confundida, un logotipo leído como razón social) y las personas lo corrigen al revisar, queda guardado en la factura lo leído y lo
dado por bueno (`lectura_calidad`). Si la misma corrección se repite al menos dos veces para el mismo cliente de la gestoría y siempre da el mismo resultado, la siguiente lectura ya sale corregida y
con un aviso. Solo corrige el NIF y el nombre (identifican al tercero); nunca importes, fechas ni números. Sin tablas nuevas: se calcula con las facturas revisadas a mano."""
from __future__ import annotations

import json
from collections import Counter

from . import db

MINIMO_REPETICIONES = 2
FACTURAS_A_MIRAR = 800
CAMPOS = {"nif": "tercero_nif", "tercero": "tercero_nombre"}          # campo de `lectura_calidad` → columna de la factura


def _clave(campo: str, valor) -> str:
    """Lo leído y lo corregido se comparan igual que en la medida de calidad: mayúsculas y sin espacios ni guiones en el NIF; mayúsculas y espacios simples en el nombre."""
    t = str(valor or "")
    return t.replace(" ", "").replace("-", "").upper() if campo == "nif" else " ".join(t.split()).upper()


def aprendidas(tenant_id: int, cliente_fiscal_id: int) -> dict[str, dict[str, str]]:
    """{«nif»: {leído: correcto}, «tercero»: {leído: correcto}} con las correcciones repetidas y coherentes de las facturas revisadas a mano de ese cliente."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT tercero_nif, tercero_nombre, lectura_evidencia FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado IN ('revisada', 'exportada') "
                             "AND revision_auto = 0 AND lectura = 'ia' AND lectura_evidencia LIKE '%\"correcciones\"%' ORDER BY id DESC LIMIT ?", (tenant_id, cliente_fiscal_id, FACTURAS_A_MIRAR)).fetchall()
    finally:
        conn.close()
    cuentas: dict[tuple[str, str], Counter] = {}
    for f in filas:
        try:
            correcciones = (json.loads(f["lectura_evidencia"] or "{}").get("correcciones")) or {}
        except ValueError:
            continue
        for campo, columna in CAMPOS.items():
            c = correcciones.get(campo)
            if isinstance(c, dict) and c.get("leido") and c.get("final") and f[columna]:
                cuentas.setdefault((campo, c["leido"]), Counter())[f[columna]] += 1
    res: dict[str, dict[str, str]] = {campo: {} for campo in CAMPOS}
    for (campo, leido), final in cuentas.items():
        mas_comun, veces = final.most_common(1)[0]
        if veces >= MINIMO_REPETICIONES and veces * 3 >= sum(final.values()) * 2:       # al menos dos veces y al menos dos de cada tres
            res[campo][leido] = mas_comun
    return res


def aplicar(tenant_id: int, cliente_fiscal_id: int, nuevos: dict) -> list[str]:
    """Corrige en `nuevos` (los datos recién leídos) el NIF y el nombre ya corregidos antes por el despacho. Devuelve un aviso por cada cambio."""
    if not any(nuevos.get(c) for c in CAMPOS.values()):
        return []
    sabidas = aprendidas(tenant_id, cliente_fiscal_id)
    avisos = []
    for campo, columna in CAMPOS.items():
        leido = nuevos.get(columna)
        final = sabidas[campo].get(_clave(campo, leido)) if leido else None
        if final and _clave(campo, final) != _clave(campo, leido):
            nuevos[columna] = final
            avisos.append(f"Corregido como en las facturas anteriores de este cliente: {'NIF' if campo == 'nif' else 'nombre'} «{leido}» → «{final}».")
    return avisos
