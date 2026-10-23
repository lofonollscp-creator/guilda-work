"""Expedientes unificados del control fiscal (especificación de control fiscal, RF-13).

No es un módulo aparte: son **tipos nuevos de los expedientes del núcleo** (`app/nucleo.py`) para el módulo de Gestoría —campaña, obligación, renovación, requerimiento e incidencia—, así que
ya traen lo que el núcleo da a cualquier expediente: cliente, responsable, miembros, documentos, plazos, horas, cronología y alcance por oficinas. Este módulo añade lo propio de RF-13:

- **Estados**: abierto, en curso, pendiente del cliente, pendiente de un tercero, en revisión, resuelto y cerrado. Esperar a un cliente o a un tercero **no pausa el plazo legal**
  (la fecha objetivo y las alertas siguen corriendo).
- **Datos de control** por expediente (`expediente_control`): oficina responsable, revisor, prioridad, fecha objetivo y el objeto al que se refiere (obligación, certificado…).
- **Lista de comprobación** (`expediente_checklist`): con puntos obligatorios, responsable y fecha. **Cerrar exige completar los obligatorios, o documentar una excepción**, que solo puede
  autorizar la dirección o un revisor fiscal; la excepción queda guardada y auditada. Reabrir un expediente cerrado también es de la dirección o del revisor.
- **Documentos versionados**: una nueva versión sustituye a la anterior a la vista (la historia se conserva), con hash, clasificación, autor y una fecha «conservar hasta» que impide
  mandar el documento a la papelera antes de tiempo.
- **Comentarios sin secretos**: se rechazan claves privadas, «contraseña: …», tokens y números de tarjeta. **Menciones** (`@nombre`) que solo avisan a quien puede ver el expediente;
  las demás se descartan y se le dice a quien comenta.
- Se abren desde la obligación o el certificado (un solo expediente abierto por objeto) y todo cambio importante queda en la auditoría."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from datetime import date

from flask_babel import lazy_gettext as _l

from . import acceso, auditoria, db, nucleo, traspasos, verticales
from .verticales import Estado, TipoExpediente

ID = "gestoria"
ESTADOS = (Estado("abierto", _l("Abierto")), Estado("en_curso", _l("En curso")), Estado("pendiente_cliente", _l("Pendiente del cliente")),
           Estado("pendiente_tercero", _l("Pendiente de un tercero")), Estado("en_revision", _l("En revisión")), Estado("resuelto", _l("Resuelto")), Estado("cerrado", _l("Cerrado"), True))
PRIORIDADES = ("baja", "normal", "alta", "urgente")

# Puntos de partida de la lista de cada tipo (texto, obligatorio). Se puede cambiar libremente en cada expediente.
LISTAS: dict[str, tuple[tuple[str, bool], ...]] = {
    "control_campana": (("Definir alcance y clientes afectados", True), ("Comunicar al equipo y a los clientes", True), ("Seguimiento del avance", False), ("Revisión final y cierre de la campaña", True)),
    "control_obligacion": (("Documentación recibida del cliente", True), ("Cálculo preparado", True), ("Revisado por segunda persona", True), ("Presentada y justificante archivado", True)),
    "control_renovacion": (("Pedir cita o iniciar la solicitud", True), ("Nuevo certificado obtenido", True), ("Probado en cada servicio donde se usa", True), ("Anterior retirado de los servicios", False)),
    "control_requerimiento": (("Registrar la notificación y su plazo", True), ("Reunir la documentación pedida", True), ("Respuesta revisada", True), ("Respuesta presentada y justificante archivado", True)),
    "control_incidencia": (("Describir qué ha pasado y a quién afecta", True), ("Contener el problema", True), ("Causa identificada", False), ("Cliente informado, si procede", False)),
}


# --- Controles de cierre y de comentarios -----------------------------------------------------------------------------------------------------
def pendientes_obligatorios(expediente_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT id, texto FROM expediente_checklist WHERE expediente_id = ? AND obligatorio = 1 AND hecho_en IS NULL ORDER BY orden, id", (expediente_id,))]
    finally:
        conn.close()


def _al_cambiar_estado(tenant_id: int, usuario_id: int, exp, nuevo: str, excepcion: str | None) -> None:
    if acceso.es_solo_auditor(tenant_id, usuario_id):
        raise ValueError("Con tu rol solo puedes consultar los expedientes.")
    if exp["estado"] == "cerrado" and not acceso.puede_autorizar(tenant_id, usuario_id):
        raise ValueError("Solo la dirección o un revisor fiscal puede reabrir un expediente cerrado.")
    motivo = (excepcion or "").strip()
    if nuevo == "cerrado":
        faltan = pendientes_obligatorios(exp["id"])
        if faltan:
            if not motivo:
                lista = "; ".join(f["texto"] for f in faltan[:3]) + ("…" if len(faltan) > 3 else "")
                raise ValueError(f"Para cerrar faltan {len(faltan)} puntos obligatorios ({lista}). Complétalos o documenta una excepción autorizada.")
            if not acceso.puede_autorizar(tenant_id, usuario_id):
                raise ValueError("Solo la dirección o un revisor fiscal puede autorizar una excepción para cerrar.")
            conn = db.get_connection()
            try:
                conn.execute("UPDATE expediente_control SET excepcion_motivo = ?, excepcion_por = ?, excepcion_en = ? WHERE expediente_id = ?", (motivo[:500], usuario_id, db.now_iso(), exp["id"]))
                auditoria.registrar(tenant_id, usuario_id, "expediente.excepcion", "expediente", exp["id"], {"motivo": motivo[:500], "puntos_pendientes": [f["id"] for f in faltan]}, conn=conn)
                nucleo._evento(conn, exp["id"], "excepcion", f"Cierre con excepción autorizada: {motivo[:300]}", usuario_id)
                conn.commit()
            finally:
                conn.close()
    auditoria.registrar(tenant_id, usuario_id, "expediente.estado", "expediente", exp["id"], {"de": exp["estado"], "a": nuevo})


_SECRETOS = (
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.I), "una clave privada"),
    (re.compile(r"\b(contrase[ñn]a|password|passwd|pwd|pin)\b\s*(?:es|:|=)\s*\S{3,}", re.I), "una contraseña"),
    (re.compile(r"\b(api[ _-]?key|token|secret[oa]?|clave\s+secreta|clave\s+privada)\b\s*[:=]\s*\S{6,}", re.I), "un token o una clave"),
    (re.compile(r"\b[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9])"), "una cadena que parece un token o una clave"),
)


def _luhn(digitos: str) -> bool:
    suma, alterna = 0, False
    for d in reversed(digitos):
        n = int(d)
        if alterna:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        suma += n
        alterna = not alterna
    return suma % 10 == 0


def contiene_secreto(texto: str) -> str | None:
    """Qué tipo de secreto parece haber en el texto (para decírselo a quien escribe), o None. Es una red de seguridad, no una garantía."""
    for patron, nombre in _SECRETOS:
        if patron.search(texto):
            return nombre
    for m in re.finditer(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)", texto):
        digitos = re.sub(r"\D", "", m.group())
        if 13 <= len(digitos) <= 19 and _luhn(digitos) and not digitos.startswith(("0", "ES")):
            return "un número de tarjeta"
    return None


def _plano(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t.lower()) if not unicodedata.combining(c))


def _resolver_menciones(tenant_id: int, texto: str) -> tuple[dict[int, str], list[str]]:
    """(personas del despacho mencionadas, menciones que no corresponden a nadie). `@marta` casa con el nombre de pila o con la parte del correo antes de la @, si es única."""
    quienes = [(u, _plano(db.nombre_mostrado_usuario(u) or ""), _plano((db.obtener_usuario(u)["email"] or "").split("@")[0])) for u in db.usuarios_de_tenant(tenant_id)]
    hallados: dict[int, str] = {}
    sin_resolver: list[str] = []
    for m in dict.fromkeys(re.findall(r"@([\w.\-áéíóúñüÁÉÍÓÚÑÜ]+)", texto)):
        clave = _plano(m).rstrip(".")
        cand = [u for u, nombre, local in quienes if clave in (local, nombre, nombre.split(" ")[0] if nombre else "")]
        if len(cand) == 1:
            hallados[cand[0]] = m
        else:
            sin_resolver.append(m)
    return hallados, sin_resolver


def _al_anotar(tenant_id: int, usuario_id: int, exp, texto: str):
    if acceso.es_solo_auditor(tenant_id, usuario_id):
        raise ValueError("Con tu rol solo puedes consultar los expedientes.")
    secreto = contiene_secreto(texto)
    if secreto:
        raise ValueError(f"El comentario parece contener {secreto}. Los comentarios no pueden llevar secretos: guárdalos en el gestor de contraseñas del despacho y escribe solo dónde están.")
    hallados, sin_resolver = _resolver_menciones(tenant_id, texto)

    def despues() -> dict:
        avisadas, sin_acceso = [], []
        supervisor = False
        for uid, mencion in hallados.items():
            if uid == usuario_id:
                continue
            ver = nucleo.obtener_expediente(tenant_id, exp["id"], uid, bool(db.es_supervisor_tenant(uid)))
            if ver is None:
                sin_acceso.append(mencion)
                continue
            try:
                from . import notificaciones
                notificaciones.crear_y_enviar(uid, "mencion", "Te mencionan en un expediente", f"{exp['titulo']}: {texto[:160]}", url=f"/expedientes/{exp['id']}", datos={"tipo": "mencion", "expediente_id": exp["id"]})
                avisadas.append(mencion)
            except Exception:  # noqa: BLE001
                pass
        return {"avisadas": avisadas, "sin_acceso": sin_acceso, "no_encontradas": sin_resolver, "supervisor": supervisor}
    return despues


TIPOS = tuple(TipoExpediente(i, n, ESTADOS, al_cambiar_estado=_al_cambiar_estado, al_anotar=_al_anotar) for i, n in (
    ("control_campana", _l("Campaña")), ("control_obligacion", _l("Obligación")), ("control_renovacion", _l("Renovación de certificado")),
    ("control_requerimiento", _l("Requerimiento")), ("control_incidencia", _l("Incidencia"))))
IDS_TIPOS = tuple(t.id for t in TIPOS)


# --- Esquema -------------------------------------------------------------------------------------------------------------------------------
ESQUEMA = """
CREATE TABLE IF NOT EXISTS expediente_control (
    expediente_id INTEGER PRIMARY KEY REFERENCES expedientes(id) ON DELETE CASCADE,
    oficina_id INTEGER REFERENCES oficinas(id),
    revisor_id INTEGER REFERENCES usuarios(id),
    prioridad TEXT NOT NULL DEFAULT 'normal' CHECK (prioridad IN ('baja', 'normal', 'alta', 'urgente')),
    fecha_objetivo TEXT,
    vinculo_tipo TEXT,
    vinculo_id INTEGER,
    excepcion_motivo TEXT,
    excepcion_por INTEGER REFERENCES usuarios(id),
    excepcion_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_expediente_control_vinculo ON expediente_control(vinculo_tipo, vinculo_id);
CREATE TABLE IF NOT EXISTS expediente_checklist (
    id INTEGER PRIMARY KEY,
    expediente_id INTEGER NOT NULL REFERENCES expedientes(id) ON DELETE CASCADE,
    texto TEXT NOT NULL,
    obligatorio INTEGER NOT NULL DEFAULT 0,
    asignado_id INTEGER REFERENCES usuarios(id),
    fecha_limite TEXT,
    orden INTEGER NOT NULL DEFAULT 0,
    hecho_en TEXT,
    hecho_por INTEGER REFERENCES usuarios(id),
    nota TEXT,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_expediente_checklist ON expediente_checklist(expediente_id, orden);
"""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    db._asegurar_columna(conn, "documentos", "version", "INTEGER NOT NULL DEFAULT 1")
    db._asegurar_columna(conn, "documentos", "reemplaza_a", "INTEGER REFERENCES documentos(id)")
    db._asegurar_columna(conn, "documentos", "conservar_hasta", "TEXT")


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    sub = "SELECT id FROM expedientes WHERE tenant_id = ?"
    conn.execute(f"DELETE FROM expediente_checklist WHERE expediente_id IN ({sub})", (tenant_id,))
    conn.execute(f"DELETE FROM expediente_control WHERE expediente_id IN ({sub})", (tenant_id,))


# --- Acceso ---------------------------------------------------------------------------------------------------------------------------------
def _supervisor(usuario_id: int) -> bool:
    return bool(db.es_supervisor_tenant(usuario_id))


def _exp(tenant_id: int, usuario_id: int, expediente_id: int, *, escribir: bool = False):
    x = nucleo.obtener_expediente(tenant_id, expediente_id, usuario_id, _supervisor(usuario_id))
    if x is None or x["tipo"] not in IDS_TIPOS:
        raise ValueError("Expediente no encontrado.")
    if escribir and acceso.es_solo_auditor(tenant_id, usuario_id):
        raise ValueError("Con tu rol solo puedes consultar los expedientes.")
    return x


def datos_de(expediente_id: int) -> dict:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM expediente_control WHERE expediente_id = ?", (expediente_id,)).fetchone()
    finally:
        conn.close()
    return dict(f) if f else {"expediente_id": expediente_id, "oficina_id": None, "revisor_id": None, "prioridad": "normal", "fecha_objetivo": None, "vinculo_tipo": None, "vinculo_id": None}


# --- Alta ------------------------------------------------------------------------------------------------------------------------------------
def crear(tenant_id: int, usuario_id: int, cliente_id: int, tipo: str, titulo: str, *, responsable_id: int | None = None, revisor_id: int | None = None, oficina_id: int | None = None,
          prioridad: str = "normal", fecha_objetivo: str | None = None, descripcion: str | None = None, vinculo: tuple[str, int] | None = None, lista: bool = True) -> int:
    if tipo not in IDS_TIPOS:
        raise ValueError("Ese tipo de expediente no existe.")
    if prioridad not in PRIORIDADES:
        raise ValueError("Prioridad no válida: baja, normal, alta o urgente.")
    if fecha_objetivo:
        try:
            fecha_objetivo = date.fromisoformat(str(fecha_objetivo)[:10]).isoformat()
        except ValueError:
            raise ValueError("La fecha objetivo debe tener el formato AAAA-MM-DD.") from None
    if acceso.es_solo_auditor(tenant_id, usuario_id):
        raise ValueError("Con tu rol solo puedes consultar los expedientes.")
    conn = db.get_connection()
    try:
        for uid, campo in ((revisor_id, "El revisor"), (responsable_id, "El responsable")):
            if uid is not None and conn.execute("SELECT 1 FROM usuarios WHERE id = ? AND tenant_id = ?", (uid, tenant_id)).fetchone() is None:
                raise ValueError(f"{campo} no pertenece al despacho.")
        if oficina_id is not None and conn.execute("SELECT 1 FROM oficinas WHERE id = ? AND tenant_id = ? AND activa = 1", (oficina_id, tenant_id)).fetchone() is None:
            raise ValueError("No existe esa oficina.")
    finally:
        conn.close()
    nuevo = nucleo.crear_expediente(tenant_id, usuario_id, cliente_id, titulo, tipo=tipo, descripcion=descripcion, responsable_id=responsable_id)
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO expediente_control (expediente_id, oficina_id, revisor_id, prioridad, fecha_objetivo, vinculo_tipo, vinculo_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (nuevo, oficina_id, revisor_id, prioridad, fecha_objetivo, vinculo[0] if vinculo else None, vinculo[1] if vinculo else None))
        if lista:
            for i, (texto, obligatorio) in enumerate(LISTAS[tipo]):
                conn.execute("INSERT INTO expediente_checklist (expediente_id, texto, obligatorio, orden, creado_en) VALUES (?, ?, ?, ?, ?)", (nuevo, texto, int(obligatorio), i, db.now_iso()))
        auditoria.registrar(tenant_id, usuario_id, "expediente.crear", "expediente", nuevo, {"tipo": tipo, "vinculo": list(vinculo) if vinculo else None}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return nuevo


def _abierto_para(conn, tenant_id: int, vinculo: tuple[str, int]):
    return conn.execute("SELECT x.id FROM expediente_control c JOIN expedientes x ON x.id = c.expediente_id WHERE x.tenant_id = ? AND c.vinculo_tipo = ? AND c.vinculo_id = ? "
                        "AND x.estado != 'cerrado' AND x.papelera_en IS NULL ORDER BY x.id DESC LIMIT 1", (tenant_id, *vinculo)).fetchone()


def abrir_desde_obligacion(tenant_id: int, usuario_id: int, vencimiento_id: int) -> dict:
    """Abre (o devuelve el que ya hay abierto) el expediente de una obligación: un solo expediente abierto por objeto."""
    v = db.obtener_vencimiento_fiscal(tenant_id, vencimiento_id)
    if v is None or not acceso.puede_modificar_cliente(tenant_id, usuario_id, v["cliente_fiscal_id"]):
        raise ValueError("No existe esa obligación.")
    cli = db.obtener_cliente_fiscal(tenant_id, v["cliente_fiscal_id"])
    nucleo_id = nucleo.vincular_cliente_fiscal(tenant_id, v["cliente_fiscal_id"])
    conn = db.get_connection()
    try:
        previo = _abierto_para(conn, tenant_id, ("obligacion", vencimiento_id))
        extra = conn.execute("SELECT responsable_id, oficina_id FROM clientes_fiscales WHERE id = ?", (v["cliente_fiscal_id"],)).fetchone()
    finally:
        conn.close()
    if previo:
        return {"id": previo["id"], "nuevo": False}
    nuevo = crear(tenant_id, usuario_id, nucleo_id, "control_obligacion", f"{v['modelo']} {v['periodo']} · {cli['nombre']}", responsable_id=extra["responsable_id"] or usuario_id,
                  oficina_id=extra["oficina_id"], fecha_objetivo=v["fecha_limite"][:10], vinculo=("obligacion", vencimiento_id))
    return {"id": nuevo, "nuevo": True}


def abrir_desde_certificado(tenant_id: int, usuario_id: int, certificado_id: int) -> dict:
    from . import certificados
    if not certificados.puede_gestionar(usuario_id, tenant_id):
        raise ValueError("Solo los custodios de certificados y los supervisores del despacho pueden hacer esto.")
    c = certificados.obtener(tenant_id, certificado_id)
    if c is None:
        raise ValueError("No existe ese certificado.")
    if not c.get("cliente_titular_id"):
        raise ValueError("Asocia primero el certificado a un cliente (en «Datos») para abrir su expediente.")
    nucleo_id = nucleo.vincular_cliente_fiscal(tenant_id, c["cliente_titular_id"])
    conn = db.get_connection()
    try:
        previo = _abierto_para(conn, tenant_id, ("certificado", certificado_id))
        extra = conn.execute("SELECT responsable_id, oficina_id FROM clientes_fiscales WHERE id = ?", (c["cliente_titular_id"],)).fetchone()
    finally:
        conn.close()
    if previo:
        return {"id": previo["id"], "nuevo": False}
    nombre = c["nombre_comun"] or c["sujeto"] or f"#{certificado_id}"
    nuevo = crear(tenant_id, usuario_id, nucleo_id, "control_renovacion", f"Renovación: {nombre}"[:200], responsable_id=c["custodio_id"] or extra["responsable_id"] or usuario_id, oficina_id=extra["oficina_id"],
                  fecha_objetivo=(c["not_after"] or "")[:10] or None, prioridad="alta", vinculo=("certificado", certificado_id))
    return {"id": nuevo, "nuevo": True}


def editar_control(tenant_id: int, usuario_id: int, expediente_id: int, **campos) -> dict:
    x = _exp(tenant_id, usuario_id, expediente_id, escribir=True)
    sets, vals, cambios = [], [], {}
    if "prioridad" in campos:
        if campos["prioridad"] not in PRIORIDADES:
            raise ValueError("Prioridad no válida: baja, normal, alta o urgente.")
        sets.append("prioridad = ?"); vals.append(campos["prioridad"]); cambios["prioridad"] = campos["prioridad"]
    if "fecha_objetivo" in campos:
        f = campos["fecha_objetivo"]
        if f:
            try:
                f = date.fromisoformat(str(f)[:10]).isoformat()
            except ValueError:
                raise ValueError("La fecha objetivo debe tener el formato AAAA-MM-DD.") from None
        sets.append("fecha_objetivo = ?"); vals.append(f or None); cambios["fecha_objetivo"] = f or None
    conn = db.get_connection()
    try:
        if "revisor_id" in campos:
            r = campos["revisor_id"] or None
            if r is not None and conn.execute("SELECT 1 FROM usuarios WHERE id = ? AND tenant_id = ?", (r, tenant_id)).fetchone() is None:
                raise ValueError("El revisor no pertenece al despacho.")
            if r is not None and r == x["responsable_id"]:
                raise ValueError("El revisor y el responsable deben ser personas distintas.")
            sets.append("revisor_id = ?"); vals.append(r); cambios["revisor_id"] = r
        if "oficina_id" in campos:
            o = campos["oficina_id"] or None
            if o is not None and conn.execute("SELECT 1 FROM oficinas WHERE id = ? AND tenant_id = ? AND activa = 1", (o, tenant_id)).fetchone() is None:
                raise ValueError("No existe esa oficina.")
            sets.append("oficina_id = ?"); vals.append(o); cambios["oficina_id"] = o
        if not sets:
            return datos_de(expediente_id)
        conn.execute("INSERT INTO expediente_control (expediente_id) VALUES (?) ON CONFLICT DO NOTHING", (expediente_id,))
        conn.execute(f"UPDATE expediente_control SET {', '.join(sets)} WHERE expediente_id = ?", [*vals, expediente_id])
        nucleo._evento(conn, expediente_id, "control", "Datos de control actualizados.", usuario_id)
        auditoria.registrar(tenant_id, usuario_id, "expediente.control", "expediente", expediente_id, cambios, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return datos_de(expediente_id)


# --- Lista de comprobación ---------------------------------------------------------------------------------------------------------------
def listar_lista(expediente_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute("SELECT * FROM expediente_checklist WHERE expediente_id = ? ORDER BY orden, id", (expediente_id,))]
    finally:
        conn.close()
    for f in filas:
        f["asignado"] = traspasos._nombre(f["asignado_id"])
        f["hecho_por_nombre"] = traspasos._nombre(f["hecho_por"])
    return filas


def anadir_punto(tenant_id: int, usuario_id: int, expediente_id: int, texto: str, *, obligatorio: bool = False, asignado_id: int | None = None, fecha_limite: str | None = None) -> int:
    _exp(tenant_id, usuario_id, expediente_id, escribir=True)
    texto = (texto or "").strip()[:300]
    if not texto:
        raise ValueError("Escribe el punto de la lista.")
    if contiene_secreto(texto):
        raise ValueError("El punto parece contener un secreto: no se guardan contraseñas ni claves.")
    if fecha_limite:
        try:
            fecha_limite = date.fromisoformat(str(fecha_limite)[:10]).isoformat()
        except ValueError:
            raise ValueError("La fecha debe tener el formato AAAA-MM-DD.") from None
    conn = db.get_connection()
    try:
        if asignado_id is not None and conn.execute("SELECT 1 FROM usuarios WHERE id = ? AND tenant_id = ?", (asignado_id, tenant_id)).fetchone() is None:
            raise ValueError("Esa persona no pertenece al despacho.")
        orden = (conn.execute("SELECT COALESCE(MAX(orden), -1) + 1 FROM expediente_checklist WHERE expediente_id = ?", (expediente_id,)).fetchone()[0])
        cur = conn.execute("INSERT INTO expediente_checklist (expediente_id, texto, obligatorio, asignado_id, fecha_limite, orden, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (expediente_id, texto, int(bool(obligatorio)), asignado_id, fecha_limite or None, orden, db.now_iso()))
        nucleo._evento(conn, expediente_id, "lista", f"Punto añadido: {texto[:120]}", usuario_id)
        conn.commit()
    finally:
        conn.close()
    if asignado_id and asignado_id != usuario_id:
        try:
            from . import notificaciones
            notificaciones.crear_y_enviar(asignado_id, "expediente", "Te asignan un punto de un expediente", texto[:200], url=f"/expedientes/{expediente_id}", datos={"tipo": "expediente", "expediente_id": expediente_id})
        except Exception:  # noqa: BLE001
            pass
    return cur.lastrowid


def _punto(conn, tenant_id: int, punto_id: int):
    f = conn.execute("SELECT c.* FROM expediente_checklist c JOIN expedientes x ON x.id = c.expediente_id WHERE c.id = ? AND x.tenant_id = ?", (punto_id, tenant_id)).fetchone()
    if f is None:
        raise ValueError("No existe ese punto.")
    return f


def marcar_punto(tenant_id: int, usuario_id: int, punto_id: int, hecho: bool = True, nota: str | None = None) -> None:
    conn = db.get_connection()
    try:
        p = _punto(conn, tenant_id, punto_id)
        _exp(tenant_id, usuario_id, p["expediente_id"], escribir=True)
        nota = (nota or "").strip()[:300] or None
        if nota and contiene_secreto(nota):
            raise ValueError("La nota parece contener un secreto: no se guardan contraseñas ni claves.")
        if hecho:
            conn.execute("UPDATE expediente_checklist SET hecho_en = ?, hecho_por = ?, nota = COALESCE(?, nota) WHERE id = ?", (db.now_iso(), usuario_id, nota, punto_id))
        else:
            conn.execute("UPDATE expediente_checklist SET hecho_en = NULL, hecho_por = NULL WHERE id = ?", (punto_id,))
        nucleo._evento(conn, p["expediente_id"], "lista", f"{'Hecho' if hecho else 'Reabierto'}: {p['texto'][:120]}", usuario_id)
        conn.commit()
    finally:
        conn.close()


def eliminar_punto(tenant_id: int, usuario_id: int, punto_id: int) -> None:
    conn = db.get_connection()
    try:
        p = _punto(conn, tenant_id, punto_id)
        _exp(tenant_id, usuario_id, p["expediente_id"], escribir=True)
        if p["obligatorio"] and not acceso.puede_autorizar(tenant_id, usuario_id):
            raise ValueError("Solo la dirección o un revisor fiscal puede quitar un punto obligatorio.")
        conn.execute("DELETE FROM expediente_checklist WHERE id = ?", (punto_id,))
        auditoria.registrar(tenant_id, usuario_id, "expediente.lista_quitar", "expediente", p["expediente_id"], {"texto": p["texto"], "obligatorio": bool(p["obligatorio"])}, conn=conn)
        nucleo._evento(conn, p["expediente_id"], "lista", f"Punto quitado: {p['texto'][:120]}", usuario_id)
        conn.commit()
    finally:
        conn.close()


# --- Documentos versionados --------------------------------------------------------------------------------------------------------------
def documentos(tenant_id: int, usuario_id: int, expediente_id: int) -> list[dict]:
    """Un elemento por documento (su última versión) con `versiones` anteriores; hash, clasificación, autor, visibilidad y conservación a la vista."""
    _exp(tenant_id, usuario_id, expediente_id)
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute(
            "SELECT id, nombre_archivo, tamano_bytes, categoria, hash_sha256, subido_por, creado_en, version, reemplaza_a, conservar_hasta, compartido_cliente FROM documentos "
            "WHERE expediente_id = ? AND tenant_id = ? AND papelera_en IS NULL ORDER BY id", (expediente_id, tenant_id))]
    finally:
        conn.close()
    por_id = {f["id"]: f for f in filas}
    reemplazados = {f["reemplaza_a"] for f in filas if f["reemplaza_a"]}
    res = []
    for f in filas:
        if f["id"] in reemplazados:
            continue
        previas, p = [], f["reemplaza_a"]
        while p and p in por_id:
            previas.append(por_id[p]); p = por_id[p]["reemplaza_a"]
        f["autor"] = traspasos._nombre(f["subido_por"])
        f["versiones"] = previas
        res.append(f)
    return res


def subir_version(tenant_id: int, usuario_id: int, documento_id: int, nombre: str, tipo_mime: str | None, contenido: bytes) -> int:
    from . import almacen_documentos
    conn = db.get_connection()
    try:
        d = conn.execute("SELECT id, expediente_id, categoria, version, conservar_hasta, compartido_cliente FROM documentos WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL AND expediente_id IS NOT NULL", (documento_id, tenant_id)).fetchone()
        reemplazado = d is not None and conn.execute("SELECT 1 FROM documentos WHERE reemplaza_a = ? AND papelera_en IS NULL", (documento_id,)).fetchone() is not None
    finally:
        conn.close()
    if d is None:
        raise ValueError("No existe ese documento.")
    _exp(tenant_id, usuario_id, d["expediente_id"], escribir=True)
    if reemplazado:
        raise ValueError("Ya hay una versión más reciente de este documento.")
    r, nuevo = almacen_documentos.guardar(usuario_id, nombre, tipo_mime, contenido, expediente_id=d["expediente_id"], categoria=d["categoria"])
    if r == "duplicado":
        raise ValueError("Ese archivo es idéntico a uno que ya está en el expediente.")
    if r != "ok":
        raise ValueError({"vacio": "El archivo está vacío.", "grande": "El archivo es demasiado grande.", "limite": "Hay demasiados documentos en el expediente.",
                          "clave_privada": "Ese archivo contiene una clave privada o es un contenedor .p12/.pfx: no se guarda."}.get(r, "No se pudo guardar."))
    conn = db.get_connection()
    try:
        conn.execute("UPDATE documentos SET version = ?, reemplaza_a = ?, conservar_hasta = ?, compartido_cliente = ? WHERE id = ?", (d["version"] + 1, documento_id, d["conservar_hasta"], d["compartido_cliente"], nuevo))
        auditoria.registrar(tenant_id, usuario_id, "documento.version", "expediente", d["expediente_id"], {"documento": nuevo, "reemplaza_a": documento_id, "version": d["version"] + 1}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return nuevo


def fijar_conservacion(tenant_id: int, usuario_id: int, documento_id: int, hasta: str | None) -> None:
    conn = db.get_connection()
    try:
        d = conn.execute("SELECT expediente_id FROM documentos WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL AND expediente_id IS NOT NULL", (documento_id, tenant_id)).fetchone()
        if d is None:
            raise ValueError("No existe ese documento.")
        _exp(tenant_id, usuario_id, d["expediente_id"], escribir=True)
        if hasta:
            try:
                hasta = date.fromisoformat(str(hasta)[:10]).isoformat()
            except ValueError:
                raise ValueError("La fecha debe tener el formato AAAA-MM-DD.") from None
        conn.execute("UPDATE documentos SET conservar_hasta = ? WHERE id = ?", (hasta or None, documento_id))
        auditoria.registrar(tenant_id, usuario_id, "documento.conservacion", "expediente", d["expediente_id"], {"documento": documento_id, "hasta": hasta or None}, conn=conn)
        conn.commit()
    finally:
        conn.close()


# --- Consulta ---------------------------------------------------------------------------------------------------------------------------------
def listar(tenant_id: int, usuario_id: int, *, estado: str | None = None, tipo: str | None = None, solo_abiertos: bool = True, limite: int = 200) -> list[dict]:
    filas, _ = nucleo.listar_expedientes(tenant_id, usuario_id, _supervisor(usuario_id), estado=estado, tipo=tipo, solo_abiertos=solo_abiertos, limite=500)
    res = []
    for x in filas:
        if x["tipo"] not in IDS_TIPOS:
            continue
        c = datos_de(x["id"])
        conn = db.get_connection()
        try:
            tot, hechos = conn.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN hecho_en IS NOT NULL THEN 1 ELSE 0 END), 0) FROM expediente_checklist WHERE expediente_id = ?", (x["id"],)).fetchone()
            obligatorios = conn.execute("SELECT COUNT(*) FROM expediente_checklist WHERE expediente_id = ? AND obligatorio = 1 AND hecho_en IS NULL", (x["id"],)).fetchone()[0]
        finally:
            conn.close()
        res.append({"id": x["id"], "tipo": x["tipo"], "titulo": x["titulo"], "estado": x["estado"], "cliente": x["cliente_nombre"], "responsable_id": x["responsable_id"], "prioridad": c["prioridad"],
                    "fecha_objetivo": c["fecha_objetivo"], "revisor_id": c["revisor_id"], "oficina_id": c["oficina_id"], "vinculo_tipo": c["vinculo_tipo"], "vinculo_id": c["vinculo_id"],
                    "puntos": tot, "puntos_hechos": hechos, "obligatorios_pendientes": obligatorios, "abierto_en": x["abierto_en"], "cerrado_en": x["cerrado_en"]})
    res.sort(key=lambda r: (r["estado"] == "cerrado", {"urgente": 0, "alta": 1, "normal": 2, "baja": 3}[r["prioridad"]], r["fecha_objetivo"] or "9999"))
    return res[:limite]


def detalle(tenant_id: int, usuario_id: int, expediente_id: int) -> dict:
    x = _exp(tenant_id, usuario_id, expediente_id)
    c = datos_de(expediente_id)
    return {"id": x["id"], "tipo": x["tipo"], "titulo": x["titulo"], "descripcion": x["descripcion"], "estado": x["estado"], "cliente": x["cliente_nombre"], "responsable_id": x["responsable_id"],
            "responsable": x["responsable_nombre"], "abierto_en": x["abierto_en"], "cerrado_en": x["cerrado_en"], "control": c, "lista": listar_lista(expediente_id),
            "documentos": documentos(tenant_id, usuario_id, expediente_id), "faltan_obligatorios": len(pendientes_obligatorios(expediente_id))}


def vencidos_abiertos(tenant_id: int, hoy: date | None = None) -> list[dict]:
    """Expedientes de control abiertos cuya fecha objetivo ya pasó (para el motor de avisos). Sin filtrar por persona: lo usa el sistema."""
    hoy = (hoy or date.today()).isoformat()
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            "SELECT x.id, x.titulo, x.responsable_id, x.cliente_id, c.fecha_objetivo, c.prioridad, c.oficina_id, (SELECT cf.id FROM clientes_fiscales cf WHERE cf.cliente_id = x.cliente_id AND cf.tenant_id = x.tenant_id LIMIT 1) AS cliente_fiscal_id "
            "FROM expedientes x JOIN expediente_control c ON c.expediente_id = x.id WHERE x.tenant_id = ? AND x.papelera_en IS NULL AND x.estado != 'cerrado' AND x.estado != 'resuelto' "
            "AND c.fecha_objetivo IS NOT NULL AND c.fecha_objetivo < ?", (tenant_id, hoy))]
    finally:
        conn.close()


def sin_evidencia(tenant_id: int) -> dict:
    """Indicador de la especificación «expedientes sin evidencia»: resueltos o cerrados que no tienen ningún documento ni punto hecho."""
    conn = db.get_connection()
    try:
        base = "FROM expedientes x JOIN expediente_control c ON c.expediente_id = x.id WHERE x.tenant_id = ? AND x.papelera_en IS NULL AND x.estado IN ('resuelto', 'cerrado')"
        n = conn.execute(f"SELECT COUNT(1) {base}", (tenant_id,)).fetchone()[0]
        sin = conn.execute(f"SELECT COUNT(1) {base} AND NOT EXISTS (SELECT 1 FROM documentos d WHERE d.expediente_id = x.id AND d.papelera_en IS NULL)", (tenant_id,)).fetchone()[0]
        return {"n": n, "sin": sin}
    finally:
        conn.close()


# --- Panel de la ficha y registro ----------------------------------------------------------------------------------------------------------
def contexto_panel(tenant_id: int, usuario_id: int, supervisor: bool, exp) -> dict:
    c = datos_de(exp["id"])
    vinc = None
    if c["vinculo_tipo"] == "obligacion":
        v = db.obtener_vencimiento_fiscal(tenant_id, c["vinculo_id"])
        vinc = {"texto": f"{v['modelo']} {v['periodo']}", "url": f"/fiscal/vencimientos/{v['id']}/editar", "etiqueta": "Obligación"} if v else None
    elif c["vinculo_tipo"] == "certificado":
        vinc = {"texto": f"Certificado #{c['vinculo_id']}", "url": f"/certificados/{c['vinculo_id']}", "etiqueta": "Certificado"}
    equipo = [{"id": u, "nombre": db.nombre_mostrado_usuario(u) or db.obtener_usuario(u)["email"]} for u in db.usuarios_de_tenant(tenant_id)]
    return {"control": c, "lista": listar_lista(exp["id"]), "docs": documentos(tenant_id, usuario_id, exp["id"]), "vinculo": vinc, "equipo": equipo, "prioridades": PRIORIDADES,
            "oficinas": acceso.listar_oficinas(tenant_id), "puede_autorizar": acceso.puede_autorizar(tenant_id, usuario_id), "solo_lectura": acceso.es_solo_auditor(tenant_id, usuario_id),
            "faltan": len(pendientes_obligatorios(exp["id"])), "hoy": date.today().isoformat(),
            "revisor": traspasos._nombre(c["revisor_id"])}


def _registrar() -> None:
    base = verticales.VERTICALES[ID]
    verticales.registrar(replace(base, tipos_expediente=TIPOS, esquema=crear_esquema, borrar_datos=borrar_datos_de_tenant, panel_expediente="control/_panel_expediente.html",
                                 tipos_con_panel=IDS_TIPOS, contexto_expediente=contexto_panel))


_registrar()
