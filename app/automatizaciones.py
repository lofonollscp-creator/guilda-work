"""Reglas de automatización (Fase 4 de docs/guilda-work-implementation-plan.md): **disparador → condiciones → acciones**, por despacho.

Hay dos formas de dispararse. Las **diarias** (certificado a punto de caducar, tarea vencida, modelo próximo) se buscan en un análisis periódico (`ejecutar`, desde `scripts/ejecutar_automatizaciones.py`
con su timer). Las **por evento** (se crea una tarea, una tarea cambia de estado) reaccionan en segundos: el cambio anota el evento en una cola persistente (`registrar_evento`) y un hilo de fondo
lo procesa (`procesar_eventos`); la pasada diaria vacía lo que quedara. Garantías:

- **Idempotencia**: cada ejecución tiene una clave única por regla y ocurrencia (`UNIQUE(regla_id, clave)`), p. ej. «este certificado, con esta caducidad». Repetir el análisis nunca
  crea otra tarea; si el certificado se renueva, cambia la caducidad y deja de cumplir la condición (el aviso obsoleto desaparece solo).
- **Reintentos acotados**: si una acción falla se reintenta con espera creciente (15 min, 1 h, 4 h); al tercer fallo queda `fallida` y se avisa una sola vez a la dirección.
  Las acciones ya hechas no se repiten al reintentar.
- **Sin bucles**: las tareas creadas por una regla llevan la marca `auto:…` y ninguna regla de tareas las vuelve a disparar. Tope de reglas por despacho y de ejecuciones por pasada.
- **Simulación**: `simular` enseña qué haría una regla ahora, sin escribir nada.
- **Despacho y zona horaria**: solo se miran datos del propio despacho; «hoy» es el día en la zona del despacho (Europe/Madrid por defecto).
Solo la dirección del despacho crea, cambia o apaga reglas. Todo cambio queda en la auditoría."""
from __future__ import annotations

import contextvars
import json
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone

from . import auditoria, db

DISPARADORES = {
    "certificado.caduca": "Un certificado digital está cerca de caducar (y nadie lo ha renovado)",
    "tarea.vencida": "Una tarea lleva días vencida sin completarse",
    "vencimiento.proximo": "Se acerca la fecha límite de un modelo fiscal pendiente",
    "tarea.creada": "Se crea una tarea",
    "tarea.estado": "Una tarea cambia de estado",
    "recurrencia.generada": "Se genera una tarea recurrente",
    "tarea.liberada": "Una tarea queda libre (se completa lo que esperaba)",
    "expediente.creado": "Se abre un expediente",
    "expediente.estado": "Un expediente cambia de estado",
    "oportunidad.etapa": "Una oportunidad comercial cambia de etapa",
}
# Los cinco últimos no se buscan una vez al día: reaccionan a un evento (cola `automatizaciones_eventos`). Cada disparador de evento escucha un evento interno.
DISPARADORES_DE_EVENTO = {"tarea.creada": "tarea.creada", "tarea.estado": "tarea.estado_cambiado", "recurrencia.generada": "recurrencia.generada", "tarea.liberada": "tarea.desbloqueada",
                          "expediente.creado": "expediente.creado", "expediente.estado": "expediente.estado_cambiado", "oportunidad.etapa": "oportunidad.etapa_cambiada"}
# Los de tarea tienen UNA tarea sobre la que se puede actuar (comentar, fijar fecha, asignar, pedir revisión); los de expediente no: solo crear tareas y avisar.
DISPARADORES_CON_TAREA = ("tarea.vencida", "tarea.creada", "tarea.estado", "recurrencia.generada", "tarea.liberada")
EVENTOS_DE_EXPEDIENTE = ("expediente.creado", "expediente.estado_cambiado")
EVENTOS_DE_OPORTUNIDAD = ("oportunidad.etapa_cambiada",)
PERIODICIDADES_TEXTO = {"diaria": "diaria", "laborables": "en días laborables", "semanal": "semanal", "mensual": "mensual", "trimestral": "trimestral", "anual": "anual"}
_ID_EXPEDIENTE = re.compile(r"[a-z0-9_]{1,40}")
ESTADOS_TAREA = {"no_iniciada": "Sin empezar", "en_progreso": "En progreso", "completada": "Completada", "esperando": "Esperando a otros", "aplazada": "Aplazada", "en_revision": "En revisión"}
ACCIONES = ("crear_tarea", "notificar", "comentar", "fijar_fecha", "asignar", "pedir_revision")
# Estas actúan sobre LA tarea del disparador, así que solo valen cuando el disparador es una tarea (vencida, creada o que cambia de estado).
ACCIONES_SOBRE_LA_TAREA = ("comentar", "fijar_fecha", "asignar", "pedir_revision")
# Variables que se pueden escribir entre llaves en los textos de cada disparador (las que rellena `_ocurrencias`).
VARIABLES = {
    "certificado.caduca": ("titular", "fecha", "dias"),
    "tarea.vencida": ("asunto", "fecha", "dias"),
    "vencimiento.proximo": ("modelo", "periodo", "cliente", "fecha", "dias"),
    "tarea.creada": ("asunto", "prioridad", "cliente", "fecha", "modelo", "periodo"),     # modelo y periodo: solo si la tarea está vinculada a un vencimiento fiscal; si no, vacíos
    "tarea.estado": ("asunto", "estado", "anterior", "prioridad", "cliente", "fecha"),
    "recurrencia.generada": ("asunto", "periodicidad", "prioridad", "cliente", "fecha"),
    "tarea.liberada": ("asunto", "previa", "prioridad", "cliente", "fecha"),                 # previa: la tarea que se acaba de completar y que esta esperaba
    "expediente.creado": ("expediente", "referencia", "tipo", "cliente", "estado"),
    "expediente.estado": ("expediente", "referencia", "tipo", "cliente", "estado", "anterior"),
    "oportunidad.etapa": ("oportunidad", "contacto", "etapa", "anterior", "importe", "responsable"),
}
PRIORIDADES = ("baja", "normal", "alta")
MAX_REGLAS = 50
MAX_ACCIONES = 5
MAX_POR_PASADA = 200
MAX_EVENTOS_POR_LOTE = 100
PURGA_EVENTOS_DIAS = 7
MAX_INTENTOS = 3
ESPERAS_MINUTOS = (15, 60, 240)
ENCALLADA_MINUTOS = 30

ESQUEMA = """
CREATE TABLE IF NOT EXISTS automatizaciones_reglas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    nombre TEXT NOT NULL,
    disparador TEXT NOT NULL,
    condiciones TEXT NOT NULL DEFAULT '{}',
    acciones TEXT NOT NULL DEFAULT '[]',
    activa INTEGER NOT NULL DEFAULT 1,
    version INTEGER NOT NULL DEFAULT 1,
    creada_por INTEGER REFERENCES usuarios(id),
    creada_en TEXT NOT NULL,
    actualizada_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_auto_reglas_tenant ON automatizaciones_reglas(tenant_id, activa);
CREATE TABLE IF NOT EXISTS automatizaciones_ejecuciones (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    regla_id INTEGER NOT NULL REFERENCES automatizaciones_reglas(id) ON DELETE CASCADE,
    regla_version INTEGER NOT NULL,
    clave TEXT NOT NULL,
    objeto TEXT,
    estado TEXT NOT NULL CHECK (estado IN ('pendiente', 'ok', 'error', 'fallida')),
    intentos INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    progreso TEXT NOT NULL DEFAULT '[]',
    proximo_intento TEXT,
    avisada INTEGER NOT NULL DEFAULT 0,
    creada_en TEXT NOT NULL,
    actualizada_en TEXT NOT NULL,
    UNIQUE (regla_id, clave)
);
CREATE INDEX IF NOT EXISTS idx_auto_ejec_tenant ON automatizaciones_ejecuciones(tenant_id, estado);
CREATE TABLE IF NOT EXISTS automatizaciones_eventos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    evento TEXT NOT NULL,
    tarea_id INTEGER,
    datos TEXT NOT NULL DEFAULT '{}',
    creado_en TEXT NOT NULL,
    procesado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_auto_eventos_pendientes ON automatizaciones_eventos(procesado_en, id);
"""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    db._asegurar_columna(conn, "automatizaciones_ejecuciones", "contexto", "TEXT")
    db._asegurar_columna(conn, "automatizaciones_eventos", "objeto_id", "INTEGER")        # el expediente de los eventos de expediente (los de tarea usan tarea_id)        # la ocurrencia de un evento, para poder reintentarla sin volver a buscarla


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    conn.execute("DELETE FROM automatizaciones_eventos WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM automatizaciones_ejecuciones WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM automatizaciones_reglas WHERE tenant_id = ?", (tenant_id,))


# --- Validación de reglas --------------------------------------------------------------------------------------------

def _entero(valor, nombre: str, minimo: int, maximo: int, defecto: int | None = None) -> int:
    if valor in (None, ""):
        if defecto is None:
            raise ValueError(f"Falta {nombre}.")
        return defecto
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{nombre} tiene que ser un número entero.") from None
    if not minimo <= n <= maximo:
        raise ValueError(f"{nombre} tiene que estar entre {minimo} y {maximo}.")
    return n


def validar_condiciones(disparador: str, condiciones: dict) -> dict:
    c = condiciones or {}
    if disparador == "certificado.caduca":
        return {"dias_antes": _entero(c.get("dias_antes"), "Los días de antelación", 0, 365, 30)}
    if disparador == "tarea.vencida":
        out = {"dias_vencida": _entero(c.get("dias_vencida"), "Los días de retraso", 1, 365, 1)}
        prioridades = [p for p in (c.get("prioridades") or []) if p in PRIORIDADES]
        if prioridades:
            out["prioridades"] = prioridades
        if c.get("cliente_fiscal_id") not in (None, ""):
            out["cliente_fiscal_id"] = _entero(c.get("cliente_fiscal_id"), "El cliente", 1, 10**9)
        return out
    if disparador == "vencimiento.proximo":
        out = {"dias_antes": _entero(c.get("dias_antes"), "Los días de antelación", 0, 365, 7)}
        if (c.get("modelo") or "").strip():
            out["modelo"] = c["modelo"].strip()[:10]
        return out
    if disparador in ("tarea.creada", "tarea.estado", "tarea.liberada"):
        out = {}
        if disparador == "tarea.estado":
            if c.get("estado") not in ESTADOS_TAREA:
                raise ValueError("Elige a qué estado tiene que pasar la tarea.")
            out["estado"] = c["estado"]
        elif disparador == "tarea.creada":
            modelo = (c.get("modelo") or "").strip()[:10]
            if modelo:
                out["modelo"] = modelo
            if modelo or c.get("desde_vencimiento") in (True, 1, "1", "on", "true"):          # pedir un modelo implica que venga de un vencimiento
                out["desde_vencimiento"] = True
        prioridades = [p for p in (c.get("prioridades") or []) if p in PRIORIDADES]
        if prioridades:
            out["prioridades"] = prioridades
        if c.get("cliente_fiscal_id") not in (None, ""):
            out["cliente_fiscal_id"] = _entero(c.get("cliente_fiscal_id"), "El cliente", 1, 10**9)
        return out
    if disparador == "recurrencia.generada":
        periodicidades = [p for p in (c.get("periodicidades") or []) if p in PERIODICIDADES_TEXTO]
        return {"periodicidades": periodicidades} if periodicidades else {}
    if disparador in ("expediente.creado", "expediente.estado"):
        out = {}
        if disparador == "expediente.estado":
            if not _ID_EXPEDIENTE.fullmatch(c.get("estado") or ""):
                raise ValueError("Elige a qué estado tiene que pasar el expediente.")
            out["estado"] = c["estado"]
        if (c.get("tipo") or "") != "":
            if not _ID_EXPEDIENTE.fullmatch(c["tipo"]):
                raise ValueError("El tipo de expediente no es válido.")
            out["tipo"] = c["tipo"]
        return out
    if disparador == "oportunidad.etapa":
        if not _ID_EXPEDIENTE.fullmatch(c.get("etapa") or ""):
            raise ValueError("Elige a qué etapa tiene que pasar la oportunidad.")
        return {"etapa": c["etapa"]}
    raise ValueError("Disparador no válido.")


def _comprobar_variables(disparador: str, *textos: str) -> None:
    permitidas = VARIABLES[disparador]
    for texto in textos:
        for nombre in _MARCADOR.findall(texto or ""):
            if nombre not in permitidas:
                raise ValueError(f"La variable {{{nombre}}} no existe para este disparador. Puedes usar: " + ", ".join("{" + v + "}" for v in permitidas) + ".")


def validar_acciones(disparador: str, acciones: list) -> list[dict]:
    if not isinstance(acciones, list) or not acciones:
        raise ValueError("La regla necesita al menos una acción.")
    if len(acciones) > MAX_ACCIONES:
        raise ValueError(f"Una regla admite hasta {MAX_ACCIONES} acciones.")
    limpias = []
    for a in acciones:
        tipo = (a or {}).get("tipo")
        if tipo not in ACCIONES:
            raise ValueError("Acción no válida.")
        if tipo in ACCIONES_SOBRE_LA_TAREA and disparador not in DISPARADORES_CON_TAREA:
            raise ValueError("Esa acción actúa sobre la tarea del disparador, así que solo vale cuando el disparador es una tarea.")
        if tipo == "crear_tarea":
            asunto = (a.get("asunto") or "").strip()[:300]
            if not asunto:
                raise ValueError("La tarea que se crea necesita un asunto.")
            _comprobar_variables(disparador, asunto, a.get("cuerpo"))
            limpias.append({"tipo": tipo, "asunto": asunto, "cuerpo": (a.get("cuerpo") or "").strip()[:2000],
                            "prioridad": a.get("prioridad") if a.get("prioridad") in PRIORIDADES else "normal",
                            "dias_plazo": _entero(a.get("dias_plazo"), "El plazo de la tarea", 0, 365, 7), "asignar_a": _destino(a.get("asignar_a"), "responsable")})
        elif tipo == "notificar":
            titulo = (a.get("titulo") or "").strip()[:150]
            if not titulo:
                raise ValueError("El aviso necesita un título.")
            _comprobar_variables(disparador, titulo, a.get("cuerpo"))
            limpias.append({"tipo": tipo, "titulo": titulo, "cuerpo": (a.get("cuerpo") or "").strip()[:500], "a": _destino(a.get("a"), "responsable")})
        elif tipo == "fijar_fecha":
            limpias.append({"tipo": tipo, "dias_plazo": _entero(a.get("dias_plazo"), "El plazo", 0, 365, 7), "solo_si_vacia": a.get("solo_si_vacia") not in (False, "0", 0, "")})
        elif tipo == "asignar":
            limpias.append({"tipo": tipo, "a": _persona(a.get("a"), "A quién se asigna la tarea")})
        elif tipo == "pedir_revision":
            _comprobar_variables(disparador, a.get("nota"))
            limpias.append({"tipo": tipo, "revisor": _persona(a.get("revisor"), "Quién revisa la tarea"), "nota": (a.get("nota") or "").strip()[:500]})
        else:
            texto = (a.get("texto") or "").strip()[:200]
            if not texto:
                raise ValueError("El comentario necesita un texto.")
            _comprobar_variables(disparador, texto)
            limpias.append({"tipo": tipo, "texto": texto})
    return limpias


def _persona(valor, que: str) -> int:
    """Una persona concreta (no «el responsable» ni «la dirección»): estas acciones necesitan saber exactamente a quién."""
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{que}: elige una persona.") from None
    if n < 1:
        raise ValueError(f"{que}: elige una persona.")
    return n


def _destino(valor, defecto: str):
    """«responsable» (quien lleva el objeto), «direccion» (los directivos del despacho) o el id de una persona."""
    if valor in (None, ""):
        return defecto
    if valor in ("responsable", "direccion"):
        return valor
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ValueError("El destinatario no es válido.") from None


def comprobar_pertenencia(tenant_id: int, condiciones: dict, acciones: list[dict], disparador: str | None = None) -> None:
    """Las personas y el cliente que nombra una regla tienen que ser del propio despacho (también al crearla por la API o por código, no solo desde la pantalla). En los disparadores de
    expediente, el tipo y el estado tienen que existir para ese despacho."""
    if disparador == "oportunidad.etapa":
        from . import comercial, verticales
        if not verticales.esta_activo(tenant_id, "comercial"):
            raise ValueError("Tu despacho no tiene el módulo Comercial.")
        if condiciones.get("etapa") not in {e["clave"] for e in comercial.listar_etapas(tenant_id)}:
            raise ValueError("Esa etapa no existe en tu embudo.")
    if disparador in ("expediente.creado", "expediente.estado"):
        from . import verticales
        tipos = verticales.tipos_expediente(tenant_id)
        if condiciones.get("tipo") and condiciones["tipo"] not in tipos:
            raise ValueError("Ese tipo de expediente no está disponible para tu despacho.")
        if condiciones.get("estado") and not any(t.estado(condiciones["estado"]) for t in ([tipos[condiciones["tipo"]]] if condiciones.get("tipo") else tipos.values())):
            raise ValueError("Ese estado no existe para ese tipo de expediente.")
    personas = {a["asignar_a"] for a in acciones if a["tipo"] == "crear_tarea" and isinstance(a["asignar_a"], int)}
    personas |= {a["a"] for a in acciones if a["tipo"] in ("notificar", "asignar") and isinstance(a["a"], int)}
    personas |= {a["revisor"] for a in acciones if a["tipo"] == "pedir_revision"}
    conn = db.get_connection()
    try:
        for u in personas:
            if conn.execute("SELECT 1 FROM usuarios WHERE id = ? AND tenant_id = ?", (u, tenant_id)).fetchone() is None:
                raise ValueError("Una de las personas elegidas no es de tu despacho.")
        cliente = condiciones.get("cliente_fiscal_id")
        if cliente and conn.execute("SELECT 1 FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente, tenant_id)).fetchone() is None:
            raise ValueError("El cliente elegido no es de tu despacho.")
    finally:
        conn.close()


def comprobar_coherencia(disparador: str, condiciones: dict, acciones: list[dict]) -> None:
    """Combinaciones que nunca pueden funcionar y que es mejor rechazar al guardar que ver fallar cada vez: pedir la revisión de una tarea que, por la propia condición, ya está completada."""
    if disparador == "tarea.estado" and condiciones.get("estado") == "completada" and any(a["tipo"] == "pedir_revision" for a in acciones):
        raise ValueError("No se puede pedir la revisión de una tarea ya completada: elige otro estado o quita esa acción.")
    if disparador == "tarea.estado" and condiciones.get("estado") == "en_revision" and any(a["tipo"] == "pedir_revision" for a in acciones):
        raise ValueError("La tarea ya está en revisión cuando se activa esta regla: no se puede pedir otra revisión. Elige otro estado o quita esa acción.")


def _destino_de_formulario(valor: str):
    """«responsable», «direccion» o «u:<id>» (una persona concreta)."""
    if valor and valor.startswith("u:"):
        return valor[2:]
    return valor or "responsable"


def formulario_a_regla(form, disparador: str) -> tuple[dict, list[dict]]:
    """Traduce el formulario del constructor (campos `c_*` para las condiciones y `a<i>_*` para hasta cinco acciones) a condiciones y acciones SIN validar: la validación y los límites los
    pone `validar_condiciones`/`validar_acciones` al guardar, igual que por la API. Las filas de acción sin tipo se saltan."""
    if disparador == "certificado.caduca":
        cond = {"dias_antes": form.get("c_dias_cert")}
    elif disparador == "tarea.vencida":
        cond = {"dias_vencida": form.get("c_dias_tarea"), "prioridades": form.getlist("c_prioridades"), "cliente_fiscal_id": form.get("c_cliente")}
    elif disparador == "vencimiento.proximo":
        cond = {"dias_antes": form.get("c_dias_venc"), "modelo": form.get("c_modelo")}
    elif disparador == "tarea.creada":
        cond = {"prioridades": form.getlist("c_prioridades_c"), "cliente_fiscal_id": form.get("c_cliente_c"), "desde_vencimiento": form.get("c_venc_c"), "modelo": form.get("c_modelo_c")}
    elif disparador == "tarea.estado":
        cond = {"estado": form.get("c_estado_e"), "prioridades": form.getlist("c_prioridades_e"), "cliente_fiscal_id": form.get("c_cliente_e")}
    elif disparador == "tarea.liberada":
        cond = {"prioridades": form.getlist("c_prioridades_l"), "cliente_fiscal_id": form.get("c_cliente_l")}
    elif disparador == "recurrencia.generada":
        cond = {"periodicidades": form.getlist("c_periodicidades_r")}
    elif disparador == "expediente.creado":
        cond = {"tipo": form.get("c_tipo_xc")}
    elif disparador == "expediente.estado":
        cond = {"estado": form.get("c_estado_x"), "tipo": form.get("c_tipo_x")}
    elif disparador == "oportunidad.etapa":
        cond = {"etapa": form.get("c_etapa_o")}
    else:
        raise ValueError("Disparador no válido.")
    acciones = []
    for i in range(MAX_ACCIONES):
        tipo = (form.get(f"a{i}_tipo") or "").strip()
        if not tipo:
            continue
        if tipo == "crear_tarea":
            acciones.append({"tipo": tipo, "asunto": form.get(f"a{i}_asunto"), "cuerpo": form.get(f"a{i}_cuerpo"), "prioridad": form.get(f"a{i}_prioridad"),
                             "dias_plazo": form.get(f"a{i}_dias_plazo"), "asignar_a": _destino_de_formulario(form.get(f"a{i}_dest"))})
        elif tipo == "notificar":
            acciones.append({"tipo": tipo, "titulo": form.get(f"a{i}_titulo"), "cuerpo": form.get(f"a{i}_cuerpo_aviso"), "a": _destino_de_formulario(form.get(f"a{i}_dest_aviso"))})
        elif tipo == "fijar_fecha":
            acciones.append({"tipo": tipo, "dias_plazo": form.get(f"a{i}_dias_fecha"), "solo_si_vacia": bool(form.get(f"a{i}_solo_vacia"))})
        elif tipo == "asignar":
            acciones.append({"tipo": tipo, "a": form.get(f"a{i}_persona")})
        elif tipo == "pedir_revision":
            acciones.append({"tipo": tipo, "revisor": form.get(f"a{i}_revisor"), "nota": form.get(f"a{i}_nota_rev")})
        else:
            acciones.append({"tipo": tipo, "texto": form.get(f"a{i}_texto")})
    return cond, acciones


def regla_a_formulario(regla: dict | None) -> dict:
    """Los valores con los que se rellena el constructor al editar una regla (o vacíos al crearla)."""
    if regla is None:
        return {"nombre": "", "disparador": "certificado.caduca", "activa": True, "condiciones": {}, "acciones": []}
    return {"nombre": regla["nombre"], "disparador": regla["disparador"], "activa": regla["activa"], "condiciones": regla["condiciones"], "acciones": regla["acciones"]}


# --- CRUD de reglas (solo la dirección) --------------------------------------------------------------------------------

def _regla(f) -> dict:
    d = dict(f)
    d["condiciones"], d["acciones"], d["activa"] = json.loads(d["condiciones"]), json.loads(d["acciones"]), bool(d["activa"])
    d["disparador_texto"] = DISPARADORES.get(d["disparador"], d["disparador"])
    return d


def _exigir_direccion(usuario_id: int) -> None:
    from . import acceso
    if not acceso.es_directivo(usuario_id):
        raise PermissionError("Solo la dirección del despacho gestiona las automatizaciones.")


def listar_reglas(tenant_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        return [_regla(f) for f in conn.execute("SELECT * FROM automatizaciones_reglas WHERE tenant_id = ? ORDER BY id", (tenant_id,))]
    finally:
        conn.close()


def obtener_regla(tenant_id: int, regla_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM automatizaciones_reglas WHERE id = ? AND tenant_id = ?", (regla_id, tenant_id)).fetchone()
        return _regla(f) if f else None
    finally:
        conn.close()


def crear_regla(tenant_id: int, usuario_id: int, nombre: str, disparador: str, condiciones: dict, acciones: list, activa: bool = True) -> int:
    _exigir_direccion(usuario_id)
    nombre = (nombre or "").strip()[:120]
    if not nombre:
        raise ValueError("La regla necesita un nombre.")
    if disparador not in DISPARADORES:
        raise ValueError("Disparador no válido.")
    cond, acc = validar_condiciones(disparador, condiciones), validar_acciones(disparador, acciones)
    comprobar_pertenencia(tenant_id, cond, acc, disparador)
    comprobar_coherencia(disparador, cond, acc)
    conn = db.get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM automatizaciones_reglas WHERE tenant_id = ?", (tenant_id,)).fetchone()[0] >= MAX_REGLAS:
            raise ValueError(f"Un despacho admite hasta {MAX_REGLAS} reglas.")
        cur = conn.execute("INSERT INTO automatizaciones_reglas (tenant_id, nombre, disparador, condiciones, acciones, activa, creada_por, creada_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, nombre, disparador, json.dumps(cond), json.dumps(acc, ensure_ascii=False), 1 if activa else 0, usuario_id, db.now_iso()))
        auditoria.registrar(tenant_id, usuario_id, "automatizacion.crear", "regla", cur.lastrowid, {"disparador": disparador}, conn=conn)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def cambiar_regla(tenant_id: int, usuario_id: int, regla_id: int, *, nombre=None, condiciones=None, acciones=None, activa=None) -> dict:
    """Editar condiciones o acciones sube la versión: las ocurrencias ya atendidas no se repiten (la clave no incluye la versión), pero queda anotado con cuál se hicieron."""
    _exigir_direccion(usuario_id)
    r = obtener_regla(tenant_id, regla_id)
    if r is None:
        raise LookupError("Regla no encontrada.")
    nuevo_nombre = (nombre if nombre is not None else r["nombre"]).strip()[:120]
    if not nuevo_nombre:
        raise ValueError("La regla necesita un nombre.")
    cond = validar_condiciones(r["disparador"], condiciones) if condiciones is not None else r["condiciones"]
    acc = validar_acciones(r["disparador"], acciones) if acciones is not None else r["acciones"]
    cambia_logica = cond != r["condiciones"] or acc != r["acciones"]
    if cambia_logica:
        comprobar_pertenencia(tenant_id, cond, acc, r["disparador"])
        comprobar_coherencia(r["disparador"], cond, acc)
    conn = db.get_connection()
    try:
        if acc != r["acciones"]:
            # Lo que quedó a medias llevaba el progreso de las acciones ANTERIORES: reintentarlo con otras podría repetir o saltarse pasos. Se deja a la vista para que la dirección decida.
            conn.execute("UPDATE automatizaciones_ejecuciones SET estado = 'fallida', error = 'La regla cambió mientras esta ejecución estaba a medias', proximo_intento = NULL, avisada = 1 "
                         "WHERE regla_id = ? AND estado IN ('error', 'pendiente') AND progreso != '[]'", (regla_id,))
        conn.execute("UPDATE automatizaciones_reglas SET nombre = ?, condiciones = ?, acciones = ?, activa = ?, version = version + ?, actualizada_en = ? WHERE id = ? AND tenant_id = ?",
                     (nuevo_nombre, json.dumps(cond), json.dumps(acc, ensure_ascii=False), 1 if (r["activa"] if activa is None else activa) else 0, 1 if cambia_logica else 0, db.now_iso(), regla_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "automatizacion.cambiar", "regla", regla_id, {"activa": activa, "logica": cambia_logica}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return obtener_regla(tenant_id, regla_id)


def borrar_regla(tenant_id: int, usuario_id: int, regla_id: int) -> bool:
    _exigir_direccion(usuario_id)
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM automatizaciones_reglas WHERE id = ? AND tenant_id = ?", (regla_id, tenant_id)).fetchone() is None:
            return False
        conn.execute("DELETE FROM automatizaciones_ejecuciones WHERE regla_id = ?", (regla_id,))
        conn.execute("DELETE FROM automatizaciones_reglas WHERE id = ? AND tenant_id = ?", (regla_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "automatizacion.borrar", "regla", regla_id, conn=conn)
        conn.commit()
        return True
    finally:
        conn.close()


PLANTILLAS = {
    "renovar_certificado": {"nombre": "Renovar certificados 30 días antes", "disparador": "certificado.caduca", "condiciones": {"dias_antes": 30},
                            "acciones": [{"tipo": "crear_tarea", "asunto": "Renovar el certificado de {titular} (caduca el {fecha})", "prioridad": "alta", "dias_plazo": 20, "asignar_a": "responsable"},
                                         {"tipo": "notificar", "titulo": "Certificado de {titular} a punto de caducar", "cuerpo": "Caduca el {fecha} (en {dias} días). Se ha creado la tarea de renovación.", "a": "responsable"}]},
    "tarea_vencida": {"nombre": "Avisar de tareas vencidas hace 3 días", "disparador": "tarea.vencida", "condiciones": {"dias_vencida": 3},
                      "acciones": [{"tipo": "notificar", "titulo": "Tarea vencida: {asunto}", "cuerpo": "Venció el {fecha} y sigue sin completarse.", "a": "responsable"},
                                   {"tipo": "comentar", "texto": "Aviso automático: lleva {dias} días vencida."}]},
    "tarea_bloqueada": {"nombre": "Avisar a la dirección cuando una tarea quede en espera", "disparador": "tarea.estado", "condiciones": {"estado": "esperando"},
                        "acciones": [{"tipo": "notificar", "titulo": "Tarea en espera: {asunto}", "cuerpo": "Cliente: {cliente}. Antes estaba en «{anterior}».", "a": "direccion"}]},
    "tarea_urgente": {"nombre": "Avisar de las tareas urgentes nuevas", "disparador": "tarea.creada", "condiciones": {"prioridades": ["alta"]},
                      "acciones": [{"tipo": "notificar", "titulo": "Tarea urgente nueva: {asunto}", "cuerpo": "Fecha límite: {fecha}", "a": "responsable"}]},
    "recurrente_con_fecha": {"nombre": "Poner fecha límite a las tareas recurrentes (en 7 días)", "disparador": "recurrencia.generada", "condiciones": {},
                             "acciones": [{"tipo": "fijar_fecha", "dias_plazo": 7, "solo_si_vacia": True}]},
    "expediente_cerrado": {"nombre": "Avisar a la dirección cuando se cierre un expediente", "disparador": "expediente.estado", "condiciones": {"estado": "cerrado"},
                           "acciones": [{"tipo": "notificar", "titulo": "Expediente cerrado: {expediente}", "cuerpo": "Cliente: {cliente}. Tipo: {tipo}.", "a": "direccion"}]},
    "oportunidad_ganada": {"nombre": "Avisar a la dirección cuando se gane una oportunidad", "disparador": "oportunidad.etapa", "condiciones": {"etapa": "ganada"},
                           "acciones": [{"tipo": "notificar", "titulo": "Oportunidad ganada: {oportunidad}", "cuerpo": "{contacto}: {importe}. Lleva: {responsable}.", "a": "direccion"}]},
    "preparar_modelo": {"nombre": "Preparar el modelo 7 días antes", "disparador": "vencimiento.proximo", "condiciones": {"dias_antes": 7},
                        "acciones": [{"tipo": "crear_tarea", "asunto": "Preparar el modelo {modelo} de {cliente} ({periodo})", "prioridad": "normal", "dias_plazo": 5, "asignar_a": "responsable"}]},
}


# --- Tiempo ------------------------------------------------------------------------------------------------------------

def hoy_del_despacho(tenant_id: int, ahora: datetime | None = None) -> date:
    from zoneinfo import ZoneInfo
    conn = db.get_connection()
    try:
        t = conn.execute("SELECT zona_horaria FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    try:
        zona = ZoneInfo((t["zona_horaria"] if t and t["zona_horaria"] else None) or "Europe/Madrid")
    except Exception:  # noqa: BLE001
        zona = ZoneInfo("Europe/Madrid")
    return (ahora or datetime.now(timezone.utc)).astimezone(zona).date()


# --- Quién cumple el disparador (cada uno devuelve ocurrencias con su clave estable) ------------------------------------

def _ocurrencias(tenant_id: int, regla: dict, hoy: date) -> list[dict]:
    if regla["disparador"] in DISPARADORES_DE_EVENTO:
        return []                    # reaccionan a un evento: ver `procesar_eventos`
    c = regla["condiciones"]
    conn = db.get_connection()
    try:
        if regla["disparador"] == "certificado.caduca":
            filas = conn.execute(
                """SELECT c.id, c.not_after, c.custodio_id, c.cliente_titular_id,
                          COALESCE(NULLIF(c.nombre_comun, ''), NULLIF(c.sujeto, ''), 'certificado ' || c.id) AS titular
                   FROM certificados c WHERE c.tenant_id = ? AND c.not_after IS NOT NULL AND c.es_ca = 0
                     AND c.estado_operativo IN ('inventariado', 'autorizado', 'suspendido')
                     AND NOT EXISTS (SELECT 1 FROM certificados n WHERE n.sustituye_a = c.id)
                   ORDER BY c.not_after LIMIT 1000""", (tenant_id,)).fetchall()
            out = []
            for f in filas:
                dias = (date.fromisoformat(f["not_after"][:10]) - hoy).days
                if dias <= c["dias_antes"]:
                    out.append({"clave": f"cert:{f['id']}:{f['not_after'][:10]}", "objeto": f"certificado {f['id']}", "responsable": f["custodio_id"], "cliente_fiscal_id": f["cliente_titular_id"],
                                "datos": {"titular": f["titular"], "fecha": f["not_after"][:10], "dias": max(dias, 0)}, "fecha": f["not_after"][:10]})
            return out
        if regla["disparador"] == "tarea.vencida":
            limite = (hoy - timedelta(days=c["dias_vencida"])).isoformat()
            filas = conn.execute(
                """SELECT t.id, t.asunto, t.fecha_vencimiento, t.prioridad, t.cliente_fiscal_id, COALESCE(t.asignada_a, t.usuario_id) AS responsable
                   FROM tareas_outlook t JOIN usuarios u ON u.id = t.usuario_id
                   WHERE u.tenant_id = ? AND t.papelera_en IS NULL AND t.estado != 'completada' AND t.fecha_vencimiento IS NOT NULL
                     AND substr(t.fecha_vencimiento, 1, 10) <= ? AND COALESCE(t.referencia_externa, '') NOT LIKE 'auto:%'
                   ORDER BY t.fecha_vencimiento LIMIT 1000""", (tenant_id, limite)).fetchall()
            out = []
            for f in filas:
                if c.get("prioridades") and f["prioridad"] not in c["prioridades"]:
                    continue
                if c.get("cliente_fiscal_id") and f["cliente_fiscal_id"] != c["cliente_fiscal_id"]:
                    continue
                dias = (hoy - date.fromisoformat(f["fecha_vencimiento"][:10])).days
                out.append({"clave": f"tarea:{f['id']}:{f['fecha_vencimiento'][:10]}", "objeto": f"tarea {f['id']}", "responsable": f["responsable"], "cliente_fiscal_id": f["cliente_fiscal_id"],
                            "tarea_id": f["id"], "datos": {"asunto": f["asunto"], "fecha": f["fecha_vencimiento"][:10], "dias": dias}, "fecha": f["fecha_vencimiento"][:10]})
            return out
        filas = conn.execute(
            """SELECT v.id, v.modelo, v.periodo, v.fecha_limite, v.usuario_id, v.cliente_fiscal_id, cf.nombre AS cliente FROM vencimientos_fiscales v
               JOIN clientes_fiscales cf ON cf.id = v.cliente_fiscal_id
               WHERE v.tenant_id = ? AND v.papelera_en IS NULL AND v.estado = 'pendiente' AND substr(v.fecha_limite, 1, 10) >= ?
               ORDER BY v.fecha_limite LIMIT 1000""", (tenant_id, hoy.isoformat())).fetchall()
        out = []
        for f in filas:
            dias = (date.fromisoformat(f["fecha_limite"][:10]) - hoy).days
            if dias <= c["dias_antes"] and (not c.get("modelo") or f["modelo"] == c["modelo"]):
                out.append({"clave": f"venc:{f['id']}:{f['fecha_limite'][:10]}", "objeto": f"{f['modelo']} {f['periodo']} de {f['cliente']}", "responsable": f["usuario_id"],
                            "cliente_fiscal_id": f["cliente_fiscal_id"], "datos": {"modelo": f["modelo"], "periodo": f["periodo"], "cliente": f["cliente"], "fecha": f["fecha_limite"][:10], "dias": dias},
                            "fecha": f["fecha_limite"][:10]})
        return out
    finally:
        conn.close()


# --- Acciones ----------------------------------------------------------------------------------------------------------

_MARCADOR = re.compile(r"\{([a-z_]+)\}")


def rellenar(texto: str, datos: dict) -> str:
    """Sustituye {clave} por su valor; una clave desconocida se queda vacía. Nada más: sin atributos ni expresiones."""
    return _MARCADOR.sub(lambda m: str(datos.get(m.group(1), "")), texto)


def _direccion_del_despacho(tenant_id: int) -> list[int]:
    conn = db.get_connection()
    try:
        return [f["id"] for f in conn.execute("SELECT id FROM usuarios WHERE tenant_id = ? AND supervisor_tenant = 1", (tenant_id,))]
    finally:
        conn.close()


def _usuario_del_despacho(tenant_id: int, usuario_id) -> int | None:
    if not usuario_id:
        return None
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT id FROM usuarios WHERE id = ? AND tenant_id = ?", (usuario_id, tenant_id)).fetchone()
        return f["id"] if f else None
    finally:
        conn.close()


def _con_acceso_al_expediente(tenant_id: int, expediente_id: int, usuarios: list[int]) -> list[int]:
    """Un aviso o una tarea sobre un expediente solo llega a quien puede verlo (confidencial, oficina…): la regla nunca enseña su título a nadie más."""
    from . import nucleo
    direccion = set(_direccion_del_despacho(tenant_id))
    return [u for u in usuarios if nucleo.obtener_expediente(tenant_id, expediente_id, u, u in direccion) is not None]


def _destinatarios(tenant_id: int, destino, oc: dict, regla: dict) -> list[int]:
    if destino == "direccion":
        quienes = _direccion_del_despacho(tenant_id)
    elif destino == "responsable":
        quien = _usuario_del_despacho(tenant_id, oc.get("responsable")) or _usuario_del_despacho(tenant_id, regla["creada_por"])
        quienes = [quien] if quien else _direccion_del_despacho(tenant_id)[:1]
    else:
        quien = _usuario_del_despacho(tenant_id, destino)
        quienes = [quien] if quien else []
    if oc.get("oportunidad_id"):
        from . import comercial
        return [u for u in quienes if comercial.obtener_oportunidad(tenant_id, u, oc["oportunidad_id"], incluir_papelera=True) is not None]
    return _con_acceso_al_expediente(tenant_id, oc["expediente_id"], quienes) if oc.get("expediente_id") else quienes


_ACTUANDO: contextvars.ContextVar[bool] = contextvars.ContextVar("automatizacion_actuando", default=False)


def _aplicar(tenant_id: int, regla: dict, oc: dict, accion: dict, ejecucion_clave: str, hoy: date) -> str:
    """Hace UNA acción. Mientras actúa, los eventos que provoque (p. ej. la tarea que crea) no se encolan para otras reglas: así una automatización nunca se dispara a sí misma ni a otra en cadena."""
    marca = _ACTUANDO.set(True)
    try:
        return _aplicar_accion(tenant_id, regla, oc, accion, ejecucion_clave, hoy)
    finally:
        _ACTUANDO.reset(marca)


def _aplicar_accion(tenant_id: int, regla: dict, oc: dict, accion: dict, ejecucion_clave: str, hoy: date) -> str:
    datos = dict(oc["datos"])
    if accion["tipo"] == "crear_tarea":
        quien = _destinatarios(tenant_id, accion["asignar_a"], oc, regla)
        if not quien:
            raise RuntimeError("No hay a quién asignar la tarea.")
        asunto = rellenar(accion["asunto"], datos)
        tarea_id = db.crear_tarea_outlook(quien[0], asunto=asunto, cuerpo=rellenar(accion["cuerpo"], datos) or None, prioridad=accion["prioridad"],
                                          fecha_vencimiento=(hoy + timedelta(days=accion["dias_plazo"])).isoformat(), cliente_fiscal_id=oc.get("cliente_fiscal_id"))
        conn = db.get_connection()
        try:
            conn.execute("UPDATE tareas_outlook SET referencia_externa = ? WHERE id = ?", (f"auto:{regla['id']}:{ejecucion_clave}"[:200], tarea_id))
            conn.commit()
        finally:
            conn.close()
        db.registrar_actividad_tarea(quien[0], tarea_id, "automatizacion", regla["nombre"])
        return f"tarea {tarea_id}"
    if accion["tipo"] == "notificar":
        from . import notificaciones
        enviados = 0
        for u in _destinatarios(tenant_id, accion["a"], oc, regla):
            notificaciones.crear_y_enviar(u, "automatizacion", rellenar(accion["titulo"], datos), rellenar(accion["cuerpo"], datos),
                                          url="/tareas/automatizaciones")
            enviados += 1
        return f"{enviados} aviso(s)"
    if not oc.get("tarea_id"):
        raise RuntimeError("No hay una tarea sobre la que actuar.")
    if accion["tipo"] == "comentar":
        db.registrar_actividad_tarea(oc.get("responsable") or regla["creada_por"] or 0, oc["tarea_id"], "automatizacion", rellenar(accion["texto"], datos))
        return "comentario"
    return _actuar_sobre_la_tarea(tenant_id, regla, oc, accion, datos, hoy)


def _actuar_sobre_la_tarea(tenant_id: int, regla: dict, oc: dict, accion: dict, datos: dict, hoy: date) -> str:
    """Fijar fecha, asignar y pedir revisión. Actúan en nombre de la persona dueña de la tarea (es quien tiene derecho a hacerlo) y dejan constancia de la regla en el historial. Si ya está hecho
    (la fecha ya estaba puesta, ya hay una revisión pendiente) no es un fallo."""
    tarea = _tarea_del_evento(oc["tarea_id"])
    if tarea is None:
        raise RuntimeError("La tarea ya no existe.")
    dueno = tarea["dueno"]
    if accion["tipo"] == "fijar_fecha":
        if accion["solo_si_vacia"] and tarea["fecha_vencimiento"]:
            return "ya tenía fecha"
        db.editar_tarea_outlook(dueno, tarea["id"], fecha_vencimiento=(hoy + timedelta(days=accion["dias_plazo"])).isoformat())
        db.registrar_actividad_tarea(dueno, tarea["id"], "automatizacion", f"{regla['nombre']}: fecha límite en {accion['dias_plazo']} días")
        return "fecha fijada"
    if accion["tipo"] == "asignar":
        if _usuario_del_despacho(tenant_id, accion["a"]) is None:
            raise RuntimeError("La persona elegida ya no es de este despacho.")
        if tarea["responsable"] == accion["a"] and tarea["dueno"] != accion["a"]:
            return "ya estaba asignada"
        if not db.asignar_tarea_outlook(dueno, tarea["id"], accion["a"]):
            raise RuntimeError("No se pudo asignar la tarea.")
        db.registrar_actividad_tarea(dueno, tarea["id"], "automatizacion", f"{regla['nombre']}: asignada")
        return "asignada"
    from . import tareas_trabajo
    try:
        tareas_trabajo.solicitar_revision(dueno, tarea["id"], accion["revisor"], rellenar(accion["nota"], datos) or None)
    except tareas_trabajo.TransicionInvalida as e:
        if e.codigo == "revision_pendiente":
            return "ya había una revisión pendiente"
        raise RuntimeError(str(e)) from e
    return "revisión pedida"


def _avisar_fallo(tenant_id: int, regla: dict, objeto: str, error: str) -> None:
    from . import notificaciones
    for u in _direccion_del_despacho(tenant_id):
        notificaciones.crear_y_enviar(u, "automatizacion_fallo", f"Falló la automatización «{regla['nombre']}»", f"{objeto}: {error}"[:300], url="/tareas/automatizaciones")


# --- Pasada ---------------------------------------------------------------------------------------------------------

def _ahora_texto(ahora: datetime) -> str:
    return ahora.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _ejecutar_una(tenant_id: int, regla: dict, oc: dict, ejecucion: dict, hoy: date, ahora: datetime) -> str:
    """Hace las acciones que falten (las ya hechas constan en `progreso`) y deja el resultado. Devuelve el estado final."""
    hechas = json.loads(ejecucion["progreso"])
    error = None
    for i, accion in enumerate(regla["acciones"]):
        if i < len(hechas):
            continue
        try:
            hechas.append(_aplicar(tenant_id, regla, oc, accion, oc["clave"], hoy))
        except Exception as e:  # noqa: BLE001
            error = f"{type(e).__name__}: {e}"[:300]
            break
        _guardar_progreso(ejecucion["id"], hechas)
    intentos = ejecucion["intentos"] + 1
    if error is None:
        estado, proximo, avisada = "ok", None, ejecucion["avisada"]
    elif intentos >= MAX_INTENTOS:
        estado, proximo = "fallida", None
        avisada = 1
        if not ejecucion["avisada"]:
            _avisar_fallo(tenant_id, regla, oc["objeto"], error)
    else:
        estado, avisada = "error", ejecucion["avisada"]
        proximo = _ahora_texto(ahora + timedelta(minutes=ESPERAS_MINUTOS[min(intentos - 1, len(ESPERAS_MINUTOS) - 1)]))
    conn = db.get_connection()
    try:
        conn.execute("UPDATE automatizaciones_ejecuciones SET estado = ?, intentos = ?, error = ?, progreso = ?, proximo_intento = ?, avisada = ?, actualizada_en = ? WHERE id = ?",
                     (estado, intentos, error, json.dumps(hechas, ensure_ascii=False), proximo, avisada, _ahora_texto(ahora), ejecucion["id"]))
        conn.commit()
    finally:
        conn.close()
    return estado


def _guardar_progreso(ejecucion_id: int, hechas: list) -> None:
    conn = db.get_connection()
    try:
        conn.execute("UPDATE automatizaciones_ejecuciones SET progreso = ? WHERE id = ?", (json.dumps(hechas, ensure_ascii=False), ejecucion_id))
        conn.commit()
    finally:
        conn.close()


def simular(tenant_id: int, regla_id: int, ahora: datetime | None = None) -> dict:
    """Qué haría la regla ahora: ocurrencias que cumplen y cuáles son nuevas. No escribe nada."""
    regla = obtener_regla(tenant_id, regla_id)
    if regla is None:
        raise LookupError("Regla no encontrada.")
    hoy = hoy_del_despacho(tenant_id, ahora)
    if regla["disparador"] in DISPARADORES_DE_EVENTO:
        return _simular_evento(tenant_id, regla, hoy)
    ocs = _ocurrencias(tenant_id, regla, hoy)
    conn = db.get_connection()
    try:
        hechas = {f["clave"] for f in conn.execute("SELECT clave FROM automatizaciones_ejecuciones WHERE regla_id = ?", (regla_id,))}
    finally:
        conn.close()
    nuevas = [o for o in ocs if o["clave"] not in hechas]
    return {"cumplen": len(ocs), "nuevas": len(nuevas), "ya_atendidas": len(ocs) - len(nuevas),
            "ejemplos": [{"objeto": o["objeto"], "fecha": o["fecha"], "datos": o["datos"]} for o in nuevas[:20]]}


def _simular_evento(tenant_id: int, regla: dict, hoy: date) -> dict:
    """Una regla de evento reacciona cuando ocurre, así que no hay «casos ahora»: se enseñan los de los últimos 7 días que la habrían activado. No escribe nada."""
    desde = (hoy - timedelta(days=7)).isoformat()
    if regla["disparador"] == "recurrencia.generada":
        return _simular_recurrencia(tenant_id, regla, desde)
    if regla["disparador"] == "tarea.liberada":
        return _simular_liberada(tenant_id, regla, desde)
    if regla["disparador"] in ("expediente.creado", "expediente.estado"):
        return _simular_expediente(tenant_id, regla, desde)
    if regla["disparador"] == "oportunidad.etapa":
        return _simular_oportunidad(tenant_id, regla, desde)
    estado = regla["condiciones"].get("estado")
    campo = "t.creada_en" if regla["disparador"] == "tarea.creada" else "t.actualizada_en"
    conn = db.get_connection()
    try:
        filas = conn.execute(
            f"""SELECT t.id FROM tareas_outlook t JOIN usuarios u ON u.id = t.usuario_id
                WHERE u.tenant_id = ? AND t.papelera_en IS NULL AND substr({campo}, 1, 10) >= ? {"AND t.estado = ?" if estado else ""} ORDER BY {campo} DESC LIMIT 200""",
            (tenant_id, desde, *([estado] if estado else []))).fetchall()
    finally:
        conn.close()
    ejemplos = []
    for f in filas:
        tarea = _tarea_del_evento(f["id"])
        if tarea and cumple_evento(regla, tarea, {"a": estado}):
            oc = _ocurrencia_de_evento(0, regla, tarea, {"a": estado})
            ejemplos.append({"objeto": oc["objeto"], "fecha": oc["fecha"], "datos": oc["datos"]})
    return {"cumplen": len(ejemplos), "nuevas": len(ejemplos), "ya_atendidas": 0, "reciente": True, "ejemplos": ejemplos[:20]}


def _simular_liberada(tenant_id: int, regla: dict, desde: str) -> dict:
    """Tareas abiertas que esperaban a otras y que ahora están libres (todo lo previo está completado), movidas en los últimos 7 días."""
    conn = db.get_connection()
    try:
        filas = conn.execute(
            """SELECT DISTINCT t.id FROM tareas_dependencias d JOIN tareas_outlook t ON t.id = d.tarea_id JOIN usuarios u ON u.id = t.usuario_id
               WHERE u.tenant_id = ? AND t.papelera_en IS NULL AND t.estado != 'completada' AND substr(t.actualizada_en, 1, 10) >= ? LIMIT 200""", (tenant_id, desde)).fetchall()
        libres = [f["id"] for f in filas if not db.bloqueos_de_tareas([f["id"]]).get(f["id"])]
    finally:
        conn.close()
    ejemplos = []
    for tarea_id in libres:
        tarea = _tarea_del_evento(tarea_id)
        if tarea and cumple_evento(regla, tarea, {}):
            oc = _ocurrencia_de_evento(0, regla, tarea, {})
            ejemplos.append({"objeto": oc["objeto"], "fecha": oc["fecha"], "datos": oc["datos"]})
    return {"cumplen": len(ejemplos), "nuevas": len(ejemplos), "ya_atendidas": 0, "reciente": True, "ejemplos": ejemplos[:20]}


def _simular_recurrencia(tenant_id: int, regla: dict, desde: str) -> dict:
    conn = db.get_connection()
    try:
        filas = conn.execute(
            """SELECT t.id, r.periodicidad FROM tareas_outlook t JOIN tareas_recurrentes r ON r.id = t.tarea_recurrente_id JOIN usuarios u ON u.id = t.usuario_id
               WHERE u.tenant_id = ? AND t.papelera_en IS NULL AND substr(t.creada_en, 1, 10) >= ? ORDER BY t.creada_en DESC LIMIT 200""", (tenant_id, desde)).fetchall()
    finally:
        conn.close()
    ejemplos = []
    for f in filas:
        tarea, datos = _tarea_del_evento(f["id"]), {"periodicidad": f["periodicidad"]}
        if tarea and cumple_evento(regla, tarea, datos):
            oc = _ocurrencia_de_evento(0, regla, tarea, datos)
            ejemplos.append({"objeto": oc["objeto"], "fecha": oc["fecha"], "datos": oc["datos"]})
    return {"cumplen": len(ejemplos), "nuevas": len(ejemplos), "ya_atendidas": 0, "reciente": True, "ejemplos": ejemplos[:20]}


def _simular_oportunidad(tenant_id: int, regla: dict, desde: str) -> dict:
    """Oportunidades que han llegado a esa etapa en los últimos 7 días (por la cronología de cambios de etapa)."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT DISTINCT o.id FROM crm_oportunidades o WHERE o.tenant_id = ? AND o.papelera_en IS NULL AND o.etapa = ? AND substr(COALESCE(o.actualizada_en, o.creada_en), 1, 10) >= ? LIMIT 200",
                             (tenant_id, regla["condiciones"]["etapa"], desde)).fetchall()
    finally:
        conn.close()
    ejemplos = []
    for f in filas:
        o = _oportunidad_del_evento(f["id"])
        if o:
            oc = _ocurrencia_de_oportunidad(0, regla, o, {"a": regla["condiciones"]["etapa"]})
            ejemplos.append({"objeto": oc["objeto"], "fecha": oc["fecha"], "datos": oc["datos"]})
    return {"cumplen": len(ejemplos), "nuevas": len(ejemplos), "ya_atendidas": 0, "reciente": True, "ejemplos": ejemplos[:20]}


def _simular_expediente(tenant_id: int, regla: dict, desde: str) -> dict:
    estado = regla["condiciones"].get("estado")
    campo = "abierto_en" if regla["disparador"] == "expediente.creado" else "actualizado_en"
    conn = db.get_connection()
    try:
        filas = conn.execute(f"SELECT id FROM expedientes WHERE tenant_id = ? AND papelera_en IS NULL AND substr({campo}, 1, 10) >= ? {'AND estado = ?' if estado else ''} ORDER BY {campo} DESC LIMIT 200",
                             (tenant_id, desde, *([estado] if estado else []))).fetchall()
    finally:
        conn.close()
    ejemplos = []
    for f in filas:
        exp = _expediente_del_evento(f["id"])
        if exp and cumple_evento_expediente(regla, exp, {"a": estado}):
            oc = _ocurrencia_de_expediente(0, regla, exp, {"a": estado})
            ejemplos.append({"objeto": oc["objeto"], "fecha": oc["fecha"], "datos": oc["datos"]})
    return {"cumplen": len(ejemplos), "nuevas": len(ejemplos), "ya_atendidas": 0, "reciente": True, "ejemplos": ejemplos[:20]}


def ejecutar(tenant_id: int | None = None, ahora: datetime | None = None) -> dict:
    """Una pasada: reintenta lo que falló o se quedó a medias y atiende lo nuevo. Idempotente. Con `tenant_id` solo ese despacho."""
    ahora = ahora or datetime.now(timezone.utc)
    resumen = {"reglas": 0, "nuevas": 0, "ok": 0, "errores": 0, "fallidas": 0, "reintentos": 0, "topes": 0}
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT * FROM automatizaciones_reglas WHERE activa = 1" + (" AND tenant_id = ?" if tenant_id else "") + " ORDER BY tenant_id, id", (tenant_id,) if tenant_id else ()).fetchall()
    finally:
        conn.close()
    por_despacho: dict[int, int] = {}
    for f in filas:
        regla = _regla(f)
        tid = regla["tenant_id"]
        resumen["reglas"] += 1
        hoy = hoy_del_despacho(tid, ahora)
        usados = por_despacho.get(tid, 0)
        # 1. reintentos: errores con la espera cumplida y ejecuciones que se quedaron a medias
        conn = db.get_connection()
        try:
            pendientes = [dict(e) for e in conn.execute(
                "SELECT * FROM automatizaciones_ejecuciones WHERE regla_id = ? AND (estado = 'error' AND proximo_intento <= ? OR estado = 'pendiente' AND actualizada_en <= ?)",
                (regla["id"], _ahora_texto(ahora), _ahora_texto(ahora - timedelta(minutes=ENCALLADA_MINUTOS))))]
        finally:
            conn.close()
        for e in pendientes:
            if usados >= MAX_POR_PASADA:
                resumen["topes"] += 1
                break
            oc = json.loads(e["contexto"]) if e.get("contexto") else next((o for o in _ocurrencias(tid, regla, hoy) if o["clave"] == e["clave"]), None)
            if oc is None:                    # ya no cumple (se renovó, se completó…): se cierra sin hacer nada más
                _cerrar_obsoleta(e["id"], ahora)
                continue
            usados += 1
            resumen["reintentos"] += 1
            _contar(resumen, _ejecutar_una(tid, regla, oc, e, hoy, ahora))
        # 2. ocurrencias nuevas
        for oc in _ocurrencias(tid, regla, hoy):
            if usados >= MAX_POR_PASADA:
                resumen["topes"] += 1
                break
            conn = db.get_connection()
            try:
                cur = conn.execute("INSERT INTO automatizaciones_ejecuciones (tenant_id, regla_id, regla_version, clave, objeto, estado, creada_en, actualizada_en) VALUES (?, ?, ?, ?, ?, 'pendiente', ?, ?) ON CONFLICT DO NOTHING",
                                   (tid, regla["id"], regla["version"], oc["clave"], oc["objeto"][:200], _ahora_texto(ahora), _ahora_texto(ahora)))
                conn.commit()
                nueva = cur.rowcount == 1
                ejecucion = dict(conn.execute("SELECT * FROM automatizaciones_ejecuciones WHERE regla_id = ? AND clave = ?", (regla["id"], oc["clave"])).fetchone()) if nueva else None
            finally:
                conn.close()
            if not nueva:
                continue
            usados += 1
            resumen["nuevas"] += 1
            _contar(resumen, _ejecutar_una(tid, regla, oc, ejecucion, hoy, ahora))
        por_despacho[tid] = usados
    return resumen


def _contar(resumen: dict, estado: str) -> None:
    resumen[{"ok": "ok", "error": "errores", "fallida": "fallidas"}[estado]] += 1


def _cerrar_obsoleta(ejecucion_id: int, ahora: datetime) -> None:
    conn = db.get_connection()
    try:
        conn.execute("UPDATE automatizaciones_ejecuciones SET estado = 'ok', error = 'Ya no se cumple la condición', proximo_intento = NULL, actualizada_en = ? WHERE id = ?", (_ahora_texto(ahora), ejecucion_id))
        conn.commit()
    finally:
        conn.close()


def ejecuciones(tenant_id: int, regla_id: int | None = None, estado: str | None = None, limite: int = 100) -> list[dict]:
    cond, p = ["e.tenant_id = ?"], [tenant_id]
    if regla_id:
        cond.append("e.regla_id = ?"); p.append(regla_id)
    if estado:
        cond.append("e.estado = ?"); p.append(estado)
    conn = db.get_connection()
    try:
        filas = conn.execute(f"SELECT e.*, r.nombre AS regla FROM automatizaciones_ejecuciones e JOIN automatizaciones_reglas r ON r.id = e.regla_id WHERE {' AND '.join(cond)} ORDER BY e.id DESC LIMIT ?",
                             (*p, max(1, min(limite, 500)))).fetchall()
        return [{**dict(f), "progreso": json.loads(f["progreso"])} for f in filas]
    finally:
        conn.close()


def reintentar(tenant_id: int, usuario_id: int, ejecucion_id: int) -> bool:
    """La dirección da otra oportunidad a una ejecución fallida (vuelve a la cola con los intentos a cero; no repite lo ya hecho)."""
    _exigir_direccion(usuario_id)
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE automatizaciones_ejecuciones SET estado = 'error', intentos = 0, avisada = 0, proximo_intento = ? WHERE id = ? AND tenant_id = ? AND estado = 'fallida'",
                           (_ahora_texto(datetime.now(timezone.utc)), ejecucion_id, tenant_id))
        if cur.rowcount:
            auditoria.registrar(tenant_id, usuario_id, "automatizacion.reintentar", "ejecucion", ejecucion_id, conn=conn)
        conn.commit()
        return bool(cur.rowcount)
    finally:
        conn.close()


def resumen_de_salud(tenant_id: int) -> dict:
    """Para el panel: cuántas ejecuciones fallidas o en reintento tiene el despacho."""
    conn = db.get_connection()
    try:
        return {f["estado"]: f["n"] for f in conn.execute("SELECT estado, COUNT(*) AS n FROM automatizaciones_ejecuciones WHERE tenant_id = ? GROUP BY estado", (tenant_id,))}
    finally:
        conn.close()


# --- Disparadores por evento: cola, proceso y hilo de fondo --------------------------------------------------------------
# `registrar_evento` apunta el evento al instante (una fila) y vuelve; un hilo de fondo (o la pasada diaria) lo procesa. Es una cola persistente: sobrevive a reinicios. Procesar es idempotente:
# la ejecución de cada regla para cada evento tiene su clave única, así que si dos procesos o un reinicio lo repiten, no se duplica nada.

_hilo_iniciado = False
_lock_hilo = threading.Lock()
_despertar = threading.Event()


def iniciar_worker() -> None:
    """Arranca el hilo que procesa la cola (una vez por proceso). Los tests lo anulan: viviría más que cada base temporal."""
    global _hilo_iniciado
    with _lock_hilo:
        if not _hilo_iniciado:
            threading.Thread(target=_worker, daemon=True, name="automatizaciones").start()
            _hilo_iniciado = True


def _worker() -> None:
    ultima_purga = 0.0
    while True:
        try:
            trabajado = procesar_eventos().get("eventos", 0)
            if time.monotonic() - ultima_purga > 3600:
                _purgar_eventos()
                ultima_purga = time.monotonic()
        except Exception:  # noqa: BLE001 -- un fallo inesperado nunca debe tumbar el hilo
            trabajado = 0
        if not trabajado:
            _despertar.wait(timeout=5)
        _despertar.clear()


def registrar_evento(tenant_id: int, evento: str, payload: dict) -> None:
    """Anota un evento de tarea SOLO si el despacho tiene alguna regla activa que lo escuche (así los cambios masivos no llenan la cola de nada) y si no lo ha provocado una automatización."""
    if _ACTUANDO.get():
        return
    disparadores = [d for d, e in DISPARADORES_DE_EVENTO.items() if e == evento]
    if not disparadores or not payload or not (payload.get("tarea_id") or payload.get("expediente_id") or payload.get("oportunidad_id")):
        return
    conn = db.get_connection()
    try:
        if conn.execute(f"SELECT 1 FROM automatizaciones_reglas WHERE tenant_id = ? AND activa = 1 AND disparador IN ({','.join('?' * len(disparadores))}) LIMIT 1", (tenant_id, *disparadores)).fetchone() is None:
            return
        conn.execute("INSERT INTO automatizaciones_eventos (tenant_id, evento, tarea_id, objeto_id, datos, creado_en) VALUES (?, ?, ?, ?, ?, ?)",
                     (tenant_id, evento, payload.get("tarea_id"), payload.get("expediente_id") or payload.get("oportunidad_id"), json.dumps({k: payload[k] for k in ("de", "a", "periodicidad", "recurrente_id", "por") if k in payload}), db.now_iso()))
        conn.commit()
    finally:
        conn.close()
    iniciar_worker()
    _despertar.set()


def _purgar_eventos() -> None:
    corte = (datetime.now(timezone.utc) - timedelta(days=PURGA_EVENTOS_DIAS)).strftime("%Y-%m-%dT%H:%M:%S")
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM automatizaciones_eventos WHERE procesado_en IS NOT NULL AND procesado_en < ?", (corte,))
        conn.commit()
    finally:
        conn.close()


def _tarea_del_evento(tarea_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute(
            """SELECT t.id, t.asunto, t.estado, t.prioridad, t.fecha_vencimiento, t.cliente_fiscal_id, t.referencia_externa, t.usuario_id AS dueno, COALESCE(t.asignada_a, t.usuario_id) AS responsable,
                      t.vencimiento_id, (SELECT modelo FROM vencimientos_fiscales WHERE id = t.vencimiento_id) AS modelo, (SELECT periodo FROM vencimientos_fiscales WHERE id = t.vencimiento_id) AS periodo,
                      (SELECT nombre FROM clientes_fiscales WHERE id = t.cliente_fiscal_id) AS cliente
               FROM tareas_outlook t WHERE t.id = ? AND t.papelera_en IS NULL""", (tarea_id,)).fetchone()
        return dict(f) if f else None
    finally:
        conn.close()


def cumple_evento(regla: dict, tarea: dict, datos: dict) -> bool:
    """¿La tarea del evento cumple las condiciones de la regla? Las tareas que creó una automatización no disparan nunca reglas de evento."""
    if (tarea.get("referencia_externa") or "").startswith("auto:"):
        return False
    c = regla["condiciones"]
    if regla["disparador"] == "tarea.estado" and datos.get("a") != c.get("estado"):
        return False
    if regla["disparador"] == "recurrencia.generada" and c.get("periodicidades") and datos.get("periodicidad") not in c["periodicidades"]:
        return False
    if regla["disparador"] == "tarea.creada":
        if c.get("desde_vencimiento") and not tarea.get("vencimiento_id"):
            return False
        if c.get("modelo") and (tarea.get("modelo") or "").lower() != c["modelo"].lower():
            return False
    if c.get("prioridades") and tarea["prioridad"] not in c["prioridades"]:
        return False
    if c.get("cliente_fiscal_id") and tarea["cliente_fiscal_id"] != c["cliente_fiscal_id"]:
        return False
    return True


def _ocurrencia_de_evento(evento_id: int, regla: dict, tarea: dict, datos: dict) -> dict:
    fecha = (tarea["fecha_vencimiento"] or "")[:10]
    d = {"asunto": tarea["asunto"], "prioridad": tarea["prioridad"], "cliente": tarea["cliente"] or "", "fecha": fecha}
    if regla["disparador"] == "tarea.estado":
        d.update({"estado": ESTADOS_TAREA.get(datos.get("a"), datos.get("a") or ""), "anterior": ESTADOS_TAREA.get(datos.get("de"), datos.get("de") or "")})
    if regla["disparador"] == "tarea.creada":
        d.update({"modelo": tarea.get("modelo") or "", "periodo": tarea.get("periodo") or ""})
    if regla["disparador"] == "tarea.liberada":
        d["previa"] = db._asunto_tarea(datos["por"]) if datos.get("por") else ""
    if regla["disparador"] == "recurrencia.generada":
        d["periodicidad"] = PERIODICIDADES_TEXTO.get(datos.get("periodicidad"), datos.get("periodicidad") or "")
    return {"clave": f"evt:{evento_id}", "objeto": f"tarea {tarea['id']}: {tarea['asunto'][:60]}", "responsable": tarea["responsable"], "cliente_fiscal_id": tarea["cliente_fiscal_id"],
            "tarea_id": tarea["id"], "datos": d, "fecha": fecha}


def _expediente_del_evento(expediente_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute(
            """SELECT x.id, x.titulo, x.referencia, x.tipo, x.estado, x.responsable_id, x.cliente_id, c.nombre AS cliente,
                      (SELECT id FROM clientes_fiscales WHERE cliente_id = x.cliente_id LIMIT 1) AS cliente_fiscal_id
               FROM expedientes x JOIN clientes c ON c.id = x.cliente_id WHERE x.id = ? AND x.papelera_en IS NULL""", (expediente_id,)).fetchone()
        return dict(f) if f else None
    finally:
        conn.close()


def cumple_evento_expediente(regla: dict, exp: dict, datos: dict) -> bool:
    c = regla["condiciones"]
    if c.get("tipo") and exp["tipo"] != c["tipo"]:
        return False
    if regla["disparador"] == "expediente.estado" and datos.get("a") != c.get("estado"):
        return False
    return True


def _texto(valor) -> str:
    try:
        return str(valor)
    except Exception:  # noqa: BLE001 -- un texto traducible fuera de una petición
        return ""


def _ocurrencia_de_expediente(evento_id: int, regla: dict, exp: dict, datos: dict) -> dict:
    from . import verticales
    tipo = verticales.tipo_de(exp["tipo"])
    estado_actual = tipo.estado(exp["estado"])
    d = {"expediente": exp["titulo"], "referencia": exp["referencia"] or "", "tipo": _texto(tipo.nombre), "cliente": exp["cliente"] or "", "estado": _texto(estado_actual.nombre) if estado_actual else exp["estado"]}
    if regla["disparador"] == "expediente.estado":
        nuevo, anterior = tipo.estado(datos.get("a") or ""), tipo.estado(datos.get("de") or "")
        d["estado"] = _texto(nuevo.nombre) if nuevo else (datos.get("a") or "")
        d["anterior"] = _texto(anterior.nombre) if anterior else (datos.get("de") or "")
    return {"clave": f"evt:{evento_id}", "objeto": f"expediente {exp['id']}: {exp['titulo'][:60]}", "responsable": exp["responsable_id"], "cliente_fiscal_id": exp["cliente_fiscal_id"],
            "expediente_id": exp["id"], "datos": d, "fecha": ""}


def _oportunidad_del_evento(oportunidad_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute(
            """SELECT o.id, o.titulo, o.etapa, o.importe_centimos, o.responsable_id, o.cliente_id, COALESCE(c.nombre, o.empresa, o.contacto_nombre, '') AS contacto,
                      (SELECT id FROM clientes_fiscales WHERE cliente_id = o.cliente_id LIMIT 1) AS cliente_fiscal_id
               FROM crm_oportunidades o LEFT JOIN clientes c ON c.id = o.cliente_id WHERE o.id = ? AND o.papelera_en IS NULL""", (oportunidad_id,)).fetchone()
        return dict(f) if f else None
    finally:
        conn.close()


def cumple_evento_oportunidad(regla: dict, o: dict, datos: dict) -> bool:
    return datos.get("a") == regla["condiciones"].get("etapa")


def _ocurrencia_de_oportunidad(evento_id: int, regla: dict, o: dict, datos: dict) -> dict:
    conn = db.get_connection()
    try:
        nombres = {f["clave"]: f["nombre"] for f in conn.execute("SELECT clave, nombre FROM crm_etapas WHERE tenant_id = (SELECT tenant_id FROM crm_oportunidades WHERE id = ?)", (o["id"],))}
    finally:
        conn.close()
    d = {"oportunidad": o["titulo"], "contacto": o["contacto"], "etapa": nombres.get(datos.get("a"), datos.get("a") or ""), "anterior": nombres.get(datos.get("de"), datos.get("de") or ""),
         "importe": f"{o['importe_centimos'] / 100:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."), "responsable": (db.nombre_mostrado_usuario(o["responsable_id"]) if o["responsable_id"] else "") or ""}
    return {"clave": f"evt:{evento_id}", "objeto": f"oportunidad {o['id']}: {o['titulo'][:60]}", "responsable": o["responsable_id"], "cliente_fiscal_id": o["cliente_fiscal_id"],
            "oportunidad_id": o["id"], "datos": d, "fecha": ""}


def procesar_eventos(ahora: datetime | None = None, limite: int = MAX_EVENTOS_POR_LOTE) -> dict:
    """Procesa los eventos pendientes (los más antiguos primero): para cada regla activa del despacho que escuche ese evento y cuyas condiciones cumpla la tarea, abre la ejecución (clave única)
    y hace las acciones, con los mismos reintentos y avisos que el análisis diario. Devuelve cuántos eventos y ejecuciones ha tratado."""
    ahora = ahora or datetime.now(timezone.utc)
    resumen = {"eventos": 0, "ejecuciones": 0, "ok": 0, "errores": 0, "fallidas": 0}
    conn = db.get_connection()
    try:
        eventos = [dict(f) for f in conn.execute("SELECT * FROM automatizaciones_eventos WHERE procesado_en IS NULL ORDER BY id LIMIT ?", (max(1, limite),))]
    finally:
        conn.close()
    for ev in eventos:
        de_expediente = ev["evento"] in EVENTOS_DE_EXPEDIENTE
        de_oportunidad = ev["evento"] in EVENTOS_DE_OPORTUNIDAD
        tarea = (_expediente_del_evento(ev["objeto_id"]) if de_expediente else _oportunidad_del_evento(ev["objeto_id"]) if de_oportunidad
                 else _tarea_del_evento(ev["tarea_id"]))                                       # `tarea` es el objeto del evento: una tarea, un expediente o una oportunidad
        cumple, ocurrencia = ((cumple_evento_expediente, _ocurrencia_de_expediente) if de_expediente else (cumple_evento_oportunidad, _ocurrencia_de_oportunidad) if de_oportunidad
                              else (cumple_evento, _ocurrencia_de_evento))
        datos = json.loads(ev["datos"] or "{}")
        if tarea is not None:
            conn = db.get_connection()
            try:
                reglas = [_regla(f) for f in conn.execute("SELECT * FROM automatizaciones_reglas WHERE tenant_id = ? AND activa = 1 ORDER BY id", (ev["tenant_id"],))]
            finally:
                conn.close()
            hoy = hoy_del_despacho(ev["tenant_id"], ahora)
            for regla in reglas:
                if DISPARADORES_DE_EVENTO.get(regla["disparador"]) != ev["evento"] or not cumple(regla, tarea, datos):
                    continue
                oc = ocurrencia(ev["id"], regla, tarea, datos)
                conn = db.get_connection()
                try:
                    cur = conn.execute("INSERT INTO automatizaciones_ejecuciones (tenant_id, regla_id, regla_version, clave, objeto, estado, contexto, creada_en, actualizada_en) "
                                       "VALUES (?, ?, ?, ?, ?, 'pendiente', ?, ?, ?) ON CONFLICT DO NOTHING", (ev["tenant_id"], regla["id"], regla["version"], oc["clave"], oc["objeto"][:200], json.dumps(oc, ensure_ascii=False),
                                                                                      _ahora_texto(ahora), _ahora_texto(ahora)))
                    conn.commit()
                    nueva = cur.rowcount == 1
                    ejecucion = dict(conn.execute("SELECT * FROM automatizaciones_ejecuciones WHERE regla_id = ? AND clave = ?", (regla["id"], oc["clave"])).fetchone()) if nueva else None
                finally:
                    conn.close()
                if not nueva:
                    continue                       # otro proceso (o un reinicio a medias) ya se ocupó de esta regla para este evento
                resumen["ejecuciones"] += 1
                _contar(resumen, _ejecutar_una(ev["tenant_id"], regla, oc, ejecucion, hoy, ahora))
        conn = db.get_connection()
        try:
            conn.execute("UPDATE automatizaciones_eventos SET procesado_en = ? WHERE id = ?", (_ahora_texto(ahora), ev["id"]))
            conn.commit()
        finally:
            conn.close()
        resumen["eventos"] += 1
    return resumen


def eventos_pendientes() -> int:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM automatizaciones_eventos WHERE procesado_en IS NULL").fetchone()[0]
    finally:
        conn.close()
