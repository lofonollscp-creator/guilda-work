"""Cambios en lote sobre los vencimientos fiscales, siempre en tres pasos: **proponer → confirmar → deshacer** (el mismo patrón que los cambios en lote del Comercial).

- **Proponer no cambia nada.** Guarda qué vencimientos cambiarían (con su estado de ANTES), cuáles se omiten y por qué, y enseña el resumen.
- **Aplicar exige confirmación** de quien propuso, dentro de una hora. Si un vencimiento cambió entre la propuesta y la confirmación, se omite: no se pisa el trabajo de otra persona.
- **Deshacer** durante 90 días: cada vencimiento vuelve a su estado anterior, salvo los que se hayan vuelto a cambiar después.
- Dos acciones: **cambiar de responsable** y **posponer la fecha de seguimiento**. Esta última mueve la fecha que sigue el despacho, NO el plazo legal de presentación: por eso pide un motivo, que
  queda en la auditoría. Solo se tocan los vencimientos pendientes; marcar como presentado es una declaración de quien presenta y no se hace en lote.
- Cada persona ve y cambia solo los titulares que su rol le deja ver; quien solo audita, no propone. Máximo 500 vencimientos por cambio."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from . import acceso, auditoria, db, db_fiscal

ESQUEMA = """
CREATE TABLE IF NOT EXISTS fiscal_acciones_masivas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('reasignar', 'posponer')),
    parametros TEXT NOT NULL DEFAULT '{}',
    descripcion TEXT NOT NULL,
    afectados TEXT NOT NULL DEFAULT '[]',
    omitidos TEXT NOT NULL DEFAULT '[]',
    estado TEXT NOT NULL DEFAULT 'propuesta' CHECK (estado IN ('propuesta', 'aplicada', 'deshecha', 'cancelada')),
    creada_en TEXT NOT NULL,
    aplicada_en TEXT,
    deshecha_en TEXT,
    caduca_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_fiscal_acciones_masivas ON fiscal_acciones_masivas(tenant_id, creada_en);
"""

TIPOS = {"reasignar": "Cambiar de responsable", "posponer": "Posponer la fecha de seguimiento"}
MAX_VENCIMIENTOS = 500
MINUTOS_PARA_CONFIRMAR = 60
DIAS_PARA_DESHACER = 90
MAX_DIAS = 90
CAMPOS_ANTES = ("usuario_id", "fecha_limite", "estado")


class ErrorMasivoFiscal(ValueError):
    """Un error con un texto que se puede enseñar tal cual."""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _ahora() -> datetime:
    return datetime.now().replace(microsecond=0)


def _fila(f) -> dict:
    d = dict(f)
    for k in ("parametros", "afectados", "omitidos"):
        try:
            d[k] = json.loads(d[k])
        except ValueError:
            d[k] = {} if k == "parametros" else []
    d["nombre_tipo"] = TIPOS.get(d["tipo"], d["tipo"])
    d["se_puede_deshacer"] = d["estado"] == "aplicada" and bool(d["caduca_en"]) and d["caduca_en"] >= _ahora().isoformat(timespec="seconds")
    d["se_puede_aplicar"] = d["estado"] == "propuesta" and d["creada_en"] >= (_ahora() - timedelta(minutes=MINUTOS_PARA_CONFIRMAR)).isoformat(timespec="seconds")
    return d


def _exigir_escritura(tenant_id: int, usuario_id: int) -> None:
    if acceso.es_solo_auditor(tenant_id, usuario_id):
        raise ErrorMasivoFiscal("Tu rol solo permite consultar.")


def _vencimiento(tenant_id: int, usuario_id: int, vencimiento_id: int) -> dict | None:
    """El vencimiento si existe, no está en la papelera y la persona puede cambiar a su titular."""
    v = db_fiscal.obtener_vencimiento_fiscal(tenant_id, vencimiento_id)
    if v is None or not acceso.puede_modificar_cliente(tenant_id, usuario_id, v["cliente_fiscal_id"]):
        return None
    return dict(v)


def _antes(v: dict) -> dict:
    return {k: v.get(k) for k in CAMPOS_ANTES}


def _igual(v: dict, estado: dict) -> bool:
    return all((v.get(k) or None) == (estado.get(k) or None) for k in CAMPOS_ANTES)


def _etiqueta(v: dict) -> str:
    return f"{v.get('cliente_nombre') or ''} · {v['modelo']} {v['periodo']}".strip(" ·")


# --- Proponer -------------------------------------------------------------------------------------------------------------------

def proponer(tenant_id: int, usuario_id: int, tipo: str, ids, parametros: dict | None = None) -> dict:
    """Guarda la propuesta (sin cambiar nada) y la devuelve."""
    _exigir_escritura(tenant_id, usuario_id)
    if tipo not in TIPOS:
        raise ErrorMasivoFiscal("Esa acción no existe.")
    parametros = dict(parametros or {})
    destino = ""
    if tipo == "reasignar":
        try:
            persona = int(parametros.get("usuario_id"))
        except (TypeError, ValueError):
            raise ErrorMasivoFiscal("Elige a quién se reasignan.") from None
        conn = db.get_connection()
        try:
            es_del_despacho = conn.execute("SELECT 1 FROM usuarios u WHERE u.id = ? AND " + db.sql_miembro(), (persona, tenant_id, tenant_id)).fetchone() is not None
        finally:
            conn.close()
        if not es_del_despacho:
            raise ErrorMasivoFiscal("La persona elegida no es de tu despacho.")
        parametros = {"usuario_id": persona}
        destino = db.nombre_mostrado_usuario(persona) or str(persona)
    else:
        try:
            dias = int(parametros.get("dias"))
        except (TypeError, ValueError):
            raise ErrorMasivoFiscal("Indica cuántos días se pospone.") from None
        if not 1 <= dias <= MAX_DIAS:
            raise ErrorMasivoFiscal(f"Los días a posponer van de 1 a {MAX_DIAS}.")
        motivo = str(parametros.get("motivo") or "").strip()[:300]
        if len(motivo) < 3:
            raise ErrorMasivoFiscal("Escribe el motivo: la fecha de seguimiento se mueve, el plazo legal no, y queda constancia.")
        parametros = {"dias": dias, "motivo": motivo}
        destino = f"{dias} días"
    seleccion = []
    for i in list(dict.fromkeys(ids or []))[:MAX_VENCIMIENTOS]:
        try:
            seleccion.append(int(i))
        except (TypeError, ValueError):
            continue
    if not seleccion:
        raise ErrorMasivoFiscal("No has marcado ningún vencimiento.")
    afectados, omitidos = [], []
    for i in seleccion:
        v = _vencimiento(tenant_id, usuario_id, i)
        if v is None:
            omitidos.append({"id": i, "titulo": f"#{i}", "motivo": "no existe o no puedes cambiarlo"})
            continue
        motivo_omitido = None
        if v["estado"] != "pendiente":
            motivo_omitido = "ya no está pendiente"
        elif tipo == "reasignar" and v["usuario_id"] == parametros["usuario_id"]:
            motivo_omitido = "ya es suyo"
        if motivo_omitido:
            omitidos.append({"id": i, "titulo": _etiqueta(v), "motivo": motivo_omitido})
        else:
            afectados.append({"id": i, "titulo": _etiqueta(v), "antes": _antes(v)})
    if not afectados:
        raise ErrorMasivoFiscal("Ningún vencimiento cambiaría: " + ("; ".join(sorted({x["motivo"] for x in omitidos})) or "nada que hacer") + ".")
    descripcion = f"{TIPOS[tipo]}: {destino} · {len(afectados)} vencimientos"
    conn = db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO fiscal_acciones_masivas (tenant_id, usuario_id, tipo, parametros, descripcion, afectados, omitidos, creada_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, usuario_id, tipo, json.dumps(parametros, ensure_ascii=False), descripcion, json.dumps(afectados, ensure_ascii=False), json.dumps(omitidos, ensure_ascii=False),
             _ahora().isoformat(timespec="seconds")))
        accion_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return obtener(tenant_id, usuario_id, accion_id)


def obtener(tenant_id: int, usuario_id: int, accion_id: int) -> dict | None:
    """Una propuesta o acción: la ve quien la creó y la dirección del despacho."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM fiscal_acciones_masivas WHERE id = ? AND tenant_id = ?", (accion_id, tenant_id)).fetchone()
    finally:
        conn.close()
    if f is None or (f["usuario_id"] != usuario_id and not acceso.es_directivo(usuario_id)):
        return None
    return _fila(f)


def historial(tenant_id: int, usuario_id: int, limite: int = 30) -> list[dict]:
    conn = db.get_connection()
    try:
        if acceso.es_directivo(usuario_id):
            filas = conn.execute("SELECT * FROM fiscal_acciones_masivas WHERE tenant_id = ? AND estado <> 'propuesta' ORDER BY id DESC LIMIT ?", (tenant_id, limite)).fetchall()
        else:
            filas = conn.execute("SELECT * FROM fiscal_acciones_masivas WHERE tenant_id = ? AND usuario_id = ? AND estado <> 'propuesta' ORDER BY id DESC LIMIT ?", (tenant_id, usuario_id, limite)).fetchall()
    finally:
        conn.close()
    return [_fila(f) for f in filas]


# --- Aplicar --------------------------------------------------------------------------------------------------------------------

def _cambiar(tenant_id: int, vencimiento_id: int, **campos) -> None:
    db_fiscal.editar_vencimiento_fiscal(tenant_id, vencimiento_id, **campos)


def aplicar(tenant_id: int, usuario_id: int, accion_id: int) -> dict:
    a = obtener(tenant_id, usuario_id, accion_id)
    if a is None or a["usuario_id"] != usuario_id:
        raise ErrorMasivoFiscal("Propuesta no encontrada.")
    _exigir_escritura(tenant_id, usuario_id)
    if a["estado"] != "propuesta":
        raise ErrorMasivoFiscal("Esta propuesta ya se resolvió.")
    if not a["se_puede_aplicar"]:
        raise ErrorMasivoFiscal(f"La propuesta caducó (más de {MINUTOS_PARA_CONFIRMAR} minutos): vuelve a proponerla.")
    aplicadas, omitidos = [], list(a["omitidos"])
    for x in a["afectados"]:
        v = _vencimiento(tenant_id, usuario_id, x["id"])
        if v is None:
            omitidos.append({"id": x["id"], "titulo": x["titulo"], "motivo": "ya no está disponible"})
            continue
        if not _igual(v, x["antes"]):
            omitidos.append({"id": x["id"], "titulo": x["titulo"], "motivo": "ha cambiado desde la propuesta"})
            continue
        if a["tipo"] == "reasignar":
            _cambiar(tenant_id, x["id"], usuario_id=a["parametros"]["usuario_id"])
        else:
            nueva = (date.fromisoformat(v["fecha_limite"][:10]) + timedelta(days=a["parametros"]["dias"])).isoformat()
            _cambiar(tenant_id, x["id"], fecha_limite=nueva)
        despues = _vencimiento(tenant_id, usuario_id, x["id"]) or {}
        aplicadas.append({**x, "despues": _antes(despues)})
    ahora = _ahora()
    conn = db.get_connection()
    try:
        conn.execute("UPDATE fiscal_acciones_masivas SET estado = 'aplicada', afectados = ?, omitidos = ?, aplicada_en = ?, caduca_en = ? WHERE id = ? AND tenant_id = ?",
                     (json.dumps(aplicadas, ensure_ascii=False), json.dumps(omitidos, ensure_ascii=False), ahora.isoformat(timespec="seconds"),
                      (ahora + timedelta(days=DIAS_PARA_DESHACER)).isoformat(timespec="seconds"), accion_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "fiscal.masivo.aplicado", "fiscal_accion_masiva", accion_id,
                            {"tipo": a["tipo"], "aplicadas": len(aplicadas), "omitidas": len(omitidos), "motivo": a["parametros"].get("motivo")}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return obtener(tenant_id, usuario_id, accion_id)


def cancelar(tenant_id: int, usuario_id: int, accion_id: int) -> None:
    a = obtener(tenant_id, usuario_id, accion_id)
    if a is None or a["usuario_id"] != usuario_id:
        raise ErrorMasivoFiscal("Propuesta no encontrada.")
    if a["estado"] != "propuesta":
        raise ErrorMasivoFiscal("Esta propuesta ya se resolvió.")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE fiscal_acciones_masivas SET estado = 'cancelada' WHERE id = ? AND tenant_id = ?", (accion_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


# --- Deshacer -------------------------------------------------------------------------------------------------------------------

def deshacer(tenant_id: int, usuario_id: int, accion_id: int) -> dict:
    """Devuelve cada vencimiento a su estado anterior si nadie lo ha vuelto a cambiar. Solo durante 90 días."""
    _exigir_escritura(tenant_id, usuario_id)
    a = obtener(tenant_id, usuario_id, accion_id)
    if a is None:
        raise ErrorMasivoFiscal("Acción no encontrada.")
    if a["estado"] != "aplicada":
        raise ErrorMasivoFiscal("Esta acción no se puede deshacer.")
    if not a["se_puede_deshacer"]:
        raise ErrorMasivoFiscal(f"Han pasado más de {DIAS_PARA_DESHACER} días: ya no se puede deshacer.")
    devueltos, sin_tocar = [], []
    for x in a["afectados"]:
        v = _vencimiento(tenant_id, usuario_id, x["id"])
        if v is None or not _igual(v, x["despues"]):
            sin_tocar.append({"id": x["id"], "titulo": x["titulo"], "motivo": "se ha vuelto a cambiar después"})
            continue
        campo = "usuario_id" if a["tipo"] == "reasignar" else "fecha_limite"
        _cambiar(tenant_id, x["id"], **{campo: x["antes"][campo]})
        devueltos.append(x)
    conn = db.get_connection()
    try:
        conn.execute("UPDATE fiscal_acciones_masivas SET estado = 'deshecha', deshecha_en = ?, omitidos = ? WHERE id = ? AND tenant_id = ?",
                     (_ahora().isoformat(timespec="seconds"), json.dumps(a["omitidos"] + sin_tocar, ensure_ascii=False), accion_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "fiscal.masivo.deshecho", "fiscal_accion_masiva", accion_id, {"devueltos": len(devueltos), "sin_tocar": len(sin_tocar)}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    resultado = obtener(tenant_id, usuario_id, accion_id)
    resultado["devueltos"], resultado["sin_tocar"] = len(devueltos), sin_tocar
    return resultado
