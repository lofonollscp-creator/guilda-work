"""Migración de una sola vez de los documentos fiscales que quedaron
como BLOB en SQLite (subidos antes de que db.subir_documento_vencimiento
empezara a promoverlos a Nextcloud automáticamente, ver ese commit) --
NO es un cron, se ejecuta a mano cuando haga falta:

    .venv/bin/python scripts/migrar_documentos_a_nextcloud.py [--aplicar]

Sin --aplicar hace un "dry run": informa de qué documentos migraría sin
tocar nada. Con --aplicar, por cada documento con `contenido` (BLOB) no
nulo: sube el contenido a Nextcloud, lo vuelve a descargar y compara el
hash SHA-256 byte a byte, y SOLO si coincide, actualiza la fila
(ruta_nextcloud = ruta, contenido = NULL) -- si algo falla o el hash no
coincide, esa fila se deja tal cual (sigue sirviéndose desde el BLOB) y
se informa por consola, nunca se aborta el resto del lote a medias.

Requiere que el tenant de cada documento tenga ya su espacio Nextcloud
aprovisionado (ver app/nextcloud.py:crear_espacio_tenant) -- si no lo
tiene, la subida falla con ErrorNextcloud y ese documento se deja como
estaba, sin más.
"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, nextcloud  # noqa: E402


def main() -> None:
    aplicar = "--aplicar" in sys.argv

    conn = db.get_connection()
    try:
        filas = conn.execute(
            """SELECT d.id, d.vencimiento_id, d.nombre_archivo, d.contenido, t.nombre AS tenant_nombre
               FROM vencimientos_fiscales_documentos d
               JOIN vencimientos_fiscales v ON v.id = d.vencimiento_id
               JOIN tenants t ON t.id = v.tenant_id
               WHERE d.contenido IS NOT NULL"""
        ).fetchall()
    finally:
        conn.close()

    if not filas:
        print("Nada que migrar: no hay ningún documento con BLOB local todavía.")
        return

    print(f"{len(filas)} documento(s) con BLOB local encontrados.")
    migrados = 0
    fallidos = 0
    for fila in filas:
        ruta = f"{fila['tenant_nombre']}/vencimientos-fiscales/{fila['id']}-{fila['nombre_archivo']}"
        if not aplicar:
            print(f"  [dry-run] documento #{fila['id']} -> {ruta}")
            continue
        try:
            nextcloud.subir_archivo(ruta, fila["contenido"])
            descargado = nextcloud.descargar_archivo(ruta)
            hash_original = hashlib.sha256(fila["contenido"]).hexdigest()
            hash_descargado = hashlib.sha256(descargado).hexdigest()
            if hash_original != hash_descargado:
                print(f"  ERROR documento #{fila['id']}: el hash no coincide tras subir, se deja como estaba.")
                fallidos += 1
                continue
        except nextcloud.ErrorNextcloud as e:
            print(f"  ERROR documento #{fila['id']}: {e} -- se deja como estaba.")
            fallidos += 1
            continue

        conn = db.get_connection()
        try:
            conn.execute(
                "UPDATE vencimientos_fiscales_documentos SET ruta_nextcloud = ?, contenido = NULL WHERE id = ?",
                (ruta, fila["id"]),
            )
            conn.commit()
        finally:
            conn.close()
        migrados += 1
        print(f"  OK documento #{fila['id']} -> {ruta}")

    if aplicar:
        print(f"Migrados: {migrados}. Fallidos (sin tocar, siguen como BLOB): {fallidos}.")
    else:
        print("Dry run -- ejecuta con --aplicar para migrar de verdad.")


if __name__ == "__main__":
    main()
