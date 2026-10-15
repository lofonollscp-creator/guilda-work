"""Módulo de negocio «Gabinete de abogados»: procedimientos judiciales y asuntos extrajudiciales con sus partes, notificaciones que generan plazos
procesales, vistas, provisión de fondos, minutas, hoja de encargo y un enlace de solo lectura para el cliente. Cuelga del núcleo común (`app/nucleo.py`):
sus asuntos son expedientes de dos tipos propios, y los plazos, las horas y los documentos son los de siempre.

**Todo lo normativo es de ejemplo y está SIN VALIDAR** (días de los plazos típicos, IVA y retención de las minutas, calendario procesal, texto de la hoja de
encargo): son valores editables por despacho y la interfaz lo dice. Una herramienta ayuda, no sustituye la comprobación de cada plazo con la norma vigente."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta

from flask_babel import lazy_gettext as _l

from . import almacen_documentos, calendario_plazos as cp, db, enlaces_publicos, firma_documentos, generador_documentos, nucleo, verticales
from .verticales import Estado, TipoExpediente

ID = "abogados"

TIPO_JUDICIAL = TipoExpediente(
    "procedimiento_judicial", _l("Procedimiento judicial"),
    (Estado("preparacion", _l("En preparación")), Estado("tramite", _l("En trámite")), Estado("pendiente_vista", _l("Pendiente de vista")),
     Estado("pendiente_sentencia", _l("Pendiente de sentencia")), Estado("recurso", _l("En recurso")), Estado("ejecucion", _l("En ejecución")),
     Estado("archivado", _l("Archivado"), True)),
    calendario="procesal",
)
TIPO_EXTRAJUDICIAL = TipoExpediente(
    "asunto_extrajudicial", _l("Asunto extrajudicial"),
    (Estado("abierto", _l("Abierto")), Estado("negociacion", _l("En negociación")), Estado("pendiente_cliente", _l("Pendiente del cliente")), Estado("cerrado", _l("Cerrado"), True)),
)
TIPOS = (TIPO_JUDICIAL.id, TIPO_EXTRAJUDICIAL.id)

JURISDICCIONES = (("civil", _l("Civil")), ("penal", _l("Penal")), ("contencioso", _l("Contencioso-administrativo")), ("social", _l("Social")),
                  ("mercantil", _l("Mercantil")), ("familia", _l("Familia")), ("otra", _l("Otra")))
ROLES_PARTE = (("cliente", _l("Cliente")), ("contraparte", _l("Contraparte")), ("letrado_contrario", _l("Letrado contrario")), ("procurador_contrario", _l("Procurador contrario")),
               ("tercero", _l("Tercero")), ("perito", _l("Perito")), ("testigo", _l("Testigo")))
ROLES_CONTRARIOS = ("contraparte", "letrado_contrario", "procurador_contrario")
TIPOS_VISTA = (("vista", _l("Vista")), ("juicio", _l("Juicio")), ("comparecencia", _l("Comparecencia")), ("declaracion", _l("Declaración")), ("mediacion", _l("Mediación")),
               ("otra", _l("Otra")))
RESOLUCIONES = (("providencia", _l("Providencia")), ("auto", _l("Auto")), ("decreto", _l("Decreto")), ("sentencia", _l("Sentencia")), ("diligencia", _l("Diligencia de ordenación")),
                ("requerimiento", _l("Requerimiento")), ("otra", _l("Otra")))
# Plazos típicos, ORIENTATIVOS y SIN VALIDAR: (id, texto, días hábiles). Se muestran como atajos y se pueden cambiar a mano.
PLAZOS_TIPICOS = (("contestacion", _l("Contestación a la demanda (juicio ordinario)"), 20), ("apelacion", _l("Recurso de apelación"), 20), ("reposicion", _l("Recurso de reposición"), 5))

MOVIMIENTOS = (("provision", _l("Provisión de fondos")), ("suplido", _l("Suplido (gasto pagado por cuenta del cliente)")), ("honorarios", _l("Cargo de honorarios")),
               ("devolucion", _l("Devolución al cliente")))
AJUSTES_POR_DEFECTO = {"serie": "M", "iva_pct": 21, "irpf_pct": 15, "bloque_minutos": 6, "provision_minima_centimos": 0}

HOJA_DE_ENCARGO_POR_DEFECTO = """HOJA DE ENCARGO PROFESIONAL (modelo de ejemplo, sin validar)

En {fecha}.

{despacho} ("el Despacho") y {cliente}, con NIF {nif} ("el Cliente"), acuerdan:

1. Objeto. El Despacho se encargará de la defensa y asesoramiento del Cliente en el asunto: {asunto}.

2. Honorarios. Los honorarios se calcularán según la tarifa horaria pactada ({tarifa}), más los impuestos aplicables. Los gastos y suplidos (tasas, procurador, peritos, desplazamientos) se facturarán aparte.

3. Provisión de fondos. El Cliente entregará una provisión de fondos para atender los gastos del asunto; el Despacho podrá compensar con ella las minutas emitidas.

4. Información y documentación. El Cliente facilitará toda la documentación necesaria y será informado de la marcha del asunto. El Despacho mantendrá el secreto profesional.

5. Protección de datos. Los datos personales se tratarán únicamente para prestar este servicio, conforme a la normativa vigente.

Y en prueba de conformidad, firman ambas partes.
"""

ESQUEMA = """
CREATE TABLE IF NOT EXISTS abogados_ajustes (
    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id),
    serie TEXT NOT NULL DEFAULT 'M',
    iva_pct INTEGER NOT NULL DEFAULT 21,
    irpf_pct INTEGER NOT NULL DEFAULT 15,
    bloque_minutos INTEGER NOT NULL DEFAULT 6,
    provision_minima_centimos INTEGER NOT NULL DEFAULT 0,
    plantilla_encargo TEXT
);

CREATE TABLE IF NOT EXISTS abogados_partes (
    id INTEGER PRIMARY KEY,
    expediente_id INTEGER NOT NULL REFERENCES expedientes(id) ON DELETE CASCADE,
    rol TEXT NOT NULL,
    nombre TEXT NOT NULL,
    nif TEXT,
    notas TEXT,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_abogados_partes_expediente ON abogados_partes(expediente_id);

CREATE TABLE IF NOT EXISTS abogados_vistas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    expediente_id INTEGER NOT NULL REFERENCES expedientes(id) ON DELETE CASCADE,
    fecha_hora TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'vista',
    lugar TEXT,
    notas TEXT,
    estado TEXT NOT NULL DEFAULT 'prevista' CHECK (estado IN ('prevista', 'celebrada', 'suspendida')),
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_abogados_vistas ON abogados_vistas(tenant_id, estado, fecha_hora);

CREATE TABLE IF NOT EXISTS abogados_fondos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    expediente_id INTEGER NOT NULL REFERENCES expedientes(id) ON DELETE CASCADE,
    fecha TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('provision', 'suplido', 'honorarios', 'devolucion')),
    importe_centimos INTEGER NOT NULL CHECK (importe_centimos > 0),
    concepto TEXT NOT NULL,
    minuta_id INTEGER,
    facturado_en TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_abogados_fondos ON abogados_fondos(expediente_id, fecha);

CREATE TABLE IF NOT EXISTS abogados_minutas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    expediente_id INTEGER REFERENCES expedientes(id) ON DELETE SET NULL,
    numero TEXT,
    fecha TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador', 'emitida', 'pagada', 'anulada')),
    iva_pct INTEGER NOT NULL DEFAULT 21,
    irpf_pct INTEGER NOT NULL DEFAULT 0,
    base_centimos INTEGER NOT NULL DEFAULT 0,
    suplidos_centimos INTEGER NOT NULL DEFAULT 0,
    iva_centimos INTEGER NOT NULL DEFAULT 0,
    irpf_centimos INTEGER NOT NULL DEFAULT 0,
    total_centimos INTEGER NOT NULL DEFAULT 0,
    cargada_a_provision INTEGER NOT NULL DEFAULT 0,
    notas TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    UNIQUE (tenant_id, numero)
);
CREATE INDEX IF NOT EXISTS idx_abogados_minutas ON abogados_minutas(tenant_id, estado, fecha);

CREATE TABLE IF NOT EXISTS abogados_minuta_lineas (
    id INTEGER PRIMARY KEY,
    minuta_id INTEGER NOT NULL REFERENCES abogados_minutas(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL DEFAULT 'honorarios' CHECK (tipo IN ('honorarios', 'suplido')),
    concepto TEXT NOT NULL,
    segundos INTEGER,
    importe_centimos INTEGER NOT NULL,
    parte_id INTEGER,
    fondo_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_abogados_minuta_lineas ON abogados_minuta_lineas(minuta_id);

"""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    enlaces_publicos.esquema(conn, ID)


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    enlaces_publicos.borrar_datos_de_tenant(conn, ID, tenant_id)
    for tabla in ("abogados_vistas", "abogados_fondos"):
        conn.execute(f"DELETE FROM {tabla} WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM abogados_minuta_lineas WHERE minuta_id IN (SELECT id FROM abogados_minutas WHERE tenant_id = ?)", (tenant_id,))
    conn.execute("DELETE FROM abogados_minutas WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM abogados_partes WHERE expediente_id IN (SELECT id FROM expedientes WHERE tenant_id = ?)", (tenant_id,))
    conn.execute("DELETE FROM abogados_ajustes WHERE tenant_id = ?", (tenant_id,))


# --- Ajustes del despacho -------------------------------------------------------------------------------------------------------------------------
def obtener_ajustes(tenant_id: int) -> dict:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM abogados_ajustes WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    a = dict(AJUSTES_POR_DEFECTO)
    if f:
        a.update({k: f[k] for k in AJUSTES_POR_DEFECTO})
        a["plantilla_encargo"] = f["plantilla_encargo"]
    a.setdefault("plantilla_encargo", None)
    a["plantilla_encargo_efectiva"] = a["plantilla_encargo"] or HOJA_DE_ENCARGO_POR_DEFECTO
    return a


def guardar_ajustes(tenant_id: int, *, serie: str, iva_pct, irpf_pct, bloque_minutos, provision_minima_centimos, plantilla_encargo: str | None) -> None:
    serie = (serie or "").strip().upper()
    if not serie or len(serie) > 8 or not serie.replace("-", "").isalnum():
        raise ValueError("La serie de las minutas son hasta 8 letras o números (por ejemplo M).")
    try:
        iva, irpf, bloque, prov = int(iva_pct), int(irpf_pct), int(bloque_minutos), int(provision_minima_centimos)
    except (TypeError, ValueError):
        raise ValueError("IVA, retención, bloque de minutos y provisión mínima deben ser números.") from None
    if not (0 <= iva <= 30 and 0 <= irpf <= 30 and 0 <= bloque <= 60 and 0 <= prov <= 100_000_000):
        raise ValueError("Algún valor está fuera de rango (IVA y retención 0-30 %, bloque 0-60 min).")
    plantilla = (plantilla_encargo or "").strip() or None
    if plantilla and len(plantilla) > 20000:
        raise ValueError("La hoja de encargo es demasiado larga.")
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO abogados_ajustes (tenant_id, serie, iva_pct, irpf_pct, bloque_minutos, provision_minima_centimos, plantilla_encargo) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(tenant_id) DO UPDATE SET serie = excluded.serie, iva_pct = excluded.iva_pct, irpf_pct = excluded.irpf_pct, bloque_minutos = excluded.bloque_minutos, "
            "provision_minima_centimos = excluded.provision_minima_centimos, plantilla_encargo = excluded.plantilla_encargo",
            (tenant_id, serie, iva, irpf, bloque, prov, plantilla))
        conn.commit()
    finally:
        conn.close()


# --- Datos del procedimiento y partes -------------------------------------------------------------------------------------------------------
CAMPOS_PROCEDIMIENTO = ("numero_procedimiento", "juzgado", "jurisdiccion", "tipo_procedimiento", "procurador", "fase", "materia", "resumen_cliente")


def datos_de(exp) -> dict:
    try:
        return json.loads(exp["datos"]) if exp["datos"] else {}
    except (TypeError, ValueError):
        return {}


def _expediente_abogados(tenant_id: int, usuario_id: int, expediente_id: int, supervisor: bool):
    exp = nucleo.obtener_expediente(tenant_id, expediente_id, usuario_id, supervisor)
    if exp is None or exp["tipo"] not in TIPOS:
        raise ValueError("Expediente no encontrado.")
    return exp


def fijar_datos(tenant_id: int, usuario_id: int, expediente_id: int, supervisor: bool = False, **campos) -> dict:
    """Guarda los datos propios del asunto (juzgado, número de procedimiento, jurisdicción, procurador, cuantía, resumen para el cliente…)."""
    exp = _expediente_abogados(tenant_id, usuario_id, expediente_id, supervisor)
    datos = datos_de(exp)
    for c in CAMPOS_PROCEDIMIENTO:
        if c in campos:
            v = (campos[c] or "").strip()
            if c == "jurisdiccion" and v and v not in dict(JURISDICCIONES):
                raise ValueError("Jurisdicción no válida.")
            datos[c] = v[:3000 if c == "resumen_cliente" else 200] or None
    if "cuantia" in campos:
        try:
            datos["cuantia_centimos"] = nucleo.importe_a_centimos(campos["cuantia"]) if (campos["cuantia"] or "").strip() else None
        except ValueError:
            raise ValueError("La cuantía no es un importe válido.") from None
        if datos["cuantia_centimos"] is not None and datos["cuantia_centimos"] < 0:
            raise ValueError("La cuantía no puede ser negativa.")
    datos = {k: v for k, v in datos.items() if v not in (None, "")}
    nucleo.editar_expediente(tenant_id, usuario_id, expediente_id, supervisor, datos=datos)
    return datos


def anadir_parte(tenant_id: int, usuario_id: int, expediente_id: int, rol: str, nombre: str, nif: str | None = None, notas: str | None = None, supervisor: bool = False) -> int:
    _expediente_abogados(tenant_id, usuario_id, expediente_id, supervisor)
    if rol not in dict(ROLES_PARTE):
        raise ValueError("Rol no válido.")
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("Indica el nombre de la parte.")
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO abogados_partes (expediente_id, rol, nombre, nif, notas, creado_en) VALUES (?, ?, ?, ?, ?, ?)",
                           (expediente_id, rol, nombre[:200], (nif or "").strip()[:30] or None, (notas or "").strip()[:500] or None, db.now_iso()))
        nucleo._evento(conn, expediente_id, "parte", f"Parte añadida: {nombre[:80]} ({verticales.original(dict(ROLES_PARTE)[rol])}).", usuario_id)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_partes(tenant_id: int, usuario_id: int, expediente_id: int, supervisor: bool = False) -> list:
    if nucleo.obtener_expediente(tenant_id, expediente_id, usuario_id, supervisor) is None:
        return []
    conn = db.get_connection()
    try:
        return conn.execute("SELECT * FROM abogados_partes WHERE expediente_id = ? ORDER BY CASE rol WHEN 'cliente' THEN 0 WHEN 'contraparte' THEN 1 ELSE 2 END, id", (expediente_id,)).fetchall()
    finally:
        conn.close()


def eliminar_parte(tenant_id: int, usuario_id: int, expediente_id: int, parte_id: int, supervisor: bool = False) -> None:
    _expediente_abogados(tenant_id, usuario_id, expediente_id, supervisor)
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM abogados_partes WHERE id = ? AND expediente_id = ?", (parte_id, expediente_id))
        conn.commit()
    finally:
        conn.close()


# --- Conflicto de intereses -------------------------------------------------------------------------------------------------------------------------
def _igual(a: str | None, b: str | None) -> bool:
    return bool(a and b) and nucleo.plano(a).replace(" ", "") == nucleo.plano(b).replace(" ", "")


def _nif_igual(a: str | None, b: str | None) -> bool:
    limpio = lambda x: (x or "").upper().replace("-", "").replace(" ", "").replace(".", "")
    return bool(limpio(a)) and limpio(a) == limpio(b)


def revisar_conflictos(tenant_id: int, usuario_id: int, nombre: str, nif: str | None = None, como: str = "cliente", supervisor: bool = False, excluir_expediente: int | None = None) -> list[dict]:
    """Posibles conflictos de intereses de una persona o empresa **dentro del despacho** (todo lo suyo, aunque la persona que pregunta no pueda ver el expediente):
    como = «cliente» → ¿ha sido contraparte (o su letrado o procurador) en algún asunto?; como = «contraparte» → ¿es ya cliente del despacho?
    De un expediente confidencial que la persona no puede ver solo se avisa de que existe, sin título ni cliente. Coincide por NIF o por nombre igual."""
    nombre = (nombre or "").strip()
    if not nombre and not (nif or "").strip():
        return []
    conn = db.get_connection()
    try:
        hallazgos: list[dict] = []
        if como == "cliente":
            for p in conn.execute(
                "SELECT p.rol, p.nombre, p.nif, x.id AS expediente_id, x.titulo, x.confidencial, x.responsable_id, x.creado_por, c.nombre AS cliente FROM abogados_partes p "
                "JOIN expedientes x ON x.id = p.expediente_id JOIN clientes c ON c.id = x.cliente_id WHERE x.tenant_id = ? AND x.papelera_en IS NULL AND p.rol IN ('contraparte', 'letrado_contrario', 'procurador_contrario')",
                (tenant_id,)).fetchall():
                if (_nif_igual(nif, p["nif"]) or _igual(nombre, p["nombre"])) and p["expediente_id"] != excluir_expediente:
                    hallazgos.append({"motivo": "fue_contraparte", "rol": p["rol"], "expediente_id": p["expediente_id"], "titulo": p["titulo"], "cliente": p["cliente"], "confidencial": p["confidencial"],
                                      "responsable_id": p["responsable_id"], "creado_por": p["creado_por"]})
        else:
            for c in conn.execute("SELECT id, nombre, nif FROM clientes WHERE tenant_id = ? AND papelera_en IS NULL", (tenant_id,)).fetchall():
                if _nif_igual(nif, c["nif"]) or _igual(nombre, c["nombre"]):
                    hallazgos.append({"motivo": "es_cliente", "cliente_id": c["id"], "cliente": c["nombre"], "confidencial": 0})
            for p in conn.execute(
                "SELECT p.nombre, p.nif, x.id AS expediente_id, x.titulo, x.confidencial, x.responsable_id, x.creado_por, c.nombre AS cliente FROM abogados_partes p JOIN expedientes x ON x.id = p.expediente_id "
                "JOIN clientes c ON c.id = x.cliente_id WHERE x.tenant_id = ? AND x.papelera_en IS NULL AND p.rol = 'cliente'", (tenant_id,)).fetchall():
                if (_nif_igual(nif, p["nif"]) or _igual(nombre, p["nombre"])) and p["expediente_id"] != excluir_expediente:
                    hallazgos.append({"motivo": "es_parte_cliente", "expediente_id": p["expediente_id"], "titulo": p["titulo"], "cliente": p["cliente"], "confidencial": p["confidencial"],
                                      "responsable_id": p["responsable_id"], "creado_por": p["creado_por"]})
        miembros = {}
        for h in hallazgos:
            if h.get("confidencial") and not supervisor and usuario_id not in (h.get("responsable_id"), h.get("creado_por")):
                eid = h["expediente_id"]
                if eid not in miembros:
                    miembros[eid] = conn.execute("SELECT 1 FROM expediente_miembros WHERE expediente_id = ? AND usuario_id = ?", (eid, usuario_id)).fetchone() is not None
                if not miembros[eid]:
                    h["oculto"] = True
                    for k in ("titulo", "cliente", "expediente_id"):
                        h[k] = None
        return hallazgos
    finally:
        conn.close()


# --- Vistas -----------------------------------------------------------------------------------------------------------------------------------------------
def _fecha_hora(valor: str) -> str:
    try:
        return datetime.fromisoformat((valor or "").strip().replace(" ", "T")[:16]).isoformat(timespec="minutes")
    except ValueError:
        raise ValueError("La fecha y la hora de la vista no son válidas.") from None


def crear_vista(tenant_id: int, usuario_id: int, expediente_id: int, fecha_hora: str, tipo: str = "vista", lugar: str | None = None, notas: str | None = None, supervisor: bool = False) -> int:
    _expediente_abogados(tenant_id, usuario_id, expediente_id, supervisor)
    if tipo not in dict(TIPOS_VISTA):
        raise ValueError("Tipo de vista no válido.")
    fh = _fecha_hora(fecha_hora)
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO abogados_vistas (tenant_id, expediente_id, fecha_hora, tipo, lugar, notas, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, expediente_id, fh, tipo, (lugar or "").strip()[:200] or None, (notas or "").strip()[:1000] or None, usuario_id, db.now_iso()))
        nucleo._evento(conn, expediente_id, "vista", f"Señalamiento: {verticales.original(dict(TIPOS_VISTA)[tipo])} el {fh.replace('T', ' ')}.", usuario_id)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_vistas(tenant_id: int, usuario_id: int, supervisor: bool = False, *, expediente_id: int | None = None, desde: str | None = None, hasta: str | None = None,
                  estado: str | None = None, limite: int = 200) -> list:
    cond_vis, p_vis = nucleo._visible_sql(usuario_id, supervisor, "x")
    donde, p = ["v.tenant_id = ?", "x.papelera_en IS NULL", cond_vis], [tenant_id, *p_vis]
    if expediente_id:
        donde.append("v.expediente_id = ?"); p.append(expediente_id)
    if desde:
        donde.append("v.fecha_hora >= ?"); p.append(desde)
    if hasta:
        donde.append("v.fecha_hora <= ?"); p.append(hasta + "T23:59" if len(hasta) == 10 else hasta)
    if estado:
        donde.append("v.estado = ?"); p.append(estado)
    conn = db.get_connection()
    try:
        return conn.execute("SELECT v.*, x.titulo AS expediente_titulo, c.nombre AS cliente_nombre FROM abogados_vistas v JOIN expedientes x ON x.id = v.expediente_id JOIN clientes c ON c.id = x.cliente_id "
                            f"WHERE {' AND '.join(donde)} ORDER BY v.fecha_hora LIMIT ?", [*p, max(1, min(limite, 1000))]).fetchall()
    finally:
        conn.close()


def cambiar_estado_vista(tenant_id: int, usuario_id: int, vista_id: int, estado: str, supervisor: bool = False) -> None:
    if estado not in ("prevista", "celebrada", "suspendida"):
        raise ValueError("Estado no válido.")
    v = _vista(tenant_id, usuario_id, vista_id, supervisor)
    conn = db.get_connection()
    try:
        conn.execute("UPDATE abogados_vistas SET estado = ? WHERE id = ?", (estado, vista_id))
        nucleo._evento(conn, v["expediente_id"], "vista", f"Señalamiento del {v['fecha_hora'].replace('T', ' ')}: {estado}.", usuario_id)
        conn.commit()
    finally:
        conn.close()


def eliminar_vista(tenant_id: int, usuario_id: int, vista_id: int, supervisor: bool = False) -> None:
    _vista(tenant_id, usuario_id, vista_id, supervisor)
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM abogados_vistas WHERE id = ?", (vista_id,))
        conn.commit()
    finally:
        conn.close()


def _vista(tenant_id: int, usuario_id: int, vista_id: int, supervisor: bool):
    conn = db.get_connection()
    try:
        v = conn.execute("SELECT * FROM abogados_vistas WHERE id = ? AND tenant_id = ?", (vista_id, tenant_id)).fetchone()
    finally:
        conn.close()
    if v is None or nucleo.obtener_expediente(tenant_id, v["expediente_id"], usuario_id, supervisor) is None:
        raise ValueError("Señalamiento no encontrado.")
    return v


def vistas_a_ics(vistas) -> str:
    """Calendario .ics de los señalamientos (importable en cualquier calendario). Hora local flotante, sin zona."""
    def esc(t: str) -> str:
        return (t or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    lineas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Guilda Work//Abogados//ES", "CALSCALE:GREGORIAN"]
    for v in vistas:
        ini = datetime.fromisoformat(v["fecha_hora"])
        fin = ini + timedelta(hours=1)
        lineas += ["BEGIN:VEVENT", f"UID:vista-{v['id']}@guildawork", f"DTSTAMP:{datetime.now():%Y%m%dT%H%M%S}", f"DTSTART:{ini:%Y%m%dT%H%M%S}", f"DTEND:{fin:%Y%m%dT%H%M%S}",
                   f"SUMMARY:{esc(verticales.original(dict(TIPOS_VISTA).get(v['tipo'], 'Vista')))} — {esc(v['expediente_titulo'])}", f"LOCATION:{esc(v['lugar'] or '')}", f"DESCRIPTION:{esc(v['notas'] or '')}",
                   "STATUS:CANCELLED" if v["estado"] == "suspendida" else "STATUS:CONFIRMED", "END:VEVENT"]
    lineas.append("END:VCALENDAR")
    return "\r\n".join(lineas) + "\r\n"


# --- Notificaciones y plazos procesales ----------------------------------------------------------------------------------------------------------
def calcular_plazo(tenant_id: int, fecha_notificacion: str, plazo: int, unidad: str = "habiles") -> dict:
    """Fecha límite de un plazo procesal contado desde la notificación (el día de la notificación no cuenta), con el calendario procesal del despacho."""
    f = nucleo._fecha_iso(fecha_notificacion, "La fecha de la notificación")
    if not (1 <= int(plazo) <= 366):
        raise ValueError("El plazo debe estar entre 1 y 366.")
    cal = nucleo.calendario_del_despacho(tenant_id, "procesal")
    inicio = date.fromisoformat(f)
    limite = cp.vencimiento(inicio, int(plazo), unidad, cal)
    saltados = [d.isoformat() for d in (inicio + timedelta(days=i) for i in range(1, (limite - inicio).days + 1)) if not cal.es_habil(d) and d.weekday() < 5]
    return {"fecha_notificacion": f, "plazo": int(plazo), "unidad": unidad, "fecha_limite": limite.isoformat(), "dias_inhabiles_entre": saltados,
            "dias_habiles_restantes": cp.dias_habiles_entre(date.today(), limite, cal) if limite >= date.today() else None}


def registrar_notificacion(tenant_id: int, usuario_id: int, expediente_id: int, resolucion: str, fecha_notificacion: str, plazo: int, unidad: str = "habiles", *,
                           titulo: str | None = None, critico: bool = True, crear_tarea: bool = True, supervisor: bool = False) -> int:
    """Una resolución notificada → su plazo (marcado como fatal por defecto, pendiente de segunda revisión) y una tarea para la persona responsable.
    Devuelve el id del plazo."""
    exp = _expediente_abogados(tenant_id, usuario_id, expediente_id, supervisor)
    if resolucion not in dict(RESOLUCIONES):
        raise ValueError("Tipo de resolución no válido.")
    c = calcular_plazo(tenant_id, fecha_notificacion, plazo, unidad)
    nombre = (titulo or "").strip() or f"{verticales.original(dict(RESOLUCIONES)[resolucion])} notificada el {c['fecha_notificacion']}: plazo de {c['plazo']} días"
    pid = nucleo.crear_plazo(tenant_id, usuario_id, nombre, c["fecha_limite"], expediente_id=expediente_id, origen="notificacion", critico=critico, supervisor=supervisor,
                             notas=f"Notificación del {c['fecha_notificacion']}, plazo de {c['plazo']} días {unidad}. Calculado con el calendario procesal de ejemplo (sin validar): comprobar.")
    if crear_tarea:
        try:
            db.crear_tarea_outlook(exp["responsable_id"] or usuario_id, f"Plazo: {nombre} — {exp['titulo']}", cuerpo=f"Vence el {c['fecha_limite']}. Expediente: {exp['titulo']}.",
                                   prioridad="alta", fecha_vencimiento=c["fecha_limite"], asignada_a=None)
        except Exception:  # noqa: BLE001 -- la tarea es un extra: el plazo ya está guardado y es lo que importa
            pass
    return pid


# --- Provisión de fondos ---------------------------------------------------------------------------------------------------------------------------
def _importe(valor) -> int:
    return nucleo.importe_a_centimos(valor)


def registrar_movimiento(tenant_id: int, usuario_id: int, expediente_id: int, tipo: str, importe, concepto: str, fecha: str | None = None, supervisor: bool = False) -> int:
    _expediente_abogados(tenant_id, usuario_id, expediente_id, supervisor)
    if tipo not in dict(MOVIMIENTOS):
        raise ValueError("Tipo de movimiento no válido.")
    centimos = _importe(importe)
    if centimos <= 0 or centimos > 1_000_000_000:
        raise ValueError("El importe debe ser mayor que cero.")
    concepto = (concepto or "").strip()
    if not concepto:
        raise ValueError("Indica el concepto.")
    fecha = nucleo._fecha_iso(fecha, "La fecha") if fecha else date.today().isoformat()
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO abogados_fondos (tenant_id, expediente_id, fecha, tipo, importe_centimos, concepto, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, expediente_id, fecha, tipo, centimos, concepto[:200], usuario_id, db.now_iso()))
        nucleo._evento(conn, expediente_id, "fondos", f"{verticales.original(dict(MOVIMIENTOS)[tipo])}: {centimos / 100:.2f} €.", usuario_id)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def saldo(tenant_id: int, expediente_id: int) -> dict:
    """Cuenta del cliente en el asunto: provisiones recibidas menos suplidos, honorarios cargados y devoluciones. Saldo negativo = el despacho ha adelantado dinero."""
    conn = db.get_connection()
    try:
        f = {r["tipo"]: r["t"] for r in conn.execute("SELECT tipo, SUM(importe_centimos) AS t FROM abogados_fondos WHERE tenant_id = ? AND expediente_id = ? GROUP BY tipo", (tenant_id, expediente_id))}
    finally:
        conn.close()
    prov, sup, hon, dev = f.get("provision", 0), f.get("suplido", 0), f.get("honorarios", 0), f.get("devolucion", 0)
    return {"provisiones": prov, "suplidos": sup, "honorarios": hon, "devoluciones": dev, "saldo": prov - sup - hon - dev}


def listar_movimientos(tenant_id: int, usuario_id: int, expediente_id: int, supervisor: bool = False) -> list:
    if nucleo.obtener_expediente(tenant_id, expediente_id, usuario_id, supervisor) is None:
        return []
    conn = db.get_connection()
    try:
        return conn.execute("SELECT * FROM abogados_fondos WHERE tenant_id = ? AND expediente_id = ? ORDER BY fecha DESC, id DESC", (tenant_id, expediente_id)).fetchall()
    finally:
        conn.close()


def expedientes_con_provision_baja(tenant_id: int, usuario_id: int, supervisor: bool = False) -> list[dict]:
    """Asuntos abiertos cuyo saldo está por debajo de la provisión mínima del despacho (y con alguna provisión o suplido movido, para no avisar de lo que no usa fondos)."""
    minimo = obtener_ajustes(tenant_id)["provision_minima_centimos"]
    if minimo <= 0:
        return []
    filas, _n = nucleo.listar_expedientes(tenant_id, usuario_id, supervisor, solo_abiertos=True, limite=500)
    res = []
    for x in filas:
        if x["tipo"] not in TIPOS:
            continue
        s = saldo(tenant_id, x["id"])
        if (s["provisiones"] or s["suplidos"]) and s["saldo"] < minimo:
            res.append({"expediente_id": x["id"], "titulo": x["titulo"], "cliente_nombre": x["cliente_nombre"], "saldo": s["saldo"], "minimo": minimo})
    return res


# --- Minutas ------------------------------------------------------------------------------------------------------------------------------------------
def _redondeo(valor: float) -> int:
    return int(valor + 0.5) if valor >= 0 else -int(-valor + 0.5)


def calcular_minuta(honorarios_centimos: int, suplidos_centimos: int, iva_pct: int, irpf_pct: int) -> dict:
    """Totales de una minuta en céntimos: IVA y retención sobre los honorarios (los suplidos no llevan ninguno de los dos) y total a pagar."""
    iva = _redondeo(honorarios_centimos * iva_pct / 100)
    irpf = _redondeo(honorarios_centimos * irpf_pct / 100)
    return {"base": honorarios_centimos, "suplidos": suplidos_centimos, "iva": iva, "irpf": irpf, "total": honorarios_centimos + iva - irpf + suplidos_centimos}


def _recalcular(conn, minuta_id: int) -> None:
    m = conn.execute("SELECT iva_pct, irpf_pct FROM abogados_minutas WHERE id = ?", (minuta_id,)).fetchone()
    t = {r["tipo"]: r["s"] for r in conn.execute("SELECT tipo, SUM(importe_centimos) AS s FROM abogados_minuta_lineas WHERE minuta_id = ? GROUP BY tipo", (minuta_id,))}
    c = calcular_minuta(t.get("honorarios", 0), t.get("suplido", 0), m["iva_pct"], m["irpf_pct"])
    conn.execute("UPDATE abogados_minutas SET base_centimos = ?, suplidos_centimos = ?, iva_centimos = ?, irpf_centimos = ?, total_centimos = ? WHERE id = ?",
                 (c["base"], c["suplidos"], c["iva"], c["irpf"], c["total"], minuta_id))


def _minuta_de(conn, tenant_id: int, minuta_id: int):
    m = conn.execute("SELECT * FROM abogados_minutas WHERE id = ? AND tenant_id = ?", (minuta_id, tenant_id)).fetchone()
    if m is None:
        raise ValueError("Minuta no encontrada.")
    return m


def crear_borrador_de_minuta(tenant_id: int, usuario_id: int, expediente_id: int, supervisor: bool = False, *, desde: str | None = None, hasta: str | None = None) -> int:
    """Borrador con las horas facturables aún sin facturar del asunto (a la tarifa de cada parte, redondeadas al bloque del despacho) y los suplidos pendientes."""
    exp = _expediente_abogados(tenant_id, usuario_id, expediente_id, supervisor)
    aj = obtener_ajustes(tenant_id)
    cliente = nucleo.obtener_cliente(tenant_id, exp["cliente_id"])
    irpf = aj["irpf_pct"] if cliente["tipo"] == "empresa" else 0           # la retención solo se aplica a clientes que sean empresa o profesional
    partes = nucleo.listar_partes(tenant_id, usuario_id, supervisor, ver_todo=True, expediente_id=expediente_id, pendiente_de_facturar=True, desde=desde, hasta=hasta, limite=2000)
    conn = db.get_connection()
    try:
        suplidos = conn.execute("SELECT * FROM abogados_fondos WHERE tenant_id = ? AND expediente_id = ? AND tipo = 'suplido' AND facturado_en IS NULL ORDER BY fecha", (tenant_id, expediente_id)).fetchall()
        if not partes and not suplidos:
            raise ValueError("No hay horas facturables ni suplidos pendientes en este asunto.")
        cur = conn.execute("INSERT INTO abogados_minutas (tenant_id, cliente_id, expediente_id, fecha, iva_pct, irpf_pct, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, exp["cliente_id"], expediente_id, date.today().isoformat(), aj["iva_pct"], irpf, usuario_id, db.now_iso()))
        mid = cur.lastrowid
        for p in sorted(partes, key=lambda p: (p["fecha"], p["id"])):
            conn.execute("INSERT INTO abogados_minuta_lineas (minuta_id, tipo, concepto, segundos, importe_centimos, parte_id) VALUES (?, 'honorarios', ?, ?, ?, ?)",
                         (mid, f"{p['fecha']} — {p['descripcion']}", p["segundos"], nucleo.importe_centimos(p["segundos"], p["tarifa_hora_centimos"], aj["bloque_minutos"]), p["id"]))
        for s in suplidos:
            conn.execute("INSERT INTO abogados_minuta_lineas (minuta_id, tipo, concepto, importe_centimos, fondo_id) VALUES (?, 'suplido', ?, ?, ?)", (mid, f"{s['fecha']} — {s['concepto']}", s["importe_centimos"], s["id"]))
        _recalcular(conn, mid)
        nucleo._evento(conn, expediente_id, "minuta", "Borrador de minuta creado.", usuario_id)
        conn.commit()
        return mid
    finally:
        conn.close()


def obtener_minuta(tenant_id: int, minuta_id: int):
    conn = db.get_connection()
    try:
        m = conn.execute("SELECT m.*, c.nombre AS cliente_nombre, c.nif AS cliente_nif, x.titulo AS expediente_titulo FROM abogados_minutas m JOIN clientes c ON c.id = m.cliente_id "
                         "LEFT JOIN expedientes x ON x.id = m.expediente_id WHERE m.id = ? AND m.tenant_id = ?", (minuta_id, tenant_id)).fetchone()
        if m is None:
            return None, []
        return m, conn.execute("SELECT * FROM abogados_minuta_lineas WHERE minuta_id = ? ORDER BY id", (minuta_id,)).fetchall()
    finally:
        conn.close()


def listar_minutas(tenant_id: int, usuario_id: int, supervisor: bool = False, *, estado: str | None = None, expediente_id: int | None = None, limite: int = 200) -> list:
    cond_vis, p_vis = nucleo._visible_sql(usuario_id, supervisor, "x")
    donde, p = ["m.tenant_id = ?", f"(m.expediente_id IS NULL OR ({cond_vis}))"], [tenant_id, *p_vis]
    if estado:
        donde.append("m.estado = ?"); p.append(estado)
    if expediente_id:
        donde.append("m.expediente_id = ?"); p.append(expediente_id)
    conn = db.get_connection()
    try:
        return conn.execute("SELECT m.*, c.nombre AS cliente_nombre, x.titulo AS expediente_titulo FROM abogados_minutas m JOIN clientes c ON c.id = m.cliente_id LEFT JOIN expedientes x ON x.id = m.expediente_id "
                            f"WHERE {' AND '.join(donde)} ORDER BY m.fecha DESC, m.id DESC LIMIT ?", [*p, max(1, min(limite, 1000))]).fetchall()
    finally:
        conn.close()


def _borrador(conn, tenant_id: int, minuta_id: int):
    m = _minuta_de(conn, tenant_id, minuta_id)
    if m["estado"] != "borrador":
        raise ValueError("La minuta ya está emitida: no se puede modificar.")
    return m


def anadir_linea_minuta(tenant_id: int, minuta_id: int, concepto: str, importe, tipo: str = "honorarios") -> int:
    if tipo not in ("honorarios", "suplido"):
        raise ValueError("Tipo de línea no válido.")
    concepto = (concepto or "").strip()
    if not concepto:
        raise ValueError("Indica el concepto.")
    centimos = _importe(importe)
    conn = db.get_connection()
    try:
        _borrador(conn, tenant_id, minuta_id)
        cur = conn.execute("INSERT INTO abogados_minuta_lineas (minuta_id, tipo, concepto, importe_centimos) VALUES (?, ?, ?, ?)", (minuta_id, tipo, concepto[:300], centimos))
        _recalcular(conn, minuta_id)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def quitar_linea_minuta(tenant_id: int, minuta_id: int, linea_id: int) -> None:
    conn = db.get_connection()
    try:
        _borrador(conn, tenant_id, minuta_id)
        conn.execute("DELETE FROM abogados_minuta_lineas WHERE id = ? AND minuta_id = ?", (linea_id, minuta_id))
        _recalcular(conn, minuta_id)
        conn.commit()
    finally:
        conn.close()


def fijar_impuestos_minuta(tenant_id: int, minuta_id: int, iva_pct, irpf_pct, notas: str | None = None) -> None:
    try:
        iva, irpf = int(iva_pct), int(irpf_pct)
    except (TypeError, ValueError):
        raise ValueError("El IVA y la retención deben ser números.") from None
    if not (0 <= iva <= 30 and 0 <= irpf <= 30):
        raise ValueError("IVA y retención entre 0 y 30 %.")
    conn = db.get_connection()
    try:
        _borrador(conn, tenant_id, minuta_id)
        conn.execute("UPDATE abogados_minutas SET iva_pct = ?, irpf_pct = ?, notas = ? WHERE id = ?", (iva, irpf, (notas or "").strip()[:1000] or None, minuta_id))
        _recalcular(conn, minuta_id)
        conn.commit()
    finally:
        conn.close()


def _siguiente_numero(conn, tenant_id: int, serie: str, anio: int) -> str:
    prefijo = f"{serie}-{anio}-"
    n = 0
    for f in conn.execute("SELECT numero FROM abogados_minutas WHERE tenant_id = ? AND numero LIKE ?", (tenant_id, prefijo + "%")):
        try:
            n = max(n, int(f["numero"][len(prefijo):]))
        except ValueError:
            continue
    return f"{prefijo}{n + 1:03d}"


def emitir_minuta(tenant_id: int, usuario_id: int, minuta_id: int, cargar_a_provision: bool = False) -> str:
    """Pasa el borrador a emitida: le da número correlativo de la serie y año, marca como facturadas las horas y los suplidos que incluye y, si se pide,
    carga el total a la provisión de fondos del asunto. Devuelve el número."""
    aj = obtener_ajustes(tenant_id)
    conn = db.get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        m = _borrador(conn, tenant_id, minuta_id)
        lineas = conn.execute("SELECT * FROM abogados_minuta_lineas WHERE minuta_id = ?", (minuta_id,)).fetchall()
        if not lineas:
            raise ValueError("La minuta no tiene líneas.")
        if m["total_centimos"] <= 0:
            raise ValueError("El total de la minuta debe ser mayor que cero.")
        numero = _siguiente_numero(conn, tenant_id, aj["serie"], date.today().year)
        hoy = date.today().isoformat()
        conn.execute("UPDATE abogados_minutas SET estado = 'emitida', numero = ?, fecha = ?, cargada_a_provision = ? WHERE id = ?", (numero, hoy, 1 if cargar_a_provision and m["expediente_id"] else 0, minuta_id))
        for l in lineas:
            if l["parte_id"]:
                conn.execute("UPDATE partes_tiempo SET facturado_en = ? WHERE id = ? AND tenant_id = ?", (hoy, l["parte_id"], tenant_id))
            if l["fondo_id"]:
                conn.execute("UPDATE abogados_fondos SET facturado_en = ?, minuta_id = ? WHERE id = ?", (hoy, minuta_id, l["fondo_id"]))
        if cargar_a_provision and m["expediente_id"]:
            conn.execute("INSERT INTO abogados_fondos (tenant_id, expediente_id, fecha, tipo, importe_centimos, concepto, minuta_id, facturado_en, creado_por, creado_en) VALUES (?, ?, ?, 'honorarios', ?, ?, ?, ?, ?, ?)",
                         (tenant_id, m["expediente_id"], hoy, m["total_centimos"], f"Minuta {numero}", minuta_id, hoy, usuario_id, db.now_iso()))
        if m["expediente_id"]:
            nucleo._evento(conn, m["expediente_id"], "minuta", f"Minuta {numero} emitida: {m['total_centimos'] / 100:.2f} €.", usuario_id)
        conn.commit()
        return numero
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def cambiar_estado_minuta(tenant_id: int, usuario_id: int, minuta_id: int, estado: str) -> None:
    """Emitida → pagada, o anular. Anular libera las horas y los suplidos para volver a facturarlos y borra el cargo a provisión."""
    if estado not in ("pagada", "anulada"):
        raise ValueError("Estado no válido.")
    conn = db.get_connection()
    try:
        m = _minuta_de(conn, tenant_id, minuta_id)
        if m["estado"] not in ("emitida", "pagada") or (estado == "pagada" and m["estado"] != "emitida"):
            raise ValueError("Esa minuta no admite este cambio.")
        if estado == "anulada":
            for l in conn.execute("SELECT parte_id, fondo_id FROM abogados_minuta_lineas WHERE minuta_id = ?", (minuta_id,)):
                if l["parte_id"]:
                    conn.execute("UPDATE partes_tiempo SET facturado_en = NULL WHERE id = ?", (l["parte_id"],))
                if l["fondo_id"]:
                    conn.execute("UPDATE abogados_fondos SET facturado_en = NULL, minuta_id = NULL WHERE id = ?", (l["fondo_id"],))
            conn.execute("DELETE FROM abogados_fondos WHERE minuta_id = ? AND tipo = 'honorarios'", (minuta_id,))
        conn.execute("UPDATE abogados_minutas SET estado = ? WHERE id = ?", (estado, minuta_id))
        if m["expediente_id"]:
            nucleo._evento(conn, m["expediente_id"], "minuta", f"Minuta {m['numero']}: {estado}.", usuario_id)
        conn.commit()
    finally:
        conn.close()


def eliminar_borrador(tenant_id: int, minuta_id: int) -> None:
    conn = db.get_connection()
    try:
        _borrador(conn, tenant_id, minuta_id)
        conn.execute("DELETE FROM abogados_minutas WHERE id = ?", (minuta_id,))
        conn.commit()
    finally:
        conn.close()


def minuta_a_pdf(tenant_id: int, minuta_id: int) -> bytes:
    m, lineas = obtener_minuta(tenant_id, minuta_id)
    if m is None:
        raise ValueError("Minuta no encontrada.")
    despacho = (db.obtener_tenant(tenant_id) or {"nombre": ""})["nombre"]
    eur = lambda c: f"{c / 100:,.2f} €".replace(",", "§").replace(".", ",").replace("§", ".")
    filas = [[l["concepto"], f"{l['segundos'] / 3600:.2f} h" if l["segundos"] else "", eur(l["importe_centimos"]) + (" (suplido)" if l["tipo"] == "suplido" else "")] for l in lineas]
    filas += [["", "Honorarios", eur(m["base_centimos"])], ["", f"IVA ({m['iva_pct']} %)", eur(m["iva_centimos"])]]
    if m["irpf_pct"]:
        filas.append(["", f"Retención IRPF ({m['irpf_pct']} %)", "-" + eur(m["irpf_centimos"])])
    if m["suplidos_centimos"]:
        filas.append(["", "Suplidos", eur(m["suplidos_centimos"])])
    filas.append(["", "TOTAL", eur(m["total_centimos"])])
    titulo = f"Minuta {m['numero'] or '(borrador)'}"
    notas = f"{despacho} · Cliente: {m['cliente_nombre']}" + (f" ({m['cliente_nif']})" if m["cliente_nif"] else "") + f" · Fecha: {m['fecha']}" + (f" · Asunto: {m['expediente_titulo']}" if m["expediente_titulo"] else "")
    return generador_documentos.tabla_a_pdf(titulo, ["Concepto", "Tiempo", "Importe"], filas, notas=notas)


# --- Hoja de encargo ----------------------------------------------------------------------------------------------------------------------------------
def generar_hoja_de_encargo(tenant_id: int, usuario_id: int, expediente_id: int, supervisor: bool = False) -> int:
    """PDF de la hoja de encargo con los datos del asunto, guardado como documento del expediente (categoría «Hoja de encargo»). Devuelve el id del documento."""
    exp = _expediente_abogados(tenant_id, usuario_id, expediente_id, supervisor)
    cliente = nucleo.obtener_cliente(tenant_id, exp["cliente_id"])
    despacho = (db.obtener_tenant(tenant_id) or {"nombre": ""})["nombre"]
    tarifa = nucleo.tarifa_de(exp["responsable_id"] or usuario_id)
    valores = {"{fecha}": date.today().strftime("%d/%m/%Y"), "{despacho}": despacho, "{cliente}": cliente["nombre"], "{nif}": cliente["nif"] or "—", "{asunto}": exp["titulo"],
               "{tarifa}": f"{tarifa / 100:.2f} €/hora" if tarifa else "la que se acuerde"}
    texto = obtener_ajustes(tenant_id)["plantilla_encargo_efectiva"]
    for k, v in valores.items():
        texto = texto.replace(k, v)
    pdf = generador_documentos.texto_a_pdf("Hoja de encargo", texto, notas=f"{exp['titulo']} — modelo de ejemplo, sin validar")
    r, did = almacen_documentos.guardar(usuario_id, f"hoja_de_encargo_{exp['id']}.pdf", "application/pdf", pdf, expediente_id=expediente_id, categoria="Hoja de encargo", origen="generado")
    if r == "duplicado":
        return did
    if r != "ok":
        raise ValueError("No se pudo guardar la hoja de encargo.")
    return did


def enviar_a_firma(tenant_id: int, usuario_id: int, documento_id: int, email: str, nombre: str, supervisor: bool = False) -> str:
    """Manda un documento del asunto a firmar con Documenso (acción externa: la persona la confirma en pantalla). Devuelve el id en Documenso."""
    return firma_documentos.enviar(tenant_id, usuario_id, documento_id, email, nombre, lambda expediente_id: _expediente_abogados(tenant_id, usuario_id, expediente_id, supervisor))


# --- Enlace de solo lectura para el cliente ------------------------------------------------------------------------------------------------------
ESTADO_EN_LLANO = {
    "preparacion": _l("Estamos preparando su caso."), "tramite": _l("Su asunto está en tramitación."), "pendiente_vista": _l("Estamos pendientes de la celebración de una vista."),
    "pendiente_sentencia": _l("Ya se ha celebrado lo necesario y esperamos la resolución del juzgado."), "recurso": _l("El asunto está en fase de recurso."), "ejecucion": _l("Estamos ejecutando lo resuelto."),
    "archivado": _l("El asunto está finalizado y archivado."), "abierto": _l("Su asunto está abierto."), "negociacion": _l("Estamos negociando con la otra parte."),
    "pendiente_cliente": _l("Estamos a la espera de información o documentación por su parte."), "cerrado": _l("El asunto está cerrado."),
}


def crear_enlace(tenant_id: int, usuario_id: int, expediente_id: int, dias: int = 30, supervisor: bool = False, permite_mensajes: bool = False) -> str:
    """Enlace secreto de solo lectura para que el cliente vea el estado de su asunto. Devuelve el token en claro (solo se muestra ahora: en la base queda su huella)."""
    _expediente_abogados(tenant_id, usuario_id, expediente_id, supervisor)
    return enlaces_publicos.crear(ID, tenant_id, usuario_id, expediente_id, dias, permite_mensajes)


def listar_enlaces(tenant_id: int, expediente_id: int) -> list:
    return enlaces_publicos.listar(ID, tenant_id, expediente_id)


def revocar_enlace(tenant_id: int, usuario_id: int, expediente_id: int, enlace_id: int, supervisor: bool = False) -> None:
    _expediente_abogados(tenant_id, usuario_id, expediente_id, supervisor)
    enlaces_publicos.revocar(ID, tenant_id, expediente_id, enlace_id)


def resolver_enlace(token: str) -> dict | None:
    """El asunto al que da acceso un token válido (existe, no está revocado ni caducado, y el despacho tiene el módulo activo), o None."""
    return enlaces_publicos.resolver(ID, token)


def datos_publicos(token: str) -> dict | None:
    """Lo único que ve el cliente: el asunto, su estado en lenguaje llano, el resumen que haya escrito el despacho, los próximos señalamientos y los documentos
    que el despacho haya marcado como compartidos. Nada de horas, notas internas, plazos ni partes contrarias."""
    r = resolver_enlace(token)
    if r is None:
        return None
    x, tenant_id = r["expediente"], r["enlace"]["tenant_id"]
    datos = datos_de(x)
    conn = db.get_connection()
    try:
        vistas = conn.execute("SELECT fecha_hora, tipo, lugar FROM abogados_vistas WHERE expediente_id = ? AND estado = 'prevista' AND fecha_hora >= ? ORDER BY fecha_hora LIMIT 5", (x["id"], datetime.now().isoformat(timespec="minutes"))).fetchall()
        docs = almacen_documentos.compartidos_de_expediente(tenant_id, x["id"])
    finally:
        conn.close()
    despacho = (db.obtener_tenant(tenant_id) or {"nombre": ""})["nombre"]
    from . import mensajes_enlace
    return {"despacho": despacho, "titulo": x["titulo"], "cliente": x["cliente_nombre"], "estado_id": x["estado"], "resumen": datos.get("resumen_cliente"),
            "referencia": x["referencia"], "vistas": [dict(v) for v in vistas], "documentos": [dict(d) for d in docs], "actualizado": x["actualizado_en"] or x["creado_en"],
            **mensajes_enlace.para_pagina_publica(ID, r)}


def compartir_documento(tenant_id: int, usuario_id: int, expediente_id: int, documento_id: int, compartido: bool, supervisor: bool = False) -> None:
    _expediente_abogados(tenant_id, usuario_id, expediente_id, supervisor)
    compartir_documento_de_expediente(tenant_id, usuario_id, expediente_id, documento_id, compartido)


def compartir_documento_de_expediente(tenant_id: int, usuario_id: int, expediente_id: int, documento_id: int, compartido: bool) -> None:
    """Marca un documento de un expediente como visible (o no) en el enlace de solo lectura. Lo usan Abogados e Inmobiliaria; quien llama ya ha comprobado el permiso."""
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE documentos SET compartido_cliente = ? WHERE id = ? AND tenant_id = ? AND expediente_id = ? AND papelera_en IS NULL", (1 if compartido else 0, documento_id, tenant_id, expediente_id))
        if cur.rowcount == 0:
            raise ValueError("Documento no encontrado.")
        nucleo._evento(conn, expediente_id, "documento", f"Documento {'compartido con' if compartido else 'dejado de compartir con'} el cliente.", usuario_id)
        conn.commit()
    finally:
        conn.close()


def documento_publico(token: str, documento_id: int) -> dict | None:
    r = resolver_enlace(token)
    if r is None:
        return None
    conn = db.get_connection()
    try:
        ok = conn.execute("SELECT 1 FROM documentos WHERE id = ? AND expediente_id = ? AND compartido_cliente = 1 AND papelera_en IS NULL", (documento_id, r["expediente"]["id"])).fetchone()
    finally:
        conn.close()
    if ok is None:
        return None
    return almacen_documentos.leer_sin_usuario(r["enlace"]["tenant_id"], documento_id)


# --- Panel del asunto y registro del módulo ------------------------------------------------------------------------------------------------------
def _mensajes(tenant_id: int, expediente_id: int) -> dict:
    from . import mensajes_enlace
    return mensajes_enlace.contexto_panel(ID, tenant_id, expediente_id)


def contexto_panel(tenant_id: int, usuario_id: int, supervisor: bool, exp) -> dict:
    return {
        "datos": datos_de(exp), "partes": listar_partes(tenant_id, usuario_id, exp["id"], supervisor), "vistas": listar_vistas(tenant_id, usuario_id, supervisor, expediente_id=exp["id"]),
        "fondos": saldo(tenant_id, exp["id"]), "movimientos": listar_movimientos(tenant_id, usuario_id, exp["id"], supervisor), "minutas": listar_minutas(tenant_id, usuario_id, supervisor, expediente_id=exp["id"]),
        "enlaces": listar_enlaces(tenant_id, exp["id"]), "mensajes": _mensajes(tenant_id, exp["id"]), "ajustes": obtener_ajustes(tenant_id), "jurisdicciones": JURISDICCIONES, "roles": ROLES_PARTE, "tipos_vista": TIPOS_VISTA,
        "movimientos_tipos": MOVIMIENTOS, "plazos_tipicos": PLAZOS_TIPICOS, "es_judicial": exp["tipo"] == TIPO_JUDICIAL.id, "estado_llano": ESTADO_EN_LLANO.get(exp["estado"], ""),
    }


def _registrar() -> None:
    base = verticales.VERTICALES[ID]
    verticales.registrar(replace(
        base, disponible=True, tipos_expediente=(TIPO_JUDICIAL, TIPO_EXTRAJUDICIAL), esquema=crear_esquema, borrar_datos=borrar_datos_de_tenant,
        entradas_menu=(verticales.EntradaMenu("abogados", _l("Gabinete"), "abogados.panel", "briefcase"),),
        panel_expediente="abogados/_panel_expediente.html", tipos_con_panel=TIPOS, contexto_expediente=contexto_panel,
    ))


_registrar()
