"""Búsqueda en la biblioteca jurídica: identificadores exactos + texto (FTS5) + similitud vectorial si hay embeddings. Los filtros y los permisos se aplican ANTES de recuperar contenido.

- Solo se busca en las fuentes que el despacho puede usar (habilitadas, con política que permita indexar y accesibles a ese despacho). Lo demás no entra ni como candidato ni como contexto.
- Fecha jurídica: en legislación se devuelve la versión del bloque vigente en esa fecha según la fuente; sin fecha, la versión actual. Si la fecha es anterior a la primera versión recogida de una
  norma, el resultado lo dice (hueco de cobertura) en vez de escoger el último texto en silencio.
- Sin embeddings la búsqueda es solo textual y la respuesta lo indica (`modo`)."""
from __future__ import annotations

import base64
import math
import re

from .. import db
from . import corpus

MAX_VECTORIAL = 20000
CANDIDATOS_POR_VIA = 40
_TOKEN = re.compile(r"[\wáéíóúüñÁÉÍÓÚÜÑ]{2,}", re.UNICODE)
_RE_ID = [
    ("id_externo", re.compile(r"\b(BOE-[A-Z]-\d{4}-\d+)\b", re.I)),
    ("ecli", re.compile(r"\b(ECLI:[A-Z]{2}:[A-Z0-9]+:\d{4}:[A-Z0-9.]+)\b", re.I)),
    ("celex", re.compile(r"\b(\d{5}[A-Z]{1,2}\d{3,4})\b")),
    ("roj", re.compile(r"\b(?:ROJ:?\s*)?([A-Z]{2,3}\s+\d{1,6}/\d{4})\b")),
]


class ErrorBusqueda(ValueError):
    """Parámetro de búsqueda no válido, con texto apto para enseñar."""


_VACIAS = frozenset("""de la el los las un una unos unas y o u e en que qué a por para con se su sus al del lo es son ser fue han has hay como cómo cual cuál cuáles cuales cuando cuándo donde dónde si no mi me te le les
este esta esto estos estas ese esa eso sobre entre desde hasta tiene tienen puede pueden debe deben según segun sin muy más mas ya también tambien o""".split())


def _fts_consulta(texto: str, modo: str = "y") -> str | None:
    """Consulta FTS5 segura: cada palabra entre comillas (nada de operadores del usuario). `y` = todas las palabras (búsqueda precisa); `o` = las significativas, cualquiera (preguntas en lenguaje natural)."""
    tokens = _TOKEN.findall(texto or "")
    if modo == "o":
        tokens = [t for t in tokens if t.lower() not in _VACIAS and len(t) >= 3]
    if not tokens:
        return None
    union = " OR " if modo == "o" else " "
    return union.join('"' + t.replace('"', "") + '"' for t in tokens[:24])


def _coseno(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def _fecha(valor: str | None, campo: str) -> str | None:
    if not valor:
        return None
    f = corpus.fecha_iso(valor)
    if f is None:
        raise ErrorBusqueda(f"{campo}: la fecha tiene que ser AAAA-MM-DD.")
    return f


def _filtros_sql(fuentes: list[str], colecciones, materia, territorio, emisor, tipo, desde, hasta, fecha_juridica, corte_historico=None) -> tuple[str, list]:
    donde = ["v.activa = 1", "v.bloqueada = 0", f"d.fuente_id IN ({','.join('?' for _ in fuentes)})"]
    params: list = list(fuentes)
    if colecciones:
        donde.append(f"d.coleccion IN ({','.join('?' for _ in colecciones)})")
        params += list(colecciones)
    for col, val in (("materia", materia), ("territorio", territorio), ("emisor", emisor), ("tipo", tipo)):
        if val:
            donde.append(f"d.{col} LIKE ?")
            params.append(f"%{val}%" if col in ("materia", "emisor") else val)
    if desde:
        donde.append("COALESCE(d.fecha_resolucion, d.fecha_publicacion) >= ?")
        params.append(desde)
    if hasta:
        donde.append("COALESCE(d.fecha_resolucion, d.fecha_publicacion) <= ?")
        params.append(hasta)
    if corte_historico:                                                   # «estado del conocimiento en esa fecha»: nada publicado o resuelto después
        donde.append("COALESCE(d.fecha_publicacion, d.fecha_resolucion, '0000-00-00') <= ?")
        params.append(corte_historico)
    if fecha_juridica:
        donde.append("(g.vigente_desde IS NULL OR g.vigente_desde <= ?) AND (g.vigente_hasta IS NULL OR g.vigente_hasta >= ?)")
        params += [fecha_juridica, fecha_juridica]
    else:
        donde.append("g.vigente_hasta IS NULL")                           # sin fecha: la versión actual de cada bloque
    return " AND ".join(donde), params


def _resultado(f, motivo: str, extracto: str | None = None) -> dict:
    return {"documento_id": f["documento_id"], "fragmento_id": f["fragmento_id"], "version_id": f["version_id"], "coleccion": f["coleccion"], "fuente_id": f["fuente_id"], "titulo": f["titulo"],
            "emisor": f["emisor"], "territorio": f["territorio"], "rango": f["rango"], "tipo": f["tipo"], "estado_normativo": f["estado_normativo"], "fecha_publicacion": f["fecha_publicacion"],
            "fecha_resolucion": f["fecha_resolucion"], "localizador": f["localizador"], "vigente_desde": f["vigente_desde"], "vigente_hasta": f["vigente_hasta"], "vigencia_origen": f["vigencia_origen"],
            "extracto": (extracto if extracto is not None else f["texto"][:400]), "motivo": motivo, "url_canonica": f["url_canonica"], "capturada_en": f["capturada_en"]}


_SELECT = ("SELECT g.id AS fragmento_id, g.localizador, g.texto, g.vigente_desde, g.vigente_hasta, g.vigencia_origen, v.id AS version_id, v.capturada_en, d.id AS documento_id, d.coleccion, "
           "d.fuente_id, d.titulo, d.emisor, d.territorio, d.rango, d.tipo, d.estado_normativo, d.fecha_publicacion, d.fecha_resolucion, d.url_canonica "
           "FROM jur_fragmentos g JOIN jur_versiones v ON v.id = g.version_id JOIN jur_documentos d ON d.id = v.documento_id")


def buscar(tenant_id: int, consulta: str, *, colecciones: list[str] | None = None, materia: str | None = None, territorio: str | None = None, emisor: str | None = None, tipo: str | None = None,
           desde: str | None = None, hasta: str | None = None, fecha_juridica: str | None = None, limite: int = 20, cursor: str | None = None, embedder=None,
           operaciones: tuple[str, ...] = ("indexar",), corte_historico: str | None = None) -> dict:
    """Resultados agrupados por documento (el mejor fragmento de cada uno), con motivo de relevancia, cobertura y huecos."""
    consulta = (consulta or "").strip()
    if embedder is None:
        from . import modulo
        embedder = modulo.embedder()
    if not consulta and not (materia or emisor or tipo or colecciones):
        raise ErrorBusqueda("Escribe qué buscas o elige algún filtro.")
    desde, hasta, fecha_juridica = _fecha(desde, "Desde"), _fecha(hasta, "Hasta"), _fecha(fecha_juridica, "Fecha jurídica")
    limite = max(1, min(int(limite or 20), 50))
    offset = 0
    if cursor:
        try:
            offset = max(0, int(base64.urlsafe_b64decode(cursor.encode()).decode()))
        except Exception:  # noqa: BLE001
            raise ErrorBusqueda("El cursor no es válido.") from None
    conn = db.get_connection()
    try:
        fuentes = corpus.fuentes_para_despacho(tenant_id, operaciones[0], conn)
        for extra in operaciones[1:]:                                       # p. ej. enviar_llm y citar para alimentar al asistente
            permitidas = set(corpus.fuentes_para_despacho(tenant_id, extra, conn))
            fuentes = [f for f in fuentes if f in permitidas]
        if colecciones:
            conocidas = {r["id"] for r in conn.execute("SELECT id FROM jur_fuentes WHERE coleccion IN (%s)" % ",".join("?" for _ in colecciones), colecciones)}
            fuentes = [f for f in fuentes if f in conocidas]
        aviso = []
        solicitadas_sin_fuente = [c for c in (colecciones or []) if not _hay_fuente(conn, tenant_id, c, operaciones)]
        for c in solicitadas_sin_fuente:
            aviso.append(f"La colección «{c}» no está disponible para tu despacho (fuente pendiente de habilitación): no se ha buscado en ella.")
        if not fuentes:
            return {"resultados": [], "total": 0, "siguiente_cursor": None, "modo": "sin_fuentes", "avisos": aviso or ["No hay fuentes habilitadas para tu despacho."], "huecos": [], "fuentes": []}
        donde, params = _filtros_sql(fuentes, colecciones, materia, territorio, emisor, tipo, desde, hasta, fecha_juridica, _fecha(corte_historico, 'Corte histórico'))
        candidatos: dict[int, dict] = {}                                  # fragmento_id -> {fila, motivo, puntos}
        # 1. Identificadores exactos
        for campo, patron in _RE_ID:
            for m in patron.finditer(consulta):
                valor = m.group(1)
                col = {"id_externo": "d.id_externo", "ecli": "d.ecli", "celex": "d.celex", "roj": "d.roj"}[campo]
                for f in conn.execute(f"{_SELECT} WHERE {donde} AND {col} = ? COLLATE NOCASE ORDER BY g.orden LIMIT 5", (*params, valor)):
                    candidatos.setdefault(f["fragmento_id"], {"fila": f, "motivo": f"Identificador exacto ({valor})", "rrf": 1.0})
        # 2. Texto (FTS5, bm25)
        fts = _fts_consulta(consulta)
        n_texto = 0
        fts_usada = fts
        if fts:
            filas = conn.execute(f"{_SELECT} JOIN jur_fragmentos_fts ON jur_fragmentos_fts.rowid = g.id WHERE jur_fragmentos_fts MATCH ? AND {donde} ORDER BY bm25(jur_fragmentos_fts) LIMIT ?",
                                 (fts, *params, CANDIDATOS_POR_VIA)).fetchall()
            if len(filas) < 5 and not any(pat.search(consulta) for _c, pat in _RE_ID):                                              # pocas con todas las palabras: se amplía a «cualquiera de las significativas» (pregunta en lenguaje natural)
                fts_o = _fts_consulta(consulta, "o")
                if fts_o and fts_o != fts:
                    extra = conn.execute(f"{_SELECT} JOIN jur_fragmentos_fts ON jur_fragmentos_fts.rowid = g.id WHERE jur_fragmentos_fts MATCH ? AND {donde} ORDER BY bm25(jur_fragmentos_fts) LIMIT ?",
                                         (fts_o, *params, CANDIDATOS_POR_VIA)).fetchall()
                    vistos = {f["fragmento_id"] for f in filas}
                    filas = list(filas) + [f for f in extra if f["fragmento_id"] not in vistos]
                    fts_usada = fts_o
            n_texto = len(filas)
            for rango, f in enumerate(filas):
                c = candidatos.setdefault(f["fragmento_id"], {"fila": f, "motivo": "Coincidencia de texto", "rrf": 0.0})
                c["rrf"] += 1.0 / (60 + rango + 1)
        # 3. Vectores (solo si hay embedder y fragmentos con embedding)
        modo = "texto"
        if embedder is not None and consulta:
            try:
                q = embedder(consulta)
            except Exception:  # noqa: BLE001
                q = None
            if q:
                puntuados = []
                modelo = getattr(embedder, "modelo", None)
                for f in conn.execute(f"{_SELECT.replace('SELECT g.id', 'SELECT g.embedding AS emb, g.id')} WHERE {donde} AND g.embedding IS NOT NULL AND g.embedding_modelo IS ? LIMIT ?", (*params, modelo, MAX_VECTORIAL)):
                    puntuados.append((_coseno(q, corpus.bytes_a_vector(f["emb"])), f))
                if puntuados:
                    modo = "hibrido"
                    puntuados.sort(key=lambda x: -x[0])
                    for rango, (s, f) in enumerate(puntuados[:CANDIDATOS_POR_VIA]):
                        c = candidatos.setdefault(f["fragmento_id"], {"fila": f, "motivo": "Similitud semántica", "rrf": 0.0})
                        c["rrf"] += 1.0 / (60 + rango + 1)
                        if c["motivo"] == "Coincidencia de texto":
                            c["motivo"] = "Coincidencia de texto y similitud semántica"
        if not consulta:                                                # solo filtros: navegar la colección
            for f in conn.execute(f"{_SELECT} WHERE {donde} ORDER BY COALESCE(d.fecha_publicacion, '') DESC, g.orden LIMIT ?", (*params, 200)):
                candidatos.setdefault(f["fragmento_id"], {"fila": f, "motivo": "Filtro", "rrf": 0.0})
        # Agrupar por documento (el mejor fragmento) y paginar
        por_doc: dict[int, dict] = {}
        for c in sorted(candidatos.values(), key=lambda c: -c["rrf"]):
            por_doc.setdefault(c["fila"]["documento_id"], c)
        ordenados = list(por_doc.values())
        total = len(ordenados)
        pagina = ordenados[offset:offset + limite]
        resultados = []
        for c in pagina:
            extracto = None
            if fts and c["motivo"].startswith(("Coincidencia", "Similitud")):
                s = conn.execute("SELECT snippet(jur_fragmentos_fts, 0, '«', '»', ' … ', 24) AS s FROM jur_fragmentos_fts WHERE jur_fragmentos_fts MATCH ? AND rowid = ?", (fts_usada, c["fila"]["fragmento_id"])).fetchone()
                extracto = s["s"] if s and s["s"] else None
            resultados.append(_resultado(c["fila"], c["motivo"], extracto))
        huecos = _huecos_temporales(conn, [r["documento_id"] for r in resultados], fecha_juridica) if fecha_juridica else []
        if fecha_juridica and fts_usada:                                    # normas que coinciden con la búsqueda pero no tienen texto aplicable a esa fecha: se dicen aunque no salgan como resultado
            sin_fecha_donde, sin_fecha_p = _filtros_sql(fuentes, colecciones, materia, territorio, emisor, tipo, desde, hasta, None, _fecha(corte_historico, "Corte histórico"))
            sin_fecha_donde = sin_fecha_donde.replace(" AND g.vigente_hasta IS NULL", "")
            ids = [f["documento_id"] for f in conn.execute(f"{_SELECT} JOIN jur_fragmentos_fts ON jur_fragmentos_fts.rowid = g.id WHERE jur_fragmentos_fts MATCH ? AND {sin_fecha_donde} AND d.coleccion = 'legislacion' "
                                                           f"ORDER BY bm25(jur_fragmentos_fts) LIMIT 30", (fts_usada, *sin_fecha_p))]
            nuevos = [i for i in dict.fromkeys(ids) if i not in {r["documento_id"] for r in resultados}][:5]
            huecos += [h for h in _huecos_temporales(conn, nuevos, fecha_juridica) if h not in huecos]
        siguiente = base64.urlsafe_b64encode(str(offset + limite).encode()).decode() if offset + limite < total else None
        return {"resultados": resultados, "total": total, "siguiente_cursor": siguiente, "modo": modo, "avisos": aviso, "huecos": huecos, "fuentes": fuentes}
    finally:
        conn.close()


def _hay_fuente(conn, tenant_id: int, coleccion: str, operaciones: tuple[str, ...] = ("indexar",)) -> bool:
    ids = set(corpus.fuentes_para_despacho(tenant_id, operaciones[0], conn))
    for extra in operaciones[1:]:
        ids &= set(corpus.fuentes_para_despacho(tenant_id, extra, conn))
    return any(r["id"] in ids for r in conn.execute("SELECT id FROM jur_fuentes WHERE coleccion = ?", (coleccion,)))


def _huecos_temporales(conn, documento_ids: list[int], fecha_juridica: str) -> list[str]:
    """Normas cuya primera versión recogida es posterior a la fecha jurídica: no hay texto aplicable a esa fecha en el corpus."""
    huecos = []
    for did in documento_ids:
        f = conn.execute("SELECT d.titulo, d.coleccion, MIN(g.vigente_desde) AS primera, SUM(CASE WHEN g.vigente_desde IS NULL THEN 1 ELSE 0 END) AS sin_fecha FROM jur_fragmentos g JOIN jur_versiones v ON v.id = g.version_id "
                         "JOIN jur_documentos d ON d.id = v.documento_id WHERE d.id = ? AND v.activa = 1 GROUP BY d.id", (did,)).fetchone()
        if f and f["coleccion"] == "legislacion" and f["primera"] and f["primera"] > fecha_juridica:
            huecos.append(f"«{f['titulo'][:90]}»: la primera versión recogida es de {f['primera']}, posterior a {fecha_juridica}; no hay texto aplicable a esa fecha en la biblioteca.")
        elif f and f["coleccion"] == "legislacion" and f["sin_fecha"]:
            huecos.append(f"«{f['titulo'][:90]}»: hay partes sin fecha de vigencia en la fuente; su aplicabilidad a {fecha_juridica} es desconocida.")
    return huecos


# --- Fichas y versiones ----------------------------------------------------------------------------------------------------------------------------------

def _fuentes_del_despacho(conn, tenant_id: int) -> list[str]:
    return corpus.fuentes_para_despacho(tenant_id, "indexar", conn)


def documento(tenant_id: int, documento_id: int) -> dict | None:
    """Metadatos de un documento y sus versiones, solo si el despacho puede usar su fuente."""
    conn = db.get_connection()
    try:
        d = conn.execute("SELECT * FROM jur_documentos WHERE id = ?", (documento_id,)).fetchone()
        if d is None or d["fuente_id"] not in _fuentes_del_despacho(conn, tenant_id):
            return None
        versiones = [dict(v) for v in conn.execute("SELECT id, hash_texto, fecha_publicacion, fecha_resolucion, capturada_en, calidad, activa, bloqueada FROM jur_versiones WHERE documento_id = ? ORDER BY id DESC", (documento_id,))]
        relaciones = [dict(r) for r in conn.execute("SELECT r.tipo, r.destino_externo, r.evidencia, r.verificada, r.destino_documento_id, dd.titulo AS destino_titulo FROM jur_relaciones r "
                                                   "LEFT JOIN jur_documentos dd ON dd.id = r.destino_documento_id WHERE r.documento_id = ? ORDER BY r.tipo, r.destino_externo LIMIT 200", (documento_id,))]
        fuente = conn.execute("SELECT nombre FROM jur_fuentes WHERE id = ?", (d["fuente_id"],)).fetchone()
        politica = corpus.politica_vigente(d["fuente_id"], conn)
        return {**dict(d), "fuente_nombre": fuente["nombre"] if fuente else d["fuente_id"], "versiones": versiones, "relaciones": relaciones, "atribucion": politica["atribucion"] if politica else None}
    finally:
        conn.close()


def texto_de_version(tenant_id: int, documento_id: int, version_id: int | None = None, fecha_juridica: str | None = None) -> dict | None:
    """Fragmentos de la versión indicada (o la activa). En legislación, con `fecha_juridica`, solo los vigentes en esa fecha según la fuente."""
    fecha_juridica = _fecha(fecha_juridica, "Fecha jurídica")
    conn = db.get_connection()
    try:
        d = conn.execute("SELECT id, fuente_id, titulo, coleccion FROM jur_documentos WHERE id = ?", (documento_id,)).fetchone()
        if d is None or d["fuente_id"] not in _fuentes_del_despacho(conn, tenant_id):
            return None
        v = (conn.execute("SELECT * FROM jur_versiones WHERE id = ? AND documento_id = ? AND bloqueada = 0", (version_id, documento_id)).fetchone() if version_id
             else conn.execute("SELECT * FROM jur_versiones WHERE documento_id = ? AND activa = 1 AND bloqueada = 0", (documento_id,)).fetchone())
        if v is None:
            return None
        if fecha_juridica:
            filas = conn.execute("SELECT * FROM jur_fragmentos WHERE version_id = ? AND (vigente_desde IS NULL OR vigente_desde <= ?) AND (vigente_hasta IS NULL OR vigente_hasta >= ?) ORDER BY orden", (v["id"], fecha_juridica, fecha_juridica)).fetchall()
        else:
            filas = conn.execute("SELECT * FROM jur_fragmentos WHERE version_id = ? AND vigente_hasta IS NULL ORDER BY orden", (v["id"],)).fetchall()
        return {"documento": dict(d), "version": {k: v[k] for k in ("id", "fecha_publicacion", "capturada_en", "calidad", "activa")},
                "fragmentos": [{k: f[k] for k in ("id", "orden", "bloque_id", "localizador", "texto", "vigente_desde", "vigente_hasta", "vigencia_origen")} for f in filas],
                "fecha_juridica": fecha_juridica, "huecos": _huecos_temporales(conn, [documento_id], fecha_juridica) if fecha_juridica else []}
    finally:
        conn.close()
