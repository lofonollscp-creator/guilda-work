#!/usr/bin/env python3
"""Simulacro de desastre y recuperación de la base de datos de la aplicación (fase 10; docs/runbooks-postgresql.md). De extremo a extremo y en contenedores DESECHABLES:

  1. levanta una instancia con la MISMA configuración que producción (docker-compose.postgres-app.yml: archivo de WAL, wal_level, etc.) y le carga datos sintéticos de 3 despachos;
  2. copia base (scripts/backup_postgres.sh base), más actividad, un punto de restauración de Citus y la hora exacta «antes del desastre»;
  3. DESASTRE: se borra todo lo del despacho 1 y las notas del 3; el despacho 2 sigue trabajando (30 notas legítimas posteriores);
  4. recuperación a un instante, dos veces (por punto de restauración y por hora) con scripts/restaurar_postgres.sh: la instancia restaurada debe tener los tres despachos como antes;
  5. recuperación de UN despacho: se exporta el 1 y el 3 de la instancia restaurada y se importan en la viva (scripts/copia_despacho.py): los dos vuelven y el 2 conserva sus 30 notas posteriores.

Mide cada paso (RTO) y guarda el informe. No toca producción ni la instancia de ensayo. Se ejecuta desde la copia aislada:

  scripts/probar.sh --ejecutar scripts/simulacro_restauracion_pg.py [--informe RUTA.json] [--conservar]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

IMAGEN = os.environ.get("PG_IMAGEN", "guilda-work-citus:ensayo")
VIVA, PUERTO_VIVA = "guilda-pg-simulacro", 55450
CLAVE = "simulacro"
URL_VIVA = f"postgresql://guilda:{CLAVE}@127.0.0.1:{PUERTO_VIVA}/guilda"


def sh(*args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def esperar(condicion, segundos, que):
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        try:
            if condicion():
                return
        except Exception:                                                                            # noqa: BLE001
            pass
        time.sleep(1)
    raise SystemExit(f"tiempo agotado esperando: {que}")


def banderas_de_produccion() -> list[str]:
    """Los `-c ...` del contenedor de producción, tal cual (para que el simulacro pruebe la configuración real), con la memoria acotada."""
    import yaml
    orden = yaml.safe_load((RAIZ / "docker-compose.postgres-app.yml").read_text())["services"]["postgres-app"]["command"]
    return orden + ["-c", "shared_buffers=128MB", "-c", "effective_cache_size=512MB", "-c", "max_connections=100"]


def cuentas(url: str) -> dict:
    import psycopg
    with psycopg.connect(url, autocommit=True) as c:
        return {t: {"notas": c.execute("SELECT count(*) FROM notas WHERE tenant_id = %s", (t,)).fetchone()[0],
                    "tareas": c.execute("SELECT count(*) FROM tareas_outlook WHERE tenant_id = %s", (t,)).fetchone()[0],
                    "correo": c.execute("SELECT count(*) FROM correo_mensajes WHERE tenant_id = %s", (t,)).fetchone()[0]} for t in (1, 2, 3)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--informe", default=str(RAIZ / "data" / "pg-ensayo" / "simulacro-restauracion.json"))
    ap.add_argument("--conservar", action="store_true", help="no borra contenedores ni carpetas al terminar")
    ap.add_argument("--carpeta", default=None, help="carpeta de trabajo (por defecto en /var/tmp: el /tmp del servidor es pequeño)")
    args = ap.parse_args()

    import psycopg
    from app.bd import despacho_copia as dc
    from app.bd import esquema, migrar_datos, tenant
    from app.bd import postgres as pg

    trabajo = Path(args.carpeta or tempfile.mkdtemp(prefix="guilda-simulacro-", dir="/var/tmp"))
    (trabajo / "wal").mkdir(parents=True, exist_ok=True)
    (trabajo / "base").mkdir(exist_ok=True)
    os.chmod(trabajo / "wal", 0o777)
    os.chmod(trabajo / "base", 0o777)
    informe: dict = {"pasos": {}, "ok": False}
    medidas = informe["pasos"]
    restaurada = "guilda-pg-simulacro-rest"
    try:
        for n in (VIVA, restaurada):
            sh("docker", "rm", "-f", "-v", n)
        sh("docker", "volume", "rm", f"{restaurada}-datos")
        # 1. la instancia «de producción»
        t0 = time.monotonic()
        r = sh("docker", "run", "-d", "--name", VIVA, "--memory", "1g", "--shm-size", "256m", "-p", f"127.0.0.1:{PUERTO_VIVA}:5432", "-e", "POSTGRES_USER=guilda",
               "-e", f"POSTGRES_PASSWORD={CLAVE}", "-e", "POSTGRES_DB=guilda", "-e", "POSTGRES_INITDB_ARGS=--encoding=UTF8 --data-checksums",
               "-v", f"{trabajo}/wal:/backup/wal", "-v", f"{trabajo}/base:/backup/base", IMAGEN, *banderas_de_produccion())
        if r.returncode:
            raise SystemExit(f"no se pudo arrancar la instancia: {r.stderr}")
        esperar(lambda: sh("docker", "exec", VIVA, "pg_isready", "-h", "127.0.0.1", "-U", "guilda", "-d", "guilda").returncode == 0, 120, "la instancia")
        time.sleep(3)
        with psycopg.connect(URL_VIVA, autocommit=True) as c:
            for e in ("citus", "unaccent", "pg_trgm"):
                c.execute(f"CREATE EXTENSION IF NOT EXISTS {e}")
            c.execute("SELECT citus_set_coordinator_host('localhost', 5432)")
            c.execute("SELECT citus_set_node_property('localhost', 5432, 'shouldhaveshards', true)")
        pg.fijar_url(URL_VIVA)
        conn = pg.conectar()
        esquema.crear_si_falta(conn, "citus")
        conn.close()
        pg.cerrar_pool()
        # datos sintéticos: se siembran en SQLite con el generador de la prueba de carga y se migran con la herramienta de la fase 8
        from app import db
        import prueba_carga
        db.DB_PATH = trabajo / "semilla.db"
        db.BACKUPS_DIR = trabajo / "bk"
        db.init_db()
        prueba_carga.sembrar(db, 9, 300, 20, 3)
        with psycopg.connect(URL_VIVA, autocommit=True) as admin:
            res: dict = {}
            migrar_datos.copiar(db.DB_PATH, admin, informe=res)
            if not res["ok"]:
                raise SystemExit(f"la migración de datos de prueba no cuadra: {res['discrepancias'][:3]}")
        base0 = cuentas(URL_VIVA)
        medidas["1_instancia_y_datos"] = {"segundos": round(time.monotonic() - t0, 1), "datos": base0}

        entorno = {**os.environ, "PG_CONTENEDOR": VIVA, "PG_BASE": "guilda", "GUILDA_PG_BACKUPS": str(trabajo), "PG_PERMITIR_MISMO_DISCO": "1",
                   "GUILDA_BACKUPS_DIR": str(trabajo / "estado"), "GUILDA_ENV_FILE": "/nonexistent"}
        # 2. copia base, más actividad, punto de restauración
        t0 = time.monotonic()
        r = subprocess.run([str(RAIZ / "scripts" / "backup_postgres.sh"), "todo"], env=entorno, capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"backup_postgres.sh falló: {r.stdout}{r.stderr}")
        bases = sorted((trabajo / "base").glob("base-*.tar.gz"))
        medidas["2_copia_base"] = {"segundos": round(time.monotonic() - t0, 1), "mb": round(bases[-1].stat().st_size / 1e6, 1), "salida": r.stdout.strip().splitlines()[0]}
        # retención: dos copias base más y «limpiar» conservando solo 2: la más antigua se retira y con ella el WAL anterior a la que ahora es la más antigua
        with psycopg.connect(URL_VIVA, autocommit=True) as c:
            usuario2 = c.execute("SELECT usuario_id FROM usuarios_tenants WHERE tenant_id = 2 LIMIT 1").fetchone()[0]
            for k in range(2):
                for i in range(20):
                    c.execute("INSERT INTO notas (tenant_id, usuario_id, texto, creada_en) VALUES (2, %s, %s, 'x')", (usuario2, f"entre copias {k}-{i}"))
                time.sleep(1.2)
                r = subprocess.run([str(RAIZ / "scripts" / "backup_postgres.sh"), "base"], env=entorno, capture_output=True, text=True)
                if r.returncode:
                    raise SystemExit(f"backup_postgres.sh base falló: {r.stdout}{r.stderr}")
        wal_antes = len(list((trabajo / "wal").glob("0*")))
        r = subprocess.run([str(RAIZ / "scripts" / "backup_postgres.sh"), "limpiar"], env={**entorno, "PG_BASES_CONSERVADAS": "2"}, capture_output=True, text=True)
        bases = sorted((trabajo / "base").glob("base-*.tar.gz"))
        wal_despues = len(list((trabajo / "wal").glob("0*")))
        inicial_mas_antigua = json.loads(Path(f"{bases[0]}.json").read_text())["wal_inicial"]
        assert len(bases) == 2 and wal_despues < wal_antes and (trabajo / "wal" / inicial_mas_antigua).exists() and r.returncode == 0, (bases, wal_antes, wal_despues, r.stdout, r.stderr)
        medidas["2b_retencion"] = {"bases_que_quedan": len(bases), "wal_antes": wal_antes, "wal_despues": wal_despues}
        with psycopg.connect(URL_VIVA, autocommit=True) as c:
            for i in range(50):
                c.execute("INSERT INTO notas (tenant_id, usuario_id, texto, creada_en) VALUES (2, %s, %s, 'x')", (usuario2, f"antes del desastre {i}"))
            time.sleep(2)
            c.execute("SELECT citus_create_restore_point('antes_del_desastre')")
            hora_buena = c.execute("SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US') || '+00'").fetchone()[0]
            time.sleep(2)
        antes = cuentas(URL_VIVA)
        # 3. el desastre
        pg.fijar_url(URL_VIVA)
        conn = pg.conectar()
        conn.modo_secuencial()
        tenant.borrar_filas_de_tenant(conn, 1)
        conn.execute("DELETE FROM notas WHERE tenant_id = 3")
        conn.commit()
        conn.close()
        pg.cerrar_pool()
        with psycopg.connect(URL_VIVA, autocommit=True) as c:
            for i in range(30):
                c.execute("INSERT INTO notas (tenant_id, usuario_id, texto, creada_en) VALUES (2, %s, %s, 'x')", (usuario2, f"posterior al desastre {i}"))
            c.execute("SELECT pg_switch_wal()")
            esperar(lambda: c.execute("SELECT last_archived_wal >= pg_walfile_name(pg_current_wal_lsn() - 16777216) FROM pg_stat_archiver").fetchone()[0], 60, "el archivo del WAL")
            time.sleep(1)
            c.execute("SELECT pg_switch_wal()")
            time.sleep(6)
        despues = cuentas(URL_VIVA)
        informe["desastre"] = {"antes": antes, "despues": despues}
        assert despues[1] == {"notas": 0, "tareas": 0, "correo": 0} and despues[3]["notas"] == 0 and despues[2]["notas"] == antes[2]["notas"] + 30, despues

        # 4. recuperación a un instante: por punto y por hora
        scr = str(RAIZ / "scripts" / "restaurar_postgres.sh")
        for clave, opciones in (("punto", ["--punto", "antes_del_desastre"]), ("hora", ["--hasta", hora_buena]),
                                ("copia_mas_antigua", ["--punto", "antes_del_desastre", "--base", str(bases[0])])):
            t0 = time.monotonic()
            r = subprocess.run([scr, "instancia", *opciones, "--puerto", "55451", "--nombre", restaurada, "--memoria", "1g"], env=entorno, capture_output=True, text=True)
            segundos = round(time.monotonic() - t0, 1)
            if r.returncode:
                raise SystemExit(f"restaurar_postgres.sh ({clave}) falló: {r.stdout[-400:]}{r.stderr[-400:]}")
            url_rest = f"postgresql://guilda:{CLAVE}@127.0.0.1:55451/guilda"
            esperar(lambda: psycopg.connect(url_rest).close() or True, 30, "conectar con la instancia restaurada")
            recuperado = cuentas(url_rest)
            igual = recuperado == antes
            medidas[f"4_recuperacion_por_{clave}"] = {"segundos": segundos, "igual_que_antes_del_desastre": igual, "datos": recuperado}
            if not igual:
                raise SystemExit(f"la instancia restaurada ({clave}) no coincide: {recuperado} frente a {antes}")
            if clave == "punto":
                # 5. recuperar solo los despachos 1 y 3 en la instancia viva, desde la restaurada
                t1 = time.monotonic()
                with psycopg.connect(url_rest, autocommit=True) as origen:
                    for d in (1, 3):
                        dc.exportar(origen, d, str(trabajo / f"despacho-{d}.tar.gz"))
                t_exp = round(time.monotonic() - t1, 1)
                t1 = time.monotonic()
                with psycopg.connect(URL_VIVA, autocommit=True) as viva:
                    resultados = {d: dc.importar(viva, str(trabajo / f"despacho-{d}.tar.gz"), reemplazar=True) for d in (1, 3)}
                t_imp = round(time.monotonic() - t1, 1)
                final = cuentas(URL_VIVA)
                correcto = (final[1] == antes[1] and final[3] == antes[3] and final[2]["notas"] == antes[2]["notas"] + 30 and all(x["ok"] for x in resultados.values()))
                medidas["5_recuperar_dos_despachos"] = {"exportar_s": t_exp, "importar_s": t_imp, "correcto": correcto, "final": final,
                                                        "filas": {d: sum(x["tablas"].values()) for d, x in resultados.items()}}
                if not correcto:
                    raise SystemExit(f"la recuperación por despacho no coincide: {final}")
            sh(scr, "quitar", restaurada)
        # 6. las alertas del panel Salud, con el rol real de la plataforma (pg_monitor): se rompe el archivo de WAL y la copia base envejece
        from app import salud_postgres as sp
        with psycopg.connect(URL_VIVA, autocommit=True) as admin:
            admin.execute("ALTER ROLE guilda_plataforma PASSWORD 'x'")
        url_plat = f"postgresql://guilda_plataforma:x@127.0.0.1:{PUERTO_VIVA}/guilda"
        estado_json = trabajo / "estado" / "pg_estado.json"

        def panel():
            with psycopg.connect(url_plat, autocommit=True) as c:
                return {i["clave"]: i for i in sp.comprobaciones(c, ruta_estado=estado_json)}
        sano = panel()
        alertas = {"antes": {k: sano[k]["estado"] for k in ("pg_archivo_wal", "pg_copia_base", "pg_conexiones", "pg_bloqueos")}}
        assert all(v == sp.VERDE for v in alertas["antes"].values()), sano
        # (el destino del archivo se hace ilegible: los parámetros dados con -c en la línea de órdenes no se pueden cambiar con ALTER SYSTEM)
        with psycopg.connect(URL_VIVA, autocommit=True) as admin:
            sh("docker", "exec", "-u", "root", VIVA, "chmod", "000", "/backup/wal")
            admin.execute("INSERT INTO notas (tenant_id, usuario_id, texto, creada_en) VALUES (2, %s, 'fuerza WAL', 'x')", (usuario2,))
            admin.execute("SELECT pg_switch_wal()")
            esperar(lambda: panel()["pg_archivo_wal"]["estado"] == sp.ROJO, 120, "la alerta de archivo de WAL")
            alertas["archivo_roto"] = panel()["pg_archivo_wal"]
            sh("docker", "exec", "-u", "root", VIVA, "chmod", "777", "/backup/wal")
            esperar(lambda: panel()["pg_archivo_wal"]["estado"] == sp.VERDE, 180, "que el archivo de WAL se recupere")
            alertas["archivo_recuperado"] = panel()["pg_archivo_wal"]["estado"]
        import datetime as _dt
        e = json.loads(estado_json.read_text())
        e["ultimo_ok"] = (_dt.datetime.now() - _dt.timedelta(days=4)).isoformat(timespec="seconds")
        estado_json.write_text(json.dumps(e))
        alertas["copia_vieja"] = panel()["pg_copia_base"]["estado"]
        assert alertas["archivo_roto"]["estado"] == sp.ROJO and alertas["copia_vieja"] == sp.ROJO
        medidas["6_alertas"] = {"archivo_roto": alertas["archivo_roto"]["detalle"], "archivo_recuperado": alertas["archivo_recuperado"], "copia_de_hace_4_dias": alertas["copia_vieja"]}
        informe["ok"] = True
        return 0
    finally:
        informe["fecha"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        destino = Path(args.informe)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(informe, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(json.dumps({k: v for k, v in informe["pasos"].items()}, ensure_ascii=False, indent=1, default=str))
        print("RESULTADO:", "TODO CORRECTO" if informe["ok"] else "FALLÓ", "· informe:", destino)
        if not args.conservar:
            for n in (VIVA, restaurada):
                sh("docker", "rm", "-f", "-v", n)
            sh("docker", "volume", "rm", f"{restaurada}-datos")
            shutil.rmtree(trabajo, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
