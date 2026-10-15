"""Módulo de negocio «Inmobiliaria»: inmuebles (cada uno es una operación de venta o alquiler, o sea un expediente del núcleo, y sus fases son el embudo de captación),
demandas de compradores o inquilinos con cruce explicable, visitas con valoración, ofertas, contratos desde plantilla con versiones y firma, comisiones con reparto,
fotos y un enlace de solo lectura para el propietario con su informe mensual. Cuelga del núcleo común (`app/nucleo.py`): los plazos, las horas, los documentos y la
línea de tiempo de una operación son los de siempre.

**Todo lo normativo y los números por defecto son de ejemplo y están SIN VALIDAR** (porcentaje de comisión, IVA, textos de mandato, arras, alquiler y reserva): son valores
editables por agencia y la interfaz lo dice. Un contrato generado por plantilla no sustituye la revisión de un profesional."""
from __future__ import annotations

import io
import json
from dataclasses import replace
from datetime import date, datetime, timedelta

from flask_babel import lazy_gettext as _l

from . import almacen_documentos, db, enlaces_publicos, firma_documentos, generador_documentos, mensajes_enlace, nucleo, verticales
from .verticales import Estado, TipoExpediente

ID = "inmobiliaria"

ESTADOS_OPERACION = (
    Estado("contacto", _l("Primer contacto")), Estado("valoracion", _l("Valoración")), Estado("mandato", _l("Mandato firmado")), Estado("publicado", _l("Publicado")),
    Estado("visitas", _l("En visitas")), Estado("oferta", _l("Con oferta")), Estado("reserva", _l("Reservado / arras")), Estado("cerrada", _l("Cerrada"), True), Estado("perdida", _l("Perdida"), True),
)
TIPO_VENTA = TipoExpediente("operacion_venta", _l("Venta"), ESTADOS_OPERACION)
TIPO_ALQUILER = TipoExpediente("operacion_alquiler", _l("Alquiler"), ESTADOS_OPERACION)
TIPOS = (TIPO_VENTA.id, TIPO_ALQUILER.id)
OPERACIONES = {"venta": TIPO_VENTA.id, "alquiler": TIPO_ALQUILER.id}
EN_COMERCIALIZACION = ("publicado", "visitas", "oferta")

TIPOS_INMUEBLE = (("piso", _l("Piso")), ("casa", _l("Casa o chalet")), ("atico", _l("Ático")), ("local", _l("Local comercial")), ("oficina", _l("Oficina")), ("garaje", _l("Garaje")),
                  ("trastero", _l("Trastero")), ("terreno", _l("Terreno")), ("edificio", _l("Edificio")), ("otro", _l("Otro")))
CARACTERISTICAS = (("ascensor", _l("Ascensor")), ("terraza", _l("Terraza")), ("garaje", _l("Garaje")), ("piscina", _l("Piscina")), ("aire_acondicionado", _l("Aire acondicionado")),
                   ("amueblado", _l("Amueblado")), ("mascotas", _l("Admite mascotas")), ("exterior", _l("Exterior")), ("reformado", _l("Reformado")), ("trastero", _l("Trastero")))
CERTIFICADOS = ("A", "B", "C", "D", "E", "F", "G", "en_tramite", "exento")
ESTADOS_DEMANDA = (("activa", _l("Activa")), ("pausada", _l("Pausada")), ("satisfecha", _l("Satisfecha")), ("descartada", _l("Descartada")))
ESTADOS_VISITA = (("prevista", _l("Prevista")), ("realizada", _l("Realizada")), ("cancelada", _l("Cancelada")), ("ausente", _l("No se presentó")))
INTERES = (("alto", _l("Alto")), ("medio", _l("Medio")), ("bajo", _l("Bajo")), ("ninguno", _l("Ninguno")))
ESTADOS_OFERTA = (("pendiente", _l("Pendiente")), ("contraoferta", _l("Contraoferta")), ("aceptada", _l("Aceptada")), ("rechazada", _l("Rechazada")), ("retirada", _l("Retirada")))
TIPOS_CONTRATO = (("mandato_venta", _l("Mandato de venta")), ("arras", _l("Contrato de arras")), ("alquiler", _l("Contrato de alquiler")), ("reserva", _l("Documento de reserva")))
ESTADOS_COMISION = (("prevista", _l("Prevista")), ("facturada", _l("Facturada")), ("cobrada", _l("Cobrada")))

AJUSTES_POR_DEFECTO = {"iva_pct": 21, "comision_venta_bp": 300, "comision_alquiler_meses_x100": 100, "minimo_centimos": 0}
CAMPOS_PLANTILLA = {"mandato_venta": "plantilla_mandato", "arras": "plantilla_arras", "alquiler": "plantilla_alquiler", "reserva": "plantilla_reserva"}

_BASE = """({titulo}, modelo de ejemplo, sin validar)

En {fecha}.

REUNIDOS: {agencia} ("la Agencia"); {propietario} (NIF {nif_propietario}), propietario; y {parte} (NIF {nif_parte}).

Inmueble: {inmueble}, en {direccion}. Referencia catastral: {ref_catastral}.
"""
PLANTILLAS_POR_DEFECTO = {
    "mandato_venta": _BASE.format(titulo="MANDATO DE VENTA", **{k: "{" + k + "}" for k in ("fecha", "agencia", "propietario", "nif_propietario", "parte", "nif_parte", "inmueble", "direccion", "ref_catastral")}) +
    "\nEl propietario encarga a la Agencia la comercialización del inmueble al precio de {precio}, con unos honorarios de {comision}. Duración del encargo: {duracion}.\nEl propietario declara ser titular del inmueble y estar al corriente de sus cargas.\n\nFirman las partes en prueba de conformidad.\n",
    "arras": _BASE.format(titulo="CONTRATO DE ARRAS", **{k: "{" + k + "}" for k in ("fecha", "agencia", "propietario", "nif_propietario", "parte", "nif_parte", "inmueble", "direccion", "ref_catastral")}) +
    "\nLas partes acuerdan la compraventa del inmueble por {precio}. El comprador entrega en este acto {arras} en concepto de arras. La escritura se otorgará en {duracion}.\n\nFirman las partes en prueba de conformidad.\n",
    "alquiler": _BASE.format(titulo="CONTRATO DE ALQUILER", **{k: "{" + k + "}" for k in ("fecha", "agencia", "propietario", "nif_propietario", "parte", "nif_parte", "inmueble", "direccion", "ref_catastral")}) +
    "\nEl propietario arrienda el inmueble al inquilino por una renta mensual de {renta}. Fianza: {fianza}. Duración: {duracion}.\n\nFirman las partes en prueba de conformidad.\n",
    "reserva": _BASE.format(titulo="DOCUMENTO DE RESERVA", **{k: "{" + k + "}" for k in ("fecha", "agencia", "propietario", "nif_propietario", "parte", "nif_parte", "inmueble", "direccion", "ref_catastral")}) +
    "\nEl interesado entrega {arras} como reserva del inmueble, que se retirará de la comercialización durante {duracion}. Precio acordado: {precio}.\n\nFirman las partes en prueba de conformidad.\n",
}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS inmobiliaria_ajustes (
    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id),
    iva_pct INTEGER NOT NULL DEFAULT 21,
    comision_venta_bp INTEGER NOT NULL DEFAULT 300,
    comision_alquiler_meses_x100 INTEGER NOT NULL DEFAULT 100,
    minimo_centimos INTEGER NOT NULL DEFAULT 0,
    plantilla_mandato TEXT, plantilla_arras TEXT, plantilla_alquiler TEXT, plantilla_reserva TEXT
);

CREATE TABLE IF NOT EXISTS inmobiliaria_inmuebles (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    expediente_id INTEGER NOT NULL UNIQUE REFERENCES expedientes(id) ON DELETE CASCADE,
    referencia TEXT,
    tipo TEXT NOT NULL DEFAULT 'piso',
    direccion TEXT NOT NULL,
    municipio TEXT,
    codigo_postal TEXT,
    ref_catastral TEXT,
    superficie_m2 INTEGER,
    habitaciones INTEGER,
    banos INTEGER,
    planta TEXT,
    certificado_energetico TEXT,
    caracteristicas TEXT,
    precio_centimos INTEGER,
    descripcion TEXT,
    copropietarios TEXT,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inmobiliaria_inmuebles ON inmobiliaria_inmuebles(tenant_id, municipio);

CREATE TABLE IF NOT EXISTS inmobiliaria_precios (
    id INTEGER PRIMARY KEY,
    inmueble_id INTEGER NOT NULL REFERENCES inmobiliaria_inmuebles(id) ON DELETE CASCADE,
    precio_centimos INTEGER NOT NULL,
    fecha TEXT NOT NULL,
    motivo TEXT,
    usuario_id INTEGER REFERENCES usuarios(id)
);

CREATE TABLE IF NOT EXISTS inmobiliaria_demandas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    operacion TEXT NOT NULL CHECK (operacion IN ('venta', 'alquiler')),
    tipos TEXT,
    municipios TEXT,
    presupuesto_min_centimos INTEGER,
    presupuesto_max_centimos INTEGER,
    superficie_min INTEGER,
    habitaciones_min INTEGER,
    banos_min INTEGER,
    requisitos TEXT,
    notas TEXT,
    estado TEXT NOT NULL DEFAULT 'activa' CHECK (estado IN ('activa', 'pausada', 'satisfecha', 'descartada')),
    agente_id INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    actualizado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_inmobiliaria_demandas ON inmobiliaria_demandas(tenant_id, estado, operacion);

CREATE TABLE IF NOT EXISTS inmobiliaria_visitas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    inmueble_id INTEGER NOT NULL REFERENCES inmobiliaria_inmuebles(id) ON DELETE CASCADE,
    demanda_id INTEGER REFERENCES inmobiliaria_demandas(id) ON DELETE SET NULL,
    cliente_id INTEGER REFERENCES clientes(id),
    visitante TEXT,
    fecha_hora TEXT NOT NULL,
    agente_id INTEGER REFERENCES usuarios(id),
    estado TEXT NOT NULL DEFAULT 'prevista' CHECK (estado IN ('prevista', 'realizada', 'cancelada', 'ausente')),
    valoracion INTEGER CHECK (valoracion IS NULL OR (valoracion BETWEEN 1 AND 5)),
    interes TEXT,
    comentario TEXT,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inmobiliaria_visitas ON inmobiliaria_visitas(tenant_id, estado, fecha_hora);

CREATE TABLE IF NOT EXISTS inmobiliaria_ofertas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    inmueble_id INTEGER NOT NULL REFERENCES inmobiliaria_inmuebles(id) ON DELETE CASCADE,
    demanda_id INTEGER REFERENCES inmobiliaria_demandas(id) ON DELETE SET NULL,
    cliente_id INTEGER REFERENCES clientes(id),
    oferente TEXT,
    importe_centimos INTEGER NOT NULL CHECK (importe_centimos > 0),
    fecha TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'contraoferta', 'aceptada', 'rechazada', 'retirada')),
    notas TEXT,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inmobiliaria_contratos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    inmueble_id INTEGER NOT NULL REFERENCES inmobiliaria_inmuebles(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK (tipo IN ('mandato_venta', 'arras', 'alquiler', 'reserva')),
    version INTEGER NOT NULL,
    documento_id INTEGER,
    parte_nombre TEXT,
    parte_nif TEXT,
    datos TEXT,
    estado TEXT NOT NULL DEFAULT 'generado' CHECK (estado IN ('generado', 'enviado_firma', 'firmado')),
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inmobiliaria_comisiones (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    inmueble_id INTEGER NOT NULL UNIQUE REFERENCES inmobiliaria_inmuebles(id) ON DELETE CASCADE,
    base_centimos INTEGER NOT NULL,
    pct_bp INTEGER NOT NULL,
    minimo_centimos INTEGER NOT NULL DEFAULT 0,
    iva_pct INTEGER NOT NULL DEFAULT 21,
    honorarios_centimos INTEGER NOT NULL,
    iva_centimos INTEGER NOT NULL,
    total_centimos INTEGER NOT NULL,
    reparto TEXT,
    estado TEXT NOT NULL DEFAULT 'prevista' CHECK (estado IN ('prevista', 'facturada', 'cobrada')),
    creado_en TEXT NOT NULL,
    actualizado_en TEXT
);
"""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    enlaces_publicos.esquema(conn, ID)


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    enlaces_publicos.borrar_datos_de_tenant(conn, ID, tenant_id)
    ids = "SELECT id FROM inmobiliaria_inmuebles WHERE tenant_id = ?"
    for tabla in ("inmobiliaria_precios",):
        conn.execute(f"DELETE FROM {tabla} WHERE inmueble_id IN ({ids})", (tenant_id,))
    for tabla in ("inmobiliaria_comisiones", "inmobiliaria_contratos", "inmobiliaria_ofertas", "inmobiliaria_visitas", "inmobiliaria_demandas", "inmobiliaria_inmuebles", "inmobiliaria_ajustes"):
        conn.execute(f"DELETE FROM {tabla} WHERE tenant_id = ?", (tenant_id,))


# =============================================================================== Cálculos puros
def estado_comercial(operacion: str, estado: str) -> str:
    """Estado comercial de un inmueble según la fase de su operación: captación, en_venta/en_alquiler, reservado, vendido/alquilado o retirado."""
    if estado in ("contacto", "valoracion", "mandato"):
        return "captacion"
    if estado in EN_COMERCIALIZACION:
        return "en_venta" if operacion == "venta" else "en_alquiler"
    if estado == "reserva":
        return "reservado"
    if estado == "cerrada":
        return "vendido" if operacion == "venta" else "alquilado"
    return "retirado"


def calcular_comision(base_centimos: int, pct_bp: int, minimo_centimos: int = 0, iva_pct: int = 21) -> dict:
    """Honorarios = base × porcentaje (en puntos básicos: 300 = 3 %), con un mínimo; más IVA. Todo en céntimos, con el redondeo al céntimo más cercano."""
    honorarios = (base_centimos * pct_bp + 5000) // 10000
    aplicado_minimo = honorarios < minimo_centimos
    honorarios = max(honorarios, minimo_centimos)
    iva = (honorarios * iva_pct + 50) // 100
    return {"base": base_centimos, "honorarios": honorarios, "iva": iva, "total": honorarios + iva, "aplicado_minimo": aplicado_minimo}


def repartir(total_centimos: int, reparto: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Reparte un importe entre personas por porcentajes (que deben sumar 100) sin perder ni inventar ni un céntimo: el resto del redondeo va a quien más decimales tenía."""
    if not reparto or sum(p for _a, p in reparto) != 100 or any(p < 0 for _a, p in reparto):
        raise ValueError("El reparto debe sumar el 100 %.")
    partes = [(a, total_centimos * p // 100, (total_centimos * p) % 100) for a, p in reparto]
    resto = total_centimos - sum(x[1] for x in partes)
    orden = sorted(range(len(partes)), key=lambda i: (-partes[i][2], i))
    res = [[a, c] for a, c, _r in partes]
    for i in orden[:resto]:
        res[i][1] += 1
    return [(a, c) for a, c in res]


def puntuar(demanda: dict, inmueble: dict) -> dict:
    """Cuánto encaja un inmueble con una demanda (0-100) y por qué. Los filtros duros (misma operación, inmueble en comercialización) los comprueba quien llama.
    Puntos: tipo 20, zona 25, precio 30 (todo dentro del presupuesto, la mitad si lo supera en menos de un 10 % o no llega al mínimo), superficie 10, habitaciones 10 y baños 5;
    un criterio sin preferencia indicada da todos sus puntos. Cada requisito (ascensor, terraza…) que el inmueble no tiene resta 8 puntos. El resultado incluye cada razón con
    sus puntos para poder explicarlo a quien lo pregunte."""
    razones = []

    def razon(nombre, puntos, maximo, ok, detalle):
        razones.append({"criterio": nombre, "puntos": puntos, "maximo": maximo, "ok": ok, "detalle": detalle})

    tipos = demanda.get("tipos") or []
    if tipos:
        ok = inmueble["tipo"] in tipos
        razon("tipo", 20 if ok else 0, 20, ok, "El tipo de inmueble encaja." if ok else "No es de ninguno de los tipos buscados.")
    else:
        razon("tipo", 20, 20, True, "Sin preferencia de tipo.")
    zonas = [nucleo.plano(z).strip() for z in (demanda.get("municipios") or []) if z.strip()]
    if zonas:
        ok = nucleo.plano(inmueble.get("municipio") or "").strip() in zonas
        razon("zona", 25 if ok else 0, 25, ok, "Está en una de las zonas buscadas." if ok else "Está fuera de las zonas buscadas.")
    else:
        razon("zona", 25, 25, True, "Sin preferencia de zona.")
    precio, pmin, pmax = inmueble.get("precio_centimos"), demanda.get("presupuesto_min_centimos"), demanda.get("presupuesto_max_centimos")
    if precio and (pmin or pmax):
        if pmax and precio > pmax:
            if precio <= pmax * 1.10:
                razon("precio", 15, 30, False, "Supera el presupuesto en menos de un 10 %: negociable.")
            else:
                razon("precio", 0, 30, False, "Supera el presupuesto en más de un 10 %.")
        elif pmin and precio < pmin:
            razon("precio", 15, 30, False, "Está por debajo del mínimo indicado.")
        else:
            razon("precio", 30, 30, True, "Dentro del presupuesto.")
    else:
        razon("precio", 30, 30, True, "Sin presupuesto indicado.")
    for campo, maximo, clave, etiqueta in (("superficie_min", 10, "superficie_m2", "superficie"), ("habitaciones_min", 10, "habitaciones", "habitaciones"), ("banos_min", 5, "banos", "baños")):
        minimo = demanda.get(campo)
        if minimo:
            ok = (inmueble.get(clave) or 0) >= minimo
            razon(etiqueta, maximo if ok else 0, maximo, ok, f"{etiqueta.capitalize()}: {'cumple' if ok else 'no llega a'} el mínimo de {minimo}.")
        else:
            razon(etiqueta, maximo, maximo, True, f"Sin mínimo de {etiqueta}.")
    requisitos = demanda.get("requisitos") or []
    tiene = set(inmueble.get("caracteristicas") or [])
    faltan = [r for r in requisitos if r not in tiene]
    for r in requisitos:
        razon(f"requisito:{r}", 0, 0, r in tiene, f"{'Tiene' if r in tiene else 'No tiene'}: {verticales.original(dict(CARACTERISTICAS).get(r, r))}.")
    puntos = sum(r["puntos"] for r in razones)
    penal = min(puntos, 8 * len(faltan))                # cada requisito que falta resta 8 puntos (sin bajar de 0)
    total = max(0, min(100, puntos - penal))
    return {"puntos": total, "razones": razones, "faltan": faltan, "cumple_todo": all(r["ok"] for r in razones)}


# =============================================================================== Ajustes
def obtener_ajustes(tenant_id: int) -> dict:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM inmobiliaria_ajustes WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    a = dict(AJUSTES_POR_DEFECTO)
    if f:
        a.update({k: f[k] for k in AJUSTES_POR_DEFECTO})
    a["plantillas"] = {tipo: ((f[campo] if f else None) or PLANTILLAS_POR_DEFECTO[tipo]) for tipo, campo in CAMPOS_PLANTILLA.items()}
    a["plantillas_propias"] = {tipo: bool(f and f[campo]) for tipo, campo in CAMPOS_PLANTILLA.items()}
    return a


def guardar_ajustes(tenant_id: int, *, iva_pct, comision_venta_pct, comision_alquiler_meses, minimo_centimos, plantillas: dict[str, str]) -> None:
    try:
        iva = int(iva_pct)
        bp = int(round(float(str(comision_venta_pct).replace(",", ".")) * 100))
        meses = int(round(float(str(comision_alquiler_meses).replace(",", ".")) * 100))
        minimo = int(minimo_centimos)
    except (TypeError, ValueError):
        raise ValueError("IVA, comisión y mínimo deben ser números.") from None
    if not (0 <= iva <= 30 and 0 <= bp <= 2500 and 0 <= meses <= 1200 and 0 <= minimo <= 100_000_000):
        raise ValueError("Algún valor está fuera de rango (IVA 0-30 %, comisión de venta 0-25 %, alquiler hasta 12 mensualidades).")
    valores = {}
    for tipo, campo in CAMPOS_PLANTILLA.items():
        t = (plantillas.get(tipo) or "").strip()
        if len(t) > 20000:
            raise ValueError("Una plantilla de contrato es demasiado larga.")
        valores[campo] = t or None
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO inmobiliaria_ajustes (tenant_id, iva_pct, comision_venta_bp, comision_alquiler_meses_x100, minimo_centimos, plantilla_mandato, plantilla_arras, plantilla_alquiler, plantilla_reserva) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(tenant_id) DO UPDATE SET iva_pct = excluded.iva_pct, comision_venta_bp = excluded.comision_venta_bp, "
            "comision_alquiler_meses_x100 = excluded.comision_alquiler_meses_x100, minimo_centimos = excluded.minimo_centimos, plantilla_mandato = excluded.plantilla_mandato, "
            "plantilla_arras = excluded.plantilla_arras, plantilla_alquiler = excluded.plantilla_alquiler, plantilla_reserva = excluded.plantilla_reserva",
            (tenant_id, iva, bp, meses, minimo, valores["plantilla_mandato"], valores["plantilla_arras"], valores["plantilla_alquiler"], valores["plantilla_reserva"]))
        conn.commit()
    finally:
        conn.close()


# =============================================================================== Inmuebles
def _importe(valor) -> int | None:
    return None if valor in (None, "") else nucleo.importe_a_centimos(valor)


def _entero(valor, nombre: str, maximo: int = 100000) -> int | None:
    if valor in (None, ""):
        return None
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{nombre} debe ser un número.") from None
    if not (0 <= n <= maximo):
        raise ValueError(f"{nombre} está fuera de rango.")
    return n


def _lista(valor) -> list[str]:
    if isinstance(valor, str):
        valor = valor.replace(";", ",").split(",")
    return [v.strip() for v in (valor or []) if v and v.strip()]


def _inmueble_dict(f) -> dict:
    d = dict(f)
    try:
        d["caracteristicas"] = json.loads(f["caracteristicas"]) if f["caracteristicas"] else []
    except (TypeError, ValueError):
        d["caracteristicas"] = []
    return d


def crear_inmueble(tenant_id: int, usuario_id: int, propietario_id: int, operacion: str, direccion: str, *, tipo: str = "piso", municipio: str | None = None, codigo_postal: str | None = None,
                   ref_catastral: str | None = None, superficie_m2=None, habitaciones=None, banos=None, planta: str | None = None, certificado_energetico: str | None = None,
                   caracteristicas=None, precio=None, descripcion: str | None = None, copropietarios: str | None = None, referencia: str | None = None) -> tuple[int, int]:
    """Da de alta un inmueble: crea su operación (un expediente de venta o alquiler que arranca en «Primer contacto») y su ficha. Devuelve (inmueble_id, expediente_id)."""
    if operacion not in OPERACIONES:
        raise ValueError("Elige si es una venta o un alquiler.")
    if tipo not in dict(TIPOS_INMUEBLE):
        raise ValueError("Tipo de inmueble no válido.")
    direccion = (direccion or "").strip()
    if not direccion:
        raise ValueError("Indica la dirección del inmueble.")
    if certificado_energetico and certificado_energetico not in CERTIFICADOS:
        raise ValueError("Certificado energético no válido.")
    caracts = [c for c in _lista(caracteristicas) if c in dict(CARACTERISTICAS)]
    precio_c = _importe(precio)
    sup, hab, ban = _entero(superficie_m2, "La superficie"), _entero(habitaciones, "Las habitaciones", 100), _entero(banos, "Los baños", 100)
    titulo = f"{verticales.original(dict(TIPOS_INMUEBLE)[tipo])} en {direccion}"[:200]
    xid = nucleo.crear_expediente(tenant_id, usuario_id, propietario_id, titulo, tipo=OPERACIONES[operacion], descripcion=None)
    conn = db.get_connection()
    try:
        if not (referencia or "").strip():
            n = conn.execute("SELECT COUNT(*) FROM inmobiliaria_inmuebles WHERE tenant_id = ?", (tenant_id,)).fetchone()[0] + 1
            referencia = f"INM-{date.today().year}-{n:03d}"
            while conn.execute("SELECT 1 FROM inmobiliaria_inmuebles WHERE tenant_id = ? AND referencia = ?", (tenant_id, referencia)).fetchone():
                n += 1
                referencia = f"INM-{date.today().year}-{n:03d}"
        cur = conn.execute(
            "INSERT INTO inmobiliaria_inmuebles (tenant_id, expediente_id, referencia, tipo, direccion, municipio, codigo_postal, ref_catastral, superficie_m2, habitaciones, banos, planta, "
            "certificado_energetico, caracteristicas, precio_centimos, descripcion, copropietarios, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, xid, referencia.strip()[:40], tipo, direccion[:300], (municipio or "").strip()[:100] or None, (codigo_postal or "").strip()[:10] or None, (ref_catastral or "").strip()[:30] or None,
             sup, hab, ban, (planta or "").strip()[:20] or None, certificado_energetico or None, json.dumps(caracts), precio_c, (descripcion or "").strip()[:5000] or None,
             (copropietarios or "").strip()[:500] or None, db.now_iso()))
        iid = cur.lastrowid
        if precio_c:
            conn.execute("INSERT INTO inmobiliaria_precios (inmueble_id, precio_centimos, fecha, motivo, usuario_id) VALUES (?, ?, ?, 'Precio inicial', ?)", (iid, precio_c, date.today().isoformat(), usuario_id))
        conn.commit()
        return iid, xid
    finally:
        conn.close()


def obtener_inmueble(tenant_id: int, usuario_id: int, inmueble_id: int, supervisor: bool = False):
    """(inmueble como dict, expediente) si existe, es del despacho y la persona puede ver su operación; si no, (None, None)."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM inmobiliaria_inmuebles WHERE id = ? AND tenant_id = ?", (inmueble_id, tenant_id)).fetchone()
    finally:
        conn.close()
    if f is None:
        return None, None
    x = nucleo.obtener_expediente(tenant_id, f["expediente_id"], usuario_id, supervisor)
    return (_inmueble_dict(f), x) if x is not None else (None, None)


def _inmueble_o_error(tenant_id: int, usuario_id: int, inmueble_id: int, supervisor: bool):
    i, x = obtener_inmueble(tenant_id, usuario_id, inmueble_id, supervisor)
    if i is None:
        raise ValueError("Inmueble no encontrado.")
    return i, x


def inmueble_de_expediente(tenant_id: int, usuario_id: int, expediente_id: int, supervisor: bool = False):
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT id FROM inmobiliaria_inmuebles WHERE expediente_id = ? AND tenant_id = ?", (expediente_id, tenant_id)).fetchone()
    finally:
        conn.close()
    return obtener_inmueble(tenant_id, usuario_id, f["id"], supervisor) if f else (None, None)


def operacion_de(exp) -> str:
    return "venta" if exp["tipo"] == TIPO_VENTA.id else "alquiler"


def listar_inmuebles(tenant_id: int, usuario_id: int, supervisor: bool = False, *, operacion: str | None = None, estado: str | None = None, municipio: str | None = None, q: str | None = None,
                     precio_max=None, solo_activos: bool = False, limite: int = 200) -> list[dict]:
    cond_vis, p_vis = nucleo._visible_sql(usuario_id, supervisor, "x")
    donde, p = ["i.tenant_id = ?", "x.papelera_en IS NULL", cond_vis], [tenant_id, *p_vis]
    if operacion in OPERACIONES:
        donde.append("x.tipo = ?"); p.append(OPERACIONES[operacion])
    if estado:
        donde.append("x.estado = ?"); p.append(estado)
    if solo_activos:
        donde.append("x.estado NOT IN ('cerrada', 'perdida')")
    if municipio and municipio.strip():
        donde.append("plano(i.municipio) = ?"); p.append(nucleo.plano(municipio).strip())
    if q and q.strip():
        like = f"%{nucleo.plano(q.strip())}%"
        donde.append("(plano(i.direccion) LIKE ? OR plano(i.referencia) LIKE ? OR plano(c.nombre) LIKE ?)")
        p += [like] * 3
    maximo = _importe(precio_max)
    if maximo:
        donde.append("i.precio_centimos <= ?"); p.append(maximo)
    conn = nucleo._conn_con_busqueda()
    try:
        filas = conn.execute(
            "SELECT i.*, x.estado, x.tipo AS tipo_operacion, x.responsable_id, c.nombre AS propietario_nombre, c.id AS propietario_id, "
            "(SELECT COUNT(*) FROM inmobiliaria_visitas v WHERE v.inmueble_id = i.id AND v.estado = 'realizada') AS visitas_realizadas, "
            "(SELECT COUNT(*) FROM inmobiliaria_ofertas o WHERE o.inmueble_id = i.id AND o.estado IN ('pendiente', 'contraoferta')) AS ofertas_abiertas "
            "FROM inmobiliaria_inmuebles i JOIN expedientes x ON x.id = i.expediente_id JOIN clientes c ON c.id = x.cliente_id "
            f"WHERE {' AND '.join(donde)} ORDER BY i.creado_en DESC LIMIT ?", [*p, max(1, min(limite, 1000))]).fetchall()
    finally:
        conn.close()
    res = []
    for f in filas:
        d = _inmueble_dict(f)
        d["operacion"] = "venta" if f["tipo_operacion"] == TIPO_VENTA.id else "alquiler"
        d["estado_comercial"] = estado_comercial(d["operacion"], f["estado"])
        res.append(d)
    return res


def editar_inmueble(tenant_id: int, usuario_id: int, inmueble_id: int, supervisor: bool = False, **campos) -> None:
    i, x = _inmueble_o_error(tenant_id, usuario_id, inmueble_id, supervisor)
    sets, vals = [], []
    for c, largo in (("referencia", 40), ("direccion", 300), ("municipio", 100), ("codigo_postal", 10), ("ref_catastral", 30), ("planta", 20), ("descripcion", 5000), ("copropietarios", 500)):
        if c in campos:
            v = (campos[c] or "").strip()[:largo] or None
            if c == "direccion" and not v:
                raise ValueError("La dirección no puede quedar vacía.")
            sets.append(f"{c} = ?"); vals.append(v)
    if "tipo" in campos:
        if campos["tipo"] not in dict(TIPOS_INMUEBLE):
            raise ValueError("Tipo de inmueble no válido.")
        sets.append("tipo = ?"); vals.append(campos["tipo"])
    if "certificado_energetico" in campos:
        if campos["certificado_energetico"] and campos["certificado_energetico"] not in CERTIFICADOS:
            raise ValueError("Certificado energético no válido.")
        sets.append("certificado_energetico = ?"); vals.append(campos["certificado_energetico"] or None)
    for c, nombre, maximo in (("superficie_m2", "La superficie", 100000), ("habitaciones", "Las habitaciones", 100), ("banos", "Los baños", 100)):
        if c in campos:
            sets.append(f"{c} = ?"); vals.append(_entero(campos[c], nombre, maximo))
    if "caracteristicas" in campos:
        sets.append("caracteristicas = ?"); vals.append(json.dumps([c for c in _lista(campos["caracteristicas"]) if c in dict(CARACTERISTICAS)]))
    if not sets:
        return
    conn = db.get_connection()
    try:
        conn.execute(f"UPDATE inmobiliaria_inmuebles SET {', '.join(sets)} WHERE id = ?", [*vals, inmueble_id])
        nucleo._evento(conn, i["expediente_id"], "editado", "Datos del inmueble editados.", usuario_id)
        conn.commit()
    finally:
        conn.close()


def cambiar_precio(tenant_id: int, usuario_id: int, inmueble_id: int, precio, motivo: str | None = None, supervisor: bool = False) -> None:
    i, x = _inmueble_o_error(tenant_id, usuario_id, inmueble_id, supervisor)
    centimos = _importe(precio)
    if not centimos or centimos <= 0:
        raise ValueError("El precio debe ser mayor que cero.")
    if centimos == i["precio_centimos"]:
        return
    conn = db.get_connection()
    try:
        conn.execute("UPDATE inmobiliaria_inmuebles SET precio_centimos = ? WHERE id = ?", (centimos, inmueble_id))
        conn.execute("INSERT INTO inmobiliaria_precios (inmueble_id, precio_centimos, fecha, motivo, usuario_id) VALUES (?, ?, ?, ?, ?)", (inmueble_id, centimos, date.today().isoformat(), (motivo or "").strip()[:200] or None, usuario_id))
        antes = f"{i['precio_centimos'] / 100:.2f} € → " if i["precio_centimos"] else ""
        nucleo._evento(conn, i["expediente_id"], "precio", f"Precio: {antes}{centimos / 100:.2f} €.", usuario_id)
        conn.commit()
    finally:
        conn.close()


def historial_precios(inmueble_id: int) -> list:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT * FROM inmobiliaria_precios WHERE inmueble_id = ? ORDER BY fecha DESC, id DESC", (inmueble_id,)).fetchall()
    finally:
        conn.close()


# =============================================================================== Demandas y cruce
def _demanda_dict(f) -> dict:
    d = dict(f)
    for campo in ("tipos", "municipios", "requisitos"):
        try:
            d[campo] = json.loads(f[campo]) if f[campo] else []
        except (TypeError, ValueError):
            d[campo] = []
    return d


def crear_demanda(tenant_id: int, usuario_id: int, cliente_id: int, operacion: str, *, tipos=None, municipios=None, presupuesto_min=None, presupuesto_max=None, superficie_min=None,
                  habitaciones_min=None, banos_min=None, requisitos=None, notas: str | None = None, agente_id: int | None = None) -> int:
    if operacion not in OPERACIONES:
        raise ValueError("Elige si busca comprar o alquilar.")
    pmin, pmax = _importe(presupuesto_min), _importe(presupuesto_max)
    if pmin and pmax and pmin > pmax:
        raise ValueError("El presupuesto mínimo no puede ser mayor que el máximo.")
    ts = [t for t in _lista(tipos) if t in dict(TIPOS_INMUEBLE)]
    rs = [r for r in _lista(requisitos) if r in dict(CARACTERISTICAS)]
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM clientes WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_id, tenant_id)).fetchone() is None:
            raise ValueError("Cliente no encontrado.")
        nucleo._usuario_de_tenant(conn, agente_id, tenant_id, "El agente")
        cur = conn.execute(
            "INSERT INTO inmobiliaria_demandas (tenant_id, cliente_id, operacion, tipos, municipios, presupuesto_min_centimos, presupuesto_max_centimos, superficie_min, habitaciones_min, banos_min, requisitos, notas, agente_id, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, cliente_id, operacion, json.dumps(ts), json.dumps(_lista(municipios)), pmin, pmax, _entero(superficie_min, "La superficie"), _entero(habitaciones_min, "Las habitaciones", 100),
             _entero(banos_min, "Los baños", 100), json.dumps(rs), (notas or "").strip()[:2000] or None, agente_id or usuario_id, db.now_iso()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def obtener_demanda(tenant_id: int, demanda_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT d.*, c.nombre AS cliente_nombre, c.email AS cliente_email, c.telefono AS cliente_telefono FROM inmobiliaria_demandas d JOIN clientes c ON c.id = d.cliente_id WHERE d.id = ? AND d.tenant_id = ?", (demanda_id, tenant_id)).fetchone()
    finally:
        conn.close()
    return _demanda_dict(f) if f else None


def listar_demandas(tenant_id: int, *, estado: str | None = "activa", operacion: str | None = None, limite: int = 300) -> list[dict]:
    donde, p = ["d.tenant_id = ?"], [tenant_id]
    if estado:
        donde.append("d.estado = ?"); p.append(estado)
    if operacion in OPERACIONES:
        donde.append("d.operacion = ?"); p.append(operacion)
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT d.*, c.nombre AS cliente_nombre FROM inmobiliaria_demandas d JOIN clientes c ON c.id = d.cliente_id "
                             f"WHERE {' AND '.join(donde)} ORDER BY d.creado_en DESC LIMIT ?", [*p, max(1, min(limite, 1000))]).fetchall()
    finally:
        conn.close()
    return [_demanda_dict(f) for f in filas]


def cambiar_estado_demanda(tenant_id: int, demanda_id: int, estado: str) -> None:
    if estado not in dict(ESTADOS_DEMANDA):
        raise ValueError("Estado no válido.")
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE inmobiliaria_demandas SET estado = ?, actualizado_en = ? WHERE id = ? AND tenant_id = ?", (estado, db.now_iso(), demanda_id, tenant_id))
        if cur.rowcount == 0:
            raise ValueError("Demanda no encontrada.")
        conn.commit()
    finally:
        conn.close()


def cruces_para_inmueble(tenant_id: int, usuario_id: int, inmueble_id: int, supervisor: bool = False, minimo: int = 50) -> list[dict]:
    """Demandas activas de la misma operación que encajan con un inmueble en comercialización, de mayor a menor encaje."""
    i, x = obtener_inmueble(tenant_id, usuario_id, inmueble_id, supervisor)
    if i is None or x["estado"] not in EN_COMERCIALIZACION:
        return []
    res = []
    for d in listar_demandas(tenant_id, estado="activa", operacion=operacion_de(x)):
        c = puntuar(d, i)
        if c["puntos"] >= minimo:
            res.append({"demanda": d, **c})
    return sorted(res, key=lambda c: (-c["puntos"], c["demanda"]["id"]))


def cruces_para_demanda(tenant_id: int, usuario_id: int, demanda_id: int, supervisor: bool = False, minimo: int = 50) -> list[dict]:
    d = obtener_demanda(tenant_id, demanda_id)
    if d is None:
        return []
    res = []
    for i in listar_inmuebles(tenant_id, usuario_id, supervisor, operacion=d["operacion"]):
        if i["estado"] not in EN_COMERCIALIZACION:
            continue
        c = puntuar(d, i)
        if c["puntos"] >= minimo:
            res.append({"inmueble": i, **c})
    return sorted(res, key=lambda c: (-c["puntos"], c["inmueble"]["id"]))


# =============================================================================== Visitas y ofertas
def _fecha_hora(valor: str) -> str:
    try:
        return datetime.fromisoformat((valor or "").strip().replace(" ", "T")[:16]).isoformat(timespec="minutes")
    except ValueError:
        raise ValueError("La fecha y la hora de la visita no son válidas.") from None


def crear_visita(tenant_id: int, usuario_id: int, inmueble_id: int, fecha_hora: str, *, demanda_id: int | None = None, cliente_id: int | None = None, visitante: str | None = None,
                 agente_id: int | None = None, supervisor: bool = False, crear_tarea: bool = True) -> int:
    i, x = _inmueble_o_error(tenant_id, usuario_id, inmueble_id, supervisor)
    fh = _fecha_hora(fecha_hora)
    conn = db.get_connection()
    try:
        if demanda_id:
            d = conn.execute("SELECT cliente_id FROM inmobiliaria_demandas WHERE id = ? AND tenant_id = ?", (demanda_id, tenant_id)).fetchone()
            if d is None:
                raise ValueError("Demanda no encontrada.")
            cliente_id = cliente_id or d["cliente_id"]
        if cliente_id and conn.execute("SELECT 1 FROM clientes WHERE id = ? AND tenant_id = ?", (cliente_id, tenant_id)).fetchone() is None:
            raise ValueError("Cliente no encontrado.")
        if not cliente_id and not (visitante or "").strip():
            raise ValueError("Indica quién hace la visita.")
        nucleo._usuario_de_tenant(conn, agente_id, tenant_id, "El agente")
        agente = agente_id or usuario_id
        cur = conn.execute("INSERT INTO inmobiliaria_visitas (tenant_id, inmueble_id, demanda_id, cliente_id, visitante, fecha_hora, agente_id, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, inmueble_id, demanda_id, cliente_id, (visitante or "").strip()[:200] or None, fh, agente, db.now_iso()))
        nucleo._evento(conn, i["expediente_id"], "visita", f"Visita prevista el {fh.replace('T', ' ')}.", usuario_id)
        conn.commit()
        vid = cur.lastrowid
    finally:
        conn.close()
    if crear_tarea:
        try:
            db.crear_tarea_outlook(agente, f"Visita: {i['direccion']}", cuerpo=f"{fh.replace('T', ' ')} — {i['direccion']}", fecha_vencimiento=fh[:10], prioridad="normal")
        except Exception:  # noqa: BLE001 -- la tarea es un recordatorio extra: la visita ya está guardada
            pass
    return vid


def registrar_resultado_visita(tenant_id: int, usuario_id: int, visita_id: int, estado: str, valoracion=None, interes: str | None = None, comentario: str | None = None, supervisor: bool = False) -> None:
    if estado not in dict(ESTADOS_VISITA):
        raise ValueError("Estado no válido.")
    if interes and interes not in dict(INTERES):
        raise ValueError("Interés no válido.")
    val = None
    if valoracion not in (None, ""):
        try:
            val = int(valoracion)
        except (TypeError, ValueError):
            raise ValueError("La valoración debe ser de 1 a 5.") from None
        if not 1 <= val <= 5:
            raise ValueError("La valoración debe ser de 1 a 5.")
    v = _visita(tenant_id, usuario_id, visita_id, supervisor)
    conn = db.get_connection()
    try:
        conn.execute("UPDATE inmobiliaria_visitas SET estado = ?, valoracion = ?, interes = ?, comentario = ? WHERE id = ?", (estado, val, interes or None, (comentario or "").strip()[:1500] or None, visita_id))
        i = conn.execute("SELECT expediente_id FROM inmobiliaria_inmuebles WHERE id = ?", (v["inmueble_id"],)).fetchone()
        nucleo._evento(conn, i["expediente_id"], "visita", f"Visita del {v['fecha_hora'].replace('T', ' ')}: {verticales.original(dict(ESTADOS_VISITA)[estado])}.", usuario_id)
        conn.commit()
    finally:
        conn.close()


def _visita(tenant_id: int, usuario_id: int, visita_id: int, supervisor: bool):
    conn = db.get_connection()
    try:
        v = conn.execute("SELECT * FROM inmobiliaria_visitas WHERE id = ? AND tenant_id = ?", (visita_id, tenant_id)).fetchone()
    finally:
        conn.close()
    if v is None or obtener_inmueble(tenant_id, usuario_id, v["inmueble_id"], supervisor)[0] is None:
        raise ValueError("Visita no encontrada.")
    return v


def eliminar_visita(tenant_id: int, usuario_id: int, visita_id: int, supervisor: bool = False) -> None:
    _visita(tenant_id, usuario_id, visita_id, supervisor)
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM inmobiliaria_visitas WHERE id = ?", (visita_id,))
        conn.commit()
    finally:
        conn.close()


def listar_visitas(tenant_id: int, usuario_id: int, supervisor: bool = False, *, inmueble_id: int | None = None, desde: str | None = None, hasta: str | None = None, estado: str | None = None,
                   agente_id: int | None = None, limite: int = 300) -> list:
    cond_vis, p_vis = nucleo._visible_sql(usuario_id, supervisor, "x")
    donde, p = ["v.tenant_id = ?", "x.papelera_en IS NULL", cond_vis], [tenant_id, *p_vis]
    for col, val in (("v.inmueble_id", inmueble_id), ("v.estado", estado), ("v.agente_id", agente_id)):
        if val:
            donde.append(f"{col} = ?"); p.append(val)
    if desde:
        donde.append("v.fecha_hora >= ?"); p.append(desde)
    if hasta:
        donde.append("v.fecha_hora <= ?"); p.append(hasta + "T23:59" if len(hasta) == 10 else hasta)
    conn = db.get_connection()
    try:
        return conn.execute(
            "SELECT v.*, i.direccion, i.municipio, i.referencia, COALESCE(c.nombre, v.visitante) AS visitante_nombre, c.telefono AS visitante_telefono, COALESCE(p.nombre_mostrado, u.email) AS agente_nombre "
            "FROM inmobiliaria_visitas v JOIN inmobiliaria_inmuebles i ON i.id = v.inmueble_id JOIN expedientes x ON x.id = i.expediente_id LEFT JOIN clientes c ON c.id = v.cliente_id "
            "LEFT JOIN usuarios u ON u.id = v.agente_id LEFT JOIN usuario_perfil p ON p.usuario_id = v.agente_id "
            f"WHERE {' AND '.join(donde)} ORDER BY v.fecha_hora LIMIT ?", [*p, max(1, min(limite, 1000))]).fetchall()
    finally:
        conn.close()


def mapa_url(direccion: str, municipio: str | None = None) -> str:
    from urllib.parse import quote

    return "https://www.openstreetmap.org/search?query=" + quote(f"{direccion}, {municipio or ''}".strip(", "))


def registrar_oferta(tenant_id: int, usuario_id: int, inmueble_id: int, importe, *, demanda_id: int | None = None, cliente_id: int | None = None, oferente: str | None = None, fecha: str | None = None,
                     notas: str | None = None, supervisor: bool = False) -> int:
    i, x = _inmueble_o_error(tenant_id, usuario_id, inmueble_id, supervisor)
    centimos = _importe(importe)
    if not centimos or centimos <= 0:
        raise ValueError("El importe de la oferta debe ser mayor que cero.")
    fecha = nucleo._fecha_iso(fecha, "La fecha") if fecha else date.today().isoformat()
    conn = db.get_connection()
    try:
        if demanda_id:
            d = conn.execute("SELECT cliente_id FROM inmobiliaria_demandas WHERE id = ? AND tenant_id = ?", (demanda_id, tenant_id)).fetchone()
            if d is None:
                raise ValueError("Demanda no encontrada.")
            cliente_id = cliente_id or d["cliente_id"]
        if cliente_id and conn.execute("SELECT 1 FROM clientes WHERE id = ? AND tenant_id = ?", (cliente_id, tenant_id)).fetchone() is None:
            raise ValueError("Cliente no encontrado.")
        if not cliente_id and not (oferente or "").strip():
            raise ValueError("Indica quién hace la oferta.")
        cur = conn.execute("INSERT INTO inmobiliaria_ofertas (tenant_id, inmueble_id, demanda_id, cliente_id, oferente, importe_centimos, fecha, notas, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, inmueble_id, demanda_id, cliente_id, (oferente or "").strip()[:200] or None, centimos, fecha, (notas or "").strip()[:1000] or None, db.now_iso()))
        nucleo._evento(conn, i["expediente_id"], "oferta", f"Oferta recibida: {centimos / 100:.2f} €.", usuario_id)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def cambiar_estado_oferta(tenant_id: int, usuario_id: int, oferta_id: int, estado: str, supervisor: bool = False) -> None:
    if estado not in dict(ESTADOS_OFERTA):
        raise ValueError("Estado no válido.")
    conn = db.get_connection()
    try:
        o = conn.execute("SELECT * FROM inmobiliaria_ofertas WHERE id = ? AND tenant_id = ?", (oferta_id, tenant_id)).fetchone()
    finally:
        conn.close()
    if o is None:
        raise ValueError("Oferta no encontrada.")
    i, x = _inmueble_o_error(tenant_id, usuario_id, o["inmueble_id"], supervisor)
    conn = db.get_connection()
    try:
        conn.execute("UPDATE inmobiliaria_ofertas SET estado = ? WHERE id = ?", (estado, oferta_id))
        nucleo._evento(conn, i["expediente_id"], "oferta", f"Oferta de {o['importe_centimos'] / 100:.2f} €: {verticales.original(dict(ESTADOS_OFERTA)[estado])}.", usuario_id)
        conn.commit()
    finally:
        conn.close()


def listar_ofertas(tenant_id: int, usuario_id: int, supervisor: bool = False, *, inmueble_id: int | None = None, abiertas: bool = False, limite: int = 200) -> list:
    cond_vis, p_vis = nucleo._visible_sql(usuario_id, supervisor, "x")
    donde, p = ["o.tenant_id = ?", "x.papelera_en IS NULL", cond_vis], [tenant_id, *p_vis]
    if inmueble_id:
        donde.append("o.inmueble_id = ?"); p.append(inmueble_id)
    if abiertas:
        donde.append("o.estado IN ('pendiente', 'contraoferta')")
    conn = db.get_connection()
    try:
        return conn.execute("SELECT o.*, i.direccion, i.referencia, COALESCE(c.nombre, o.oferente) AS oferente_nombre FROM inmobiliaria_ofertas o JOIN inmobiliaria_inmuebles i ON i.id = o.inmueble_id "
                            "JOIN expedientes x ON x.id = i.expediente_id LEFT JOIN clientes c ON c.id = o.cliente_id "
                            f"WHERE {' AND '.join(donde)} ORDER BY o.fecha DESC, o.id DESC LIMIT ?", [*p, max(1, min(limite, 1000))]).fetchall()
    finally:
        conn.close()


# =============================================================================== Contratos
def _eur(c) -> str:
    return f"{c / 100:,.2f} €".replace(",", "§").replace(".", ",").replace("§", ".") if c is not None else "—"


def generar_contrato(tenant_id: int, usuario_id: int, inmueble_id: int, tipo: str, *, parte_nombre: str, parte_nif: str | None = None, precio=None, arras=None, renta=None, fianza=None,
                     duracion: str | None = None, comision: str | None = None, supervisor: bool = False) -> int:
    """Genera un contrato desde la plantilla de la agencia con los datos del inmueble y de las partes, lo guarda como documento de la operación (categoría «Contrato») y registra
    una **nueva versión** (las anteriores se conservan). Devuelve el id del contrato."""
    if tipo not in dict(TIPOS_CONTRATO):
        raise ValueError("Tipo de contrato no válido.")
    i, x = _inmueble_o_error(tenant_id, usuario_id, inmueble_id, supervisor)
    if not (parte_nombre or "").strip():
        raise ValueError("Indica el nombre de la otra parte.")
    prop = nucleo.obtener_cliente(tenant_id, x["cliente_id"])
    ajustes = obtener_ajustes(tenant_id)
    agencia = (db.obtener_tenant(tenant_id) or {"nombre": ""})["nombre"]
    p_c = _importe(precio) if precio not in (None, "") else i["precio_centimos"]
    valores = {
        "{fecha}": date.today().strftime("%d/%m/%Y"), "{agencia}": agencia, "{propietario}": prop["nombre"], "{nif_propietario}": prop["nif"] or "—", "{parte}": parte_nombre.strip(),
        "{nif_parte}": (parte_nif or "").strip() or "—", "{inmueble}": verticales.original(dict(TIPOS_INMUEBLE)[i["tipo"]]), "{direccion}": i["direccion"] + (f", {i['municipio']}" if i["municipio"] else ""),
        "{ref_catastral}": i["ref_catastral"] or "—", "{precio}": _eur(p_c), "{arras}": _eur(_importe(arras)) if arras not in (None, "") else "—", "{renta}": _eur(_importe(renta)) if renta not in (None, "") else "—",
        "{fianza}": _eur(_importe(fianza)) if fianza not in (None, "") else "—", "{duracion}": (duracion or "").strip() or "a determinar", "{comision}": (comision or "").strip() or "los pactados",
    }
    texto = ajustes["plantillas"][tipo]
    for k, v in valores.items():
        texto = texto.replace(k, v)
    etiqueta = verticales.original(dict(TIPOS_CONTRATO)[tipo])
    pdf = generador_documentos.texto_a_pdf(etiqueta, texto, notas=f"{i['direccion']} — modelo de ejemplo, sin validar")
    conn = db.get_connection()
    try:
        version = (conn.execute("SELECT COALESCE(MAX(version), 0) FROM inmobiliaria_contratos WHERE inmueble_id = ? AND tipo = ?", (inmueble_id, tipo)).fetchone()[0]) + 1
    finally:
        conn.close()
    r, did = almacen_documentos.guardar(usuario_id, f"{tipo}_{i['referencia'] or i['id']}_v{version}.pdf", "application/pdf", pdf, expediente_id=i["expediente_id"], categoria=f"Contrato: {etiqueta}", origen="generado")
    if r not in ("ok", "duplicado"):
        raise ValueError("No se pudo guardar el contrato.")
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO inmobiliaria_contratos (tenant_id, inmueble_id, tipo, version, documento_id, parte_nombre, parte_nif, datos, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, inmueble_id, tipo, version, did, parte_nombre.strip()[:200], (parte_nif or "").strip()[:30] or None, json.dumps({k.strip("{}"): v for k, v in valores.items()}, ensure_ascii=False), usuario_id, db.now_iso()))
        nucleo._evento(conn, i["expediente_id"], "contrato", f"{etiqueta} generado (versión {version}).", usuario_id)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_contratos(tenant_id: int, usuario_id: int, inmueble_id: int, supervisor: bool = False) -> list:
    if obtener_inmueble(tenant_id, usuario_id, inmueble_id, supervisor)[0] is None:
        return []
    conn = db.get_connection()
    try:
        return conn.execute("SELECT * FROM inmobiliaria_contratos WHERE tenant_id = ? AND inmueble_id = ? ORDER BY tipo, version DESC", (tenant_id, inmueble_id)).fetchall()
    finally:
        conn.close()


def _contrato(tenant_id: int, usuario_id: int, contrato_id: int, supervisor: bool):
    conn = db.get_connection()
    try:
        c = conn.execute("SELECT * FROM inmobiliaria_contratos WHERE id = ? AND tenant_id = ?", (contrato_id, tenant_id)).fetchone()
    finally:
        conn.close()
    if c is None or obtener_inmueble(tenant_id, usuario_id, c["inmueble_id"], supervisor)[0] is None:
        raise ValueError("Contrato no encontrado.")
    return c


def enviar_contrato_a_firma(tenant_id: int, usuario_id: int, contrato_id: int, email: str, nombre: str, supervisor: bool = False) -> str:
    c = _contrato(tenant_id, usuario_id, contrato_id, supervisor)
    ident = firma_documentos.enviar(tenant_id, usuario_id, c["documento_id"], email, nombre, lambda expediente_id: None)
    conn = db.get_connection()
    try:
        conn.execute("UPDATE inmobiliaria_contratos SET estado = 'enviado_firma' WHERE id = ?", (contrato_id,))
        conn.commit()
    finally:
        conn.close()
    return ident


def marcar_contrato_firmado(tenant_id: int, usuario_id: int, contrato_id: int, supervisor: bool = False) -> None:
    c = _contrato(tenant_id, usuario_id, contrato_id, supervisor)
    i, x = obtener_inmueble(tenant_id, usuario_id, c["inmueble_id"], supervisor)
    conn = db.get_connection()
    try:
        conn.execute("UPDATE inmobiliaria_contratos SET estado = 'firmado' WHERE id = ?", (contrato_id,))
        nucleo._evento(conn, i["expediente_id"], "contrato", f"{verticales.original(dict(TIPOS_CONTRATO)[c['tipo']])} (versión {c['version']}) firmado.", usuario_id)
        conn.commit()
    finally:
        conn.close()


# =============================================================================== Comisiones
def proponer_comision(tenant_id: int, usuario_id: int, inmueble_id: int, supervisor: bool = False) -> dict:
    """Comisión sugerida con los ajustes de la agencia: en venta, un porcentaje del precio; en alquiler, tantas mensualidades como se hayan configurado (la base es la renta mensual)."""
    i, x = _inmueble_o_error(tenant_id, usuario_id, inmueble_id, supervisor)
    a = obtener_ajustes(tenant_id)
    base = i["precio_centimos"] or 0
    pct_bp = a["comision_venta_bp"] if operacion_de(x) == "venta" else a["comision_alquiler_meses_x100"] * 100
    return {"base_centimos": base, "pct_bp": pct_bp, "minimo_centimos": a["minimo_centimos"], "iva_pct": a["iva_pct"], **calcular_comision(base, pct_bp, a["minimo_centimos"], a["iva_pct"])}


def guardar_comision(tenant_id: int, usuario_id: int, inmueble_id: int, base, pct_bp, minimo, iva_pct, reparto: list[tuple[int, int]], supervisor: bool = False) -> dict:
    i, x = _inmueble_o_error(tenant_id, usuario_id, inmueble_id, supervisor)
    b = _importe(base)
    if not b or b <= 0:
        raise ValueError("La base de la comisión debe ser mayor que cero.")
    try:
        bp, iva = int(pct_bp), int(iva_pct)
    except (TypeError, ValueError):
        raise ValueError("El porcentaje y el IVA deben ser números.") from None
    if not (0 <= bp <= 100000 and 0 <= iva <= 30):
        raise ValueError("Porcentaje o IVA fuera de rango.")
    minimo_c = _importe(minimo) or 0
    c = calcular_comision(b, bp, minimo_c, iva)
    conn = db.get_connection()
    try:
        for agente, _p in reparto:
            nucleo._usuario_de_tenant(conn, agente, tenant_id, "Una de las personas del reparto")
        partes = repartir(c["honorarios"], reparto)         # lanza ValueError si no suma 100
        existe = conn.execute("SELECT id FROM inmobiliaria_comisiones WHERE inmueble_id = ?", (inmueble_id,)).fetchone()
        datos = (b, bp, minimo_c, iva, c["honorarios"], c["iva"], c["total"], json.dumps([{"agente_id": a, "pct": p, "centimos": cant} for (a, p), (_a, cant) in zip(reparto, partes)]))
        if existe:
            conn.execute("UPDATE inmobiliaria_comisiones SET base_centimos = ?, pct_bp = ?, minimo_centimos = ?, iva_pct = ?, honorarios_centimos = ?, iva_centimos = ?, total_centimos = ?, reparto = ?, actualizado_en = ? WHERE id = ?", (*datos, db.now_iso(), existe["id"]))
        else:
            conn.execute("INSERT INTO inmobiliaria_comisiones (tenant_id, inmueble_id, base_centimos, pct_bp, minimo_centimos, iva_pct, honorarios_centimos, iva_centimos, total_centimos, reparto, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (tenant_id, inmueble_id, *datos, db.now_iso()))
        nucleo._evento(conn, i["expediente_id"], "comision", f"Comisión calculada: {c['total'] / 100:.2f} € con IVA.", usuario_id)
        conn.commit()
    finally:
        conn.close()
    return obtener_comision(tenant_id, inmueble_id)


def obtener_comision(tenant_id: int, inmueble_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM inmobiliaria_comisiones WHERE tenant_id = ? AND inmueble_id = ?", (tenant_id, inmueble_id)).fetchone()
    finally:
        conn.close()
    if f is None:
        return None
    d = dict(f)
    d["reparto"] = json.loads(f["reparto"]) if f["reparto"] else []
    return d


def cambiar_estado_comision(tenant_id: int, usuario_id: int, inmueble_id: int, estado: str, supervisor: bool = False) -> None:
    if estado not in dict(ESTADOS_COMISION):
        raise ValueError("Estado no válido.")
    _inmueble_o_error(tenant_id, usuario_id, inmueble_id, supervisor)
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE inmobiliaria_comisiones SET estado = ?, actualizado_en = ? WHERE tenant_id = ? AND inmueble_id = ?", (estado, db.now_iso(), tenant_id, inmueble_id))
        if cur.rowcount == 0:
            raise ValueError("Calcula antes la comisión.")
        conn.commit()
    finally:
        conn.close()


# =============================================================================== Fotos
MAX_FOTOS = 30
LADO_MAXIMO_FOTO = 1600


def subir_foto(tenant_id: int, usuario_id: int, inmueble_id: int, nombre: str, contenido: bytes, supervisor: bool = False) -> int:
    """Guarda una foto del inmueble: comprueba que es una imagen de verdad, la reduce a 1600 px, la guarda como JPEG y **elimina los datos EXIF** (incluida la ubicación GPS
    de quien la hizo)."""
    from PIL import Image, ImageOps

    i, x = _inmueble_o_error(tenant_id, usuario_id, inmueble_id, supervisor)
    if sum(1 for d in almacen_documentos.listar(tenant_id, usuario_id, expediente_id=i["expediente_id"]) if d["categoria"] == "Foto") >= MAX_FOTOS:
        raise ValueError(f"Máximo {MAX_FOTOS} fotos por inmueble.")
    try:
        imagen = Image.open(io.BytesIO(contenido))
        imagen.load()
        imagen = ImageOps.exif_transpose(imagen).convert("RGB")
    except Exception:  # noqa: BLE001 -- cualquier cosa que no sea una imagen legible
        raise ValueError("El archivo no es una imagen válida.") from None
    imagen.thumbnail((LADO_MAXIMO_FOTO, LADO_MAXIMO_FOTO))
    salida = io.BytesIO()
    imagen.save(salida, format="JPEG", quality=85, optimize=True)            # sin exif=...: no se copia ningún metadato
    base = (nombre or "foto").rsplit(".", 1)[0][:60] or "foto"
    r, did = almacen_documentos.guardar(usuario_id, base + ".jpg", "image/jpeg", salida.getvalue(), expediente_id=i["expediente_id"], categoria="Foto")
    if r not in ("ok", "duplicado"):
        raise ValueError("No se pudo guardar la foto.")
    return did


def fotos(tenant_id: int, usuario_id: int, inmueble_id: int, supervisor: bool = False) -> list[dict]:
    i, x = obtener_inmueble(tenant_id, usuario_id, inmueble_id, supervisor)
    if i is None:
        return []
    return sorted((d for d in almacen_documentos.listar(tenant_id, usuario_id, expediente_id=i["expediente_id"]) if d["categoria"] == "Foto"), key=lambda d: d["id"])


# =============================================================================== Panel, informes, publicación
def resumen(tenant_id: int, usuario_id: int, supervisor: bool = False) -> dict:
    inmuebles = listar_inmuebles(tenant_id, usuario_id, supervisor, solo_activos=True, limite=1000)
    por_estado: dict[str, int] = {}
    for i in inmuebles:
        por_estado[i["estado"]] = por_estado.get(i["estado"], 0) + 1
    hoy = date.today()
    hace14 = (datetime.now() - timedelta(days=14)).isoformat(timespec="minutes")
    sin_movimiento = []
    for i in inmuebles:
        if i["estado"] in EN_COMERCIALIZACION:
            conn = db.get_connection()
            try:
                hay = conn.execute("SELECT 1 FROM inmobiliaria_visitas WHERE inmueble_id = ? AND fecha_hora >= ? LIMIT 1", (i["id"], hace14)).fetchone() or \
                    conn.execute("SELECT 1 FROM inmobiliaria_ofertas WHERE inmueble_id = ? AND creado_en >= ? LIMIT 1", (i["id"], hace14)).fetchone()
            finally:
                conn.close()
            if not hay:
                sin_movimiento.append(i)
    return {
        "por_estado": por_estado, "n_activos": len(inmuebles), "sin_movimiento": sin_movimiento[:10],
        "visitas_hoy": listar_visitas(tenant_id, usuario_id, supervisor, desde=hoy.isoformat(), hasta=hoy.isoformat(), estado="prevista"),
        "visitas_semana": listar_visitas(tenant_id, usuario_id, supervisor, desde=hoy.isoformat(), hasta=(hoy + timedelta(days=7)).isoformat(), estado="prevista"),
        "ofertas": listar_ofertas(tenant_id, usuario_id, supervisor, abiertas=True, limite=10), "demandas": len(listar_demandas(tenant_id, estado="activa")),
    }


ESTADO_EN_LLANO = {
    "contacto": _l("Estamos empezando a preparar la venta o el alquiler de su inmueble."), "valoracion": _l("Estamos valorando su inmueble para proponerle un precio."),
    "mandato": _l("Tenemos su encargo firmado y preparamos la comercialización."), "publicado": _l("Su inmueble está anunciado."), "visitas": _l("Su inmueble se está enseñando a interesados."),
    "oferta": _l("Hemos recibido ofertas y estamos negociando."), "reserva": _l("Su inmueble está reservado."), "cerrada": _l("La operación se ha cerrado."), "perdida": _l("La operación se ha dado por terminada."),
}


def informe_propietario(tenant_id: int, inmueble_id: int, desde: str, hasta: str) -> dict:
    """Datos del informe de un periodo para el propietario: visitas realizadas (con valoración y comentario, SIN el nombre del visitante), ofertas (SIN el nombre del oferente) y precios."""
    conn = db.get_connection()
    try:
        i = conn.execute("SELECT * FROM inmobiliaria_inmuebles WHERE id = ? AND tenant_id = ?", (inmueble_id, tenant_id)).fetchone()
        visitas = conn.execute("SELECT fecha_hora, valoracion, interes, comentario FROM inmobiliaria_visitas WHERE inmueble_id = ? AND estado = 'realizada' AND substr(fecha_hora, 1, 10) BETWEEN ? AND ? ORDER BY fecha_hora", (inmueble_id, desde, hasta)).fetchall()
        ofertas = conn.execute("SELECT fecha, importe_centimos, estado FROM inmobiliaria_ofertas WHERE inmueble_id = ? AND fecha BETWEEN ? AND ? ORDER BY fecha", (inmueble_id, desde, hasta)).fetchall()
        precios = conn.execute("SELECT fecha, precio_centimos, motivo FROM inmobiliaria_precios WHERE inmueble_id = ? AND fecha BETWEEN ? AND ? ORDER BY fecha", (inmueble_id, desde, hasta)).fetchall()
    finally:
        conn.close()
    if i is None:
        raise ValueError("Inmueble no encontrado.")
    vals = [v["valoracion"] for v in visitas if v["valoracion"]]
    return {"inmueble": dict(i), "desde": desde, "hasta": hasta, "visitas": [dict(v) for v in visitas], "ofertas": [dict(o) for o in ofertas], "precios": [dict(p) for p in precios],
            "valoracion_media": round(sum(vals) / len(vals), 1) if vals else None}


def informe_a_pdf(tenant_id: int, inmueble_id: int, desde: str, hasta: str) -> bytes:
    d = informe_propietario(tenant_id, inmueble_id, desde, hasta)
    agencia = (db.obtener_tenant(tenant_id) or {"nombre": ""})["nombre"]
    filas = [[v["fecha_hora"].replace("T", " "), "Visita realizada", (f"Valoración {v['valoracion']}/5. " if v["valoracion"] else "") + (v["comentario"] or "")] for v in d["visitas"]]
    filas += [[o["fecha"], "Oferta recibida", f"{_eur(o['importe_centimos'])} ({o['estado']})"] for o in d["ofertas"]]
    filas += [[p["fecha"], "Cambio de precio", f"{_eur(p['precio_centimos'])} {p['motivo'] or ''}".strip()] for p in d["precios"]]
    filas.sort(key=lambda f: f[0])
    resumen_txt = f"{agencia} · {d['inmueble']['direccion']} · {desde} a {hasta} · {len(d['visitas'])} visitas" + (f" (valoración media {d['valoracion_media']}/5)" if d["valoracion_media"] else "") + f" · {len(d['ofertas'])} ofertas"
    return generador_documentos.tabla_a_pdf("Informe para el propietario", ["Fecha", "Qué ha pasado", "Detalle"], filas or [["", "Sin movimientos en el periodo", ""]], notas=resumen_txt)


def crear_enlace(tenant_id: int, usuario_id: int, inmueble_id: int, dias: int = 30, supervisor: bool = False, permite_mensajes: bool = False) -> str:
    i, x = _inmueble_o_error(tenant_id, usuario_id, inmueble_id, supervisor)
    return enlaces_publicos.crear(ID, tenant_id, usuario_id, x["id"], dias, permite_mensajes)


def datos_propietario(token: str) -> dict | None:
    """Lo que ve el propietario con su enlace: su inmueble, en qué fase va, el precio, un resumen de visitas y ofertas SIN datos personales de los interesados, el historial de
    precios y los documentos que la agencia haya compartido. Nada de comisiones, notas internas, horas ni otras demandas."""
    r = enlaces_publicos.resolver(ID, token)
    if r is None:
        return None
    x, tenant_id = r["expediente"], r["enlace"]["tenant_id"]
    conn = db.get_connection()
    try:
        i = conn.execute("SELECT * FROM inmobiliaria_inmuebles WHERE expediente_id = ?", (x["id"],)).fetchone()
        if i is None:
            return None
        hoy = date.today()
        mes_ini = hoy.replace(day=1).isoformat()
        realizadas = conn.execute("SELECT valoracion, comentario, fecha_hora FROM inmobiliaria_visitas WHERE inmueble_id = ? AND estado = 'realizada' ORDER BY fecha_hora DESC", (i["id"],)).fetchall()
        proximas = conn.execute("SELECT fecha_hora FROM inmobiliaria_visitas WHERE inmueble_id = ? AND estado = 'prevista' AND fecha_hora >= ? ORDER BY fecha_hora LIMIT 5", (i["id"], datetime.now().isoformat(timespec="minutes"))).fetchall()
        ofertas = conn.execute("SELECT fecha, importe_centimos, estado FROM inmobiliaria_ofertas WHERE inmueble_id = ? ORDER BY fecha DESC", (i["id"],)).fetchall()
        precios = conn.execute("SELECT fecha, precio_centimos FROM inmobiliaria_precios WHERE inmueble_id = ? ORDER BY fecha DESC, id DESC", (i["id"],)).fetchall()
        docs = almacen_documentos.compartidos_de_expediente(tenant_id, x["id"])
    finally:
        conn.close()
    vals = [v["valoracion"] for v in realizadas if v["valoracion"]]
    return {
        "agencia": (db.obtener_tenant(tenant_id) or {"nombre": ""})["nombre"], "propietario": x["cliente_nombre"], "direccion": i["direccion"], "municipio": i["municipio"], "referencia": i["referencia"],
        "precio_centimos": i["precio_centimos"], "estado_id": x["estado"], "operacion": "venta" if x["tipo"] == TIPO_VENTA.id else "alquiler", "visitas_total": len(realizadas),
        "visitas_mes": sum(1 for v in realizadas if v["fecha_hora"][:10] >= mes_ini), "valoracion_media": round(sum(vals) / len(vals), 1) if vals else None,
        "comentarios": [{"fecha": v["fecha_hora"][:10], "valoracion": v["valoracion"], "comentario": v["comentario"]} for v in realizadas if v["comentario"]][:10],
        "proximas": [v["fecha_hora"] for v in proximas], "ofertas": [dict(o) for o in ofertas], "precios": [dict(p) for p in precios], "documentos": [dict(d) for d in docs],
        "inmueble_id": i["id"], "tenant_id": tenant_id, "actualizado": x["actualizado_en"] or x["creado_en"], **mensajes_enlace.para_pagina_publica(ID, r),
    }


def informe_publico_pdf(token: str) -> bytes | None:
    d = datos_propietario(token)
    if d is None:
        return None
    hoy = date.today()
    return informe_a_pdf(d["tenant_id"], d["inmueble_id"], hoy.replace(day=1).isoformat(), hoy.isoformat())


def documento_publico(token: str, documento_id: int) -> dict | None:
    r = enlaces_publicos.resolver(ID, token)
    if r is None:
        return None
    conn = db.get_connection()
    try:
        ok = conn.execute("SELECT 1 FROM documentos WHERE id = ? AND expediente_id = ? AND compartido_cliente = 1 AND papelera_en IS NULL", (documento_id, r["expediente"]["id"])).fetchone()
    finally:
        conn.close()
    return almacen_documentos.leer_sin_usuario(r["enlace"]["tenant_id"], documento_id) if ok else None


def feed_publicacion(tenant_id: int, usuario_id: int, supervisor: bool = False) -> list[dict]:
    """Inmuebles en comercialización listos para exportar a portales: sin la calle exacta ni el propietario (solo municipio y código postal), con precio, características y descripción."""
    res = []
    for i in listar_inmuebles(tenant_id, usuario_id, supervisor, solo_activos=True, limite=1000):
        if i["estado"] not in EN_COMERCIALIZACION:
            continue
        res.append({"referencia": i["referencia"], "operacion": i["operacion"], "tipo": i["tipo"], "municipio": i["municipio"], "codigo_postal": i["codigo_postal"], "precio_eur": (i["precio_centimos"] or 0) / 100,
                    "superficie_m2": i["superficie_m2"], "habitaciones": i["habitaciones"], "banos": i["banos"], "planta": i["planta"], "certificado_energetico": i["certificado_energetico"],
                    "caracteristicas": i["caracteristicas"], "descripcion": i["descripcion"]})
    return res


def feed_a_csv(feed: list[dict]) -> str:
    import csv

    salida = io.StringIO()
    cols = ["referencia", "operacion", "tipo", "municipio", "codigo_postal", "precio_eur", "superficie_m2", "habitaciones", "banos", "planta", "certificado_energetico", "caracteristicas", "descripcion"]
    w = csv.writer(salida, delimiter=";")
    w.writerow(cols)
    for f in feed:
        fila = [("|".join(v) if isinstance(v, list) else v) for v in (f[c] for c in cols)]
        w.writerow([("'" + str(c)) if isinstance(c, str) and c[:1] in ("=", "+", "-", "@") else ("" if c is None else c) for c in fila])
    return "﻿" + salida.getvalue()


# =============================================================================== Panel de la ficha y registro del módulo
def contexto_panel(tenant_id: int, usuario_id: int, supervisor: bool, exp) -> dict:
    i, x = inmueble_de_expediente(tenant_id, usuario_id, exp["id"], supervisor)
    if i is None:
        return {"inmueble": None}
    return {
        "inmueble": i, "operacion": operacion_de(exp), "estado_comercial": estado_comercial(operacion_de(exp), exp["estado"]), "precios": historial_precios(i["id"]),
        "visitas": listar_visitas(tenant_id, usuario_id, supervisor, inmueble_id=i["id"]), "ofertas": listar_ofertas(tenant_id, usuario_id, supervisor, inmueble_id=i["id"]),
        "cruces": cruces_para_inmueble(tenant_id, usuario_id, i["id"], supervisor)[:8], "contratos": listar_contratos(tenant_id, usuario_id, i["id"], supervisor),
        "comision": obtener_comision(tenant_id, i["id"]), "propuesta_comision": proponer_comision(tenant_id, usuario_id, i["id"], supervisor), "fotos": fotos(tenant_id, usuario_id, i["id"], supervisor),
        "enlaces": enlaces_publicos.listar(ID, tenant_id, exp["id"]), "mensajes": mensajes_enlace.contexto_panel(ID, tenant_id, exp["id"]), "ajustes": obtener_ajustes(tenant_id), "tipos_inmueble": TIPOS_INMUEBLE, "caracteristicas": CARACTERISTICAS, "certificados": CERTIFICADOS,
        "estados_visita": ESTADOS_VISITA, "interes": INTERES, "estados_oferta": ESTADOS_OFERTA, "tipos_contrato": TIPOS_CONTRATO, "estados_comision": ESTADOS_COMISION,
        "estado_llano": ESTADO_EN_LLANO.get(exp["estado"], ""), "demandas_activas": listar_demandas(tenant_id, estado="activa", operacion=operacion_de(exp)), "equipo": nucleo.equipo(tenant_id),
        "mapa": mapa_url(i["direccion"], i["municipio"]),
    }


def _registrar() -> None:
    base = verticales.VERTICALES[ID]
    verticales.registrar(replace(
        base, disponible=True, tipos_expediente=(TIPO_VENTA, TIPO_ALQUILER), esquema=crear_esquema, borrar_datos=borrar_datos_de_tenant,
        entradas_menu=(verticales.EntradaMenu("inmobiliaria", _l("Inmobiliaria"), "inmobiliaria.panel", "building-2"),),
        panel_expediente="inmobiliaria/_panel_expediente.html", tipos_con_panel=TIPOS, contexto_expediente=contexto_panel,
    ))


_registrar()
