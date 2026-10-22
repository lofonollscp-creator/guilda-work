"""Corpus jurídico compartido: fuentes, políticas de uso, documentos, versiones inmutables y fragmentos citables.

Reglas (ver `docs/adr-asistente-juridico.md`):
- **Política antes de cada operación.** Sin política vigente que lo permita, una fuente no almacena, no indexa, no se busca ni llega al modelo. La capacidad técnica de un conector no es un derecho de uso.
- **Publicación atómica.** Una versión nueva se inserta con sus fragmentos y se activa en UNA transacción; la anterior deja de estar activa en la misma. Una consulta nunca mezcla texto de dos versiones.
- **Identidad ≠ origen.** Un documento es `(fuente, id externo)`; ECLI, ROJ, ELI y CELEX solo se guardan si constan en la fuente, nunca se componen.
- **Vigencia tal como la da la fuente.** Si no consta, queda `NULL` (desconocida) y se explica; no se infiere de fechas de publicación."""
from __future__ import annotations

import array
import hashlib
import json
import re
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime

from .. import db

OPERACIONES = ("almacenar", "indexar", "enviar_llm", "citar", "exportar")
MAX_CARACTERES_FRAGMENTO = 3500


class ErrorCorpus(ValueError):
    """Error de negocio del corpus, con un texto apto para enseñar."""


@dataclass
class FragmentoNuevo:
    localizador: str
    texto: str
    bloque_id: str | None = None
    vigente_desde: str | None = None         # AAAA-MM-DD, tal como lo publica la fuente
    vigente_hasta: str | None = None
    vigencia_origen: str | None = None       # de dónde sale: «version_propia», «siguiente_version», None si es desconocida


@dataclass
class DocumentoNuevo:
    fuente_id: str
    id_externo: str
    coleccion: str
    titulo: str
    materia: str | None = None
    emisor: str | None = None
    territorio: str | None = None
    rango: str | None = None
    tipo: str | None = None
    url_canonica: str | None = None
    ecli: str | None = None
    roj: str | None = None
    eli: str | None = None
    celex: str | None = None
    estado_normativo: str | None = None
    fecha_publicacion: str | None = None
    fecha_resolucion: str | None = None
    idioma: str = "es"


@dataclass
class Publicacion:
    estado: str                    # nueva | sin_cambios | bloqueada
    documento_id: int | None = None
    version_id: int | None = None
    motivo: str | None = None
    fragmentos: int = 0
    relaciones: list = field(default_factory=list)


def ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def hash_bytes(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def hash_fragmentos(fragmentos: list[FragmentoNuevo]) -> str:
    h = hashlib.sha256()
    for f in fragmentos:
        h.update(f"{f.localizador}\x1f{f.bloque_id or ''}\x1f{f.vigente_desde or ''}\x1f{f.vigente_hasta or ''}\x1f{f.texto}\x1e".encode("utf-8"))
    return h.hexdigest()


def fecha_iso(valor: str | None) -> str | None:
    """AAAAMMDD, AAAAMMDDThhmmssZ o AAAA-MM-DD -> AAAA-MM-DD; cualquier otra cosa -> None (nunca se inventa una fecha)."""
    if not valor:
        return None
    v = str(valor).strip()
    m = re.fullmatch(r"(\d{4})-?(\d{2})-?(\d{2})(?:T.*)?", v)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


# --- Fuentes y políticas ---------------------------------------------------------------------------------------------------------------------------------

def registrar_fuente(fuente_id: str, nombre: str, conector: str, coleccion: str, *, url: str | None = None, acceso: str = "explicito", conn=None) -> None:
    """Alta idempotente de una fuente en el catálogo. No la habilita: eso es una decisión humana con política registrada."""
    propia = conn is None
    conn = conn or db.get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO jur_fuentes (id, nombre, url, conector, coleccion, acceso, creada_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (fuente_id, nombre, url, conector, coleccion, acceso, ahora()))
        if propia:
            conn.commit()
    finally:
        if propia:
            conn.close()


def obtener_fuente(fuente_id: str) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM jur_fuentes WHERE id = ?", (fuente_id,)).fetchone()
        return dict(f) if f else None
    finally:
        conn.close()


def listar_fuentes() -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT * FROM jur_fuentes ORDER BY coleccion, nombre")]
    finally:
        conn.close()


def politica_vigente(fuente_id: str, conn=None) -> dict | None:
    propia = conn is None
    conn = conn or db.get_connection()
    try:
        f = conn.execute("SELECT * FROM jur_politicas WHERE fuente_id = ? ORDER BY version DESC LIMIT 1", (fuente_id,)).fetchone()
        return dict(f) if f else None
    finally:
        if propia:
            conn.close()


def registrar_politica(fuente_id: str, *, evidencia: str, almacenar: bool, indexar: bool, enviar_llm: bool, citar: bool, exportar: bool = False, atribucion: str | None = None,
                       restricciones: dict | None = None, usuario_id: int | None = None) -> int:
    """Registra una versión nueva de la política de una fuente. Exige evidencia (contrato, condiciones de reutilización con su URL…): sin ella no hay política."""
    evidencia = (evidencia or "").strip()
    if len(evidencia) < 10:
        raise ErrorCorpus("Indica la evidencia de los derechos de uso (condiciones, contrato o URL del aviso legal).")
    if (indexar or enviar_llm or citar or exportar) and not almacenar:
        raise ErrorCorpus("Para indexar, citar, exportar o enviar al modelo hace falta poder almacenar el texto.")
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM jur_fuentes WHERE id = ?", (fuente_id,)).fetchone() is None:
            raise ErrorCorpus("La fuente no existe.")
        version = (conn.execute("SELECT COALESCE(MAX(version), 0) FROM jur_politicas WHERE fuente_id = ?", (fuente_id,)).fetchone()[0]) + 1
        conn.execute(
            "INSERT INTO jur_politicas (fuente_id, version, evidencia, vigente_desde, permite_almacenar, permite_indexar, permite_enviar_llm, permite_citar, permite_exportar, atribucion, restricciones,"
            " registrada_por, registrada_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fuente_id, version, evidencia, date.today().isoformat(), int(almacenar), int(indexar), int(enviar_llm), int(citar), int(exportar), atribucion,
             json.dumps(restricciones) if restricciones else None, usuario_id, ahora()))
        auditar(None, usuario_id, "politica.registrar", f"fuente:{fuente_id}", {"version": version}, conn=conn)
        conn.commit()
        return version
    finally:
        conn.close()


def operacion_permitida(fuente_id: str, operacion: str, conn=None) -> bool:
    """¿La política vigente de la fuente permite esta operación? Sin política, no."""
    if operacion not in OPERACIONES:
        raise ErrorCorpus(f"Operación desconocida: {operacion}.")
    p = politica_vigente(fuente_id, conn=conn)
    return bool(p and p[f"permite_{operacion}"])


def habilitar_fuente(fuente_id: str, habilitada: bool, usuario_id: int | None = None) -> None:
    """Habilita o deshabilita una fuente para todo el sistema. Habilitar exige una política vigente que permita almacenar e indexar."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM jur_fuentes WHERE id = ?", (fuente_id,)).fetchone()
        if f is None:
            raise ErrorCorpus("La fuente no existe.")
        if habilitada and not (operacion_permitida(fuente_id, "almacenar", conn) and operacion_permitida(fuente_id, "indexar", conn)):
            raise ErrorCorpus("Registra antes la política de uso de la fuente (con su evidencia): tiene que permitir almacenar e indexar.")
        conn.execute("UPDATE jur_fuentes SET habilitada = ?, estado = CASE WHEN ? = 1 THEN 'activo' WHEN estado = 'activo' THEN 'pendiente' ELSE estado END WHERE id = ?",
                     (int(habilitada), int(habilitada), fuente_id))
        auditar(None, usuario_id, "fuente.habilitar" if habilitada else "fuente.deshabilitar", f"fuente:{fuente_id}", None, conn=conn)
        conn.commit()
    finally:
        conn.close()


def fijar_fuente_despacho(tenant_id: int, fuente_id: str, habilitada: bool, usuario_id: int | None = None) -> None:
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM jur_fuentes WHERE id = ?", (fuente_id,)).fetchone() is None:
            raise ErrorCorpus("La fuente no existe.")
        conn.execute("INSERT INTO jur_fuente_despacho (tenant_id, fuente_id, habilitada) VALUES (?, ?, ?) ON CONFLICT (tenant_id, fuente_id) DO UPDATE SET habilitada = excluded.habilitada",
                     (tenant_id, fuente_id, int(habilitada)))
        auditar(tenant_id, usuario_id, "fuente_despacho.fijar", f"fuente:{fuente_id}", {"habilitada": habilitada}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def fuentes_para_despacho(tenant_id: int, operacion: str = "indexar", conn=None) -> list[str]:
    """Ids de las fuentes que ESTE despacho puede usar para la operación: habilitadas globalmente, con política que la permita y accesibles al despacho
    (`acceso = todos` salvo que el despacho la desactive; `explicito` solo si el despacho la activó)."""
    propia = conn is None
    conn = conn or db.get_connection()
    try:
        out = []
        for f in conn.execute("SELECT id, acceso FROM jur_fuentes WHERE habilitada = 1"):
            if not operacion_permitida(f["id"], operacion, conn):
                continue
            fila = conn.execute("SELECT habilitada FROM jur_fuente_despacho WHERE tenant_id = ? AND fuente_id = ?", (tenant_id, f["id"])).fetchone()
            if (f["acceso"] == "todos" and (fila is None or fila["habilitada"])) or (f["acceso"] == "explicito" and fila is not None and fila["habilitada"]):
                out.append(f["id"])
        return out
    finally:
        if propia:
            conn.close()


def auditar(tenant_id: int | None, actor_id: int | None, accion: str, recurso: str | None, detalle: dict | None, conn=None) -> None:
    """Evento de auditoría mínimo: sin texto de expedientes ni de preguntas."""
    propia = conn is None
    conn = conn or db.get_connection()
    try:
        conn.execute("INSERT INTO jur_auditoria (tenant_id, actor_id, accion, recurso, detalle, creada_en) VALUES (?, ?, ?, ?, ?, ?)",
                     (tenant_id, actor_id, accion, recurso, json.dumps(detalle) if detalle else None, ahora()))
        if propia:
            conn.commit()
    finally:
        if propia:
            conn.close()


# --- Originales ----------------------------------------------------------------------------------------------------------------------------------------------

def guardar_original(fuente_id: str, contenido: bytes, url: str | None, tipo_mime: str | None, conn=None) -> str:
    """Guarda el original inmutable (comprimido) y devuelve su hash. Exige que la política permita almacenar."""
    propia = conn is None
    conn = conn or db.get_connection()
    try:
        if not operacion_permitida(fuente_id, "almacenar", conn):
            raise ErrorCorpus("La política de la fuente no permite almacenar su contenido.")
        h = hash_bytes(contenido)
        conn.execute("INSERT OR IGNORE INTO jur_originales (hash, fuente_id, url, tipo_mime, contenido, capturado_en) VALUES (?, ?, ?, ?, ?, ?)",
                     (h, fuente_id, url, tipo_mime, zlib.compress(contenido, 6), ahora()))
        if propia:
            conn.commit()
        return h
    finally:
        if propia:
            conn.close()


def leer_original(hash_original: str) -> bytes | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT contenido FROM jur_originales WHERE hash = ?", (hash_original,)).fetchone()
        return zlib.decompress(f["contenido"]) if f else None
    finally:
        conn.close()


# --- Fragmentación ---------------------------------------------------------------------------------------------------------------------------------------------

def partir_parrafos(texto: str, maximo: int = MAX_CARACTERES_FRAGMENTO) -> list[str]:
    """Parte un texto largo por límites de párrafo (nunca a mitad de una frase si se puede evitar). Un texto corto sale entero."""
    texto = (texto or "").strip()
    if len(texto) <= maximo:
        return [texto] if texto else []
    partes, actual = [], ""
    for p in [x for x in texto.split("\n") if x.strip()]:
        while len(p) > maximo:                                                      # párrafo gigante: por frases
            corte = p.rfind(". ", 0, maximo)
            corte = corte + 1 if corte > maximo // 3 else maximo
            if actual:
                partes.append(actual); actual = ""
            partes.append(p[:corte].strip())
            p = p[corte:].strip()
        if actual and len(actual) + len(p) + 1 > maximo:
            partes.append(actual); actual = ""
        actual = (actual + "\n" + p) if actual else p
    if actual:
        partes.append(actual)
    return partes


def _vector_a_bytes(v: list[float]) -> bytes:
    return array.array("f", v).tobytes()


def bytes_a_vector(b: bytes) -> list[float]:
    a = array.array("f")
    a.frombytes(b)
    return list(a)


# --- Publicación atómica ---------------------------------------------------------------------------------------------------------------------------------

def publicar(doc: DocumentoNuevo, fragmentos: list[FragmentoNuevo], *, hash_original: str | None = None, relaciones: list[dict] | None = None, embedder=None,
             calidad: str = "ok") -> Publicacion:
    """Crea (o actualiza) el documento y publica una versión nueva con sus fragmentos en una sola transacción.

    - Sin política que permita almacenar e indexar -> `bloqueada` (no se escribe nada).
    - Mismo texto que la versión activa (mismo hash) -> `sin_cambios`: un cambio solo de metadatos no crea versión de texto.
    - Sin fragmentos -> error: nunca se publica un texto vacío o incompleto como si fuera íntegro."""
    if doc.coleccion not in ("legislacion", "jurisprudencia", "doctrina"):
        raise ErrorCorpus(f"Colección desconocida: {doc.coleccion}.")
    fragmentos = [f for f in fragmentos if (f.texto or "").strip()]
    if not fragmentos:
        raise ErrorCorpus("El documento no tiene texto utilizable: no se publica.")
    h = hash_fragmentos(fragmentos)
    conn = db.get_connection()
    try:
        politica = politica_vigente(doc.fuente_id, conn)
        if not politica or not (politica["permite_almacenar"] and politica["permite_indexar"]):
            return Publicacion("bloqueada", motivo="La política de la fuente no permite almacenar e indexar.")
        conn.execute("BEGIN IMMEDIATE") if not conn.in_transaction else None
        campos = ("coleccion", "titulo", "materia", "emisor", "territorio", "rango", "tipo", "url_canonica", "ecli", "roj", "eli", "celex", "estado_normativo", "fecha_publicacion", "fecha_resolucion", "idioma")
        existente = conn.execute("SELECT id FROM jur_documentos WHERE fuente_id = ? AND id_externo = ?", (doc.fuente_id, doc.id_externo)).fetchone()
        if existente is None:
            cur = conn.execute(f"INSERT INTO jur_documentos (fuente_id, id_externo, creado_en, {', '.join(campos)}) VALUES (?, ?, ?, {', '.join('?' for _ in campos)})",
                               (doc.fuente_id, doc.id_externo, ahora(), *[getattr(doc, c) for c in campos]))
            documento_id = cur.lastrowid
        else:
            documento_id = existente["id"]
            conn.execute(f"UPDATE jur_documentos SET {', '.join(f'{c} = ?' for c in campos)} WHERE id = ?", (*[getattr(doc, c) for c in campos], documento_id))
        _resolver_relaciones_hacia(conn, documento_id, doc.id_externo)
        activa = conn.execute("SELECT id, hash_texto FROM jur_versiones WHERE documento_id = ? AND activa = 1", (documento_id,)).fetchone()
        if activa is not None and activa["hash_texto"] == h:
            _guardar_relaciones(conn, documento_id, relaciones)
            conn.commit()
            return Publicacion("sin_cambios", documento_id, activa["id"])
        anterior = conn.execute("SELECT id FROM jur_versiones WHERE documento_id = ? AND hash_texto = ?", (documento_id, h)).fetchone()
        if anterior is not None:                                                      # vuelve un texto ya visto: se reactiva esa versión, no se duplica
            conn.execute("UPDATE jur_versiones SET activa = 0 WHERE documento_id = ?", (documento_id,))
            conn.execute("UPDATE jur_versiones SET activa = 1 WHERE id = ? AND bloqueada = 0", (anterior["id"],))
            _guardar_relaciones(conn, documento_id, relaciones)
            conn.commit()
            return Publicacion("nueva", documento_id, anterior["id"], fragmentos=len(fragmentos))
        cur = conn.execute("INSERT INTO jur_versiones (documento_id, hash_texto, hash_original, fecha_publicacion, fecha_resolucion, capturada_en, calidad, politica_version, activa) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                           (documento_id, h, hash_original, doc.fecha_publicacion, doc.fecha_resolucion, ahora(), calidad, politica["version"]))
        version_id = cur.lastrowid
        modelo = getattr(embedder, "modelo", None) if embedder else None
        for orden, f in enumerate(fragmentos):
            vector = None
            if embedder is not None and politica["permite_indexar"]:
                try:
                    v = embedder(f.texto)
                    vector = _vector_a_bytes(v) if v else None
                except Exception:  # noqa: BLE001 -- el embedding es opcional: nunca impide publicar
                    vector = None
            conn.execute("INSERT INTO jur_fragmentos (version_id, orden, bloque_id, localizador, texto, hash, vigente_desde, vigente_hasta, vigencia_origen, embedding, embedding_modelo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (version_id, orden, f.bloque_id, f.localizador, f.texto, hashlib.sha256(f.texto.encode("utf-8")).hexdigest(), f.vigente_desde, f.vigente_hasta, f.vigencia_origen,
                          vector, modelo if vector else None))
        conn.execute("UPDATE jur_versiones SET activa = 0 WHERE documento_id = ? AND id <> ?", (documento_id, version_id))
        conn.execute("UPDATE jur_versiones SET activa = 1 WHERE id = ?", (version_id,))
        _guardar_relaciones(conn, documento_id, relaciones)
        conn.commit()
        return Publicacion("nueva", documento_id, version_id, fragmentos=len(fragmentos))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _resolver_relaciones_hacia(conn, documento_id: int, id_externo: str) -> None:
    """Las relaciones de otros documentos que apuntaban a este (aún no cargado) pasan a resolverse a él."""
    conn.execute("UPDATE jur_relaciones SET destino_documento_id = ? WHERE destino_externo = ? AND destino_documento_id IS NULL AND documento_id <> ?", (documento_id, id_externo, documento_id))


def _guardar_relaciones(conn, documento_id: int, relaciones: list[dict] | None) -> None:
    for r in relaciones or []:
        conn.execute("INSERT OR IGNORE INTO jur_relaciones (documento_id, destino_externo, tipo, evidencia, verificada) VALUES (?, ?, ?, ?, 0)",
                     (documento_id, r["destino_externo"], r["tipo"], (r.get("evidencia") or "")[:600] or None))
    conn.execute("UPDATE jur_relaciones SET destino_documento_id = (SELECT d.id FROM jur_documentos d WHERE d.id_externo = jur_relaciones.destino_externo LIMIT 1) "
                 "WHERE documento_id = ? AND destino_documento_id IS NULL", (documento_id,))


# --- Retirada ------------------------------------------------------------------------------------------------------------------------------------------------

def retirar(fuente_id: str, id_externo: str, motivo: str, *, purgar: bool = True, usuario_id: int | None = None) -> bool:
    """Retirada CONFIRMADA de un documento (privacidad, corrección, orden de la fuente): bloquea sus versiones al instante (dejan de recuperarse) y, con `purgar`, borra fragmentos,
    embeddings y originales. Una simple desaparición en una búsqueda NO es una orden de retirada: quien llama debe tener una señal fiable."""
    conn = db.get_connection()
    try:
        d = conn.execute("SELECT id FROM jur_documentos WHERE fuente_id = ? AND id_externo = ?", (fuente_id, id_externo)).fetchone()
        if d is None:
            return False
        conn.execute("UPDATE jur_versiones SET bloqueada = 1, activa = 0, motivo_bloqueo = ? WHERE documento_id = ?", ((motivo or "retirada")[:300], d["id"]))
        if purgar:
            hashes = [r["hash_original"] for r in conn.execute("SELECT hash_original FROM jur_versiones WHERE documento_id = ? AND hash_original IS NOT NULL", (d["id"],))]
            conn.execute("DELETE FROM jur_fragmentos WHERE version_id IN (SELECT id FROM jur_versiones WHERE documento_id = ?)", (d["id"],))
            for h in hashes:
                if conn.execute("SELECT 1 FROM jur_versiones WHERE hash_original = ? AND bloqueada = 0 LIMIT 1", (h,)).fetchone() is None:
                    conn.execute("DELETE FROM jur_originales WHERE hash = ?", (h,))
        conn.execute("UPDATE jur_registros_fuente SET estado = 'WITHDRAWN', actualizado_en = ? WHERE fuente_id = ? AND id_externo = ?", (ahora(), fuente_id, id_externo))
        conn.execute("UPDATE jur_informes SET aviso_fuente = ? WHERE instantanea LIKE ?", (f"Una fuente citada fue retirada o corregida: {(motivo or '')[:200]}", f'%"kind": "legal_source", "documentId": {d["id"]},%'))
        auditar(None, usuario_id, "documento.retirar", f"documento:{d['id']}", {"fuente": fuente_id, "purgado": purgar}, conn=conn)
        conn.commit()
        return True
    finally:
        conn.close()


# --- Cobertura -----------------------------------------------------------------------------------------------------------------------------------------------

def cobertura(fuente_id: str | None = None) -> list[dict]:
    """Lo realmente indexado por fuente: documentos, fragmentos, fechas, última carga correcta, pendientes y cuarentena. No dice «exhaustivo»: dice lo que hay."""
    conn = db.get_connection()
    try:
        filas = []
        for f in conn.execute("SELECT * FROM jur_fuentes" + (" WHERE id = ?" if fuente_id else "") + " ORDER BY coleccion, nombre", (fuente_id,) if fuente_id else ()):
            docs = conn.execute("SELECT COUNT(DISTINCT d.id) AS n, MIN(d.fecha_publicacion) AS desde, MAX(d.fecha_publicacion) AS hasta FROM jur_documentos d JOIN jur_versiones v ON v.documento_id = d.id "
                                "WHERE d.fuente_id = ? AND v.activa = 1 AND v.bloqueada = 0", (f["id"],)).fetchone()
            frags = conn.execute("SELECT COUNT(*) FROM jur_fragmentos g JOIN jur_versiones v ON v.id = g.version_id JOIN jur_documentos d ON d.id = v.documento_id "
                                 "WHERE d.fuente_id = ? AND v.activa = 1 AND v.bloqueada = 0", (f["id"],)).fetchone()[0]
            estados = {r["estado"]: r["n"] for r in conn.execute("SELECT estado, COUNT(*) AS n FROM jur_registros_fuente WHERE fuente_id = ? GROUP BY estado", (f["id"],))}
            politica = politica_vigente(f["id"], conn)
            filas.append({"fuente_id": f["id"], "nombre": f["nombre"], "coleccion": f["coleccion"], "estado": f["estado"], "habilitada": bool(f["habilitada"]), "acceso": f["acceso"],
                          "documentos": docs["n"], "fragmentos": frags, "desde": docs["desde"], "hasta": docs["hasta"], "ultimo_exito_en": f["ultimo_exito_en"],
                          "pendientes": sum(n for e, n in estados.items() if e not in ("PUBLISHED", "WITHDRAWN", "QUARANTINED", "BLOCKED_POLICY", "RETRYABLE_ERROR")),
                          "reintentables": estados.get("RETRYABLE_ERROR", 0), "cuarentena": estados.get("QUARANTINED", 0), "bloqueados": estados.get("BLOCKED_POLICY", 0),
                          "retirados": estados.get("WITHDRAWN", 0), "politica_version": politica["version"] if politica else None})
        return filas
    finally:
        conn.close()
