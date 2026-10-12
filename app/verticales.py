"""Módulos de negocio de Guilda Work («verticales»): Gestoría, Gabinete de abogados e Inmobiliaria. Son independientes y combinables; todos se apoyan
en el núcleo común (clientes, expedientes, plazos, tiempo, documentos: `app/nucleo.py`).

Se llaman «verticales» en el código porque el backoffice ya usa «módulo» para las herramientas conectadas (Outline, Chat, Drive…).

Un despacho tiene activo un vertical si:
  1. es `por_defecto` (hoy, Gestoría: lo que Guilda Work ha sido siempre), o
  2. tiene un **extra** de pago activo vinculado a él (`extras_guilda.vertical_id`), o
  3. el backoffice lo ha activado a mano (`tenants_verticales`, p. ej. una prueba gratuita),
y el backoffice no lo ha desactivado a mano. Los activos se guardan 30 s en memoria por despacho (`TTL_SEGUNDOS`): no cuesta una consulta por página,
y un cambio hecho desde el backoffice —otro proceso— se nota como mucho a los 30 s."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import wraps

from flask import abort, g
from flask_babel import lazy_gettext as _l

from . import db

TTL_SEGUNDOS = 30


@dataclass(frozen=True)
class Estado:
    id: str
    nombre: object            # texto traducible
    cerrado: bool = False


@dataclass(frozen=True)
class TipoExpediente:
    id: str
    nombre: object
    estados: tuple[Estado, ...]
    calendario: str = "general"          # "general" | "procesal": qué días cuentan para sus plazos

    def estado(self, estado_id: str) -> Estado | None:
        return next((e for e in self.estados if e.id == estado_id), None)

    @property
    def inicial(self) -> str:
        return self.estados[0].id


@dataclass(frozen=True)
class EntradaMenu:
    clave: str
    etiqueta: object
    endpoint: str
    icono: str


@dataclass(frozen=True)
class Vertical:
    id: str
    nombre: object
    descripcion: object
    icono: str
    por_defecto: bool = False
    disponible: bool = True               # false = reservado: aún no tiene pantallas, el backoffice no lo ofrece
    entradas_menu: tuple[EntradaMenu, ...] = ()
    tipos_expediente: tuple[TipoExpediente, ...] = ()


ESTADOS_GENERALES = (Estado("abierto", _l("Abierto")), Estado("en_curso", _l("En curso")), Estado("en_espera", _l("En espera")), Estado("cerrado", _l("Cerrado"), True))
TIPO_GENERAL = TipoExpediente("general", _l("Expediente"), ESTADOS_GENERALES)

# Orden = orden en que se ofrecen. Los tipos de expediente de cada vertical se añaden aquí cuando se construye su módulo (Días 4 y 5).
VERTICALES: dict[str, Vertical] = {v.id: v for v in (
    Vertical("gestoria", _l("Gestoría"), _l("Calendario fiscal, clientes fiscales, vencimientos, recordatorios y portal de cliente."), "calendar-days", por_defecto=True),
    Vertical("abogados", _l("Gabinete de abogados"), _l("Expedientes judiciales y extrajudiciales, plazos procesales, minutas y provisión de fondos."), "briefcase", disponible=False),
    Vertical("inmobiliaria", _l("Inmobiliaria"), _l("Inmuebles, captación, demandas, visitas, contratos y comisiones."), "building-2", disponible=False),
)}


def tipos_expediente(tenant_id: int | None = None, activos: frozenset[str] | None = None) -> dict[str, TipoExpediente]:
    """Tipos de expediente que puede crear un despacho: el general y los de sus verticales activos."""
    activos = activos if activos is not None else activos_de(tenant_id)
    tipos = {TIPO_GENERAL.id: TIPO_GENERAL}
    for vid in VERTICALES:
        if vid in activos:
            for t in VERTICALES[vid].tipos_expediente:
                tipos[t.id] = t
    return tipos


def tipo_de(tipo_id: str) -> TipoExpediente:
    """El tipo con ese id (de cualquier vertical), o el general si ya no existe (un tipo retirado no debe romper expedientes antiguos)."""
    for v in VERTICALES.values():
        for t in v.tipos_expediente:
            if t.id == tipo_id:
                return t
    return TIPO_GENERAL


# --- Qué verticales tiene activos un despacho -------------------------------------------------------------------------------------------------
_CACHE: dict[tuple[str, int], tuple[float, frozenset[str]]] = {}


def _clave(tenant_id: int) -> tuple[str, int]:
    return (str(db.DB_PATH), tenant_id)         # la ruta evita mezclar bases distintas (los tests usan una por prueba)


def invalidar(tenant_id: int | None = None) -> None:
    if tenant_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(_clave(tenant_id), None)


def _calcular(tenant_id: int, ahora: str) -> frozenset[str]:
    activos = {v.id for v in VERTICALES.values() if v.por_defecto}
    conn = db.get_connection()
    try:
        for f in conn.execute(
            "SELECT eg.vertical_id FROM tenants_extras_activos tea JOIN extras_guilda eg ON eg.id = tea.extra_id "
            "WHERE tea.tenant_id = ? AND eg.vertical_id IS NOT NULL AND tea.activo_desde <= ? AND (tea.activo_hasta IS NULL OR tea.activo_hasta >= ?)",
            (tenant_id, ahora, ahora),
        ):
            activos.add(f["vertical_id"])
        for f in conn.execute("SELECT vertical_id, activo, activo_hasta FROM tenants_verticales WHERE tenant_id = ?", (tenant_id,)):
            if f["activo"] and (f["activo_hasta"] is None or f["activo_hasta"] >= ahora):
                activos.add(f["vertical_id"])
            elif not f["activo"]:
                activos.discard(f["vertical_id"])
    finally:
        conn.close()
    return frozenset(v for v in activos if v in VERTICALES)


def activos_de(tenant_id: int | None, *, ahora: str | None = None, usar_cache: bool = True) -> frozenset[str]:
    """Ids de los verticales activos de un despacho. Sin despacho (la persona local de escritorio) valen los `por_defecto`."""
    if tenant_id is None:
        return frozenset(v.id for v in VERTICALES.values() if v.por_defecto)
    ahora = ahora or db.now_iso()
    clave = _clave(tenant_id)
    if usar_cache and clave in _CACHE and time.monotonic() - _CACHE[clave][0] < TTL_SEGUNDOS:
        return _CACHE[clave][1]
    res = _calcular(tenant_id, ahora)
    _CACHE[clave] = (time.monotonic(), res)
    return res


def esta_activo(tenant_id: int | None, vertical_id: str) -> bool:
    return vertical_id in activos_de(tenant_id)


def fijar_activo(tenant_id: int, vertical_id: str, activo: bool, activo_hasta: str | None = None) -> None:
    """Activa o desactiva a mano un vertical para un despacho (backoffice). `activo_hasta` solo vale al activar (prueba con caducidad)."""
    if vertical_id not in VERTICALES:
        raise ValueError("Módulo de negocio desconocido.")
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO tenants_verticales (tenant_id, vertical_id, activo, activo_hasta, creado_en) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(tenant_id, vertical_id) DO UPDATE SET activo = excluded.activo, activo_hasta = excluded.activo_hasta",
            (tenant_id, vertical_id, 1 if activo else 0, activo_hasta if activo else None, db.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    invalidar(tenant_id)


def quitar_ajuste_manual(tenant_id: int, vertical_id: str) -> None:
    """Vuelve a lo que corresponda por defecto o por extras (borra el ajuste manual)."""
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM tenants_verticales WHERE tenant_id = ? AND vertical_id = ?", (tenant_id, vertical_id))
        conn.commit()
    finally:
        conn.close()
    invalidar(tenant_id)


def estado_para_backoffice(tenant_id: int) -> list[dict]:
    """Por vertical disponible: si está activo y por qué (defecto, extra o ajuste manual)."""
    activos = activos_de(tenant_id, usar_cache=False)
    conn = db.get_connection()
    try:
        manual = {f["vertical_id"]: dict(f) for f in conn.execute("SELECT * FROM tenants_verticales WHERE tenant_id = ?", (tenant_id,))}
        por_extra = {f["vertical_id"] for f in conn.execute(
            "SELECT eg.vertical_id FROM tenants_extras_activos tea JOIN extras_guilda eg ON eg.id = tea.extra_id "
            "WHERE tea.tenant_id = ? AND eg.vertical_id IS NOT NULL AND (tea.activo_hasta IS NULL OR tea.activo_hasta >= ?)", (tenant_id, db.now_iso()))}
    finally:
        conn.close()
    res = []
    for v in VERTICALES.values():
        if not v.disponible:
            continue
        m = manual.get(v.id)
        motivo = "manual" if m else ("extra" if v.id in por_extra else ("defecto" if v.por_defecto else None))
        res.append({"id": v.id, "nombre": str(v.nombre), "descripcion": str(v.descripcion), "activo": v.id in activos, "motivo": motivo, "hasta": m["activo_hasta"] if m else None})
    return res


# --- Para las rutas y las plantillas ---------------------------------------------------------------------------------------------------------
def requiere_vertical(vertical_id: str):
    """Decorador de ruta: 404 si el despacho de la persona no tiene activo ese vertical (no se revela que existe)."""
    def deco(f):
        @wraps(f)
        def interior(*a, **k):
            if not esta_activo(g.get("tenant_id"), vertical_id):
                abort(404)
            return f(*a, **k)
        return interior
    return deco


def entradas_de_menu(tenant_id: int | None) -> list[EntradaMenu]:
    activos = activos_de(tenant_id)
    return [e for v in VERTICALES.values() if v.id in activos for e in v.entradas_menu]
