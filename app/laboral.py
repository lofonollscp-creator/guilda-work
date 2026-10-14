"""Gestión laboral de los clientes (primera rebanada): los trabajadores de cada cliente de la gestoría.

Solo guarda lo mínimo para llevar su gestión: identificación (nombre, NIF/NIE, número de afiliación), puesto, tipo de contrato, jornada y fechas de alta y baja. **No guarda
salarios ni calcula nóminas** y **no genera obligaciones ni fechas laborales** (TC, 111/190, altas y bajas): esas reglas las valida el propietario antes de entrar en el catálogo
fiscal (ver app/vencimientos_fiscales.py), así que aquí solo hay datos, no calendario.

**Solo el nombre es obligatorio**: el resto de datos son opcionales y ninguno impide guardar por su formato o su rango (un nº de afiliación con letras, una jornada de 70 horas, una baja
anterior al alta o un NIF repetido se guardan y la pantalla lo señala con un aviso suave). Únicamente fallan los textos que no se pueden interpretar (una fecha o un número ilegibles),
porque guardarlos corrompería el dato.

Son datos personales de terceros (las personas que trabajan para el cliente): el acceso a la pestaña Laboral y cada alta, cambio o borrado quedan anotados en el registro de accesos
del cliente (`cliente_accesos`), que lo ven los supervisores; el borrado manda a la papelera y la papelera se vacía con el resto (app/rgpd.py:vaciar_papelera); y el cliente entra
en su exportación RGPD. Los permisos son los del cliente fiscal (oficinas, ver app/acceso.py)."""
from __future__ import annotations

import sqlite3
from datetime import date

from flask_babel import lazy_gettext as _l

from . import db, fiscal_identidad

TIPOS_CONTRATO = (
    ("indefinido", _l("Indefinido")), ("temporal", _l("Temporal")), ("practicas", _l("Prácticas")), ("formacion", _l("Formación")), ("otro", _l("Otro")),
)
_CLAVES_CONTRATO = {k for k, _ in TIPOS_CONTRATO}
CAMPOS = ("nombre", "nif", "naf", "puesto", "categoria", "convenio", "tipo_contrato", "jornada_horas_semana", "fecha_alta", "fecha_baja", "notas")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS trabajadores_cliente (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    nif TEXT,
    nif_normalizado TEXT,
    naf TEXT,
    puesto TEXT,
    categoria TEXT,
    convenio TEXT,
    tipo_contrato TEXT,
    jornada_horas_semana REAL,
    fecha_alta TEXT,
    fecha_baja TEXT,
    notas TEXT,
    creado_por INTEGER,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT,
    papelera_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_trabajadores_cliente ON trabajadores_cliente(cliente_fiscal_id, papelera_en);
DROP INDEX IF EXISTS ux_trabajadores_cliente_nif;
CREATE TABLE IF NOT EXISTS laboral_config (
    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    nominas_dia INTEGER,
    nominas_activo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS nominas_seguimiento (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    trabajador_id INTEGER NOT NULL REFERENCES trabajadores_cliente(id) ON DELETE CASCADE,
    periodo TEXT NOT NULL,
    estado TEXT NOT NULL,
    actualizado_por INTEGER,
    actualizado_en TEXT NOT NULL,
    UNIQUE (trabajador_id, periodo)
);
"""


def crear_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(ESQUEMA)
    for columna in ("categoria", "convenio"):          # bases creadas antes de existir estas columnas
        db._asegurar_columna(conn, "trabajadores_cliente", columna, "TEXT")
    db._asegurar_columna(conn, "vencimientos_fiscales", "trabajador_id", "INTEGER")      # el trabajador del que nace un plazo (ALTA-SS, BAJA-SS, CONTRATO)


def _texto(valor, maximo: int) -> str | None:
    valor = " ".join((valor or "").split())
    return valor[:maximo] or None


def _fecha(valor, campo: str) -> str | None:
    valor = (valor or "").strip()
    if not valor:
        return None
    try:
        return date.fromisoformat(valor[:10]).isoformat()
    except ValueError:
        raise ValueError(f"{campo}: fecha no válida.") from None


def _limpiar(datos: dict) -> dict:
    """Valida y normaliza los campos recibidos (solo los presentes). `ValueError` con un mensaje legible si algo no vale."""
    res: dict = {}
    if "nombre" in datos:
        nombre = _texto(datos["nombre"], 200)
        if not nombre:
            raise ValueError("Indica el nombre del trabajador.")
        res["nombre"] = nombre
    if "nif" in datos:
        res["nif"] = _texto(datos["nif"], 30)
        res["nif_normalizado"] = fiscal_identidad.normalizar(res["nif"]) or None
    if "naf" in datos:
        res["naf"] = _texto(datos["naf"], 30)
    if "puesto" in datos:
        res["puesto"] = _texto(datos["puesto"], 120)
    if "categoria" in datos:
        res["categoria"] = _texto(datos["categoria"], 120)
    if "convenio" in datos:
        res["convenio"] = _texto(datos["convenio"], 200)
    if "tipo_contrato" in datos:
        tipo = (datos["tipo_contrato"] or "").strip()
        if tipo and tipo not in _CLAVES_CONTRATO:
            raise ValueError("Tipo de contrato no válido.")
        res["tipo_contrato"] = tipo or None
    if "jornada_horas_semana" in datos:
        bruto = str(datos["jornada_horas_semana"] if datos["jornada_horas_semana"] is not None else "").strip().replace(",", ".")
        try:
            horas = float(bruto) if bruto else None
        except ValueError:
            raise ValueError("La jornada son horas a la semana (por ejemplo 40).") from None
        if horas is not None and not 0 <= horas < float("inf"):
            raise ValueError("La jornada son horas a la semana (por ejemplo 40).")
        res["jornada_horas_semana"] = horas
    for campo, etiqueta in (("fecha_alta", "Fecha de alta"), ("fecha_baja", "Fecha de baja")):
        if campo in datos:
            res[campo] = _fecha(datos[campo], etiqueta)
    if "notas" in datos:
        res["notas"] = (datos["notas"] or "").strip()[:2000] or None
    return res


def _cliente_vivo(conn, tenant_id: int, cliente_fiscal_id: int) -> None:
    if conn.execute("SELECT 1 FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_fiscal_id, tenant_id)).fetchone() is None:
        raise ValueError("Cliente no encontrado.")


def crear(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, nombre: str, **datos) -> int:
    """Da de alta un trabajador del cliente. Un mismo NIF no puede estar dos veces entre los trabajadores vivos de un cliente."""
    campos = _limpiar({"nombre": nombre, **{k: v for k, v in datos.items() if k in CAMPOS}})
    campos = {c: campos.get(c) for c in (*CAMPOS, "nif_normalizado")}
    conn = db.get_connection()
    try:
        _cliente_vivo(conn, tenant_id, cliente_fiscal_id)
        cur = conn.execute(
            f"INSERT INTO trabajadores_cliente (tenant_id, cliente_fiscal_id, {', '.join(campos)}, creado_por, creado_en) VALUES (?, ?, {', '.join('?' * len(campos))}, ?, ?)",
            (tenant_id, cliente_fiscal_id, *campos.values(), usuario_id, db.now_iso()))
        conn.commit()
        trabajador_id = cur.lastrowid
    finally:
        conn.close()
    sincronizar_plazos(tenant_id, trabajador_id)
    return trabajador_id


def obtener(tenant_id: int, trabajador_id: int):
    conn = db.get_connection()
    try:
        return conn.execute("SELECT * FROM trabajadores_cliente WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (trabajador_id, tenant_id)).fetchone()
    finally:
        conn.close()


def editar(tenant_id: int, trabajador_id: int, **datos) -> None:
    actual = obtener(tenant_id, trabajador_id)
    if actual is None:
        raise ValueError("Trabajador no encontrado.")
    campos = _limpiar({k: v for k, v in datos.items() if k in CAMPOS})
    if not campos:
        return
    conn = db.get_connection()
    try:
        conn.execute(f"UPDATE trabajadores_cliente SET {', '.join(f'{c} = ?' for c in campos)}, actualizado_en = ? WHERE id = ? AND tenant_id = ?",
                     (*campos.values(), db.now_iso(), trabajador_id, tenant_id))
        conn.commit()
    finally:
        conn.close()
    sincronizar_plazos(tenant_id, trabajador_id)


def eliminar(tenant_id: int, trabajador_id: int) -> bool:
    """Lo manda a la papelera (se vacía con el resto, ver app/rgpd.py)."""
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE trabajadores_cliente SET papelera_en = ? WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (db._marca_papelera(), trabajador_id, tenant_id))
        if cur.rowcount:      # sus plazos pendientes dejan de tener sentido; los presentados se conservan
            conn.execute("UPDATE vencimientos_fiscales SET papelera_en = ? WHERE trabajador_id = ? AND tenant_id = ? AND estado IN ('pendiente', 'fuera_plazo') AND papelera_en IS NULL",
                         (db._marca_papelera(), trabajador_id, tenant_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def listar(tenant_id: int, cliente_fiscal_id: int, hoy: str | None = None) -> list[dict]:
    """Los trabajadores vivos del cliente: primero los que están de alta hoy (sin baja o con baja futura), después los que ya causaron baja. Cada uno lleva `de_baja` y los avisos suaves
    `nif_repetido` y `baja_antes_del_alta` (no impiden guardar nada)."""
    hoy = hoy or date.today().isoformat()
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT * FROM trabajadores_cliente WHERE tenant_id = ? AND cliente_fiscal_id = ? AND papelera_en IS NULL", (tenant_id, cliente_fiscal_id)).fetchall()
        plazos: dict[int, list] = {}
        for v in conn.execute("SELECT id, trabajador_id, modelo, fecha_limite, estado FROM vencimientos_fiscales WHERE cliente_fiscal_id = ? AND trabajador_id IS NOT NULL AND papelera_en IS NULL "
                              "ORDER BY fecha_limite", (cliente_fiscal_id,)):
            plazos.setdefault(v["trabajador_id"], []).append(dict(v))
    finally:
        conn.close()
    repetidos: dict[str, int] = {}
    for f in filas:
        if f["nif_normalizado"]:
            repetidos[f["nif_normalizado"]] = repetidos.get(f["nif_normalizado"], 0) + 1
    res = [{**dict(f), "de_baja": bool(f["fecha_baja"] and f["fecha_baja"] < hoy),
            "nif_repetido": bool(f["nif_normalizado"] and repetidos[f["nif_normalizado"]] > 1),
            "baja_antes_del_alta": bool(f["fecha_alta"] and f["fecha_baja"] and f["fecha_baja"] < f["fecha_alta"]),
            "plazos": plazos.get(f["id"], [])} for f in filas]
    res.sort(key=lambda t: (t["de_baja"], t["nombre"].lower(), t["id"]))
    return res


# --- Calendario laboral del cliente (solo con reglas aprobadas, ver app/reglas_laborales.py) -----------------------------------------------------------

def tiene_trabajadores_de_alta(tenant_id: int, cliente_fiscal_id: int) -> bool:
    return any(not t["de_baja"] for t in listar(tenant_id, cliente_fiscal_id))


def propuestas_laborales(tenant_id: int, cliente_fiscal_id: int, anio: int) -> list[dict]:
    """Vencimientos laborales periódicos del año para un cliente: `TC` (mensual), `190` (anual) y el recordatorio mensual `NOMINAS` (día fijado por el despacho), con la fecha ajustada al siguiente día hábil del despacho.
    Vacío si el cliente no tiene ningún trabajador de alta o si la regla no está aprobada / el recordatorio no está activado (sin nada aprobado no se genera nada)."""
    from . import nucleo, perfil_fiscal, reglas_laborales
    reglas = reglas_laborales.vigentes()
    nominas = config(tenant_id)
    if not ({"tc", "m190"} & reglas.keys() or nominas["activo"]) or not tiene_trabajadores_de_alta(tenant_id, cliente_fiscal_id):
        return []
    propuestas = []
    if nominas["activo"]:          # el día lo fija cada despacho (no es una regla legal): recordatorio mensual de generar las nóminas
        propuestas += [{"modelo": "NOMINAS", **p} for p in reglas_laborales.periodos_mensuales({"dia": nominas["dia"], "mes_siguiente": 0}, anio)]
    if "tc" in reglas:
        propuestas += [{"modelo": "TC", **p} for p in reglas_laborales.periodos_mensuales(reglas["tc"], anio)]
    if "m190" in reglas:
        propuestas.append({"modelo": "190", **reglas_laborales.periodo_anual(reglas["m190"], anio)})
    return perfil_fiscal.ajustar_a_calendario(propuestas, nucleo.calendario_del_despacho(tenant_id, anios=(anio, anio + 1)))


def generar_laborales(tenant_id: int, cliente_fiscal_id: int) -> int:
    """Crea los vencimientos laborales (TC, 190) que le faltan al cliente, del año anterior y del actual; idempotente. Es lo que hace el botón de la pestaña Laboral (solo laborales:
    los modelos fiscales siguen su propio camino). Devuelve cuántos ha creado."""
    creados = 0
    for anio in (date.today().year - 1, date.today().year):
        for p in propuestas_laborales(tenant_id, cliente_fiscal_id, anio):
            if not db._existe_vencimiento_fiscal(tenant_id, cliente_fiscal_id, p["modelo"], p["periodo"]):
                db.crear_vencimiento_fiscal(tenant_id, cliente_fiscal_id, p["modelo"], p["periodo"], p["fecha_limite"])
                creados += 1
    for w in listar(tenant_id, cliente_fiscal_id):         # y los plazos de sus trabajadores (alta, baja, contrato) que falten
        creados += sincronizar_plazos(tenant_id, w["id"])
    return creados


# --- Plazos que nacen de un hecho del trabajador (alta, baja, contrato) -------------------------------------------------------------------------------

# clave de la regla -> (modelo del vencimiento, sufijo del periodo, campo del trabajador que es el hecho). El contrato se comunica desde su fecha de inicio (la de alta).
HECHOS = {"alta_ss": ("ALTA-SS", "alta", "fecha_alta"), "baja_ss": ("BAJA-SS", "baja", "fecha_baja"), "contrato": ("CONTRATO", "contrato", "fecha_alta")}


def plazo_desde_hecho(regla: dict, hecho: date, cal) -> date:
    """La fecha límite de un plazo de `regla` (`plazo` con signo y `unidad`) contado desde `hecho`. Un plazo negativo («antes de») que cae en inhábil retrocede al día hábil anterior en lugar de avanzar."""
    from . import calendario_plazos as cp
    limite = cp.vencimiento(hecho, int(regla["plazo"]), regla["unidad"], cal, desplazar_si_inhabil=False) if regla["unidad"] != "habiles" else cp.sumar_dias_habiles(hecho, int(regla["plazo"]), cal)
    if regla["unidad"] != "habiles" and not cal.es_habil(limite):
        limite = cp.anterior_habil(limite, cal) if int(regla["plazo"]) < 0 else cp.siguiente_habil(limite, cal)
    return limite


def sincronizar_plazos(tenant_id: int, trabajador_id: int) -> int:
    """Crea o actualiza los vencimientos `ALTA-SS`, `BAJA-SS` y `CONTRATO` del trabajador según las reglas **aprobadas** y sus fechas. El periodo es `T<id>-<hecho>` (único por trabajador y hecho;
    **no lleva el nombre**: es un dato personal). Solo se tocan los pendientes: uno ya presentado no cambia aunque cambie la fecha. Si se borra la fecha, el pendiente va a la papelera. Solo se crean los
    plazos que todavía no han vencido (dar de alta a alguien con un alta de hace años no llena el calendario de vencidos). Devuelve cuántos ha creado."""
    from . import nucleo, reglas_laborales
    t = obtener(tenant_id, trabajador_id)
    if t is None:
        return 0
    reglas = reglas_laborales.vigentes()
    creados = 0
    for clave, (modelo, sufijo, campo) in HECHOS.items():
        regla = reglas.get(clave)
        if regla is None:
            continue
        periodo = f"T{trabajador_id}-{sufijo}"
        conn = db.get_connection()
        try:
            existente = conn.execute("SELECT id, estado, fecha_limite FROM vencimientos_fiscales WHERE cliente_fiscal_id = ? AND modelo = ? AND periodo = ? AND papelera_en IS NULL AND rectifica_a IS NULL",
                                     (t["cliente_fiscal_id"], modelo, periodo)).fetchone()
            hecho = t[campo]
            if existente is not None and existente["estado"] not in ("pendiente", "fuera_plazo"):
                continue
            if not hecho:
                if existente is not None:
                    conn.execute("UPDATE vencimientos_fiscales SET papelera_en = ? WHERE id = ?", (db._marca_papelera(), existente["id"]))
                    conn.commit()
                continue
            fecha = date.fromisoformat(hecho)
            limite = plazo_desde_hecho(regla, fecha, nucleo.calendario_del_despacho(tenant_id, anios=(fecha.year - 1, fecha.year, fecha.year + 1, fecha.year + 2))).isoformat()
            if existente is not None:
                if existente["fecha_limite"] != limite:
                    conn.execute("UPDATE vencimientos_fiscales SET fecha_limite = ?, estado = 'pendiente', actualizado_en = ? WHERE id = ?", (limite, db.now_iso(), existente["id"]))
                    conn.commit()
                continue
        finally:
            conn.close()
        if limite < date.today().isoformat():
            continue
        vid = db.crear_vencimiento_fiscal(tenant_id, t["cliente_fiscal_id"], modelo, periodo, limite)
        conn = db.get_connection()
        try:
            conn.execute("UPDATE vencimientos_fiscales SET trabajador_id = ? WHERE id = ?", (trabajador_id, vid))
            conn.commit()
        finally:
            conn.close()
        creados += 1
    return creados


# --- Nóminas: recordatorio mensual y seguimiento (no se calcula ni se guarda ningún importe) ------------------------------------------------------

ESTADOS_NOMINA = (("pendiente", _l("Pendiente")), ("generada", _l("Generada")), ("enviada", _l("Enviada")), ("firmada", _l("Firmada")))
_ORDEN_ESTADOS = [k for k, _ in ESTADOS_NOMINA]


def config(tenant_id: int) -> dict:
    """El recordatorio de nóminas del despacho: `activo` y `dia` del mes (preferencia interna, no una regla legal). Sin configurar = desactivado."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT nominas_dia, nominas_activo FROM laboral_config WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    dia = f["nominas_dia"] if f else None
    return {"dia": dia, "activo": bool(f and f["nominas_activo"] and dia)}


def guardar_config(tenant_id: int, usuario_id: int, *, dia, activo: bool) -> None:
    """Solo la dirección del despacho (supervisores). Con `activo` hace falta un día del mes entre 1 y 31."""
    from . import acceso, auditoria
    if not acceso.es_directivo(usuario_id) or db.tenant_de_usuario(usuario_id) is None or db.tenant_de_usuario(usuario_id)["id"] != tenant_id:
        raise ValueError("Solo la dirección del despacho (supervisores) puede cambiar el recordatorio de nóminas.")
    try:
        dia = int(str(dia).strip()) if str(dia or "").strip() else None
    except ValueError:
        raise ValueError("Día del recordatorio: indica un número entre 1 y 31.") from None
    if dia is not None and not 1 <= dia <= 31:
        raise ValueError("Día del recordatorio: indica un número entre 1 y 31.")
    if activo and dia is None:
        raise ValueError("Para activar el recordatorio indica el día del mes.")
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO laboral_config (tenant_id, nominas_dia, nominas_activo) VALUES (?, ?, ?) ON CONFLICT(tenant_id) DO UPDATE SET nominas_dia = excluded.nominas_dia, nominas_activo = excluded.nominas_activo",
                     (tenant_id, dia, int(bool(activo))))
        auditoria.registrar(tenant_id, usuario_id, "laboral.config", "despacho", tenant_id, {"nominas_dia": dia, "nominas_activo": bool(activo)}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def periodo_actual(hoy: date | None = None) -> str:
    return (hoy or date.today()).strftime("%Y-%m")


def seguimiento_nominas(tenant_id: int, cliente_fiscal_id: int, periodo: str) -> dict:
    """Cuadrícula del mes: cada trabajador de alta con el estado de su nómina (por defecto `pendiente`), si todas están ya enviadas, y el vencimiento NOMINAS del mes si existe y sigue pendiente."""
    trabajadores = [t for t in listar(tenant_id, cliente_fiscal_id) if not t["de_baja"]]
    conn = db.get_connection()
    try:
        estados = {f["trabajador_id"]: f["estado"] for f in conn.execute("SELECT trabajador_id, estado FROM nominas_seguimiento WHERE tenant_id = ? AND periodo = ?", (tenant_id, periodo))}
        venc = conn.execute("SELECT id, estado FROM vencimientos_fiscales WHERE tenant_id = ? AND cliente_fiscal_id = ? AND modelo = 'NOMINAS' AND periodo = ? AND papelera_en IS NULL",
                            (tenant_id, cliente_fiscal_id, periodo)).fetchone()
    finally:
        conn.close()
    filas = [{"trabajador_id": t["id"], "nombre": t["nombre"], "estado": estados.get(t["id"], "pendiente")} for t in trabajadores]
    for f in filas:
        i = _ORDEN_ESTADOS.index(f["estado"])
        f["siguiente"] = _ORDEN_ESTADOS[i + 1] if i + 1 < len(_ORDEN_ESTADOS) else None
        f["anterior"] = _ORDEN_ESTADOS[i - 1] if i else None
    todas_enviadas = bool(filas) and all(f["estado"] in ("enviada", "firmada") for f in filas)
    return {"periodo": periodo, "filas": filas, "todas_enviadas": todas_enviadas,
            "sugerir_presentado": bool(todas_enviadas and venc is not None and venc["estado"] in ("pendiente", "fuera_plazo"))}


def fijar_estado_nomina(tenant_id: int, usuario_id: int, trabajador_id: int, periodo: str, estado: str) -> None:
    """Anota en qué punto está la nómina del trabajador ese mes. `ValueError` si el estado, el periodo o el trabajador no valen. No guarda ningún importe."""
    if estado not in _ORDEN_ESTADOS:
        raise ValueError("Estado de nómina no válido.")
    try:
        date.fromisoformat(f"{periodo}-01")
    except ValueError:
        raise ValueError("Periodo no válido (AAAA-MM).") from None
    if obtener(tenant_id, trabajador_id) is None:
        raise ValueError("Trabajador no encontrado.")
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO nominas_seguimiento (tenant_id, trabajador_id, periodo, estado, actualizado_por, actualizado_en) VALUES (?, ?, ?, ?, ?, ?) "
                     "ON CONFLICT(trabajador_id, periodo) DO UPDATE SET estado = excluded.estado, actualizado_por = excluded.actualizado_por, actualizado_en = excluded.actualizado_en",
                     (tenant_id, trabajador_id, periodo, estado, usuario_id, db.now_iso()))
        conn.commit()
    finally:
        conn.close()
