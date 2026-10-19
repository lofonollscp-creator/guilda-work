"""Facturas para contabilizar: se anotan los datos de cada factura (de un cliente de la gestoría, emitida o recibida), el despacho las revisa y de ahí sale el fichero de enlace que lee a3
(app/enlace_a3.py). No sustituye a la contabilidad: es la entrada de datos que evita teclear cada factura en a3 y que los clientes entreguen a última hora un montón de papeles.

Ciclo de vida: `pendiente` (anotada, sin revisar) → `revisada` (el despacho ha comprobado los datos y no hay nada que impida exportarla) → `exportada` (ya va en un fichero; se puede volver a bajar
ese lote). `descartada` la saca del circuito sin borrarla. Cada exportación es un lote guardado con su contenido para poder descargarlo de nuevo."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from dataclasses import replace

from flask_babel import lazy_gettext as _l

from . import acceso, auditoria, db, enlace_a3, verticales

ESQUEMA = """
CREATE TABLE IF NOT EXISTS contabilidad_clientes (
    cliente_fiscal_id INTEGER PRIMARY KEY REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL,
    a3_empresa TEXT,
    digitos INTEGER NOT NULL DEFAULT 8,
    cuenta_proveedores TEXT NOT NULL DEFAULT '40000000',
    cuenta_clientes TEXT NOT NULL DEFAULT '43000000',
    cuenta_gasto TEXT NOT NULL DEFAULT '62900000',
    cuenta_ingreso TEXT NOT NULL DEFAULT '70000000',
    cuenta_iva_soportado TEXT NOT NULL DEFAULT '47200000',
    cuenta_iva_repercutido TEXT NOT NULL DEFAULT '47700000',
    cuenta_retencion TEXT NOT NULL DEFAULT '47510000'
);
CREATE TABLE IF NOT EXISTS contabilidad_terceros (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL,
    nif TEXT NOT NULL,
    nombre TEXT,
    cuenta TEXT NOT NULL,
    UNIQUE (cliente_fiscal_id, tipo, nif)
);
CREATE TABLE IF NOT EXISTS contabilidad_lotes (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    creado_por INTEGER,
    creado_en TEXT NOT NULL,
    desde TEXT,
    hasta TEXT,
    n_facturas INTEGER NOT NULL,
    n_registros INTEGER NOT NULL,
    contenido BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS facturas_contables (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK (tipo IN ('emitida', 'recibida')),
    origen TEXT NOT NULL DEFAULT 'despacho',
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'revisada', 'exportada', 'descartada')),
    fecha TEXT NOT NULL,
    fecha_operacion TEXT,
    numero TEXT NOT NULL,
    tercero_nombre TEXT NOT NULL,
    tercero_nif TEXT,
    tercero_cuenta TEXT,
    concepto TEXT,
    referencia TEXT,
    abono INTEGER NOT NULL DEFAULT 0,
    rectifica_fecha TEXT,
    rectifica_numero TEXT,
    documento_id INTEGER,
    suplidos_centimos INTEGER NOT NULL DEFAULT 0,
    total_centimos INTEGER NOT NULL,
    notas TEXT,
    creado_por INTEGER,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT NOT NULL,
    revisado_por INTEGER,
    revisado_en TEXT,
    lote_id INTEGER REFERENCES contabilidad_lotes(id)
);
CREATE INDEX IF NOT EXISTS idx_facturas_contables ON facturas_contables(tenant_id, cliente_fiscal_id, estado, fecha);
CREATE TABLE IF NOT EXISTS facturas_contables_lineas (
    id INTEGER PRIMARY KEY,
    factura_id INTEGER NOT NULL REFERENCES facturas_contables(id) ON DELETE CASCADE,
    cuenta TEXT,
    subtipo TEXT NOT NULL DEFAULT '01',
    base_centimos INTEGER NOT NULL,
    pct_iva INTEGER NOT NULL DEFAULT 0,
    cuota_iva INTEGER NOT NULL DEFAULT 0,
    pct_recargo INTEGER NOT NULL DEFAULT 0,
    cuota_recargo INTEGER NOT NULL DEFAULT 0,
    pct_retencion INTEGER NOT NULL DEFAULT 0,
    cuota_retencion INTEGER NOT NULL DEFAULT 0,
    sujeta_iva INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_facturas_contables_lineas ON facturas_contables_lineas(factura_id);
"""
ESTADOS = ("pendiente", "revisada", "exportada", "descartada")
TIPOS = ("emitida", "recibida")
MAX_LINEAS = 8
MAX_NUMERO = 60          # el enlace de a3 admite hasta 60 caracteres (campo ampliado del SII); en las 10 posiciones clásicas va un resumen
TOLERANCIA_CENTIMOS = 2
CONFIG_DEFECTO = {"digitos": 8, "cuenta_proveedores": "40000000", "cuenta_clientes": "43000000", "cuenta_gasto": "62900000", "cuenta_ingreso": "70000000",
                  "cuenta_iva_soportado": "47200000", "cuenta_iva_repercutido": "47700000", "cuenta_retencion": "47510000", "subcuentas_auto": 0}


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    # ampliación posterior: los abonos llevan la factura que rectifican (registro tipo 4 del enlace de a3)
    db._asegurar_columna(conn, "facturas_contables", "rectifica_fecha", "TEXT")
    db._asegurar_columna(conn, "facturas_contables", "rectifica_numero", "TEXT")
    db._asegurar_columna(conn, "facturas_contables", "documento_id", "INTEGER")       # la factura escaneada o fotografiada, en los documentos del cliente
    db._asegurar_columna(conn, "contabilidad_clientes", "subcuentas_auto", "INTEGER NOT NULL DEFAULT 0")   # numerar solas las subcuentas de los terceros nuevos
    db._asegurar_columna(conn, "facturas_contables", "lectura", "TEXT")           # NULL = escrita a mano · pendiente = solo el archivo, por leer · ia = leída por la IA · fallida
    db._asegurar_columna(conn, "facturas_contables", "lectura_error", "TEXT")


# --- Lectura de lo que se escribe -----------------------------------------------------------------------------------------------------------------------

def importe_a_centimos(texto, *, permitir_cero: bool = True, maximo: int = 10**9) -> int:
    """«1.234,56», «1234,56» o «1234.56» → céntimos. `ValueError` con un mensaje legible si no vale."""
    t = str(texto if texto is not None else "").strip().replace("€", "").replace(" ", "")
    if t == "":
        return 0 if permitir_cero else _error("Falta un importe.")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", t):
        t = t.replace(".", "").replace(",", ".")
    elif "," in t and "." not in t:
        t = t.replace(",", ".")
    try:
        v = Decimal(t)
    except InvalidOperation:
        raise ValueError(f"El importe «{str(texto)[:20]}» no es válido: escríbelo como 1.234,56.") from None
    if v < 0:
        raise ValueError("Los importes se escriben en positivo; para un abono marca «Es un abono».")
    c = int((v * 100).quantize(Decimal("1")))
    if c > maximo:
        raise ValueError("El importe es demasiado grande.")
    return c


def _error(mensaje: str):
    raise ValueError(mensaje)


def porcentaje_a_centesimas(texto) -> int:
    """«21», «21,5» o «4.00» → centésimas de punto (2100, 2150, 400). Vacío = 0."""
    t = str(texto if texto is not None else "").strip().replace("%", "").replace(",", ".").replace(" ", "")
    if t == "":
        return 0
    try:
        v = Decimal(t)
    except InvalidOperation:
        raise ValueError(f"El porcentaje «{str(texto)[:10]}» no es válido.") from None
    if v < 0 or v > 100:
        raise ValueError("Un porcentaje debe estar entre 0 y 100.")
    return int((v * 100).quantize(Decimal("1")))


def _fecha(texto, campo: str) -> str:
    try:
        return date.fromisoformat(str(texto or "").strip()[:10]).isoformat()
    except ValueError:
        raise ValueError(f"{campo}: indica una fecha válida (AAAA-MM-DD).") from None


def trimestre_de(fecha: str) -> str:
    return f"{fecha[:4]}-T{(int(fecha[5:7]) - 1) // 3 + 1}"


def rango_del_trimestre(trimestre: str) -> tuple[str, str]:
    """«2026-T3» → («2026-07-01», «2026-09-30»)."""
    m = re.fullmatch(r"(\d{4})-T([1-4])", trimestre or "")
    if not m:
        raise ValueError("Elige un trimestre válido.")
    anio, t = int(m.group(1)), int(m.group(2))
    ini = date(anio, (t - 1) * 3 + 1, 1)
    fin = date(anio + (t == 4), 1 if t == 4 else t * 3 + 1, 1)
    return ini.isoformat(), (fin.fromordinal(fin.toordinal() - 1)).isoformat()


# --- Configuración de a3 por cliente ----------------------------------------------------------------------------------------------------------------------

def _cliente(tenant_id: int, usuario_id: int, cliente_fiscal_id: int):
    f = db.obtener_cliente_fiscal(tenant_id, cliente_fiscal_id)
    if f is None or not acceso.puede_ver_cliente(tenant_id, usuario_id, cliente_fiscal_id):
        raise ValueError("Cliente no encontrado.")
    return f


def configuracion(tenant_id: int, cliente_fiscal_id: int) -> dict:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM contabilidad_clientes WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id)).fetchone()
    finally:
        conn.close()
    return {**CONFIG_DEFECTO, "a3_empresa": None, **({k: f[k] for k in f.keys() if k not in ("cliente_fiscal_id", "tenant_id")} if f else {})}


def _cuenta_valida(valor, campo: str, digitos: int) -> str:
    d = re.sub(r"\D", "", str(valor or ""))
    if len(d) < 3 or len(d) > 12:
        raise ValueError(f"{campo}: escribe una cuenta de entre 3 y 12 dígitos.")
    return d


def guardar_configuracion(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, datos: dict) -> dict:
    _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    empresa = re.sub(r"\D", "", str(datos.get("a3_empresa") or ""))
    if empresa and len(empresa) > 5:
        raise ValueError("El código de empresa de a3 tiene como máximo 5 dígitos.")
    try:
        digitos = int(datos.get("digitos") or 8)
    except ValueError:
        raise ValueError("Los dígitos de las subcuentas deben ser un número.") from None
    if not 4 <= digitos <= 12:
        raise ValueError("Los dígitos de las subcuentas deben estar entre 4 y 12.")
    cuentas = {k: _cuenta_valida(datos.get(k) or CONFIG_DEFECTO[k], etiqueta, digitos) for k, etiqueta in (
        ("cuenta_proveedores", "Subcuenta genérica de proveedores"), ("cuenta_clientes", "Subcuenta genérica de clientes"), ("cuenta_gasto", "Cuenta de gasto por defecto"),
        ("cuenta_ingreso", "Cuenta de ingreso por defecto"), ("cuenta_iva_soportado", "Cuenta de IVA soportado"), ("cuenta_iva_repercutido", "Cuenta de IVA repercutido"),
        ("cuenta_retencion", "Cuenta de retenciones"))}
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO contabilidad_clientes (cliente_fiscal_id, tenant_id, a3_empresa, digitos, cuenta_proveedores, cuenta_clientes, cuenta_gasto, cuenta_ingreso, cuenta_iva_soportado, "
                     "cuenta_iva_repercutido, cuenta_retencion, subcuentas_auto) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(cliente_fiscal_id) DO UPDATE SET a3_empresa = excluded.a3_empresa, subcuentas_auto = excluded.subcuentas_auto, "
                     "digitos = excluded.digitos, cuenta_proveedores = excluded.cuenta_proveedores, cuenta_clientes = excluded.cuenta_clientes, cuenta_gasto = excluded.cuenta_gasto, "
                     "cuenta_ingreso = excluded.cuenta_ingreso, cuenta_iva_soportado = excluded.cuenta_iva_soportado, cuenta_iva_repercutido = excluded.cuenta_iva_repercutido, "
                     "cuenta_retencion = excluded.cuenta_retencion",
                     (cliente_fiscal_id, tenant_id, empresa or None, digitos, *[cuentas[k] for k in ("cuenta_proveedores", "cuenta_clientes", "cuenta_gasto", "cuenta_ingreso",
                                                                                                  "cuenta_iva_soportado", "cuenta_iva_repercutido", "cuenta_retencion")], 1 if datos.get("subcuentas_auto") in (1, "1", "on", True) else 0))
        auditoria.registrar(tenant_id, usuario_id, "contabilidad.configuracion", "cliente_fiscal", cliente_fiscal_id, {"a3_empresa": empresa or None, "digitos": digitos}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return configuracion(tenant_id, cliente_fiscal_id)


def cuenta_del_tercero(tenant_id: int, cliente_fiscal_id: int, tipo_factura: str, nif: str | None) -> str | None:
    """La subcuenta recordada de ese proveedor (recibidas) o cliente (emitidas) por su NIF, o None."""
    if not nif:
        return None
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT cuenta FROM contabilidad_terceros WHERE cliente_fiscal_id = ? AND tenant_id = ? AND tipo = ? AND nif = ?",
                         (cliente_fiscal_id, tenant_id, "proveedor" if tipo_factura == "recibida" else "cliente", _nif(nif))).fetchone()
    finally:
        conn.close()
    return f["cuenta"] if f else None


def _nif(valor) -> str:
    return re.sub(r"[\s.\-]", "", str(valor or "")).upper()


def _recordar_tercero(conn, tenant_id: int, cliente_fiscal_id: int, tipo_factura: str, nif: str, nombre: str, cuenta: str) -> None:
    if nif and cuenta:
        conn.execute("INSERT INTO contabilidad_terceros (tenant_id, cliente_fiscal_id, tipo, nif, nombre, cuenta) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(cliente_fiscal_id, tipo, nif) DO UPDATE SET "
                     "cuenta = excluded.cuenta, nombre = excluded.nombre",
                     (tenant_id, cliente_fiscal_id, "proveedor" if tipo_factura == "recibida" else "cliente", nif, nombre[:100], cuenta))


def _subcuentas_nuevas(tenant_id: int, cfg: dict, facturas: list[dict]) -> dict[tuple[str, str], tuple[str, str]]:
    """Con `subcuentas_auto`, la subcuenta que toca a cada tercero (por NIF) que aún no tiene la suya: la siguiente libre tras la genérica (40000001, 40000002… / 43000001…).
    Nunca repite una que el cliente ya use, ni las escritas a mano. Devuelve {(tipo_tercero, nif): (cuenta, nombre)}; no escribe nada."""
    if not cfg.get("subcuentas_auto") or not facturas:
        return {}
    cliente_id = facturas[0]["cliente_fiscal_id"]
    conn = db.get_connection()
    try:
        usadas = {"proveedor": set(), "cliente": set()}
        for r in conn.execute("SELECT tipo, cuenta FROM contabilidad_terceros WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_id, tenant_id)):
            usadas[r["tipo"]].add(r["cuenta"])
        for r in conn.execute("SELECT tipo, tercero_cuenta FROM facturas_contables WHERE cliente_fiscal_id = ? AND tenant_id = ? AND tercero_cuenta IS NOT NULL", (cliente_id, tenant_id)):
            usadas["proveedor" if r["tipo"] == "recibida" else "cliente"].add(r["tercero_cuenta"])
    finally:
        conn.close()
    res: dict[tuple[str, str], tuple[str, str]] = {}
    for f in sorted(facturas, key=lambda f: (f["fecha"], f["id"])):
        nif = _nif(f.get("tercero_nif"))
        tipo = "proveedor" if f["tipo"] == "recibida" else "cliente"
        if not nif or f.get("tercero_cuenta") or (tipo, nif) in res or cuenta_del_tercero(tenant_id, cliente_id, f["tipo"], nif):
            continue
        generica = cfg["cuenta_proveedores"] if tipo == "proveedor" else cfg["cuenta_clientes"]
        ancho = cfg["digitos"]
        prefijo = generica[:3]
        hueco = ancho - len(prefijo)
        propias = usadas[tipo] | {generica} | {c for (t, _n), (c, _nom) in res.items() if t == tipo}
        mayor = max([int(c[len(prefijo):]) for c in propias if len(c) == ancho and c.startswith(prefijo) and c[len(prefijo):].isdigit()] + [0])
        siguiente = mayor + 1
        if len(str(siguiente)) > hueco:
            raise ValueError(f"No quedan subcuentas libres de {ancho} dígitos para los {'proveedores' if tipo == 'proveedor' else 'clientes'} de este cliente.")
        res[(tipo, nif)] = (prefijo + str(siguiente).zfill(hueco), f["tercero_nombre"])
    return res


def terceros_del_cliente(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> list[dict]:
    """Las subcuentas recordadas de proveedores y clientes (para que el despacho las tenga a la vista al configurar)."""
    _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT tipo, nif, nombre, cuenta FROM contabilidad_terceros WHERE cliente_fiscal_id = ? AND tenant_id = ? ORDER BY tipo, cuenta", (cliente_fiscal_id, tenant_id))]
    finally:
        conn.close()


# --- Alta, edición y comprobación ----------------------------------------------------------------------------------------------------------------------

def _lineas_limpias(lineas: list[dict]) -> list[dict]:
    """Las líneas de IVA escritas, con las cuotas calculadas cuando se dejan en blanco. Se descartan las vacías."""
    res = []
    for i, l in enumerate(lineas, start=1):
        if not any(str(l.get(k) or "").strip() for k in ("base", "cuota_iva", "pct_iva")):
            continue
        base = importe_a_centimos(l.get("base"))
        pct_iva, pct_re, pct_ret = (porcentaje_a_centesimas(l.get(k)) for k in ("pct_iva", "pct_recargo", "pct_retencion"))
        if base <= 0:
            raise ValueError(f"Línea {i}: indica la base imponible.")
        cuota_iva = importe_a_centimos(l.get("cuota_iva")) if str(l.get("cuota_iva") or "").strip() else enlace_a3.cuota(base, pct_iva)
        cuota_re = importe_a_centimos(l.get("cuota_recargo")) if str(l.get("cuota_recargo") or "").strip() else enlace_a3.cuota(base, pct_re)
        cuota_ret = importe_a_centimos(l.get("cuota_retencion")) if str(l.get("cuota_retencion") or "").strip() else enlace_a3.cuota(base, pct_ret)
        cuenta = re.sub(r"\D", "", str(l.get("cuenta") or "")) or None
        res.append({"cuenta": cuenta, "subtipo": re.sub(r"\D", "", str(l.get("subtipo") or "")).zfill(2)[-2:] or "01", "base_centimos": base, "pct_iva": pct_iva, "cuota_iva": cuota_iva,
                    "pct_recargo": pct_re, "cuota_recargo": cuota_re, "pct_retencion": pct_ret, "cuota_retencion": cuota_ret, "sujeta_iva": 0 if str(l.get("sujeta_iva")) == "0" else 1})
    if not res:
        raise ValueError("Añade al menos una línea con la base imponible y el IVA.")
    if len(res) > MAX_LINEAS:
        raise ValueError(f"Como máximo {MAX_LINEAS} tipos de IVA por factura.")
    return res


def _total_de(lineas: list[dict], suplidos: int) -> int:
    return sum(l["base_centimos"] + l["cuota_iva"] + l["cuota_recargo"] - l["cuota_retencion"] for l in lineas) + suplidos


def _datos_limpios(datos: dict) -> dict:
    tipo = datos.get("tipo")
    if tipo not in TIPOS:
        raise ValueError("Indica si es una factura emitida o recibida.")
    nombre = str(datos.get("tercero_nombre") or "").strip()
    if not nombre:
        raise ValueError("Indica el nombre del proveedor o cliente de la factura.")
    numero = str(datos.get("numero") or "").strip()
    if not numero:
        raise ValueError("Indica el número de factura.")
    fecha = _fecha(datos.get("fecha"), "Fecha de la factura")
    return {"tipo": tipo, "fecha": fecha, "fecha_operacion": _fecha(datos["fecha_operacion"], "Fecha de operación") if str(datos.get("fecha_operacion") or "").strip() else fecha,
            "numero": numero[:MAX_NUMERO], "tercero_nombre": nombre[:100], "tercero_nif": _nif(datos.get("tercero_nif"))[:20] or None,
            "tercero_cuenta": re.sub(r"\D", "", str(datos.get("tercero_cuenta") or ""))[:12] or None, "concepto": str(datos.get("concepto") or "").strip()[:60] or None,
            "referencia": str(datos.get("referencia") or "").strip()[:60] or None, "abono": 1 if datos.get("abono") in (True, 1, "1", "on", "true") else 0,
            "rectifica_fecha": _fecha(datos["rectifica_fecha"], "Fecha de la factura que rectifica") if str(datos.get("rectifica_fecha") or "").strip() else None,
            "rectifica_numero": str(datos.get("rectifica_numero") or "").strip()[:60] or None,
            "suplidos_centimos": importe_a_centimos(datos.get("suplidos")), "notas": str(datos.get("notas") or "").strip()[:1000] or None}


def crear(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, datos: dict, lineas: list[dict], origen: str = "despacho", documento_id: int | None = None) -> int:
    f = _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    return _insertar(tenant_id, usuario_id, f, datos, lineas, origen, documento_id)


def _insertar(tenant_id: int, usuario_id: int | None, f, datos: dict, lineas: list[dict], origen: str, documento_id: int | None) -> int:
    cliente_fiscal_id = f["id"]
    d = _datos_limpios(datos)
    ls = _lineas_limpias(lineas)
    total = _total_de(ls, d["suplidos_centimos"])
    ahora = db.now_iso()
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO facturas_contables (tenant_id, cliente_fiscal_id, tipo, origen, estado, fecha, fecha_operacion, numero, tercero_nombre, tercero_nif, tercero_cuenta, concepto, "
                           "referencia, abono, rectifica_fecha, rectifica_numero, suplidos_centimos, total_centimos, notas, creado_por, creado_en, actualizado_en, documento_id) VALUES (?, ?, ?, ?, 'pendiente', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, cliente_fiscal_id, d["tipo"], origen, d["fecha"], d["fecha_operacion"], d["numero"], d["tercero_nombre"], d["tercero_nif"], d["tercero_cuenta"], d["concepto"],
                            d["referencia"], d["abono"], d["rectifica_fecha"], d["rectifica_numero"], d["suplidos_centimos"], total, d["notas"], usuario_id, ahora, ahora, documento_id))
        fid = cur.lastrowid
        _guardar_lineas(conn, fid, ls)
        if d["tercero_cuenta"]:
            _recordar_tercero(conn, tenant_id, cliente_fiscal_id, d["tipo"], d["tercero_nif"] or "", d["tercero_nombre"], d["tercero_cuenta"])
        auditoria.registrar(tenant_id, usuario_id, "factura_contable.creada", "factura_contable", fid, {"cliente": f["nombre"], "tipo": d["tipo"], "numero": d["numero"], "total": total}, conn=conn)
        conn.commit()
        return fid
    finally:
        conn.close()


def _guardar_lineas(conn, factura_id: int, lineas: list[dict]) -> None:
    conn.execute("DELETE FROM facturas_contables_lineas WHERE factura_id = ?", (factura_id,))
    conn.executemany("INSERT INTO facturas_contables_lineas (factura_id, cuenta, subtipo, base_centimos, pct_iva, cuota_iva, pct_recargo, cuota_recargo, pct_retencion, cuota_retencion, sujeta_iva) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     [(factura_id, l["cuenta"], l["subtipo"], l["base_centimos"], l["pct_iva"], l["cuota_iva"], l["pct_recargo"], l["cuota_recargo"], l["pct_retencion"], l["cuota_retencion"],
                       l["sujeta_iva"]) for l in lineas])


def obtener(tenant_id: int, usuario_id: int, factura_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT x.*, c.nombre AS cliente_nombre FROM facturas_contables x JOIN clientes_fiscales c ON c.id = x.cliente_fiscal_id WHERE x.id = ? AND x.tenant_id = ?",
                         (factura_id, tenant_id)).fetchone()
        if f is None or not acceso.puede_ver_cliente(tenant_id, usuario_id, f["cliente_fiscal_id"]):
            return None
        d = dict(f)
        d["lineas"] = [dict(l) for l in conn.execute("SELECT * FROM facturas_contables_lineas WHERE factura_id = ? ORDER BY id", (factura_id,))]
    finally:
        conn.close()
    d["trimestre"] = trimestre_de(d["fecha"])
    d["problemas"] = problemas(tenant_id, d)
    return d


def actualizar(tenant_id: int, usuario_id: int, factura_id: int, datos: dict, lineas: list[dict], documento_id: int | None = None) -> None:
    """Corrige una factura que aún no se ha exportado. Al cambiarla vuelve a `pendiente`: hay que revisarla otra vez."""
    f = obtener(tenant_id, usuario_id, factura_id)
    if f is None:
        raise ValueError("Factura no encontrada.")
    if f["estado"] == "exportada":
        raise ValueError("Esa factura ya se exportó: no se puede cambiar. Si hace falta corregirla, reábrela antes.")
    d = _datos_limpios({**datos, "tipo": f["tipo"]})
    ls = _lineas_limpias(lineas)
    total = _total_de(ls, d["suplidos_centimos"])
    conn = db.get_connection()
    try:
        conn.execute("UPDATE facturas_contables SET estado = 'pendiente', fecha = ?, fecha_operacion = ?, numero = ?, tercero_nombre = ?, tercero_nif = ?, tercero_cuenta = ?, concepto = ?, referencia = ?, "
                     "abono = ?, rectifica_fecha = ?, rectifica_numero = ?, suplidos_centimos = ?, total_centimos = ?, notas = ?, actualizado_en = ?, revisado_por = NULL, revisado_en = NULL, "
                     "documento_id = COALESCE(?, documento_id), lectura = CASE WHEN lectura IN ('pendiente', 'fallida') THEN NULL ELSE lectura END, "
                     "lectura_error = CASE WHEN lectura IN ('pendiente', 'fallida') THEN NULL ELSE lectura_error END WHERE id = ? AND tenant_id = ?",
                     (d["fecha"], d["fecha_operacion"], d["numero"], d["tercero_nombre"], d["tercero_nif"], d["tercero_cuenta"], d["concepto"], d["referencia"], d["abono"], d["rectifica_fecha"], d["rectifica_numero"],
                      d["suplidos_centimos"], total, d["notas"], db.now_iso(), documento_id, factura_id, tenant_id))
        _guardar_lineas(conn, factura_id, ls)
        if d["tercero_cuenta"]:
            _recordar_tercero(conn, tenant_id, f["cliente_fiscal_id"], f["tipo"], d["tercero_nif"] or "", d["tercero_nombre"], d["tercero_cuenta"])
        auditoria.registrar(tenant_id, usuario_id, "factura_contable.editada", "factura_contable", factura_id, {"numero": d["numero"], "total": total}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def cuenta_efectiva(tenant_id: int, f: dict, cfg: dict | None = None) -> str | None:
    """La subcuenta con la que se contabiliza el tercero: la escrita en la factura, la recordada por su NIF o la genérica del cliente."""
    cfg = cfg or configuracion(tenant_id, f["cliente_fiscal_id"])
    return f.get("tercero_cuenta") or cuenta_del_tercero(tenant_id, f["cliente_fiscal_id"], f["tipo"], f.get("tercero_nif")) or (
        cfg["cuenta_proveedores"] if f["tipo"] == "recibida" else cfg["cuenta_clientes"])


def problemas(tenant_id: int, f: dict) -> list[str]:
    """Lo que impide dar por buena y exportar una factura (lista vacía = lista para revisar)."""
    cfg = configuracion(tenant_id, f["cliente_fiscal_id"])
    res = []
    if f.get("lectura") == "pendiente":
        res.append("Es solo el archivo de la factura: léela con la IA o rellena sus datos.")
    elif f.get("lectura") == "fallida":
        res.append("No se pudo leer el archivo: " + (f.get("lectura_error") or "rellena los datos a mano."))
    if not cfg["a3_empresa"]:
        res.append("Falta el código de empresa de a3 de este cliente (en Configuración de a3).")
    if f["abono"] and not (f.get("rectifica_numero") and f.get("rectifica_fecha")):
        res.append("Un abono o rectificativa necesita el número y la fecha de la factura que rectifica: a3 lo exige.")
    if not f.get("tercero_nif"):
        res.append("Falta el NIF del proveedor o cliente.")
    ls = f.get("lineas") or []
    if not ls:
        res.append("No tiene líneas de IVA.")
    for i, l in enumerate(ls, start=1):
        esperada = enlace_a3.cuota(l["base_centimos"], l["pct_iva"])
        if abs(esperada - l["cuota_iva"]) > TOLERANCIA_CENTIMOS and l["sujeta_iva"]:
            res.append(f"Línea {i}: la cuota de IVA ({l['cuota_iva'] / 100:.2f}) no coincide con la base por el porcentaje ({esperada / 100:.2f}).")
    if ls and f["total_centimos"] != _total_de(ls, f["suplidos_centimos"]):
        res.append("El total no cuadra con las líneas.")
    return res


def cambiar_estado(tenant_id: int, usuario_id: int, factura_id: int, nuevo: str) -> None:
    """`revisada` (solo si no hay problemas), `pendiente` (reabrir; una exportada solo si se reabre aposta), `descartada`."""
    f = obtener(tenant_id, usuario_id, factura_id)
    if f is None:
        raise ValueError("Factura no encontrada.")
    if nuevo not in ESTADOS or nuevo == "exportada":
        raise ValueError("Estado no válido.")
    if nuevo == "revisada":
        if f["estado"] not in ("pendiente",):
            raise ValueError("Solo se puede revisar una factura pendiente.")
        if f["problemas"]:
            raise ValueError("No se puede dar por revisada: " + " ".join(f["problemas"]))
    conn = db.get_connection()
    try:
        conn.execute("UPDATE facturas_contables SET estado = ?, actualizado_en = ?, revisado_por = ?, revisado_en = ?, lote_id = CASE WHEN ? = 'exportada' THEN lote_id ELSE NULL END WHERE id = ? AND tenant_id = ?",
                     (nuevo, db.now_iso(), usuario_id if nuevo == "revisada" else None, db.now_iso() if nuevo == "revisada" else None, nuevo, factura_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, f"factura_contable.{nuevo}", "factura_contable", factura_id, {"antes": f["estado"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def listar(tenant_id: int, usuario_id: int, *, cliente_fiscal_id: int | None = None, estado: str | None = None, tipo: str | None = None, desde: str | None = None, hasta: str | None = None,
           limite: int = 300) -> list[dict]:
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    donde, p = ["x.tenant_id = ?"], [tenant_id]
    for campo, valor in (("x.cliente_fiscal_id", cliente_fiscal_id), ("x.estado", estado), ("x.tipo", tipo)):
        if valor:
            donde.append(f"{campo} = ?"); p.append(valor)
    if desde:
        donde.append("x.fecha >= ?"); p.append(desde)
    if hasta:
        donde.append("x.fecha <= ?"); p.append(hasta)
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute(
            "SELECT x.*, c.nombre AS cliente_nombre FROM facturas_contables x JOIN clientes_fiscales c ON c.id = x.cliente_fiscal_id WHERE " + " AND ".join(donde) +
            " ORDER BY x.fecha DESC, x.id DESC LIMIT ?", [*p, limite])]
    finally:
        conn.close()
    return [f for f in filas if visibles is None or f["cliente_fiscal_id"] in visibles]


def resumen_por_estado(tenant_id: int, usuario_id: int, cliente_fiscal_id: int | None = None) -> dict[str, int]:
    cuentas = {e: 0 for e in ESTADOS}
    for f in listar(tenant_id, usuario_id, cliente_fiscal_id=cliente_fiscal_id, limite=5000):
        cuentas[f["estado"]] += 1
    return cuentas


# --- Exportar a a3 ---------------------------------------------------------------------------------------------------------------------------------------

def _para_enlace(tenant_id: int, f: dict, cfg: dict, nuevas: dict | None = None) -> dict:
    gasto_o_ingreso = cfg["cuenta_gasto"] if f["tipo"] == "recibida" else cfg["cuenta_ingreso"]
    cuenta_iva = cfg["cuenta_iva_soportado"] if f["tipo"] == "recibida" else cfg["cuenta_iva_repercutido"]
    return {"tipo": f["tipo"], "abono": bool(f["abono"]), "fecha": f["fecha"], "fecha_operacion": f["fecha_operacion"], "numero": f["numero"], "rectifica_fecha": f.get("rectifica_fecha"), "rectifica_numero": f.get("rectifica_numero"), "concepto": f["concepto"] or (
        ("Su Fra. " if f["tipo"] == "recibida" else "Nuestra Fra. ") + f["numero"]), "nif": f["tercero_nif"], "nombre": f["tercero_nombre"],
        "cuenta_tercero": (nuevas or {}).get(("proveedor" if f["tipo"] == "recibida" else "cliente", _nif(f["tercero_nif"])), (None,))[0] or cuenta_efectiva(tenant_id, f, cfg), "total_centimos": f["total_centimos"],
        "lineas": [{"cuenta": l["cuenta"] or gasto_o_ingreso, "descripcion_cuenta": "Compras" if f["tipo"] == "recibida" else "Ventas", "subtipo": l["subtipo"], "base_centimos": l["base_centimos"], "pct_iva": l["pct_iva"], "cuota_iva": l["cuota_iva"],
                    "pct_recargo": l["pct_recargo"], "cuota_recargo": l["cuota_recargo"], "pct_retencion": l["pct_retencion"], "cuota_retencion": l["cuota_retencion"],
                    "sujeta_iva": bool(l["sujeta_iva"]), "cuenta_iva": cuenta_iva, "cuenta_retencion": cfg["cuenta_retencion"] if l["cuota_retencion"] else None}
                   for l in f["lineas"]]}


def exportar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, *, desde: str | None = None, hasta: str | None = None) -> dict:
    """Genera el SUENLACE.DAT con las facturas **revisadas** del cliente (en el rango de fechas, si se da), las marca como exportadas y guarda el lote. `ValueError` si no hay nada que exportar."""
    cliente = _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    cfg = configuracion(tenant_id, cliente_fiscal_id)
    if not cfg["a3_empresa"]:
        raise ValueError("Indica antes el código de empresa de a3 de este cliente.")
    facturas = [obtener(tenant_id, usuario_id, f["id"]) for f in listar(tenant_id, usuario_id, cliente_fiscal_id=cliente_fiscal_id, estado="revisada", desde=desde, hasta=hasta, limite=5000)]
    facturas = sorted([f for f in facturas if f], key=lambda f: (f["fecha"], f["id"]))
    if not facturas:
        raise ValueError("No hay facturas revisadas pendientes de exportar en ese periodo.")
    for f in facturas:
        if f["problemas"]:
            raise ValueError(f"La factura {f['numero']} tiene problemas: " + " ".join(f["problemas"]))
    nuevas = _subcuentas_nuevas(tenant_id, cfg, facturas)
    contenido = enlace_a3.generar([_para_enlace(tenant_id, f, cfg, nuevas) for f in facturas], empresa=cfg["a3_empresa"], digitos=cfg["digitos"])
    n_registros = contenido.count(b"\r\n")
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO contabilidad_lotes (tenant_id, cliente_fiscal_id, creado_por, creado_en, desde, hasta, n_facturas, n_registros, contenido) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, cliente_fiscal_id, usuario_id, db.now_iso(), desde, hasta, len(facturas), n_registros, contenido))
        lote = cur.lastrowid
        conn.executemany("UPDATE facturas_contables SET estado = 'exportada', lote_id = ?, actualizado_en = ? WHERE id = ? AND tenant_id = ?", [(lote, db.now_iso(), f["id"], tenant_id) for f in facturas])
        for (tipo_tercero, nif), (cuenta, nombre) in nuevas.items():
            conn.execute("INSERT INTO contabilidad_terceros (tenant_id, cliente_fiscal_id, tipo, nif, nombre, cuenta) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(cliente_fiscal_id, tipo, nif) DO NOTHING",
                         (tenant_id, cliente_fiscal_id, tipo_tercero, nif, nombre[:100], cuenta))
        auditoria.registrar(tenant_id, usuario_id, "contabilidad.exportada", "cliente_fiscal", cliente_fiscal_id,
                            {"lote": lote, "facturas": len(facturas), "desde": desde, "hasta": hasta, "subcuentas_nuevas": len(nuevas)}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return {"lote": lote, "n_facturas": len(facturas), "n_registros": n_registros, "contenido": contenido, "cliente": cliente["nombre"]}


def listar_lotes(tenant_id: int, usuario_id: int, cliente_fiscal_id: int | None = None, limite: int = 50) -> list[dict]:
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute(
            "SELECT l.id, l.cliente_fiscal_id, l.creado_en, l.desde, l.hasta, l.n_facturas, l.n_registros, c.nombre AS cliente_nombre FROM contabilidad_lotes l JOIN clientes_fiscales c ON c.id = l.cliente_fiscal_id "
            "WHERE l.tenant_id = ?" + (" AND l.cliente_fiscal_id = ?" if cliente_fiscal_id else "") + " ORDER BY l.id DESC LIMIT ?", [tenant_id, *([cliente_fiscal_id] if cliente_fiscal_id else []), limite])]
    finally:
        conn.close()
    return [f for f in filas if visibles is None or f["cliente_fiscal_id"] in visibles]


def contenido_del_lote(tenant_id: int, usuario_id: int, lote_id: int) -> bytes | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT cliente_fiscal_id, contenido FROM contabilidad_lotes WHERE id = ? AND tenant_id = ?", (lote_id, tenant_id)).fetchone()
    finally:
        conn.close()
    if f is None or not acceso.puede_ver_cliente(tenant_id, usuario_id, f["cliente_fiscal_id"]):
        return None
    return bytes(f["contenido"])


# --- Subida desde el portal del cliente ------------------------------------------------------------------------------------------------------------------

MAX_PENDIENTES_DEL_PORTAL = 300
MIME_ADJUNTO = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}
MAX_ADJUNTO_BYTES = 8 * 1024 * 1024
TEXTO_ESTADO_PORTAL = {"pendiente": _l("Recibida: el despacho la revisará"), "revisada": _l("Revisada por el despacho"), "exportada": _l("Contabilizada"),
                       "descartada": _l("No válida: el despacho te contactará")}


def adjuntar(tenant_id: int, cliente_fiscal_id: int, usuario_id: int | None, nombre: str, tipo_mime: str | None, contenido: bytes) -> int:
    """Guarda la factura escaneada o fotografiada en los documentos del cliente (por el almacén de documentos: sellada con la clave del despacho si la tiene activada, como cualquier otro documento)
    y devuelve su id. `ValueError` con un mensaje legible si no vale. Un mismo archivo subido dos veces no se duplica."""
    from . import almacen_documentos
    mime = (tipo_mime or "").lower().split(";")[0]
    if mime not in MIME_ADJUNTO or len(contenido or b"") > MAX_ADJUNTO_BYTES:
        raise ValueError("Archivo no válido: solo imágenes o PDF, hasta 8 MB.")
    if usuario_id is None:
        resultado, doc = almacen_documentos.guardar_de_cliente_fiscal_sin_usuario(tenant_id, cliente_fiscal_id, nombre, mime, contenido, "Factura")
    else:
        resultado, doc = almacen_documentos.guardar_de_cliente_fiscal(usuario_id, cliente_fiscal_id, nombre, mime, contenido, categoria="Factura")
    if resultado in ("ok", "duplicado"):
        return doc
    raise ValueError({"vacio": "El archivo está vacío.", "grande": "Archivo no válido: solo imágenes o PDF, hasta 8 MB.", "limite": "Se ha alcanzado el máximo de documentos de este cliente.",
                      "clave_privada": "Ese archivo no se puede guardar."}.get(resultado, "No se ha podido guardar el archivo."))


def _desglose_desde_el_total(total_centimos: int, pct_centesimas: int) -> tuple[int, int]:
    """(base, cuota) de una factura de la que solo se conoce el total y el tipo de IVA."""
    base = int((Decimal(total_centimos) * Decimal(10000) / Decimal(10000 + pct_centesimas)).quantize(Decimal("1")))
    return base, total_centimos - base


def crear_desde_portal(cliente_fiscal_id: int, datos: dict, archivo: tuple[str, str | None, bytes] | None = None) -> int:
    """El cliente apunta una factura suya desde su portal con lo que sabe: tipo, fecha, número, proveedor o cliente, total y tipo de IVA. Queda `pendiente`: el despacho la completa y la revisa.
    `datos["complicada"]` (lleva retención o varios tipos de IVA) lo deja anotado para que el despacho la complete con la factura delante. `ValueError` con un mensaje legible si algo no vale."""
    f = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    if f is None:
        raise ValueError("Cliente no encontrado.")
    tenant_id = f["tenant_id"]
    conn = db.get_connection()
    try:
        pendientes = conn.execute("SELECT COUNT(*) FROM facturas_contables WHERE cliente_fiscal_id = ? AND origen = 'portal' AND estado = 'pendiente'", (cliente_fiscal_id,)).fetchone()[0]
    finally:
        conn.close()
    if pendientes >= MAX_PENDIENTES_DEL_PORTAL:
        raise ValueError("Tienes muchas facturas pendientes de revisar: espera a que el despacho las procese.")
    total = importe_a_centimos(datos.get("total"), permitir_cero=False)
    if total <= 0:
        raise ValueError("Indica el total de la factura.")
    pct = porcentaje_a_centesimas(datos.get("pct_iva"))
    base, cuota_iva = _desglose_desde_el_total(total, pct)
    notas = "Anotada por el cliente desde el portal."
    if str(datos.get("complicada")) in ("1", "on", "true", "True"):
        notas += " PENDIENTE DE COMPLETAR: lleva retención o más de un tipo de IVA; el desglose de abajo es solo una aproximación a partir del total."
    documento_id = adjuntar(tenant_id, cliente_fiscal_id, None, *archivo) if archivo else None
    fid = _insertar(tenant_id, None, f, {**{k: datos.get(k) for k in ("tipo", "fecha", "numero", "tercero_nombre", "tercero_nif", "concepto")}, "notas": notas},
                    [{"base": f"{base / 100:.2f}", "pct_iva": str(pct / 100), "cuota_iva": f"{cuota_iva / 100:.2f}"}], "portal", documento_id)
    _avisar_al_despacho(f, fid, datos)
    return fid


MAX_ARCHIVOS_POR_SUBIDA = 10


def _crear_borrador(tenant_id: int, usuario_id: int | None, f, tipo: str, documento_id: int, origen: str, nota: str) -> int:
    """Una factura que es solo el archivo, a la espera de que alguien (o la IA) la lea: datos de relleno que `problemas` marca hasta entonces."""
    ahora = db.now_iso()
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO facturas_contables (tenant_id, cliente_fiscal_id, tipo, origen, estado, fecha, fecha_operacion, numero, tercero_nombre, total_centimos, notas, creado_por, creado_en, "
                           "actualizado_en, documento_id, lectura) VALUES (?, ?, ?, ?, 'pendiente', ?, ?, '(por leer)', '(por leer)', 0, ?, ?, ?, ?, ?, 'pendiente')",
                           (tenant_id, f["id"], tipo, origen, ahora[:10], ahora[:10], nota, usuario_id, ahora, ahora, documento_id))
        fid = cur.lastrowid
        auditoria.registrar(tenant_id, usuario_id, "factura_contable.subida", "factura_contable", fid, {"cliente": f["nombre"], "tipo": tipo, "origen": origen}, conn=conn)
        conn.commit()
        return fid
    finally:
        conn.close()


def subir_archivos(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, tipo: str, archivos: list[tuple[str, str | None, bytes]]) -> list[int]:
    """El despacho sube varias facturas (fotos o PDF) de un cliente sin rellenar nada: quedan por leer. Devuelve los ids."""
    f = _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    return _subir(tenant_id, usuario_id, f, tipo, archivos, "despacho", "Subida por el despacho, pendiente de leer.")


def _subir(tenant_id: int, usuario_id: int | None, f, tipo: str, archivos, origen: str, nota: str) -> list[int]:
    if tipo not in TIPOS:
        raise ValueError("Indica si son facturas emitidas o recibidas.")
    archivos = [a for a in archivos if a and a[2]]
    if not archivos:
        raise ValueError("Elige al menos un archivo.")
    if len(archivos) > MAX_ARCHIVOS_POR_SUBIDA:
        raise ValueError(f"Sube como máximo {MAX_ARCHIVOS_POR_SUBIDA} archivos de una vez.")
    for _n, mime, contenido in archivos:      # se comprueban todos antes de guardar ninguno
        if (mime or "").lower().split(";")[0] not in MIME_ADJUNTO or len(contenido) > MAX_ADJUNTO_BYTES:
            raise ValueError("Archivo no válido: solo imágenes o PDF, hasta 8 MB.")
    ids = []
    for nombre, mime, contenido in archivos:
        documento_id = adjuntar(tenant_id, f["id"], usuario_id, nombre, mime, contenido)
        ids.append(_crear_borrador(tenant_id, usuario_id, f, tipo, documento_id, origen, nota))
    return ids


def subir_desde_portal(cliente_fiscal_id: int, tipo: str, archivos: list[tuple[str, str | None, bytes]]) -> list[int]:
    """El cliente sube fotos o PDF de sus facturas sin teclear nada: el despacho las leerá de golpe. Mismos límites que anotar una a mano."""
    f = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    if f is None:
        raise ValueError("Cliente no encontrado.")
    conn = db.get_connection()
    try:
        pendientes = conn.execute("SELECT COUNT(*) FROM facturas_contables WHERE cliente_fiscal_id = ? AND origen = 'portal' AND estado = 'pendiente'", (cliente_fiscal_id,)).fetchone()[0]
    finally:
        conn.close()
    if pendientes + len([a for a in archivos if a and a[2]]) > MAX_PENDIENTES_DEL_PORTAL:
        raise ValueError("Tienes muchas facturas pendientes de revisar: espera a que el despacho las procese.")
    ids = _subir(f["tenant_id"], None, f, tipo, archivos, "portal", "Subida por el cliente desde el portal, pendiente de leer.")
    _avisar_al_despacho(f, ids[-1], {"tercero_nombre": f"{len(ids)} archivo(s) por leer", "numero": ""}, len(ids))
    return ids


def _avisar_al_despacho(f, factura_id: int, datos: dict, cuantas: int = 1) -> None:
    """Avisa a quien lleva al cliente (o, si nadie, a la dirección y la coordinación) de que ha anotado una factura. Nunca rompe la subida."""
    try:
        from . import notificaciones
        conn = db.get_connection()
        try:
            destinatarios = [f["responsable_id"]] if f["responsable_id"] else [r["id"] for r in conn.execute("SELECT id FROM usuarios WHERE tenant_id = ? AND supervisor_tenant = 1", (f["tenant_id"],))]
        finally:
            conn.close()
        titulo = f"{f['nombre']} ha anotado una factura" if cuantas == 1 else f"{f['nombre']} ha subido {cuantas} facturas"
        for uid in destinatarios:
            if uid and db.notificacion_tipo_activa(uid, "portal_mensaje_nuevo"):
                notificaciones.crear_y_enviar(uid, "portal_mensaje_nuevo", titulo, f"{datos.get('tercero_nombre') or ''} · {datos.get('numero') or ''}"[:100], url=f"/contabilidad/{factura_id}",
                                              datos={"tipo": "portal_mensaje_nuevo", "factura_contable_id": factura_id})
    except Exception:
        pass


def listar_del_cliente(cliente_fiscal_id: int, limite: int = 100) -> list[dict]:
    """Lo que ve el cliente de sus facturas anotadas (sin cuentas ni notas internas)."""
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute(
            "SELECT id, tipo, fecha, numero, tercero_nombre, total_centimos, estado, origen, documento_id FROM facturas_contables WHERE cliente_fiscal_id = ? ORDER BY fecha DESC, id DESC LIMIT ?",
            (cliente_fiscal_id, limite))]
    finally:
        conn.close()
    return filas


# --- Módulo «Contabilización de facturas» ---------------------------------------------------------------------------------------------------------------
# Es un módulo propio, aparte de la Gestoría aunque se apoye en sus clientes fiscales: se activa por despacho (extra de pago vinculado o a mano desde el backoffice) y se podrá cobrar por uso.

def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    """Borra lo del módulo de un despacho (lo llama `nucleo.borrar_datos_de_tenant`). Las facturas cuelgan de las fichas fiscales y se irían con ellas, pero así no depende del orden."""
    conn.execute("UPDATE facturas_contables SET lote_id = NULL WHERE tenant_id = ?", (tenant_id,))
    for tabla in ("facturas_contables_lineas",):
        conn.execute(f"DELETE FROM {tabla} WHERE factura_id IN (SELECT id FROM facturas_contables WHERE tenant_id = ?)", (tenant_id,))
    for tabla in ("facturas_contables", "contabilidad_lotes", "contabilidad_terceros", "contabilidad_clientes"):
        conn.execute(f"DELETE FROM {tabla} WHERE tenant_id = ?", (tenant_id,))


def uso_del_mes(tenant_id: int, mes: str | None = None) -> dict:
    """Lo consumido en un mes (AAAA-MM, por defecto el actual): facturas anotadas (y cuántas por el portal del cliente), con su archivo adjunto, y facturas y ficheros exportados. Es lo que
    se contaría para un cobro por uso."""
    mes = mes or db.now_iso()[:7]
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT COUNT(*) AS anotadas, COALESCE(SUM(origen = 'portal'), 0) AS portal, COALESCE(SUM(documento_id IS NOT NULL), 0) AS con_archivo, COALESCE(SUM(lectura = 'ia'), 0) AS leidas_ia FROM facturas_contables "
                         "WHERE tenant_id = ? AND substr(creado_en, 1, 7) = ?", (tenant_id, mes)).fetchone()
        e = conn.execute("SELECT COUNT(*) AS ficheros, COALESCE(SUM(n_facturas), 0) AS facturas FROM contabilidad_lotes WHERE tenant_id = ? AND substr(creado_en, 1, 7) = ?", (tenant_id, mes)).fetchone()
    finally:
        conn.close()
    return {"mes": mes, "anotadas": f["anotadas"], "desde_portal": f["portal"], "con_archivo": f["con_archivo"], "leidas_ia": f["leidas_ia"], "ficheros": e["ficheros"], "exportadas": e["facturas"]}


def _uso_para_backoffice(tenant_id: int) -> list[tuple[str, str]]:
    u = uso_del_mes(tenant_id)
    return [("Mes", u["mes"]), ("Facturas anotadas", f"{u['anotadas']} ({u['desde_portal']} desde el portal, {u['con_archivo']} con archivo)"), ("Facturas leídas con IA", str(u["leidas_ia"])), ("Facturas exportadas a a3", f"{u['exportadas']} en {u['ficheros']} fichero(s)")]


def _registrar() -> None:
    base = verticales.VERTICALES["contabilizacion"]
    verticales.registrar(replace(base, disponible=True, esquema=crear_esquema, borrar_datos=borrar_datos_de_tenant, uso=_uso_para_backoffice,
                                 entradas_menu=(verticales.EntradaMenu("contabilizacion", _l("Facturas para contabilizar"), "contabilidad.lista", "clipboard-list"),)))


_registrar()
