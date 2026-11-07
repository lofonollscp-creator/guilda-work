"""Cuestionarios del cliente (Q8): formularios cortos que la gestoría le manda para recoger datos antes de una declaración o de un cambio («Datos para la renta», «Cambio de situación familiar»…),
que el cliente contesta desde su portal y cuyas respuestas quedan en su ficha.

Cada cuestionario lleva sus preguntas (texto, sí/no, número, fecha u opción entre varias) con la marca de obligatoria. Hay plantillas hechas y también se puede escribir uno propio con una pregunta por
línea («¿Cuántos hijos tiene? | numero»). Las respuestas se validan por tipo y se guardan tal cual; el equipo las ve en la ficha del cliente y da el cuestionario por recibido. Una vez respondido el cliente
no lo cambia (si se equivocó, la gestoría lo reabre)."""
from __future__ import annotations

import json
import re
from datetime import date, datetime

from flask_babel import gettext as _

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_cuestionarios (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    titulo TEXT NOT NULL,
    descripcion TEXT NOT NULL DEFAULT '',
    preguntas TEXT NOT NULL,
    respuestas TEXT,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'respondido', 'recibido', 'cancelado')),
    fecha_limite TEXT,
    creado_por INTEGER,
    creado_en TEXT NOT NULL,
    respondido_en TEXT,
    respondido_por TEXT
);
CREATE INDEX IF NOT EXISTS idx_portal_cuestionarios_cliente ON portal_cuestionarios(tenant_id, cliente_fiscal_id, estado);
"""

TIPOS = ("texto", "si_no", "numero", "fecha", "opcion")
MAX_TITULO, MAX_DESCRIPCION, MAX_PREGUNTA, MAX_PREGUNTAS, MAX_RESPUESTA = 120, 400, 200, 40, 1000
MAX_ABIERTOS = 15

PLANTILLAS = {
    "renta": {"titulo": "Datos para tu declaración de la renta", "descripcion": "Cuéntanos qué ha cambiado este año para preparar bien tu declaración.", "preguntas": [
        {"texto": "¿Ha cambiado tu estado civil o tu situación familiar este año?", "tipo": "si_no", "obligatoria": True},
        {"texto": "¿Cuántos hijos o personas a tu cargo tienes?", "tipo": "numero", "obligatoria": True},
        {"texto": "¿Has cambiado de domicilio?", "tipo": "si_no", "obligatoria": True},
        {"texto": "¿Has comprado o vendido alguna vivienda o inmueble?", "tipo": "si_no", "obligatoria": True},
        {"texto": "¿Has tenido ingresos de más de un pagador?", "tipo": "si_no", "obligatoria": False},
        {"texto": "¿Pagas alquiler de tu vivienda habitual?", "tipo": "si_no", "obligatoria": False},
        {"texto": "Cualquier otra cosa que debamos saber", "tipo": "texto", "obligatoria": False}]},
    "familia": {"titulo": "Cambio de situación familiar", "descripcion": "Para actualizar tu retención y tus datos.", "preguntas": [
        {"texto": "¿Qué ha cambiado?", "tipo": "opcion", "opciones": ["Matrimonio o pareja de hecho", "Separación o divorcio", "Nacimiento o adopción", "Fallecimiento de un familiar", "Otro"], "obligatoria": True},
        {"texto": "Fecha del cambio", "tipo": "fecha", "obligatoria": True},
        {"texto": "Detalles (nombres y fechas de nacimiento si procede)", "tipo": "texto", "obligatoria": False}]},
    "empleado": {"titulo": "Alta de un nuevo empleado", "descripcion": "Los datos que necesitamos para dar de alta a la persona que incorporas.", "preguntas": [
        {"texto": "Nombre y apellidos", "tipo": "texto", "obligatoria": True}, {"texto": "NIF o NIE", "tipo": "texto", "obligatoria": True},
        {"texto": "Fecha de inicio", "tipo": "fecha", "obligatoria": True}, {"texto": "Tipo de contrato", "tipo": "opcion", "opciones": ["Indefinido", "Temporal", "Formación", "Otro"], "obligatoria": True},
        {"texto": "Jornada (horas a la semana)", "tipo": "numero", "obligatoria": True}, {"texto": "Salario bruto anual", "tipo": "numero", "obligatoria": True},
        {"texto": "Observaciones", "tipo": "texto", "obligatoria": False}]},
    "domicilio": {"titulo": "Cambio de domicilio fiscal", "descripcion": "Para comunicar el cambio y no perder ninguna notificación.", "preguntas": [
        {"texto": "Nueva dirección completa", "tipo": "texto", "obligatoria": True}, {"texto": "Fecha del cambio", "tipo": "fecha", "obligatoria": True},
        {"texto": "¿Cambia también el domicilio de la actividad?", "tipo": "si_no", "obligatoria": True}]},
}


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _limpio(t, largo: int) -> str:
    return " ".join((t or "").split())[:largo]


def preguntas_desde_texto(texto: str) -> list[dict]:
    """Una pregunta por línea; «Pregunta | tipo» fija el tipo (texto, si_no, numero, fecha) y un «*» al final la hace obligatoria. `ValueError` si no hay ninguna o hay demasiadas."""
    salida = []
    for linea in (texto or "").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        obligatoria = linea.endswith("*")
        linea = linea.rstrip("* ").strip()
        pregunta, _s, tipo = linea.partition("|")
        tipo = tipo.strip().lower().replace(" ", "_").replace("í", "i") or "texto"
        if tipo not in ("texto", "si_no", "numero", "fecha"):
            raise ValueError("El tipo de pregunta debe ser texto, si_no, numero o fecha.")
        pregunta = _limpio(pregunta, MAX_PREGUNTA)
        if pregunta:
            salida.append({"texto": pregunta, "tipo": tipo, "obligatoria": obligatoria})
    if not salida:
        raise ValueError("Escribe al menos una pregunta.")
    if len(salida) > MAX_PREGUNTAS:
        raise ValueError("Como máximo 40 preguntas.")
    return salida


def crear(cliente, titulo: str, preguntas: list[dict], descripcion: str = "", fecha_limite: str | None = None, por: int | None = None) -> int:
    titulo = _limpio(titulo, MAX_TITULO)
    if len(titulo) < 3:
        raise ValueError("Ponle un título al cuestionario (mínimo 3 caracteres).")
    limpias = []
    for i, p in enumerate(preguntas[:MAX_PREGUNTAS], 1):
        tipo = p.get("tipo")
        texto = _limpio(p.get("texto"), MAX_PREGUNTA)
        if tipo not in TIPOS or not texto:
            raise ValueError("Una pregunta no es válida.")
        q = {"id": f"p{i}", "texto": texto, "tipo": tipo, "obligatoria": bool(p.get("obligatoria"))}
        if tipo == "opcion":
            opciones = [_limpio(o, 80) for o in (p.get("opciones") or []) if _limpio(o, 80)]
            if len(opciones) < 2:
                raise ValueError("Una pregunta de opciones necesita al menos dos.")
            q["opciones"] = opciones[:12]
        limpias.append(q)
    if not limpias:
        raise ValueError("Escribe al menos una pregunta.")
    limite = None
    if fecha_limite:
        try:
            limite = date.fromisoformat(fecha_limite).isoformat()
        except ValueError:
            raise ValueError("La fecha límite no es válida.") from None
    conn = db.get_connection()
    try:
        abiertos = conn.execute("SELECT COUNT(*) FROM portal_cuestionarios WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado IN ('pendiente', 'respondido')", (cliente["tenant_id"], cliente["id"])).fetchone()[0]
        if abiertos >= MAX_ABIERTOS:
            raise ValueError("Hay demasiados cuestionarios abiertos con este cliente.")
        cur = conn.execute("INSERT INTO portal_cuestionarios (tenant_id, cliente_fiscal_id, titulo, descripcion, preguntas, fecha_limite, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (cliente["tenant_id"], cliente["id"], titulo, _limpio(descripcion, MAX_DESCRIPCION), json.dumps(limpias, ensure_ascii=False), limite, por, _ahora()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def desde_plantilla(cliente, clave: str, por: int | None = None, fecha_limite: str | None = None) -> int:
    p = PLANTILLAS.get(clave)
    if p is None:
        raise ValueError("Esa plantilla no existe.")
    return crear(cliente, p["titulo"], p["preguntas"], p["descripcion"], fecha_limite, por)


def _fila(f) -> dict:
    d = dict(f)
    d["preguntas"] = json.loads(d["preguntas"])
    d["respuestas"] = json.loads(d["respuestas"]) if d.get("respuestas") else None
    return d


def obtener(cliente, cuestionario_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM portal_cuestionarios WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?", (cuestionario_id, cliente["tenant_id"], cliente["id"])).fetchone()
    finally:
        conn.close()
    return _fila(f) if f else None


def listar(cliente) -> list[dict]:
    """Los cuestionarios del cliente: primero los pendientes, luego los respondidos y por último los demás, cada grupo del más reciente al más antiguo."""
    conn = db.get_connection()
    try:
        filas = [_fila(f) for f in conn.execute("SELECT * FROM portal_cuestionarios WHERE tenant_id = ? AND cliente_fiscal_id = ? ORDER BY id DESC", (cliente["tenant_id"], cliente["id"])).fetchall()]
    finally:
        conn.close()
    orden = {"pendiente": 0, "respondido": 1, "recibido": 2, "cancelado": 3}
    return sorted(filas, key=lambda f: orden[f["estado"]])


def pendientes_del_cliente(cliente_fiscal_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT id, titulo, fecha_limite FROM portal_cuestionarios WHERE cliente_fiscal_id = ? AND estado = 'pendiente' ORDER BY id", (cliente_fiscal_id,)).fetchall()
    finally:
        conn.close()
    hoy = date.today()
    salida = []
    for f in filas:
        d = dict(f)
        try:
            d["dias"] = (date.fromisoformat(d["fecha_limite"]) - hoy).days if d["fecha_limite"] else None
        except ValueError:
            d["dias"] = None
        salida.append(d)
    return salida


def validar_respuestas(preguntas: list[dict], formulario) -> dict[str, str]:
    """Las respuestas del formulario (`formulario.get(id)`) validadas por tipo. `ValueError` con el motivo si falta una obligatoria o una no tiene el formato de su tipo."""
    respuestas = {}
    for q in preguntas:
        crudo = (formulario.get(q["id"]) or "").strip()[:MAX_RESPUESTA]
        if not crudo:
            if q["obligatoria"]:
                raise ValueError(_("Falta contestar: «%(p)s»", p=q["texto"]))
            continue
        if q["tipo"] == "numero":
            if not re.fullmatch(r"-?\d+([.,]\d+)?", crudo):
                raise ValueError(_("«%(p)s»: escribe un número.", p=q["texto"]))
            crudo = crudo.replace(",", ".")
        elif q["tipo"] == "fecha":
            try:
                crudo = date.fromisoformat(crudo).isoformat()
            except ValueError:
                raise ValueError(_("«%(p)s»: elige una fecha válida.", p=q["texto"])) from None
        elif q["tipo"] == "si_no" and crudo not in ("si", "no"):
            raise ValueError(_("«%(p)s»: contesta sí o no.", p=q["texto"]))
        elif q["tipo"] == "opcion" and crudo not in q.get("opciones", []):
            raise ValueError(_("«%(p)s»: elige una de las opciones.", p=q["texto"]))
        respuestas[q["id"]] = crudo
    return respuestas


def responder(cliente, cuestionario_id: int, formulario, quien: str) -> bool:
    """Guarda las respuestas del cliente (solo si el cuestionario sigue pendiente). `ValueError` si algo no vale; False si ya no admite respuestas."""
    c = obtener(cliente, cuestionario_id)
    if c is None or c["estado"] != "pendiente":
        return False
    respuestas = validar_respuestas(c["preguntas"], formulario)
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_cuestionarios SET respuestas = ?, estado = 'respondido', respondido_en = ?, respondido_por = ? WHERE id = ? AND tenant_id = ? AND estado = 'pendiente'",
                         (json.dumps(respuestas, ensure_ascii=False), _ahora(), _limpio(quien, 120), cuestionario_id, cliente["tenant_id"])).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()


def cambiar(cliente, cuestionario_id: int, desde: tuple[str, ...], estado: str) -> bool:
    """Da por recibido, reabre (vuelve a pendiente y se borran las respuestas para que las rehaga) o cancela. False si no existe o no estaba en un estado desde el que se pueda."""
    conn = db.get_connection()
    try:
        extra = ", respuestas = NULL, respondido_en = NULL, respondido_por = NULL" if estado == "pendiente" else ""
        n = conn.execute(f"UPDATE portal_cuestionarios SET estado = ?{extra} WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ? AND estado IN ({','.join('?' * len(desde))})",
                         (estado, cuestionario_id, cliente["tenant_id"], cliente["id"], *desde)).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()
