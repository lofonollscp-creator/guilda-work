#!/usr/bin/env python3
"""Prueba de concurrencia de la API sobre PostgreSQL + Citus (PG-00 del plan, docs/plan-ux-ui-app-y-postgresql.md §D).

Varios clientes a la vez, cada uno con su token, piden endpoints de lectura y escriben notas con `Idempotency-Key`. Se exige **0 respuestas 5xx**.

Por qué existe: la aplicación escribía en cada petición en tablas que en Citus son **de referencia** (`tokens_api`, `tokens_api_uso`, `api_idempotencia`, `mcp_uso`); con peticiones simultáneas Citus
respondía `DeadlockDetected` («distributed deadlock») y la API devolvía 500: con 4 clientes el 7 %, con 12 el 65 %. La suite normal usa el esquema `multitenant` (sin tablas de referencia) y no podía verlo.

    scripts/probar.sh --ejecutar scripts/prueba_concurrencia_api.py --url postgresql://guilda:ensayo@127.0.0.1:55432/postgres
    ...  --hilos 4,8,12 --peticiones 40 --control        # --control repite con el volcado diferido APAGADO para enseñar el fallo antiguo (no cuenta para el resultado)

Siembra datos sintéticos en SQLite, los migra a una base de ensayo con Citus (`gw_carga`, se borra al terminar) y usa los roles SIN privilegios de la aplicación (con RLS).
Código de salida: 0 sin errores 5xx · 1 con errores · 2 no se pudo preparar."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))


def _escenario(app, tokens: list[str], hilos: int, peticiones: int) -> dict:
    lecturas = ("/api/v1/auth/me", "/api/v1/notas", "/api/v1/proyectos", "/api/v1/mi-dia", "/api/v1/tareas-outlook?limit=20", "/api/v1/notificaciones", "/api/v1/perfil")
    codigos: dict[int, int] = {}
    latencias: list[float] = []
    cerrojo = threading.Lock()
    salida = threading.Barrier(hilos)

    def trabajar(i: int):
        c = app.test_client()
        cab = {"Authorization": f"Bearer {tokens[i % len(tokens)]}"}
        salida.wait()
        for k in range(peticiones):
            t0 = time.perf_counter()
            if k % 8 == 7:                                                  # una de cada 8 escribe, con clave de idempotencia
                r = c.post("/api/v1/notas", json={"texto": f"nota {i}-{k}"}, headers={**cab, "Idempotency-Key": f"conc-{os.getpid()}-{hilos}-{i}-{k}"})
            else:
                r = c.get(lecturas[k % len(lecturas)], headers=cab)
            ms = (time.perf_counter() - t0) * 1000
            with cerrojo:
                codigos[r.status_code] = codigos.get(r.status_code, 0) + 1
                latencias.append(ms)

    t0 = time.perf_counter()
    hs = [threading.Thread(target=trabajar, args=(i,)) for i in range(hilos)]
    [h.start() for h in hs]
    [h.join(300) for h in hs]
    seg = time.perf_counter() - t0
    latencias.sort()
    n = sum(codigos.values())
    return {"hilos": hilos, "peticiones": n, "rps": round(n / seg, 1) if seg else 0, "p50_ms": round(statistics.median(latencias), 1) if latencias else None,
            "p95_ms": round(latencias[int(len(latencias) * 0.95) - 1], 1) if latencias else None, "codigos": codigos,
            "errores_5xx": sum(v for k, v in codigos.items() if k >= 500)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("GUILDA_TEST_PG_URL"), help="superusuario de PostgreSQL con Citus (base «postgres»)")
    ap.add_argument("--hilos", default="4,8,12", help="clientes simultáneos de cada escenario, separados por comas")
    ap.add_argument("--peticiones", type=int, default=40, help="peticiones por cliente")
    ap.add_argument("--pool", type=int, default=20)
    ap.add_argument("--control", action="store_true", help="repite con el diferido apagado para enseñar el fallo antiguo (informativo)")
    ap.add_argument("--json", help="guarda las cifras en este fichero")
    args = ap.parse_args(argv)
    if not args.url:
        ap.error("falta --url (o GUILDA_TEST_PG_URL)")
    args.esquema = "citus"
    os.environ.setdefault("GUILDA_USO_HILO", "0")

    import prueba_carga as pc
    # Los roles son del CLÚSTER: si esta prueba corre junto a la suite (tests/test_citus.py), las contraseñas tienen que ser las mismas que ellas esperan, o se pisan entre sí.
    pc.CLAVE_APP, pc.CLAVE_PLATAFORMA = "prueba-app", "prueba-plataforma"
    tmp = Path(tempfile.mkdtemp(prefix="guilda-conc-"))
    url_base = None
    try:
        from app import db
        db.DB_PATH = tmp / "conc.db"
        db.BACKUPS_DIR = tmp / "backups"
        db.init_db()
        hilos_max = max(int(x) for x in args.hilos.split(","))
        infos = pc.sembrar(db, max(12, hilos_max), 600, 20, 3)
        resultado: dict = {}
        try:
            url_base = pc.preparar_postgres(args, db, resultado)
        except Exception as e:                                               # noqa: BLE001
            print(f"No se pudo preparar la base de ensayo con Citus: {e}", file=sys.stderr)
            return 2
        tokens = [db.crear_token_api(i["usuario"], "concurrencia") for i in infos]
        from app.auth import limiter
        from app.main import app
        app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
        limiter.enabled = False
        c = app.test_client()
        for t in tokens:                                                     # calentamiento: cada persona entra una vez
            c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {t}"})
        salida: dict = {"esquema": "citus", "escenarios": [], "control": []}
        for h in (int(x) for x in args.hilos.split(",")):
            os.environ.pop("GUILDA_USO_DIFERIDO", None)                      # por defecto con PostgreSQL: diferido
            r = _escenario(app, tokens, h, args.peticiones)
            salida["escenarios"].append(r)
            print(f"  {h:>2} clientes: {r['peticiones']} peticiones · {r['rps']} rps · p50 {r['p50_ms']} ms · p95 {r['p95_ms']} ms · códigos {r['codigos']}")
        if args.control:
            os.environ["GUILDA_USO_DIFERIDO"] = "0"
            print("  --- control (volcado diferido APAGADO: el comportamiento antiguo) ---")
            for h in (int(x) for x in args.hilos.split(",")):
                r = _escenario(app, tokens, h, args.peticiones)
                salida["control"].append(r)
                print(f"  {h:>2} clientes: {r['peticiones']} peticiones · {r['rps']} rps · p95 {r['p95_ms']} ms · códigos {r['codigos']}")
            os.environ.pop("GUILDA_USO_DIFERIDO", None)
        from app import uso_diferido
        uso_diferido.volcar()
        errores = sum(e["errores_5xx"] for e in salida["escenarios"])
        salida["errores_5xx"] = errores
        if args.json:
            Path(args.json).write_text(json.dumps(salida, indent=1))
        print("RESULTADO:", "0 errores 5xx" if errores == 0 else f"{errores} respuestas 5xx")
        return 0 if errores == 0 else 1
    finally:
        try:
            from app.bd import postgres as pg
            pg.cerrar_pool()
            if url_base:
                import psycopg
                from psycopg.conninfo import make_conninfo
                with psycopg.connect(make_conninfo(args.url, dbname="postgres"), autocommit=True) as adm:
                    adm.execute('DROP DATABASE IF EXISTS gw_carga WITH (FORCE)')
        except Exception as e:                                               # noqa: BLE001
            print(f"(aviso) no se pudo borrar gw_carga: {e}", file=sys.stderr)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
