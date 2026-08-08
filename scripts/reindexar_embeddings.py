"""Reindexación única: añade el vector de embedding a notas/tareas/
mensajes que ya estaban indexados en Meilisearch ANTES de la fase de
búsqueda semántica (ver app/embeddings.py, app/busqueda.py) — ese
contenido se indexó sin `_vectors`, así que solo es buscable por
palabra clave hasta que se reindexa.

Uso:
    python scripts/reindexar_embeddings.py

Requiere Meilisearch (`MEILISEARCH_MASTER_KEY`) y, para que de verdad
añada vectores y no solo vuelva a mandar el mismo documento sin ellos,
Ollama con el modelo de `OLLAMA_EMBED_MODEL` descargado — si Ollama no
está disponible, `busqueda._indexar()` reindexa igual (sin vector) sin
fallar, así que este script tampoco falla, solo no consigue el
objetivo real de añadir búsqueda semántica.

Idempotente: se puede volver a ejecutar sin duplicar nada (mismo `id`
de siempre, Meilisearch sobrescribe)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import busqueda, db  # noqa: E402


def _notas() -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            """SELECT n.id, n.usuario_id, n.texto, n.categoria_id, n.creada_en, c.nombre AS categoria_nombre
               FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
               WHERE n.papelera_en IS NULL"""
        )]
    finally:
        conn.close()


def _tareas() -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            """SELECT t.id, t.usuario_id, t.nombre, t.categoria_id, t.inicio_en, c.nombre AS categoria_nombre
               FROM tareas t LEFT JOIN categorias c ON c.id = t.categoria_id
               WHERE t.papelera_en IS NULL"""
        )]
    finally:
        conn.close()


def _mensajes() -> list[tuple[dict, int]]:
    """Devuelve (mensaje, usuario_id) — correo_mensajes no tiene
    usuario_id propia, se resuelve vía correo_cuentas (ver
    app/busqueda.py:indexar_mensaje)."""
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT m.id, m.asunto, m.cuerpo_texto, m.fecha, c.usuario_id "
            "FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id"
        )
        return [(dict(f), f["usuario_id"]) for f in filas]
    finally:
        conn.close()


def main() -> None:
    if not busqueda.MEILISEARCH_MASTER_KEY:
        print("MEILISEARCH_MASTER_KEY no está configurada — nada que reindexar.")
        return

    notas = _notas()
    for i, nota in enumerate(notas, 1):
        busqueda.indexar_nota(nota)
        print(f"\rNotas: {i}/{len(notas)}", end="", flush=True)
    print()

    tareas = _tareas()
    for i, tarea in enumerate(tareas, 1):
        busqueda.indexar_tarea(tarea)
        print(f"\rTareas: {i}/{len(tareas)}", end="", flush=True)
    print()

    mensajes = _mensajes()
    for i, (mensaje, usuario_id) in enumerate(mensajes, 1):
        if usuario_id is not None:
            busqueda.indexar_mensaje(mensaje, usuario_id)
        print(f"\rMensajes: {i}/{len(mensajes)}", end="", flush=True)
    print()

    print(f"Reindexado: {len(notas)} notas, {len(tareas)} tareas, {len(mensajes)} mensajes.")


if __name__ == "__main__":
    main()
