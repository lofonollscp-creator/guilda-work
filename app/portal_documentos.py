"""«Mis documentos»: el espacio permanente de documentos entre el cliente y su gestoría (contratos, escrituras, seguros, nóminas, extractos…), con carpetas, búsqueda y fecha de caducidad opcional.

Sobre el expediente documental que ya existe (`cliente_documentos`): un documento solo se ve en el portal si está marcado como visible (lo que sube el cliente, o lo que la gestoría decide compartir con él), así que lo interno —correos
archivados, documentos de trabajo— nunca sale. Al subir, el documento se coloca solo en su carpeta según su nombre y su texto (reglas sencillas y locales, sin IA ni envío a terceros); el cliente puede cambiarla. El texto se
guarda para poder buscar **solo si el documento no está cifrado** (con el cifrado del despacho activado no se guarda nada en claro). Lo que sube el cliente lo puede borrar él; lo que deja la gestoría, no."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta

from flask_babel import lazy_gettext as _l

from . import almacen_documentos, db

CARPETAS: dict[str, dict] = {
    "identidad": {"nombre": _l("Identidad"), "palabras": ("dni", "nie", "pasaporte", "identidad", "carnet de conducir", "tarjeta de residencia", "tarjeta nif", "tarjeta de identificacion")},
    "sociedad": {"nombre": _l("Sociedad y escrituras"), "palabras": ("escritura", "estatutos", "constitucion", "poderes", "acta de junta", "junta general", "registro mercantil", "cuentas anuales", "libro de socios")},
    "laboral": {"nombre": _l("Trabajadores y Seguridad Social"), "palabras": ("nomina", "finiquito", "seguridad social", "rlc", "rnt", "tc2", "contrato de trabajo", "alta trabajador", "baja trabajador", "vida laboral", "trabajador")},
    "seguros": {"nombre": _l("Seguros"), "palabras": ("seguro", "poliza", "aseguradora", "recibo del seguro")},
    "bancos": {"nombre": _l("Bancos y préstamos"), "palabras": ("extracto", "banco", "iban", "prestamo", "hipoteca", "leasing", "renting", "tarjeta de credito", "cuenta corriente")},
    "contratos": {"nombre": _l("Contratos y alquileres"), "palabras": ("contrato", "arrendamiento", "alquiler", "acuerdo", "convenio", "presupuesto aceptado")},
    "impuestos": {"nombre": _l("Impuestos y Hacienda"), "palabras": ("modelo ", "hacienda", "aeat", "irpf", "iva", "renta", "declaracion", "requerimiento", "notificacion", "agencia tributaria", "certificado tributario", "censo")},
    "otros": {"nombre": _l("Otros"), "palabras": ()},
}
CARPETA_POR_DEFECTO = "otros"
MAX_TEXTO = 8000
MAX_ARCHIVOS = 10
DIAS_AVISO = 30
TIPOS_EN_LINEA = ("application/pdf", "image/png", "image/jpeg", "image/webp")


def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(t or "").lower()) if unicodedata.category(c) != "Mn")


def clasificar(nombre: str, texto: str = "") -> str:
    """La carpeta que mejor encaja con el nombre (que pesa más) y el principio del texto. «otros» si nada encaja."""
    n = _sin_tildes(re.sub(r"[_\-.]+", " ", nombre or "")) + " "
    cuerpo = _sin_tildes(texto)[:2000]
    for sitio in (n, cuerpo):
        for clave, d in CARPETAS.items():
            if any(re.search(r"(?<![a-z0-9])" + re.escape(p.strip()) + (r"(?![a-z0-9])" if not p.endswith(" ") else ""), sitio) for p in d["palabras"]):
                return clave
    return CARPETA_POR_DEFECTO


def _texto_buscable(contenido: bytes, mime: str) -> str:
    """El texto de la capa de texto de un PDF, sin tildes ni mayúsculas, para buscar. Vacío si es una imagen o un escaneo (no se hace OCR aquí)."""
    if not (mime == "application/pdf" or contenido[:5] == b"%PDF-"):
        return ""
    from . import pdf_facturas
    paginas = pdf_facturas.texto_de_paginas(contenido) or []
    return re.sub(r"\s+", " ", _sin_tildes(" ".join(paginas)))[:MAX_TEXTO]


def _fecha_o_none(v) -> str | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise ValueError("Escribe una fecha válida.") from None


def _marcar(conn, tenant_id: int, documento_id: int, carpeta: str, origen: str, vence: str | None, texto: str) -> None:
    conn.execute("UPDATE cliente_documentos SET portal_visible = 1, portal_carpeta = ?, portal_origen = ?, portal_vence = ?, portal_texto = ? WHERE id = ? AND tenant_id = ?",
                 (carpeta, origen, vence, texto if not _cifrado(conn, tenant_id, documento_id) else "", documento_id, tenant_id))


def _cifrado(conn, tenant_id: int, documento_id: int) -> bool:
    f = conn.execute("SELECT cifrado FROM cliente_documentos WHERE id = ? AND tenant_id = ?", (documento_id, tenant_id)).fetchone()
    return bool(f and f["cifrado"])


def _aviso(resultado: str, nombre: str) -> str:
    """Por qué un archivo no entró, ya en el idioma de quien lo mira."""
    from flask_babel import gettext as _
    n = nombre[:80]
    return {"duplicado": _("«%(n)s» ya está en tus documentos.", n=n), "vacio": _("«%(n)s» está vacío.", n=n), "grande": _("«%(n)s» pesa demasiado.", n=n),
            "limite": _("Has llegado al máximo de documentos."), "clave_privada": _("«%(n)s» contiene una clave privada y no se puede guardar aquí.", n=n)}.get(resultado, _("No se pudo guardar «%(n)s».", n=n))


def subir(cliente, archivos: list[tuple[str, str | None, bytes]], carpeta: str | None = None, vence: str | None = None) -> dict:
    """Guarda lo que sube el cliente: {subidos: [ids], avisos: [mensajes]}. Cada archivo se coloca solo en su carpeta si no se elige una. `ValueError` si la fecha no vale o no hay archivos."""
    if carpeta and carpeta not in CARPETAS:
        raise ValueError("Esa carpeta no existe.")
    vence = _fecha_o_none(vence)
    archivos = [a for a in archivos if a and a[0]][:MAX_ARCHIVOS]
    if not archivos:
        raise ValueError("Elige al menos un archivo.")
    res = {"subidos": [], "avisos": []}
    for nombre, mime, contenido in archivos:
        r, doc_id = almacen_documentos.guardar_de_cliente_fiscal_sin_usuario(cliente["tenant_id"], cliente["id"], nombre, mime, contenido)
        origen = "cliente"
        if r == "duplicado":
            conn = db.get_connection()
            try:
                fila = conn.execute("SELECT portal_visible FROM cliente_documentos WHERE id = ? AND tenant_id = ?", (doc_id, cliente["tenant_id"])).fetchone()
            finally:
                conn.close()
            if fila is not None and fila["portal_visible"]:
                res["avisos"].append(_aviso("duplicado", nombre))
                continue
            origen = "despacho"                                   # ya estaba en el expediente (no lo subió el cliente): ahora se ve, pero no lo puede borrar
        elif r != "ok":
            res["avisos"].append(_aviso(r, nombre))
            continue
        texto = _texto_buscable(contenido, (mime or "").lower())
        conn = db.get_connection()
        try:
            _marcar(conn, cliente["tenant_id"], doc_id, carpeta or clasificar(nombre, texto), origen, vence, texto)
            conn.commit()
        finally:
            conn.close()
        res["subidos"].append(doc_id)
    return res


def compartir_con_cliente(tenant_id: int, cliente_fiscal_id: int, documento_id: int, carpeta: str | None = None, vence: str | None = None) -> bool:
    """La gestoría hace visible para el cliente un documento de su expediente (en la carpeta que elija o la que le toque). False si el documento no es de ese cliente."""
    if carpeta and carpeta not in CARPETAS:
        raise ValueError("Esa carpeta no existe.")
    vence = _fecha_o_none(vence)
    d = almacen_documentos.datos_de_cliente_fiscal(tenant_id, cliente_fiscal_id, documento_id)
    if d is None:
        return False
    conn = db.get_connection()
    try:
        _marcar(conn, tenant_id, documento_id, carpeta or clasificar(d["nombre_archivo"]), "despacho", vence, "")
        conn.commit()
    finally:
        conn.close()
    return True


def ocultar(tenant_id: int, cliente_fiscal_id: int, documento_id: int) -> bool:
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE cliente_documentos SET portal_visible = 0 WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?", (documento_id, tenant_id, cliente_fiscal_id)).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()


def listar(cliente, carpeta: str | None = None, q: str = "") -> list[dict]:
    """Los documentos visibles del cliente (el más reciente primero), opcionalmente de una carpeta y filtrados por una búsqueda en el nombre o el texto."""
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute("SELECT id, nombre_archivo, nombre_cifrado, tipo_mime, tamano_bytes, portal_carpeta, portal_origen, portal_vence, creado_en FROM cliente_documentos "
                                              "WHERE tenant_id = ? AND cliente_fiscal_id = ? AND portal_visible = 1 ORDER BY creado_en DESC, id DESC LIMIT 1000", (cliente["tenant_id"], cliente["id"])).fetchall()]
        por_texto: set[int] = set()
        qn = _sin_tildes(q).strip()
        if qn:
            por_texto = {f["id"] for f in conn.execute("SELECT id FROM cliente_documentos WHERE tenant_id = ? AND cliente_fiscal_id = ? AND portal_visible = 1 AND portal_texto LIKE ?",
                                                      (cliente["tenant_id"], cliente["id"], f"%{qn}%")).fetchall()}
    finally:
        conn.close()
    nombres = {d["id"]: d["nombre_archivo"] for d in almacen_documentos.listar_de_cliente_fiscal(cliente["tenant_id"], cliente["id"], 1000)}
    salida = []
    for f in filas:
        f["nombre"] = nombres.get(f["id"], f["nombre_archivo"])
        f["carpeta"] = f["portal_carpeta"] if f["portal_carpeta"] in CARPETAS else CARPETA_POR_DEFECTO
        if carpeta and f["carpeta"] != carpeta:
            continue
        if qn and qn not in _sin_tildes(f["nombre"]) and f["id"] not in por_texto:
            continue
        f["en_linea"] = (f["tipo_mime"] or "").lower().split(";")[0] in TIPOS_EN_LINEA
        f["borrable"] = f["portal_origen"] == "cliente"
        salida.append(f)
    return salida


def cuentas(cliente) -> dict[str, int]:
    """Cuántos documentos visibles hay en cada carpeta."""
    c = {k: 0 for k in CARPETAS}
    for d in listar(cliente):
        c[d["carpeta"]] += 1
    return c


def abrir(cliente, documento_id: int) -> dict | None:
    """El documento visible con su contenido (`DespachoBloqueado` si está cifrado y el despacho está bloqueado), o None si no existe o no es visible."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT portal_visible FROM cliente_documentos WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?", (documento_id, cliente["tenant_id"], cliente["id"])).fetchone()
    finally:
        conn.close()
    if f is None or not f["portal_visible"]:
        return None
    return almacen_documentos.leer_de_cliente_fiscal(cliente["tenant_id"], cliente["id"], documento_id)


def mover(cliente, documento_id: int, carpeta: str | None, vence: str | None) -> bool:
    """Cambia la carpeta y/o la caducidad de un documento visible (el cliente puede con cualquiera; es solo cómo lo ordena)."""
    if carpeta and carpeta not in CARPETAS:
        raise ValueError("Esa carpeta no existe.")
    vence = _fecha_o_none(vence)
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE cliente_documentos SET portal_carpeta = COALESCE(?, portal_carpeta), portal_vence = ? WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ? AND portal_visible = 1",
                         (carpeta or None, vence, documento_id, cliente["tenant_id"], cliente["id"])).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()


def borrar(cliente, documento_id: int) -> bool:
    """El cliente borra lo que él subió; lo que dejó la gestoría no se puede borrar desde el portal (se puede ocultar desde el despacho)."""
    conn = db.get_connection()
    try:
        n = conn.execute("DELETE FROM cliente_documentos WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ? AND portal_visible = 1 AND portal_origen = 'cliente'", (documento_id, cliente["tenant_id"], cliente["id"])).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()


def por_vencer(cliente, hoy: date | None = None, dias: int = DIAS_AVISO) -> list[dict]:
    """Documentos visibles que caducan en los próximos `dias` días (o ya han caducado hace poco): [{id, nombre, vence, dias}], los más urgentes primero."""
    hoy = hoy or date.today()
    limite = (hoy + timedelta(days=dias)).isoformat()
    desde = (hoy - timedelta(days=60)).isoformat()
    res = []
    for d in listar(cliente):
        if d["portal_vence"] and desde <= d["portal_vence"] <= limite:
            res.append({"id": d["id"], "nombre": d["nombre"], "carpeta": d["carpeta"], "vence": d["portal_vence"], "dias": (date.fromisoformat(d["portal_vence"]) - hoy).days})
    return sorted(res, key=lambda x: x["dias"])
