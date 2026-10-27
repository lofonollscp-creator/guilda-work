"""Guilda Fiscal · conciliación con el banco: de un extracto (CSV o Excel) a tres listas: movimientos que casan con una factura, facturas sin movimiento y movimientos sin factura.

**No guarda el extracto ni los movimientos**: se lee, se cruza con las facturas del titular y se enseña el resultado; para volver a verlo se vuelve a subir el fichero. Es lo prudente con datos bancarios y evita
una tabla nueva. La IA no interviene: las reglas son fijas y cada pareja dice por qué se propone. Quien revisa decide; nada se aprueba ni se registra desde aquí.

Importes en céntimos con signo (cargo negativo, ingreso positivo). Una factura emitida se espera como ingreso y una recibida como cargo, por su total (que ya descuenta la retención de IRPF); los abonos al revés.
Solo se cruzan importes **exactos**: un cobro parcial, un pago agrupado de varias facturas o una diferencia por comisión quedan como movimiento sin factura y factura sin movimiento, para mirarlos a mano."""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import acceso, auditoria, db
from .fiscal_perfiles import ErrorFiscal

MAX_BYTES = 3_000_000
MAX_FILAS = 20_000
VENTANA_ANTES = 10                    # días: un movimiento puede ser algo anterior a la fecha de la factura (anticipos, facturas fechadas al cierre)
VENTANA_DESPUES = 150                 # días tras la fecha de la factura en que se espera el cobro o el pago

# Conceptos que casi nunca llevan factura del cliente: se separan para no marearlo con ellos, pero se enseñan.
SIN_FACTURA_ESPERABLE = ("comision", "intereses", "mantenimiento", "seguridad social", "tgss", "tesoreria general", "aeat", "agencia tributaria", "hacienda", "impuesto", "nomina", "cuota autonomo",
                         "seguro social", "prestamo", "amortizacion", "traspaso", "retirada", "ingreso en efectivo", "cajero", "recibo luz", "recibo agua")


@dataclass(frozen=True)
class Movimiento:
    fila: int
    fecha: date
    importe: int                      # céntimos con signo
    concepto: str


def _plano(texto: str) -> str:
    s = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _alnum(texto: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _plano(texto))


# --- Lectura del extracto -----------------------------------------------------------------------------------------------------------------------
def _fecha(valor) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    t = str(valor or "").strip()[:10]
    for formato in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(t, formato).date()
        except ValueError:
            continue
    return None


def _importe(valor) -> int | None:
    """«1.234,56», «-1234,56», «1,234.56», «(50,00)», «50,00-» o un número → céntimos con signo. None si no es un importe."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return int(round(float(valor) * 100))
    t = str(valor).strip().replace("€", "").replace("EUR", "").replace(" ", "").replace("\xa0", "")
    if not t:
        return None
    negativo = t.startswith("-") or t.endswith("-") or (t.startswith("(") and t.endswith(")"))
    t = t.strip("-()+")
    if not re.fullmatch(r"\d[\d.,]*", t):
        return None
    if "," in t and "." in t:
        decimal = "," if t.rfind(",") > t.rfind(".") else "."
        t = t.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    else:
        for separador in (",", "."):
            if separador in t:
                partes = t.split(separador)
                miles = len(partes) > 2 or len(partes[-1]) == 3            # «1.234» o «1,234,567» son miles; «12,5» y «12,50» son decimales
                t = t.replace(separador, "") if miles else t.replace(separador, ".")
    try:
        cent = int(round(float(t) * 100))
    except ValueError:
        return None
    return -cent if negativo else cent


def _filas_csv(contenido: bytes) -> list[list[str]]:
    for codificacion in ("utf-8-sig", "latin-1"):
        try:
            texto = contenido.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    muestra = "\n".join(texto.splitlines()[:30])
    delimitador = max(";,\t|", key=lambda d: muestra.count(d))
    return [list(f) for f in csv.reader(io.StringIO(texto), delimiter=delimitador)]


def _filas_xlsx(contenido: bytes) -> list[list]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    return [list(f) for f in ws.iter_rows(values_only=True, max_row=MAX_FILAS + 50)]


_CAB = {"fecha": ("fecha", "f operacion", "f. operacion", "fecha operacion", "fecha contable", "fecha mov", "fecha movimiento", "date"),
        "valor": ("fecha valor", "f valor", "f. valor"),
        "concepto": ("concepto", "descripcion", "movimiento", "detalle", "observaciones", "concept", "description", "mas datos"),
        "importe": ("importe", "cantidad", "amount", "importe eur", "importe (eur)"),
        "cargo": ("cargo", "cargos", "debe", "debito", "salida", "pagos"),
        "abono": ("abono", "abonos", "haber", "credito", "entrada", "ingresos")}


def _columnas(fila) -> dict[str, int] | None:
    mapa: dict[str, int] = {}
    for i, c in enumerate(fila):
        n = _plano(c)
        for clave, nombres in _CAB.items():
            if clave not in mapa and n in tuple(_plano(x) for x in nombres):
                mapa[clave] = i
    if "fecha" in mapa and ("importe" in mapa or ("cargo" in mapa and "abono" in mapa)):
        return mapa
    return None


def leer_extracto(nombre: str, contenido: bytes) -> tuple[list[Movimiento], list[str]]:
    """Los movimientos de un extracto `.csv` o `.xlsx` y los avisos de lo que no se pudo leer. Busca la fila de cabecera (fecha, concepto, importe o cargo/abono)."""
    if len(contenido) > MAX_BYTES:
        raise ErrorFiscal("El extracto es demasiado grande (máximo 3 MB).")
    if not contenido.strip():
        raise ErrorFiscal("El fichero está vacío.")
    try:
        filas = _filas_xlsx(contenido) if contenido[:2] == b"PK" else _filas_csv(contenido)
    except Exception as e:                                                       # noqa: BLE001 — un fichero que no es lo que dice ser
        raise ErrorFiscal("No se puede leer el extracto: usa un CSV o un Excel (.xlsx) con fecha, concepto e importe.") from e
    cab, inicio = None, 0
    for i, f in enumerate(filas[:60]):
        cab = _columnas(f)
        if cab:
            inicio = i + 1
            break
    if not cab:
        raise ErrorFiscal("No encuentro las columnas del extracto: hacen falta «Fecha», «Concepto» e «Importe» (o «Cargo» y «Abono») en la primera fila.")
    movimientos, ilegibles = [], 0
    for n, f in enumerate(filas[inicio:], inicio + 1):
        f = list(f) + [None] * 12
        fecha = _fecha(f[cab["fecha"]])
        if "importe" in cab:
            importe = _importe(f[cab["importe"]])
        else:
            cargo, abono = _importe(f[cab["cargo"]]), _importe(f[cab["abono"]])
            importe = (abono or 0) - abs(cargo or 0) if (cargo or abono) else None
        if fecha is None or importe is None:
            if any(str(x or "").strip() for x in f[:6]):
                ilegibles += 1
            continue
        movimientos.append(Movimiento(n, fecha, importe, re.sub(r"\s+", " ", str(f[cab["concepto"]] if "concepto" in cab else "") or "").strip()[:200]))
        if len(movimientos) > MAX_FILAS:
            raise ErrorFiscal("El extracto tiene demasiadas filas (máximo 20.000): sube un periodo más corto.")
    avisos = []
    if ilegibles:
        avisos.append(f"{ilegibles} fila(s) del extracto no se han podido leer (sin fecha o sin importe válidos) y se han ignorado.")
    if not movimientos:
        raise ErrorFiscal("El extracto no tiene ningún movimiento legible.")
    return movimientos, avisos


# --- El cruce -----------------------------------------------------------------------------------------------------------------------------------
def _puntuar(m: Movimiento, f: dict) -> tuple[int, list[str]]:
    """Puntos de una pareja con el MISMO importe y fechas compatibles, y por qué."""
    concepto, concepto_alnum = _plano(m.concepto), _alnum(m.concepto)
    puntos, motivos = 0, []
    numero = _alnum(f.get("numero", ""))
    fichas = {_alnum(t) for t in re.split(r"\s+", m.concepto or "") if t}                  # «F-1» como palabra suelta cuenta aunque sea corto; dentro de otra palabra, solo si tiene 4 o más caracteres
    if numero and (numero in fichas or (len(numero) >= 4 and numero in concepto_alnum)):
        puntos += 4
        motivos.append("el concepto lleva el número de factura")
    nif = _alnum(f.get("tercero_nif", "") or "")
    if len(nif) >= 8 and nif in concepto_alnum:
        puntos += 3
        motivos.append("el concepto lleva el NIF")
    palabras = [p for p in _plano(f.get("tercero_nombre", "")).split() if len(p) >= 4 and p not in ("sociedad", "limitada", "anonima", "asociados", "servicios")]
    if any(p in concepto.split() or p in concepto for p in palabras):
        puntos += 2
        motivos.append("el concepto lleva el nombre")
    return puntos, motivos


def conciliar(movimientos: list[Movimiento], facturas: list[dict]) -> dict:
    """`facturas`: `[{id, origen, tipo, fecha: date, numero, tercero_nombre, tercero_nif, esperado: céntimos con signo, en_periodo: bool}]`. Devuelve `conciliados`, `facturas_sin_movimiento` (solo las
    `en_periodo`) y `movimientos_sin_factura`. Cada movimiento y cada factura entran en una sola pareja (primero las de más puntos)."""
    parejas = []
    for m in movimientos:
        for f in facturas:
            if m.importe != f["esperado"] or m.importe == 0:
                continue
            dias = (m.fecha - f["fecha"]).days
            if not -VENTANA_ANTES <= dias <= VENTANA_DESPUES:
                continue
            puntos, motivos = _puntuar(m, f)
            parejas.append((-puntos, abs(dias), m.fila, f["id"], m, f, puntos, motivos))
    parejas.sort(key=lambda p: p[:4])
    usados_m, usados_f, conciliados = set(), set(), []
    for _, _, _, _, m, f, puntos, motivos in parejas:
        if m.fila in usados_m or (f["origen"], f["id"]) in usados_f:
            continue
        usados_m.add(m.fila)
        usados_f.add((f["origen"], f["id"]))
        rivales = [1 for p in parejas if p[4].fila == m.fila and p[5] is not f and p[6] == puntos and (p[5]["origen"], p[5]["id"]) not in usados_f]
        confianza = "seguro" if puntos >= 3 else "probable" if puntos >= 2 else "posible"
        if rivales and puntos < 3:
            confianza, motivos = "posible", motivos + ["hay otra factura del mismo importe: confírmalo"]
        elif not motivos:
            motivos = ["mismo importe y fechas compatibles"]
        conciliados.append({"movimiento": m, "factura": f, "confianza": confianza, "motivos": motivos})
    conciliados.sort(key=lambda c: c["movimiento"].fecha)
    sin_mov = [f for f in facturas if f.get("en_periodo") and (f["origen"], f["id"]) not in usados_f]
    sin_factura = []
    for m in movimientos:
        if m.fila in usados_m:
            continue
        plano = _plano(m.concepto)
        sin_factura.append({"movimiento": m, "sin_factura_esperable": any(k in plano for k in SIN_FACTURA_ESPERABLE)})
    return {"conciliados": conciliados, "facturas_sin_movimiento": sin_mov, "movimientos_sin_factura": sin_factura}


# --- Con los datos del titular ------------------------------------------------------------------------------------------------------------------
def _facturas_candidatas(tenant_id: int, cliente_fiscal_id: int, desde: date, hasta: date, hasta_periodo: date, desde_periodo: date) -> list[dict]:
    """Facturas contables del titular (y apuntes aprobados sin factura) que pueden explicar un movimiento del extracto. `en_periodo`: la fecha cae en el periodo elegido."""
    conn = db.get_connection()
    try:
        facturas = conn.execute("SELECT id, tipo, fecha, numero, tercero_nombre, tercero_nif, abono, total_centimos FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado != 'descartada' "
                                "AND fecha >= ? AND fecha <= ? ORDER BY fecha, id", (tenant_id, cliente_fiscal_id, (desde - timedelta(days=VENTANA_DESPUES)).isoformat(), hasta.isoformat())).fetchall()
        apuntes = conn.execute("SELECT id, libro, fecha_expedicion, serie, numero, contraparte_nombre, contraparte_nif, base_centimos, cuota_centimos, recargo_cuota_centimos, total_centimos, retencion_centimos "
                               "FROM fiscal_apuntes WHERE tenant_id = ? AND cliente_fiscal_id = ? AND factura_id IS NULL AND anulado_en IS NULL AND fecha_expedicion >= ? AND fecha_expedicion <= ?",
                               (tenant_id, cliente_fiscal_id, (desde - timedelta(days=VENTANA_DESPUES)).isoformat(), hasta.isoformat())).fetchall()
    finally:
        conn.close()
    salida = []
    for f in facturas:
        total = abs(f["total_centimos"])
        signo = (1 if f["tipo"] == "emitida" else -1) * (-1 if f["abono"] else 1)
        fecha = date.fromisoformat(f["fecha"][:10])
        salida.append({"id": f["id"], "origen": "factura", "tipo": f["tipo"], "fecha": fecha, "numero": f["numero"], "tercero_nombre": f["tercero_nombre"], "tercero_nif": f["tercero_nif"] or "",
                       "esperado": signo * total, "en_periodo": desde_periodo <= fecha <= hasta_periodo})
    for a in apuntes:
        total = abs(a["total_centimos"]) if a["total_centimos"] is not None else abs(a["base_centimos"] + a["cuota_centimos"] + (a["recargo_cuota_centimos"] or 0))
        total -= abs(a["retencion_centimos"] or 0) if a["libro"] == "R" else 0
        signo = (1 if a["libro"] == "E" else -1) * (-1 if (a["base_centimos"] < 0) else 1)
        fecha = date.fromisoformat(a["fecha_expedicion"][:10])
        salida.append({"id": a["id"], "origen": "apunte", "tipo": "emitida" if a["libro"] == "E" else "recibida", "fecha": fecha, "numero": f"{a['serie'] or ''}{a['numero']}",
                       "tercero_nombre": a["contraparte_nombre"], "tercero_nif": a["contraparte_nif"] or "", "esperado": signo * total, "en_periodo": desde_periodo <= fecha <= hasta_periodo})
    return salida


def conciliar_extracto(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ejercicio: int, periodo: str, nombre_fichero: str, contenido: bytes) -> dict:
    """Lee el extracto y lo cruza con las facturas del titular. Devuelve el resultado de `conciliar` más `avisos`, `movimientos` (total) y el rango de fechas del extracto. No guarda nada salvo una línea de
    auditoría con las cifras (nunca el contenido del extracto)."""
    from .fiscal_nucleo import _limites_periodo
    if not acceso.puede_ver_cliente(tenant_id, usuario_id, cliente_fiscal_id):
        raise ErrorFiscal("No tienes acceso a este titular.", "prohibido")
    if periodo not in tuple(f"{m:02d}" for m in range(1, 13)) + ("1T", "2T", "3T", "4T"):
        raise ErrorFiscal("Periodo no válido.")
    movimientos, avisos = leer_extracto(nombre_fichero, contenido)
    desde_p, hasta_p = (date.fromisoformat(x) for x in _limites_periodo(ejercicio, periodo))
    primero, ultimo = min(m.fecha for m in movimientos), max(m.fecha for m in movimientos)
    facturas = _facturas_candidatas(tenant_id, cliente_fiscal_id, min(primero, desde_p), max(ultimo, hasta_p), hasta_p, desde_p)
    r = conciliar(movimientos, facturas)
    if primero > desde_p or ultimo < hasta_p:
        avisos.append(f"El extracto va del {primero.strftime('%d/%m/%Y')} al {ultimo.strftime('%d/%m/%Y')} y el periodo del {desde_p.strftime('%d/%m/%Y')} al {hasta_p.strftime('%d/%m/%Y')}: "
                      "las facturas cuyo cobro o pago cae fuera del extracto saldrán como «sin movimiento».")
    avisos.append("Solo se cruzan importes exactos. Un pago de varias facturas juntas, un cobro parcial o una diferencia por comisión salen como movimiento sin factura y factura sin movimiento.")
    r.update({"avisos": avisos, "movimientos": len(movimientos), "desde": primero, "hasta": ultimo, "ejercicio": ejercicio, "periodo": periodo})
    auditoria.registrar(tenant_id, usuario_id, "fiscal.conciliacion", "cliente_fiscal", cliente_fiscal_id,
                        {"ejercicio": ejercicio, "periodo": periodo, "movimientos": len(movimientos), "conciliados": len(r["conciliados"]), "facturas_sin_movimiento": len(r["facturas_sin_movimiento"]),
                         "movimientos_sin_factura": len(r["movimientos_sin_factura"])})
    return r
