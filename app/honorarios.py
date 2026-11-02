"""Reglas de honorarios por tramos para los vencimientos fiscales: proponen cuánto cobrar por presentar un modelo.

- Cada **regla** tiene una prioridad (el número más bajo va primero) y filtra por modelo (303, 130…) y por forma jurídica del titular; un filtro vacío vale para todos. Aplica **la primera regla
  activa que encaja**, y las siguientes ni se miran.
- Tres formas de calcular, siempre en céntimos: **fijo**; **por apunte** (base + importe por cada apunte del periodo, con mínimo); **por tramos** (según el número de apuntes del periodo, el
  importe del primer tramo que lo contiene; el último tramo queda abierto).
- Los apuntes son los del periodo del vencimiento («2T 2026» = abril-junio, «2025» = todo el año) que no están anulados. Los periodos de otro formato no cuentan apuntes: solo sirven las reglas fijas.
- **Proponer no cobra nada.** La propuesta enseña la regla aplicada y el cálculo; quien dirige el despacho (o el revisor fiscal) la **confirma**, y queda guardada con el desglose tal y como estaba,
  aunque la regla cambie después. Luego se marca como facturada (con la referencia de la factura) o se anula con motivo. La factura se sigue emitiendo en la herramienta de facturación del despacho."""
from __future__ import annotations

import json
import re

from . import acceso, auditoria, db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS honorarios_reglas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    prioridad INTEGER NOT NULL DEFAULT 100,
    activa INTEGER NOT NULL DEFAULT 1,
    modelo TEXT NOT NULL DEFAULT '',
    forma_juridica TEXT NOT NULL DEFAULT '',
    calculo TEXT NOT NULL CHECK (calculo IN ('fijo', 'por_apunte', 'tramos')),
    importe_centimos INTEGER NOT NULL DEFAULT 0,
    unidad_centimos INTEGER NOT NULL DEFAULT 0,
    minimo_centimos INTEGER NOT NULL DEFAULT 0,
    tramos TEXT NOT NULL DEFAULT '[]',
    creada_por INTEGER,
    creada_en TEXT NOT NULL,
    actualizada_en TEXT,
    papelera_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_honorarios_reglas ON honorarios_reglas(tenant_id, prioridad);
CREATE TABLE IF NOT EXISTS honorarios_aplicados (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    vencimiento_id INTEGER NOT NULL,
    cliente_fiscal_id INTEGER NOT NULL,
    regla_id INTEGER,
    regla_nombre TEXT NOT NULL,
    concepto TEXT NOT NULL,
    unidades INTEGER NOT NULL DEFAULT 0,
    importe_centimos INTEGER NOT NULL,
    desglose TEXT NOT NULL DEFAULT '{}',
    estado TEXT NOT NULL DEFAULT 'confirmado' CHECK (estado IN ('confirmado', 'facturado', 'anulado')),
    confirmado_por INTEGER,
    confirmado_en TEXT NOT NULL,
    facturado_en TEXT,
    referencia_factura TEXT,
    anulado_en TEXT,
    anulado_motivo TEXT
);
CREATE INDEX IF NOT EXISTS idx_honorarios_aplicados ON honorarios_aplicados(tenant_id, vencimiento_id);
CREATE INDEX IF NOT EXISTS idx_honorarios_aplicados_cliente ON honorarios_aplicados(tenant_id, cliente_fiscal_id, estado);
"""

CALCULOS = {"fijo": "Importe fijo", "por_apunte": "Base más importe por apunte", "tramos": "Por tramos según el número de apuntes"}
FORMAS_JURIDICAS = ("persona_fisica", "sociedad", "comunidad_bienes", "otra")
MAX_IMPORTE = 100_000_000                    # 1.000.000,00 €
MAX_TRAMOS = 20
MAX_PENDIENTES = 200


class ErrorHonorarios(Exception):
    """Un error con un texto que se puede enseñar tal cual."""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _ahora() -> str:
    return db.now_iso()


def _exigir_dirigir(tenant_id: int, usuario_id: int) -> None:
    if not acceso.puede_autorizar(tenant_id, usuario_id):
        raise ErrorHonorarios("Solo la dirección del despacho o el revisor fiscal pueden gestionar los honorarios.")


def _centimos(valor, campo: str, *, obligatorio: bool = False) -> int:
    texto = str(valor if valor is not None else "").strip().replace("€", "").replace(" ", "")
    if not texto:
        if obligatorio:
            raise ErrorHonorarios(f"Falta el importe de «{campo}».")
        return 0
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    if not re.fullmatch(r"\d{1,9}(\.\d{1,2})?", texto):
        raise ErrorHonorarios(f"El importe de «{campo}» no es válido.")
    c = round(float(texto) * 100)
    if c > MAX_IMPORTE:
        raise ErrorHonorarios(f"El importe de «{campo}» es demasiado grande.")
    return c


def _tramos(valor) -> list[dict]:
    """Tramos `[{"hasta": 10, "importe_centimos": 5000}, …]` en orden creciente; el último, abierto (`hasta` vacío)."""
    if isinstance(valor, str):
        try:
            valor = json.loads(valor or "[]")
        except ValueError:
            raise ErrorHonorarios("Los tramos no son válidos.") from None
    if not isinstance(valor, list) or not valor:
        raise ErrorHonorarios("Añade al menos un tramo.")
    if len(valor) > MAX_TRAMOS:
        raise ErrorHonorarios(f"Máximo {MAX_TRAMOS} tramos.")
    salida, anterior = [], 0
    for i, t in enumerate(valor, 1):
        if not isinstance(t, dict):
            raise ErrorHonorarios("Los tramos no son válidos.")
        hasta = t.get("hasta")
        hasta = None if hasta in (None, "") else hasta
        if hasta is not None:
            try:
                hasta = int(hasta)
            except (TypeError, ValueError):
                raise ErrorHonorarios(f"El límite del tramo {i} no es un número.") from None
            if hasta <= anterior:
                raise ErrorHonorarios(f"El límite del tramo {i} debe ser mayor que el del anterior ({anterior}).")
            anterior = hasta
        elif i != len(valor):
            raise ErrorHonorarios("Solo el último tramo puede quedar sin límite.")
        importe = t.get("importe_centimos")
        if importe is None:
            importe = _centimos(t.get("importe"), f"tramo {i}", obligatorio=True)
        if not isinstance(importe, int) or not 0 <= importe <= MAX_IMPORTE:
            raise ErrorHonorarios(f"El importe del tramo {i} no es válido.")
        salida.append({"hasta": hasta, "importe_centimos": importe})
    if salida[-1]["hasta"] is not None:
        raise ErrorHonorarios("El último tramo debe quedar sin límite («y más»), para que todo número de apuntes tenga precio.")
    return salida


def tramos_desde_texto(texto: str) -> list[dict]:
    """Un tramo por línea: «hasta 10: 60,00» y, la última, «resto: 45,00»."""
    salida = []
    for linea in (texto or "").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        m = re.fullmatch(r"(?:hasta\s+(\d+)|resto|y m[aá]s)\s*:?\s*([\d.,]+)\s*€?", linea, re.I)
        if not m:
            raise ErrorHonorarios(f"No entiendo la línea «{linea[:40]}». Usa «hasta 10: 60,00» y, en la última, «resto: 45,00».")
        salida.append({"hasta": int(m.group(1)) if m.group(1) else None, "importe": m.group(2)})
    return salida


def tramos_a_texto(tramos: list[dict]) -> str:
    return "\n".join(f"{'hasta ' + str(t['hasta']) if t['hasta'] is not None else 'resto'}: {t['importe_centimos'] // 100},{t['importe_centimos'] % 100:02d}" for t in tramos)


def _validar(datos: dict) -> dict:
    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        raise ErrorHonorarios("Pon un nombre a la regla.")
    calculo = datos.get("calculo")
    if calculo not in CALCULOS:
        raise ErrorHonorarios("Elige cómo se calcula.")
    forma = (datos.get("forma_juridica") or "").strip()
    if forma and forma not in FORMAS_JURIDICAS:
        raise ErrorHonorarios("La forma jurídica no es válida.")
    try:
        prioridad = int(datos.get("prioridad") if datos.get("prioridad") not in (None, "") else 100)
    except (TypeError, ValueError):
        raise ErrorHonorarios("La prioridad debe ser un número.") from None
    if not 1 <= prioridad <= 9999:
        raise ErrorHonorarios("La prioridad va de 1 a 9999.")
    r = {"nombre": nombre[:120], "prioridad": prioridad, "modelo": re.sub(r"[^0-9A-Za-z]", "", (datos.get("modelo") or ""))[:6].upper(), "forma_juridica": forma, "calculo": calculo,
         "importe_centimos": 0, "unidad_centimos": 0, "minimo_centimos": 0, "tramos": "[]"}
    if calculo == "fijo":
        r["importe_centimos"] = _centimos(datos.get("importe"), "importe", obligatorio=True)
    elif calculo == "por_apunte":
        r["importe_centimos"] = _centimos(datos.get("importe"), "base")
        r["unidad_centimos"] = _centimos(datos.get("unidad"), "por apunte", obligatorio=True)
        r["minimo_centimos"] = _centimos(datos.get("minimo"), "mínimo")
    else:
        r["tramos"] = json.dumps(_tramos(datos.get("tramos")))
    return r


def listar_reglas(tenant_id: int, *, solo_activas: bool = False) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT * FROM honorarios_reglas WHERE tenant_id = ? AND papelera_en IS NULL" + (" AND activa = 1" if solo_activas else "") + " ORDER BY prioridad, id", (tenant_id,)).fetchall()
    finally:
        conn.close()
    salida = []
    for f in filas:
        r = dict(f)
        r["tramos"] = json.loads(r["tramos"] or "[]")
        salida.append(r)
    return salida


def obtener_regla(tenant_id: int, regla_id: int) -> dict | None:
    return next((r for r in listar_reglas(tenant_id) if r["id"] == regla_id), None)


def crear_regla(tenant_id: int, usuario_id: int, datos: dict) -> int:
    _exigir_dirigir(tenant_id, usuario_id)
    r = _validar(datos)
    conn = db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO honorarios_reglas (tenant_id, nombre, prioridad, activa, modelo, forma_juridica, calculo, importe_centimos, unidad_centimos, minimo_centimos, tramos, creada_por, creada_en) "
            "VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, r["nombre"], r["prioridad"], r["modelo"], r["forma_juridica"], r["calculo"], r["importe_centimos"], r["unidad_centimos"], r["minimo_centimos"], r["tramos"], usuario_id, _ahora()))
        regla_id = cur.lastrowid
        auditoria.registrar(tenant_id, usuario_id, "honorarios.regla.crear", "honorarios_regla", regla_id, {"nombre": r["nombre"], "calculo": r["calculo"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return regla_id


def editar_regla(tenant_id: int, usuario_id: int, regla_id: int, datos: dict) -> None:
    _exigir_dirigir(tenant_id, usuario_id)
    if obtener_regla(tenant_id, regla_id) is None:
        raise ErrorHonorarios("La regla no existe.")
    r = _validar(datos)
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE honorarios_reglas SET nombre = ?, prioridad = ?, modelo = ?, forma_juridica = ?, calculo = ?, importe_centimos = ?, unidad_centimos = ?, minimo_centimos = ?, tramos = ?, actualizada_en = ? "
            "WHERE id = ? AND tenant_id = ?",
            (r["nombre"], r["prioridad"], r["modelo"], r["forma_juridica"], r["calculo"], r["importe_centimos"], r["unidad_centimos"], r["minimo_centimos"], r["tramos"], _ahora(), regla_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "honorarios.regla.editar", "honorarios_regla", regla_id, {"nombre": r["nombre"], "calculo": r["calculo"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def alternar_regla(tenant_id: int, usuario_id: int, regla_id: int) -> bool:
    """Activa o desactiva una regla. Devuelve si queda activa."""
    _exigir_dirigir(tenant_id, usuario_id)
    r = obtener_regla(tenant_id, regla_id)
    if r is None:
        raise ErrorHonorarios("La regla no existe.")
    nueva = 0 if r["activa"] else 1
    conn = db.get_connection()
    try:
        conn.execute("UPDATE honorarios_reglas SET activa = ?, actualizada_en = ? WHERE id = ? AND tenant_id = ?", (nueva, _ahora(), regla_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "honorarios.regla.activar" if nueva else "honorarios.regla.desactivar", "honorarios_regla", regla_id, {"nombre": r["nombre"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return bool(nueva)


def eliminar_regla(tenant_id: int, usuario_id: int, regla_id: int) -> None:
    """A la papelera: los honorarios ya confirmados conservan su desglose."""
    _exigir_dirigir(tenant_id, usuario_id)
    r = obtener_regla(tenant_id, regla_id)
    if r is None:
        raise ErrorHonorarios("La regla no existe.")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE honorarios_reglas SET papelera_en = ?, activa = 0 WHERE id = ? AND tenant_id = ?", (_ahora(), regla_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "honorarios.regla.eliminar", "honorarios_regla", regla_id, {"nombre": r["nombre"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()


# ── cálculo ───────────────────────────────────────────────────────────────

def rango_del_periodo(periodo: str) -> tuple[str, str] | None:
    """«2T 2026» o «2026-T2» -> (2026-04-01, 2026-06-30); «2025» -> todo el año. Otro formato: None."""
    texto = (periodo or "").strip()
    m = re.fullmatch(r"([1-4])T (\d{4})", texto) or None
    if m:
        t, a = int(m.group(1)), int(m.group(2))
    else:
        m = re.fullmatch(r"(\d{4})-T([1-4])", texto)
        if m:
            a, t = int(m.group(1)), int(m.group(2))
        elif re.fullmatch(r"\d{4}", texto):
            return f"{texto}-01-01", f"{texto}-12-31"
        else:
            return None
    mes_ini = 3 * (t - 1) + 1
    fin = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}[t]
    return f"{a}-{mes_ini:02d}-01", f"{a}-{fin}"


def contar_apuntes(tenant_id: int, cliente_fiscal_id: int, periodo: str) -> int | None:
    """Apuntes no anulados del titular en el periodo. None si el periodo no tiene un formato que se pueda acotar."""
    rango = rango_del_periodo(periodo)
    if rango is None:
        return None
    conn = db.get_connection()
    try:
        return conn.execute("SELECT COUNT(*) AS n FROM fiscal_apuntes WHERE tenant_id = ? AND cliente_fiscal_id = ? AND anulado_en IS NULL AND fecha_expedicion >= ? AND fecha_expedicion <= ?",
                            (tenant_id, cliente_fiscal_id, rango[0], rango[1])).fetchone()["n"]
    finally:
        conn.close()


def _importe(regla: dict, n: int) -> tuple[int, dict]:
    """(importe en céntimos, desglose) de una regla para `n` apuntes."""
    if regla["calculo"] == "fijo":
        return regla["importe_centimos"], {"calculo": "fijo", "importe_centimos": regla["importe_centimos"]}
    if regla["calculo"] == "por_apunte":
        bruto = regla["importe_centimos"] + regla["unidad_centimos"] * n
        total = max(bruto, regla["minimo_centimos"])
        return total, {"calculo": "por_apunte", "base_centimos": regla["importe_centimos"], "unidad_centimos": regla["unidad_centimos"], "apuntes": n, "minimo_centimos": regla["minimo_centimos"],
                       "minimo_aplicado": total != bruto}
    for i, t in enumerate(regla["tramos"], 1):
        if t["hasta"] is None or n <= t["hasta"]:
            return t["importe_centimos"], {"calculo": "tramos", "apuntes": n, "tramo": i, "hasta": t["hasta"], "importe_centimos": t["importe_centimos"]}
    return regla["tramos"][-1]["importe_centimos"], {"calculo": "tramos", "apuntes": n, "tramo": len(regla["tramos"]), "hasta": None, "importe_centimos": regla["tramos"][-1]["importe_centimos"]}


def regla_que_aplica(reglas: list[dict], modelo: str, forma_juridica: str) -> dict | None:
    """La primera regla activa (por prioridad) cuyos filtros encajan."""
    modelo = (modelo or "").strip().upper()
    for r in reglas:
        if not r["activa"]:
            continue
        if r["modelo"] and r["modelo"] != modelo:
            continue
        if r["forma_juridica"] and r["forma_juridica"] != (forma_juridica or ""):
            continue
        return r
    return None


def calcular(reglas: list[dict], *, modelo: str, forma_juridica: str, apuntes: int | None) -> dict:
    """Propuesta para un caso concreto: `{regla, importe_centimos, desglose, motivo}`. Sin regla, `regla` es None y `motivo` dice por qué."""
    r = regla_que_aplica(reglas, modelo, forma_juridica)
    if r is None:
        return {"regla": None, "importe_centimos": None, "desglose": {}, "motivo": "Ninguna regla activa encaja con este modelo y esta forma jurídica."}
    if apuntes is None and r["calculo"] != "fijo":
        return {"regla": r, "importe_centimos": None, "desglose": {}, "motivo": "El periodo no permite contar apuntes: usa una regla de importe fijo para este caso."}
    importe, desglose = _importe(r, apuntes or 0)
    return {"regla": r, "importe_centimos": importe, "desglose": desglose, "motivo": ""}


def simular(tenant_id: int, modelo: str, forma_juridica: str, apuntes) -> dict:
    """Para probar las reglas sin tocar nada: qué saldría con ese modelo, esa forma jurídica y ese número de apuntes."""
    try:
        n = int(apuntes)
    except (TypeError, ValueError):
        n = 0
    return calcular(listar_reglas(tenant_id), modelo=modelo, forma_juridica=forma_juridica, apuntes=max(0, n))


def _vencimiento(conn, tenant_id: int, usuario_id: int, vencimiento_id: int):
    v = conn.execute(
        "SELECT v.id, v.cliente_fiscal_id, v.modelo, v.periodo, v.estado, v.fecha_limite, c.nombre AS cliente FROM vencimientos_fiscales v "
        "JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id AND c.tenant_id = v.tenant_id WHERE v.id = ? AND v.tenant_id = ? AND v.papelera_en IS NULL", (vencimiento_id, tenant_id)).fetchone()
    if v is None or not acceso.puede_ver_cliente(tenant_id, usuario_id, v["cliente_fiscal_id"]):
        raise ErrorHonorarios("El vencimiento no existe.")
    return v


def _forma_juridica(conn, tenant_id: int, cliente_fiscal_id: int) -> str:
    try:
        f = conn.execute("SELECT forma_juridica FROM fiscal_perfiles WHERE tenant_id = ? AND cliente_fiscal_id = ? AND (vigente_hasta IS NULL OR vigente_hasta >= ?) ORDER BY vigente_desde DESC, id DESC",
                         (tenant_id, cliente_fiscal_id, db.now_iso()[:10])).fetchone()
    except Exception:                                     # noqa: BLE001 -- sin perfil fiscal las reglas sin filtro de forma jurídica siguen valiendo
        return ""
    return (f["forma_juridica"] if f else "") or ""


def aplicado_de(tenant_id: int, vencimiento_id: int) -> dict | None:
    """El honorario vigente (confirmado o facturado) de un vencimiento."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM honorarios_aplicados WHERE tenant_id = ? AND vencimiento_id = ? AND estado != 'anulado' ORDER BY id DESC", (tenant_id, vencimiento_id)).fetchone()
    finally:
        conn.close()
    if f is None:
        return None
    a = dict(f)
    a["desglose"] = json.loads(a["desglose"] or "{}")
    return a


def proponer(tenant_id: int, usuario_id: int, vencimiento_id: int, reglas: list[dict] | None = None) -> dict:
    """La propuesta para un vencimiento (no guarda nada): `{vencimiento, apuntes, forma_juridica, aplicado, + calcular()}`."""
    conn = db.get_connection()
    try:
        v = _vencimiento(conn, tenant_id, usuario_id, vencimiento_id)
        forma = _forma_juridica(conn, tenant_id, v["cliente_fiscal_id"])
    finally:
        conn.close()
    n = contar_apuntes(tenant_id, v["cliente_fiscal_id"], v["periodo"])
    p = calcular(reglas if reglas is not None else listar_reglas(tenant_id), modelo=v["modelo"], forma_juridica=forma, apuntes=n)
    p.update({"vencimiento": dict(v), "apuntes": n, "forma_juridica": forma, "aplicado": aplicado_de(tenant_id, vencimiento_id)})
    return p


def _concepto(v: dict) -> str:
    return f"Honorarios modelo {v['modelo']} {v['periodo']}"


def confirmar(tenant_id: int, usuario_id: int, vencimiento_id: int, *, importe=None) -> int:
    """Guarda el honorario propuesto para el vencimiento. Si quien confirma indica otro `importe`, queda ese, y el desglose conserva el calculado."""
    _exigir_dirigir(tenant_id, usuario_id)
    p = proponer(tenant_id, usuario_id, vencimiento_id)
    if p["aplicado"]:
        raise ErrorHonorarios("Este vencimiento ya tiene un honorario confirmado; anúlalo antes de fijar otro.")
    calculado = p["importe_centimos"]
    final = _centimos(importe, "importe", obligatorio=True) if importe not in (None, "") else calculado
    if final is None:
        raise ErrorHonorarios(p["motivo"] or "No hay importe que confirmar.")
    desglose = dict(p["desglose"])
    if calculado is not None and final != calculado:
        desglose["calculado_centimos"] = calculado
        desglose["ajustado_a_mano"] = True
    v = p["vencimiento"]
    conn = db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO honorarios_aplicados (tenant_id, vencimiento_id, cliente_fiscal_id, regla_id, regla_nombre, concepto, unidades, importe_centimos, desglose, confirmado_por, confirmado_en) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, vencimiento_id, v["cliente_fiscal_id"], p["regla"]["id"] if p["regla"] else None, p["regla"]["nombre"] if p["regla"] else "A mano", _concepto(v), p["apuntes"] or 0, final,
             json.dumps(desglose), usuario_id, _ahora()))
        aplicado_id = cur.lastrowid
        auditoria.registrar(tenant_id, usuario_id, "honorarios.confirmar", "cliente_fiscal", v["cliente_fiscal_id"],
                            {"vencimiento_id": vencimiento_id, "importe_centimos": final, "regla": p["regla"]["nombre"] if p["regla"] else None, "ajustado_a_mano": bool(desglose.get("ajustado_a_mano"))}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return aplicado_id


def _cambiar_estado(tenant_id: int, usuario_id: int, aplicado_id: int, nuevo: str, campos: dict, accion: str) -> None:
    _exigir_dirigir(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        a = conn.execute("SELECT * FROM honorarios_aplicados WHERE id = ? AND tenant_id = ?", (aplicado_id, tenant_id)).fetchone()
        if a is None or not acceso.puede_ver_cliente(tenant_id, usuario_id, a["cliente_fiscal_id"]):
            raise ErrorHonorarios("El honorario no existe.")
        if a["estado"] == "anulado" or (nuevo == "facturado" and a["estado"] != "confirmado"):
            raise ErrorHonorarios("Este honorario ya no admite ese cambio.")
        sets = ", ".join(f"{k} = ?" for k in campos)
        conn.execute(f"UPDATE honorarios_aplicados SET estado = ?, {sets} WHERE id = ? AND tenant_id = ?", (nuevo, *campos.values(), aplicado_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, accion, "cliente_fiscal", a["cliente_fiscal_id"], {"vencimiento_id": a["vencimiento_id"], "importe_centimos": a["importe_centimos"], **{k: v for k, v in campos.items() if k != "facturado_en" and k != "anulado_en"}}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def marcar_facturado(tenant_id: int, usuario_id: int, aplicado_id: int, referencia: str) -> None:
    referencia = (referencia or "").strip()[:60]
    if not referencia:
        raise ErrorHonorarios("Indica la referencia de la factura.")
    _cambiar_estado(tenant_id, usuario_id, aplicado_id, "facturado", {"facturado_en": _ahora(), "referencia_factura": referencia}, "honorarios.facturar")


def anular(tenant_id: int, usuario_id: int, aplicado_id: int, motivo: str) -> None:
    motivo = (motivo or "").strip()[:300]
    if len(motivo) < 3:
        raise ErrorHonorarios("Escribe el motivo de la anulación.")
    _cambiar_estado(tenant_id, usuario_id, aplicado_id, "anulado", {"anulado_en": _ahora(), "anulado_motivo": motivo}, "honorarios.anular")


# ── listados ──────────────────────────────────────────────────────────────

def pendientes_de_confirmar(tenant_id: int, usuario_id: int) -> list[dict]:
    """Vencimientos ya presentados que aún no tienen honorario, con su propuesta. Los más recientes primero; los que la persona no ve, fuera."""
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT v.id FROM vencimientos_fiscales v WHERE v.tenant_id = ? AND v.estado = 'presentado' AND v.papelera_en IS NULL AND NOT EXISTS "
            "(SELECT 1 FROM honorarios_aplicados h WHERE h.tenant_id = v.tenant_id AND h.vencimiento_id = v.id AND h.estado != 'anulado') ORDER BY v.fecha_limite DESC, v.id DESC LIMIT ?",
            (tenant_id, MAX_PENDIENTES * 3)).fetchall()
    finally:
        conn.close()
    reglas = listar_reglas(tenant_id, solo_activas=True)
    salida = []
    for f in filas:
        if len(salida) >= MAX_PENDIENTES:
            break
        try:
            p = proponer(tenant_id, usuario_id, f["id"], reglas)
        except ErrorHonorarios:
            continue
        if visibles is not None and p["vencimiento"]["cliente_fiscal_id"] not in visibles:
            continue
        salida.append(p)
    return salida


def aplicados(tenant_id: int, usuario_id: int, *, estado: str | None = None, limite: int = 200) -> list[dict]:
    """Honorarios confirmados, facturados o anulados de los titulares que la persona ve."""
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    sql = ("SELECT h.*, c.nombre AS cliente FROM honorarios_aplicados h JOIN clientes_fiscales c ON c.id = h.cliente_fiscal_id AND c.tenant_id = h.tenant_id WHERE h.tenant_id = ?")
    args: list = [tenant_id]
    if estado in ("confirmado", "facturado", "anulado"):
        sql += " AND h.estado = ?"
        args.append(estado)
    conn = db.get_connection()
    try:
        filas = conn.execute(sql + " ORDER BY h.id DESC LIMIT ?", (*args, limite * 3)).fetchall()
    finally:
        conn.close()
    salida = []
    for f in filas:
        if visibles is not None and f["cliente_fiscal_id"] not in visibles:
            continue
        a = dict(f)
        a["desglose"] = json.loads(a["desglose"] or "{}")
        salida.append(a)
        if len(salida) >= limite:
            break
    return salida


def euros(centimos) -> str:
    if centimos is None:
        return "—"
    c = int(centimos)
    entero, resto = divmod(abs(c), 100)
    return f"{'-' if c < 0 else ''}{entero:,}".replace(",", ".") + f",{resto:02d} €"

