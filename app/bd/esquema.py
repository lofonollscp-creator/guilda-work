"""Esquema de PostgreSQL: se crea una sola vez (ficheros de app/bd/esquema_pg/) y después evoluciona con migraciones numeradas.

`01`-`04` los genera scripts/migracion/generar_esquema_pg.py a partir del esquema de SQLite; `00` (funciones) y `05` (triggers) son
manuales. Mientras SQLite siga siendo el motor de producción, cualquier tabla nueva se añade a SQLite y se regenera; tests/test_esquema_pg.py
avisa si los ficheros del repositorio se han quedado atrás.
"""
from pathlib import Path

DIRECTORIO = Path(__file__).resolve().parent / "esquema_pg"
ORDEN = ("00_funciones.sql", "01_tablas.sql", "02_indices.sql", "03_claves_foraneas.sql", "04_vistas.sql", "05_triggers.sql")
VERSION_BASE = 1


def script_base() -> str:
    return "\n".join((DIRECTORIO / f).read_text(encoding="utf-8") for f in ORDEN)


def crear_si_falta(conn) -> bool:
    """Crea el esquema base si la base de datos está vacía. Devuelve True si lo ha creado. Todo o nada: el script se ejecuta en una sola transacción."""
    from . import existe_tabla
    if existe_tabla(conn, "bd_esquema_version"):
        return False
    conn.ejecutar_script(
        script_base()
        + "\nCREATE TABLE bd_esquema_version (version bigint PRIMARY KEY, aplicada_en text NOT NULL, descripcion text);"
        + f"\nINSERT INTO bd_esquema_version VALUES ({VERSION_BASE}, to_char(localtimestamp, 'YYYY-MM-DD\"T\"HH24:MI:SS'), 'esquema base generado desde SQLite');"
    )
    return True
