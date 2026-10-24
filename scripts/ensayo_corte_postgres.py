#!/usr/bin/env python3
"""ENSAYO GENERAL del corte a PostgreSQL y de la vuelta atrás (fase 11), con una copia de los datos reales y tiempos medidos. No toca producción ni sus servicios: lee los SQLite reales con la
API de copia (solo lectura), trabaja en una carpeta temporal y en una base del contenedor de ensayo (`gw_corte`), y lo borra todo al terminar.

Cada pasada hace lo que se hará de verdad, en este orden:
  1. copia final de registro.db y backoffice.db (API de copia de SQLite)               [en el corte: con los servicios parados]
  2. pruebas de humo sobre SQLite + instantánea de recuentos de cada tabla               [referencia]
  3. migración a PostgreSQL + Citus (scripts/migrar_a_postgres.py, con backoffice.db) y sus controles
  4. pruebas de humo sobre PostgreSQL (rol sin privilegios, pantallas, RLS, Citus) + recuentos iguales a SQLite
  5. «el día después»: la aplicación escribe (notas, tareas y una nota de administración) ya sobre PostgreSQL
  6. VUELTA ATRÁS: scripts/exportar_a_sqlite.py → registro.db y backoffice.db nuevos desde PostgreSQL, con sus comprobaciones
  7. pruebas de humo sobre el SQLite recuperado: mismos recuentos que PostgreSQL y las escrituras del paso 5 presentes

  scripts/probar.sh --ejecutar scripts/ensayo_corte_postgres.py [--pasadas 2] [--url postgresql://guilda:ensayo@127.0.0.1:55432/postgres] [--datos /home/guilda/guilda-work/data] [--informe RUTA]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BASE = "gw_corte"
CLAVES = {"guilda_app": "corte-app", "guilda_plataforma": "corte-plataforma", "guilda_backoffice": "corte-bo"}

ESCRIBIR = r'''
import json, sys
sys.path.insert(0, ".")
from app import bd, db, kratos
from app.auth import limiter
from app.main import app
conn = db.get_connection(plataforma=True) if bd.MOTOR == "postgres" else db.get_connection()
personas = {}
for fila in conn.execute("SELECT id, email, kratos_identity_id, tenant_id FROM usuarios WHERE tenant_id IS NOT NULL AND kratos_identity_id IS NOT NULL ORDER BY id").fetchall():
    personas.setdefault(fila["tenant_id"], dict(fila))
conn.close()
por_cookie = {p["kratos_identity_id"]: p["email"] for p in personas.values()}
kratos.whoami = lambda cookies: ({"active": True, "identity": {"id": cookies.get("ory_kratos_session"), "traits": {"email": por_cookie[cookies.get("ory_kratos_session")]}}} if cookies.get("ory_kratos_session") in por_cookie else None)
limiter.enabled = False
app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000", PROPAGATE_EXCEPTIONS=False)
hechas = {"notas": 0, "tareas": 0, "fallos": []}
for d, p in list(personas.items())[:10]:
    cli = app.test_client()
    cli.set_cookie("ory_kratos_session", p["kratos_identity_id"], domain="127.0.0.1")
    r = cli.post("/notas", data={"texto": f"nota tras el corte {d}"})
    if r.status_code < 400: hechas["notas"] += 1
    else: hechas["fallos"].append(f"nota {d}: {r.status_code}")
    r = cli.post("/tareas/", data={"asunto": f"tarea tras el corte {d} ~1h"})
    if r.status_code < 400: hechas["tareas"] += 1
    else: hechas["fallos"].append(f"tarea {d}: {r.status_code}")
from backoffice import auth
bo = auth.conectar()
bo.execute("INSERT INTO notas_tenant (tenant_id, texto, admin_usuario, creado_en) VALUES (?, 'nota de administración tras el corte', 'ensayo', ?)", (next(iter(personas), 1), db.now_iso()))
bo.commit(); bo.close()
print(json.dumps(hechas))
'''


def ejecutar(orden, entorno=None, ok=(0,), nombre="") -> subprocess.CompletedProcess:
    r = subprocess.run(orden, cwd=RAIZ, env=entorno or os.environ, capture_output=True, text=True)
    if r.returncode not in ok:
        raise SystemExit(f"FALLÓ {nombre or orden[1]}:\n{r.stdout[-1800:]}\n{r.stderr[-1800:]}")
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pasadas", type=int, default=2)
    ap.add_argument("--url", default="postgresql://guilda:ensayo@127.0.0.1:55432/postgres", help="superusuario del contenedor de ensayo (base «postgres»)")
    ap.add_argument("--datos", default="/home/guilda/guilda-work/data", help="carpeta con registro.db y backoffice.db REALES (solo se leen)")
    ap.add_argument("--informe", default=str(RAIZ / "data" / "pg-ensayo" / "ensayo-corte.json"))
    ap.add_argument("--sintetico", type=int, default=0, metavar="PERSONAS", help="en vez de la copia real, datos sintéticos de la prueba de carga: PERSONAS personas en PERSONAS/3 despachos (mide el corte a otra escala)")
    ap.add_argument("--conservar", action="store_true")
    args = ap.parse_args()

    import psycopg
    from psycopg.conninfo import make_conninfo
    trabajo = Path(tempfile.mkdtemp(prefix="guilda-ensayo-corte-", dir="/var/tmp"))
    os.chmod(trabajo, 0o700)
    datos = RAIZ / "data"
    datos.mkdir(exist_ok=True)
    url_base = make_conninfo(args.url, dbname=BASE)
    url = lambda rol: make_conninfo(url_base, user=rol, password=CLAVES[rol])             # noqa: E731
    entorno_pg = {**os.environ, "GUILDA_DB_ENGINE": "postgres", "GUILDA_PG_ESQUEMA": "citus", "GUILDA_PG_POOL_MAX": "12", "GUILDA_DATABASE_URL": url("guilda_app"),
                  "GUILDA_DATABASE_URL_PLATAFORMA": url("guilda_plataforma"), "GUILDA_DATABASE_URL_BACKOFFICE": url("guilda_backoffice")}
    entorno_sqlite = {**os.environ, "GUILDA_DB_ENGINE": "sqlite"}
    informe: dict = {"pasadas": [], "ok": False}
    try:
        for n in range(1, args.pasadas + 1):
            p: dict = {"pasada": n, "pasos": {}}
            informe["pasadas"].append(p)
            pasos = p["pasos"]
            for f in datos.glob("*.db*"):
                f.unlink()

            def paso(clave, fn):
                t0 = time.monotonic()
                resultado = fn()
                pasos[clave] = {"segundos": round(time.monotonic() - t0, 1), **(resultado or {})}
                print(f"[pasada {n}] {clave}: {pasos[clave]['segundos']} s", flush=True)

            # 1. copia final
            def copiar():
                if args.sintetico:
                    ejecutar([sys.executable, "-c", f"import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'scripts'); from app import db; import prueba_carga; db.init_db(); "
                              f"prueba_carga.sembrar(db, {args.sintetico}, 30000, 60, max(1, {args.sintetico} // 3)); from backoffice import auth; auth.crear_admin('ensayo', 'contrasena-larga-de-ensayo-1', 'Ensayo')"],
                             entorno_sqlite, nombre="datos sintéticos")
                    return {"registro_mb": round((datos / "registro.db").stat().st_size / 1e6, 1), "sintetico": args.sintetico}
                for nombre in ("registro.db", "backoffice.db"):
                    origen = sqlite3.connect(f"file:{args.datos}/{nombre}?mode=ro", uri=True)
                    destino = sqlite3.connect(datos / nombre)
                    origen.backup(destino)
                    destino.execute("PRAGMA journal_mode = DELETE")
                    destino.close()
                    origen.close()
                return {"registro_mb": round((datos / "registro.db").stat().st_size / 1e6, 1)}
            paso("1_copia_final", copiar)

            # 1b. el código nuevo, ya desplegado con el motor SQLite, arranca una vez y deja el esquema al día (init_db es idempotente): es el paso 0 del corte real
            def esquema_al_dia():
                t0 = time.monotonic()
                ejecutar([sys.executable, "-c", "import sys; sys.path.insert(0, '.'); from app import db; db.init_db()"], entorno_sqlite, nombre="init_db sobre la copia")
                return {}
            paso("1b_init_db_con_el_codigo_nuevo", esquema_al_dia)

            # 2. humo sobre SQLite
            antes = trabajo / f"antes-{n}.json"
            def humo_sqlite():
                r = ejecutar([sys.executable, "scripts/humo_postgres.py", "--instantanea", str(antes)], entorno_sqlite, nombre="humo sobre SQLite")
                return {"resumen": r.stdout.strip().splitlines()[-1]}
            paso("2_humo_sqlite", humo_sqlite)

            # 3. migración (la base de ensayo se crea de nuevo)
            def migrar():
                informe_m = trabajo / f"migracion-{n}.json"
                r = ejecutar([sys.executable, "scripts/migrar_a_postgres.py", "--origen", str(datos / "registro.db"), "--url", url_base, "--recrear-base", "--informe", str(informe_m)],
                             entorno_sqlite, ok=(0,), nombre="migración")
                with psycopg.connect(url_base, autocommit=True) as c:
                    for rol, clave in CLAVES.items():
                        c.execute(f"ALTER ROLE {rol} PASSWORD '{clave}'")
                    c.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
                m = json.loads(informe_m.read_text())
                return {"filas": m["filas"], "controles_ok": m["ok"], "backoffice_filas": sum(t["destino"] for t in (m.get("backoffice") or {}).get("tablas", {}).values()), "segundos_controles": m["segundos"]}
            paso("3_migracion", migrar)
            assert pasos["3_migracion"]["controles_ok"]

            # 4. humo sobre PostgreSQL, comparando con SQLite
            def humo_pg():
                r = ejecutar([sys.executable, "scripts/humo_postgres.py", "--comparar", str(antes)], entorno_pg, nombre="humo sobre PostgreSQL")
                return {"resumen": r.stdout.strip().splitlines()[-1]}
            paso("4_humo_postgres", humo_pg)

            # 5. el día después
            def escribir():
                r = ejecutar([sys.executable, "-c", ESCRIBIR], entorno_pg, nombre="escrituras tras el corte")
                hechas = json.loads(r.stdout.strip().splitlines()[-1])
                if hechas["fallos"] or not hechas["notas"]:
                    raise SystemExit(f"las escrituras de prueba fallaron: {hechas}")
                return hechas
            paso("5_escrituras_tras_el_corte", escribir)
            despues = trabajo / f"despues-{n}.json"
            ejecutar([sys.executable, "scripts/humo_postgres.py", "--instantanea", str(despues)], entorno_pg, nombre="instantánea tras las escrituras")

            # 6. vuelta atrás
            vuelta = trabajo / f"vuelta-{n}"
            vuelta.mkdir()
            def volver():
                informe_e = vuelta / "informe.json"
                r = ejecutar([sys.executable, "scripts/exportar_a_sqlite.py", "--url", url_base, "--salida", str(vuelta / "registro.db"), "--backoffice-salida", str(vuelta / "backoffice.db"),
                              "--informe", str(informe_e)], entorno_pg, nombre="exportación inversa")
                e = json.loads(informe_e.read_text())
                return {"filas": sum(e["tablas"].values()), "ok": e["ok"], "integrity_check": e["integrity_check"], "foreign_key_check": e["foreign_key_check"],
                        "plataforma_conservadas": e["plataforma_conservadas"], "sin_exportar": e["sin_exportar"]}
            paso("6_exportar_a_sqlite", volver)
            assert pasos["6_exportar_a_sqlite"]["ok"]

            # 7. humo sobre el SQLite recuperado
            def humo_vuelta():
                for f in datos.glob("*.db*"):
                    f.unlink()
                shutil.copy(vuelta / "registro.db", datos / "registro.db")
                shutil.copy(vuelta / "backoffice.db", datos / "backoffice.db")
                r = ejecutar([sys.executable, "scripts/humo_postgres.py", "--comparar", str(despues)], entorno_sqlite, nombre="humo sobre el SQLite recuperado")
                lite = sqlite3.connect(datos / "registro.db")
                notas = lite.execute("SELECT count(*) FROM notas WHERE texto LIKE 'nota tras el corte%'").fetchone()[0]
                tareas = lite.execute("SELECT count(*) FROM tareas_outlook WHERE asunto LIKE 'tarea tras el corte%'").fetchone()[0]
                lite.close()
                bo = sqlite3.connect(datos / "backoffice.db")
                admin = bo.execute("SELECT count(*) FROM notas_tenant WHERE texto LIKE 'nota de administración tras el corte%'").fetchone()[0]
                bo.close()
                hechas = pasos["5_escrituras_tras_el_corte"]
                if (notas, tareas, admin) != (hechas["notas"], hechas["tareas"], 1):
                    raise SystemExit(f"la vuelta atrás perdió escrituras: notas {notas}/{hechas['notas']}, tareas {tareas}/{hechas['tareas']}, nota de administración {admin}/1")
                return {"resumen": r.stdout.strip().splitlines()[-1], "escrituras_recuperadas": {"notas": notas, "tareas": tareas, "nota_admin": admin}}
            paso("7_humo_sqlite_recuperado", humo_vuelta)
            p["total_segundos"] = round(sum(v["segundos"] for v in pasos.values()), 1)
            # ventana de corte real = 1 + 3 + 4 (+ reiniciar servicios); la vuelta atrás = 6 (+ 7)
            p["ventana_de_corte_segundos"] = round(pasos["1_copia_final"]["segundos"] + pasos["3_migracion"]["segundos"] + pasos["4_humo_postgres"]["segundos"], 1)
            p["vuelta_atras_segundos"] = pasos["6_exportar_a_sqlite"]["segundos"]
        informe["ok"] = True
        return 0
    finally:
        informe["fecha"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        destino = Path(args.informe)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(informe, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        os.chmod(destino, 0o600)
        for p in informe["pasadas"]:
            print(f"pasada {p['pasada']}: ventana de corte ≈ {p.get('ventana_de_corte_segundos', '?')} s · vuelta atrás ≈ {p.get('vuelta_atras_segundos', '?')} s")
        print("RESULTADO:", "TODO CORRECTO" if informe["ok"] else "FALLÓ", "· informe:", destino)
        if not args.conservar:
            for f in datos.glob("*.db*"):
                f.unlink()
            shutil.rmtree(trabajo, ignore_errors=True)
            subprocess.run([str(RAIZ / "scripts" / "pg_ensayo.sh"), "borrar", BASE], capture_output=True)


if __name__ == "__main__":
    sys.exit(main())
