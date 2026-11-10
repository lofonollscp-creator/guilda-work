"""Retorno desde a3 (J3): comprobar que lo que se exportó con el SUENLACE.DAT está de verdad contabilizado.

La persona saca de a3 un listado de facturas del cliente (el libro registro de IVA o cualquier listado de facturas, en CSV o Excel) y lo sube aquí. Se cruza con las facturas **exportadas** de ese cliente:
 · las que aparecen en a3 quedan «confirmadas» (y el cliente lo ve en su portal);
 · las exportadas que NO aparecen se señalan por lote, para volver a pasarlas o mirar por qué a3 las rechazó;
 · las que a3 tiene y aquí no se exportaron se listan aparte (altas manuales o de otra vía).
Los títulos de las columnas se reconocen por su nombre (número, fecha, NIF, base, cuota, total) sin fijar un formato: a3 los nombra distinto según el listado. Nada se escribe salvo la fecha de confirmación."""
from __future__ import annotations

import csv
import io
import re
import unicodedata

from . import acceso, auditoria, db, facturas_contables as fc

SINONIMOS = {
    "numero": ("numero", "n factura", "no factura", "num factura", "n documento", "documento", "factura", "n doc", "numero factura", "numero documento", "n de factura", "n expediente", "num"),
    "fecha": ("fecha", "fecha factura", "f factura", "fecha documento", "fecha expedicion", "fecha de factura", "f expedicion"),
    "nif": ("nif", "cif", "nif cif", "n i f", "nif proveedor", "nif cliente", "nif contraparte", "cif nif"),
    "total": ("total", "importe total", "total factura", "importe", "total documento"),
    "base": ("base", "base imponible", "base iva", "importe base"),
    "cuota": ("cuota", "cuota iva", "iva", "importe iva"),
}
MAX_FILAS = 20000
MAX_BYTES = 8 * 1024 * 1024


def _plano(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", t.replace("º", "o").replace("ª", "a")).split())


def _columnas(cabecera: list) -> dict[str, int]:
    """{campo: posición} según el título de cada columna (la primera que lo cumple; «número» es el título más exacto que haya)."""
    planos = [_plano(c) for c in cabecera]
    res: dict[str, int] = {}
    for campo, nombres in SINONIMOS.items():
        for nombre in nombres:                                      # en orden de preferencia
            if nombre in planos and campo not in res and planos.index(nombre) not in res.values():
                res[campo] = planos.index(nombre)
    return res


def _texto_del_archivo(contenido: bytes) -> str:
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            return contenido.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return contenido.decode("latin-1", "replace")


def _filas_de_csv(contenido: bytes) -> list[list]:
    texto = _texto_del_archivo(contenido)
    try:
        dialecto = csv.Sniffer().sniff(texto[:4096], delimiters=";,\t|")
    except csv.Error:
        dialecto = csv.excel
        dialecto.delimiter = ";"
    return [fila for fila in csv.reader(io.StringIO(texto), dialecto)]


def _filas_de_excel(contenido: bytes) -> list[list]:
    import openpyxl
    libro = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    try:
        hoja = libro.worksheets[0]
        return [list(fila) for fila in hoja.iter_rows(values_only=True)]
    finally:
        libro.close()


def _importe(valor) -> int | None:
    """Céntimos de un importe en cifra, texto español («1.234,56») o con signo; None si no es un importe."""
    if valor is None or str(valor).strip() == "":
        return None
    if isinstance(valor, (int, float)):
        return round(valor * 100)
    t = str(valor).strip().replace("€", "").replace(" ", "")
    negativo = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    t = t.strip("-()")
    try:
        c = fc.importe_a_centimos(t)
    except ValueError:
        return None
    return -c if negativo else c


def _fecha(valor) -> str | None:
    if valor is None or str(valor).strip() == "":
        return None
    if hasattr(valor, "isoformat"):
        return valor.isoformat()[:10]
    t = str(valor).strip()
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", t)
    if m:
        d, mes, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a = a + 2000 if a < 100 else a
        return f"{a:04d}-{mes:02d}-{d:02d}"
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2}).*", t)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _clave_numero(numero) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(numero or "").upper()).lstrip("0")


def leer(contenido: bytes, nombre: str = "") -> list[dict]:
    """Las facturas del listado de a3: [{numero, fecha, nif, total, base, cuota}] (los campos que el listado no traiga quedan en None). `ValueError` si no se puede leer o no se reconoce ninguna columna útil."""
    if not contenido or len(contenido) > MAX_BYTES:
        raise ValueError("El archivo está vacío o pesa más de 8 MB.")
    es_excel = nombre.lower().endswith((".xlsx", ".xlsm")) or contenido[:2] == b"PK"
    try:
        filas = _filas_de_excel(contenido) if es_excel else _filas_de_csv(contenido)
    except Exception:  # noqa: BLE001 -- un archivo estropeado o de otro tipo
        raise ValueError("No se ha podido leer el archivo: sube el listado de a3 en CSV o Excel.") from None
    inicio = next((i for i, f in enumerate(filas[:30]) if len(_columnas(f)) >= 2 and "numero" in _columnas(f)), None)
    if inicio is None:
        raise ValueError("No encuentro las columnas del listado: hace falta al menos el número de factura y otra columna (fecha, NIF o total).")
    col = _columnas(filas[inicio])
    res = []
    for f in filas[inicio + 1:inicio + 1 + MAX_FILAS]:
        numero = str(f[col["numero"]]).strip() if col["numero"] < len(f) and f[col["numero"]] is not None else ""
        if not numero:
            continue
        def celda(campo):
            return f[col[campo]] if campo in col and col[campo] < len(f) else None
        res.append({"numero": numero, "fecha": _fecha(celda("fecha")), "nif": fc._nif(celda("nif")) or None, "total": _importe(celda("total")), "base": _importe(celda("base")), "cuota": _importe(celda("cuota"))})
    if not res:
        raise ValueError("El listado no trae ninguna factura.")
    return res


def _coincide(f: dict, a: dict) -> bool:
    """¿Es la misma factura la exportada `f` y la fila `a` de a3? El número manda; con él, el NIF (si ambos lo traen) y el importe (si ambos lo traen, sin signo) no pueden contradecirse."""
    if _clave_numero(f["numero"]) != _clave_numero(a["numero"]):
        return False
    if a["nif"] and f.get("tercero_nif") and fc._nif(f["tercero_nif"]) != a["nif"]:
        return False
    if a["total"] is not None and abs(a["total"]) != f["total_centimos"] and (a["base"] is None or abs(a["base"]) != sum(l["base_centimos"] for l in f["lineas"])):
        return False
    return True


def cruzar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, filas: list[dict], *, confirmar: bool = True) -> dict:
    """Cruza el listado de a3 con las facturas exportadas del cliente. Devuelve {leidas, confirmadas, ya_confirmadas, faltan, sobran, por_lote} y, con `confirmar`, anota la fecha de confirmación de las que
    coinciden. `faltan`: exportadas que a3 no tiene (solo las del rango de fechas del listado). `sobran`: filas de a3 que no corresponden a ninguna exportada."""
    if not acceso.puede_ver_cliente(tenant_id, usuario_id, cliente_fiscal_id):
        raise ValueError("Cliente no encontrado.")
    exportadas = [fc.obtener(tenant_id, usuario_id, f["id"]) for f in fc.listar(tenant_id, usuario_id, cliente_fiscal_id=cliente_fiscal_id, estado="exportada", limite=5000)]
    exportadas = [f for f in exportadas if f]
    fechas = [a["fecha"] for a in filas if a["fecha"]]
    desde, hasta = (min(fechas), max(fechas)) if fechas else (None, None)
    libres = list(filas)
    confirmadas, ya, faltan = [], [], []
    for f in sorted(exportadas, key=lambda f: (f["fecha"], f["id"])):
        encontrada = next((a for a in libres if _coincide(f, a)), None)
        if encontrada is not None:
            libres.remove(encontrada)
            (ya if f.get("confirmada_en") else confirmadas).append(f)
        elif (desde is None or desde <= f["fecha"] <= hasta) and not f.get("confirmada_en"):
            faltan.append(f)
    por_lote: dict[int, dict] = {}
    for f in (*confirmadas, *ya, *faltan):
        l = por_lote.setdefault(f.get("lote_id") or 0, {"lote_id": f.get("lote_id"), "confirmadas": 0, "faltan": 0})
        l["faltan" if f in faltan else "confirmadas"] += 1
    if confirmar and confirmadas:
        conn = db.get_connection()
        try:
            ahora = db.now_iso()
            conn.executemany("UPDATE facturas_contables SET confirmada_en = ? WHERE id = ? AND tenant_id = ?", [(ahora, f["id"], tenant_id) for f in confirmadas])
            for lote_id, l in por_lote.items():
                if lote_id:
                    conn.execute("UPDATE contabilidad_lotes SET comprobado_en = ?, n_confirmadas = (SELECT COUNT(*) FROM facturas_contables WHERE lote_id = ? AND tenant_id = ? AND confirmada_en IS NOT NULL) "
                                 "WHERE id = ? AND tenant_id = ?", (ahora, lote_id, tenant_id, lote_id, tenant_id))
            auditoria.registrar(tenant_id, usuario_id, "contabilidad.retorno_a3", "cliente_fiscal", cliente_fiscal_id, {"leidas": len(filas), "confirmadas": len(confirmadas), "faltan": len(faltan)}, conn=conn)
            conn.commit()
        finally:
            conn.close()
    return {"leidas": len(filas), "confirmadas": confirmadas, "ya_confirmadas": ya, "faltan": faltan, "sobran": libres, "por_lote": sorted(por_lote.values(), key=lambda l: l["lote_id"] or 0),
            "desde": desde, "hasta": hasta}
