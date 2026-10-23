"""Adjuntos privados del asistente jurídico: documentos que una persona del despacho aporta a una consulta (hechos), nunca autoridad jurídica ni corpus común.

- Formatos: TXT, DOCX (sin macros) y PDF con texto (si está instalado `pypdf`; si no, se rechaza con un mensaje claro). Un PDF escaneado sin texto se rechaza («sin OCR»): no hay motor de OCR configurado.
- Límites propios y configurables (no son de ningún proveedor): 20 MB por archivo, 100 páginas, 5 archivos por consulta.
- El tipo se decide por el CONTENIDO (firma del archivo), no por la extensión ni por el tipo que declara el navegador. Un DOCX con expansión descontrolada (zip bomb) o con macros se rechaza.
- Antivirus (ClamAV) si está configurado; si el antivirus está configurado y falla, se rechaza (mismo criterio que el portal del cliente).
- **Minimización**: no se guarda el archivo original, solo el texto extraído por fragmentos con su localizador (página o fragmento). Se borra al vencer la retención (`LEGAL_AI_RETENCION_DIAS`, 90 por defecto) o cuando alguien lo borra, con sus fragmentos e índice.
- Permisos: el cliente/expediente al que se asocia debe ser visible para quien sube; en cada consulta se revalidan los ids (un adjunto conocido por id no da acceso).
- Su texto lo ve el modelo de IA del usuario como DATOS: nunca como instrucciones."""
from __future__ import annotations

import hashlib
import io
import os
import re
import zipfile
from datetime import date, datetime, timedelta

from lxml import etree

from .. import acceso, antivirus, db, nucleo
from . import corpus

MAX_BYTES = int(os.environ.get("LEGAL_AI_MAX_BYTES", 20 * 1024 * 1024))
MAX_PAGINAS = int(os.environ.get("LEGAL_AI_MAX_PAGINAS", 100))
MAX_POR_CONSULTA = 5
MAX_DESCOMPRIMIDO = 60 * 1024 * 1024
MAX_ENTRADAS_ZIP = 3000
MAX_CARACTERES_TEXTO = 2_000_000
RETENCION_DIAS = int(os.environ.get("LEGAL_AI_RETENCION_DIAS", 90))
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class ErrorAdjunto(ValueError):
    """El adjunto no se acepta o no se puede usar; el texto es apto para enseñárselo a la persona. `codigo` es estable para programas."""

    def __init__(self, mensaje: str, codigo: str = "adjunto_invalido"):
        super().__init__(mensaje)
        self.codigo = codigo


def detectar_tipo(contenido: bytes) -> str:
    """pdf | docx | txt, por el contenido. Cualquier otra cosa se rechaza."""
    if contenido[:5] == b"%PDF-":
        return "pdf"
    if contenido[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(contenido)) as z:
                nombres = set(z.namelist())
        except zipfile.BadZipFile:
            raise ErrorAdjunto("El archivo está dañado.", "archivo_corrupto") from None
        if "word/document.xml" in nombres and "[Content_Types].xml" in nombres:
            return "docx"
        raise ErrorAdjunto("Solo se admiten documentos de Word (.docx), PDF con texto y texto plano.", "tipo_no_admitido")
    if b"\x00" in contenido[:4096]:
        raise ErrorAdjunto("Solo se admiten documentos de Word (.docx), PDF con texto y texto plano.", "tipo_no_admitido")
    try:
        contenido[:200000].decode("utf-8")
    except UnicodeDecodeError:
        try:
            contenido[:200000].decode("latin-1")
        except UnicodeDecodeError:
            raise ErrorAdjunto("No se reconoce el formato del archivo.", "tipo_no_admitido") from None
    return "txt"


def _texto_txt(contenido: bytes) -> list[tuple[str, str]]:
    try:
        texto = contenido.decode("utf-8")
    except UnicodeDecodeError:
        texto = contenido.decode("latin-1")
    return [("", texto)]


def _texto_docx(contenido: bytes) -> list[tuple[str, str]]:
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        infos = z.infolist()
        if len(infos) > MAX_ENTRADAS_ZIP or sum(i.file_size for i in infos) > MAX_DESCOMPRIMIDO:
            raise ErrorAdjunto("El documento se expande demasiado: no se puede procesar con seguridad.", "expansion_excesiva")
        if any(i.filename.lower().endswith("vbaproject.bin") for i in infos):
            raise ErrorAdjunto("El documento contiene macros: no se admite.", "macros")
        if z.getinfo("word/document.xml").file_size > 40 * 1024 * 1024:
            raise ErrorAdjunto("El documento es demasiado grande para procesarlo.", "expansion_excesiva")
        xml = z.read("word/document.xml")
    try:
        raiz = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, load_dtd=False))
    except etree.XMLSyntaxError:
        raise ErrorAdjunto("El documento está dañado.", "archivo_corrupto") from None
    parrafos = []
    for p in raiz.iter(f"{_W}p"):
        t = "".join(x.text or "" for x in p.iter(f"{_W}t")).strip()
        if t:
            parrafos.append(t)
    return [("", "\n".join(parrafos))]


def _texto_pdf(contenido: bytes) -> list[tuple[str, str]]:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ErrorAdjunto("Este servidor todavía no puede leer PDF (falta el lector). Sube el documento en Word o texto, o pídele al administrador que lo active.", "pdf_no_soportado") from None
    try:
        lector = PdfReader(io.BytesIO(contenido))
        if lector.is_encrypted:
            raise ErrorAdjunto("El PDF está protegido con contraseña.", "pdf_protegido")
        n = len(lector.pages)
        if n > MAX_PAGINAS:
            raise ErrorAdjunto(f"El documento tiene {n} páginas; el máximo es {MAX_PAGINAS}.", "demasiadas_paginas")
        paginas = [(f"Página {i}", (p.extract_text() or "").strip()) for i, p in enumerate(lector.pages, 1)]
    except ErrorAdjunto:
        raise
    except Exception:  # noqa: BLE001
        raise ErrorAdjunto("No se ha podido leer el PDF (puede estar dañado).", "archivo_corrupto") from None
    if sum(len(t) for _l, t in paginas) < 20 * max(1, n):
        raise ErrorAdjunto("El PDF parece escaneado (sin texto) y este servidor no tiene OCR: sube una versión con texto.", "sin_texto_ocr_requerido")
    return paginas


def extraer(contenido: bytes) -> tuple[str, list[tuple[str, str]]]:
    """(tipo, [(etiqueta, texto)]) del archivo. Lanza `ErrorAdjunto` si no es utilizable."""
    tipo = detectar_tipo(contenido)
    partes = {"txt": _texto_txt, "docx": _texto_docx, "pdf": _texto_pdf}[tipo](contenido)
    if sum(len(t) for _l, t in partes) > MAX_CARACTERES_TEXTO:
        raise ErrorAdjunto("El documento tiene demasiado texto para procesarlo.", "demasiado_texto")
    if not any(t.strip() for _l, t in partes):
        raise ErrorAdjunto("El documento no tiene texto.", "sin_texto")
    return tipo, partes


def _fragmentar(partes: list[tuple[str, str]]) -> list[tuple[str, str]]:
    salida, n = [], 0
    for etiqueta, texto in partes:
        trozos = corpus.partir_parrafos(re.sub(r"[ \t]+", " ", texto), 1800)
        for i, t in enumerate(trozos, 1):
            n += 1
            loc = (etiqueta if len(trozos) == 1 else f"{etiqueta} (parte {i}/{len(trozos)})") if etiqueta else f"Fragmento {n}"
            salida.append((loc, t))
    return salida


def _comprobar_destino(tenant_id: int, usuario_id: int, cliente_id: int | None, expediente_id: int | None) -> int | None:
    """Devuelve el cliente efectivo. Un expediente solo se asocia si la persona puede verlo, y su cliente manda."""
    if expediente_id is not None:
        exp = nucleo.obtener_expediente(tenant_id, expediente_id, usuario_id, acceso.es_directivo(usuario_id))
        if exp is None:
            raise ErrorAdjunto("No encuentras ese expediente.", "no_encontrado")
        if cliente_id is not None and cliente_id != exp["cliente_id"]:
            raise ErrorAdjunto("El expediente no es de ese cliente.", "peticion_invalida")
        cliente_id = exp["cliente_id"]
    if cliente_id is not None and (nucleo.obtener_cliente(tenant_id, cliente_id) is None or not acceso.puede_ver_cliente_nucleo(tenant_id, usuario_id, cliente_id)):
        raise ErrorAdjunto("No encuentras ese cliente.", "no_encontrado")
    return cliente_id


def subir(tenant_id: int, usuario_id: int, nombre: str, contenido: bytes, *, cliente_id: int | None = None, expediente_id: int | None = None) -> dict:
    nombre = os.path.basename((nombre or "").strip())[:200] or "documento"
    if not contenido:
        raise ErrorAdjunto("El archivo está vacío.", "archivo_vacio")
    if len(contenido) > MAX_BYTES:
        raise ErrorAdjunto(f"El archivo supera el máximo de {MAX_BYTES // (1024 * 1024)} MB.", "archivo_grande")
    cliente_id = _comprobar_destino(tenant_id, usuario_id, cliente_id, expediente_id)
    try:
        antivirus.exigir_limpio(nombre, contenido, tenant_id)
    except antivirus.ArchivoRechazado as e:
        raise ErrorAdjunto(str(e), "antivirus") from e
    retener = (date.today() + timedelta(days=RETENCION_DIAS)).isoformat()
    conn = db.get_connection()
    try:
        adj = conn.execute("INSERT INTO jur_adjuntos (tenant_id, subido_por, cliente_id, expediente_id, nombre, tipo_mime, tamano, hash, estado, retener_hasta, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pendiente', ?, ?)",
                           (tenant_id, usuario_id, cliente_id, expediente_id, nombre, None, len(contenido), hashlib.sha256(contenido).hexdigest(), retener, corpus.ahora())).lastrowid
        conn.commit()
    finally:
        conn.close()
    try:
        tipo, partes = extraer(contenido)
        trozos = _fragmentar(partes)
    except ErrorAdjunto as e:
        _marcar(adj, tenant_id, "fallida", f"{e.codigo}: {e}")
        raise
    except Exception:  # noqa: BLE001 -- una extracción rota nunca tumba la petición
        _marcar(adj, tenant_id, "fallida", "extraccion_fallida")
        raise ErrorAdjunto("No se ha podido extraer el texto del archivo.", "extraccion_fallida") from None
    conn = db.get_connection()
    try:
        for orden, (loc, texto) in enumerate(trozos):
            conn.execute("INSERT INTO jur_fragmentos_privados (tenant_id, adjunto_id, orden, localizador, texto) VALUES (?, ?, ?, ?, ?)", (tenant_id, adj, orden, loc, texto))
        conn.execute("UPDATE jur_adjuntos SET estado = 'lista', tipo_mime = ?, error = NULL WHERE id = ? AND tenant_id = ?", ({"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "txt": "text/plain"}[tipo], adj, tenant_id))
        corpus.auditar(tenant_id, usuario_id, "adjunto.subir", f"adjunto:{adj}", {"tipo": tipo, "fragmentos": len(trozos)}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return obtener(tenant_id, usuario_id, adj)


def _marcar(adjunto_id: int, tenant_id: int, estado: str, error: str | None) -> None:
    conn = db.get_connection()
    try:
        conn.execute("UPDATE jur_adjuntos SET estado = ?, error = ? WHERE id = ? AND tenant_id = ?", (estado, error, adjunto_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


def _visible(tenant_id: int, usuario_id: int, fila) -> bool:
    if fila["tenant_id"] != tenant_id:
        return False
    if fila["subido_por"] == usuario_id:
        return True
    return acceso.es_directivo(usuario_id) and acceso.puede_ver_cliente_nucleo(tenant_id, usuario_id, fila["cliente_id"])


def obtener(tenant_id: int, usuario_id: int, adjunto_id: int) -> dict | None:
    """Metadatos y estado. Solo quien lo subió (o la dirección, si ve a ese cliente); nunca el texto."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT id, tenant_id, subido_por, cliente_id, expediente_id, nombre, tipo_mime, tamano, estado, error, retener_hasta, creado_en FROM jur_adjuntos WHERE id = ? AND tenant_id = ?", (adjunto_id, tenant_id)).fetchone()
        if f is None or not _visible(tenant_id, usuario_id, f):
            return None
        d = dict(f)
        d["fragmentos"] = conn.execute("SELECT COUNT(*) FROM jur_fragmentos_privados WHERE adjunto_id = ? AND tenant_id = ?", (adjunto_id, tenant_id)).fetchone()[0]
        return d
    finally:
        conn.close()


def listar(tenant_id: int, usuario_id: int, *, cliente_id: int | None = None, limite: int = 100) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT id FROM jur_adjuntos WHERE tenant_id = ?" + (" AND cliente_id = ?" if cliente_id else "") + " ORDER BY id DESC LIMIT ?", ((tenant_id, cliente_id, limite) if cliente_id else (tenant_id, limite))).fetchall()
    finally:
        conn.close()
    return [a for a in (obtener(tenant_id, usuario_id, f["id"]) for f in filas) if a]


def validar_para_consulta(tenant_id: int, usuario_id: int, ids: list[int]) -> list[int]:
    """Revalida en CADA consulta: del despacho, visibles para quien consulta, listos y no vencidos. Lanza `ErrorAdjunto` si alguno no sirve (no se descarta en silencio)."""
    ids = list(dict.fromkeys(int(i) for i in ids or []))
    if len(ids) > MAX_POR_CONSULTA:
        raise ErrorAdjunto(f"Máximo {MAX_POR_CONSULTA} archivos por consulta.", "demasiados_adjuntos")
    for i in ids:
        a = obtener(tenant_id, usuario_id, i)
        if a is None:
            raise ErrorAdjunto(f"No encuentras el adjunto {i}.", "no_encontrado")
        if a["estado"] != "lista":
            raise ErrorAdjunto(f"El adjunto «{a['nombre']}» todavía no está listo o no se pudo procesar.", "extraccion_pendiente")
        if a["retener_hasta"] and a["retener_hasta"] < date.today().isoformat():
            raise ErrorAdjunto(f"El adjunto «{a['nombre']}» ha vencido y se ha retirado.", "no_encontrado")
    return ids


def fragmentos_para(tenant_id: int, adjunto_ids: list[int], pregunta: str, maximo: int = 8) -> list[dict]:
    """Fragmentos de los adjuntos (ya validados) más pertinentes a la pregunta (FTS) y, si no hay coincidencias, los primeros de cada archivo. Siempre acotados por `tenant_id`."""
    if not adjunto_ids:
        return []
    from .busqueda import _fts_consulta, _sql_texto
    conn = db.get_connection()
    try:
        marcas = ",".join("?" for _ in adjunto_ids)
        elegidos: dict[int, dict] = {}
        fts = _fts_consulta(pregunta, "y", conn)
        if fts:
            union, cond, orden, orden_con_parametro = _sql_texto(conn, "p", "jur_fragmentos_privados_fts")
            args = [fts, tenant_id, *adjunto_ids] + ([fts] if orden_con_parametro else []) + [maximo]
            for f in conn.execute(f"SELECT p.id, p.adjunto_id, p.localizador, p.texto, a.nombre FROM jur_fragmentos_privados p JOIN jur_adjuntos a ON a.id = p.adjunto_id{union} "
                                  f"WHERE {cond} AND p.tenant_id = ? AND p.adjunto_id IN ({marcas}) ORDER BY {orden} LIMIT ?", args):
                elegidos[f["id"]] = dict(f)
        for aid in adjunto_ids:
            if len(elegidos) >= maximo:
                break
            for f in conn.execute("SELECT p.id, p.adjunto_id, p.localizador, p.texto, a.nombre FROM jur_fragmentos_privados p JOIN jur_adjuntos a ON a.id = p.adjunto_id WHERE p.tenant_id = ? AND p.adjunto_id = ? ORDER BY p.orden LIMIT 2", (tenant_id, aid)):
                elegidos.setdefault(f["id"], dict(f))
        return list(elegidos.values())[:maximo]
    finally:
        conn.close()


def borrar(tenant_id: int, usuario_id: int, adjunto_id: int) -> bool:
    """Borra el adjunto con sus fragmentos e índice. Las citas de consultas ya hechas conservan su extracto (instantánea), no el archivo."""
    a = obtener(tenant_id, usuario_id, adjunto_id)
    if a is None or (a["subido_por"] != usuario_id and not acceso.es_directivo(usuario_id)):
        return False
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM jur_fragmentos_privados WHERE adjunto_id = ? AND tenant_id = ?", (adjunto_id, tenant_id))
        conn.execute("DELETE FROM jur_adjuntos WHERE id = ? AND tenant_id = ?", (adjunto_id, tenant_id))
        corpus.auditar(tenant_id, usuario_id, "adjunto.borrar", f"adjunto:{adjunto_id}", None, conn=conn)
        conn.commit()
        return True
    finally:
        conn.close()


def purgar_vencidos(hoy: str | None = None) -> int:
    """Borra los adjuntos cuya retención ha vencido (con fragmentos e índice). Lo llama el mantenimiento periódico."""
    hoy = hoy or date.today().isoformat()
    conn = db.get_connection()
    try:
        ids = [(r["id"], r["tenant_id"]) for r in conn.execute("SELECT id, tenant_id FROM jur_adjuntos WHERE retener_hasta IS NOT NULL AND retener_hasta < ?", (hoy,))]
        for aid, tid in ids:
            conn.execute("DELETE FROM jur_fragmentos_privados WHERE adjunto_id = ? AND tenant_id = ?", (aid, tid))
            conn.execute("DELETE FROM jur_adjuntos WHERE id = ? AND tenant_id = ?", (aid, tid))
        conn.commit()
        return len(ids)
    finally:
        conn.close()
