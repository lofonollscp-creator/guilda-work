"""Facturas para contabilizar: se anotan los datos de cada factura (de un cliente de la gestoría, emitida o recibida), el despacho las revisa y de ahí sale el fichero de enlace que lee a3
(app/enlace_a3.py). No sustituye a la contabilidad: es la entrada de datos que evita teclear cada factura en a3 y que los clientes entreguen a última hora un montón de papeles.

Ciclo de vida: `pendiente` (anotada, sin revisar) → `revisada` (el despacho ha comprobado los datos y no hay nada que impida exportarla) → `exportada` (ya va en un fichero; se puede volver a bajar
ese lote). `descartada` la saca del circuito sin borrarla. Cada exportación es un lote guardado con su contenido para poder descargarlo de nuevo."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from dataclasses import replace

from flask_babel import lazy_gettext as _l

from . import acceso, antivirus, auditoria, db, enlace_a3, verticales

logger = logging.getLogger("guilda")

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
CREATE INDEX IF NOT EXISTS idx_facturas_contables_duplicadas ON facturas_contables(tenant_id, cliente_fiscal_id, tercero_nif, numero);
CREATE INDEX IF NOT EXISTS idx_facturas_contables_fecha ON facturas_contables(tenant_id, fecha DESC, id DESC);
CREATE TABLE IF NOT EXISTS facturas_contables_mensajes (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    factura_id INTEGER NOT NULL,
    autor TEXT NOT NULL CHECK (autor IN ('cliente', 'empleado')),
    usuario_id INTEGER,
    texto TEXT NOT NULL,
    creado_en TEXT NOT NULL,
    leido_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_facturas_contables_mensajes ON facturas_contables_mensajes(tenant_id, factura_id, id);
CREATE TABLE IF NOT EXISTS justificantes_pendientes (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    origen TEXT NOT NULL CHECK (origen IN ('extracto', 'cliente')),
    fecha TEXT NOT NULL,
    importe_centimos INTEGER NOT NULL,
    concepto TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'con_factura', 'tiquet', 'personal', 'no_se', 'resuelto', 'descartado')),
    factura_id INTEGER,
    documento_id INTEGER,
    comentario TEXT,
    huella TEXT NOT NULL,
    pedido_por INTEGER,
    creado_en TEXT NOT NULL,
    respondido_en TEXT,
    resuelto_por INTEGER,
    resuelto_en TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_justificantes_huella ON justificantes_pendientes(tenant_id, cliente_fiscal_id, huella);
CREATE INDEX IF NOT EXISTS idx_justificantes_cliente ON justificantes_pendientes(tenant_id, cliente_fiscal_id, estado);
"""
# Tipo de operación de cada línea (campo «subtipo» del enlace de a3, posiciones 100-101). La importación (06) necesita el número de DUA (datos de ampliación) y solo sale en el formato clásico de 256.
OPERACIONES = {
    "emitida": (("01", _l("Operación interior sujeta a IVA")), ("02", _l("Exenta sin derecho a deducción")), ("03", _l("Entrega intracomunitaria")),
                ("04", _l("Entrega intracomunitaria triangular")), ("05", _l("Operación con Canarias, Ceuta o Melilla")), ("06", _l("Exportación")),
                ("07", _l("Otra operación no sujeta a IVA")), ("08", _l("No sujeta o inversión del sujeto pasivo")), ("09", _l("Otra exenta con derecho a deducción"))),
    "recibida": (("01", _l("Operación interior con IVA deducible")), ("02", _l("Compensación agraria")), ("03", _l("Adquisición intracomunitaria de bienes")),
                 ("04", _l("Inversión del sujeto pasivo")), ("06", _l("Importación")), ("07", _l("IVA no deducible")), ("08", _l("Adquisición intracomunitaria de servicios"))),
}
IMPRESO_349 = {"emitida": {"03": "02", "04": "02"}, "recibida": {"03": "02", "08": "11"}}     # impreso 02 = 349 bienes · 11 = 349 servicios
IMPRESOS_VALIDOS = {f"{i:02d}" for i in range(1, 40)}          # los códigos de «impreso» (posiciones 173-174) que admite a3: 347, 349, 115 y las variantes del 110/123
IMPRESOS_COMUNES = (("01", _l("347")), ("02", _l("349 bienes")), ("11", _l("349 servicios")), ("03", _l("115 alquileres")), ("05", _l("110 profesionales")), ("07", _l("110 agrarios")))
IMPRESO_DE_LA_RETENCION = {1900: "03", 1500: "05", 700: "05", 200: "07", 100: "07"}     # retención practicada en una compra → impreso que la acumula (por su porcentaje)


def impreso_de_linea(tipo: str, linea: dict) -> str | None:
    """El impreso de a3 de una línea: el que se eligió a mano; si no, el del 349 que toca por su operación intracomunitaria y, en las compras con retención, el del modelo de esa retención (19 % → 115,
    15 y 7 % → 110 profesionales, 2 y 1 % → 110 agrarios). Las retenciones de otro tipo no se adivinan: se eligen a mano."""
    manual = str(linea.get("impreso") or "").strip()
    if manual in IMPRESOS_VALIDOS:
        return manual
    del_349 = IMPRESO_349.get(tipo, {}).get(linea.get("subtipo"))
    if del_349:
        return del_349
    if tipo == "recibida" and linea.get("cuota_retencion"):
        return IMPRESO_DE_LA_RETENCION.get(linea.get("pct_retencion"))
    return None


def iban_valido(iban: str) -> bool:
    """El dígito de control del IBAN (módulo 97 de la cadena reordenada) y su longitud mínima. No comprueba que el banco exista."""
    t = re.sub(r"\s", "", str(iban or "")).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", t):
        return False
    if t[:2] == "ES" and len(t) != 24:
        return False
    return int("".join(str(int(ch, 36)) for ch in t[4:] + t[:4])) % 97 == 1


def datos_a3_validados(datos: dict | None, tipo: str) -> dict:
    """Los datos de ampliación de a3 de una factura, ya limpios: `bien_inversion` (solo compras), `dua` (importaciones; 18), `clave_340` (1 = ticket; 3 = agencias de viajes, solo compras), `nif_representante`
    (14), `autofactura` (inversión del sujeto pasivo; 10) y `metalico` / `inmuebles` del 347 (`total` = el total de la factura, o un importe en euros). Lo vacío no se guarda. `ValueError` si algo no vale."""
    datos = datos or {}
    res: dict = {}
    if str(datos.get("bien_inversion") or "").lower() in ("1", "true", "on", "s"):
        if tipo != "recibida":
            raise ValueError("Solo una factura recibida puede ser un bien de inversión.")
        res["bien_inversion"] = True
    for campo, largo in (("dua", 18), ("nif_representante", 14), ("autofactura", 10)):
        v = str(datos.get(campo) or "").strip()
        if v:
            res[campo] = _nif(v)[:largo] if campo == "nif_representante" else v[:largo]
    clave = str(datos.get("clave_340") or "").strip()
    if clave:
        if clave not in (("1",) if tipo == "emitida" else ("1", "3")):
            raise ValueError("La clave de factura del modelo 340 debe ser 1 (ticket) o, en las compras, 3 (agencias de viajes).")
        res["clave_340"] = clave
    iban = re.sub(r"\s", "", str(datos.get("iban") or "")).upper()
    if iban:
        if not iban_valido(iban):
            raise ValueError("El IBAN no es válido: revisa los dígitos.")
        res["iban"] = iban
    venc = str(datos.get("vencimiento") or "").strip()
    if venc:
        res["vencimiento"] = _fecha(venc, "Vencimiento")
    forma = str(datos.get("forma_pago") or "").strip().upper()
    if forma:
        if forma not in enlace_a3.FORMAS_DE_PAGO:
            raise ValueError("Elige una forma de cobro o pago de la lista.")
        res["forma_pago"] = forma
    for campo in ("metalico", "inmuebles"):
        v = str(datos.get(campo) if datos.get(campo) is not None else "").strip().lower()
        if v in ("total", "true", "s"):
            res[campo] = "total"
        elif v:
            c = importe_a_centimos(v, permitir_cero=False)
            res[campo] = c
    return res


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
                  "cuenta_iva_soportado": "47200000", "cuenta_iva_repercutido": "47700000", "cuenta_retencion": "47510000", "cuenta_tesoreria": "57200000", "subcuentas_auto": 0, "regimen_iva": "general", "retencion_emitidas": 0, "formato_enlace": "512"}


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
    db._asegurar_columna(conn, "facturas_contables", "lectura_evidencia", "TEXT")      # de dónde sacó la IA cada dato (migración 008)
    db._asegurar_columna(conn, "contabilidad_lotes", "comprobado_en", "TEXT")                  # cuándo se cruzó el lote con lo que devolvió a3 (J3)
    db._asegurar_columna(conn, "contabilidad_lotes", "n_confirmadas", "INTEGER")
    db._asegurar_columna(conn, "facturas_contables", "confirmada_en", "TEXT")                  # cuándo se comprobó que a3 la tiene contabilizada (retorno de a3, J3)
    db._asegurar_columna(conn, "facturas_contables", "lectura_confianza", "INTEGER")        # 0-100, lo que merece la lectura (app/lectura_confianza.py)
    db._asegurar_columna(conn, "facturas_contables", "lectura_fuente", "TEXT")             # xml · texto (capa de texto del PDF) · imagen
    db._asegurar_columna(conn, "facturas_contables", "revision_auto", "INTEGER NOT NULL DEFAULT 0")     # 1 = la dio por revisada la IA (modo «decide sola»), sin que la mirara una persona
    db._asegurar_columna(conn, "contabilidad_clientes", "formato_enlace", "TEXT NOT NULL DEFAULT '512'")      # 512 = SII, 256 = clásico (migración 046)
    db._asegurar_columna(conn, "contabilidad_despacho", "formato_enlace", "TEXT NOT NULL DEFAULT '512'")
    db._asegurar_columna(conn, "contabilidad_clientes", "cuenta_tesoreria", "TEXT NOT NULL DEFAULT '57200000'")      # migración 047: banco o caja de los asientos de cobro y pago
    db._asegurar_columna(conn, "contabilidad_despacho", "cuenta_tesoreria", "TEXT NOT NULL DEFAULT '57200000'")
    db._asegurar_columna(conn, "contabilidad_clientes", "columnas_retorno", "TEXT")            # JSON: las columnas del listado de a3 que la persona indicó la última vez
    db._asegurar_columna(conn, "facturas_contables", "pago_exportado_en", "TEXT")              # cuándo salió su asiento de cobro o pago en un fichero para a3
    db._asegurar_columna(conn, "contabilidad_reglas", "pct_deducible", "INTEGER")              # % de IVA deducible en centésimas (5000 = 50 %); vacío = todo
    db._asegurar_columna(conn, "contabilidad_clientes", "buzon_activo", "INTEGER NOT NULL DEFAULT 0")      # migración 057: buzón de facturas por correo, solo en los clientes que el despacho active
    db._asegurar_columna(conn, "contabilidad_clientes", "buzon_codigo", "TEXT")
    db._asegurar_columna(conn, "contabilidad_clientes", "avisar_lectura", "INTEGER NOT NULL DEFAULT 0")      # migración 060: avisar al cliente cuando una factura suya del portal queda leída
    db._asegurar_columna(conn, "contabilidad_despacho", "buzon_cuenta_id", "INTEGER")
    db._asegurar_columna(conn, "contabilidad_despacho", "buzon_direccion", "TEXT")
    db._asegurar_columna(conn, "contabilidad_lotes", "clase", "TEXT")                          # vacío = facturas; «pagos» = asientos de cobro y pago (migración 047)
    db._asegurar_columna(conn, "contabilidad_clientes", "plan_cuentas", "TEXT")                # JSON: todas las cuentas del plan de a3 importado (J12)
    db._asegurar_columna(conn, "contabilidad_lotes", "estado_a3", "TEXT")                      # importado · rechazado (lo que dice la persona tras importar el fichero en a3)
    db._asegurar_columna(conn, "contabilidad_lotes", "motivo_a3", "TEXT")
    db._asegurar_columna(conn, "contabilidad_lotes", "estado_a3_en", "TEXT")
    db._asegurar_columna(conn, "facturas_contables", "datos_a3", "TEXT")                       # JSON: bien de inversión, DUA, clave del 340, 347… (ver `datos_a3_validados`)
    db._asegurar_columna(conn, "facturas_contables_lineas", "impreso", "TEXT")                 # impreso de a3 elegido a mano para la línea (110, 115, 347, 349…); vacío = el que toca
    db._asegurar_columna(conn, "facturas_contables", "incluir_en_fiscal", "INTEGER NOT NULL DEFAULT 1")      # 1 = cuenta para Guilda Fiscal (modelos de impuestos); 0 = solo contabilidad


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
    return {**configuracion_despacho(tenant_id), "a3_empresa": None, **({k: f[k] for k in f.keys() if k not in ("cliente_fiscal_id", "tenant_id", "plan_cuentas", "columnas_retorno")} if f else {})}


def _cuenta_valida(valor, campo: str, digitos: int) -> str:
    d = re.sub(r"\D", "", str(valor or ""))
    if len(d) < 3 or len(d) > 12:
        raise ValueError(f"{campo}: escribe una cuenta de entre 3 y 12 dígitos.")
    return d


CAMPOS_CUENTAS = ("cuenta_proveedores", "cuenta_clientes", "cuenta_gasto", "cuenta_ingreso", "cuenta_iva_soportado", "cuenta_iva_repercutido", "cuenta_retencion", "cuenta_tesoreria")
_ETIQUETAS_CUENTAS = {"cuenta_proveedores": "Subcuenta genérica de proveedores", "cuenta_clientes": "Subcuenta genérica de clientes", "cuenta_gasto": "Cuenta de gasto por defecto",
                      "cuenta_ingreso": "Cuenta de ingreso por defecto", "cuenta_iva_soportado": "Cuenta de IVA soportado", "cuenta_iva_repercutido": "Cuenta de IVA repercutido",
                      "cuenta_retencion": "Cuenta de retenciones", "cuenta_tesoreria": "Cuenta de banco o caja (cobros y pagos)"}


def _empresa_valida(valor) -> str | None:
    empresa = re.sub(r"\D", "", str(valor or ""))
    if len(empresa) > 5:
        raise ValueError("El código de empresa de a3 tiene como máximo 5 dígitos.")
    return empresa or None


REGIMENES = ("general", "recargo", "exento")
TEXTO_REGIMEN = {"general": _l("Régimen general"), "recargo": _l("Recargo de equivalencia (comercio minorista)"), "exento": _l("Actividad exenta de IVA (sin derecho a deducción)")}
RECARGO_ESTANDAR = {2100: 520, 1000: 140, 400: 50}        # recargo de equivalencia que acompaña a cada tipo de IVA
COLUMNAS_AJUSTES = ("digitos", *CAMPOS_CUENTAS, "subcuentas_auto", "regimen_iva", "retencion_emitidas", "formato_enlace")


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
    formato = str(datos.get("formato_enlace") or CONFIG_DEFECTO["formato_enlace"]).strip()
    if formato not in enlace_a3.FORMATOS:
        raise ValueError("Elige un formato de fichero de la lista: 512 (SII) o 256 (clásico).")
    res = {"digitos": digitos, "subcuentas_auto": 1 if datos.get("subcuentas_auto") in (1, "1", "on", True) else 0, "regimen_iva": regimen, "retencion_emitidas": retencion, "formato_enlace": formato}
    for k in CAMPOS_CUENTAS:
        res[k] = _cuenta_valida(datos.get(k) or CONFIG_DEFECTO[k], _ETIQUETAS_CUENTAS[k], digitos)
    return res


def _asegurar_fila_cliente(conn, tenant_id: int, cliente_fiscal_id: int) -> None:
    """Si el cliente aún no tiene su fila de configuración, la crea con los valores que ya le valían (los del despacho), para poder guardar en ella algo suyo sin cambiarle nada."""
    if conn.execute("SELECT 1 FROM contabilidad_clientes WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id)).fetchone():
        return
    cfg = configuracion(tenant_id, cliente_fiscal_id)
    _guardar_fila_cliente(conn, tenant_id, cliente_fiscal_id, None, {k: cfg[k] for k in COLUMNAS_AJUSTES})


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


def mapa_de_cuentas(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> dict:
    """Qué subcuenta de a3 se usará con cada proveedor y cliente del cliente de la gestoría (los de sus facturas no descartadas, por NIF): {terceros: [{tipo, nif, nombre, facturas, cuenta, origen}], sin_nif, faltan}.
    `origen`: «recordada» (guardada al exportar o fijada a mano), «plan» (la que ya tiene en el plan de a3 importado), «nueva» (se numerará sola al exportar) o «generica» (la genérica del cliente: en a3 todo
    caerá en una sola subcuenta). `faltan` cuenta los que van a la genérica."""
    _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    cfg = configuracion(tenant_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute(
            "SELECT id, cliente_fiscal_id, tipo, fecha, tercero_nif, tercero_nombre, tercero_cuenta FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado != 'descartada' ORDER BY fecha, id",
            (tenant_id, cliente_fiscal_id))]
        recordadas = {(r["tipo"], r["nif"]): r["cuenta"] for r in conn.execute("SELECT tipo, nif, cuenta FROM contabilidad_terceros WHERE tenant_id = ? AND cliente_fiscal_id = ?", (tenant_id, cliente_fiscal_id))}
        del_plan = {}
        for r in conn.execute("SELECT tipo, nif, cuenta FROM contabilidad_plan WHERE tenant_id = ? AND cliente_fiscal_id = ? AND nif IS NOT NULL ORDER BY cuenta", (tenant_id, cliente_fiscal_id)):
            del_plan.setdefault((r["tipo"], r["nif"]), r["cuenta"])
    finally:
        conn.close()
    try:
        nuevas = _subcuentas_nuevas(tenant_id, cfg, filas)
    except ValueError:
        nuevas = {}
    grupos: dict[tuple[str, str], dict] = {}
    sin_nif = 0
    for f in filas:
        nif, tipo = _nif(f["tercero_nif"]), _tipo_tercero(f["tipo"])
        if not nif:
            sin_nif += 1
            continue
        g_ = grupos.setdefault((tipo, nif), {"tipo": tipo, "nif": nif, "nombre": f["tercero_nombre"], "facturas": 0, "cuenta_en_factura": None})
        g_["facturas"] += 1
        g_["nombre"] = f["tercero_nombre"] or g_["nombre"]
        g_["cuenta_en_factura"] = f["tercero_cuenta"] or g_["cuenta_en_factura"]
    res = []
    for (tipo, nif), t in grupos.items():
        generica = cfg["cuenta_proveedores"] if tipo == "proveedor" else cfg["cuenta_clientes"]
        if (tipo, nif) in recordadas:
            cuenta, origen = recordadas[(tipo, nif)], "recordada"
        elif t["cuenta_en_factura"]:
            cuenta, origen = t["cuenta_en_factura"], "recordada"
        elif (tipo, nif) in del_plan:
            cuenta, origen = del_plan[(tipo, nif)], "plan"
        elif (tipo, nif) in nuevas:
            cuenta, origen = nuevas[(tipo, nif)][0], "nueva"
        else:
            cuenta, origen = generica, "generica"
        res.append({"tipo": tipo, "nif": nif, "nombre": t["nombre"], "facturas": t["facturas"], "cuenta": cuenta, "origen": origen})
    res.sort(key=lambda t: ({"generica": 0, "nueva": 1, "recordada": 2, "plan": 3}[t["origen"]], t["tipo"], t["nombre"].lower()))
    return {"terceros": res, "sin_nif": sin_nif, "faltan": sum(1 for t in res if t["origen"] == "generica")}


def fijar_cuenta_tercero(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, tipo_tercero: str, nif: str, cuenta: str) -> None:
    """Fija a mano la subcuenta de un proveedor o cliente (por su NIF) para las próximas exportaciones. Las ya exportadas no cambian."""
    _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    if tipo_tercero not in ("proveedor", "cliente") or not _nif(nif):
        raise ValueError("Proveedor o cliente no válido.")
    cfg = configuracion(tenant_id, cliente_fiscal_id)
    cuenta = _cuenta_valida(cuenta, "Subcuenta", cfg["digitos"])
    if len(cuenta) != cfg["digitos"]:
        raise ValueError("La subcuenta no tiene los dígitos que usa este cliente (se ven abajo, en la tabla).")
    conn = db.get_connection()
    try:
        nombre = conn.execute("SELECT tercero_nombre FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND tercero_nif = ? ORDER BY id DESC LIMIT 1", (tenant_id, cliente_fiscal_id, _nif(nif))).fetchone()
        _recordar_tercero(conn, tenant_id, cliente_fiscal_id, "recibida" if tipo_tercero == "proveedor" else "emitida", _nif(nif), (nombre["tercero_nombre"] if nombre else "") or "", cuenta)
        auditoria.registrar(tenant_id, usuario_id, "contabilidad.cuenta_tercero", "cliente_fiscal", cliente_fiscal_id, {"tipo": tipo_tercero, "nif": _nif(nif), "cuenta": cuenta}, conn=conn)
        conn.commit()
    finally:
        conn.close()


# --- Cierre de periodos ----------------------------------------------------------------------------------------------------------------------------------
# Un trimestre de un cliente está cerrado cuando se ha cerrado a mano aquí, o cuando su modelo 303 (o el 390 de ese año) figura como presentado en el calendario fiscal. Exportar facturas de un periodo
# cerrado exige confirmarlo: lo normal es que ya estén contabilizadas o que haya que presentar una complementaria.

def _anio_de(trimestre: str) -> int:
    return int(trimestre[:4])


def _cierres_de(trimestres, manual: dict, presentados: set) -> dict[str, dict]:
    res = {}
    for t in trimestres:
        if t in manual:
            res[t] = {"motivo": "manual", "detalle": f"cerrado a mano el {manual[t]['cerrado_en'][:10]}"}
        elif ("303", t) in presentados:
            res[t] = {"motivo": "303", "detalle": "modelo 303 presentado"}
        elif ("390", f"{_anio_de(t)}-anual") in presentados:
            res[t] = {"motivo": "390", "detalle": f"modelo 390 de {_anio_de(t)} presentado"}
    return res


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
    return _cierres_de(trimestres, manual, presentados)


def periodos_cerrados_de_varios(tenant_id: int, por_cliente: dict) -> dict[int, dict[str, dict]]:
    """Lo mismo para varios clientes de golpe, con dos consultas en vez de dos por cliente (la lista de facturas de todos los clientes salía con 60 consultas de más).
    `por_cliente`: {cliente_fiscal_id: trimestres}. Devuelve {cliente_fiscal_id: {trimestre: cierre}}."""
    ids = sorted(c for c, ts in por_cliente.items() if any(ts))
    if not ids:
        return {}
    marcas = ",".join("?" * len(ids))
    conn = db.get_connection()
    try:
        manual: dict[int, dict] = {}
        for r in conn.execute(f"SELECT cliente_fiscal_id, trimestre, cerrado_en FROM contabilidad_cierres WHERE tenant_id = ? AND cliente_fiscal_id IN ({marcas})", (tenant_id, *ids)):
            manual.setdefault(r["cliente_fiscal_id"], {})[r["trimestre"]] = r
        presentados: dict[int, set] = {}
        for r in conn.execute(f"SELECT cliente_fiscal_id, modelo, periodo FROM vencimientos_fiscales WHERE tenant_id = ? AND estado = 'presentado' AND papelera_en IS NULL AND modelo IN ('303', '390') "
                              f"AND cliente_fiscal_id IN ({marcas})", (tenant_id, *ids)):
            presentados.setdefault(r["cliente_fiscal_id"], set()).add((r["modelo"], r["periodo"]))
    finally:
        conn.close()
    return {c: _cierres_de(sorted({t for t in por_cliente[c] if t}), manual.get(c, {}), presentados.get(c, set())) for c in ids}


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
            "subtipo": subtipo, "pct_deducible": _porcentaje_o_nulo(datos.get("pct_deducible"), "IVA deducible", 10000) if tipo == "proveedor" else None,
            "criterio_caja": 1 if tipo == "proveedor" and datos.get("criterio_caja") in (1, "1", "on", True) else 0,
            "concepto": str(datos.get("concepto") or "").strip()[:60] or None}


def guardar_regla(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, tipo: str, datos: dict, *, aprendida: bool = False) -> int:
    """Crea o cambia la regla de un proveedor o cliente (identificado por su NIF). Devuelve su id."""
    _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    r = _regla_validada(tipo, datos)
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO contabilidad_reglas (tenant_id, cliente_fiscal_id, tipo, nif, nombre, cuenta_linea, pct_iva, pct_retencion, subtipo, criterio_caja, concepto, aprendida, actualizado_en, pct_deducible) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(cliente_fiscal_id, tipo, nif) DO UPDATE SET nombre = excluded.nombre, cuenta_linea = excluded.cuenta_linea, "
                     "pct_iva = excluded.pct_iva, pct_retencion = excluded.pct_retencion, subtipo = excluded.subtipo, criterio_caja = excluded.criterio_caja, concepto = excluded.concepto, "
                     "aprendida = excluded.aprendida, actualizado_en = excluded.actualizado_en, pct_deducible = excluded.pct_deducible",
                     (tenant_id, cliente_fiscal_id, r["tipo"], r["nif"], r["nombre"], r["cuenta_linea"], r["pct_iva"], r["pct_retencion"], r["subtipo"], r["criterio_caja"], r["concepto"],
                      1 if aprendida else 0, db.now_iso(), r["pct_deducible"]))
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


def sugerencias_de_reglas(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, minimo: int = 2, solo_revisadas: bool = False) -> list[dict]:
    """Los proveedores y clientes con al menos `minimo` facturas y sin regla, con lo que tienen en común todas sus facturas (cuenta, IVA, retención, tipo de operación). Solo cuenta lo que
    coincide en todas: un tercero cuyas facturas llevan IVA distinto no propone IVA."""
    _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT x.id, x.tipo, x.tercero_nif, x.tercero_nombre, x.concepto, x.criterio_caja, l.cuenta, l.subtipo, l.pct_iva, l.pct_retencion FROM facturas_contables x "
                             "JOIN facturas_contables_lineas l ON l.factura_id = x.id WHERE x.cliente_fiscal_id = ? AND x.tenant_id = ? AND x.estado != 'descartada' AND x.tercero_nif IS NOT NULL "
                             + ("AND x.estado IN ('revisada', 'exportada') AND x.revision_auto = 0 " if solo_revisadas else "") + "ORDER BY x.id", (cliente_fiscal_id, tenant_id)).fetchall()
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


def aprender_regla(tenant_id: int, usuario_id: int, f: dict) -> bool:
    """Aprende de lo que corrigen las personas: cuando una persona da por revisada una factura y ese proveedor o cliente ya tiene al menos dos facturas REVISADAS A MANO con la misma cuenta, IVA,
    retención o tipo de operación (y aún no tiene regla), se crea su regla marcada como «aprendida» para que la próxima factura salga ya rellena. Las revisadas solas por la IA no enseñan nada.
    Una regla creada a mano nunca se pisa. Devuelve si creó una."""
    nif = _nif(f.get("tercero_nif"))
    if not nif:
        return False
    tipo = _tipo_tercero(f["tipo"])
    sugerencia = next((x for x in sugerencias_de_reglas(tenant_id, usuario_id, f["cliente_fiscal_id"], minimo=2, solo_revisadas=True) if x["tipo"] == tipo and x["nif"] == nif), None)
    if not sugerencia or not (sugerencia["cuenta_linea"] or sugerencia["pct_iva"] is not None or sugerencia["pct_retencion"] or sugerencia["subtipo"] not in (None, "01")):      # el «01» es lo de siempre: no enseña nada
        return False
    guardar_regla(tenant_id, usuario_id, f["cliente_fiscal_id"], tipo, sugerencia, aprendida=True)
    return True


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

def _partir_por_iva_deducible(lineas: list[dict], pct_deducible: int) -> list[dict]:
    """El IVA de este proveedor solo se deduce en parte (un vehículo, por ejemplo: 50 %): cada línea con IVA y operación normal (01) se parte en la parte deducible (01) y la que no lo es (07, «IVA no deducible»), que
    a3 lleva como mayor gasto. La base y la cuota se reparten sin perder un céntimo. Una línea sin IVA no se toca; con 0 % toda la línea pasa a no deducible."""
    res = []
    for l in lineas:
        if l["subtipo"] != "01" or not l["cuota_iva"] or not l["sujeta_iva"]:
            res.append(l)
            continue
        if pct_deducible <= 0:
            res.append({**l, "subtipo": "07"})
            continue
        base1 = enlace_a3.cuota(l["base_centimos"], pct_deducible)
        cuota1 = min(l["cuota_iva"], enlace_a3.cuota(l["cuota_iva"], pct_deducible))
        res.append({**l, "base_centimos": base1, "cuota_iva": cuota1, "cuota_recargo": enlace_a3.cuota(l["cuota_recargo"], pct_deducible), "cuota_retencion": enlace_a3.cuota(l["cuota_retencion"], pct_deducible)})
        res.append({**l, "subtipo": "07", "base_centimos": l["base_centimos"] - base1, "cuota_iva": l["cuota_iva"] - cuota1, "cuota_recargo": l["cuota_recargo"] - enlace_a3.cuota(l["cuota_recargo"], pct_deducible),
                    "cuota_retencion": l["cuota_retencion"] - enlace_a3.cuota(l["cuota_retencion"], pct_deducible)})
    if len(res) > MAX_LINEAS:
        raise ValueError(f"Como máximo {MAX_LINEAS} tipos de IVA por factura (con la parte no deducible del IVA, las líneas se duplican).")
    return res


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
                    "pct_recargo": pct_re, "cuota_recargo": cuota_re, "pct_retencion": pct_ret, "cuota_retencion": cuota_ret, "sujeta_iva": 0 if str(l.get("sujeta_iva")) == "0" else 1,
                    "impreso": (lambda v: v if v in IMPRESOS_VALIDOS else None)(re.sub(r"\D", "", str(l.get("impreso") or "")).zfill(2)[-2:] if str(l.get("impreso") or "").strip() else "")})
    if regla and tipo == "recibida" and regla.get("pct_deducible") is not None and regla["pct_deducible"] < 10000 and not any(str(l.get("subtipo") or "").strip() in ("07", "7") for l in lineas):
        res = _partir_por_iva_deducible(res, regla["pct_deducible"])
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
        conn.execute("UPDATE facturas_contables SET datos_a3 = ? WHERE id = ?", (_json_datos_a3(datos, d["tipo"]), fid))
        _guardar_lineas(conn, fid, ls)
        if d["tercero_cuenta"]:
            _recordar_tercero(conn, tenant_id, cliente_fiscal_id, d["tipo"], d["tercero_nif"] or "", d["tercero_nombre"], d["tercero_cuenta"])
        auditoria.registrar(tenant_id, usuario_id, "factura_contable.creada", "factura_contable", fid, {"cliente": f["nombre"], "tipo": d["tipo"], "numero": d["numero"], "total": total}, conn=conn)
        conn.commit()
        return fid
    finally:
        conn.close()


DATOS_A3 = ("bien_inversion", "dua", "clave_340", "nif_representante", "autofactura", "metalico", "inmuebles", "iban", "vencimiento", "forma_pago")


def _json_datos_a3(datos: dict, tipo: str, previos: dict | None = None) -> str | None:
    """Los datos de ampliación de a3 que llegan con la factura (sueltos, como en el formulario, o en `datos_a3`, como en una lectura con IA), validados y en JSON; None si no hay ninguno. Los de `datos_a3` se
    suman a los `previos` (una lectura no borra lo que puso una persona); los sueltos mandan, y uno vacío lo quita."""
    import json
    origen = dict(previos or {}) if isinstance(datos.get("datos_a3"), dict) else {}
    origen.update(datos["datos_a3"] if isinstance(datos.get("datos_a3"), dict) else {})
    origen.update({k: datos[k] for k in DATOS_A3 if k in datos})
    limpio = datos_a3_validados(origen, tipo)
    return json.dumps(limpio, ensure_ascii=False) if limpio else None


def _guardar_lineas(conn, factura_id: int, lineas: list[dict]) -> None:
    conn.execute("DELETE FROM facturas_contables_lineas WHERE factura_id = ?", (factura_id,))
    conn.executemany("INSERT INTO facturas_contables_lineas (factura_id, cuenta, subtipo, base_centimos, pct_iva, cuota_iva, pct_recargo, cuota_recargo, pct_retencion, cuota_retencion, sujeta_iva, impreso) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     [(factura_id, l["cuenta"], l["subtipo"], l["base_centimos"], l["pct_iva"], l["cuota_iva"], l["pct_recargo"], l["cuota_recargo"], l["pct_retencion"], l["cuota_retencion"],
                       l["sujeta_iva"], l.get("impreso")) for l in lineas])


def _leer_datos_a3(texto) -> dict:
    import json
    try:
        v = json.loads(texto) if texto else {}
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


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
    d["a3"] = _leer_datos_a3(d.get("datos_a3"))
    d["problemas"] = problemas(tenant_id, d)
    return d


def fijar_incluir_en_fiscal(tenant_id: int, usuario_id: int, factura_id: int, incluir: bool) -> None:
    """Elige si la factura cuenta para Guilda Fiscal (los modelos de impuestos). Una factura que ya tiene un apunte fiscal vivo no se puede sacar: primero hay que anular el apunte."""
    f = obtener(tenant_id, usuario_id, factura_id)
    if f is None:
        raise ValueError("Factura no encontrada.")
    valor = 1 if incluir else 0
    if int(f.get("incluir_en_fiscal", 1)) == valor:
        return
    conn = db.get_connection()
    try:
        if not incluir:
            try:
                hay = conn.execute("SELECT 1 FROM fiscal_apuntes WHERE tenant_id = ? AND factura_id = ? AND anulado_en IS NULL LIMIT 1", (tenant_id, factura_id)).fetchone()
            except Exception:                                                     # noqa: BLE001 — el despacho no tiene Guilda Fiscal: no hay apuntes
                conn.rollback()
                hay = None
            if hay:
                raise ValueError("Esta factura ya tiene un apunte en Guilda Fiscal: anúlalo antes de sacarla.")
        conn.execute("UPDATE facturas_contables SET incluir_en_fiscal = ? WHERE id = ? AND tenant_id = ?", (valor, factura_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "factura_contable.incluir_en_fiscal", "factura_contable", factura_id, {"incluir": bool(valor)}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def _cambios_de(antes: dict, despues: dict, total: int, lineas_nuevas: list[dict]) -> dict:
    """Lo que cambió al editar una factura, para su historial: {campo: [antes, después]} con los datos principales y `lineas: true` si cambió algún importe o cuenta de las líneas."""
    cambios = {}
    for campo, nuevo in (("fecha", despues["fecha"]), ("numero", despues["numero"]), ("tercero_nombre", despues["tercero_nombre"]), ("tercero_nif", despues["tercero_nif"]), ("concepto", despues["concepto"]),
                         ("total_centimos", total)):
        viejo = antes.get(campo)
        if (viejo or None) != (nuevo or None):
            cambios[campo] = [str(viejo if viejo is not None else "")[:60], str(nuevo if nuevo is not None else "")[:60]]
    columnas = ("cuenta", "subtipo", "base_centimos", "pct_iva", "cuota_iva", "pct_recargo", "cuota_recargo", "pct_retencion", "cuota_retencion")
    if [tuple(l.get(c) for c in columnas) for l in antes["lineas"]] != [tuple(l.get(c) for c in columnas) for l in lineas_nuevas]:
        cambios["lineas"] = True
    return cambios


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
        if "datos_a3" in datos or any(k in datos for k in DATOS_A3):                       # solo se tocan si llegan: una lectura con IA no borra lo que puso una persona
            conn.execute("UPDATE facturas_contables SET datos_a3 = ? WHERE id = ? AND tenant_id = ?", (_json_datos_a3(datos, f["tipo"], f.get("a3")), factura_id, tenant_id))
        _guardar_lineas(conn, factura_id, ls)
        if d["tercero_cuenta"]:
            _recordar_tercero(conn, tenant_id, f["cliente_fiscal_id"], f["tipo"], d["tercero_nif"] or "", d["tercero_nombre"], d["tercero_cuenta"])
        auditoria.registrar(tenant_id, usuario_id, "factura_contable.editada", "factura_contable", factura_id,
                            {"numero": d["numero"], "total": total, "cambios": _cambios_de(f, d, total, ls)}, conn=conn)
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
    if not f.get("tercero_nif") and not (f["tipo"] == "emitida" and (f.get("a3") or {}).get("clave_340") == "1"):         # un tique emitido no lleva el NIF del cliente
        res.append("Falta el NIF del proveedor o cliente.")
    ls = f.get("lineas") or []
    if not ls:
        res.append("No tiene líneas de IVA.")
    if f["tipo"] == "recibida" and any(l["subtipo"] == "06" for l in ls):
        if cfg.get("formato_enlace") != enlace_a3.FORMATO_CLASICO:
            res.append("Una importación (tipo de operación 06) solo se puede exportar en el formato clásico de 256 posiciones: cámbialo en la configuración de a3 del cliente.")
        elif not (f.get("a3") or {}).get("dua"):
            res.append("Una importación necesita el número de DUA (en «Datos para los modelos 340 y 347»).")
    for i, l in enumerate(ls, start=1):
        esperada = enlace_a3.cuota(l["base_centimos"], l["pct_iva"])
        if abs(esperada - l["cuota_iva"]) > TOLERANCIA_CENTIMOS and l["sujeta_iva"]:
            res.append(f"Línea {i}: la cuota de IVA ({l['cuota_iva'] / 100:.2f}) no coincide con la base por el porcentaje ({esperada / 100:.2f}).")
    if ls and f["total_centimos"] != _total_de(ls, f["suplidos_centimos"]):
        res.append("El total no cuadra con las líneas.")
    return res


def cambiar_estado(tenant_id: int, usuario_id: int, factura_id: int, nuevo: str, aprender: bool = True, confirmar_duplicado: bool = False) -> None:
    """`revisada` (solo si no hay problemas), `pendiente` (reabrir; una exportada solo si se reabre aposta), `descartada`. Si parece copia de una factura ya revisada o exportada, hay que confirmar que no lo es."""
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
        if not confirmar_duplicado:
            from . import facturas_control
            repetida = facturas_control.ya_contabilizada(tenant_id, f)
            if repetida:
                raise ValueError("Parece repetida: ya hay una factura revisada o exportada con los mismos datos. Si no lo es, confirma que no es un duplicado y vuelve a revisarla.")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE facturas_contables SET estado = ?, actualizado_en = ?, revisado_por = ?, revisado_en = ?, lote_id = CASE WHEN ? = 'exportada' THEN lote_id ELSE NULL END, confirmada_en = NULL WHERE id = ? AND tenant_id = ?",
                     (nuevo, db.now_iso(), usuario_id if nuevo == "revisada" else None, db.now_iso() if nuevo == "revisada" else None, nuevo, factura_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, f"factura_contable.{nuevo}", "factura_contable", factura_id, {"antes": f["estado"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    if nuevo == "revisada" and aprender:
        try:
            from . import lectura_calidad
            lectura_calidad.anotar_correcciones(tenant_id, factura_id, obtener(tenant_id, usuario_id, factura_id))      # qué cambió la persona respecto de lo que leyó el sistema
        except Exception:  # noqa: BLE001 -- medir no puede impedir revisar
            logger.warning("No se pudo anotar la calidad de la lectura", exc_info=True)
        try:
            aprender_regla(tenant_id, usuario_id, f)
        except Exception:  # noqa: BLE001 -- aprender es un extra: nunca debe impedir revisar
            logger.warning("No se pudo aprender la regla del proveedor", exc_info=True)


# --- Facturas repetidas ---------------------------------------------------------------------------------------------------------------------------------

def factura_igual(cliente_fiscal_id: int, nif, numero, excluir_id: int | None = None) -> dict | None:
    """Otra factura NO descartada del mismo cliente con el mismo NIF de proveedor o cliente y el mismo número (sin distinguir mayúsculas), o None."""
    nif, numero = _nif(nif), str(numero or "").strip()
    if not nif or not numero or numero == "(por leer)":
        return None
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT id, numero, fecha, estado FROM facturas_contables WHERE cliente_fiscal_id = ? AND tercero_nif = ? AND upper(numero) = ? AND estado != 'descartada' AND id != ? ORDER BY id LIMIT 1",
                         (cliente_fiscal_id, nif, numero.upper(), excluir_id or 0)).fetchone()
    finally:
        conn.close()
    return dict(f) if f else None


def historial(tenant_id: int, usuario_id: int, factura_id: int) -> list[dict]:
    """Lo que ha pasado con una factura, de lo más reciente a lo más antiguo: [{cuando, quien, que, detalle}]. Sale de la auditoría (no hay tabla propia). `que` va ya traducido."""
    from flask_babel import gettext as _
    if obtener(tenant_id, usuario_id, factura_id) is None:
        return []
    etiquetas = {"subida": _("Archivo subido"), "creada": _("Anotada"), "leida_ia": _("Leída con IA"), "leida_xml": _("Leída de la factura electrónica"), "revisada_auto": _("Revisada sola por la IA"),
                 "editada": _("Editada"), "revisada": _("Dada por revisada"), "pendiente": _("Reabierta"), "descartada": _("Descartada"), "exportada": _("Exportada a a3"),
                 "confirmada_a3": _("Confirmada en a3"), "asiento_de_pago": _("Asiento de cobro o pago generado"), "movida": _("Movida a otro cliente"), "no_es_factura": _("Apartada: no era una factura"), "incluir_en_fiscal": _("Incluida en Guilda Fiscal"), "pdf_separado": _("PDF separado en varias facturas")}
    nombres = {"fecha": _("la fecha"), "numero": _("el número"), "tercero_nombre": _("el nombre"), "tercero_nif": _("el NIF"), "concepto": _("el concepto"), "total_centimos": _("el total")}
    res = []
    for e in auditoria.listar(tenant_id, entidad="factura_contable", entidad_id=factura_id, limite=200):
        accion = e["accion"].split(".", 1)[-1]
        detalle = ""
        d = e.get("detalle")
        if accion == "editada" and isinstance(d, dict):
            cambios = d.get("cambios") or {}
            partes = [f"{nombres[c]}: {a or '—'} → {b or '—'}" if c != "total_centimos" else f"{nombres[c]}: {int(a or 0) / 100:.2f} → {int(b or 0) / 100:.2f}" for c, (a, b) in
                      ((c, v) for c, v in cambios.items() if c in nombres and isinstance(v, list))]
            if cambios.get("lineas"):
                partes.append(_("los importes"))
            detalle = "; ".join(partes)
        elif accion == "exportada" and isinstance(d, dict) and d.get("lote"):
            detalle = f"#{d['lote']}"
        res.append({"cuando": e["creado_en"], "quien": e.get("actor") or "", "que": etiquetas.get(accion, accion), "detalle": detalle})
    return res


def mover_a_cliente(tenant_id: int, usuario_id: int, factura_id: int, destino_id: int) -> None:
    """Pasa una factura pendiente a otro cliente del despacho (se subió o se leyó en el cliente equivocado). Se lleva su archivo a los documentos del destino y lo quita del cliente de origen si ninguna otra
    factura lo usa. Las cuentas escritas a mano (la del tercero y las de las líneas) se quitan: eran las del plan del otro cliente. La persona tiene que ver los dos clientes."""
    f = obtener(tenant_id, usuario_id, factura_id)
    if f is None:
        raise ValueError("Factura no encontrada.")
    if f["estado"] != "pendiente":
        raise ValueError("Solo se puede mover una factura pendiente: reábrela antes.")
    if int(destino_id) == f["cliente_fiscal_id"]:
        raise ValueError("La factura ya es de ese cliente.")
    destino = _cliente(tenant_id, usuario_id, int(destino_id))
    documento = None
    if f.get("documento_id"):
        from . import almacen_documentos
        doc = almacen_documentos.leer_de_cliente_fiscal(tenant_id, f["cliente_fiscal_id"], f["documento_id"], usuario_id)
        if doc is None:
            raise ValueError("No se encuentra el archivo de la factura.")
        documento = adjuntar(tenant_id, destino["id"], usuario_id, doc.get("nombre_archivo") or "factura", doc.get("tipo_mime"), bytes(doc["contenido"]))
    conn = db.get_connection()
    try:
        conn.execute("UPDATE facturas_contables SET cliente_fiscal_id = ?, documento_id = ?, tercero_cuenta = NULL, actualizado_en = ? WHERE id = ? AND tenant_id = ?",
                     (destino["id"], documento if documento is not None else f.get("documento_id"), db.now_iso(), factura_id, tenant_id))
        conn.execute("UPDATE facturas_contables_lineas SET cuenta = NULL WHERE factura_id = ?", (factura_id,))
        otras = conn.execute("SELECT COUNT(*) AS n FROM facturas_contables WHERE tenant_id = ? AND documento_id = ? AND id != ?", (tenant_id, f.get("documento_id"), factura_id)).fetchone()["n"] if f.get("documento_id") else 0
        auditoria.registrar(tenant_id, usuario_id, "factura_contable.movida", "factura_contable", factura_id, {"de": f["cliente_fiscal_id"], "a": destino["id"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    if f.get("documento_id") and not otras and documento != f["documento_id"]:
        from . import almacen_documentos
        almacen_documentos.eliminar_de_cliente_fiscal(usuario_id, f["cliente_fiscal_id"], f["documento_id"])


def posibles_duplicados(tenant_id: int, usuario_id: int, factura_id: int) -> list[dict]:
    """Facturas del mismo cliente que pueden ser esta misma (ver `facturas_control.duplicados`): [{id, numero, fecha, estado, motivo, contabilizada}]."""
    from . import facturas_control
    f = obtener(tenant_id, usuario_id, factura_id)
    if f is None or f["estado"] == "descartada":
        return []
    return facturas_control.duplicados(tenant_id, f)


def con_duplicado_entre(tenant_id: int, ids: list[int]) -> set[int]:
    """Cuáles de estas facturas tienen otra del mismo cliente con el mismo NIF y número (para marcarlas en la lista sin consultar una a una)."""
    ids = [int(i) for i in ids]
    if not ids:
        return set()
    conn = db.get_connection()
    try:
        filas = conn.execute(f"SELECT DISTINCT a.id FROM facturas_contables a JOIN facturas_contables b ON b.tenant_id = a.tenant_id AND b.cliente_fiscal_id = a.cliente_fiscal_id AND b.tercero_nif = a.tercero_nif "
                             f"AND upper(b.numero) = upper(a.numero) AND b.id != a.id AND b.estado != 'descartada' WHERE a.tenant_id = ? AND a.estado != 'descartada' AND a.numero != '(por leer)' "
                             f"AND a.id IN ({','.join('?' * len(ids))})", (tenant_id, *ids)).fetchall()
    finally:
        conn.close()
    return {r["id"] for r in filas}


# Las columnas de la lista: todas menos las dos que pesan (de dónde sacó la IA cada dato y los datos de a3, JSON de varios KB por factura): ninguna pantalla de lista las usa y con 300 filas eran megas por clic.
_COLUMNAS_PESADAS = ("lectura_evidencia", "datos_a3")
COLUMNAS_LISTA = ", ".join(f"x.{c}" for c in (
    "id", "tenant_id", "cliente_fiscal_id", "tipo", "origen", "estado", "fecha", "fecha_operacion", "numero", "tercero_nombre", "tercero_nif", "tercero_cuenta", "concepto", "referencia", "abono",
    "rectifica_fecha", "rectifica_numero", "documento_id", "suplidos_centimos", "total_centimos", "notas", "creado_por", "creado_en", "actualizado_en", "revisado_por", "revisado_en", "lote_id",
    "criterio_caja", "lectura", "lectura_error", "incluir_en_fiscal", "lectura_confianza", "lectura_fuente", "revision_auto", "confirmada_en", "pago_exportado_en"))


def listar(tenant_id: int, usuario_id: int, *, cliente_fiscal_id: int | None = None, estado: str | None = None, tipo: str | None = None, desde: str | None = None, hasta: str | None = None,
           limite: int = 300, orden: str | None = None) -> list[dict]:
    """Las facturas visibles, de la más reciente a la más antigua; con `orden="confianza"` primero las que peor se leyeron (las dudosas arriba, para mirarlas antes)."""
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
            "SELECT " + COLUMNAS_LISTA + ", c.nombre AS cliente_nombre FROM facturas_contables x JOIN clientes_fiscales c ON c.id = x.cliente_fiscal_id WHERE " + " AND ".join(donde) +
            (" ORDER BY CASE WHEN x.lectura_confianza IS NULL THEN 101 ELSE x.lectura_confianza END ASC, x.fecha DESC, x.id DESC LIMIT ?" if orden == "confianza" else " ORDER BY x.fecha DESC, x.id DESC LIMIT ?"), [*p, limite])]
    finally:
        conn.close()
    return [f for f in filas if visibles is None or f["cliente_fiscal_id"] in visibles]


UMBRAL_REVISION_EN_LOTE = 90


def revisables_en_lote(tenant_id: int, usuario_id: int, cliente_fiscal_id: int | None = None, umbral: int = UMBRAL_REVISION_EN_LOTE, ids: list[int] | None = None) -> list[dict]:
    """Las facturas pendientes que se pueden dar por buenas de golpe: leídas de una factura electrónica (datos exactos) o con IA y confianza al menos `umbral`, sin problemas, sin avisos de
    control (NIF dudoso, copia, fechas raras…) y no revisadas ya por la IA sola. Las demás necesitan que una persona las mire."""
    from . import facturas_control
    umbral = max(50, min(100, int(umbral)))
    res = []
    for f in listar(tenant_id, usuario_id, cliente_fiscal_id=cliente_fiscal_id, estado="pendiente", limite=2000):
        if ids is not None and f["id"] not in ids:
            continue
        if not (f.get("lectura") == "xml" or (f.get("lectura") == "ia" and (f.get("lectura_confianza") or 0) >= umbral)):
            continue
        completa = obtener(tenant_id, usuario_id, f["id"])
        if completa is None or completa["problemas"] or facturas_control.avisos(tenant_id, completa) or facturas_control.duplicados(tenant_id, completa):
            continue
        res.append(f)
    return res


def revisar_en_lote(tenant_id: int, usuario_id: int, cliente_fiscal_id: int | None = None, umbral: int = UMBRAL_REVISION_EN_LOTE, ids: list[int] | None = None) -> dict:
    """Da por revisadas las `revisables_en_lote`. Lo hace una persona (queda como revisor) pero no enseña reglas al sistema: aprende solo de lo que se mira una a una.
    Devuelve {revisadas, omitidas} (omitidas = las que se intentaron y no pasaron, con el motivo en la auditoría)."""
    hechas = omitidas = 0
    for f in revisables_en_lote(tenant_id, usuario_id, cliente_fiscal_id, umbral, ids):
        try:
            cambiar_estado(tenant_id, usuario_id, f["id"], "revisada", aprender=False)
            hechas += 1
        except ValueError:
            omitidas += 1
    if hechas:
        auditoria.registrar(tenant_id, usuario_id, "contabilidad.revision_en_lote", "tenant", tenant_id, {"revisadas": hechas, "umbral": umbral, "cliente_fiscal_id": cliente_fiscal_id})
    return {"revisadas": hechas, "omitidas": omitidas}


def siguiente_pendiente(tenant_id: int, usuario_id: int, factura_id: int, orden: str | None = None) -> int | None:
    """La id de la siguiente factura pendiente del mismo cliente tras `factura_id` en el orden de la lista (o de otro cliente si ya no quedan), o None si no hay más."""
    f = obtener(tenant_id, usuario_id, factura_id)
    if f is None:
        return None
    pendientes = [x["id"] for x in listar(tenant_id, usuario_id, cliente_fiscal_id=f["cliente_fiscal_id"], estado="pendiente", limite=2000, orden=orden) if x["id"] != factura_id]
    if not pendientes:
        pendientes = [x["id"] for x in listar(tenant_id, usuario_id, estado="pendiente", limite=2000, orden=orden) if x["id"] != factura_id]
    return pendientes[0] if pendientes else None


def resumen_por_estado(tenant_id: int, usuario_id: int, cliente_fiscal_id: int | None = None) -> dict[str, int]:
    cuentas = {e: 0 for e in ESTADOS}
    for f in listar(tenant_id, usuario_id, cliente_fiscal_id=cliente_fiscal_id, limite=5000):
        cuentas[f["estado"]] += 1
    return cuentas


# --- Exportar a a3 ---------------------------------------------------------------------------------------------------------------------------------------

def _altas_para_enlace(facturas: list[dict], nuevas: dict) -> list[dict]:
    """Las cuentas de terceros que el programa numera al exportar (`nuevas`), con su NIF y la fecha de su primera factura, para darlas de alta con sus datos (registro C del formato de 256). Los proveedores
    que aplican el criterio de caja se marcan."""
    altas = []
    for (tipo_tercero, nif), (cuenta, nombre) in nuevas.items():
        suyas = [f for f in facturas if _nif(f["tercero_nif"]) == nif and (f["tipo"] == "recibida") == (tipo_tercero == "proveedor")]
        altas.append({"cuenta": cuenta, "nombre": nombre, "nif": nif, "fecha": min((f["fecha"] for f in suyas), default=facturas[0]["fecha"]),
                      "criterio_caja": (True if any(f.get("criterio_caja") for f in suyas) else None) if tipo_tercero == "proveedor" else None})
    return altas


def _vencimiento_para_enlace(f: dict) -> dict:
    """El vencimiento de la factura para el registro V (formato clásico): fecha, forma de cobro o pago y la cuenta bancaria de 20 dígitos (los 20 últimos de un IBAN español)."""
    a = f.get("a3") or {}
    iban = a.get("iban") or ""
    return {"fecha": a.get("vencimiento"), "forma_pago": a.get("forma_pago"), "ccc": iban[4:] if iban.startswith("ES") else None}


def _ampliacion_para_enlace(f: dict) -> dict:
    """Los datos de ampliación del registro 4 (formato clásico): el 347 en céntimos o `True` (= el total de la factura)."""
    a = f.get("a3") or {}
    return {"dua": a.get("dua"), "clave_340": a.get("clave_340"), "nif_representante": a.get("nif_representante"), "autofactura": a.get("autofactura"),
            "metalico": True if a.get("metalico") == "total" else a.get("metalico"), "inmuebles": True if a.get("inmuebles") == "total" else a.get("inmuebles")}


def _para_enlace(tenant_id: int, f: dict, cfg: dict, nuevas: dict | None = None) -> dict:
    gasto_o_ingreso = cfg["cuenta_gasto"] if f["tipo"] == "recibida" else cfg["cuenta_ingreso"]
    cuenta_iva = cfg["cuenta_iva_soportado"] if f["tipo"] == "recibida" else cfg["cuenta_iva_repercutido"]
    return {"tipo": f["tipo"], "abono": bool(f["abono"]), "fecha": f["fecha"], "fecha_operacion": f["fecha_operacion"], "numero": f["numero"], "rectifica_fecha": f.get("rectifica_fecha"), "rectifica_numero": f.get("rectifica_numero"), "concepto": f["concepto"] or (
        ("Su Fra. " if f["tipo"] == "recibida" else "Nuestra Fra. ") + f["numero"]), "nif": f["tercero_nif"], "nombre": f["tercero_nombre"], "caja": bool(f.get("criterio_caja")) and f["tipo"] == "recibida",
        "cuenta_tercero": (nuevas or {}).get(("proveedor" if f["tipo"] == "recibida" else "cliente", _nif(f["tercero_nif"])), (None,))[0] or cuenta_efectiva(tenant_id, f, cfg), "total_centimos": f["total_centimos"],
        "bien_inversion": bool((f.get("a3") or {}).get("bien_inversion")) and f["tipo"] == "recibida", "ampliacion": _ampliacion_para_enlace(f), "vencimiento": _vencimiento_para_enlace(f), "observacion": f"Guilda Work #{f['id']}" + (f" · {f['concepto']}" if f.get("concepto") else ""),
        "lineas": [{"cuenta": l["cuenta"] or gasto_o_ingreso, "descripcion_cuenta": "Compras" if f["tipo"] == "recibida" else "Ventas", "subtipo": l["subtipo"], "base_centimos": l["base_centimos"], "pct_iva": l["pct_iva"], "cuota_iva": l["cuota_iva"],
                    "pct_recargo": l["pct_recargo"], "cuota_recargo": l["cuota_recargo"], "pct_retencion": l["pct_retencion"], "cuota_retencion": l["cuota_retencion"],
                    "sujeta_iva": bool(l["sujeta_iva"]), "impreso": impreso_de_linea(f["tipo"], l), "cuenta_iva": cuenta_iva, "cuenta_retencion": cfg["cuenta_retencion"] if l["cuota_retencion"] else None}
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
    formato = cfg.get("formato_enlace") or enlace_a3.FORMATO_SII
    contenido = enlace_a3.generar([_para_enlace(tenant_id, f, cfg, nuevas) for f in facturas], empresa=cfg["a3_empresa"], digitos=cfg["digitos"], formato=formato,
                                  altas=_altas_para_enlace(facturas, nuevas))
    return cliente, cfg, facturas, nuevas, contenido


def plan_completo(tenant_id: int, cliente_fiscal_id: int) -> set[str] | None:
    """Todas las cuentas del plan de a3 importado del cliente (del ancho de sus subcuentas), o None si no se importó o se importó antes de guardarlas todas."""
    import json
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT plan_cuentas FROM contabilidad_clientes WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id)).fetchone()
    finally:
        conn.close()
    try:
        cuentas = json.loads(f["plan_cuentas"]) if f and f["plan_cuentas"] else None
    except ValueError:
        return None
    return set(cuentas) if cuentas else None


def _fuera_del_plan(tenant_id: int, cliente_fiscal_id: int, cfg: dict, facturas: list[dict], nuevas: dict) -> list[dict]:
    """Si el cliente tiene importado su plan de cuentas de a3, avisa de las cuentas que se usan y no figuran en él: subcuentas de terceros escritas a mano o recordadas, y las de gasto o ingreso, IVA y retención.
    a3 las daría de alta nuevas: casi siempre es un error de tecleo o de configuración. Las genéricas y las que el programa numera solo (`nuevas`) no se avisan: son a propósito."""
    conn = db.get_connection()
    try:
        plan = {r["cuenta"] for r in conn.execute("SELECT cuenta FROM contabilidad_plan WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id))}
    finally:
        conn.close()
    completo = plan_completo(tenant_id, cliente_fiscal_id)
    if not plan and not completo:
        return []
    existentes = plan | (completo or set())
    genericas = {cfg["cuenta_proveedores"], cfg["cuenta_clientes"]}
    ancho = cfg["digitos"]
    avisos, vistas = [], set()

    def avisar(cuenta: str, tipo: str, texto: str) -> None:
        if (tipo, cuenta) not in vistas:
            vistas.add((tipo, cuenta))
            avisos.append({"registro": None, "mensaje": texto})
    for f in facturas:
        tipo = "proveedor" if f["tipo"] == "recibida" else "cliente"
        if (tipo, _nif(f["tercero_nif"])) not in nuevas:
            cuenta = cuenta_efectiva(tenant_id, f, cfg)
            if cuenta and cuenta not in existentes and cuenta not in genericas:
                avisar(cuenta, tipo, f"La subcuenta {cuenta} de {f['tercero_nombre']} no figura en el plan de cuentas importado de a3: a3 la dará de alta nueva o rechazará el asiento.")
        if not completo:
            continue
        gasto = cfg["cuenta_gasto"] if f["tipo"] == "recibida" else cfg["cuenta_ingreso"]
        iva = cfg["cuenta_iva_soportado"] if f["tipo"] == "recibida" else cfg["cuenta_iva_repercutido"]
        for l in f["lineas"]:
            for cuenta, que in ((l["cuenta"] or gasto, "de gasto o ingreso"), (iva, "de IVA"), (cfg["cuenta_retencion"] if l["cuota_retencion"] else None, "de retención")):
                c = re.sub(r"\D", "", str(cuenta or ""))[:ancho].ljust(ancho, "0") if cuenta else ""
                if c and c not in completo:
                    avisar(c, que, f"La cuenta {que} {c} (factura {f['numero']}) no figura en el plan de cuentas importado de a3: a3 la creará nueva. ¿Es un error?")
    return avisos


def comprobar_exportacion(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, *, desde: str | None = None, hasta: str | None = None) -> dict:
    """Pre-chequeo de lo que se exportaría ahora: genera el fichero en memoria, lo relee por sus posiciones y devuelve el informe (ver app/enlace_a3_chequeo.py). No marca ni guarda nada."""
    from . import enlace_a3_chequeo
    cliente, cfg, facturas, nuevas, contenido = _preparar_exportacion(tenant_id, usuario_id, cliente_fiscal_id, desde, hasta)
    informe = enlace_a3_chequeo.chequear(contenido, cfg["digitos"])
    informe["cliente"] = cliente["nombre"]
    informe["subcuentas_nuevas"] = [{"tipo": t, "nif": nif, "cuenta": c, "nombre": nom} for (t, nif), (c, nom) in nuevas.items()]
    informe["numeros"] = [f["numero"] for f in facturas]
    from . import facturas_control
    de_control = [{"registro": None, "mensaje": f"{f['numero']}: {a}"} for f in facturas for a in facturas_control.avisos(tenant_id, f) if "periodo ya cerrado" not in a]
    informe["avisos"] = [*informe["avisos"], *de_control, *_fuera_del_plan(tenant_id, cliente_fiscal_id, cfg, facturas, nuevas)]
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
        for f in facturas:
            auditoria.registrar(tenant_id, usuario_id, "factura_contable.exportada", "factura_contable", f["id"], {"lote": lote}, conn=conn)
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
            "SELECT l.id, l.cliente_fiscal_id, l.creado_en, l.desde, l.hasta, l.n_facturas, l.n_registros, l.comprobado_en, l.n_confirmadas, l.estado_a3, l.motivo_a3, l.estado_a3_en, l.clase, c.nombre AS cliente_nombre FROM contabilidad_lotes l JOIN clientes_fiscales c ON c.id = l.cliente_fiscal_id "
            "WHERE l.tenant_id = ?" + (" AND l.cliente_fiscal_id = ?" if cliente_fiscal_id else "") + " ORDER BY l.id DESC LIMIT ?", [tenant_id, *([cliente_fiscal_id] if cliente_fiscal_id else []), limite])]
    finally:
        conn.close()
    return [f for f in filas if visibles is None or f["cliente_fiscal_id"] in visibles]


ESTADOS_A3_DEL_LOTE = ("importado", "rechazado")


def fijar_estado_a3_del_lote(tenant_id: int, usuario_id: int, lote_id: int, estado: str, motivo: str = "") -> None:
    """Anota lo que pasó al importar el fichero en a3: `importado`, `rechazado` (con el motivo que dio a3) o vacío para quitarlo. Es una nota de la persona: no cambia las facturas."""
    if estado and estado not in ESTADOS_A3_DEL_LOTE:
        raise ValueError("Estado de fichero no válido.")
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT cliente_fiscal_id FROM contabilidad_lotes WHERE id = ? AND tenant_id = ?", (lote_id, tenant_id)).fetchone()
        if f is None or not acceso.puede_ver_cliente(tenant_id, usuario_id, f["cliente_fiscal_id"]):
            raise ValueError("No existe ese fichero.")
        conn.execute("UPDATE contabilidad_lotes SET estado_a3 = ?, motivo_a3 = ?, estado_a3_en = ? WHERE id = ? AND tenant_id = ?",
                     (estado or None, (motivo or "").strip()[:300] or None if estado == "rechazado" else None, db.now_iso() if estado else None, lote_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "contabilidad.estado_fichero_a3", "cliente_fiscal", f["cliente_fiscal_id"], {"lote": lote_id, "estado": estado or None, "motivo": (motivo or "")[:300] or None}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def facturas_para_asiento_de_pago(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, limite: int = 300) -> list[dict]:
    """Las facturas exportadas del cliente (no abonos) cuyo asiento de cobro o pago aún no ha salido en un fichero: [{id, tipo, numero, fecha, tercero, total}], las más antiguas primero."""
    _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT id, tipo, numero, fecha, tercero_nombre, total_centimos FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado = 'exportada' AND abono = 0 "
                             "AND pago_exportado_en IS NULL ORDER BY fecha, id LIMIT ?", (tenant_id, cliente_fiscal_id, max(1, min(int(limite), 2000)))).fetchall()
    finally:
        conn.close()
    return [{"id": f["id"], "tipo": f["tipo"], "numero": f["numero"], "fecha": f["fecha"], "tercero": f["tercero_nombre"], "total": f["total_centimos"]} for f in filas]


def asientos_de_pago(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, pagos: list[dict], *, repetir: bool = False) -> dict:
    """Genera el fichero para a3 con los asientos de **cobro** (facturas emitidas) y **pago** (recibidas) de las facturas indicadas, y lo guarda como fichero generado de clase «pagos». `pagos`: [{factura_id, fecha
    (AAAA-MM-DD; hoy por defecto), importe (en céntimos; el total por defecto, para un pago parcial), cuenta_tesoreria (la del cliente por defecto)}]. Solo del formato clásico de 256 posiciones, y de facturas ya
    exportadas (a3 tiene que tener la factura). Un pago: Debe el proveedor, Haber el banco; un cobro: Debe el banco, Haber el cliente. Marca las facturas para no repetirlas salvo con `repetir`."""
    from datetime import date as _date
    cliente = _cliente(tenant_id, usuario_id, cliente_fiscal_id)
    cfg = configuracion(tenant_id, cliente_fiscal_id)
    if cfg.get("formato_enlace") != enlace_a3.FORMATO_CLASICO:
        raise ValueError("Los asientos de cobro y pago solo se pueden generar en el formato clásico de 256 posiciones: cámbialo en la configuración de a3 del cliente.")
    if not cfg["a3_empresa"]:
        raise ValueError("Indica antes el código de empresa de a3 de este cliente.")
    if not isinstance(pagos, list) or not pagos or len(pagos) > 500:
        raise ValueError("Indica entre 1 y 500 facturas.")
    asientos, marcadas = [], []
    for p in pagos:
        f = obtener(tenant_id, usuario_id, int(p.get("factura_id") or 0))
        if f is None or f["cliente_fiscal_id"] != cliente_fiscal_id:
            raise ValueError("Una de las facturas no existe en este cliente.")
        if f["estado"] != "exportada" or f["abono"]:
            raise ValueError(f"La factura {f['numero']} tiene que estar exportada (ya en a3) y no ser un abono para generar su asiento de cobro o pago.")
        if f.get("pago_exportado_en") and not repetir:
            raise ValueError(f"La factura {f['numero']} ya tiene su asiento de cobro o pago en un fichero: si hace falta repetirlo, indícalo.")
        fecha = _fecha(p.get("fecha") or _date.today().isoformat(), "Fecha del cobro o pago")
        importe = int(p["importe"]) if p.get("importe") not in (None, "") else f["total_centimos"]
        if not 0 < importe <= f["total_centimos"]:
            raise ValueError(f"El importe de la factura {f['numero']} tiene que ser mayor que cero y no superar su total ({f['total_centimos'] / 100:.2f}).")
        tesoreria = re.sub(r"\D", "", str(p.get("cuenta_tesoreria") or "")) or cfg["cuenta_tesoreria"]
        tercero = cuenta_efectiva(tenant_id, f, cfg)
        cobro = f["tipo"] == "emitida"
        lineas = [{"cuenta": tesoreria, "nombre": "Banco o caja", "debe": True, "importe_centimos": importe}, {"cuenta": tercero, "nombre": f["tercero_nombre"], "debe": False, "importe_centimos": importe}] if cobro else \
                 [{"cuenta": tercero, "nombre": f["tercero_nombre"], "debe": True, "importe_centimos": importe}, {"cuenta": tesoreria, "nombre": "Banco o caja", "debe": False, "importe_centimos": importe}]
        asientos.append({"fecha": fecha, "referencia": f["numero"], "descripcion": ("Cobro fra. " if cobro else "Pago fra. ") + f["numero"], "lineas": lineas})
        marcadas.append(f["id"])
    from . import enlace_a3_chequeo
    contenido = enlace_a3.generar_asientos(asientos, empresa=cfg["a3_empresa"], digitos=cfg["digitos"])
    chequeo = enlace_a3_chequeo.chequear(contenido, cfg["digitos"])
    if chequeo["errores"]:
        e = chequeo["errores"][0]
        raise ValueError(f"El fichero no pasa el pre-chequeo ({len(chequeo['errores'])} errores). El primero: {e['mensaje']}")
    fechas = sorted(a["fecha"] for a in asientos)
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO contabilidad_lotes (tenant_id, cliente_fiscal_id, creado_por, creado_en, desde, hasta, n_facturas, n_registros, contenido, clase) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pagos')",
                           (tenant_id, cliente_fiscal_id, usuario_id, db.now_iso(), fechas[0], fechas[-1], len(asientos), contenido.count(b"\r\n"), contenido))
        lote = cur.lastrowid
        conn.executemany("UPDATE facturas_contables SET pago_exportado_en = ? WHERE id = ? AND tenant_id = ?", [(db.now_iso(), i, tenant_id) for i in marcadas])
        for i in marcadas:
            auditoria.registrar(tenant_id, usuario_id, "factura_contable.asiento_de_pago", "factura_contable", i, {"lote": lote}, conn=conn)
        auditoria.registrar(tenant_id, usuario_id, "contabilidad.asientos_de_pago", "cliente_fiscal", cliente_fiscal_id, {"lote": lote, "asientos": len(asientos)}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return {"lote": lote, "asientos": len(asientos), "registros": contenido.count(b"\r\n"), "contenido": contenido, "cliente": cliente["nombre"]}


DIAS_FICHERO_SIN_ESTADO = 3        # un fichero exportado que lleva tanto sin marcar como importado ni cruzar con lo que devuelve a3 pide que alguien lo mire


def ficheros_por_atender(tenant_id: int, usuario_id: int, hoy=None, dias: int = DIAS_FICHERO_SIN_ESTADO) -> list[dict]:
    """Los ficheros para a3 de los clientes que ve la persona que necesitan que alguien haga algo: los **rechazados** por a3 (con su motivo) y los que llevan `dias` o más sin que nadie los marque como importados
    ni se hayan cruzado con lo que devuelve a3. [{id, cliente_fiscal_id, cliente, creado_en, motivo: «rechazado» | «sin_estado», motivo_a3}], los más antiguos primero."""
    from datetime import date as _date, timedelta
    limite = ((hoy or _date.today()) - timedelta(days=dias)).isoformat()
    res = []
    for l in listar_lotes(tenant_id, usuario_id, None, 200):
        if l.get("estado_a3") == "rechazado":
            res.append({"id": l["id"], "cliente_fiscal_id": l["cliente_fiscal_id"], "cliente": l["cliente_nombre"], "creado_en": l["creado_en"], "motivo": "rechazado", "motivo_a3": l.get("motivo_a3")})
        elif not l.get("estado_a3") and not l.get("comprobado_en") and str(l["creado_en"])[:10] <= limite:
            res.append({"id": l["id"], "cliente_fiscal_id": l["cliente_fiscal_id"], "cliente": l["cliente_nombre"], "creado_en": l["creado_en"], "motivo": "sin_estado", "motivo_a3": None})
    return sorted(res, key=lambda x: x["creado_en"])


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
MIME_ADJUNTO = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "application/xml", "text/xml"}      # el XML es la factura electrónica (Facturae, UBL): se lee sin IA
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
    previa = factura_igual(cliente_fiscal_id, datos.get("tercero_nif"), datos.get("numero"))
    if previa is not None:
        raise ValueError(f"Ya tienes anotada la factura {previa['numero']} de ese proveedor o cliente (fecha {previa['fecha']}). Si es otra, cambia el número.")
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


def unir_paginas(archivos: list[tuple[str, str | None, bytes]]) -> list[tuple[str, str | None, bytes]]:
    """Las fotos de UNA misma factura (varias páginas, en el orden elegido) pasan a ser un solo PDF; así se lee y se revisa como una factura y no como tantas facturas como fotos. `ValueError` si alguna
    no es una imagen o no se pueden juntar."""
    from . import pdf_facturas
    archivos = [a for a in archivos if a and a[2]]
    if len(archivos) < 2:
        return archivos
    if any((a[1] or "").lower().split(";")[0] not in ("image/png", "image/jpeg", "image/webp", "image/gif") for a in archivos):
        raise ValueError("Para juntar páginas en una sola factura, todos los archivos deben ser fotos.")
    pdf = pdf_facturas.imagenes_a_pdf([a[2] for a in archivos])
    if pdf is None:
        raise ValueError("No se han podido juntar las fotos en una sola factura: prueba con menos fotos o más pequeñas.")
    return [("factura.pdf", "application/pdf", pdf)]


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


class Subida(list):
    """Los ids de las facturas creadas; `repetidas` cuenta los archivos que ya estaban enviados (no se vuelven a anotar)."""
    repetidas = 0


def _archivo_ya_anotado(cliente_fiscal_id: int, documento_id: int) -> bool:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT 1 FROM facturas_contables WHERE cliente_fiscal_id = ? AND documento_id = ? AND estado != 'descartada'", (cliente_fiscal_id, documento_id)).fetchone() is not None
    finally:
        conn.close()


def _subir(tenant_id: int, usuario_id: int | None, f, tipo: str, archivos, origen: str, nota: str) -> Subida:
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
    ids = Subida()
    for nombre, mime, contenido in archivos:
        documento_id = adjuntar(tenant_id, f["id"], usuario_id, nombre, mime, contenido)
        if _archivo_ya_anotado(f["id"], documento_id):                  # el mismo archivo otra vez: no se anota una segunda factura igual
            ids.repetidas += 1
            continue
        ids.append(_crear_borrador(tenant_id, usuario_id, f, tipo, documento_id, origen, nota))
    return ids


def subir_desde_portal(cliente_fiscal_id: int, tipo: str, archivos: list[tuple[str, str | None, bytes]], nota: str = "Subida por el cliente desde el portal, pendiente de leer.") -> Subida:
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
    ids = _subir(f["tenant_id"], None, f, tipo, archivos, "portal", nota)
    if not ids:
        raise ValueError("Ya nos enviaste esas facturas: tu gestoría las tiene.")
    _avisar_al_despacho(f, ids[-1], {"tercero_nombre": f"{len(ids)} archivo(s) por leer", "numero": ""}, len(ids))
    return ids


def avisar_al_equipo(f, titulo: str, cuerpo: str, url: str, datos: dict) -> None:
    """Avisa a quien lleva al cliente `f` (o, si nadie, a la dirección y la coordinación) con una notificación del tipo «mensaje del portal». Nunca rompe la operación que la provoca."""
    try:
        from . import notificaciones
        conn = db.get_connection()
        try:
            destinatarios = [f["responsable_id"]] if f["responsable_id"] else [r["id"] for r in conn.execute("SELECT u.id FROM usuarios u WHERE " + db.sql_supervisor(), (f["tenant_id"], f["tenant_id"]))]
        finally:
            conn.close()
        for uid in destinatarios:
            if uid and db.notificacion_tipo_activa(uid, "portal_mensaje_nuevo"):
                notificaciones.crear_y_enviar(uid, "portal_mensaje_nuevo", titulo, cuerpo[:100], url=url, datos={"tipo": "portal_mensaje_nuevo", **datos})
    except Exception:
        pass


def _avisar_al_despacho(f, factura_id: int, datos: dict, cuantas: int = 1, titulo: str | None = None) -> None:
    """Avisa a quien lleva al cliente de que ha anotado una factura (o escrito sobre ella)."""
    titulo = titulo or (f"{f['nombre']} ha anotado una factura" if cuantas == 1 else f"{f['nombre']} ha subido {cuantas} facturas")
    avisar_al_equipo(f, titulo, f"{datos.get('tercero_nombre') or ''} · {datos.get('numero') or ''}", f"/contabilidad/{factura_id}", {"factura_contable_id": factura_id})


def listar_del_cliente(cliente_fiscal_id: int, limite: int = 100) -> list[dict]:
    """Lo que ve el cliente de sus facturas anotadas (sin cuentas ni notas internas)."""
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute(
            "SELECT id, tipo, fecha, numero, tercero_nombre, total_centimos, estado, origen, documento_id, lectura, creado_en, confirmada_en FROM facturas_contables WHERE cliente_fiscal_id = ? ORDER BY fecha DESC, id DESC LIMIT ?",
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
        filas = conn.execute("SELECT x.cliente_fiscal_id, c.nombre, SUM(CASE WHEN x.estado = 'pendiente' THEN 1 ELSE 0 END) AS pendientes, SUM(CASE WHEN x.estado = 'revisada' THEN 1 ELSE 0 END) AS revisadas, "
                             "SUM(CASE WHEN x.estado = 'pendiente' AND x.lectura IN ('pendiente', 'fallida') THEN 1 ELSE 0 END) AS por_leer, SUM(CASE WHEN x.estado = 'pendiente' AND x.origen = 'portal' THEN 1 ELSE 0 END) AS del_portal, "
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
            "SELECT cliente_fiscal_id, COUNT(*) AS anotadas, COALESCE(SUM(CASE WHEN estado = 'pendiente' THEN 1 ELSE 0 END), 0) AS por_revisar FROM facturas_contables WHERE tenant_id = ? AND fecha BETWEEN ? AND ? AND estado != 'descartada' "
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
    from . import notificaciones_email as ne, portal_avisos, portal_recordatorios
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
            ficha = db.obtener_cliente_fiscal(tenant_id, cid)
            enlace = portal_recordatorios.con_destino(url_portal, f"/portal/facturas?trimestre={trimestre}", cid)
            fallos: list[str] = []
            if portal_avisos.correo_directo(ficha, lambda e: ne.enviar_recordatorio_facturas(e, c["nombre"], trimestre, fecha_limite, enlace, tenant_id=tenant_id), urgente=True, accion="subir", errores=fallos) == 0:
                omitidos.append((c["nombre"], fallos[0] if fallos else "nadie con acceso quiere recibir este aviso"))
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
    for tabla in ("justificantes_pendientes", "facturas_contables_mensajes", "facturas_contables", "contabilidad_lotes", "contabilidad_terceros", "contabilidad_clientes", "contabilidad_recordatorios", "contabilidad_despacho", "contabilidad_plan", "contabilidad_reglas", "contabilidad_cierres"):
        conn.execute(f"DELETE FROM {tabla} WHERE tenant_id = ?", (tenant_id,))
    from . import cobro_contabilidad
    cobro_contabilidad.borrar_datos_de_tenant(conn, tenant_id)


def uso_del_mes(tenant_id: int, mes: str | None = None) -> dict:
    """Lo consumido en un mes (AAAA-MM, por defecto el actual): facturas anotadas (y cuántas por el portal del cliente), con su archivo adjunto, y facturas y ficheros exportados. Es lo que
    se contaría para un cobro por uso."""
    mes = mes or db.now_iso()[:7]
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT COUNT(*) AS anotadas, COALESCE(SUM(CASE WHEN origen = 'portal' THEN 1 ELSE 0 END), 0) AS portal, COALESCE(SUM(CASE WHEN documento_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS con_archivo, COALESCE(SUM(CASE WHEN lectura = 'ia' THEN 1 ELSE 0 END), 0) AS leidas_ia FROM facturas_contables "
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
