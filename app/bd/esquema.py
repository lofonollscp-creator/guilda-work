"""Esquema de PostgreSQL: se crea una sola vez (ficheros de app/bd/esquema_pg/) y después evoluciona con migraciones numeradas.

`01`-`04` los genera scripts/migracion/generar_esquema_pg.py a partir del esquema de SQLite; `00` (funciones), `05` (triggers), `06` (búsqueda de texto) y `07` (semillas: el
despacho «Plataforma») son manuales. Mientras SQLite siga siendo el motor de producción, cualquier tabla nueva se añade a SQLite y se regenera; tests/test_esquema_pg.py
avisa si los ficheros del repositorio se han quedado atrás.

Tres variantes del mismo esquema:
  * ``simple``      el de SQLite trasladado tal cual (hasta la fase 6c: la aplicación aún no abre las conexiones con un despacho).
  * ``multitenant`` `tenant_id` en toda tabla de un despacho, PK/UNIQUE/FK compuestas, valor por defecto tomado de la conexión, RLS y roles (esquema_pg/mt/). Sin Citus.
  * ``citus``       lo anterior + tablas de referencia y distribuidas por `tenant_id` (16 shards, D6). Requiere la extensión citus.
"""
from pathlib import Path

DIRECTORIO = Path(__file__).resolve().parent / "esquema_pg"
ORDEN = ("00_funciones.sql", "01_tablas.sql", "02_indices.sql", "03_claves_foraneas.sql", "04_vistas.sql", "05_triggers.sql", "06_busqueda.sql", "07_semillas.sql")
ORDEN_MULTITENANT = ("00_funciones.sql", "mt/01_tablas.sql", "mt/02_indices.sql", "06_busqueda.sql", "mt/03_claves_foraneas.sql", "mt/04_vistas.sql", "mt/05_triggers.sql", "mt/05b_set_null.sql", "07_semillas.sql", "mt/09_rls.sql", "mt/10_roles.sql")
# En Citus las tablas se distribuyen ANTES de las claves foráneas y los triggers, y la RLS va al final (las semillas la necesitan desactivada).
ORDEN_CITUS = ("00_funciones.sql", "mt/01_tablas.sql", "mt/02_indices.sql", "06_busqueda.sql", "mt/08_distribuir.sql", "mt/03_claves_foraneas.sql", "mt/04_vistas.sql",
               "mt/05_triggers.sql", "mt/05b_set_null.sql", "07_semillas.sql", "mt/09_rls.sql", "mt/10_roles.sql")
PREAMBULO_CITUS = "SET citus.shard_count = 16;\nSET citus.enable_unsafe_triggers = on;\n"
VERSION_BASE = 1
MODOS = {"simple": ORDEN, "multitenant": ORDEN_MULTITENANT, "citus": ORDEN_CITUS}


def script_base(modo: str = "simple") -> str:
    cuerpo = "\n".join((DIRECTORIO / f).read_text(encoding="utf-8") for f in MODOS[modo])
    return (PREAMBULO_CITUS if modo == "citus" else "") + cuerpo


def crear_si_falta(conn, modo: str = "simple") -> bool:
    """Crea el esquema base si la base de datos está vacía. Devuelve True si lo ha creado. Todo o nada, salvo en `citus` (la distribución no es transaccional)."""
    from . import existe_tabla
    if existe_tabla(conn, "bd_esquema_version"):
        return False
    conn.ejecutar_script(
        script_base(modo)
        + "\nCREATE TABLE bd_esquema_version (version bigint PRIMARY KEY, aplicada_en text NOT NULL, descripcion text);"
        + f"\nINSERT INTO bd_esquema_version VALUES ({VERSION_BASE}, to_char(localtimestamp, 'YYYY-MM-DD\"T\"HH24:MI:SS'), 'esquema base generado desde SQLite ({modo})');",
        por_sentencias=(modo == "citus"),
    )
    return True
