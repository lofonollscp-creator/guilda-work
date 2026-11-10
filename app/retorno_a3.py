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


def _filas_del_archivo(contenido: bytes, nombre: str) -> list[list]:
    if not contenido or len(contenido) > MAX_BYTES:
        raise ValueError("El archivo está vacío o pesa más de 8 MB.")
    es_excel = nombre.lower().endswith((".xlsx", ".xlsm")) or contenido[:2] == b"PK"
    try:
        return _filas_de_excel(contenido) if es_excel else _filas_de_csv(contenido)
    except Exception:  # noqa: BLE001 -- un archivo estropeado o de otro tipo
        raise ValueError("No se ha podido leer el archivo: sube el listado de a3 en CSV o Excel.") from None


def letra_de_columna(i: int) -> str:
    """0 → A, 25 → Z, 26 → AA (como en una hoja de cálculo)."""
    res = ""
    i += 1
    while i:
        i, resto = divmod(i - 1, 26)
        res = chr(65 + resto) + res
    return res


def indice_de_columna(texto) -> int | None:
    """«B» → 1, «aa» → 26 y «3» → 2 (las cifras cuentan desde 1, como las letras). None si está vacío o no vale."""
    t = str(texto or "").strip().upper()
    if re.fullmatch(r"\d{1,3}", t):
        return int(t) - 1 if int(t) >= 1 else None
    if re.fullmatch(r"[A-Z]{1,2}", t):
        n = 0
        for ch in t:
            n = n * 26 + ord(ch) - 64
        return n - 1
    return None


def vista_previa(contenido: bytes, nombre: str = "", filas: int = 6) -> dict:
    """Las primeras filas del listado con la letra de cada columna, para que la persona diga cuál es cuál cuando no se reconocen por su título: {letras: [A, B…], filas: [[texto…]]}."""
    todas = [f for f in _filas_del_archivo(contenido, nombre) if any(str(c or "").strip() for c in f)][:filas]
    ancho = max((len(f) for f in todas), default=0)
    return {"letras": [letra_de_columna(i) for i in range(ancho)], "filas": [[("" if c is None else str(c))[:40] for c in f] + [""] * (ancho - len(f)) for f in todas]}


def mapa_de_columnas(**columnas) -> dict[str, int] | None:
    """{campo: posición} con lo que la persona indicó (letra o cifra de cada columna). None si no indicó ninguna; `ValueError` si una no vale o falta el número de factura."""
    mapa = {}
    for campo in SINONIMOS:
        crudo = columnas.get(campo)
        if str(crudo or "").strip() == "":
            continue
        i = indice_de_columna(crudo)
        if i is None:
            raise ValueError("Una columna indicada no es válida: usa la letra de la columna (A, B, C…).")
        mapa[campo] = i
    if not mapa:
        return None
    if "numero" not in mapa or len(mapa) < 2:
        raise ValueError("Indica al menos la columna del número de factura y otra más (fecha, NIF o total).")
    return mapa


def leer(contenido: bytes, nombre: str = "", mapa: dict[str, int] | None = None, fila_de_titulos: int = 1) -> list[dict]:
    """Las facturas del listado de a3: [{numero, fecha, nif, total, base, cuota}] (los campos que el listado no traiga quedan en None). Las columnas se reconocen por su título; si no se reconocen, `mapa`
    ({campo: posición}) dice cuál es cuál y `fila_de_titulos` (desde 1; 0 = el listado no trae títulos) dónde empiezan los datos. `ValueError` si no se puede leer o no se reconoce ninguna columna útil."""
    filas = _filas_del_archivo(contenido, nombre)
    if mapa:
        col, inicio = dict(mapa), max(0, int(fila_de_titulos)) - 1
    else:
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


def _agrupar(filas: list[dict]) -> list[dict]:
    """Una fila por factura: el libro de IVA de a3 trae una fila por tipo impositivo de cada factura. Base y cuota se suman; el total, si se repite igual en todas las filas, es el de la factura."""
    grupos: dict[tuple[str, str], list[dict]] = {}
    for a in filas:
        grupos.setdefault((_clave_numero(a["numero"]), a["nif"] or ""), []).append(a)
    res = []
    for partes in grupos.values():
        if len(partes) == 1:
            res.append(partes[0])
            continue
        def suma(campo):
            valores = [p[campo] for p in partes if p[campo] is not None]
            return sum(valores) if valores else None
        totales = [p["total"] for p in partes if p["total"] is not None]
        res.append({**partes[0], "base": suma("base"), "cuota": suma("cuota"), "total": totales[0] if len(set(totales)) == 1 else suma("total")})
    return res


def _comparar(f: dict, a: dict) -> list[dict] | None:
    """None si `a` no es la factura `f` (otro número, o un NIF que la contradice); si lo es, la lista de diferencias de importe ({campo, guilda, a3}; vacía = idéntica). El número manda."""
    if _clave_numero(f["numero"]) != _clave_numero(a["numero"]):
        return None
    if a["nif"] and f.get("tercero_nif") and fc._nif(f["tercero_nif"]) != a["nif"]:
        return None
    nuestros = {"total": f["total_centimos"], "base": sum(l["base_centimos"] for l in f["lineas"]), "cuota": sum(l["cuota_iva"] for l in f["lineas"])}
    return [{"campo": campo, "guilda": nuestros[campo], "a3": abs(a[campo])} for campo in ("total", "base", "cuota") if a[campo] is not None and abs(a[campo]) != nuestros[campo]]


DIAS_DE_MARGEN = 3


def _posibles_parejas(faltan: list[dict], libres: list[dict]) -> list[dict]:
    """Para cada exportada que a3 no tiene, la fila de a3 sin pareja que tiene su mismo importe total y una fecha de hasta 3 días de diferencia (y un NIF que no la contradiga): suele ser la misma factura con
    otro número (a3 renumera o se tecleó distinto). Solo una pista: no se confirma nada. Cada fila de a3 se ofrece una sola vez."""
    from datetime import date
    usadas: set[int] = set()
    res = []
    for f in faltan:
        for i, a in enumerate(libres):
            if i in usadas or a["total"] is None or abs(a["total"]) != f["total_centimos"]:
                continue
            if a["nif"] and f.get("tercero_nif") and fc._nif(f["tercero_nif"]) != a["nif"]:
                continue
            if a["fecha"]:
                try:
                    if abs((date.fromisoformat(a["fecha"]) - date.fromisoformat(f["fecha"][:10])).days) > DIAS_DE_MARGEN:
                        continue
                except ValueError:
                    continue
            usadas.add(i)
            res.append({"factura": f, "a3": a})
            break
    return res


def cruzar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, filas: list[dict], *, confirmar: bool = True) -> dict:
    """Cruza el listado de a3 con las facturas exportadas del cliente. Devuelve {leidas, confirmadas, ya_confirmadas, con_diferencias, faltan, sobran, por_lote, cuadre} y, con `confirmar`, anota la fecha de
    confirmación de las idénticas. `con_diferencias`: están en a3 pero con un importe distinto (no se confirman: [{factura, diferencias}]). `faltan`: exportadas que a3 no tiene (solo las del rango de
    fechas del listado). `sobran`: filas de a3 que no corresponden a ninguna exportada. `cuadre`: IVA por trimestre y tipo según Guilda y según a3 (solo con las facturas que están en las dos partes)."""
    if not acceso.puede_ver_cliente(tenant_id, usuario_id, cliente_fiscal_id):
        raise ValueError("Cliente no encontrado.")
    exportadas = [fc.obtener(tenant_id, usuario_id, f["id"]) for f in fc.listar(tenant_id, usuario_id, cliente_fiscal_id=cliente_fiscal_id, estado="exportada", limite=5000)]
    exportadas = [f for f in exportadas if f]
    filas = _agrupar(filas)
    fechas = [a["fecha"] for a in filas if a["fecha"]]
    desde, hasta = (min(fechas), max(fechas)) if fechas else (None, None)
    libres = list(filas)
    confirmadas, ya, faltan, con_diferencias, parejas = [], [], [], [], []
    for f in sorted(exportadas, key=lambda f: (f["fecha"], f["id"])):
        pareja = next(((a, d) for a in libres if (d := _comparar(f, a)) is not None), None)
        if pareja is not None:
            libres.remove(pareja[0])
            parejas.append((f, pareja[0]))
            if pareja[1]:
                con_diferencias.append({"factura": f, "diferencias": pareja[1]})
            else:
                (ya if f.get("confirmada_en") else confirmadas).append(f)
        elif (desde is None or desde <= f["fecha"] <= hasta) and not f.get("confirmada_en"):
            faltan.append(f)
    posibles_parejas = _posibles_parejas(faltan, libres)
    por_lote: dict[int, dict] = {}
    for f in (*confirmadas, *ya, *faltan):
        l = por_lote.setdefault(f.get("lote_id") or 0, {"lote_id": f.get("lote_id"), "confirmadas": 0, "faltan": 0})
        l["faltan" if f in faltan else "confirmadas"] += 1
    cuadre: dict[tuple[str, str], dict] = {}
    for f, a in parejas:
        if a["cuota"] is None:
            continue
        c = cuadre.setdefault((fc.trimestre_de(f["fecha"]), f["tipo"]), {"trimestre": fc.trimestre_de(f["fecha"]), "tipo": f["tipo"], "facturas": 0, "iva_guilda": 0, "iva_a3": 0})
        c["facturas"] += 1
        c["iva_guilda"] += (-1 if f["abono"] else 1) * sum(l["cuota_iva"] for l in f["lineas"])
        c["iva_a3"] += (-1 if f["abono"] else 1) * abs(a["cuota"])
    for c in cuadre.values():
        c["diferencia"] = c["iva_guilda"] - c["iva_a3"]
    if confirmar and confirmadas:
        conn = db.get_connection()
        try:
            ahora = db.now_iso()
            conn.executemany("UPDATE facturas_contables SET confirmada_en = ? WHERE id = ? AND tenant_id = ?", [(ahora, f["id"], tenant_id) for f in confirmadas])
            for lote_id, l in por_lote.items():
                if lote_id:
                    conn.execute("UPDATE contabilidad_lotes SET comprobado_en = ?, n_confirmadas = (SELECT COUNT(*) FROM facturas_contables WHERE lote_id = ? AND tenant_id = ? AND confirmada_en IS NOT NULL) "
                                 "WHERE id = ? AND tenant_id = ?", (ahora, lote_id, tenant_id, lote_id, tenant_id))
            for f in confirmadas:
                auditoria.registrar(tenant_id, usuario_id, "factura_contable.confirmada_a3", "factura_contable", f["id"], None, conn=conn)
            auditoria.registrar(tenant_id, usuario_id, "contabilidad.retorno_a3", "cliente_fiscal", cliente_fiscal_id,
                                {"leidas": len(filas), "confirmadas": len(confirmadas), "faltan": len(faltan), "con_diferencias": len(con_diferencias)}, conn=conn)
            conn.commit()
        finally:
            conn.close()
    return {"leidas": len(filas), "confirmadas": confirmadas, "ya_confirmadas": ya, "con_diferencias": con_diferencias, "faltan": faltan, "sobran": libres,
            "posibles_parejas": posibles_parejas, "por_lote": sorted(por_lote.values(), key=lambda l: l["lote_id"] or 0), "cuadre": sorted(cuadre.values(), key=lambda c: (c["trimestre"], c["tipo"])), "desde": desde, "hasta": hasta}
