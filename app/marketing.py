"""Marketing del Comercial: consentimientos, grupos de clientes, plantillas de correo y envíos con constancia.

Reglas, explícitas (las de la protección de datos y la LSSI mandan sobre la comodidad):
- **Solo se escribe a quien lo ha consentido.** El registro de consentimientos (`marketing_contactos`, uno por despacho y correo) guarda cuándo, por qué vía y con qué prueba: un documento firmado
  con Documenso (`documentos_firma`), o una constancia escrita por la persona que lo recoge (formulario, verbal, importación). Sin prueba no se registra. Una baja prevalece siempre.
- **Filtros que se aplican siempre**: con consentimiento vigente, con correo válido, nunca de baja ni con correo rebotado, un envío por correo aunque lo compartan varios clientes, solo el
  correo de la ficha del cliente (nunca contactos o familiares) y sin clientes en la papelera.
- **Cada correo lleva su enlace de baja y los datos del despacho**; no se puede quitar. La baja es de un clic, sin iniciar sesión (`/baja/<token>`).
- **Programar un envío es una acción externa**: solo la dirección del despacho, tras ver el recuento y escribirlo. Se comprueba el consentimiento de nuevo en el momento de enviar cada correo.
- **La IA solo ve el texto de la plantilla y lo que escribe la persona**, nunca datos de clientes; lo que propone es un borrador que se revisa.
- El envío usa un canal SALIENTE PROPIO (`MARKETING_SMTP_*`), separado del que manda los avisos y enlaces del portal. Sin él se puede preparar todo y descargar la audiencia, pero no enviar."""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import re
import smtplib
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from html import escape
from urllib.parse import urlparse

from . import acceso, auditoria, db
from .bd import contexto

ESQUEMA = """
CREATE TABLE IF NOT EXISTS marketing_contactos (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    nombre TEXT,
    cliente_id INTEGER REFERENCES clientes(id) ON DELETE SET NULL,
    estado TEXT NOT NULL CHECK (estado IN ('consentido', 'baja', 'rebotado')),
    origen TEXT NOT NULL,
    evidencia TEXT NOT NULL,
    documento_firma_id INTEGER,
    consentido_en TEXT,
    baja_en TEXT,
    registrado_por INTEGER REFERENCES usuarios(id),
    actualizado_en TEXT NOT NULL,
    PRIMARY KEY (tenant_id, email)
);
CREATE TABLE IF NOT EXISTS marketing_grupos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    reglas TEXT NOT NULL DEFAULT '{}',
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    papelera_en TEXT
);
CREATE TABLE IF NOT EXISTS marketing_plantillas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    asunto TEXT NOT NULL,
    bloques TEXT NOT NULL DEFAULT '[]',
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    actualizado_en TEXT,
    papelera_en TEXT
);
CREATE TABLE IF NOT EXISTS marketing_envios (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    grupo_id INTEGER REFERENCES marketing_grupos(id) ON DELETE SET NULL,
    asunto TEXT NOT NULL,
    bloques TEXT NOT NULL DEFAULT '[]',
    estado TEXT NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador', 'programado', 'enviando', 'enviado', 'cancelado')),
    url_base TEXT,
    programado_para TEXT,
    canal TEXT NOT NULL DEFAULT 'propio',
    proveedor_ref TEXT,
    proveedor_estado TEXT,
    total INTEGER NOT NULL DEFAULT 0,
    enviados INTEGER NOT NULL DEFAULT 0,
    errores INTEGER NOT NULL DEFAULT 0,
    excluidos TEXT NOT NULL DEFAULT '{}',
    ultimo_error TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    programado_por INTEGER REFERENCES usuarios(id),
    iniciado_en TEXT,
    terminado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_marketing_envios ON marketing_envios(tenant_id, estado, creado_en);
CREATE TABLE IF NOT EXISTS marketing_rebotes (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    envio_id INTEGER,
    tipo TEXT NOT NULL CHECK (tipo IN ('duro', 'blando', 'queja')),
    codigo TEXT,
    detalle TEXT,
    origen TEXT NOT NULL,
    recibido_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_marketing_rebotes ON marketing_rebotes(tenant_id, email, recibido_en);
CREATE TABLE IF NOT EXISTS marketing_proveedores (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    proveedor TEXT NOT NULL CHECK (proveedor IN ('brevo', 'mailchimp')),
    clave TEXT NOT NULL,
    ajustes TEXT NOT NULL DEFAULT '{}',
    verificado_en TEXT,
    actualizado_en TEXT NOT NULL,
    actualizado_por INTEGER REFERENCES usuarios(id),
    PRIMARY KEY (tenant_id, proveedor)
);
CREATE TABLE IF NOT EXISTS marketing_envio_destinatarios (
    envio_id INTEGER NOT NULL REFERENCES marketing_envios(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    nombre TEXT,
    cliente_id INTEGER,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'enviado', 'error', 'omitido')),
    enviado_en TEXT,
    error TEXT,
    PRIMARY KEY (envio_id, email)
);
"""

ORIGENES = {"documento_firmado": "Documento firmado", "formulario": "Formulario o casilla", "verbal": "Verbal, con constancia", "importacion": "Importación, con constancia"}
ORIGENES_MANUALES = ("formulario", "verbal", "importacion")
TIPOS_BLOQUE = {"titulo": "Título", "texto": "Texto", "boton": "Botón", "imagen": "Imagen", "divisor": "Divisor"}
VARIABLES = {"nombre": "Nombre del cliente", "email": "Correo del cliente", "empresa": "Nombre del despacho", "enlace_baja": "Enlace de baja (lo pone el sistema)"}
LOTE_POR_DEFECTO = 200
MAX_BLOQUES = 40
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_VARIABLE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


class ErrorMarketing(ValueError):
    """Un error de negocio con un mensaje apto para enseñárselo a la persona."""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    for columna, definicion in (("canal", "TEXT NOT NULL DEFAULT 'propio'"), ("proveedor_ref", "TEXT"), ("proveedor_estado", "TEXT")):     # bases anteriores a los conectores
        db._asegurar_columna(conn, "marketing_envios", columna, definicion)


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    for tabla in ("marketing_envio_destinatarios", "marketing_envios", "marketing_plantillas", "marketing_grupos", "marketing_rebotes", "marketing_proveedores", "marketing_contactos"):
        conn.execute(f"DELETE FROM {tabla} WHERE tenant_id = ?", (tenant_id,))


def _ahora(ahora: datetime | None = None) -> str:
    return (ahora or datetime.now()).replace(microsecond=0).isoformat(timespec="seconds")


def _exigir_escritura(tenant_id: int, usuario_id: int) -> None:
    if acceso.es_solo_auditor(tenant_id, usuario_id):
        raise ErrorMarketing("Tu rol solo permite consultar.")


def _exigir_direccion(usuario_id: int, que: str) -> None:
    if not acceso.es_directivo(usuario_id):
        raise ErrorMarketing(f"Solo la dirección del despacho {que}.")


def normalizar_email(email) -> str:
    e = str(email or "").strip().lower()
    if not _EMAIL.match(e) or len(e) > 200:
        raise ErrorMarketing("El correo no es válido.")
    return e


# --- Consentimientos -------------------------------------------------------------------------------------------------------------

def obtener_contacto(tenant_id: int, email: str) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM marketing_contactos WHERE tenant_id = ? AND email = ?", (tenant_id, str(email).strip().lower())).fetchone()
    finally:
        conn.close()
    return dict(f) if f else None


def registrar_consentimiento(tenant_id: int, usuario_id: int | None, email: str, *, origen: str, evidencia: str, nombre: str = "", cliente_id: int | None = None,
                             documento_firma_id: int | None = None, ahora: datetime | None = None) -> dict:
    """Anota que este correo ha consentido recibir comunicaciones comerciales, con la prueba. Sin prueba no se registra; un correo que rebotó no se reactiva por esta vía."""
    if usuario_id is not None:
        _exigir_escritura(tenant_id, usuario_id)
    e = normalizar_email(email)
    if origen not in ORIGENES:
        raise ErrorMarketing("Indica cómo se consintió.")
    evidencia = re.sub(r"\s+", " ", str(evidencia or "")).strip()[:500]
    if not evidencia:
        raise ErrorMarketing("Anota la prueba del consentimiento (cuándo y cómo lo dio).")
    actual = obtener_contacto(tenant_id, e)
    if actual and actual["estado"] == "rebotado":
        raise ErrorMarketing("Ese correo rebotó: corrígelo en la ficha del cliente antes de volver a escribirle.")
    t = _ahora(ahora)
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO marketing_contactos (tenant_id, email, nombre, cliente_id, estado, origen, evidencia, documento_firma_id, consentido_en, baja_en, registrado_por, actualizado_en) "
            "VALUES (?, ?, ?, ?, 'consentido', ?, ?, ?, ?, NULL, ?, ?) ON CONFLICT (tenant_id, email) DO UPDATE SET nombre = excluded.nombre, cliente_id = excluded.cliente_id, "
            "estado = 'consentido', origen = excluded.origen, evidencia = excluded.evidencia, documento_firma_id = excluded.documento_firma_id, consentido_en = excluded.consentido_en, "
            "baja_en = NULL, registrado_por = excluded.registrado_por, actualizado_en = excluded.actualizado_en",
            (tenant_id, e, (nombre or "")[:200] or None, cliente_id, origen, evidencia, documento_firma_id, t, usuario_id, t))
        auditoria.registrar(tenant_id, usuario_id, "marketing.consentimiento", "marketing_contacto", e, {"origen": origen, "cliente_id": cliente_id}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return obtener_contacto(tenant_id, e)


def registrar_baja(tenant_id: int, usuario_id: int | None, email: str, *, origen: str = "baja_en_correo", motivo: str = "", ahora: datetime | None = None) -> dict | None:
    """Da de baja un correo (aunque no estuviera registrado: así queda excluido para siempre). La baja prevalece sobre cualquier consentimiento."""
    e = normalizar_email(email)
    t = _ahora(ahora)
    actual = obtener_contacto(tenant_id, e)
    conn = db.get_connection()
    try:
        if actual is None:
            conn.execute("INSERT INTO marketing_contactos (tenant_id, email, estado, origen, evidencia, baja_en, registrado_por, actualizado_en) VALUES (?, ?, 'baja', ?, ?, ?, ?, ?)",
                         (tenant_id, e, origen, (motivo or "Baja solicitada")[:500], t, usuario_id, t))
        else:
            conn.execute("UPDATE marketing_contactos SET estado = 'baja', baja_en = ?, evidencia = ?, actualizado_en = ? WHERE tenant_id = ? AND email = ?",
                         (t, (motivo or actual["evidencia"] or "Baja solicitada")[:500], t, tenant_id, e))
        conn.execute("UPDATE marketing_envio_destinatarios SET estado = 'omitido', error = 'baja' WHERE tenant_id = ? AND email = ? AND estado = 'pendiente'", (tenant_id, e))
        auditoria.registrar(tenant_id, usuario_id, "marketing.baja", "marketing_contacto", e, {"origen": origen}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return obtener_contacto(tenant_id, e)


def marcar_rebotado(tenant_id: int, usuario_id: int | None, email: str) -> None:
    e = normalizar_email(email)
    t = _ahora()
    conn = db.get_connection()
    try:
        conn.execute("UPDATE marketing_contactos SET estado = 'rebotado', actualizado_en = ? WHERE tenant_id = ? AND email = ? AND estado = 'consentido'", (t, tenant_id, e))
        conn.commit()
    finally:
        conn.close()


def al_firmar_consentimiento(tenant_id: int, usuario_id: int, documento: dict) -> None:
    """Efecto de firmar el «consentimiento de comunicaciones comerciales»: queda registrado, con el documento firmado como prueba."""
    from . import nucleo
    c = nucleo.obtener_cliente(tenant_id, documento["cliente_id"])
    if c is None or not (c["email"] or "").strip():
        return
    try:
        registrar_consentimiento(tenant_id, None, c["email"], origen="documento_firmado", nombre=c["nombre"], cliente_id=c["id"], documento_firma_id=documento["id"],
                                 evidencia=f"Documento firmado con Documenso el {(documento.get('firmado_en') or _ahora())[:10]} (huella {documento['pdf_sha256'][:16]}…)")
    except ErrorMarketing:
        pass


def _registrar_efectos() -> None:
    from . import documentos_firma
    documentos_firma.AL_FIRMAR["consentimiento_comercial"] = al_firmar_consentimiento


_registrar_efectos()


def listar_contactos(tenant_id: int, *, estado: str | None = None, q: str | None = None, limite: int = 200) -> list[dict]:
    donde, p = ["tenant_id = ?"], [tenant_id]
    if estado:
        donde.append("estado = ?")
        p.append(estado)
    if q and q.strip():
        donde.append("(LOWER(email) LIKE ? OR LOWER(nombre) LIKE ?)")
        p += [f"%{q.strip().lower()}%"] * 2
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(f"SELECT * FROM marketing_contactos WHERE {' AND '.join(donde)} ORDER BY actualizado_en DESC LIMIT ?", [*p, max(1, min(limite, 1000))]).fetchall()]
    finally:
        conn.close()


def resumen_consentimientos(tenant_id: int) -> dict:
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT estado, COUNT(*) n FROM marketing_contactos WHERE tenant_id = ? GROUP BY estado", (tenant_id,)).fetchall()
    finally:
        conn.close()
    r = {"consentido": 0, "baja": 0, "rebotado": 0}
    r.update({f["estado"]: f["n"] for f in filas})
    return r


# --- Grupos (segmentos por reglas) -----------------------------------------------------------------------------------------------

def reglas_validas(reglas: dict) -> dict:
    fuente = reglas.get("fuente") if reglas.get("fuente") in ("clientes", "prospectos", "ambos") else "clientes"
    etiquetas = [re.sub(r"\s+", " ", str(x)).strip()[:60] for x in (reglas.get("etiquetas") or []) if str(x).strip()][:20]
    limpias = {"fuente": fuente, "etiquetas": etiquetas, "etiquetas_modo": "todas" if reglas.get("etiquetas_modo") == "todas" else "alguna",
               "tipo": reglas.get("tipo") if reglas.get("tipo") in ("persona", "empresa") else "", "origen": str(reglas.get("origen") or "").strip()[:100],
               "idioma": str(reglas.get("idioma") or "").strip()[:10], "etapa": str(reglas.get("etapa") or "").strip()[:60]}
    limpias["vencimiento_modelo"] = re.sub(r"[^0-9A-Za-z]", "", str(reglas.get("vencimiento_modelo") or ""))[:6].upper()
    try:
        limpias["vencimiento_dias"] = min(max(int(reglas.get("vencimiento_dias") or 30), 1), 365)
    except (TypeError, ValueError):
        raise ErrorMarketing("Los días de antelación no son válidos.") from None
    try:
        limpias["responsable_id"] = int(reglas["responsable_id"]) if reglas.get("responsable_id") not in (None, "") else None
    except (TypeError, ValueError):
        raise ErrorMarketing("La persona responsable no es válida.") from None
    return limpias


def describir_reglas(r: dict) -> str:
    partes = [{"clientes": "Clientes", "prospectos": "Prospectos", "ambos": "Clientes y prospectos"}[r["fuente"]]]
    if r["tipo"]:
        partes.append({"persona": "personas", "empresa": "empresas"}[r["tipo"]])
    if r["etiquetas"]:
        partes.append(("con todas las etiquetas " if r["etiquetas_modo"] == "todas" else "con alguna etiqueta de ") + ", ".join(r["etiquetas"]))
    for clave, texto in (("origen", "origen"), ("idioma", "idioma"), ("etapa", "etapa")):
        if r[clave]:
            partes.append(f"{texto} {r[clave]}")
    if r.get("vencimiento_modelo"):
        partes.append(f"con el modelo {r['vencimiento_modelo']} por presentar en los próximos {r.get('vencimiento_dias', 30)} días")
    if r["responsable_id"]:
        partes.append("de una persona concreta")
    return " · ".join(partes)


def crear_grupo(tenant_id: int, usuario_id: int, nombre: str, reglas: dict, descripcion: str = "") -> int:
    _exigir_escritura(tenant_id, usuario_id)
    nombre = re.sub(r"\s+", " ", nombre or "").strip()[:100]
    if not nombre:
        raise ErrorMarketing("Ponle nombre al grupo.")
    limpias = reglas_validas(reglas or {})
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO marketing_grupos (tenant_id, nombre, descripcion, reglas, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?)",
                           (tenant_id, nombre, (descripcion or "").strip()[:300] or None, json.dumps(limpias, ensure_ascii=False), usuario_id, _ahora()))
        auditoria.registrar(tenant_id, usuario_id, "marketing.grupo.crear", "marketing_grupo", cur.lastrowid, {"nombre": nombre}, conn=conn)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _grupo(f) -> dict:
    d = dict(f)
    d["reglas"] = reglas_validas(json.loads(d["reglas"] or "{}"))
    d["descripcion_reglas"] = describir_reglas(d["reglas"])
    return d


def listar_grupos(tenant_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        return [_grupo(f) for f in conn.execute("SELECT * FROM marketing_grupos WHERE tenant_id = ? AND papelera_en IS NULL ORDER BY nombre", (tenant_id,)).fetchall()]
    finally:
        conn.close()


def obtener_grupo(tenant_id: int, grupo_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM marketing_grupos WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (grupo_id, tenant_id)).fetchone()
    finally:
        conn.close()
    return _grupo(f) if f else None


def papelera_grupo(tenant_id: int, usuario_id: int, grupo_id: int) -> None:
    _exigir_escritura(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        conn.execute("UPDATE marketing_grupos SET papelera_en = ? WHERE id = ? AND tenant_id = ?", (_ahora(), grupo_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "marketing.grupo.papelera", "marketing_grupo", grupo_id, conn=conn)
        conn.commit()
    finally:
        conn.close()


def audiencia(tenant_id: int, usuario_id: int, reglas: dict) -> dict:
    """A quién llegaría un envío con estas reglas AHORA, y por qué se excluye al resto: `{destinatarios: [{email, nombre, cliente_id}], excluidos: {motivo: n}, candidatos: n}`."""
    r = reglas_validas(reglas)
    candidatos: list[dict] = []
    conn = db.get_connection()
    try:
        if r["fuente"] in ("clientes", "ambos"):
            cond, params = acceso.condicion_nucleo(tenant_id, usuario_id, "c.id")
            donde, p = ["c.tenant_id = ?", "c.papelera_en IS NULL"], [tenant_id]
            if r["tipo"]:
                donde.append("c.tipo = ?")
                p.append(r["tipo"])
            for campo in ("origen", "idioma"):
                if r[campo]:
                    donde.append(f"c.{campo} = ?")
                    p.append(r[campo])
            if r["responsable_id"]:
                donde.append("c.responsable_id = ?")
                p.append(r["responsable_id"])
            if r["vencimiento_modelo"]:                                  # clientes con ese modelo aún por presentar dentro del plazo: «se acerca el 303»
                hoy = date.today()
                donde.append("EXISTS (SELECT 1 FROM vencimientos_fiscales v JOIN clientes_fiscales f ON f.id = v.cliente_fiscal_id AND f.tenant_id = v.tenant_id "
                             "WHERE f.cliente_id = c.id AND v.tenant_id = c.tenant_id AND v.modelo = ? AND v.estado = 'pendiente' AND v.papelera_en IS NULL "
                             "AND substr(v.fecha_limite, 1, 10) >= ? AND substr(v.fecha_limite, 1, 10) <= ?)")
                p += [r["vencimiento_modelo"], hoy.isoformat(), (hoy + timedelta(days=r["vencimiento_dias"])).isoformat()]
            if r["etiquetas"]:
                marcas = ", ".join("?" for _ in r["etiquetas"])
                if r["etiquetas_modo"] == "todas":
                    donde.append(f"(SELECT COUNT(DISTINCT e.etiqueta) FROM cliente_etiquetas e WHERE e.cliente_id = c.id AND e.etiqueta IN ({marcas})) = ?")
                    p += [*r["etiquetas"], len(set(r["etiquetas"]))]
                else:
                    donde.append(f"EXISTS (SELECT 1 FROM cliente_etiquetas e WHERE e.cliente_id = c.id AND e.etiqueta IN ({marcas}))")
                    p += r["etiquetas"]
            if cond:
                donde.append(cond)
                p += params
            for f in conn.execute(f"SELECT c.id, c.nombre, c.email FROM clientes c WHERE {' AND '.join(donde)} ORDER BY c.id", p).fetchall():
                candidatos.append({"email": f["email"], "nombre": f["nombre"], "cliente_id": f["id"]})
        if r["fuente"] in ("prospectos", "ambos"):
            donde, p = ["o.tenant_id = ?", "o.papelera_en IS NULL", "o.estado = 'abierta'", "o.cliente_id IS NULL"], [tenant_id]
            if r["etapa"]:
                donde.append("o.etapa = ?")
                p.append(r["etapa"])
            if r["origen"]:
                donde.append("o.origen = ?")
                p.append(r["origen"])
            if r["responsable_id"]:
                donde.append("o.responsable_id = ?")
                p.append(r["responsable_id"])
            for f in conn.execute(f"SELECT o.contacto_nombre, o.empresa, o.contacto_email FROM crm_oportunidades o WHERE {' AND '.join(donde)} ORDER BY o.id", p).fetchall():
                candidatos.append({"email": f["contacto_email"], "nombre": f["contacto_nombre"] or f["empresa"] or "", "cliente_id": None})
        estados = {f["email"]: f["estado"] for f in conn.execute("SELECT email, estado FROM marketing_contactos WHERE tenant_id = ?", (tenant_id,)).fetchall()}
    finally:
        conn.close()
    excluidos = {"sin_correo": 0, "correo_no_valido": 0, "sin_consentimiento": 0, "baja": 0, "rebotado": 0, "duplicado": 0}
    vistos, destinatarios = set(), []
    for c in candidatos:
        bruto = (c["email"] or "").strip()
        if not bruto:
            excluidos["sin_correo"] += 1
            continue
        try:
            e = normalizar_email(bruto)
        except ErrorMarketing:
            excluidos["correo_no_valido"] += 1
            continue
        estado = estados.get(e)
        if estado == "baja":
            excluidos["baja"] += 1
        elif estado == "rebotado":
            excluidos["rebotado"] += 1
        elif estado != "consentido":
            excluidos["sin_consentimiento"] += 1
        elif e in vistos:
            excluidos["duplicado"] += 1
        else:
            vistos.add(e)
            destinatarios.append({"email": e, "nombre": c["nombre"] or "", "cliente_id": c["cliente_id"]})
    return {"destinatarios": destinatarios, "excluidos": {k: v for k, v in excluidos.items() if v}, "candidatos": len(candidatos)}


def exportar_audiencia_csv(destinatarios: list[dict]) -> bytes:
    """La audiencia con consentimiento, para usarla en otra herramienta de envío (Brevo, Mailchimp…)."""
    salida = io.StringIO()
    w = csv.writer(salida)
    w.writerow(["email", "nombre"])
    for d in destinatarios:
        w.writerow([d["email"], d["nombre"]])
    return salida.getvalue().encode("utf-8-sig")


# --- Plantillas y bloques -------------------------------------------------------------------------------------------------------

def bloques_validos(bloques) -> list[dict]:
    if not isinstance(bloques, list) or not bloques:
        raise ErrorMarketing("La plantilla necesita al menos un bloque.")
    if len(bloques) > MAX_BLOQUES:
        raise ErrorMarketing(f"Máximo {MAX_BLOQUES} bloques.")
    limpios = []
    for b in bloques:
        tipo = b.get("tipo") if isinstance(b, dict) else None
        if tipo not in TIPOS_BLOQUE:
            raise ErrorMarketing("Tipo de bloque no válido.")
        texto = str(b.get("texto") or "").strip()[:2000]
        url = str(b.get("url") or "").strip()[:500]
        if tipo in ("boton", "imagen"):
            if urlparse(url).scheme not in ("https", "http") or not urlparse(url).netloc:
                raise ErrorMarketing("El enlace del botón o de la imagen debe empezar por https://.")
        if tipo in ("titulo", "texto", "boton") and not texto:
            raise ErrorMarketing("Hay un bloque de texto vacío.")
        for v in _VARIABLE.findall(texto + " " + url):
            if v not in VARIABLES:
                raise ErrorMarketing("Variable desconocida: {{" + v + "}}.")
        limpios.append({"tipo": tipo, "texto": texto if tipo != "imagen" else texto[:200], "url": url if tipo in ("boton", "imagen") else ""})
    return limpios


def _sustituir(texto: str, valores: dict) -> str:
    return _VARIABLE.sub(lambda m: str(valores.get(m.group(1), "")), texto)


def render_html(bloques: list[dict], valores: dict, despacho: dict, *, color: str = "#1f3a5f") -> str:
    """El HTML del correo: los bloques de la plantilla y SIEMPRE, al pie, el enlace de baja y los datos del despacho. Todo el texto va escapado."""
    partes = []
    for b in bloques:
        t = escape(_sustituir(b["texto"], valores))
        if b["tipo"] == "titulo":
            partes.append(f'<h1 style="font-size:24px;line-height:1.25;margin:0 0 16px;color:#111">{t}</h1>')
        elif b["tipo"] == "texto":
            partes.append('<p style="font-size:15px;line-height:1.6;margin:0 0 16px;color:#222">' + t.replace("\n", "<br>") + "</p>")
        elif b["tipo"] == "boton":
            partes.append(f'<p style="margin:0 0 20px;text-align:center"><a href="{escape(_sustituir(b["url"], valores), quote=True)}" style="display:inline-block;background:{color};color:#fff;'
                          f'text-decoration:none;padding:12px 22px;border-radius:6px;font-size:15px">{t}</a></p>')
        elif b["tipo"] == "imagen":
            partes.append(f'<p style="margin:0 0 16px;text-align:center"><img src="{escape(b["url"], quote=True)}" alt="{t}" style="max-width:100%;height:auto"></p>')
        else:
            partes.append('<hr style="border:0;border-top:1px solid #ddd;margin:20px 0">')
    enlace = escape(valores.get("enlace_baja", "#"), quote=True)
    pie = (f'<p style="font-size:12px;line-height:1.5;color:#666;text-align:center;margin:24px 0 0">Recibes este correo porque nos diste tu consentimiento. '
           f'<a href="{enlace}" style="color:#666">Darme de baja</a><br>{escape(despacho.get("nombre", ""))} · {escape(despacho.get("cif", ""))} · {escape(despacho.get("direccion", ""))}</p>')
    return ('<!doctype html><html><body style="margin:0;padding:24px;background:#f4f4f4"><div style="max-width:600px;margin:0 auto;background:#fff;padding:32px;border-radius:8px;font-family:Arial,sans-serif">'
            + "".join(partes) + pie + "</div></body></html>")


def render_texto(bloques: list[dict], valores: dict, despacho: dict) -> str:
    lineas = []
    for b in bloques:
        if b["tipo"] in ("titulo", "texto"):
            lineas.append(_sustituir(b["texto"], valores))
        elif b["tipo"] == "boton":
            lineas.append(f"{_sustituir(b['texto'], valores)}: {_sustituir(b['url'], valores)}")
    lineas.append(f"Para darte de baja: {valores.get('enlace_baja', '')}\n{despacho.get('nombre', '')} · {despacho.get('cif', '')} · {despacho.get('direccion', '')}")
    return "\n\n".join(lineas)


PLANTILLA_INICIAL = [{"tipo": "titulo", "texto": "Una novedad para ti, {{nombre}}", "url": ""},
                     {"tipo": "texto", "texto": "Hola {{nombre}},\n\nEscribe aquí tu mensaje.", "url": ""},
                     {"tipo": "boton", "texto": "Más información", "url": "https://"}]

PLANTILLA_AVISO_FISCAL = [{"tipo": "titulo", "texto": "Se acerca la fecha de presentación, {{nombre}}", "url": ""},
                          {"tipo": "texto", "texto": "Hola {{nombre}},\n\nTe recordamos que se acerca el plazo de presentación del modelo que tenemos pendiente contigo. Para llegar a tiempo necesitamos que nos "
                                                     "envíes la documentación que falte (facturas emitidas y recibidas del periodo).\n\nSi ya nos lo has enviado todo, no tienes que hacer nada.", "url": ""},
                          {"tipo": "boton", "texto": "Enviar documentación", "url": "https://"}]


def crear_plantilla(tenant_id: int, usuario_id: int, nombre: str, asunto: str, bloques) -> int:
    _exigir_escritura(tenant_id, usuario_id)
    nombre = re.sub(r"\s+", " ", nombre or "").strip()[:100]
    asunto = re.sub(r"\s+", " ", asunto or "").strip()[:200]
    if not nombre or not asunto:
        raise ErrorMarketing("Pon nombre y asunto a la plantilla.")
    limpios = bloques_validos(bloques)
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO marketing_plantillas (tenant_id, nombre, asunto, bloques, creado_por, creado_en, actualizado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, nombre, asunto, json.dumps(limpios, ensure_ascii=False), usuario_id, _ahora(), _ahora()))
        auditoria.registrar(tenant_id, usuario_id, "marketing.plantilla.crear", "marketing_plantilla", cur.lastrowid, conn=conn)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def editar_plantilla(tenant_id: int, usuario_id: int, plantilla_id: int, nombre: str, asunto: str, bloques) -> None:
    _exigir_escritura(tenant_id, usuario_id)
    if obtener_plantilla(tenant_id, plantilla_id) is None:
        raise ErrorMarketing("Plantilla no encontrada.")
    nombre = re.sub(r"\s+", " ", nombre or "").strip()[:100]
    asunto = re.sub(r"\s+", " ", asunto or "").strip()[:200]
    if not nombre or not asunto:
        raise ErrorMarketing("Pon nombre y asunto a la plantilla.")
    limpios = bloques_validos(bloques)
    conn = db.get_connection()
    try:
        conn.execute("UPDATE marketing_plantillas SET nombre = ?, asunto = ?, bloques = ?, actualizado_en = ? WHERE id = ? AND tenant_id = ?",
                     (nombre, asunto, json.dumps(limpios, ensure_ascii=False), _ahora(), plantilla_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "marketing.plantilla.editar", "marketing_plantilla", plantilla_id, conn=conn)
        conn.commit()
    finally:
        conn.close()


def _plantilla(f) -> dict:
    d = dict(f)
    d["bloques"] = json.loads(d["bloques"] or "[]")
    return d


def obtener_plantilla(tenant_id: int, plantilla_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM marketing_plantillas WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (plantilla_id, tenant_id)).fetchone()
    finally:
        conn.close()
    return _plantilla(f) if f else None


def listar_plantillas(tenant_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        return [_plantilla(f) for f in conn.execute("SELECT * FROM marketing_plantillas WHERE tenant_id = ? AND papelera_en IS NULL ORDER BY actualizado_en DESC, id DESC", (tenant_id,)).fetchall()]
    finally:
        conn.close()


def papelera_plantilla(tenant_id: int, usuario_id: int, plantilla_id: int) -> None:
    _exigir_escritura(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        conn.execute("UPDATE marketing_plantillas SET papelera_en = ? WHERE id = ? AND tenant_id = ?", (_ahora(), plantilla_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


def _datos_del_despacho(tenant_id: int) -> dict:
    t = db.obtener_tenant(tenant_id)
    return {"nombre": (t["nombre"] if t else "") or "", "cif": (t["cif"] if t else "") or "", "direccion": (t["direccion_fiscal"] if t else "") or ""}


def datos_legales_que_faltan(tenant_id: int) -> list[str]:
    d = _datos_del_despacho(tenant_id)
    return [etiqueta for clave, etiqueta in (("cif", "CIF del despacho"), ("direccion", "Dirección fiscal del despacho")) if not d[clave].strip()]


def vista_previa(tenant_id: int, bloques: list[dict], *, nombre: str = "Marta") -> str:
    d = _datos_del_despacho(tenant_id)
    return render_html(bloques_validos(bloques), {"nombre": nombre, "email": "marta@ejemplo.com", "empresa": d["nombre"], "enlace_baja": "#"}, d)


ACCIONES_IA = {"redactar": "Redacta un correo completo a partir de un breve resumen.", "reescribir": "Reescribe el texto con otro tono, más corto o más cercano.",
               "asuntos": "Propón cinco asuntos distintos para este correo.", "mejorar": "Revisa la claridad, la llamada a la acción y los requisitos legales."}


def asistente_ia(tenant_id: int, usuario_id: int, accion: str, texto: str, objetivo: str = "") -> str:
    """Un borrador de la IA a partir SOLO del texto de la plantilla y de lo que escribe la persona (nunca datos de clientes). Se revisa antes de aplicar."""
    from . import ia_asistente, reuniones
    _exigir_escritura(tenant_id, usuario_id)
    if accion not in ACCIONES_IA:
        raise ErrorMarketing("Esa ayuda no existe.")
    if not reuniones.configurada(usuario_id):
        raise ErrorMarketing("Para usar la IA hace falta un modelo y tu clave de OpenRouter, en Ajustes del Asistente IA.")
    sistema = ("Eres un redactor de correos comerciales para un despacho profesional español. Escribe en español, claro y cercano, sin inventar datos ni promesas. "
               "Usa solo las variables {{nombre}} y {{empresa}} si hacen falta. No incluyas el enlace de baja ni la dirección: el sistema los añade. " + ACCIONES_IA[accion])
    try:
        return ia_asistente.completar_texto(usuario_id, sistema, f"Objetivo: {objetivo[:500]}\n\nTexto actual:\n{texto[:4000]}").strip()
    except ia_asistente.ErrorIA as e:
        raise ErrorMarketing("No se pudo consultar a la IA (o se agotó el tope mensual).") from e


# --- Envíos ---------------------------------------------------------------------------------------------------------------------

def canal_configurado() -> bool:
    return all(os.environ.get(v) for v in ("MARKETING_SMTP_HOST", "MARKETING_SMTP_USUARIO", "MARKETING_SMTP_CONTRASENA", "MARKETING_SMTP_REMITENTE"))


def _clave_baja() -> bytes:
    return (os.environ.get("GUILDA_SECRET_KEY") or "guilda-sin-clave").encode()


def token_baja(tenant_id: int, email: str) -> str:
    cuerpo = f"{tenant_id}:{normalizar_email(email)}"
    firma = hmac.new(_clave_baja(), b"baja:" + cuerpo.encode(), hashlib.sha256).hexdigest()[:32]
    return (cuerpo + ":" + firma).encode().hex()


def verificar_token_baja(token: str) -> tuple[int, str] | None:
    try:
        cuerpo = bytes.fromhex(token).decode()
        tenant, email, firma = cuerpo.split(":", 2)
        esperado = hmac.new(_clave_baja(), f"baja:{tenant}:{email}".encode(), hashlib.sha256).hexdigest()[:32]
        if hmac.compare_digest(firma, esperado):
            return int(tenant), normalizar_email(email)
    except (ValueError, UnicodeDecodeError, ErrorMarketing):
        pass
    return None


def _enviar_smtp(destinatario: str, asunto: str, texto: str, html: str, enlace_baja: str) -> None:
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = asunto, os.environ["MARKETING_SMTP_REMITENTE"], destinatario
    m["List-Unsubscribe"] = f"<{enlace_baja}>"
    m["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    m.set_content(texto)
    m.add_alternative(html, subtype="html")
    with smtplib.SMTP(os.environ["MARKETING_SMTP_HOST"], int(os.environ.get("MARKETING_SMTP_PUERTO", "587")), timeout=15) as smtp:
        smtp.starttls()
        smtp.login(os.environ["MARKETING_SMTP_USUARIO"], os.environ["MARKETING_SMTP_CONTRASENA"])
        smtp.send_message(m, from_addr=os.environ.get("MARKETING_SMTP_RETORNO") or None)       # a dónde vuelven los rebotes (por defecto, el remitente)


def _envio(f) -> dict:
    d = dict(f)
    d["bloques"] = json.loads(d["bloques"] or "[]")
    d["excluidos"] = json.loads(d["excluidos"] or "{}")
    return d


def crear_envio(tenant_id: int, usuario_id: int, nombre: str, grupo_id: int, asunto: str, bloques, canal: str = "propio") -> int:
    """Un borrador de envío: el grupo, el asunto y los bloques (copia de la plantilla, que luego puede cambiar sin afectar a lo enviado)."""
    _exigir_escritura(tenant_id, usuario_id)
    nombre = re.sub(r"\s+", " ", nombre or "").strip()[:100]
    asunto = re.sub(r"\s+", " ", asunto or "").strip()[:200]
    if not nombre or not asunto:
        raise ErrorMarketing("Pon nombre y asunto al envío.")
    if obtener_grupo(tenant_id, grupo_id) is None:
        raise ErrorMarketing("Elige a qué grupo va el envío.")
    limpios = bloques_validos(bloques)
    if canal != "propio":
        p = obtener_proveedor(tenant_id, canal)
        if p is None or not p["verificado_en"]:
            raise ErrorMarketing("Ese canal no está configurado y probado: hazlo en Marketing → Canales de envío.")
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO marketing_envios (tenant_id, nombre, grupo_id, asunto, bloques, canal, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, nombre, grupo_id, asunto, json.dumps(limpios, ensure_ascii=False), canal, usuario_id, _ahora()))
        auditoria.registrar(tenant_id, usuario_id, "marketing.envio.crear", "marketing_envio", cur.lastrowid, {"grupo_id": grupo_id}, conn=conn)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def obtener_envio(tenant_id: int, envio_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM marketing_envios WHERE id = ? AND tenant_id = ?", (envio_id, tenant_id)).fetchone()
    finally:
        conn.close()
    return _envio(f) if f else None


def listar_envios(tenant_id: int, limite: int = 50) -> list[dict]:
    conn = db.get_connection()
    try:
        return [_envio(f) for f in conn.execute("SELECT * FROM marketing_envios WHERE tenant_id = ? ORDER BY id DESC LIMIT ?", (tenant_id, limite)).fetchall()]
    finally:
        conn.close()


def destinatarios_de(tenant_id: int, envio_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT * FROM marketing_envio_destinatarios WHERE envio_id = ? AND tenant_id = ? ORDER BY email", (envio_id, tenant_id)).fetchall()]
    finally:
        conn.close()


def revisar(tenant_id: int, usuario_id: int, envio_id: int) -> dict:
    """Lo que se enseña antes de programar: la audiencia de ahora mismo, lo excluido y lo que impide enviar."""
    e = obtener_envio(tenant_id, envio_id)
    if e is None:
        raise ErrorMarketing("Envío no encontrado.")
    a = audiencia(tenant_id, usuario_id, obtener_grupo(tenant_id, e["grupo_id"])["reglas"]) if e["grupo_id"] and obtener_grupo(tenant_id, e["grupo_id"]) else {"destinatarios": [], "excluidos": {}, "candidatos": 0}
    problemas = [f"Falta: {x}" for x in datos_legales_que_faltan(tenant_id)]
    if not a["destinatarios"]:
        problemas.append("No hay ningún destinatario con consentimiento en este grupo.")
    if e["canal"] == "propio" and not canal_configurado():
        problemas.append("El canal de envío de marketing no está configurado en el servidor (MARKETING_SMTP_*): puedes descargar la audiencia y enviarla desde otra herramienta.")
    if e["canal"] != "propio" and (obtener_proveedor(tenant_id, e["canal"]) or {}).get("verificado_en") is None:
        problemas.append("El canal elegido ya no está configurado y probado.")
    return {"envio": e, "audiencia": a, "problemas": problemas}


def programar(tenant_id: int, usuario_id: int, envio_id: int, confirmacion: str, *, url_base: str, cuando: datetime | None = None) -> dict:
    """Congela la audiencia y deja el envío listo para salir. Solo la dirección, y escribiendo el recuento de destinatarios."""
    _exigir_direccion(usuario_id, "programa envíos de marketing")
    r = revisar(tenant_id, usuario_id, envio_id)
    e = r["envio"]
    if e["estado"] != "borrador":
        raise ErrorMarketing("Este envío ya se programó.")
    if r["problemas"]:
        raise ErrorMarketing(r["problemas"][0])
    n = len(r["audiencia"]["destinatarios"])
    if str(confirmacion or "").strip() != str(n):
        raise ErrorMarketing(f"Escribe {n} (el número de destinatarios) para confirmar.")
    conn = db.get_connection()
    try:
        conn.executemany("INSERT INTO marketing_envio_destinatarios (envio_id, tenant_id, email, nombre, cliente_id) VALUES (?, ?, ?, ?, ?)",
                         [(envio_id, tenant_id, d["email"], d["nombre"], d["cliente_id"]) for d in r["audiencia"]["destinatarios"]])
        conn.execute("UPDATE marketing_envios SET estado = 'programado', url_base = ?, programado_para = ?, total = ?, excluidos = ?, programado_por = ? WHERE id = ? AND tenant_id = ?",
                     (url_base.rstrip("/"), _ahora(cuando), n, json.dumps(r["audiencia"]["excluidos"]), usuario_id, envio_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "marketing.envio.programar", "marketing_envio", envio_id, {"destinatarios": n, "excluidos": r["audiencia"]["excluidos"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return obtener_envio(tenant_id, envio_id)


def cancelar_envio(tenant_id: int, usuario_id: int, envio_id: int) -> None:
    _exigir_escritura(tenant_id, usuario_id)
    e = obtener_envio(tenant_id, envio_id)
    if e is None or e["estado"] not in ("borrador", "programado", "enviando"):
        raise ErrorMarketing("Este envío no se puede cancelar.")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE marketing_envios SET estado = 'cancelado', terminado_en = ? WHERE id = ? AND tenant_id = ?", (_ahora(), envio_id, tenant_id))
        conn.execute("UPDATE marketing_envio_destinatarios SET estado = 'omitido', error = 'envío cancelado' WHERE envio_id = ? AND estado = 'pendiente'", (envio_id,))
        auditoria.registrar(tenant_id, usuario_id, "marketing.envio.cancelar", "marketing_envio", envio_id, conn=conn)
        conn.commit()
    finally:
        conn.close()


def _componer_correo(tenant_id: int, e: dict, email: str, nombre: str, url_base: str) -> tuple[str, str, str, str]:
    d = _datos_del_despacho(tenant_id)
    enlace = f"{url_base.rstrip('/')}/baja/{token_baja(tenant_id, email)}"
    valores = {"nombre": nombre or "", "email": email, "empresa": d["nombre"], "enlace_baja": enlace}
    return _sustituir(e["asunto"], valores), render_texto(e["bloques"], valores, d), render_html(e["bloques"], valores, d), enlace


def enviar_prueba(tenant_id: int, usuario_id: int, envio_id: int, email: str, *, url_base: str, enviador=None) -> None:
    """Un correo de prueba a UNA dirección que indica la persona (no toca el registro de consentimientos). Lleva «[PRUEBA]» en el asunto."""
    _exigir_escritura(tenant_id, usuario_id)
    e = obtener_envio(tenant_id, envio_id)
    if e is None:
        raise ErrorMarketing("Envío no encontrado.")
    destino = normalizar_email(email)
    enviador = enviador or _enviar_smtp
    if enviador is _enviar_smtp and not canal_configurado():
        raise ErrorMarketing("El canal de envío de marketing no está configurado en el servidor.")
    asunto, texto, html, enlace = _componer_correo(tenant_id, e, destino, "Marta", url_base)
    try:
        enviador(destino, "[PRUEBA] " + asunto, texto, html, enlace)
    except (smtplib.SMTPException, OSError) as err:
        raise ErrorMarketing(f"No se pudo enviar la prueba: {err}") from err


def procesar_pendientes(*, enviador=None, lote: int = LOTE_POR_DEFECTO, ahora: datetime | None = None, proveedores: dict | None = None) -> dict:
    """Envía, de los envíos programados, hasta `lote` correos. Antes de CADA correo vuelve a comprobar que el destinatario sigue con consentimiento y sin baja. Lo llama el temporizador."""
    enviador = enviador or _enviar_smtp
    smtp_listo = enviador is not _enviar_smtp or canal_configurado()
    t = _ahora(ahora)
    totales = {"enviados": 0, "errores": 0, "omitidos": 0}
    with contexto.como_plataforma():
        conn = db.get_connection(plataforma=True)
        try:
            envios = [_envio(f) for f in conn.execute("SELECT * FROM marketing_envios WHERE estado IN ('programado', 'enviando') AND programado_para <= ? ORDER BY id", (t,)).fetchall()]
        finally:
            conn.close()
    restante = lote
    for e in envios:
        with contexto.en_despacho(e["tenant_id"]):
            if e["canal"] != "propio":                                      # un proveedor recibe el envío ENTERO de una vez: no entra en el lote
                _procesar_envio_proveedor(e, t, totales, proveedores)
            elif smtp_listo and restante > 0:
                restante = _procesar_envio(e, enviador, restante, t, totales)
    return {**totales, "sin_canal": True} if not smtp_listo and not any(totales.values()) else totales


def _procesar_envio(e: dict, enviador, restante: int, t: str, totales: dict) -> int:
    """Envía los pendientes de un envío (ya en el contexto de su despacho) y devuelve cuántos del lote quedan."""
    conn = db.get_connection()
    try:
        conn.execute("UPDATE marketing_envios SET estado = 'enviando', iniciado_en = COALESCE(iniciado_en, ?) WHERE id = ?", (t, e["id"]))
        pendientes = conn.execute("SELECT * FROM marketing_envio_destinatarios WHERE envio_id = ? AND estado = 'pendiente' ORDER BY email LIMIT ?", (e["id"], restante)).fetchall()
        conn.commit()
    finally:
        conn.close()
    for p in pendientes:
        restante -= 1
        contacto = obtener_contacto(e["tenant_id"], p["email"])
        if contacto is None or contacto["estado"] != "consentido":
            nuevo, error = "omitido", (contacto["estado"] if contacto else "sin consentimiento")
        else:
            try:
                asunto, texto, html, enlace = _componer_correo(e["tenant_id"], e, p["email"], p["nombre"], e["url_base"] or "")
                enviador(p["email"], asunto, texto, html, enlace)
                nuevo, error = "enviado", None
            except smtplib.SMTPRecipientsRefused as err:
                codigo, mensaje = err.recipients.get(p["email"], (0, b""))
                mensaje = mensaje.decode(errors="replace") if isinstance(mensaje, bytes) else str(mensaje)
                nuevo, error = "error", f"buzón rechazado: {codigo} {mensaje}"[:300]
                if 500 <= int(codigo or 0) < 600:                                   # el servidor de destino dice que ese buzón no existe o no acepta correo: rebote duro
                    registrar_rebote(e["tenant_id"], p["email"], tipo="duro", codigo=str(codigo), detalle=mensaje, origen="smtp", envio_id=e["id"])
            except (smtplib.SMTPException, OSError, ErrorMarketing) as err:
                nuevo, error = "error", str(err)[:300]
        conn = db.get_connection()
        try:
            conn.execute("UPDATE marketing_envio_destinatarios SET estado = ?, error = ?, enviado_en = ? WHERE envio_id = ? AND email = ?", (nuevo, error, t if nuevo == "enviado" else None, e["id"], p["email"]))
            conn.commit()
        finally:
            conn.close()
        totales["enviados" if nuevo == "enviado" else "errores" if nuevo == "error" else "omitidos"] += 1
    conn = db.get_connection()
    try:
        c = {f["estado"]: f["n"] for f in conn.execute("SELECT estado, COUNT(*) n FROM marketing_envio_destinatarios WHERE envio_id = ? GROUP BY estado", (e["id"],)).fetchall()}
        terminado = not c.get("pendiente")
        conn.execute("UPDATE marketing_envios SET enviados = ?, errores = ?, estado = ?, terminado_en = ? WHERE id = ?",
                     (c.get("enviado", 0), c.get("error", 0), "enviado" if terminado else "enviando", t if terminado else None, e["id"]))
        conn.commit()
    finally:
        conn.close()
    return restante


# --- Rebotes ------------------------------------------------------------------------------------------------------------------

BLANDOS_PARA_REBOTAR = 3                 # rebotes blandos (buzón lleno, servidor caído…) en DIAS_BLANDOS días bastan para dejar de escribir a ese correo
DIAS_BLANDOS = 30


def registrar_rebote(tenant_id: int, email: str, *, tipo: str, codigo: str = "", detalle: str = "", origen: str, envio_id: int | None = None, ahora: datetime | None = None) -> dict:
    """Anota un rebote. Uno DURO (el buzón no existe) o una QUEJA de spam deja ese correo como «rebotado» al instante; los BLANDOS lo hacen al repetirse. Un correo rebotado nunca recibe nada."""
    from datetime import timedelta
    if tipo not in ("duro", "blando", "queja"):
        raise ErrorMarketing("Tipo de rebote no válido.")
    e = normalizar_email(email)
    t = _ahora(ahora)
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO marketing_rebotes (tenant_id, email, envio_id, tipo, codigo, detalle, origen, recibido_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (tenant_id, e, envio_id, tipo, (codigo or "")[:20] or None, (detalle or "")[:500] or None, origen, t))
        desde = _ahora((ahora or datetime.now()) - timedelta(days=DIAS_BLANDOS))
        blandos = conn.execute("SELECT COUNT(*) FROM marketing_rebotes WHERE tenant_id = ? AND email = ? AND tipo = 'blando' AND recibido_en >= ? AND recibido_en <= ?", (tenant_id, e, desde, t)).fetchone()[0]
        rebota = tipo in ("duro", "queja") or blandos >= BLANDOS_PARA_REBOTAR
        if rebota:
            conn.execute("UPDATE marketing_contactos SET estado = 'rebotado', actualizado_en = ? WHERE tenant_id = ? AND email = ? AND estado = 'consentido'", (t, tenant_id, e))
            conn.execute("UPDATE marketing_envio_destinatarios SET estado = 'omitido', error = 'rebotado' WHERE tenant_id = ? AND email = ? AND estado = 'pendiente'", (tenant_id, e))
        auditoria.registrar(tenant_id, None, "marketing.rebote", "marketing_contacto", e, {"tipo": tipo, "origen": origen, "codigo": codigo}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return {"email": e, "tipo": tipo, "rebotado": rebota}


def listar_rebotes(tenant_id: int, limite: int = 30) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT * FROM marketing_rebotes WHERE tenant_id = ? ORDER BY id DESC LIMIT ?", (tenant_id, limite)).fetchall()]
    finally:
        conn.close()


def reactivar_rebotado(tenant_id: int, usuario_id: int, email: str, motivo: str) -> dict:
    """La dirección del despacho vuelve a permitir escribir a un correo rebotado (p. ej. el cliente confirma que su buzón ya funciona). Exige un motivo y queda en la auditoría."""
    _exigir_direccion(usuario_id, "reactiva un correo rebotado")
    e = normalizar_email(email)
    motivo = re.sub(r"\s+", " ", motivo or "").strip()[:300]
    actual = obtener_contacto(tenant_id, e)
    if actual is None or actual["estado"] != "rebotado":
        raise ErrorMarketing("Ese correo no está marcado como rebotado.")
    if not motivo:
        raise ErrorMarketing("Anota por qué se reactiva.")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE marketing_contactos SET estado = 'consentido', evidencia = ?, actualizado_en = ? WHERE tenant_id = ? AND email = ?",
                     (f"{actual['evidencia']} · Reactivado tras rebote: {motivo}"[:500], _ahora(), tenant_id, e))
        auditoria.registrar(tenant_id, usuario_id, "marketing.reactivar", "marketing_contacto", e, {"motivo": motivo}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return obtener_contacto(tenant_id, e)


def parsear_dsn(crudo: bytes) -> list[dict]:
    """Los rebotes de un mensaje de informe de entrega (RFC 3464, `multipart/report`): `[{email, estado, accion, detalle, tipo}]`. Cualquier otro mensaje (respuesta automática, «fuera de la
    oficina», correo normal) da `[]`: solo cuenta lo que el servidor de correo declara como fallo de entrega. `tipo` es «duro» para 5.x.x con acción failed y «blando» para 4.x.x o retrasos."""
    from email import policy
    from email.parser import BytesParser
    try:
        m = BytesParser(policy=policy.default).parsebytes(crudo)
    except Exception:       # noqa: BLE001 -- un mensaje ilegible no es un rebote
        return []
    if m.get_content_type() != "multipart/report" or m.get_param("report-type") != "delivery-status":
        return []
    salida = []
    for parte in m.walk():
        if parte.get_content_type() != "message/delivery-status":
            continue
        for grupo in parte.get_payload():                       # el primero describe el mensaje; los siguientes, a cada destinatario
            final = grupo.get("Final-Recipient") or grupo.get("Original-Recipient")
            if not final:
                continue
            email = str(final).split(";", 1)[-1].strip().strip("<>").lower()
            estado = str(grupo.get("Status") or "").strip()
            accion = str(grupo.get("Action") or "").strip().lower()
            detalle = str(grupo.get("Diagnostic-Code") or "").strip()
            if accion not in ("failed", "delayed") or not _EMAIL.match(email):
                continue
            salida.append({"email": email, "estado": estado, "accion": accion, "detalle": detalle, "tipo": "duro" if accion == "failed" and estado.startswith("5") else "blando"})
    return salida


def _tenant_y_envio_de(email: str) -> tuple[int, int] | None:
    """A qué despacho (y envío) pertenece un rebote: el último envío que SALIÓ hacia ese correo."""
    with contexto.como_plataforma():
        conn = db.get_connection(plataforma=True)
        try:
            f = conn.execute("SELECT tenant_id, envio_id FROM marketing_envio_destinatarios WHERE email = ? AND estado = 'enviado' ORDER BY enviado_en DESC, envio_id DESC LIMIT 1", (email,)).fetchone()
        finally:
            conn.close()
    return (f["tenant_id"], f["envio_id"]) if f else None


def procesar_rebotes_de(crudo: bytes, *, ahora: datetime | None = None) -> int:
    """Registra los rebotes de UN mensaje (los de correos que no enviamos nosotros se ignoran). Devuelve cuántos registró."""
    n = 0
    for r in parsear_dsn(crudo):
        destino = _tenant_y_envio_de(r["email"])
        if destino is None:
            continue
        with contexto.en_despacho(destino[0]):
            registrar_rebote(destino[0], r["email"], tipo=r["tipo"], codigo=r["estado"], detalle=r["detalle"], origen="dsn", envio_id=destino[1], ahora=ahora)
        n += 1
    return n


def buzon_de_rebotes_configurado() -> bool:
    return all(os.environ.get(v) for v in ("MARKETING_IMAP_HOST", "MARKETING_IMAP_USUARIO", "MARKETING_IMAP_CONTRASENA"))


def revisar_buzon_de_rebotes(*, imap=None, maximo: int = 200) -> dict:
    """Lee los mensajes sin leer del buzón donde llegan los rebotes (`MARKETING_IMAP_*`), registra los rebotes y los marca como leídos. `imap` permite probarlo sin servidor."""
    import imaplib
    if imap is None:
        if not buzon_de_rebotes_configurado():
            return {"leidos": 0, "rebotes": 0, "sin_buzon": True}
        imap = imaplib.IMAP4_SSL(os.environ["MARKETING_IMAP_HOST"], int(os.environ.get("MARKETING_IMAP_PUERTO", "993")))
        imap.login(os.environ["MARKETING_IMAP_USUARIO"], os.environ["MARKETING_IMAP_CONTRASENA"])
    leidos = rebotes = 0
    try:
        imap.select(os.environ.get("MARKETING_IMAP_CARPETA", "INBOX"))
        _estado, datos = imap.search(None, "UNSEEN")
        for num in (datos[0].split() if datos and datos[0] else [])[:maximo]:
            _estado, partes = imap.fetch(num, "(RFC822)")
            crudo = next((p[1] for p in partes if isinstance(p, tuple)), b"")
            rebotes += procesar_rebotes_de(crudo)
            imap.store(num, "+FLAGS", "\\Seen")
            leidos += 1
    finally:
        try:
            imap.logout()
        except Exception:       # noqa: BLE001
            pass
    return {"leidos": leidos, "rebotes": rebotes}


# --- Canales de envío: Brevo y Mailchimp ----------------------------------------------------------------------------------------

def _clase_proveedor(proveedor: str):
    from . import marketing_proveedores
    if proveedor not in marketing_proveedores.PROVEEDORES:
        raise ErrorMarketing("Ese canal no existe.")
    return marketing_proveedores.PROVEEDORES[proveedor]


def obtener_proveedor(tenant_id: int, proveedor: str) -> dict | None:
    """La configuración de un canal; la clave NUNCA sale de aquí entera (`clave_final` son sus últimos caracteres, para reconocerla)."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM marketing_proveedores WHERE tenant_id = ? AND proveedor = ?", (tenant_id, proveedor)).fetchone()
    finally:
        conn.close()
    if f is None:
        return None
    d = dict(f)
    d["ajustes"] = json.loads(d["ajustes"] or "{}")
    d["clave_final"] = d["clave"][-4:]
    return d


def listar_proveedores(tenant_id: int) -> list[dict]:
    from . import marketing_proveedores
    return [{"proveedor": k, "nombre": n, "config": obtener_proveedor(tenant_id, k)} for k, n in marketing_proveedores.NOMBRES.items()]


def guardar_proveedor(tenant_id: int, usuario_id: int, proveedor: str, clave: str, ajustes: dict) -> None:
    """Guarda la clave y los ajustes de un canal (solo la dirección). Una clave en blanco conserva la anterior. Cualquier cambio exige volver a probar la conexión."""
    _exigir_direccion(usuario_id, "configura los canales de envío")
    _clase_proveedor(proveedor)
    actual = obtener_proveedor(tenant_id, proveedor)
    clave = (clave or "").strip()
    if not clave and actual is None:
        raise ErrorMarketing("Indica la clave de la cuenta.")
    limpios = {k: re.sub(r"\s+", " ", str((ajustes or {}).get(k) or "")).strip()[:200] for k in ("remitente_nombre", "remitente_email", "audiencia_id", "carpeta_id")}
    if limpios["remitente_email"]:
        normalizar_email(limpios["remitente_email"])
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO marketing_proveedores (tenant_id, proveedor, clave, ajustes, verificado_en, actualizado_en, actualizado_por) VALUES (?, ?, ?, ?, NULL, ?, ?) "
                     "ON CONFLICT (tenant_id, proveedor) DO UPDATE SET clave = excluded.clave, ajustes = excluded.ajustes, verificado_en = NULL, actualizado_en = excluded.actualizado_en, actualizado_por = excluded.actualizado_por",
                     (tenant_id, proveedor, clave or actual["clave"], json.dumps(limpios, ensure_ascii=False), _ahora(), usuario_id))
        auditoria.registrar(tenant_id, usuario_id, "marketing.canal.guardar", "marketing_proveedor", proveedor, {"cambia_clave": bool(clave)}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def quitar_proveedor(tenant_id: int, usuario_id: int, proveedor: str) -> None:
    _exigir_direccion(usuario_id, "configura los canales de envío")
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM marketing_proveedores WHERE tenant_id = ? AND proveedor = ?", (tenant_id, proveedor))
        auditoria.registrar(tenant_id, usuario_id, "marketing.canal.quitar", "marketing_proveedor", proveedor, conn=conn)
        conn.commit()
    finally:
        conn.close()


def _instancia(tenant_id: int, proveedor: str, proveedores: dict | None = None):
    if proveedores and proveedor in proveedores:
        return proveedores[proveedor]
    cfg = obtener_proveedor(tenant_id, proveedor)
    if cfg is None:
        raise ErrorMarketing("Ese canal no está configurado.")
    return _clase_proveedor(proveedor)(cfg["clave"], cfg["ajustes"])


def probar_proveedor(tenant_id: int, usuario_id: int, proveedor: str, *, proveedores: dict | None = None) -> str:
    """Comprueba la clave contra el proveedor y, si responde, deja el canal listo para usar. Devuelve el nombre de la cuenta."""
    from .marketing_proveedores import ErrorProveedor
    _exigir_direccion(usuario_id, "configura los canales de envío")
    try:
        cuenta = _instancia(tenant_id, proveedor, proveedores).verificar()
    except ErrorProveedor as e:
        raise ErrorMarketing(str(e)) from e
    conn = db.get_connection()
    try:
        conn.execute("UPDATE marketing_proveedores SET verificado_en = ? WHERE tenant_id = ? AND proveedor = ?", (_ahora(), tenant_id, proveedor))
        conn.commit()
    finally:
        conn.close()
    return cuenta


def _procesar_envio_proveedor(e: dict, t: str, totales: dict, proveedores: dict | None) -> None:
    """Entrega un envío ENTERO a su proveedor. Vuelve a comprobar el consentimiento de cada destinatario antes de subirlo. Si algo falla el envío se CANCELA y no se reintenta solo: el proveedor podría
    haber enviado ya, y repetirlo duplicaría correos a clientes."""
    from .marketing_proveedores import ErrorProveedor
    conn = db.get_connection()
    try:
        conn.execute("UPDATE marketing_envios SET estado = 'enviando', iniciado_en = COALESCE(iniciado_en, ?) WHERE id = ?", (t, e["id"]))
        pendientes = [dict(f) for f in conn.execute("SELECT * FROM marketing_envio_destinatarios WHERE envio_id = ? AND estado = 'pendiente' ORDER BY email", (e["id"],)).fetchall()]
        conn.commit()
    finally:
        conn.close()
    vigentes, omitidos = [], []
    for p in pendientes:
        c = obtener_contacto(e["tenant_id"], p["email"])
        (vigentes if c and c["estado"] == "consentido" else omitidos).append(p)
    error = None
    ref = None
    try:
        prov = _instancia(e["tenant_id"], e["canal"], proveedores)
        d = _datos_del_despacho(e["tenant_id"])
        valores = dict(prov.etiquetas, empresa=d["nombre"])
        if not vigentes:
            raise ErrorProveedor("Ningún destinatario conserva el consentimiento.")
        ref = prov.enviar(e["nombre"], _sustituir(e["asunto"], valores), render_html(e["bloques"], valores, d), [{"email": p["email"], "nombre": p["nombre"]} for p in vigentes])
    except (ErrorProveedor, ErrorMarketing) as err:
        error = str(err)[:300]
    conn = db.get_connection()
    try:
        if error is None:
            conn.executemany("UPDATE marketing_envio_destinatarios SET estado = 'enviado', enviado_en = ? WHERE envio_id = ? AND email = ?", [(t, e["id"], p["email"]) for p in vigentes])
        conn.executemany("UPDATE marketing_envio_destinatarios SET estado = 'omitido', error = ? WHERE envio_id = ? AND email = ?",
                         [(("sin consentimiento" if error is None else "envío cancelado"), e["id"], p["email"]) for p in (omitidos if error is None else omitidos + vigentes)])
        if error is None:
            conn.execute("UPDATE marketing_envios SET estado = 'enviado', enviados = ?, proveedor_ref = ?, proveedor_estado = 'entregado_al_proveedor', terminado_en = ? WHERE id = ?",
                         (len(vigentes), json.dumps(ref), t, e["id"]))
            totales["enviados"] += len(vigentes)
            totales["omitidos"] += len(omitidos)
        else:
            conn.execute("UPDATE marketing_envios SET estado = 'cancelado', ultimo_error = ?, errores = ?, terminado_en = ? WHERE id = ?", (error, len(vigentes), t, e["id"]))
            totales["errores"] += len(vigentes)
        auditoria.registrar(e["tenant_id"], None, "marketing.envio.proveedor", "marketing_envio", e["id"], {"canal": e["canal"], "enviados": 0 if error else len(vigentes), "error": error}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def sincronizar_proveedores(*, proveedores: dict | None = None, dias: int = 60, ahora: datetime | None = None) -> dict:
    """Trae de Brevo y Mailchimp las bajas y los rebotes de los envíos recientes y los aplica al registro de consentimientos: lo que se da de baja allí queda de baja aquí."""
    from datetime import timedelta
    from .marketing_proveedores import ErrorProveedor
    desde = _ahora((ahora or datetime.now()) - timedelta(days=dias))
    with contexto.como_plataforma():
        conn = db.get_connection(plataforma=True)
        try:
            envios = [_envio(f) for f in conn.execute("SELECT * FROM marketing_envios WHERE canal <> 'propio' AND estado = 'enviado' AND proveedor_ref IS NOT NULL AND terminado_en >= ? ORDER BY id", (desde,)).fetchall()]
        finally:
            conn.close()
    r = {"envios": 0, "bajas": 0, "rebotes": 0, "errores": 0}
    for e in envios:
        with contexto.en_despacho(e["tenant_id"]):
            try:
                resultado = _instancia(e["tenant_id"], e["canal"], proveedores).bajas(json.loads(e["proveedor_ref"]))
            except (ErrorProveedor, ErrorMarketing):
                r["errores"] += 1
                continue
            r["envios"] += 1
            for correo in resultado["baja"]:
                actual = obtener_contacto(e["tenant_id"], correo)
                if actual is not None and actual["estado"] == "consentido":
                    registrar_baja(e["tenant_id"], None, correo, origen="proveedor", motivo=f"Baja en {e['canal']} (envío {e['id']})")
                    r["bajas"] += 1
            for correo in resultado["rebotado"]:
                actual = obtener_contacto(e["tenant_id"], correo)
                if actual is not None and actual["estado"] == "consentido":
                    registrar_rebote(e["tenant_id"], correo, tipo="duro", detalle=f"Rebote en {e['canal']}", origen="proveedor", envio_id=e["id"])
                    r["rebotes"] += 1
    return r
