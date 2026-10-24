#!/usr/bin/env python3
"""Revisión de estabilización de la base de datos PostgreSQL + Citus con el tráfico REAL (fase 12): qué consultas cuestan, cuáles no van a un solo fragmento, qué tablas crecen o
acumulan basura, qué índices sobran, cómo están las copias y los errores de la aplicación. Solo LEE (estadísticas del servidor) y no necesita contraseñas nuevas: usa la URL de la plataforma
(que tiene `pg_monitor`), la misma del entorno de producción.

  sudo bash -c 'set -a; source /etc/guilda-work.env; set +a; runuser -u guilda --preserve-environment -- /home/guilda/guilda-work/.venv/bin/python /home/guilda/guilda-work/scripts/revision_postgres.py'
  scripts/revision_postgres.py --json /var/tmp/revision.json        # además, el informe en JSON
  scripts/revision_postgres.py --correo                             # y, si hay hallazgos, un aviso por correo (ALERTAS_ADMIN_EMAIL)

Los hallazgos son orientaciones para decidir, no órdenes: con poco tráfico las estadísticas todavía no dicen mucho. Tras `pg_stat_statements_reset()` (o un reinicio sin guardado) empiezan de cero."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Umbrales de hallazgo
MEDIA_LENTA_MS = 100            # consulta con media por encima de esto (y suficientes llamadas)
LLAMADAS_MINIMAS = 20
CACHE_MINIMA_PCT = 95
MUERTAS_PCT = 20                # filas muertas sobre vivas
INDICE_SIN_USO_BYTES = 8 << 20  # un índice sin lecturas de más de 8 MB sobra casi seguro
SEQ_SCANS = 200                 # recorridos secuenciales de una tabla grande
TABLA_GRANDE_FILAS = 20000


def fmt_bytes(n) -> str:
    n = float(n or 0)
    for u in ("B", "kB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def revisar(c) -> dict:
    r: dict = {"fecha": datetime.now().isoformat(timespec="seconds"), "hallazgos": []}
    h = r["hallazgos"]

    version, desde = c.execute("SELECT version(), pg_postmaster_start_time()").fetchone()
    base, tam, commits, rollbacks, hit, read, deadlocks, temp, reset = c.execute(
        "SELECT datname, pg_database_size(datname), xact_commit, xact_rollback, blks_hit, blks_read, deadlocks, temp_files, stats_reset FROM pg_stat_database WHERE datname = current_database()").fetchone()
    cache = 100 * hit / max(hit + read, 1)
    r["resumen"] = {"version": version.split(",")[0], "arrancado": str(desde)[:19], "base": base, "tamano": fmt_bytes(tam), "transacciones": int(commits), "rollbacks": int(rollbacks),
                    "acierto_cache_pct": round(cache, 2), "interbloqueos": int(deadlocks), "ficheros_temporales": int(temp), "estadisticas_desde": str(reset)[:19] if reset else None}
    if cache < CACHE_MINIMA_PCT and hit + read > 100000:
        h.append(f"Acierto de caché {cache:.1f} % (< {CACHE_MINIMA_PCT} %): valorar subir shared_buffers/memoria del contenedor.")
    if deadlocks:
        h.append(f"{deadlocks} interbloqueo(s) desde {str(reset)[:10]}: mirar el log de PostgreSQL (log_lock_waits) para ver qué sentencias chocan.")

    r["conexiones"] = [{"rol": u, "estado": e or "-", "sesiones": int(n)} for u, e, n in c.execute(
        "SELECT usename, state, count(*) FROM pg_stat_activity WHERE datname = current_database() AND backend_type = 'client backend' GROUP BY 1, 2 ORDER BY 1, 2").fetchall()]
    maxc = c.execute("SELECT current_setting('max_connections')::int").fetchone()[0]
    usadas = sum(x["sesiones"] for x in r["conexiones"])
    r["resumen"]["conexiones"] = f"{usadas} de {maxc}"

    # --- consultas ---
    try:
        filas = c.execute(
            "SELECT calls, round(total_exec_time::numeric / 1000, 1), round(mean_exec_time::numeric, 2), round(max_exec_time::numeric, 1), rows, left(regexp_replace(query, '\\s+', ' ', 'g'), 130) "
            "FROM pg_stat_statements WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database()) AND query NOT LIKE '%pg_stat_%' ORDER BY total_exec_time DESC LIMIT 15").fetchall()
        r["consultas_por_tiempo_total"] = [{"llamadas": int(a), "total_s": float(b), "media_ms": float(m), "max_ms": float(x), "filas": int(f), "sql": q} for a, b, m, x, f, q in filas]
        lentas = c.execute(
            "SELECT calls, round(mean_exec_time::numeric, 1), round(max_exec_time::numeric, 1), left(regexp_replace(query, '\\s+', ' ', 'g'), 130) FROM pg_stat_statements "
            "WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database()) AND calls >= %s AND mean_exec_time >= %s AND query NOT LIKE '%%pg_stat_%%' ORDER BY mean_exec_time DESC LIMIT 10",
            (LLAMADAS_MINIMAS, MEDIA_LENTA_MS)).fetchall()
        r["consultas_lentas"] = [{"llamadas": int(a), "media_ms": float(m), "max_ms": float(x), "sql": q} for a, m, x, q in lentas]
        for q in r["consultas_lentas"][:5]:
            h.append(f"Consulta lenta (media {q['media_ms']} ms en {q['llamadas']} llamadas): {q['sql'][:90]}…")
    except Exception as e:                                                                           # noqa: BLE001
        r["consultas_por_tiempo_total"] = []
        h.append(f"pg_stat_statements no disponible: {type(e).__name__}")

    # --- Citus: consultas que NO van a un solo fragmento ---
    try:
        multi = c.execute(
            "SELECT calls, left(regexp_replace(query, '\\s+', ' ', 'g'), 130) FROM citus_stat_statements WHERE partition_key IS NULL AND executor = 'adaptive' "
            "AND query NOT LIKE '%pg_%' AND query NOT LIKE '%citus_%' AND query NOT ILIKE 'SELECT%FROM%tenants%' ORDER BY calls DESC LIMIT 15").fetchall()
        r["multifragmento"] = [{"llamadas": int(a), "sql": q} for a, q in multi]
        habituales = [m for m in r["multifragmento"] if m["llamadas"] >= 20]
        if habituales:
            h.append(f"{len(habituales)} consulta(s) habituales tocan TODOS los fragmentos (sin tenant_id): conviene revisarlas; con varios nodos serían caras. Ejemplo: {habituales[0]['sql'][:90]}…")
        r["citus_nodos"] = [{"nodo": n, "activo": a, "con_fragmentos": f} for n, a, f in c.execute("SELECT nodename, isactive, shouldhaveshards FROM pg_dist_node ORDER BY nodeid").fetchall()]
    except Exception:                                                                                # noqa: BLE001
        r["multifragmento"] = None

    # --- tablas ---
    tablas = c.execute(
        "SELECT relname, n_live_tup, n_dead_tup, seq_scan, coalesce(idx_scan, 0), pg_total_relation_size(relid), last_autovacuum, last_autoanalyze FROM pg_stat_user_tables WHERE schemaname IN ('public', 'backoffice') "
        "ORDER BY pg_total_relation_size(relid) DESC LIMIT 400").fetchall()
    # los fragmentos de Citus se llaman tabla_NNNNNN: se suman a su tabla
    agrupadas: dict[str, dict] = {}
    for nombre, vivas, muertas, seq, idx, tam_t, av, aa in tablas:
        base_t = nombre.rsplit("_", 1)[0] if nombre.rsplit("_", 1)[-1].isdigit() and len(nombre.rsplit("_", 1)[-1]) >= 5 else nombre
        d = agrupadas.setdefault(base_t, {"vivas": 0, "muertas": 0, "seq": 0, "idx": 0, "bytes": 0, "av": None})
        d["vivas"] += vivas or 0
        d["muertas"] += muertas or 0
        d["seq"] += seq or 0
        d["idx"] += idx or 0
        d["bytes"] += tam_t or 0
        d["av"] = max([x for x in (d["av"], av) if x], default=None)
    r["tablas_mayores"] = [{"tabla": t, "filas": d["vivas"], "tamano": fmt_bytes(d["bytes"]), "muertas": d["muertas"]} for t, d in sorted(agrupadas.items(), key=lambda kv: -kv[1]["bytes"])[:15]]
    for t, d in agrupadas.items():
        if d["vivas"] >= 1000 and d["muertas"] > d["vivas"] * MUERTAS_PCT / 100:
            h.append(f"Tabla {t}: {d['muertas']} filas muertas sobre {d['vivas']} vivas (> {MUERTAS_PCT} %): autovacuum va por detrás.")
        if d["vivas"] >= TABLA_GRANDE_FILAS and d["seq"] >= SEQ_SCANS and d["seq"] > 3 * d["idx"]:
            h.append(f"Tabla {t}: {d['seq']} recorridos secuenciales frente a {d['idx']} por índice con {d['vivas']} filas: falta un índice.")
    # --- índices que no se usan ---
    sin_uso = c.execute(
        "SELECT s.relname, s.indexrelname, pg_relation_size(s.indexrelid) FROM pg_stat_user_indexes s JOIN pg_index i ON i.indexrelid = s.indexrelid "
        "WHERE s.idx_scan = 0 AND NOT i.indisunique AND NOT i.indisprimary AND s.schemaname IN ('public', 'backoffice') AND pg_relation_size(s.indexrelid) >= %s ORDER BY 3 DESC LIMIT 15", (INDICE_SIN_USO_BYTES,)).fetchall()
    r["indices_sin_uso"] = [{"tabla": t, "indice": i, "tamano": fmt_bytes(b)} for t, i, b in sin_uso]
    for x in r["indices_sin_uso"][:5]:
        h.append(f"Índice {x['indice']} ({x['tamano']}) sin ninguna lectura desde {str(reset)[:10]}: candidato a borrar (si el tráfico ya cubre un ciclo completo de uso).")

    # --- WAL y copias ---
    a = c.execute("SELECT current_setting('archive_mode'), archived_count, failed_count, last_archived_time, last_failed_time FROM pg_stat_archiver").fetchone()
    r["archivado_wal"] = {"modo": a[0], "archivados": int(a[1]), "fallos": int(a[2]), "ultimo": str(a[3])[:19] if a[3] else None}
    if a[0] != "on":
        h.append("El archivo de WAL está desactivado.")
    elif a[2] and a[4] and (not a[3] or a[4] > a[3]):
        h.append("El último intento de archivar WAL falló.")
    estado = Path(os.environ.get("GUILDA_BACKUPS_DIR") or Path(__file__).resolve().parent.parent / "data" / "backups") / "pg_estado.json"
    if estado.exists():
        e = json.loads(estado.read_text())
        r["copia_base"] = {k: e.get(k) for k in ("ultima_base", "ultimo_ok", "bases", "tamano_bases", "tamano_wal", "error")}
        if e.get("error"):
            h.append(f"La última copia base falló: {e['error']}")

    # --- aplicación ---
    try:
        err = c.execute("SELECT count(*) FILTER (WHERE creado_en >= to_char(now() - interval '1 day', 'YYYY-MM-DD\"T\"HH24:MI:SS')), count(*) FILTER (WHERE creado_en >= to_char(now() - interval '7 days', 'YYYY-MM-DD\"T\"HH24:MI:SS')) FROM errores_servidor").fetchone()
        r["errores_5xx"] = {"24h": int(err[0]), "7d": int(err[1])}
        if err[0] >= 10:
            h.append(f"{err[0]} errores 5xx en las últimas 24 h (panel Salud → errores del servidor).")
    except Exception:                                                                                # noqa: BLE001
        pass
    return r


def texto(r: dict) -> str:
    s = r["resumen"]
    L = [f"Revisión de PostgreSQL · {r['fecha']}", f"{s['version']} · base {s['base']} {s['tamano']} · arrancado {s['arrancado']} · estadísticas desde {s['estadisticas_desde']}",
         f"Conexiones {s['conexiones']} · caché {s['acierto_cache_pct']} % · {s['transacciones']:,} transacciones ({s['rollbacks']} rollbacks) · interbloqueos {s['interbloqueos']} · ficheros temporales {s['ficheros_temporales']}".replace(",", "."), ""]
    L.append("Sesiones: " + ", ".join(f"{x['rol']}/{x['estado']}={x['sesiones']}" for x in r["conexiones"]))
    if r.get("citus_nodos"):
        L.append("Citus: " + ", ".join(f"{n['nodo']} ({'activo' if n['activo'] else 'INACTIVO'})" for n in r["citus_nodos"]))
    L += ["", "Consultas por tiempo total:"]
    L += [f"  {q['llamadas']:>7}× media {q['media_ms']:>7.2f} ms · máx {q['max_ms']:>7.1f} ms · total {q['total_s']:>6.1f} s · {q['sql'][:100]}" for q in r["consultas_por_tiempo_total"][:10]]
    if r.get("multifragmento"):
        L += ["", "Consultas que tocan todos los fragmentos (las más llamadas):"] + [f"  {q['llamadas']:>7}× {q['sql'][:110]}" for q in r["multifragmento"][:6]]
    L += ["", "Tablas mayores (con sus fragmentos): " + "; ".join(f"{t['tabla']} {t['tamano']} ({t['filas']} filas)" for t in r["tablas_mayores"][:8])]
    if r.get("copia_base"):
        cb = r["copia_base"]
        L.append(f"Copia base: {cb['ultima_base']} ({cb['ultimo_ok']}), {cb['bases']} conservadas · WAL archivado: {r['archivado_wal']['archivados']} segmentos, {r['archivado_wal']['fallos']} fallos")
    if r.get("errores_5xx"):
        L.append(f"Errores 5xx de la aplicación: {r['errores_5xx']['24h']} en 24 h, {r['errores_5xx']['7d']} en 7 días")
    L += ["", "HALLAZGOS:" if r["hallazgos"] else "Sin hallazgos."] + [f"  · {x}" for x in r["hallazgos"]]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("GUILDA_DATABASE_URL_PLATAFORMA") or os.environ.get("GUILDA_PG_ADMIN_URL"), help="por defecto, la URL de la plataforma del entorno")
    ap.add_argument("--json", help="guardar también el informe en JSON")
    ap.add_argument("--correo", action="store_true", help="si hay hallazgos, enviarlos por correo (ALERTAS_ADMIN_EMAIL)")
    args = ap.parse_args(argv)
    if not args.url:
        ap.error("falta --url (o GUILDA_DATABASE_URL_PLATAFORMA en el entorno)")
    import psycopg
    with psycopg.connect(args.url, autocommit=True) as c:
        r = revisar(c)
    print(texto(r))
    if args.json:
        Path(args.json).write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        os.chmod(args.json, 0o600)
    if args.correo and r["hallazgos"]:
        from app import notificaciones_email
        notificaciones_email.enviar_alerta_interna(f"[Guilda Work] Revisión de PostgreSQL: {len(r['hallazgos'])} hallazgo(s)", texto(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
