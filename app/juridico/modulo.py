"""Alta del módulo «juridico» como vertical de Guilda Work y su interruptor general `LEGAL_AI_ENABLED`.

Tres interruptores, todos necesarios: `LEGAL_AI_ENABLED` (el módulo existe en este servidor), el vertical activo en el despacho (lo ve) y fuentes habilitadas con política registrada (las usa)."""
from __future__ import annotations

import os

from flask_babel import lazy_gettext as _l


def habilitado() -> bool:
    return os.environ.get("LEGAL_AI_ENABLED", "").strip().lower() in ("1", "true", "yes", "si", "sí")


def embedder():
    """Embeddings opcionales (Ollama local, `app/embeddings.py`) solo con `LEGAL_EMBEDDINGS=1`. Devuelve un callable con atributo `modelo` o None. Sin él la búsqueda es solo textual y lo dice."""
    if os.environ.get("LEGAL_EMBEDDINGS", "").strip().lower() not in ("1", "true", "yes", "si", "sí"):
        return None
    from .. import embeddings

    class _Ollama:
        modelo = embeddings.OLLAMA_EMBED_MODEL

        def __call__(self, texto: str):
            return embeddings.generar_embedding(texto[:6000])
    return _Ollama()


def crear_esquema(conn) -> None:
    from . import catalogo, esquema
    esquema.crear_esquema(conn)
    catalogo.asegurar_catalogo(conn)
    conn.commit()


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    from . import privado
    privado.borrar_datos_de_tenant(conn, tenant_id)


def _uso(tenant_id: int) -> list[tuple[str, str]]:
    from .. import db
    conn = db.get_connection()
    try:
        from datetime import date
        n = conn.execute("SELECT COUNT(*) FROM jur_ejecuciones WHERE tenant_id = ? AND creada_en >= ?", (tenant_id, date.today().replace(day=1).isoformat())).fetchone()[0]
        return [("Consultas jurídicas este mes", str(n))]            # texto plano: el backoffice no tiene Babel
    finally:
        conn.close()


def _registrar() -> None:
    from .. import verticales
    verticales.registrar(verticales.Vertical(
        "juridico", _l("Asistente jurídico"), _l("Biblioteca de legislación y jurisprudencia autorizada, consultas con citas verificables e informes revisables en el expediente del cliente."), "scale",
        disponible=habilitado(),
        entradas_menu=(verticales.EntradaMenu("juridico", _l("Asistente jurídico"), "juridico.inicio", "scale"),),
        esquema=crear_esquema, borrar_datos=borrar_datos_de_tenant, uso=_uso))


_registrar()
