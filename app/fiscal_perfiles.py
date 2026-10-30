"""Guilda Fiscal · F1: perfil fiscal VERSIONADO del titular y relaciones gestora↔titular (docs/fiscal-f1-esquema-propuesto.md).

Un titular (`clientes_fiscales`) tiene una sucesión de perfiles con vigencia (`vigente_desde` … `vigente_hasta`, NULL = vigente) que NO se solapan: lo impone `guardar_perfil` dentro de la misma
transacción y, en PostgreSQL, además la base (restricción de exclusión de la migración 002). Un titular nunca se fusiona con otro por compartir inmueble o gestora: `fiscal_relaciones` solo
dice «quién cuelga de quién», con vigencia, y las dos puntas son siempre titulares del MISMO despacho.

Los verticales `fiscal` y `alquileres` se registran reservados (`disponible=False`) hasta que tengan pantallas."""
from __future__ import annotations

import re

from datetime import date, timedelta

from flask_babel import lazy_gettext as _l

from . import auditoria, db, verticales

ID = "fiscal"

FORMAS_JURIDICAS = ("persona_fisica", "sociedad", "comunidad_bienes", "otra")
RESIDENCIAS = ("ES", "UE", "otro")
TERRITORIOS_IVA = ("peninsula_baleares", "canarias", "ceuta_melilla")
REGIMENES_IVA = ("general", "simplificado", "general_y_simplificado", "recargo", "exento", "otro")
PERIODICIDADES = ("trimestral", "mensual")
TIPOS_RELACION = ("gestora_titular", "grupo", "otro")
BANDERAS = ("criterio_caja", "sii", "redeme", "tributacion_foral", "autoliquidacion_conjunta", "exonerado_390", "deduce_pago_cuenta_carburantes", "prorrata_especial", "sectores_diferenciados")
_CAMPOS_PERFIL = ("forma_juridica", "residencia", "pais", "territorio_iva", "regimen_iva", "periodicidad", *BANDERAS, "prorrata_centesimas", "saldo_a_compensar_centimos", "actividades", "opciones", "notas")

# Clave de actividad de la página 4 del 303 (instrucciones oficiales, «B Clave»): se declara en el último periodo por quien está exonerado del 390
CODIGOS_ACTIVIDAD = {"A01": "Arrendadores de bienes inmuebles", "A02": "Ganadería independiente", "A03": "Resto de actividades empresariales", "A04": "Actividades profesionales de carácter artístico o deportivo",
                     "A05": "Resto de actividades profesionales", "B01": "Actividad agrícola", "B02": "Actividad ganadera dependiente", "B03": "Actividad forestal", "B04": "Producción del mejillón en batea",
                     "B05": "Actividad pesquera, excepto el mejillón en batea", "B06": "Otras actividades no sujetas al IAE", "C": "Actividades no iniciadas"}
MAX_ACTIVIDADES = 6                      # la página 4 recoge la principal y cinco más


def normalizar_actividades(valor) -> list[dict] | None:
    """`[{"codigo", "epigrafe", "descripcion"}]` validado (la primera es la principal) o None si no hay ninguna. Acepta la lista o su JSON; un campo vacío no se guarda."""
    if valor in (None, "", []):
        return None
    if isinstance(valor, str):
        import json
        try:
            valor = json.loads(valor)
        except ValueError:
            raise ErrorFiscal("Las actividades no tienen un formato válido.") from None
    if not isinstance(valor, list):
        raise ErrorFiscal("Las actividades deben ser una lista.")
    salida = []
    for x in valor:
        if not isinstance(x, dict):
            raise ErrorFiscal("Cada actividad debe llevar su clave, su epígrafe y su descripción.")
        codigo = str(x.get("codigo") or "").strip().upper()
        epigrafe = str(x.get("epigrafe") or "").strip().upper()
        descripcion = str(x.get("descripcion") or "").strip()[:120]
        if codigo and codigo not in CODIGOS_ACTIVIDAD:
            raise ErrorFiscal(f"La clave de actividad «{codigo}» no existe: usa una de {', '.join(CODIGOS_ACTIVIDAD)}.")
        if epigrafe and not re.fullmatch(r"[0-9A-Z]{1,4}", epigrafe):
            raise ErrorFiscal(f"El epígrafe del IAE «{epigrafe}» no es válido: lleva hasta cuatro cifras o letras.")
        if codigo or epigrafe or descripcion:
            salida.append({k: v for k, v in (("codigo", codigo), ("epigrafe", epigrafe), ("descripcion", descripcion)) if v})
    if len(salida) > MAX_ACTIVIDADES:
        raise ErrorFiscal(f"Como máximo {MAX_ACTIVIDADES} actividades: la principal y cinco más.")
    return salida or None


def actividades_de(perfil: dict) -> list[dict]:
    """Las actividades guardadas en un perfil (o en su copia dentro de una instantánea); lo que no se pueda leer se ignora."""
    try:
        return normalizar_actividades((perfil or {}).get("actividades")) or []
    except ErrorFiscal:
        return []


ESQUEMA = """
CREATE TABLE IF NOT EXISTS fiscal_perfiles (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    vigente_desde TEXT NOT NULL,
    vigente_hasta TEXT,
    forma_juridica TEXT NOT NULL CHECK (forma_juridica IN ('persona_fisica','sociedad','comunidad_bienes','otra')),
    residencia TEXT NOT NULL DEFAULT 'ES' CHECK (residencia IN ('ES','UE','otro')),
    pais TEXT,
    territorio_iva TEXT NOT NULL DEFAULT 'peninsula_baleares' CHECK (territorio_iva IN ('peninsula_baleares','canarias','ceuta_melilla')),
    regimen_iva TEXT NOT NULL DEFAULT 'general' CHECK (regimen_iva IN ('general','simplificado','general_y_simplificado','recargo','exento','otro')),
    periodicidad TEXT NOT NULL DEFAULT 'trimestral' CHECK (periodicidad IN ('trimestral','mensual')),
    criterio_caja INTEGER NOT NULL DEFAULT 0,
    sii INTEGER NOT NULL DEFAULT 0,
    redeme INTEGER NOT NULL DEFAULT 0,
    tributacion_foral INTEGER NOT NULL DEFAULT 0,
    autoliquidacion_conjunta INTEGER NOT NULL DEFAULT 0,
    exonerado_390 INTEGER NOT NULL DEFAULT 0,
    deduce_pago_cuenta_carburantes INTEGER NOT NULL DEFAULT 0,
    prorrata_especial INTEGER NOT NULL DEFAULT 0,
    prorrata_centesimas INTEGER,
    sectores_diferenciados INTEGER NOT NULL DEFAULT 0,
    saldo_a_compensar_centimos INTEGER NOT NULL DEFAULT 0,
    actividades TEXT,
    opciones TEXT,
    notas TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    actualizado_en TEXT,
    CHECK (vigente_hasta IS NULL OR vigente_hasta >= vigente_desde),
    CHECK (residencia = 'ES' OR pais IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fiscal_perfiles_vigencia ON fiscal_perfiles(tenant_id, cliente_fiscal_id, vigente_desde);
CREATE INDEX IF NOT EXISTS idx_fiscal_perfiles_cliente ON fiscal_perfiles(tenant_id, cliente_fiscal_id, vigente_hasta);

CREATE TABLE IF NOT EXISTS fiscal_relaciones (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    desde_cliente_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    hasta_cliente_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL DEFAULT 'gestora_titular' CHECK (tipo IN ('gestora_titular','grupo','otro')),
    vigente_desde TEXT NOT NULL,
    vigente_hasta TEXT,
    notas TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    CHECK (desde_cliente_id <> hasta_cliente_id),
    CHECK (vigente_hasta IS NULL OR vigente_hasta >= vigente_desde)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fiscal_relaciones_unica ON fiscal_relaciones(tenant_id, desde_cliente_id, hasta_cliente_id, tipo, vigente_desde);
CREATE INDEX IF NOT EXISTS idx_fiscal_relaciones_hasta ON fiscal_relaciones(tenant_id, hasta_cliente_id);
"""


class ErrorFiscal(ValueError):
    """`codigo`: 'invalido' · 'no_encontrado' · 'solapa' · 'version_obsoleta' (el resto de la aplicación los traduce a 400/404/409/412)."""

    def __init__(self, mensaje: str, codigo: str = "invalido", **extra):
        super().__init__(mensaje)
        self.codigo = codigo
        self.extra = extra


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    for tabla in ("fiscal_relaciones", "fiscal_perfiles"):
        conn.execute(f"DELETE FROM {tabla} WHERE tenant_id = ?", (tenant_id,))


# --- Utilidades -----------------------------------------------------------------------------------------------------------------------------------
def _fecha(valor, campo: str, obligatoria: bool = True) -> str | None:
    if valor in (None, ""):
        if obligatoria:
            raise ErrorFiscal(f"Falta la fecha «{campo}».")
        return None
    try:
        return date.fromisoformat(str(valor)).isoformat()
    except ValueError:
        raise ErrorFiscal(f"«{campo}» no es una fecha válida (AAAA-MM-DD).") from None


def _ahora() -> str:
    return db.now_iso()


def _entero(valor, campo: str, *, minimo: int | None = None, maximo: int | None = None, opcional: bool = False) -> int | None:
    if valor in (None, ""):
        if opcional:
            return None
        return 0
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise ErrorFiscal(f"«{campo}» debe ser un número entero.") from None
    if (minimo is not None and n < minimo) or (maximo is not None and n > maximo):
        raise ErrorFiscal(f"«{campo}» está fuera de rango.")
    return n


def _elegir(valor, opciones: tuple, campo: str, defecto: str | None = None) -> str:
    valor = defecto if valor in (None, "") else valor
    if valor not in opciones:
        raise ErrorFiscal(f"«{campo}» debe ser uno de: {', '.join(opciones)}.")
    return valor


def _titular(conn, tenant_id: int, cliente_fiscal_id: int):
    f = conn.execute("SELECT id FROM clientes_fiscales WHERE id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id)).fetchone()
    if not f:
        raise ErrorFiscal("El titular no existe en este despacho.", "no_encontrado")
    return f


def _normalizar(datos: dict) -> dict:
    """Valida y completa los campos del perfil (los que no vengan toman su valor por defecto)."""
    d = {
        "forma_juridica": _elegir(datos.get("forma_juridica"), FORMAS_JURIDICAS, "forma_juridica"),
        "residencia": _elegir(datos.get("residencia"), RESIDENCIAS, "residencia", "ES"),
        "pais": (datos.get("pais") or "").strip().upper() or None,
        "territorio_iva": _elegir(datos.get("territorio_iva"), TERRITORIOS_IVA, "territorio_iva", "peninsula_baleares"),
        "regimen_iva": _elegir(datos.get("regimen_iva"), REGIMENES_IVA, "regimen_iva", "general"),
        "periodicidad": _elegir(datos.get("periodicidad"), PERIODICIDADES, "periodicidad", "trimestral"),
        "prorrata_centesimas": _entero(datos.get("prorrata_centesimas"), "prorrata_centesimas", minimo=0, maximo=10000, opcional=True),
        "saldo_a_compensar_centimos": _entero(datos.get("saldo_a_compensar_centimos"), "saldo_a_compensar_centimos", minimo=0),
        "actividades": normalizar_actividades(datos.get("actividades")),
        "opciones": datos.get("opciones") or None,
        "notas": (datos.get("notas") or "").strip() or None,
    }
    for b in BANDERAS:
        d[b] = 1 if datos.get(b) in (1, True, "1", "on", "true") else 0
    if d["residencia"] != "ES" and not d["pais"]:
        raise ErrorFiscal("Si no reside en España, indica el país (código de dos letras).")
    if d["residencia"] == "ES":
        d["pais"] = d["pais"] if d["pais"] and d["pais"] != "ES" else None
    for k in ("actividades", "opciones"):
        if d[k] is not None and not isinstance(d[k], str):
            import json
            d[k] = json.dumps(d[k], ensure_ascii=False, sort_keys=True)
    return d


def _solapa(conn, tenant_id: int, cliente_fiscal_id: int, desde: str, hasta: str | None, excepto_id: int | None = None):
    fin = hasta or "9999-12-31"
    return conn.execute(
        "SELECT id, vigente_desde, vigente_hasta FROM fiscal_perfiles WHERE tenant_id = ? AND cliente_fiscal_id = ? AND id <> ? AND vigente_desde <= ? AND COALESCE(vigente_hasta, '9999-12-31') >= ?",
        (tenant_id, cliente_fiscal_id, excepto_id or 0, fin, desde)).fetchone()


# --- Perfiles -------------------------------------------------------------------------------------------------------------------------------------
def guardar_perfil(tenant_id: int, usuario_id: int | None, cliente_fiscal_id: int, datos: dict, *, vigente_desde, vigente_hasta=None, perfil_id: int | None = None,
                   version: int | None = None) -> dict:
    """Alta de un perfil (sin `perfil_id`) o edición (con `perfil_id` y la `version` que se leyó: si ya cambió, `version_obsoleta`).

    En un alta, si el perfil anterior sigue abierto y empezó antes, se CIERRA el día anterior al nuevo (así «cambiar de régimen en el 3T» es un solo gesto); cualquier otro solapamiento se rechaza."""
    desde, hasta = _fecha(vigente_desde, "vigente_desde"), _fecha(vigente_hasta, "vigente_hasta", False)
    if hasta and hasta < desde:
        raise ErrorFiscal("«vigente_hasta» no puede ser anterior a «vigente_desde».")
    d = _normalizar(datos)
    conn = db.get_connection()
    try:
        _titular(conn, tenant_id, cliente_fiscal_id)
        if perfil_id is None:
            abierto = conn.execute("SELECT id, vigente_desde FROM fiscal_perfiles WHERE tenant_id = ? AND cliente_fiscal_id = ? AND vigente_hasta IS NULL AND vigente_desde < ?",
                                   (tenant_id, cliente_fiscal_id, desde)).fetchone()
            if abierto:
                cierre = (date.fromisoformat(desde) - timedelta(days=1)).isoformat()
                conn.execute("UPDATE fiscal_perfiles SET vigente_hasta = ?, version = version + 1, actualizado_en = ? WHERE id = ? AND tenant_id = ?", (cierre, _ahora(), abierto["id"], tenant_id))
            if _solapa(conn, tenant_id, cliente_fiscal_id, desde, hasta):
                raise ErrorFiscal("Ese periodo se solapa con otro perfil del mismo titular.", "solapa")
            cols = ("tenant_id", "cliente_fiscal_id", "vigente_desde", "vigente_hasta", *_CAMPOS_PERFIL, "creado_por", "creado_en")
            vals = (tenant_id, cliente_fiscal_id, desde, hasta, *(d[c] for c in _CAMPOS_PERFIL), usuario_id, _ahora())
            cur = conn.execute(f"INSERT INTO fiscal_perfiles ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
            perfil_id = cur.lastrowid
            accion = "fiscal.perfil.crear"
        else:
            actual = conn.execute("SELECT * FROM fiscal_perfiles WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?", (perfil_id, tenant_id, cliente_fiscal_id)).fetchone()
            if not actual:
                raise ErrorFiscal("El perfil no existe.", "no_encontrado")
            if version is None or int(version) != actual["version"]:
                raise ErrorFiscal("Alguien ha cambiado este perfil mientras lo editabas.", "version_obsoleta", version_actual=actual["version"])
            if _solapa(conn, tenant_id, cliente_fiscal_id, desde, hasta, excepto_id=perfil_id):
                raise ErrorFiscal("Ese periodo se solapa con otro perfil del mismo titular.", "solapa")
            sets = ", ".join(f"{c} = ?" for c in ("vigente_desde", "vigente_hasta", *_CAMPOS_PERFIL))
            conn.execute(f"UPDATE fiscal_perfiles SET {sets}, version = version + 1, actualizado_en = ? WHERE id = ? AND tenant_id = ? AND version = ?",
                         (desde, hasta, *(d[c] for c in _CAMPOS_PERFIL), _ahora(), perfil_id, tenant_id, actual["version"]))
            accion = "fiscal.perfil.editar"
        auditoria.registrar(tenant_id, usuario_id, accion, "cliente_fiscal", cliente_fiscal_id, {"perfil_id": perfil_id, "desde": desde, "hasta": hasta}, conn=conn)
        fila = conn.execute("SELECT * FROM fiscal_perfiles WHERE id = ? AND tenant_id = ?", (perfil_id, tenant_id)).fetchone()
        conn.commit()
        return dict(fila)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def perfiles_de(tenant_id: int, cliente_fiscal_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT * FROM fiscal_perfiles WHERE tenant_id = ? AND cliente_fiscal_id = ? ORDER BY vigente_desde", (tenant_id, cliente_fiscal_id)).fetchall()
    finally:
        conn.close()
    return [dict(f) for f in filas]


def perfil_en(tenant_id: int, cliente_fiscal_id: int, fecha) -> dict | None:
    """El perfil vigente en esa fecha (los límites cuentan: vigente_desde y vigente_hasta son inclusivos), o None."""
    dia = _fecha(fecha, "fecha")
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM fiscal_perfiles WHERE tenant_id = ? AND cliente_fiscal_id = ? AND vigente_desde <= ? AND COALESCE(vigente_hasta, '9999-12-31') >= ?",
                         (tenant_id, cliente_fiscal_id, dia, dia)).fetchone()
    finally:
        conn.close()
    return dict(f) if f else None


# --- Relaciones -----------------------------------------------------------------------------------------------------------------------------------
def relacionar(tenant_id: int, usuario_id: int | None, desde_cliente_id: int, hasta_cliente_id: int, *, tipo: str = "gestora_titular", vigente_desde, vigente_hasta=None,
               notas: str | None = None) -> dict:
    """«`desde` gestiona/agrupa a `hasta`». Las dos puntas son titulares de este despacho; nunca se fusionan."""
    if int(desde_cliente_id) == int(hasta_cliente_id):
        raise ErrorFiscal("Un titular no puede relacionarse consigo mismo.")
    tipo = _elegir(tipo, TIPOS_RELACION, "tipo")
    desde, hasta = _fecha(vigente_desde, "vigente_desde"), _fecha(vigente_hasta, "vigente_hasta", False)
    if hasta and hasta < desde:
        raise ErrorFiscal("«vigente_hasta» no puede ser anterior a «vigente_desde».")
    conn = db.get_connection()
    try:
        _titular(conn, tenant_id, desde_cliente_id)
        _titular(conn, tenant_id, hasta_cliente_id)
        if conn.execute("SELECT 1 FROM fiscal_relaciones WHERE tenant_id = ? AND desde_cliente_id = ? AND hasta_cliente_id = ? AND tipo = ? AND vigente_desde = ?",
                        (tenant_id, desde_cliente_id, hasta_cliente_id, tipo, desde)).fetchone():
            raise ErrorFiscal("Esa relación ya existe con esa fecha de inicio.", "solapa")
        cur = conn.execute("INSERT INTO fiscal_relaciones (tenant_id, desde_cliente_id, hasta_cliente_id, tipo, vigente_desde, vigente_hasta, notas, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?)",
                           (tenant_id, desde_cliente_id, hasta_cliente_id, tipo, desde, hasta, (notas or "").strip() or None, usuario_id, _ahora()))
        auditoria.registrar(tenant_id, usuario_id, "fiscal.relacion.crear", "cliente_fiscal", hasta_cliente_id, {"desde": desde_cliente_id, "tipo": tipo}, conn=conn)
        fila = conn.execute("SELECT * FROM fiscal_relaciones WHERE id = ?", (cur.lastrowid,)).fetchone()
        conn.commit()
        return dict(fila)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def titulares_de(tenant_id: int, gestora_id: int, fecha=None, tipo: str = "gestora_titular") -> list[int]:
    dia = _fecha(fecha or date.today().isoformat(), "fecha")
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT DISTINCT hasta_cliente_id FROM fiscal_relaciones WHERE tenant_id = ? AND desde_cliente_id = ? AND tipo = ? AND vigente_desde <= ? AND COALESCE(vigente_hasta, '9999-12-31') >= ? ORDER BY 1",
                             (tenant_id, gestora_id, tipo, dia, dia)).fetchall()
    finally:
        conn.close()
    return [f[0] for f in filas]


def gestoras_de(tenant_id: int, titular_id: int, fecha=None, tipo: str = "gestora_titular") -> list[int]:
    dia = _fecha(fecha or date.today().isoformat(), "fecha")
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT DISTINCT desde_cliente_id FROM fiscal_relaciones WHERE tenant_id = ? AND hasta_cliente_id = ? AND tipo = ? AND vigente_desde <= ? AND COALESCE(vigente_hasta, '9999-12-31') >= ? ORDER BY 1",
                             (tenant_id, titular_id, tipo, dia, dia)).fetchall()
    finally:
        conn.close()
    return [f[0] for f in filas]


# --- Alta de los verticales (reservados hasta que tengan pantallas) --------------------------------------------------------------------------------
def _registrar() -> None:
    verticales.registrar(verticales.Vertical(ID, _l("Guilda Fiscal"), _l("Facturas, libros de IVA, cálculo del modelo 303 y fichero para presentar en la AEAT."), "bar-chart-3",
                                             disponible=False, esquema=crear_esquema, borrar_datos=borrar_datos_de_tenant,
                                             entradas_menu=(verticales.EntradaMenu("guilda_fiscal", _l("Guilda Fiscal"), "guilda_fiscal.cartera", "bar-chart-3"),)))
    if "alquileres" not in verticales.VERTICALES:
        verticales.registrar(verticales.Vertical("alquileres", _l("Guilda Fiscal Alquileres"), _l("Fiscalidad de alquileres de larga y corta duración, también a través de plataformas."), "house",
                                                 disponible=False))


_registrar()
