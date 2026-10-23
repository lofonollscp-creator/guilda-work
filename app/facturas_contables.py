"""Facturas para contabilizar: se anotan los datos de cada factura (de un cliente de la gestoría, emitida o recibida), el despacho las revisa y de ahí sale el fichero de enlace que lee a3
(app/enlace_a3.py). No sustituye a la contabilidad: es la entrada de datos que evita teclear cada factura en a3 y que los clientes entreguen a última hora un montón de papeles.

Ciclo de vida: `pendiente` (anotada, sin revisar) → `revisada` (el despacho ha comprobado los datos y no hay nada que impida exportarla) → `exportada` (ya va en un fichero; se puede volver a bajar
ese lote). `descartada` la saca del circuito sin borrarla. Cada exportación es un lote guardado con su contenido para poder descargarlo de nuevo."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from dataclasses import replace

from flask_babel import lazy_gettext as _l

from . import acceso, antivirus, auditoria, db, enlace_a3, verticales

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
CREATE TABLE IF NOT EXISTS contabilidad_despacho (
    tenant_id INTEGER PRIMARY KEY,
    digitos INTEGER NOT NULL DEFAULT 8,
    cuenta_proveedores TEXT NOT NULL DEFAULT '40000000',
    cuenta_clientes TEXT NOT NULL DEFAULT '43000000',
    cuenta_gasto TEXT NOT NULL DEFAULT '62900000',
    cuenta_ingreso TEXT NOT NULL DEFAULT '70000000',
    cuenta_iva_soportado TEXT NOT NULL DEFAULT '47200000',
    cuenta_iva_repercutido TEXT NOT NULL DEFAULT '47700000',
    cuenta_retencion TEXT NOT NULL DEFAULT '47510000',
    subcuentas_auto INTEGER NOT NULL DEFAULT 0,
    regimen_iva TEXT NOT NULL DEFAULT 'general',
    retencion_emitidas INTEGER NOT NULL DEFAULT 0
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
CREATE TABLE IF NOT EXISTS contabilidad_recordatorios (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    trimestre TEXT NOT NULL,
    enviado_por INTEGER,
    enviado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contabilidad_recordatorios ON contabilidad_recordatorios(cliente_fiscal_id, trimestre);
CREATE TABLE IF NOT EXISTS contabilidad_plan (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    cuenta TEXT NOT NULL,
    nombre TEXT,
    nif TEXT,
    tipo TEXT NOT NULL CHECK (tipo IN ('proveedor', 'cliente')),
    importado_en TEXT NOT NULL,
    UNIQUE (cliente_fiscal_id, cuenta)
);
CREATE INDEX IF NOT EXISTS idx_contabilidad_plan_nif ON contabilidad_plan(cliente_fiscal_id, tipo, nif);
CREATE TABLE IF NOT EXISTS contabilidad_reglas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK (tipo IN ('proveedor', 'cliente')),
    nif TEXT NOT NULL,
    nombre TEXT,
    cuenta_linea TEXT,
    pct_iva INTEGER,
    pct_retencion INTEGER,
    subtipo TEXT,
    criterio_caja INTEGER NOT NULL DEFAULT 0,
    concepto TEXT,
    aprendida INTEGER NOT NULL DEFAULT 0,
    actualizado_en TEXT NOT NULL,
    UNIQUE (cliente_fiscal_id, tipo, nif)
);
CREATE TABLE IF NOT EXISTS contabilidad_cierres (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    trimestre TEXT NOT NULL,
    cerrado_por INTEGER,
    cerrado_en TEXT NOT NULL,
    UNIQUE (cliente_fiscal_id, trimestre)
);
CREATE TABLE IF NOT EXISTS contabilidad_tarifas (
    id INTEGER PRIMARY KEY,
    ambito TEXT NOT NULL CHECK (ambito IN ('defecto', 'plan', 'tenant')),
    referencia_id INTEGER NOT NULL DEFAULT 0,
    unidad TEXT NOT NULL CHECK (unidad IN ('anotadas', 'exportadas')),
    incluidas INTEGER NOT NULL DEFAULT 0,
    precio_extra_centimos INTEGER NOT NULL DEFAULT 0,
    limite_duro INTEGER,
    actualizado_en TEXT NOT NULL,
    UNIQUE (ambito, referencia_id)
);
CREATE TABLE IF NOT EXISTS contabilidad_liquidaciones (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    mes TEXT NOT NULL,
    unidad TEXT NOT NULL,
    unidades INTEGER NOT NULL,
    incluidas INTEGER,
    extra INTEGER NOT NULL DEFAULT 0,
    precio_extra_centimos INTEGER NOT NULL DEFAULT 0,
    importe_centimos INTEGER NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'cerrada', 'facturada')),
    calculada_en TEXT NOT NULL,
    cerrada_en TEXT,
    UNIQUE (tenant_id, mes)
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
# Tipo de operación de cada línea (campo «subtipo» del enlace de a3, posiciones 100-101). La importación (06) necesita el número de DUA y no se ofrece.
OPERACIONES = {
    "emitida": (("01", _l("Operación interior sujeta a IVA")), ("02", _l("Exenta sin derecho a deducción")), ("03", _l("Entrega intracomunitaria")),
                ("04", _l("Entrega intracomunitaria triangular")), ("05", _l("Operación con Canarias, Ceuta o Melilla")), ("06", _l("Exportación")),
                ("08", _l("No sujeta o inversión del sujeto pasivo")), ("09", _l("Otra exenta con derecho a deducción"))),
    "recibida": (("01", _l("Operación interior con IVA deducible")), ("02", _l("Compensación agraria")), ("03", _l("Adquisición intracomunitaria de bienes")),
                 ("04", _l("Inversión del sujeto pasivo")), ("07", _l("IVA no deducible")), ("08", _l("Adquisición intracomunitaria de servicios"))),
}
IMPRESO_349 = {"emitida": {"03": "02", "04": "02"}, "recibida": {"03": "02", "08": "11"}}     # impreso 02 = 349 bienes · 11 = 349 servicios


def operaciones_validas(tipo: str) -> set[str]:
    return {c for c, _t in OPERACIONES.get(tipo, ())}


def subtipo_por_defecto(tipo: str, cfg: dict | None) -> str:
    """El tipo de operación de una línea sin elegir: el de siempre, salvo en una actividad exenta (emitidas exentas sin derecho a deducción; recibidas con IVA no deducible)."""
    if cfg and cfg.get("regimen_iva") == "exento":
        return "02" if tipo == "emitida" else "07"
    return "01"


ESTADOS = ("pendiente", "revisada", "exportada", "descartada")
TIPOS = ("emitida", "recibida")
MAX_LINEAS = 8
MAX_NUMERO = 60          # el enlace de a3 admite hasta 60 caracteres (campo ampliado del SII); en las 10 posiciones clásicas va un resumen
TOLERANCIA_CENTIMOS = 2
CONFIG_DEFECTO = {"digitos": 8, "cuenta_proveedores": "40000000", "cuenta_clientes": "43000000", "cuenta_gasto": "62900000", "cuenta_ingreso": "70000000",
                  "cuenta_iva_soportado": "47200000", "cuenta_iva_repercutido": "47700000", "cuenta_retencion": "47510000", "subcuentas_auto": 0, "regimen_iva": "general", "retencion_emitidas": 0}


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    # ampliación posterior: los abonos llevan la factura que rectifican (registro tipo 4 del enlace de a3)
    db._asegurar_columna(conn, "facturas_contables", "rectifica_fecha", "TEXT")
    db._asegurar_columna(conn, "facturas_contables", "rectifica_numero", "TEXT")
    db._asegurar_columna(conn, "facturas_contables", "documento_id", "INTEGER")       # la factura escaneada o fotografiada, en los documentos del cliente
    db._asegurar_columna(conn, "contabilidad_clientes", "subcuentas_auto", "INTEGER NOT NULL DEFAULT 0")   # numerar solas las subcuentas de los terceros nuevos
    for tabla in ("contabilidad_clientes", "contabilidad_despacho"):
        db._asegurar_columna(conn, tabla, "regimen_iva", "TEXT NOT NULL DEFAULT 'general'")                   # general · recargo · exento
        db._asegurar_columna(conn, tabla, "retencion_emitidas", "INTEGER NOT NULL DEFAULT 0")                 # centésimas de punto que se aplican por defecto a sus facturas emitidas
    db._asegurar_columna(conn, "facturas_contables", "criterio_caja", "INTEGER NOT NULL DEFAULT 0")          # recibida de un proveedor en criterio de caja (posición 177 del enlace)
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
    return {**configuracion_despacho(tenant_id), "a3_empresa": None, **({k: f[k] for k in f.keys() if k not in ("cliente_fiscal_id", "tenant_id")} if f else {})}


def _cuenta_valida(valor, campo: str, digitos: int) -> str:
    d = re.sub(r"\D", "", str(valor or ""))
    if len(d) < 3 or len(d) > 12:
        raise ValueError(f"{campo}: escribe una cuenta de entre 3 y 12 dígitos.")
    return d


CAMPOS_CUENTAS = ("cuenta_proveedores", "cuenta_clientes", "cuenta_gasto", "cuenta_ingreso", "cuenta_iva_soportado", "cuenta_iva_repercutido", "cuenta_retencion")
_ETIQUETAS_CUENTAS = {"cuenta_proveedores": "Subcuenta genérica de proveedores", "cuenta_clientes": "Subcuenta genérica de clientes", "cuenta_gasto": "Cuenta de gasto por defecto",
                      "cuenta_ingreso": "Cuenta de ingreso por defecto", "cuenta_iva_soportado": "Cuenta de IVA soportado", "cuenta_iva_repercutido": "Cuenta de IVA repercutido",
                      "cuenta_retencion": "Cuenta de retenciones"}


def _empresa_valida(valor) -> str | None:
    empresa = re.sub(r"\D", "", str(valor or ""))
    if len(empresa) > 5:
        raise ValueError("El código de empresa de a3 tiene como máximo 5 dígitos.")
    return empresa or None


REGIMENES = ("general", "recargo", "exento")
TEXTO_REGIMEN = {"general": _l("Régimen general"), "recargo": _l("Recargo de equivalencia (comercio minorista)"), "exento": _l("Actividad exenta de IVA (sin derecho a deducción)")}
RECARGO_ESTANDAR = {2100: 520, 1000: 140, 400: 50}        # recargo de equivalencia que acompaña a cada tipo de IVA
COLUMNAS_AJUSTES = ("digitos", *CAMPOS_CUENTAS, "subcuentas_auto", "regimen_iva", "retencion_emitidas")


def _ajustes_validados(datos: dict) -> dict:
    """Los ajustes de enlace (dígitos, cuentas, subcuentas automáticas, régimen de IVA y retención) ya comprobados; `ValueError` con un mensaje legible si algo no vale.
    `retencion_emitidas` llega como texto en tanto por ciento («15») desde un formulario, o como entero en centésimas de punto (1500) si se copia de otra configuración."""
    try:
        digitos = int(datos.get("digitos") or 8)
    except ValueError:
        raise ValueError("Los dígitos de las subcuentas deben ser un número.") from None
    if not 4 <= digitos <= 12:
        raise ValueError("Los dígitos de las subcuentas deben estar entre 4 y 12.")
    regimen = datos.get("regimen_iva") or "general"
    if regimen not in REGIMENES:
        raise ValueError("Elige un régimen de IVA de la lista.")
    ret = datos.get("retencion_emitidas")
    retencion = ret if isinstance(ret, int) and not isinstance(ret, bool) else porcentaje_a_centesimas(ret)
    if not 0 <= retencion <= 6000:
        raise ValueError("La retención por defecto debe estar entre 0 y 60 %.")
    res = {"digitos": digitos, "subcuentas_auto": 1 if datos.get("subcuentas_auto") in (1, "1", "on", True) else 0, "regimen_iva": regimen, "retencion_emitidas": retencion}
    for k in CAMPOS_CUENTAS:
        res[k] = _cuenta_valida(datos.get(k) or CONFIG_DEFECTO[k], _ETIQUETAS_CUENTAS[k], digitos)
    return res


def _guardar_fila_cliente(conn, tenant_id: int, cliente_fiscal_id: int, empresa: str | None, a: dict) -> None:
    columnas = COLUMNAS_AJUSTES
    conn.execute(f"INSERT INTO contabilidad_clientes (cliente_fiscal_id, tenant_id, a3_empresa, {', '.join(columnas)}) VALUES (?, ?, ?, {', '.join('?' * len(columnas))}) "
                 f"ON CONFLICT(cliente_fiscal_id) DO UPDATE SET a3_empresa = excluded.a3_empresa, " + ", ".join(f"{k} = excluded.{k}" for k in columnas),
                 (cliente_fiscal_id, tenant_id, empresa, *[a[k] for k in columnas]))


def guardar_configuracion(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, datos: dict) -> dict:
    _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    empresa = _empresa_valida(datos.get("a3_empresa"))
    ajustes = _ajustes_validados(datos)
    conn = db.get_connection()
    try:
        _guardar_fila_cliente(conn, tenant_id, cliente_fiscal_id, empresa, ajustes)
        auditoria.registrar(tenant_id, usuario_id, "contabilidad.configuracion", "cliente_fiscal", cliente_fiscal_id, {"a3_empresa": empresa, "digitos": ajustes["digitos"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return configuracion(tenant_id, cliente_fiscal_id)


# --- Valores por defecto del despacho y alta de muchos clientes de una vez ------------------------------------------------------------------------------

def configuracion_despacho(tenant_id: int) -> dict:
    """Los ajustes de enlace que heredan los clientes que no tienen los suyos: los del despacho si los ha fijado, y si no los de siempre."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM contabilidad_despacho WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    return {**CONFIG_DEFECTO, **({k: f[k] for k in f.keys() if k != "tenant_id"} if f else {})}


def guardar_configuracion_despacho(tenant_id: int, usuario_id: int, datos: dict) -> dict:
    a = _ajustes_validados(datos)
    columnas = COLUMNAS_AJUSTES
    conn = db.get_connection()
    try:
        conn.execute(f"INSERT INTO contabilidad_despacho (tenant_id, {', '.join(columnas)}) VALUES (?, {', '.join('?' * len(columnas))}) ON CONFLICT(tenant_id) DO UPDATE SET "
                     + ", ".join(f"{k} = excluded.{k}" for k in columnas), (tenant_id, *[a[k] for k in columnas]))
        auditoria.registrar(tenant_id, usuario_id, "contabilidad.configuracion_despacho", "tenant", tenant_id,
                            {"digitos": a["digitos"], "subcuentas_auto": a["subcuentas_auto"], "regimen_iva": a["regimen_iva"], "retencion_emitidas": a["retencion_emitidas"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return configuracion_despacho(tenant_id)


def copiar_configuracion(tenant_id: int, usuario_id: int, desde_cliente_id: int, a_cliente_id: int) -> dict:
    """Los ajustes de enlace de otro cliente (todo menos su código de empresa de a3, que es de cada uno)."""
    _cliente(tenant_id, usuario_id, desde_cliente_id)
    _cliente(tenant_id, usuario_id, a_cliente_id)
    origen = configuracion(tenant_id, desde_cliente_id)
    destino = configuracion(tenant_id, a_cliente_id)
    return guardar_configuracion(tenant_id, usuario_id, a_cliente_id, {**origen, "a3_empresa": destino["a3_empresa"]})


def restablecer_configuracion(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> dict:
    """Vuelve a los valores del despacho (conserva el código de empresa de a3 del cliente)."""
    _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    return guardar_configuracion(tenant_id, usuario_id, cliente_fiscal_id, {**configuracion_despacho(tenant_id), "a3_empresa": configuracion(tenant_id, cliente_fiscal_id)["a3_empresa"]})


def resumen_clientes(tenant_id: int, usuario_id: int) -> list[dict]:
    """Cada cliente que ve la persona con su situación frente a a3: código de empresa, si usa los valores del despacho o los suyos, y cuántas facturas esperan salir."""
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    base = configuracion_despacho(tenant_id)
    conn = db.get_connection()
    try:
        filas = {r["cliente_fiscal_id"]: r for r in conn.execute("SELECT * FROM contabilidad_clientes WHERE tenant_id = ?", (tenant_id,))}
        esperando = {r["cliente_fiscal_id"]: r["n"] for r in conn.execute(
            "SELECT cliente_fiscal_id, COUNT(*) AS n FROM facturas_contables WHERE tenant_id = ? AND estado IN ('pendiente', 'revisada') GROUP BY cliente_fiscal_id", (tenant_id,))}
    finally:
        conn.close()
    res = []
    for c in db.listar_clientes_fiscales(tenant_id):
        if visibles is not None and c["id"] not in visibles:
            continue
        f = filas.get(c["id"])
        propia = bool(f) and any(f[k] != base[k] for k in COLUMNAS_AJUSTES)
        res.append({"id": c["id"], "nombre": c["nombre"], "nif": c["nif"], "a3_empresa": f["a3_empresa"] if f else None, "digitos": f["digitos"] if f else base["digitos"], "propia": propia,
                    "esperando": esperando.get(c["id"], 0)})
    return res


def guardar_codigos(tenant_id: int, usuario_id: int, codigos: dict[int, str]) -> int:
    """Fija de golpe el código de empresa de a3 de varios clientes ({cliente_fiscal_id: código}; vacío lo quita). Todo o nada: si un código no vale no se guarda ninguno. Devuelve cuántos cambiaron."""
    base = configuracion_despacho(tenant_id)
    nuevos = {}
    for cid, valor in codigos.items():
        _cliente(tenant_id, usuario_id, cid)
        try:
            nuevos[cid] = _empresa_valida(valor)
        except ValueError:
            raise ValueError(f"El código «{str(valor)[:12]}» no es válido: como máximo 5 dígitos.") from None
    cambiados = 0
    conn = db.get_connection()
    try:
        for cid, empresa in nuevos.items():
            actual = conn.execute("SELECT a3_empresa FROM contabilidad_clientes WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cid, tenant_id)).fetchone()
            if actual is not None and actual["a3_empresa"] == empresa:
                continue
            if actual is None:
                if empresa is None:
                    continue
                _guardar_fila_cliente(conn, tenant_id, cid, empresa, base)
            else:
                conn.execute("UPDATE contabilidad_clientes SET a3_empresa = ? WHERE cliente_fiscal_id = ? AND tenant_id = ?", (empresa, cid, tenant_id))
            cambiados += 1
        if cambiados:
            auditoria.registrar(tenant_id, usuario_id, "contabilidad.codigos_a3", "tenant", tenant_id, {"clientes": cambiados}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return cambiados


def _clave_nif(nif: str) -> str:
    """El NIF sin espacios, puntos ni guiones y en mayúsculas, para casar «b-12345678» con «B12345678» (con la clave normalizada de la ficha cuando el NIF es válido)."""
    from . import fiscal_identidad
    return fiscal_identidad.clave_unica(nif, "ES") or re.sub(r"[^A-Z0-9]", "", str(nif or "").upper())


def codigos_desde_texto(tenant_id: int, usuario_id: int, texto: str) -> dict:
    """Pega «NIF;código» (una pareja por línea, separada por ; , tabulador o espacios) y fija el código de a3 de cada cliente por su NIF. Devuelve {aplicados, no_encontrados, invalidos}."""
    por_nif = {}
    for r in resumen_clientes(tenant_id, usuario_id):
        if r["nif"]:
            por_nif[_clave_nif(r["nif"])] = r["id"]
    codigos, no_encontrados, invalidos = {}, [], []
    for linea in str(texto or "").splitlines()[:2000]:
        partes = [p for p in re.split(r"[;,\t ]+", linea.strip()) if p]
        if not partes:
            continue
        if len(partes) < 2:
            invalidos.append(linea.strip()[:40])
            continue
        nif, codigo = partes[0], partes[1]
        cid = por_nif.get(_clave_nif(nif))
        if cid is None:
            no_encontrados.append(nif[:20])
        elif not re.fullmatch(r"\d{1,5}", codigo):
            invalidos.append(f"{nif[:20]} → {codigo[:12]}")
        else:
            codigos[cid] = codigo
    aplicados = guardar_codigos(tenant_id, usuario_id, codigos) if codigos else 0
    return {"aplicados": aplicados, "no_encontrados": no_encontrados, "invalidos": invalidos}


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


def cuenta_del_plan(tenant_id: int, cliente_fiscal_id: int, tipo_factura: str, nif: str | None) -> str | None:
    """La subcuenta que ese proveedor o cliente ya tiene en el plan de a3 importado del cliente (por NIF), o None."""
    if not nif:
        return None
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT cuenta FROM contabilidad_plan WHERE cliente_fiscal_id = ? AND tenant_id = ? AND tipo = ? AND nif = ? ORDER BY cuenta LIMIT 1",
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
        for r in conn.execute("SELECT tipo, cuenta FROM contabilidad_plan WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_id, tenant_id)):      # las que ya existen en a3 no se repiten
            usadas[r["tipo"]].add(r["cuenta"])
        for r in conn.execute("SELECT tipo, tercero_cuenta FROM facturas_contables WHERE cliente_fiscal_id = ? AND tenant_id = ? AND tercero_cuenta IS NOT NULL", (cliente_id, tenant_id)):
            usadas["proveedor" if r["tipo"] == "recibida" else "cliente"].add(r["tercero_cuenta"])
    finally:
        conn.close()
    res: dict[tuple[str, str], tuple[str, str]] = {}
    for f in sorted(facturas, key=lambda f: (f["fecha"], f["id"])):
        nif = _nif(f.get("tercero_nif"))
        tipo = "proveedor" if f["tipo"] == "recibida" else "cliente"
        if not nif or f.get("tercero_cuenta") or (tipo, nif) in res or cuenta_del_tercero(tenant_id, cliente_id, f["tipo"], nif) or cuenta_del_plan(tenant_id, cliente_id, f["tipo"], nif):
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


# --- Cierre de periodos ----------------------------------------------------------------------------------------------------------------------------------
# Un trimestre de un cliente está cerrado cuando se ha cerrado a mano aquí, o cuando su modelo 303 (o el 390 de ese año) figura como presentado en el calendario fiscal. Exportar facturas de un periodo
# cerrado exige confirmarlo: lo normal es que ya estén contabilizadas o que haya que presentar una complementaria.

def _anio_de(trimestre: str) -> int:
    return int(trimestre[:4])


def periodos_cerrados(tenant_id: int, cliente_fiscal_id: int, trimestres) -> dict[str, dict]:
    """{trimestre: {motivo, detalle}} de los trimestres pedidos que están cerrados. `motivo`: manual · 303 · 390."""
    trimestres = sorted({t for t in trimestres if t})
    if not trimestres:
        return {}
    conn = db.get_connection()
    try:
        manual = {r["trimestre"]: r for r in conn.execute("SELECT trimestre, cerrado_en FROM contabilidad_cierres WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id))}
        presentados = {(r["modelo"], r["periodo"]) for r in conn.execute(
            "SELECT modelo, periodo FROM vencimientos_fiscales WHERE cliente_fiscal_id = ? AND tenant_id = ? AND estado = 'presentado' AND papelera_en IS NULL AND modelo IN ('303', '390')",
            (cliente_fiscal_id, tenant_id))}
    finally:
        conn.close()
    res = {}
    for t in trimestres:
        if t in manual:
            res[t] = {"motivo": "manual", "detalle": f"cerrado a mano el {manual[t]['cerrado_en'][:10]}"}
        elif ("303", t) in presentados:
            res[t] = {"motivo": "303", "detalle": "modelo 303 presentado"}
        elif ("390", f"{_anio_de(t)}-anual") in presentados:
            res[t] = {"motivo": "390", "detalle": f"modelo 390 de {_anio_de(t)} presentado"}
    return res


def cerrar_periodo(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, trimestre: str) -> None:
    _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    rango_del_trimestre(trimestre)
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO contabilidad_cierres (tenant_id, cliente_fiscal_id, trimestre, cerrado_por, cerrado_en) VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING", (tenant_id, cliente_fiscal_id, trimestre, usuario_id, db.now_iso()))
        auditoria.registrar(tenant_id, usuario_id, "contabilidad.periodo_cerrado", "cliente_fiscal", cliente_fiscal_id, {"trimestre": trimestre}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def reabrir_periodo(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, trimestre: str) -> None:
    """Quita el cierre hecho a mano. Un trimestre cerrado por un modelo presentado se reabre desde el calendario fiscal, no desde aquí."""
    _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    rango_del_trimestre(trimestre)
    cierre = periodos_cerrados(tenant_id, cliente_fiscal_id, [trimestre]).get(trimestre)
    if cierre is None:
        return
    if cierre["motivo"] != "manual":
        raise ValueError(f"Ese trimestre está cerrado por el {cierre['detalle']}: reábrelo desde el calendario fiscal si hace falta.")
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM contabilidad_cierres WHERE cliente_fiscal_id = ? AND tenant_id = ? AND trimestre = ?", (cliente_fiscal_id, tenant_id, trimestre))
        auditoria.registrar(tenant_id, usuario_id, "contabilidad.periodo_reabierto", "cliente_fiscal", cliente_fiscal_id, {"trimestre": trimestre}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def _cerrados_en(tenant_id: int, cliente_fiscal_id: int, facturas: list[dict]) -> dict[str, dict]:
    return periodos_cerrados(tenant_id, cliente_fiscal_id, {trimestre_de(f["fecha"]) for f in facturas})


def _texto_cerrados(cerrados: dict[str, dict]) -> str:
    return ", ".join(f"{t} ({c['detalle']})" for t, c in sorted(cerrados.items()))


# --- Reglas por proveedor o cliente ---------------------------------------------------------------------------------------------------------------------
# Lo que casi siempre es igual en las facturas de un mismo tercero (la cuenta de gasto, el tipo de IVA, la retención, el tipo de operación, el criterio de caja, el concepto) se guarda una vez
# como regla y rellena lo que se deja en blanco al anotar o editar una factura. Lo escrito en la factura siempre manda.

def _tipo_tercero(tipo_factura: str) -> str:
    return "proveedor" if tipo_factura == "recibida" else "cliente"


def regla_del_tercero(tenant_id: int, cliente_fiscal_id: int, tipo_factura: str, nif: str | None) -> dict | None:
    if not nif:
        return None
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM contabilidad_reglas WHERE cliente_fiscal_id = ? AND tenant_id = ? AND tipo = ? AND nif = ?",
                         (cliente_fiscal_id, tenant_id, _tipo_tercero(tipo_factura), _nif(nif))).fetchone()
    finally:
        conn.close()
    return dict(f) if f else None


def listar_reglas(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> list[dict]:
    _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM contabilidad_reglas WHERE cliente_fiscal_id = ? AND tenant_id = ? ORDER BY tipo, lower(COALESCE(nombre, nif))", (cliente_fiscal_id, tenant_id))]
    finally:
        conn.close()


def _porcentaje_o_nulo(texto, campo: str, maximo: int) -> int | None:
    if texto is None or str(texto).strip() == "":
        return None
    valor = texto if isinstance(texto, int) and not isinstance(texto, bool) else porcentaje_a_centesimas(texto)
    if not 0 <= valor <= maximo:
        raise ValueError(f"{campo}: debe estar entre 0 y {maximo // 100} %.")
    return valor


def _regla_validada(tipo: str, datos: dict) -> dict:
    if tipo not in ("proveedor", "cliente"):
        raise ValueError("Indica si la regla es de un proveedor o de un cliente.")
    tipo_factura = "recibida" if tipo == "proveedor" else "emitida"
    nif = _nif(datos.get("nif"))
    if not nif or len(nif) > 20:
        raise ValueError("Indica el NIF del proveedor o cliente al que se aplica la regla.")
    cuenta = re.sub(r"\D", "", str(datos.get("cuenta_linea") or "")) or None
    if cuenta and not 3 <= len(cuenta) <= 12:
        raise ValueError("La cuenta de gasto o ingreso debe tener entre 3 y 12 dígitos.")
    subtipo = re.sub(r"\D", "", str(datos.get("subtipo") or "")).zfill(2)[-2:] if str(datos.get("subtipo") or "").strip() else None
    if subtipo and subtipo not in operaciones_validas(tipo_factura):
        raise ValueError("Ese tipo de operación no vale para " + ("facturas recibidas." if tipo == "proveedor" else "facturas emitidas."))
    return {"tipo": tipo, "nif": nif, "nombre": str(datos.get("nombre") or "").strip()[:100] or None, "cuenta_linea": cuenta,
            "pct_iva": _porcentaje_o_nulo(datos.get("pct_iva"), "Tipo de IVA", 10000), "pct_retencion": _porcentaje_o_nulo(datos.get("pct_retencion"), "Retención", 6000),
            "subtipo": subtipo, "criterio_caja": 1 if tipo == "proveedor" and datos.get("criterio_caja") in (1, "1", "on", True) else 0,
            "concepto": str(datos.get("concepto") or "").strip()[:60] or None}


def guardar_regla(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, tipo: str, datos: dict, *, aprendida: bool = False) -> int:
    """Crea o cambia la regla de un proveedor o cliente (identificado por su NIF). Devuelve su id."""
    _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    r = _regla_validada(tipo, datos)
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO contabilidad_reglas (tenant_id, cliente_fiscal_id, tipo, nif, nombre, cuenta_linea, pct_iva, pct_retencion, subtipo, criterio_caja, concepto, aprendida, actualizado_en) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(cliente_fiscal_id, tipo, nif) DO UPDATE SET nombre = excluded.nombre, cuenta_linea = excluded.cuenta_linea, "
                     "pct_iva = excluded.pct_iva, pct_retencion = excluded.pct_retencion, subtipo = excluded.subtipo, criterio_caja = excluded.criterio_caja, concepto = excluded.concepto, "
                     "aprendida = excluded.aprendida, actualizado_en = excluded.actualizado_en",
                     (tenant_id, cliente_fiscal_id, r["tipo"], r["nif"], r["nombre"], r["cuenta_linea"], r["pct_iva"], r["pct_retencion"], r["subtipo"], r["criterio_caja"], r["concepto"],
                      1 if aprendida else 0, db.now_iso()))
        regla_id = conn.execute("SELECT id FROM contabilidad_reglas WHERE cliente_fiscal_id = ? AND tipo = ? AND nif = ?", (cliente_fiscal_id, r["tipo"], r["nif"])).fetchone()["id"]
        auditoria.registrar(tenant_id, usuario_id, "contabilidad.regla", "cliente_fiscal", cliente_fiscal_id, {"tipo": r["tipo"], "nif": r["nif"], "aprendida": aprendida}, conn=conn)
        conn.commit()
        return regla_id
    finally:
        conn.close()


def borrar_regla(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, regla_id: int) -> bool:
    _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        n = conn.execute("DELETE FROM contabilidad_reglas WHERE id = ? AND cliente_fiscal_id = ? AND tenant_id = ?", (regla_id, cliente_fiscal_id, tenant_id)).rowcount
        if n:
            auditoria.registrar(tenant_id, usuario_id, "contabilidad.regla_borrada", "cliente_fiscal", cliente_fiscal_id, {"regla": regla_id}, conn=conn)
        conn.commit()
        return bool(n)
    finally:
        conn.close()


def sugerencias_de_reglas(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, minimo: int = 2) -> list[dict]:
    """Los proveedores y clientes con al menos `minimo` facturas y sin regla, con lo que tienen en común todas sus facturas (cuenta, IVA, retención, tipo de operación). Solo cuenta lo que
    coincide en todas: un tercero cuyas facturas llevan IVA distinto no propone IVA."""
    _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT x.id, x.tipo, x.tercero_nif, x.tercero_nombre, x.concepto, x.criterio_caja, l.cuenta, l.subtipo, l.pct_iva, l.pct_retencion FROM facturas_contables x "
                             "JOIN facturas_contables_lineas l ON l.factura_id = x.id WHERE x.cliente_fiscal_id = ? AND x.tenant_id = ? AND x.estado != 'descartada' AND x.tercero_nif IS NOT NULL "
                             "ORDER BY x.id", (cliente_fiscal_id, tenant_id)).fetchall()
        con_regla = {(r["tipo"], r["nif"]) for r in conn.execute("SELECT tipo, nif FROM contabilidad_reglas WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id))}
    finally:
        conn.close()
    grupos: dict[tuple, list] = {}
    for f in filas:
        grupos.setdefault((_tipo_tercero(f["tipo"]), _nif(f["tercero_nif"])), []).append(f)
    res = []
    for (tipo, nif), lineas in grupos.items():
        facturas = {f["id"] for f in lineas}
        if len(facturas) < minimo or (tipo, nif) in con_regla:
            continue
        comun = lambda campo: lineas[0][campo] if len({f[campo] for f in lineas}) == 1 else None
        conceptos = {f["concepto"] for f in lineas}
        res.append({"tipo": tipo, "nif": nif, "nombre": lineas[-1]["tercero_nombre"], "facturas": len(facturas), "cuenta_linea": comun("cuenta"), "pct_iva": comun("pct_iva"),
                    "pct_retencion": comun("pct_retencion") or None, "subtipo": comun("subtipo"), "criterio_caja": 1 if tipo == "proveedor" and all(f["criterio_caja"] for f in lineas) else 0,
                    "concepto": next(iter(conceptos)) if len(conceptos) == 1 else None})
    return sorted(res, key=lambda r: (-r["facturas"], r["nombre"].lower()))


def crear_reglas_sugeridas(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, claves: list[tuple[str, str]]) -> int:
    """Crea las reglas de las sugerencias elegidas (pares tipo, NIF). Devuelve cuántas."""
    por_clave = {(s["tipo"], s["nif"]): s for s in sugerencias_de_reglas(tenant_id, usuario_id, cliente_fiscal_id)}
    n = 0
    for tipo, nif in dict.fromkeys(claves):
        s = por_clave.get((tipo, _nif(nif)))
        if s:
            guardar_regla(tenant_id, usuario_id, cliente_fiscal_id, tipo, s, aprendida=True)
            n += 1
    return n


# --- Alta, edición y comprobación ----------------------------------------------------------------------------------------------------------------------

def _lineas_limpias(lineas: list[dict], tipo: str | None = None, cfg: dict | None = None, regla: dict | None = None) -> list[dict]:
    """Las líneas de IVA escritas, con las cuotas calculadas cuando se dejan en blanco. Se descartan las vacías. Con el tipo de factura y los ajustes del cliente, lo que se deja en blanco toma lo del
    régimen del cliente: el tipo de operación, el recargo de equivalencia en sus compras y la retención por defecto en sus ventas; y con la regla del proveedor o cliente, su cuenta, su tipo de IVA,
    su retención y su tipo de operación (la regla manda sobre el régimen). Lo escrito siempre manda (un «0» explícito quita el recargo)."""
    res = []
    for i, l in enumerate(lineas, start=1):
        if not any(str(l.get(k) or "").strip() for k in ("base", "cuota_iva", "pct_iva")):
            continue
        base = importe_a_centimos(l.get("base"))
        l = dict(l)
        if regla:                                # lo que la línea deja en blanco lo pone la regla del tercero
            if not str(l.get("cuenta") or "").strip() and regla.get("cuenta_linea"):
                l["cuenta"] = regla["cuenta_linea"]
            if not str(l.get("pct_iva") or "").strip() and regla.get("pct_iva") is not None:
                l["pct_iva"] = regla["pct_iva"] / 100
            if not str(l.get("pct_retencion") or "").strip() and regla.get("pct_retencion") is not None:
                l["pct_retencion"] = regla["pct_retencion"] / 100
            if not str(l.get("subtipo") or "").strip() and regla.get("subtipo"):
                l["subtipo"] = regla["subtipo"]
        pct_iva, pct_re, pct_ret = (porcentaje_a_centesimas(l.get(k)) for k in ("pct_iva", "pct_recargo", "pct_retencion"))
        if base <= 0:
            raise ValueError(f"Línea {i}: indica la base imponible.")
        if cfg and tipo:
            if not str(l.get("pct_recargo") or "").strip() and tipo == "recibida" and cfg.get("regimen_iva") == "recargo":
                pct_re = RECARGO_ESTANDAR.get(pct_iva, 0)
            if not str(l.get("pct_retencion") or "").strip() and tipo == "emitida" and cfg.get("retencion_emitidas"):
                pct_ret = int(cfg["retencion_emitidas"])
        cuota_iva = importe_a_centimos(l.get("cuota_iva")) if str(l.get("cuota_iva") or "").strip() else enlace_a3.cuota(base, pct_iva)
        cuota_re = importe_a_centimos(l.get("cuota_recargo")) if str(l.get("cuota_recargo") or "").strip() else enlace_a3.cuota(base, pct_re)
        cuota_ret = importe_a_centimos(l.get("cuota_retencion")) if str(l.get("cuota_retencion") or "").strip() else enlace_a3.cuota(base, pct_ret)
        cuenta = re.sub(r"\D", "", str(l.get("cuenta") or "")) or None
        res.append({"cuenta": cuenta, "subtipo": (re.sub(r"\D", "", str(l.get("subtipo") or "")).zfill(2)[-2:] if str(l.get("subtipo") or "").strip() else subtipo_por_defecto(tipo or "recibida", cfg)), "base_centimos": base, "pct_iva": pct_iva, "cuota_iva": cuota_iva,
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
            "criterio_caja": 1 if tipo == "recibida" and datos.get("criterio_caja") in (True, 1, "1", "on", "true") else 0,
            "suplidos_centimos": importe_a_centimos(datos.get("suplidos")), "notas": str(datos.get("notas") or "").strip()[:1000] or None}


def crear(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, datos: dict, lineas: list[dict], origen: str = "despacho", documento_id: int | None = None) -> int:
    f = _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    return _insertar(tenant_id, usuario_id, f, datos, lineas, origen, documento_id)


def _aplicar_regla_a_datos(d: dict, regla: dict | None) -> None:
    """Del concepto y del criterio de caja, lo que la regla del tercero aporta si la factura no lo trae (el criterio de caja, que es una casilla, solo se puede añadir, no quitar)."""
    if not regla:
        return
    if not d.get("concepto") and regla.get("concepto"):
        d["concepto"] = regla["concepto"]
    if d["tipo"] == "recibida" and regla.get("criterio_caja"):
        d["criterio_caja"] = 1


def _insertar(tenant_id: int, usuario_id: int | None, f, datos: dict, lineas: list[dict], origen: str, documento_id: int | None) -> int:
    cliente_fiscal_id = f["id"]
    d = _datos_limpios(datos)
    from . import cobro_contabilidad
    cobro_contabilidad.comprobar_cupo(tenant_id, 1, desde_portal=origen == "portal")
    regla = regla_del_tercero(tenant_id, cliente_fiscal_id, d["tipo"], d["tercero_nif"])
    _aplicar_regla_a_datos(d, regla)
    ls = _lineas_limpias(lineas, d["tipo"], configuracion(tenant_id, cliente_fiscal_id), regla)
    total = _total_de(ls, d["suplidos_centimos"])
    ahora = db.now_iso()
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO facturas_contables (tenant_id, cliente_fiscal_id, tipo, origen, estado, fecha, fecha_operacion, numero, tercero_nombre, tercero_nif, tercero_cuenta, concepto, "
                           "referencia, abono, rectifica_fecha, rectifica_numero, suplidos_centimos, total_centimos, notas, creado_por, creado_en, actualizado_en, documento_id) VALUES (?, ?, ?, ?, 'pendiente', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, cliente_fiscal_id, d["tipo"], origen, d["fecha"], d["fecha_operacion"], d["numero"], d["tercero_nombre"], d["tercero_nif"], d["tercero_cuenta"], d["concepto"],
                            d["referencia"], d["abono"], d["rectifica_fecha"], d["rectifica_numero"], d["suplidos_centimos"], total, d["notas"], usuario_id, ahora, ahora, documento_id))
        fid = cur.lastrowid
        conn.execute("UPDATE facturas_contables SET criterio_caja = ? WHERE id = ?", (d["criterio_caja"], fid))
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
    regla = regla_del_tercero(tenant_id, f["cliente_fiscal_id"], f["tipo"], d["tercero_nif"])
    _aplicar_regla_a_datos(d, regla)
    ls = _lineas_limpias(lineas, f["tipo"], configuracion(tenant_id, f["cliente_fiscal_id"]), regla)
    total = _total_de(ls, d["suplidos_centimos"])
    conn = db.get_connection()
    try:
        conn.execute("UPDATE facturas_contables SET estado = 'pendiente', fecha = ?, fecha_operacion = ?, numero = ?, tercero_nombre = ?, tercero_nif = ?, tercero_cuenta = ?, concepto = ?, referencia = ?, "
                     "abono = ?, rectifica_fecha = ?, rectifica_numero = ?, suplidos_centimos = ?, total_centimos = ?, notas = ?, actualizado_en = ?, revisado_por = NULL, revisado_en = NULL, "
                     "documento_id = COALESCE(?, documento_id), lectura = CASE WHEN lectura IN ('pendiente', 'fallida') THEN NULL ELSE lectura END, "
                     "lectura_error = CASE WHEN lectura IN ('pendiente', 'fallida') THEN NULL ELSE lectura_error END WHERE id = ? AND tenant_id = ?",
                     (d["fecha"], d["fecha_operacion"], d["numero"], d["tercero_nombre"], d["tercero_nif"], d["tercero_cuenta"], d["concepto"], d["referencia"], d["abono"], d["rectifica_fecha"], d["rectifica_numero"],
                      d["suplidos_centimos"], total, d["notas"], db.now_iso(), documento_id, factura_id, tenant_id))
        conn.execute("UPDATE facturas_contables SET criterio_caja = ? WHERE id = ? AND tenant_id = ?", (d["criterio_caja"], factura_id, tenant_id))
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
    return f.get("tercero_cuenta") or cuenta_del_tercero(tenant_id, f["cliente_fiscal_id"], f["tipo"], f.get("tercero_nif")) or cuenta_del_plan(tenant_id, f["cliente_fiscal_id"], f["tipo"], f.get("tercero_nif")) or (
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
        ("Su Fra. " if f["tipo"] == "recibida" else "Nuestra Fra. ") + f["numero"]), "nif": f["tercero_nif"], "nombre": f["tercero_nombre"], "caja": bool(f.get("criterio_caja")) and f["tipo"] == "recibida",
        "cuenta_tercero": (nuevas or {}).get(("proveedor" if f["tipo"] == "recibida" else "cliente", _nif(f["tercero_nif"])), (None,))[0] or cuenta_efectiva(tenant_id, f, cfg), "total_centimos": f["total_centimos"],
        "lineas": [{"cuenta": l["cuenta"] or gasto_o_ingreso, "descripcion_cuenta": "Compras" if f["tipo"] == "recibida" else "Ventas", "subtipo": l["subtipo"], "base_centimos": l["base_centimos"], "pct_iva": l["pct_iva"], "cuota_iva": l["cuota_iva"],
                    "pct_recargo": l["pct_recargo"], "cuota_recargo": l["cuota_recargo"], "pct_retencion": l["pct_retencion"], "cuota_retencion": l["cuota_retencion"],
                    "sujeta_iva": bool(l["sujeta_iva"]), "impreso": IMPRESO_349.get(f["tipo"], {}).get(l["subtipo"]), "cuenta_iva": cuenta_iva, "cuenta_retencion": cfg["cuenta_retencion"] if l["cuota_retencion"] else None}
                   for l in f["lineas"]]}


def _preparar_exportacion(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, desde: str | None, hasta: str | None):
    """Las facturas revisadas del cliente y el fichero que saldría con ellas (sin guardar nada): (cliente, cfg, facturas, subcuentas nuevas, contenido)."""
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
    return cliente, cfg, facturas, nuevas, contenido


def comprobar_exportacion(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, *, desde: str | None = None, hasta: str | None = None) -> dict:
    """Pre-chequeo de lo que se exportaría ahora: genera el fichero en memoria, lo relee por sus posiciones y devuelve el informe (ver app/enlace_a3_chequeo.py). No marca ni guarda nada."""
    from . import enlace_a3_chequeo
    cliente, cfg, facturas, nuevas, contenido = _preparar_exportacion(tenant_id, usuario_id, cliente_fiscal_id, desde, hasta)
    informe = enlace_a3_chequeo.chequear(contenido, cfg["digitos"])
    informe["cliente"] = cliente["nombre"]
    informe["subcuentas_nuevas"] = [{"tipo": t, "nif": nif, "cuenta": c, "nombre": nom} for (t, nif), (c, nom) in nuevas.items()]
    informe["numeros"] = [f["numero"] for f in facturas]
    cerrados = _cerrados_en(tenant_id, cliente_fiscal_id, facturas)
    informe["periodos_cerrados"] = [{"trimestre": t, **c} for t, c in sorted(cerrados.items())]
    if cerrados:
        informe["avisos"] = [{"registro": None, "mensaje": "Hay facturas de periodos ya cerrados: " + _texto_cerrados(cerrados) + ". Para exportarlas tendrás que confirmarlo."}, *informe["avisos"]]
    return informe


def exportar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, *, desde: str | None = None, hasta: str | None = None, confirmar_cerrado: bool = False) -> dict:
    """Genera el SUENLACE.DAT con las facturas **revisadas** del cliente (en el rango de fechas, si se da), las marca como exportadas y guarda el lote. Antes lo pasa por el pre-chequeo y no lo
    entrega si encuentra errores. `ValueError` si no hay nada que exportar."""
    from . import enlace_a3_chequeo
    cliente, cfg, facturas, nuevas, contenido = _preparar_exportacion(tenant_id, usuario_id, cliente_fiscal_id, desde, hasta)
    cerrados = _cerrados_en(tenant_id, cliente_fiscal_id, facturas)
    if cerrados and not confirmar_cerrado:
        raise ValueError("Hay facturas de periodos ya cerrados: " + _texto_cerrados(cerrados) + ". Si de verdad hay que exportarlas, confírmalo (o reabre el periodo).")
    chequeo = enlace_a3_chequeo.chequear(contenido, cfg["digitos"])
    if chequeo["errores"]:
        e = chequeo["errores"][0]
        raise ValueError(f"El fichero no pasa el pre-chequeo ({len(chequeo['errores'])} errores). El primero{' (registro %d)' % e['registro'] if e['registro'] else ''}: {e['mensaje']}")
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
                            {"lote": lote, "facturas": len(facturas), "desde": desde, "hasta": hasta, "subcuentas_nuevas": len(nuevas),
                             "periodos_cerrados": sorted(cerrados) if cerrados else None}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return {"lote": lote, "n_facturas": len(facturas), "n_registros": n_registros, "contenido": contenido, "cliente": cliente["nombre"], "avisos": chequeo["avisos"]}


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


def comprobar_lote(tenant_id: int, usuario_id: int, lote_id: int) -> dict | None:
    """Pre-chequeo de un fichero ya generado (con los dígitos que tiene configurados el cliente), o None si no existe o no se puede ver."""
    from . import enlace_a3_chequeo
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT l.cliente_fiscal_id, l.contenido, l.creado_en, c.nombre FROM contabilidad_lotes l JOIN clientes_fiscales c ON c.id = l.cliente_fiscal_id WHERE l.id = ? AND l.tenant_id = ?",
                         (lote_id, tenant_id)).fetchone()
    finally:
        conn.close()
    if f is None or not acceso.puede_ver_cliente(tenant_id, usuario_id, f["cliente_fiscal_id"]):
        return None
    informe = enlace_a3_chequeo.chequear(bytes(f["contenido"]), configuracion(tenant_id, f["cliente_fiscal_id"])["digitos"])
    informe["cliente"] = f["nombre"]
    informe["creado_en"] = f["creado_en"]
    return informe


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
    if archivo:
        antivirus.exigir_limpio(archivo[0], archivo[2], tenant_id, cliente_fiscal_id)        # ArchivoRechazado es un ValueError con un mensaje apto para el cliente
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
    from . import cobro_contabilidad
    cobro_contabilidad.comprobar_cupo(tenant_id, len(archivos), desde_portal=origen == "portal")
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
    for a in archivos:
        if a and a[2]:
            antivirus.exigir_limpio(a[0], a[2], f["tenant_id"], cliente_fiscal_id)           # antes de guardar nada: si uno falla, no se guarda ninguno
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


def pendientes_por_cliente(tenant_id: int, usuario_id: int) -> list[dict]:
    """Por cada cliente que ve la persona, lo que espera en Facturas para contabilizar: pendientes de revisar (cuántas por leer y cuántas las subió el cliente), revisadas listas para exportar y la fecha
    de la pendiente más antigua. Solo los clientes con algo pendiente o listo; lo que alimenta la bandeja «Hoy»."""
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT x.cliente_fiscal_id, c.nombre, SUM(x.estado = 'pendiente') AS pendientes, SUM(x.estado = 'revisada') AS revisadas, "
                             "SUM(x.estado = 'pendiente' AND x.lectura IN ('pendiente', 'fallida')) AS por_leer, SUM(x.estado = 'pendiente' AND x.origen = 'portal') AS del_portal, "
                             "MIN(CASE WHEN x.estado = 'pendiente' THEN x.creado_en END) AS antigua FROM facturas_contables x JOIN clientes_fiscales c ON c.id = x.cliente_fiscal_id "
                             "WHERE x.tenant_id = ? AND x.estado IN ('pendiente', 'revisada') AND c.papelera_en IS NULL GROUP BY x.cliente_fiscal_id, c.nombre", (tenant_id,)).fetchall()
    finally:
        conn.close()
    return [dict(f) for f in filas if visibles is None or f["cliente_fiscal_id"] in visibles]


# --- Recordatorio a los clientes antes del cierre del trimestre ------------------------------------------------------------------------------------------

DIAS_ENTRE_RECORDATORIOS = 3          # no se vuelve a escribir al mismo cliente por el mismo trimestre antes de esto


def para_recordar(tenant_id: int, usuario_id: int, trimestre: str) -> list[dict]:
    """Los clientes del despacho que ve la persona, con cuánto han anotado ese trimestre y cuándo se les recordó por última vez. `puede` = tiene email y no se le ha escrito hace poco."""
    desde, hasta = rango_del_trimestre(trimestre)
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        notas = {r["cliente_fiscal_id"]: r for r in conn.execute(
            "SELECT cliente_fiscal_id, COUNT(*) AS anotadas, COALESCE(SUM(estado = 'pendiente'), 0) AS por_revisar FROM facturas_contables WHERE tenant_id = ? AND fecha BETWEEN ? AND ? AND estado != 'descartada' "
            "GROUP BY cliente_fiscal_id", (tenant_id, desde, hasta))}
        ultimos = {r["cliente_fiscal_id"]: r["ultimo"] for r in conn.execute(
            "SELECT cliente_fiscal_id, MAX(enviado_en) AS ultimo FROM contabilidad_recordatorios WHERE tenant_id = ? AND trimestre = ? GROUP BY cliente_fiscal_id", (tenant_id, trimestre))}
    finally:
        conn.close()
    limite = (datetime.now() - timedelta(days=DIAS_ENTRE_RECORDATORIOS)).isoformat(timespec="seconds")
    res = []
    for c in db.listar_clientes_fiscales(tenant_id):
        if visibles is not None and c["id"] not in visibles:
            continue
        n = notas.get(c["id"])
        ultimo = ultimos.get(c["id"])
        email = (c["email"] or "").strip()
        res.append({"id": c["id"], "nombre": c["nombre"], "email": email, "anotadas": n["anotadas"] if n else 0, "por_revisar": n["por_revisar"] if n else 0, "ultimo": ultimo,
                    "reciente": bool(ultimo and ultimo > limite), "puede": bool(email) and not (ultimo and ultimo > limite)})
    return sorted(res, key=lambda c: (c["anotadas"], c["nombre"].lower()))


def recordar(tenant_id: int, usuario_id: int, cliente_ids: list[int], trimestre: str, fecha_limite: str | None, url_portal: str) -> dict:
    """Escribe a los clientes elegidos para pedirles las facturas del trimestre. Devuelve {enviados, omitidos: [(nombre, motivo)]}. `ValueError` si el correo saliente no está configurado."""
    from . import notificaciones_email as ne
    rango_del_trimestre(trimestre)
    fecha_limite = _fecha(fecha_limite, "Fecha límite") if str(fecha_limite or "").strip() else None
    if not ne.configurado():
        raise ValueError("El correo saliente de la plataforma no está configurado: no se puede avisar a los clientes.")
    candidatos = {c["id"]: c for c in para_recordar(tenant_id, usuario_id, trimestre)}
    enviados, omitidos = 0, []
    for cid in dict.fromkeys(int(i) for i in cliente_ids):
        c = candidatos.get(cid)
        if c is None:
            omitidos.append(("#%d" % cid, "no es un cliente que puedas ver"))
        elif not c["email"]:
            omitidos.append((c["nombre"], "no tiene email"))
        elif c["reciente"]:
            omitidos.append((c["nombre"], f"ya se le recordó hace menos de {DIAS_ENTRE_RECORDATORIOS} días"))
        else:
            try:
                ne.enviar_recordatorio_facturas(c["email"], c["nombre"], trimestre, fecha_limite, url_portal, tenant_id=tenant_id)
            except ne.ErrorNotificacionesEmail as e:
                omitidos.append((c["nombre"], str(e)[:120]))
                continue
            conn = db.get_connection()
            try:
                conn.execute("INSERT INTO contabilidad_recordatorios (tenant_id, cliente_fiscal_id, trimestre, enviado_por, enviado_en) VALUES (?, ?, ?, ?, ?)", (tenant_id, cid, trimestre, usuario_id, db.now_iso()))
                conn.commit()
            finally:
                conn.close()
            enviados += 1
    auditoria.registrar(tenant_id, usuario_id, "contabilidad.recordatorio", "trimestre", None, {"trimestre": trimestre, "enviados": enviados, "omitidos": len(omitidos)})
    return {"enviados": enviados, "omitidos": omitidos}


# --- Módulo «Contabilización de facturas» ---------------------------------------------------------------------------------------------------------------
# Es un módulo propio, aparte de la Gestoría aunque se apoye en sus clientes fiscales: se activa por despacho (extra de pago vinculado o a mano desde el backoffice) y se podrá cobrar por uso.

def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    """Borra lo del módulo de un despacho (lo llama `nucleo.borrar_datos_de_tenant`). Las facturas cuelgan de las fichas fiscales y se irían con ellas, pero así no depende del orden."""
    conn.execute("UPDATE facturas_contables SET lote_id = NULL WHERE tenant_id = ?", (tenant_id,))
    for tabla in ("facturas_contables_lineas",):
        conn.execute(f"DELETE FROM {tabla} WHERE factura_id IN (SELECT id FROM facturas_contables WHERE tenant_id = ?)", (tenant_id,))
    for tabla in ("facturas_contables", "contabilidad_lotes", "contabilidad_terceros", "contabilidad_clientes", "contabilidad_recordatorios", "contabilidad_despacho", "contabilidad_plan", "contabilidad_reglas", "contabilidad_cierres"):
        conn.execute(f"DELETE FROM {tabla} WHERE tenant_id = ?", (tenant_id,))
    from . import cobro_contabilidad
    cobro_contabilidad.borrar_datos_de_tenant(conn, tenant_id)


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
