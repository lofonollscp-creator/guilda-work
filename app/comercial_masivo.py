"""Cambios en lote sobre oportunidades del Comercial, siempre en tres pasos: **proponer → confirmar → deshacer**.

Lo usan la pantalla (selección en la lista de oportunidades) y el asistente de IA, y comparten las mismas reglas:
- **Proponer no cambia nada.** Guarda una propuesta con las oportunidades que cambiarían (y su estado de ANTES), las que se omiten y por qué, y devuelve el resumen para enseñarlo.
- **Aplicar exige confirmación** de quien propuso, dentro de una hora. Las acciones que mandan oportunidades a la papelera piden además escribir el recuento. Si una oportunidad cambió
  entre la propuesta y la confirmación, se omite (no se pisa el trabajo de otra persona). Cada cambio pasa por las funciones de `comercial.py`, así que conserva sus reglas, su
  cronología, su auditoría y sus automatizaciones.
- **Deshacer** durante 90 días: devuelve cada oportunidad a su estado anterior, salvo las que se hayan vuelto a cambiar después.
- Quien solo audita no propone ni aplica; ve cada persona sus propias oportunidades visibles (oficinas). Máximo 500 oportunidades por cambio."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from . import acceso, auditoria, comercial, db
from .comercial import ErrorComercial

ESQUEMA = """
CREATE TABLE IF NOT EXISTS crm_acciones_masivas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('mover_etapa', 'reasignar', 'posponer_cierre', 'papelera')),
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
CREATE INDEX IF NOT EXISTS idx_crm_acciones_masivas ON crm_acciones_masivas(tenant_id, creada_en);
"""

TIPOS = {
    "mover_etapa": "Cambiar de etapa",
    "reasignar": "Cambiar de responsable",
    "posponer_cierre": "Posponer el cierre previsto",
    "papelera": "Enviar a la papelera",
}
MAX_OPORTUNIDADES = 500
MINUTOS_PARA_CONFIRMAR = 60
DIAS_PARA_DESHACER = 90
CAMPOS_ANTES = ("etapa", "estado", "responsable_id", "cierre_previsto", "motivo_perdida", "papelera_en")


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
            d[k] = [] if k != "parametros" else {}
    d["requiere_texto"] = d["tipo"] == "papelera"
    d["texto_confirmacion"] = texto_de_confirmacion(len(d["afectados"])) if d["requiere_texto"] else None
    d["nombre_tipo"] = TIPOS.get(d["tipo"], d["tipo"])
    d["se_puede_deshacer"] = d["estado"] == "aplicada" and bool(d["caduca_en"]) and d["caduca_en"] >= _ahora().isoformat(timespec="seconds")
    d["se_puede_aplicar"] = d["estado"] == "propuesta" and d["creada_en"] >= (_ahora() - timedelta(minutes=MINUTOS_PARA_CONFIRMAR)).isoformat(timespec="seconds")
    return d


def texto_de_confirmacion(n: int) -> str:
    return f"{n} oportunidades" if n != 1 else "1 oportunidad"


# --- Selección --------------------------------------------------------------------------------------------------------------

def _seleccionar(tenant_id: int, usuario_id: int, seleccion: dict) -> list[dict]:
    """Las oportunidades visibles que indica la selección: una lista de `ids` o un filtro (`estado`, `etapa`, `responsable_id`, `q`, `estancadas`)."""
    if seleccion.get("ids"):
        ids = []
        for i in seleccion["ids"]:
            try:
                ids.append(int(i))
            except (TypeError, ValueError):
                continue
        ids = list(dict.fromkeys(ids))[:MAX_OPORTUNIDADES]
        encontradas = [comercial.obtener_oportunidad(tenant_id, usuario_id, i) for i in ids]
        return [o for o in encontradas if o is not None]
    if seleccion.get("estancadas"):
        base = comercial.estancadas(tenant_id, usuario_id, int(seleccion.get("dias_sin_actividad") or comercial.DIAS_ESTANCADA))
        if seleccion.get("responsable_id") not in (None, ""):
            base = [o for o in base if str(o["responsable_id"]) == str(seleccion["responsable_id"])]
        return base[:MAX_OPORTUNIDADES]
    estado = seleccion.get("estado", "abierta")
    return comercial.listar_oportunidades(tenant_id, usuario_id, estado=None if estado in ("todas", None) else estado, etapa=seleccion.get("etapa") or None,
                                          responsable_id=seleccion.get("responsable_id") or None, q=seleccion.get("q") or None, limite=MAX_OPORTUNIDADES)


def _antes(o: dict) -> dict:
    return {k: o.get(k) for k in CAMPOS_ANTES}


# --- Proponer -------------------------------------------------------------------------------------------------------------------

def proponer(tenant_id: int, usuario_id: int, tipo: str, seleccion: dict, parametros: dict | None = None) -> dict:
    """Guarda la propuesta (sin cambiar nada) y la devuelve con su resumen."""
    if acceso.es_solo_auditor(tenant_id, usuario_id):
        raise ErrorComercial("Tu rol solo permite consultar.")
    if tipo not in TIPOS:
        raise ErrorComercial("Esa acción no existe.")
    parametros = dict(parametros or {})
    destino_nombre = ""
    if tipo == "mover_etapa":
        etapa = str(parametros.get("etapa") or "")
        etapas = {e["clave"]: e for e in comercial.listar_etapas(tenant_id)}
        if etapa not in etapas:
            raise ErrorComercial("Esa etapa no existe.")
        if etapas[etapa]["tipo"] == "perdida" and not str(parametros.get("motivo") or "").strip():
            raise ErrorComercial("Indica por qué se pierden las oportunidades.")
        parametros = {"etapa": etapa, "motivo": str(parametros.get("motivo") or "").strip()[:500]}
        destino_nombre = etapas[etapa]["nombre"]
    elif tipo == "reasignar":
        conn = db.get_connection()
        try:
            persona = comercial._persona_del_despacho(conn, tenant_id, parametros.get("responsable_id"))
        finally:
            conn.close()
        if persona is None:
            raise ErrorComercial("Elige a quién se reasignan.")
        parametros = {"responsable_id": persona}
        destino_nombre = db.nombre_mostrado_usuario(persona) or str(persona)
    elif tipo == "posponer_cierre":
        try:
            dias = int(parametros.get("dias"))
        except (TypeError, ValueError):
            raise ErrorComercial("Indica cuántos días se pospone.") from None
        if not 1 <= dias <= 365:
            raise ErrorComercial("Los días a posponer van de 1 a 365.")
        parametros = {"dias": dias}
        destino_nombre = f"{dias} días"

    elegidas = _seleccionar(tenant_id, usuario_id, seleccion or {})
    if not elegidas:
        raise ErrorComercial("No hay ninguna oportunidad con esa selección.")
    afectados, omitidos = [], []
    for o in elegidas:
        motivo = None
        if tipo == "mover_etapa" and o["etapa"] == parametros["etapa"]:
            motivo = "ya está en esa etapa"
        elif tipo == "reasignar" and o["responsable_id"] == parametros["responsable_id"]:
            motivo = "ya es suya"
        elif tipo == "posponer_cierre" and not o["cierre_previsto"]:
            motivo = "no tiene cierre previsto"
        if motivo:
            omitidos.append({"id": o["id"], "titulo": o["titulo"], "motivo": motivo})
        else:
            afectados.append({"id": o["id"], "titulo": o["titulo"], "antes": _antes(o)})
    if not afectados:
        raise ErrorComercial("Ninguna oportunidad cambiaría: " + ("; ".join(sorted({x["motivo"] for x in omitidos})) or "nada que hacer") + ".")
    descripcion = f"{TIPOS[tipo]}" + (f": {destino_nombre}" if destino_nombre else "") + f" · {len(afectados)} oportunidades"
    conn = db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO crm_acciones_masivas (tenant_id, usuario_id, tipo, parametros, descripcion, afectados, omitidos, creada_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, usuario_id, tipo, json.dumps(parametros), descripcion, json.dumps(afectados, ensure_ascii=False), json.dumps(omitidos, ensure_ascii=False), _ahora().isoformat(timespec="seconds")))
        accion_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return obtener(tenant_id, usuario_id, accion_id)


def obtener(tenant_id: int, usuario_id: int, accion_id: int) -> dict | None:
    """Una propuesta o acción: la ve quien la creó y la dirección del despacho."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM crm_acciones_masivas WHERE id = ? AND tenant_id = ?", (accion_id, tenant_id)).fetchone()
    finally:
        conn.close()
    if f is None or (f["usuario_id"] != usuario_id and not acceso.es_directivo(usuario_id)):
        return None
    return _fila(f)


def historial(tenant_id: int, usuario_id: int, limite: int = 30) -> list[dict]:
    conn = db.get_connection()
    try:
        if acceso.es_directivo(usuario_id):
            filas = conn.execute("SELECT * FROM crm_acciones_masivas WHERE tenant_id = ? AND estado <> 'propuesta' ORDER BY id DESC LIMIT ?", (tenant_id, limite)).fetchall()
        else:
            filas = conn.execute("SELECT * FROM crm_acciones_masivas WHERE tenant_id = ? AND usuario_id = ? AND estado <> 'propuesta' ORDER BY id DESC LIMIT ?", (tenant_id, usuario_id, limite)).fetchall()
    finally:
        conn.close()
    return [_fila(f) for f in filas]


# --- Aplicar --------------------------------------------------------------------------------------------------------------------

def _igual_que_antes(o: dict, antes: dict) -> bool:
    return all((o.get(k) or None) == (antes.get(k) or None) for k in CAMPOS_ANTES)


def _aplicar_uno(tenant_id: int, usuario_id: int, tipo: str, parametros: dict, o: dict) -> None:
    if tipo == "mover_etapa":
        comercial.mover_oportunidad(tenant_id, usuario_id, o["id"], parametros["etapa"], parametros.get("motivo"))
    elif tipo == "reasignar":
        comercial.editar_oportunidad(tenant_id, usuario_id, o["id"], responsable_id=parametros["responsable_id"])
    elif tipo == "posponer_cierre":
        nueva = (date.fromisoformat(o["cierre_previsto"][:10]) + timedelta(days=parametros["dias"])).isoformat()
        comercial.editar_oportunidad(tenant_id, usuario_id, o["id"], cierre_previsto=nueva)
    elif tipo == "papelera":
        comercial.papelera_oportunidad(tenant_id, usuario_id, o["id"])


def aplicar(tenant_id: int, usuario_id: int, accion_id: int, confirmacion: str | None = None) -> dict:
    """Aplica una propuesta confirmada. Devuelve la acción con lo aplicado y lo omitido."""
    a = obtener(tenant_id, usuario_id, accion_id)
    if a is None or a["usuario_id"] != usuario_id:
        raise ErrorComercial("Propuesta no encontrada.")
    if a["estado"] != "propuesta":
        raise ErrorComercial("Esta propuesta ya se resolvió.")
    if not a["se_puede_aplicar"]:
        raise ErrorComercial(f"La propuesta caducó (más de {MINUTOS_PARA_CONFIRMAR} minutos): vuelve a proponerla.")
    if a["requiere_texto"] and (confirmacion or "").strip().lower() != a["texto_confirmacion"].lower():
        raise ErrorComercial(f"Escribe «{a['texto_confirmacion']}» para confirmar.")
    aplicadas, omitidos = [], list(a["omitidos"])
    for x in a["afectados"]:
        o = comercial.obtener_oportunidad(tenant_id, usuario_id, x["id"])
        if o is None:
            omitidos.append({"id": x["id"], "titulo": x["titulo"], "motivo": "ya no está disponible"})
            continue
        if not _igual_que_antes(o, x["antes"]):
            omitidos.append({"id": x["id"], "titulo": x["titulo"], "motivo": "ha cambiado desde la propuesta"})
            continue
        try:
            _aplicar_uno(tenant_id, usuario_id, a["tipo"], a["parametros"], o)
        except ErrorComercial as e:
            omitidos.append({"id": x["id"], "titulo": x["titulo"], "motivo": str(e)})
            continue
        despues = comercial.obtener_oportunidad(tenant_id, usuario_id, x["id"], incluir_papelera=True) or {}
        aplicadas.append({**x, "despues": _antes(despues)})
    ahora = _ahora()
    conn = db.get_connection()
    try:
        conn.execute("UPDATE crm_acciones_masivas SET estado = 'aplicada', afectados = ?, omitidos = ?, aplicada_en = ?, caduca_en = ? WHERE id = ? AND tenant_id = ?",
                     (json.dumps(aplicadas, ensure_ascii=False), json.dumps(omitidos, ensure_ascii=False), ahora.isoformat(timespec="seconds"),
                      (ahora + timedelta(days=DIAS_PARA_DESHACER)).isoformat(timespec="seconds"), accion_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "crm.masivo.aplicado", "crm_accion_masiva", accion_id, {"tipo": a["tipo"], "aplicadas": len(aplicadas), "omitidas": len(omitidos)}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return obtener(tenant_id, usuario_id, accion_id)


def cancelar(tenant_id: int, usuario_id: int, accion_id: int) -> None:
    a = obtener(tenant_id, usuario_id, accion_id)
    if a is None or a["usuario_id"] != usuario_id:
        raise ErrorComercial("Propuesta no encontrada.")
    if a["estado"] != "propuesta":
        raise ErrorComercial("Esta propuesta ya se resolvió.")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE crm_acciones_masivas SET estado = 'cancelada' WHERE id = ? AND tenant_id = ?", (accion_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


# --- Deshacer -------------------------------------------------------------------------------------------------------------------

def _deshacer_uno(tenant_id: int, usuario_id: int, tipo: str, x: dict) -> None:
    antes = x["antes"]
    if tipo == "mover_etapa":
        comercial.mover_oportunidad(tenant_id, usuario_id, x["id"], antes["etapa"], antes.get("motivo_perdida") or "Cambio deshecho")
    elif tipo == "reasignar":
        comercial.editar_oportunidad(tenant_id, usuario_id, x["id"], responsable_id=antes["responsable_id"])
    elif tipo == "posponer_cierre":
        comercial.editar_oportunidad(tenant_id, usuario_id, x["id"], cierre_previsto=antes["cierre_previsto"])
    elif tipo == "papelera":
        conn = db.get_connection()
        try:
            conn.execute("UPDATE crm_oportunidades SET papelera_en = NULL, actualizada_en = ? WHERE id = ? AND tenant_id = ?", (db.now_iso(), x["id"], tenant_id))
            auditoria.registrar(tenant_id, usuario_id, "crm.oportunidad.restaurada", "crm_oportunidad", x["id"], conn=conn)
            conn.commit()
        finally:
            conn.close()


def deshacer(tenant_id: int, usuario_id: int, accion_id: int) -> dict:
    """Devuelve cada oportunidad a su estado anterior si nadie la ha vuelto a cambiar. Solo durante 90 días."""
    if acceso.es_solo_auditor(tenant_id, usuario_id):
        raise ErrorComercial("Tu rol solo permite consultar.")
    a = obtener(tenant_id, usuario_id, accion_id)
    if a is None:
        raise ErrorComercial("Acción no encontrada.")
    if a["estado"] != "aplicada":
        raise ErrorComercial("Esta acción no se puede deshacer.")
    if not a["se_puede_deshacer"]:
        raise ErrorComercial(f"Han pasado más de {DIAS_PARA_DESHACER} días: ya no se puede deshacer.")
    devueltas, sin_tocar = [], []
    for x in a["afectados"]:
        o = comercial.obtener_oportunidad(tenant_id, usuario_id, x["id"], incluir_papelera=True)
        if o is None or not _igual_que_antes(o, x["despues"]):
            sin_tocar.append({"id": x["id"], "titulo": x["titulo"], "motivo": "se ha vuelto a cambiar después"})
            continue
        try:
            _deshacer_uno(tenant_id, usuario_id, a["tipo"], x)
        except ErrorComercial as e:
            sin_tocar.append({"id": x["id"], "titulo": x["titulo"], "motivo": str(e)})
            continue
        devueltas.append(x)
    conn = db.get_connection()
    try:
        conn.execute("UPDATE crm_acciones_masivas SET estado = 'deshecha', deshecha_en = ?, omitidos = ? WHERE id = ? AND tenant_id = ?",
                     (_ahora().isoformat(timespec="seconds"), json.dumps(a["omitidos"] + sin_tocar, ensure_ascii=False), accion_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "crm.masivo.deshecho", "crm_accion_masiva", accion_id, {"devueltas": len(devueltas), "sin_tocar": len(sin_tocar)}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    resultado = obtener(tenant_id, usuario_id, accion_id)
    resultado["devueltas"], resultado["sin_tocar"] = len(devueltas), sin_tocar
    return resultado


def resumen_para_confirmar(tenant_id: int, usuario_id: int, accion_id: int) -> str:
    """El texto que enseña la tarjeta de confirmación (también la del asistente): qué cambia, cuántas, cuántas se omiten y hasta cuándo se puede deshacer."""
    a = obtener(tenant_id, usuario_id, accion_id)
    if a is None or a["estado"] != "propuesta":
        return ""
    texto = f"{a['descripcion']}. {len(a['afectados'])} oportunidades · {len(a['omitidos'])} omitidas · se puede deshacer durante {DIAS_PARA_DESHACER} días."
    if a["requiere_texto"]:
        texto += f" Para confirmar hay que escribir «{a['texto_confirmacion']}»."
    return texto


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    conn.execute("DELETE FROM crm_acciones_masivas WHERE tenant_id = ?", (tenant_id,))
