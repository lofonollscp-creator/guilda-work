"""Comprueba, ANTES de desplegar, que las migraciones del código nuevo se aplican
bien sobre una COPIA de la base de datos real (la real no se toca).

    .venv/bin/python scripts/comprobar_migraciones.py [--bd data/registro.db] [--codigo DIRECTORIO]

Con --codigo se prueba ese árbol de código (p. ej. el `git archive` de lo que se va a
desplegar) en vez del repo en el que está el script. Sale con código 0 si todo cuadra y
1 si algo falla (el despliegue debe parar).

Qué comprueba: que init_db() se ejecuta sin error y dos veces seguidas (idempotente),
que PRAGMA integrity_check da «ok», que no aparecen violaciones de claves ajenas que no
había antes, y que no se pierde ninguna fila de ninguna tabla."""
import argparse
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path


def _tablas(conn) -> dict[str, int]:
    nombres = [f[0] for f in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    return {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in nombres}


def _columnas(conn) -> dict[str, set[str]]:
    return {n: {c[1] for c in conn.execute(f'PRAGMA table_info("{n}")')} for n in _tablas(conn)}


def comprobar(bd: Path, codigo: Path) -> list[str]:
    """Lista de problemas (vacía = todo bien). Imprime un resumen."""
    problemas: list[str] = []
    if not bd.exists():
        return [f"No existe la base de datos {bd}."]
    sys.path.insert(0, str(codigo))
    try:
        from app import db  # el código que se va a desplegar
    finally:
        sys.path.pop(0)

    with tempfile.TemporaryDirectory(prefix="guilda-migraciones-") as tmp:
        copia = Path(tmp) / "registro.db"
        origen = sqlite3.connect(f"file:{bd}?mode=ro", uri=True)
        destino = sqlite3.connect(copia)
        origen.backup(destino)  # API de copia de SQLite: segura con la base en uso
        origen.close()
        destino.close()

        antes_conn = sqlite3.connect(copia)
        filas_antes, columnas_antes = _tablas(antes_conn), _columnas(antes_conn)
        fk_antes = len(antes_conn.execute("PRAGMA foreign_key_check").fetchall())
        antes_conn.close()

        db.DB_PATH = copia
        inicio = time.time()
        try:
            db.init_db()
            db.init_db()
        except Exception as e:  # noqa: BLE001
            return [f"init_db() falla sobre una copia de la base real: {type(e).__name__}: {e}"]
        duracion = time.time() - inicio

        despues = sqlite3.connect(copia)
        filas_despues, columnas_despues = _tablas(despues), _columnas(despues)
        integridad = despues.execute("PRAGMA integrity_check").fetchone()[0]
        fk_despues = len(despues.execute("PRAGMA foreign_key_check").fetchall())
        despues.close()

        if integridad != "ok":
            problemas.append(f"integrity_check: {integridad}")
        if fk_despues > fk_antes:
            problemas.append(f"{fk_despues - fk_antes} violaciones nuevas de claves ajenas tras migrar")
        for tabla, n in filas_antes.items():
            if tabla not in filas_despues:
                problemas.append(f"la tabla «{tabla}» ha desaparecido")
            elif filas_despues[tabla] < n:
                problemas.append(f"la tabla «{tabla}» ha perdido filas ({n} → {filas_despues[tabla]})")
            elif columnas_antes[tabla] - columnas_despues[tabla]:
                problemas.append(f"la tabla «{tabla}» ha perdido columnas: {sorted(columnas_antes[tabla] - columnas_despues[tabla])}")

        nuevas = sorted(set(filas_despues) - set(filas_antes))
        cols_nuevas = {t: sorted(columnas_despues[t] - columnas_antes[t]) for t in columnas_antes if t in columnas_despues and columnas_despues[t] - columnas_antes[t]}
        print(f"Migraciones sobre copia de {bd.name}: {len(filas_antes)} tablas, {sum(filas_antes.values())} filas, {duracion:.1f} s")
        print(f"  tablas nuevas: {', '.join(nuevas) or 'ninguna'}")
        for t, c in cols_nuevas.items():
            print(f"  columnas nuevas en {t}: {', '.join(c)}")
    return problemas


def main() -> int:
    raiz = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--bd", type=Path, default=raiz / "data" / "registro.db")
    parser.add_argument("--codigo", type=Path, default=raiz)
    args = parser.parse_args()
    problemas = comprobar(args.bd.resolve(), args.codigo.resolve())
    if problemas:
        print("MIGRACIÓN NO SEGURA:", file=sys.stderr)
        for p in problemas:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("OK: las migraciones se aplican bien (dos veces seguidas) y no se pierde nada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
