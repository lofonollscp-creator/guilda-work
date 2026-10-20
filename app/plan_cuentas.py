"""Plan de cuentas de un cliente en a3: se importa la lista de subcuentas de proveedores y clientes que ya existen allí (exportada de a3 a Excel o CSV) para que el fichero de enlace use la subcuenta
que cada tercero YA tiene en a3 en vez de crear otra, y para que la numeración automática no choque con las existentes.

Dos pasos, como la importación de clientes: `preparar` lee el archivo y lo guarda unos minutos (privado de quien lo sube); `previsualizar` dice qué terceros del cliente casan con una subcuenta
(por NIF, seguro; por nombre, solo si se confirma); `importar` sustituye el plan guardado del cliente y recuerda las coincidencias por nombre confirmadas.

El formato del archivo no se supone: se reconocen las columnas por su cabecera (cuenta/subcuenta/código, descripción/nombre, NIF) y, si no hay cabecera, se lee «cuenta nombre [NIF]» fila a fila.
Solo cuentan las subcuentas de 40 y 41 (proveedores y acreedores → proveedor) y 43 (clientes), con los dígitos que tenga configurado el cliente."""
from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path

from . import auditoria, db, facturas_contables as fc, importador_clientes as imp

MAX_REGISTROS = 20000
_SINONIMOS = {
    "cuenta": ("cuenta", "subcuenta", "codigo", "cod", "codcuenta", "numcuenta", "numerocuenta", "cuentacontable"),
    "nombre": ("descripcion", "nombre", "titulo", "razonsocial", "denominacion", "nombrecuenta", "descripcioncuenta", "titular"),
    "nif": ("nif", "cif", "nifcif", "cifnif", "dni", "nifproveedor", "nifcliente", "documento", "vat"),
}
_NIF = re.compile(r"^[A-Za-z]?[\s.\-]?\d{6,8}[\s.\-]?[A-Za-z]?$")


def _tipo_de(cuenta: str) -> str | None:
    if cuenta.startswith(("40", "41")):
        return "proveedor"
    if cuenta.startswith("43"):
        return "cliente"
    return None


def _filas(nombre: str, datos: bytes) -> list[list[str]]:
    if not datos:
        raise imp.ErrorImportacion("El archivo está vacío.")
    if len(datos) > imp.MAX_BYTES:
        raise imp.ErrorImportacion("El archivo es demasiado grande (máximo 5 MB).")
    sufijo = Path(nombre or "").suffix.lower()
    if sufijo == ".xlsx":
        filas = imp._leer_xlsx(datos)
    elif sufijo in (".csv", ".txt", ".tsv"):
        filas = imp._leer_csv(datos)
    elif sufijo == ".xls":
        raise imp.ErrorImportacion("Los .xls antiguos no se pueden leer: guárdalo como .xlsx o como CSV.")
    else:
        raise imp.ErrorImportacion("Sube un Excel (.xlsx) o un CSV con la lista de cuentas de a3.")
    return [f for f in filas if any(c for c in f)]


def _columnas(fila: list[str]) -> dict[str, int] | None:
    """Las columnas por su cabecera, o None si esa fila no parece una cabecera (hace falta al menos la de la cuenta)."""
    res: dict[str, int] = {}
    for i, cab in enumerate(fila):
        n = imp._norm(cab)
        for campo, sinonimos in _SINONIMOS.items():
            if campo not in res and n in sinonimos:
                res[campo] = i
                break
    return res if "cuenta" in res else None


def leer_registros(nombre: str, datos: bytes) -> dict:
    """{registros: [{cuenta, nombre, nif, tipo}], ignoradas: n, avisos: [..]}. `ErrorImportacion` si no se puede leer o no hay ninguna cuenta de proveedor o cliente."""
    filas = _filas(nombre, datos)
    columnas = None
    inicio = 0
    for i, f in enumerate(filas[:15]):
        columnas = _columnas(f)
        if columnas:
            inicio = i + 1
            break
    registros: dict[str, dict] = {}
    ignoradas = 0
    for f in filas[inicio:]:
        if columnas:
            cuenta = re.sub(r"\D", "", f[columnas["cuenta"]]) if columnas["cuenta"] < len(f) else ""
            nom = f[columnas["nombre"]].strip() if "nombre" in columnas and columnas["nombre"] < len(f) else ""
            nif = f[columnas["nif"]].strip() if "nif" in columnas and columnas["nif"] < len(f) else ""
        else:
            cuenta, nom, nif = _sin_cabecera(f)
        if not cuenta:
            continue
        tipo = _tipo_de(cuenta)
        if tipo is None or not 4 <= len(cuenta) <= 12:
            ignoradas += 1
            continue
        registros[cuenta] = {"cuenta": cuenta, "nombre": nom[:100], "nif": fc._nif(nif)[:20] if nif and _NIF.match(nif) else "", "tipo": tipo}
        if len(registros) > MAX_REGISTROS:
            raise imp.ErrorImportacion(f"Demasiadas cuentas de golpe (máximo {MAX_REGISTROS}): divide el archivo.")
    if not registros:
        raise imp.ErrorImportacion("No se ha encontrado ninguna subcuenta de proveedores (40, 41) o clientes (43) en el archivo.")
    avisos = []
    if not columnas:
        avisos.append("El archivo no tiene cabecera: se ha leído «cuenta, nombre y NIF» fila a fila. Comprueba la vista previa.")
    if columnas and "nif" not in columnas:
        avisos.append("El archivo no trae el NIF: las coincidencias serán por nombre y habrá que confirmarlas una a una.")
    return {"registros": list(registros.values()), "ignoradas": ignoradas, "avisos": avisos}


def _sin_cabecera(f: list[str]) -> tuple[str, str, str]:
    celdas = [c.strip() for c in f if c and c.strip()]
    if not celdas:
        return "", "", ""
    if len(celdas) == 1:                      # «40000001 PROVEEDOR S.L.» en una sola columna
        m = re.match(r"^(\d{4,12})\s+(.+)$", celdas[0])
        return (m.group(1), m.group(2), "") if m else ("", "", "")
    if not re.fullmatch(r"\d{4,12}", re.sub(r"\s", "", celdas[0])):
        return "", "", ""
    cuenta = re.sub(r"\s", "", celdas[0])
    nom = next((c for c in celdas[1:] if not _NIF.match(c) and not re.fullmatch(r"[\d.,\-\s]+", c)), "")
    nif = next((c for c in celdas[1:] if _NIF.match(c)), "")
    return cuenta, nom, nif


# --- Un fichero por importación (el mismo almacén privado y con caducidad que la importación de clientes) ---------------------------------------------

def preparar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, nombre: str, datos: bytes) -> str:
    leido = leer_registros(nombre, datos)
    imp._limpiar_caducadas()
    ident = secrets.token_urlsafe(24)
    ruta = imp._carpeta() / f"{ident}.json"
    with os.fdopen(os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as f:
        json.dump({"tenant_id": tenant_id, "usuario_id": usuario_id, "cliente_fiscal_id": cliente_fiscal_id, "plan": True, "nombre": (nombre or "")[:200], "creado": time.time(), **leido}, f, ensure_ascii=False)
    return ident


def cargar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ident: str) -> dict | None:
    d = imp.cargar(tenant_id, usuario_id, ident)
    return d if d and d.get("plan") and d.get("cliente_fiscal_id") == cliente_fiscal_id else None


# --- Qué casa con qué --------------------------------------------------------------------------------------------------------------------------------

def _nombre_clave(texto: str) -> str:
    return imp._norm(re.sub(r"\b(s\.?\s?l\.?\s?u?\.?|s\.?\s?a\.?|s\.?\s?l\.?\s?l\.?|c\.?\s?b\.?|s\.?\s?coop\.?)\s*$", "", str(texto or "").lower().strip()))


def _terceros_del_cliente(tenant_id: int, cliente_fiscal_id: int) -> list[dict]:
    """Los proveedores y clientes que aparecen en las facturas del cliente y aún no tienen subcuenta recordada ni escrita a mano, más los recordados (para avisar si difieren)."""
    conn = db.get_connection()
    try:
        recordados = {(r["tipo"], r["nif"]): r["cuenta"] for r in conn.execute("SELECT tipo, nif, cuenta FROM contabilidad_terceros WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id))}
        filas = conn.execute("SELECT tipo, tercero_nif, tercero_nombre FROM facturas_contables WHERE cliente_fiscal_id = ? AND tenant_id = ? AND estado != 'descartada' "
                             "GROUP BY tipo, tercero_nif, tercero_nombre", (cliente_fiscal_id, tenant_id)).fetchall()
    finally:
        conn.close()
    vistos, res = set(), []
    for f in filas:
        tipo = "proveedor" if f["tipo"] == "recibida" else "cliente"
        nif = fc._nif(f["tercero_nif"])
        clave = (tipo, nif or f["tercero_nombre"])
        if clave in vistos:
            continue
        vistos.add(clave)
        res.append({"tipo": tipo, "nif": nif, "nombre": f["tercero_nombre"], "recordada": recordados.get((tipo, nif))})
    return res


def previsualizar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, importacion: dict) -> dict:
    """Qué hará la importación: cuántas subcuentas valen, qué terceros casan por NIF (seguro) o por nombre (a confirmar) y cuáles ya tenían otra subcuenta recordada."""
    cfg = fc.configuracion(tenant_id, cliente_fiscal_id)
    regs = importacion["registros"]
    validas = [r for r in regs if len(r["cuenta"]) == cfg["digitos"]]
    por_nif = {(r["tipo"], r["nif"]): r for r in validas if r["nif"]}
    por_nombre: dict[tuple, list] = {}
    for r in validas:
        if r["nombre"]:
            por_nombre.setdefault((r["tipo"], _nombre_clave(r["nombre"])), []).append(r)
    por_nif_resultado, por_nombre_resultado, difieren = [], [], []
    for t in _terceros_del_cliente(tenant_id, cliente_fiscal_id):
        r = por_nif.get((t["tipo"], t["nif"])) if t["nif"] else None
        if r is not None:
            por_nif_resultado.append({**t, "cuenta": r["cuenta"], "nombre_a3": r["nombre"]})
            if t["recordada"] and t["recordada"] != r["cuenta"]:
                difieren.append({**t, "cuenta": r["cuenta"]})
        elif not t["recordada"]:
            candidatas = por_nombre.get((t["tipo"], _nombre_clave(t["nombre"])), [])
            if len(candidatas) == 1:
                por_nombre_resultado.append({**t, "cuenta": candidatas[0]["cuenta"], "nombre_a3": candidatas[0]["nombre"]})
    return {"total": len(regs), "validas": len(validas), "otros_digitos": len(regs) - len(validas), "digitos": cfg["digitos"], "ignoradas": importacion.get("ignoradas", 0),
            "con_nif": sum(1 for r in validas if r["nif"]), "proveedores": sum(1 for r in validas if r["tipo"] == "proveedor"), "clientes": sum(1 for r in validas if r["tipo"] == "cliente"),
            "por_nif": por_nif_resultado, "por_nombre": por_nombre_resultado, "difieren": difieren, "muestra": validas[:8], "avisos": importacion.get("avisos", [])}


def importar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, importacion: dict, nombres_confirmados: list[int]) -> dict:
    """Sustituye el plan guardado del cliente por el del archivo y recuerda las coincidencias por nombre confirmadas (índices de `previsualizar()['por_nombre']`)."""
    fc._cliente(tenant_id, usuario_id, cliente_fiscal_id)
    vista = previsualizar(tenant_id, usuario_id, cliente_fiscal_id, importacion)
    validas = [r for r in importacion["registros"] if len(r["cuenta"]) == vista["digitos"]]
    if not validas:
        raise ValueError(f"Ninguna de las subcuentas del archivo tiene {vista['digitos']} dígitos: cambia los dígitos en la configuración del cliente o revisa el archivo.")
    elegidas = [vista["por_nombre"][i] for i in dict.fromkeys(nombres_confirmados) if 0 <= i < len(vista["por_nombre"])]
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM contabilidad_plan WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id))
        conn.executemany("INSERT INTO contabilidad_plan (tenant_id, cliente_fiscal_id, cuenta, nombre, nif, tipo, importado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         [(tenant_id, cliente_fiscal_id, r["cuenta"], r["nombre"], r["nif"] or None, r["tipo"], db.now_iso()) for r in validas])
        for t in elegidas:
            if t["nif"]:
                fc._recordar_tercero(conn, tenant_id, cliente_fiscal_id, "recibida" if t["tipo"] == "proveedor" else "emitida", t["nif"], t["nombre"], t["cuenta"])
        auditoria.registrar(tenant_id, usuario_id, "contabilidad.plan_importado", "cliente_fiscal", cliente_fiscal_id, {"cuentas": len(validas), "por_nif": len(vista["por_nif"]), "por_nombre": len(elegidas)}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return {"cuentas": len(validas), "por_nif": len(vista["por_nif"]), "por_nombre": len(elegidas), "sin_nif": sum(1 for t in elegidas if not t["nif"])}


def resumen(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> dict:
    """Lo guardado del plan de un cliente: cuántas subcuentas, de qué tipo y cuándo se importó."""
    fc._cliente(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(tipo = 'proveedor'), 0) AS proveedores, COALESCE(SUM(tipo = 'cliente'), 0) AS clientes, MAX(importado_en) AS cuando "
                         "FROM contabilidad_plan WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id)).fetchone()
    finally:
        conn.close()
    return {"cuentas": f["n"], "proveedores": f["proveedores"], "clientes": f["clientes"], "importado_en": f["cuando"]}


def borrar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> None:
    fc._cliente(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM contabilidad_plan WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "contabilidad.plan_borrado", "cliente_fiscal", cliente_fiscal_id, None, conn=conn)
        conn.commit()
    finally:
        conn.close()
