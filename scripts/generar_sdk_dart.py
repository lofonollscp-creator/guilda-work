"""Genera el SDK de Dart de la app móvil (`mobile/lib/api/generado/`) del contrato OpenAPI de esta misma app.

    scripts/probar.sh --ejecutar scripts/generar_sdk_dart.py            # regenera los ficheros versionados
    scripts/probar.sh --ejecutar scripts/generar_sdk_dart.py --comprobar  # falla si lo versionado está desfasado (deriva)

Corre en la copia aislada de `probar.sh` (nunca toca datos reales); el destino por defecto se resuelve contra el repo real con
`GUILDA_SDK_DART_DESTINO` (la copia se borra al terminar, así que sin él lo generado se perdería). Con `--spec fichero.json` usa un
OpenAPI ya guardado y no arranca la app."""
import argparse
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from app import sdk_dart  # noqa: E402


def _spec(ruta: str | None) -> dict:
    if ruta:
        return json.loads(Path(ruta).read_text())
    # Los esquemas de las entidades salen de las columnas REALES de las tablas: hace falta una base de datos con el esquema creado
    # (vacía y desechable; nunca la de producción).
    import tempfile
    from app import db, openapi
    with tempfile.TemporaryDirectory(prefix="guilda-sdk-dart.") as tmp:
        db.DB_PATH = Path(tmp) / "sdk.db"
        db.BACKUPS_DIR = Path(tmp) / "backups"
        db.init_db()
        from app.main import app as flask_app
        flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
        with flask_app.test_request_context():
            return openapi.generar_spec()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spec", help="OpenAPI ya guardado (por defecto, el de la app)")
    ap.add_argument("--destino", default=os.environ.get("GUILDA_SDK_DART_DESTINO") or str(RAIZ / "mobile/lib/api/generado"))
    ap.add_argument("--comprobar", action="store_true", help="no escribe: sale con 1 si lo versionado difiere")
    a = ap.parse_args()
    spec = _spec(a.spec)
    ficheros = sdk_dart.generar(spec)
    destino = Path(a.destino)
    if a.comprobar:
        desfasados = [n for n, c in ficheros.items() if not (destino / n).exists() or (destino / n).read_text() != c]
        if desfasados:
            print("SDK Dart desfasado: " + ", ".join(desfasados) + ". Regenéralo con scripts/generar_sdk_dart.py", file=sys.stderr)
            return 1
        print("SDK Dart al día", file=sys.stderr)
        return 0
    destino.mkdir(parents=True, exist_ok=True)
    for nombre, contenido in ficheros.items():
        (destino / nombre).write_text(contenido)
    print(sdk_dart.resumen(spec), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
