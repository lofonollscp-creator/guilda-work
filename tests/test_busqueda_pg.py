"""Búsqueda de texto contra PostgreSQL (fase 5): las mismas consultas, con el mismo corpus sintético, dan los mismos documentos, fragmentos y avisos que en SQLite."""
import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("psycopg_pool")

from tests import pg_ayudas  # noqa: E402

pytestmark = pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")

@pytest.fixture
def postgres(monkeypatch):
    """La aplicación contra una base de datos PostgreSQL nueva con el esquema."""
    from app import bd
    url, limpiar = pg_ayudas.crear_base_con_esquema()
    monkeypatch.setattr(bd, "MOTOR", "postgres")
    yield url
    monkeypatch.setattr(bd, "MOTOR", "sqlite")
    limpiar()


CONSULTAS = [
    ("deducción de gastos límite", {}),
    ("deduccion de gastos limite", {}),                                           # sin acentos
    ("DEDUCCIÓN GASTOS", {}),                                                     # mayúsculas
    ("objeto deducción", {"fecha_juridica": "2021-06-01", "colecciones": ["legislacion"]}),
    ("objeto deducción", {"fecha_juridica": "2023-01-01", "colecciones": ["legislacion"]}),
    ("objeto deducción gastos", {"fecha_juridica": "2019-01-01", "colecciones": ["legislacion"]}),
    ("texto derogado sintético", {"fecha_juridica": "2021-01-01"}),
    ("BOE-A-2099-0001", {}),
    ("¿qué dice ECLI:ES:TC:2099:12 sobre el amparo?", {}),
    ("sintético", {"colecciones": ["jurisprudencia"]}),
    ("sintético", {"colecciones": ["jurisprudencia"], "tipo": "auto"}),
    ("sintético", {"emisor": "tribunal constitucional"}),                         # el filtro no distingue mayúsculas
    ("sintético", {"colecciones": ["jurisprudencia"], "desde": "2099-01-06"}),
    ("¿qué requisitos hay para deducir los gastos de la norma sintética?", {}),   # lenguaje natural: cae al «cualquiera de las palabras»
    ("", {"colecciones": ["legislacion"]}),
    ("palabrainexistente", {}),
]


def _cargar_y_buscar():
    from app import db
    from app.juridico import busqueda, ingesta
    from tests.juridico_ayudas import conector_consolidada, conector_diario, habilitar, transporte_boe
    habilitar("boe-consolidada")
    habilitar("boe-diario-tc")
    t = transporte_boe()
    ingesta.sincronizar("boe-consolidada", conector_consolidada(t), "2099-01-01", "2099-01-31")
    ingesta.sincronizar("boe-diario-tc", conector_diario(t), "2099-01-10", "2099-01-10")
    tenant = db.crear_tenant("Despacho con biblioteca")
    salida = []
    for texto, filtros in CONSULTAS:
        r = busqueda.buscar(tenant, texto, **filtros)
        salida.append({
            "modo": r["modo"], "total": r["total"], "huecos": sorted(r["huecos"]), "avisos": sorted(r["avisos"]),
            "documentos": sorted(x["titulo"] for x in r["resultados"]),     # el MEJOR fragmento de cada documento puede cambiar (bm25 frente a ts_rank_cd)
            "primero": (r["resultados"][0]["titulo"], r["resultados"][0]["motivo"]) if r["resultados"] else None,
            "fragmentos": {(x["titulo"], x["localizador"]) for x in r["resultados"]},
            "extractos": [x["extracto"] for x in r["resultados"]],
        })
    return salida


def test_las_busquedas_juridicas_dan_lo_mismo_en_sqlite_y_en_postgres(monkeypatch):
    from app import bd
    en_sqlite = _cargar_y_buscar()
    url, limpiar = pg_ayudas.crear_base_con_esquema()
    monkeypatch.setattr(bd, "MOTOR", "postgres")
    try:
        en_postgres = _cargar_y_buscar()
    finally:
        monkeypatch.setattr(bd, "MOTOR", "sqlite")
        limpiar()
    for (texto, filtros), a, b in zip(CONSULTAS, en_sqlite, en_postgres):
        for campo in ("modo", "total", "huecos", "avisos", "documentos", "primero"):
            assert a[campo] == b[campo], f"{texto!r} {filtros}: {campo} difiere\n  SQLite:     {a[campo]}\n  PostgreSQL: {b[campo]}"
    assert any(x["documentos"] for x in en_postgres), "la prueba no ha buscado nada"
    coinciden = sum(1 for a, b in zip(en_sqlite, en_postgres) if a["fragmentos"] == b["fragmentos"])
    assert coinciden >= len(CONSULTAS) - 3, f"el mejor fragmento coincide solo en {coinciden} de {len(CONSULTAS)} consultas"
    marcados = [e for x in en_postgres for e in x["extractos"] if e and "«" in e]
    assert marcados, "PostgreSQL no devuelve extractos con las coincidencias marcadas"


# --- correo -----------------------------------------------------------------------------------------------------------------------------------

MENSAJES = [
    # (asunto, remitente, destinatarios, cuerpo, cifrado)
    ("Factura de octubre", "contabilidad@acme.com", "ana@despacho.es", "Adjunto la factura 2026-104 pendiente de pago.", 0),
    ("Re: facturación trimestral", "luis@proveedor.net", "ana@despacho.es", "Revisamos la facturación del trimestre y el IVA.", 0),
    ("Reunión del lunes", "ana@despacho.es", "equipo@despacho.es", "Orden del día: pago pendiente y nueva oferta del 50% de descuento.", 0),
    ("Artículo 1.101 del Código Civil", "juan@bufete.es", "ana@despacho.es", "Consulta sobre la responsabilidad contractual (artículo 1.101).", 0),
    ("CONFIDENCIAL: contrato Ñandú", "socio@despacho.es", "ana@despacho.es", "Cláusula secreta XYZSECRETA del contrato.", 2),         # entrando, por sellar: NO se indexa
    ("Sin cuerpo", "x@y.z", "ana@despacho.es", None, 0),
]
BUSQUEDAS_CORREO = ["factura", "fact", "FACTURA", "facturacion", "facturación", '"pago pendiente"', "pago pend", "acme.com", "acme", "1.101", "articulo 1.101", "50%",
                    "ñandu", "XYZSECRETA", "contrato", "descuento oferta", "inexistente", "despacho.es"]


def _cargar_correo():
    from app import db
    conn = db.get_connection()
    try:
        cuenta = conn.execute("INSERT INTO correo_cuentas (nombre, protocolo, host, puerto, usuario, creada_en) VALUES ('t', 'imap', 'h', 993, 'u', 'ahora')").lastrowid
        for i, (asunto, rem, dest, cuerpo, cifrado) in enumerate(MENSAJES):
            conn.execute("INSERT INTO correo_mensajes (cuenta_id, carpeta, uid, asunto, remitente, destinatarios, fecha, cuerpo_texto, descargado_en, cifrado) VALUES (?, 'INBOX', ?, ?, ?, ?, ?, ?, 'ahora', ?)",
                         (cuenta, str(i + 1), asunto, rem, dest, f"2026-10-{10 + i:02d}", cuerpo, cifrado))
        conn.commit()
    finally:
        conn.close()
    return cuenta


def _buscar_correo(cuenta, textos):
    from app import db
    return {t: sorted(db.listar_mensajes_correo(cuenta, "INBOX", texto=t, incluir_pospuestos=True)[i]["uid"] for i in range(len(db.listar_mensajes_correo(cuenta, "INBOX", texto=t, incluir_pospuestos=True)))) for t in textos}


@pytest.mark.solo_sqlite          # trabaja con su propia base de PostgreSQL y esquema simple: se ejecuta en el modo normal con GUILDA_TEST_PG_URL
def test_la_busqueda_de_correo_da_lo_mismo_en_sqlite_y_en_postgres(monkeypatch):
    from app import bd, db
    en_sqlite = _buscar_correo(_cargar_correo(), BUSQUEDAS_CORREO)
    assert en_sqlite["factura"] and en_sqlite["XYZSECRETA"] == [], "SQLite: lo que está por sellar no se encuentra"
    url, limpiar = pg_ayudas.crear_base_con_esquema()
    monkeypatch.setattr(bd, "MOTOR", "postgres")
    try:
        cuenta = _cargar_correo()
        en_postgres = _buscar_correo(cuenta, BUSQUEDAS_CORREO)
        assert en_postgres["XYZSECRETA"] == [] and en_postgres["ñandu"] == [], "PostgreSQL: el mensaje por sellar no entra en el índice"
        # al sellarse (cifrado 2 → 1) sí se indexa; la columna tsvector es generada, no hay disparador que mantener
        conn = db.get_connection()
        conn.execute("UPDATE correo_mensajes SET cifrado = 0 WHERE cuenta_id = ? AND uid = '5'", (cuenta,))
        conn.commit()
        conn.close()
        assert _buscar_correo(cuenta, ["XYZSECRETA", "ñandu"]) == {"XYZSECRETA": ["5"], "ñandu": ["5"]}
        # y si el cuerpo vuelve a quedar sellado, desaparece del índice
        conn = db.get_connection()
        conn.execute("UPDATE correo_mensajes SET cifrado = 2 WHERE cuenta_id = ? AND uid = '5'", (cuenta,))
        conn.commit()
        conn.close()
        assert _buscar_correo(cuenta, ["XYZSECRETA"]) == {"XYZSECRETA": []}
    finally:
        monkeypatch.setattr(bd, "MOTOR", "sqlite")
        limpiar()
    for t in BUSQUEDAS_CORREO:
        assert en_sqlite[t] == en_postgres[t], f"{t!r}: SQLite {en_sqlite[t]} / PostgreSQL {en_postgres[t]}"


def test_las_consultas_tsquery_del_correo_solo_llevan_letras_y_cifras():
    from app import db
    assert db.consulta_tsquery("fact") == "(fact:*)"
    assert db.consulta_tsquery('"pago pendiente" iva') == "(pago <-> pendiente) & (iva:*)"
    assert db.consulta_tsquery("articulo 1.101") == "(articulo:*) & (1 <-> 101:*)"
    assert db.consulta_tsquery("50%") is None and db.consulta_tsquery("a_b") is None and db.consulta_tsquery("   ") is None
    for peligroso in ["a & b", "a | !b", "a:*)", "'; DROP TABLE x; --", "(a <-> b)"]:
        q = db.consulta_tsquery(peligroso)
        assert q is None or not __import__("re").search(r"[^\w\s&()<>:*-]|;", q), q


# --- fragmentos privados de los adjuntos -------------------------------------------------------------------------------------------------------

def test_los_fragmentos_privados_se_buscan_en_postgres_solo_dentro_del_despacho(postgres):
    from app import db
    from app.juridico import adjuntos
    t1, t2 = db.crear_tenant("Despacho uno"), db.crear_tenant("Despacho dos")
    conn = db.get_connection()
    try:
        u1 = conn.execute("INSERT INTO usuarios (email, contrasena_hash, creado_en, tenant_id) VALUES ('a@uno.es', 'x', 'ahora', ?)", (t1,)).lastrowid
        u2 = conn.execute("INSERT INTO usuarios (email, contrasena_hash, creado_en, tenant_id) VALUES ('b@dos.es', 'x', 'ahora', ?)", (t2,)).lastrowid
        conn.commit()
    finally:
        conn.close()
    a1 = adjuntos.subir(t1, u1, "nota1.txt", "El contrato fija una cláusula penal de quince mil euros.\n\nOtra parte habla de arrendamientos.".encode())
    adjuntos.subir(t2, u2, "nota2.txt", "Otro despacho: cláusula penal reservada.".encode())
    ids = adjuntos.validar_para_consulta(t1, u1, [a1["id"] if isinstance(a1, dict) else a1])
    frag = adjuntos.fragmentos_para(t1, ids, "cláusula penal euros")
    assert frag and all("quince mil" in f["texto"] or "arrendamientos" in f["texto"] for f in frag)
    assert not any("reservada" in f["texto"] for f in frag), "nada de otro despacho"


def test_la_evaluacion_de_recuperacion_no_baja_en_postgres(monkeypatch):
    """Criterio de salida de la fase 5: el conjunto de evaluación del repositorio recupera lo mismo en PostgreSQL que en SQLite."""
    from pathlib import Path
    from app import bd, db
    from app.juridico import evaluacion, ingesta
    from tests.juridico_ayudas import conector_consolidada, conector_diario, habilitar, transporte_boe
    casos = evaluacion.cargar(str(Path(__file__).parent / "datos" / "juridico_evaluacion_plantilla.json"))

    def medir():
        habilitar("boe-consolidada")
        habilitar("boe-diario-tc")
        t = transporte_boe()
        ingesta.sincronizar("boe-consolidada", conector_consolidada(t), "2099-01-01", "2099-01-31")
        ingesta.sincronizar("boe-diario-tc", conector_diario(t), "2099-01-10", "2099-01-10")
        r = evaluacion.recuperacion(db.crear_tenant("Evaluación"), casos, embedder=None)
        return r["porcentaje_recuperacion"], r["insuficientes_correctos"], [(d["id"], d["acierto"]) for d in r["detalle"]]

    en_sqlite = medir()
    url, limpiar = pg_ayudas.crear_base_con_esquema()
    monkeypatch.setattr(bd, "MOTOR", "postgres")
    try:
        en_postgres = medir()
    finally:
        monkeypatch.setattr(bd, "MOTOR", "sqlite")
        limpiar()
    assert en_sqlite[0] is not None and en_sqlite[0] > 0
    assert en_postgres == en_sqlite, f"SQLite {en_sqlite} / PostgreSQL {en_postgres}"


def test_la_busqueda_hibrida_con_embeddings_funciona_en_postgres(postgres):
    """Los embeddings siguen guardados como BLOB (bytea) y se comparan en Python: el modo híbrido debe funcionar igual con un embedder falso y determinista."""
    import hashlib
    from app import db
    from app.juridico import busqueda, ingesta
    from tests.juridico_ayudas import conector_consolidada, habilitar, transporte_boe

    def embedder(texto):
        h = hashlib.sha256(texto.lower().encode()).digest()
        return [b / 255 for b in h[:8]]
    embedder.modelo = "falso-8"
    habilitar("boe-consolidada")
    ingesta.sincronizar("boe-consolidada", conector_consolidada(transporte_boe()), "2099-01-01", "2099-01-31", embedder=embedder)
    r = busqueda.buscar(db.crear_tenant("Híbrido"), "deducción de gastos límite", embedder=embedder)
    assert r["modo"] == "hibrido" and r["total"] >= 1
    conn = db.get_connection()
    try:
        fila = conn.execute("SELECT embedding, embedding_modelo FROM jur_fragmentos WHERE embedding IS NOT NULL LIMIT 1").fetchone()
    finally:
        conn.close()
    assert fila["embedding_modelo"] == "falso-8" and isinstance(fila["embedding"], (bytes, bytearray, memoryview))
