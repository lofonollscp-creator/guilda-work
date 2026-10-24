#!/usr/bin/env python3
"""Pruebas de humo de la aplicación sobre la base de datos que diga el entorno (SQLite o PostgreSQL) con los datos REALES (fase 11). No escribe nada (las escrituras de prueba se deshacen).

  # tras el corte, con el entorno de producción (como el servicio):
  sudo -u guilda bash -c 'set -a; source /etc/guilda-work.env; set +a; cd /home/guilda/guilda-work && .venv/bin/python scripts/humo_postgres.py'
  scripts/humo_postgres.py --instantanea /var/tmp/antes.json        # recuentos por tabla (para comparar un motor con otro)
  scripts/humo_postgres.py --comparar /var/tmp/antes.json           # y los compara con una instantánea anterior

Comprueba: el motor y el rol con el que se conecta la aplicación · las pantallas principales de cada persona (hasta 3 por despacho) sin errores 5xx · una escritura de prueba por despacho
que se deshace · la búsqueda de texto · el backoffice (acceso y lectura) · en PostgreSQL: nodos de Citus, fragmentos, archivo de WAL y que cada despacho solo ve lo suyo con el rol de
la aplicación. Código de salida 0 todo bien, 1 algún fallo."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PANTALLAS = ["/", "/tareas/", "/tareas/hoy", "/tareas/tablero", "/notas", "/correo/", "/fiscal/vencimientos", "/fiscal/clientes", "/estadisticas", "/hoy"]


class Resultado:
    def __init__(self):
        self.filas: list[tuple[str, bool, str]] = []

    def anotar(self, nombre: str, ok: bool, detalle: str = "") -> bool:
        self.filas.append((nombre, ok, detalle))
        print(f"{'OK   ' if ok else 'FALLO'} {nombre}" + (f" — {detalle}" if detalle else ""), flush=True)
        return ok

    @property
    def todo_bien(self) -> bool:
        return all(ok for _n, ok, _d in self.filas)


def instantanea(db) -> dict:
    """Número de filas de cada tabla (con el motor actual). En PostgreSQL se lee con el rol de la plataforma (sin RLS) y sin el despacho 0 de «Plataforma»."""
    from app import bd
    conn = db.get_connection(plataforma=True) if bd.MOTOR == "postgres" else db.get_connection()
    try:
        if bd.MOTOR == "postgres":
            tablas = [r[0] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'").fetchall()]
        else:
            tablas = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND sql NOT LIKE 'CREATE VIRTUAL%'").fetchall()]
        salida = {}
        for t in sorted(tablas):
            if t in ("bd_esquema_version",) or "_fts" in t:
                continue
            donde = " WHERE id <> 0" if (t == "tenants" and bd.MOTOR == "postgres") else ""
            try:
                salida[t] = conn.execute(f'SELECT count(*) FROM "{t}"{donde}').fetchone()[0]
            except Exception:                                                                       # noqa: BLE001
                pass
        return salida
    finally:
        conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instantanea", help="guarda los recuentos por tabla en este JSON")
    ap.add_argument("--comparar", help="compara los recuentos con los de este JSON (de otra ejecución)")
    ap.add_argument("--personas-por-despacho", type=int, default=3)
    ap.add_argument("--despachos", type=int, default=40, help="máximo de despachos a recorrer")
    args = ap.parse_args(argv)
    r = Resultado()
    t0 = time.monotonic()

    from app import bd, db, kratos
    from app.auth import limiter
    from app.main import app

    motor = bd.MOTOR
    conn = db.get_connection(plataforma=True) if motor == "postgres" else db.get_connection()
    try:
        if motor == "postgres":
            usuario, super_, bypass = conn.execute("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user").fetchone()
            r.anotar("motor", True, f"postgres (rol de la plataforma: {usuario})")
        else:
            r.anotar("motor", True, "sqlite")
        despachos = [d[0] for d in conn.execute("SELECT id FROM tenants" + (" WHERE id > 0" if motor == "postgres" else "") + " ORDER BY id").fetchall()][: args.despachos]
        personas = {}
        for d in despachos:
            filas = conn.execute("SELECT id, email, kratos_identity_id FROM usuarios WHERE tenant_id = ? AND kratos_identity_id IS NOT NULL ORDER BY id LIMIT ?", (d, args.personas_por_despacho)).fetchall()
            if filas:
                personas[d] = [dict(f) for f in filas]
    finally:
        conn.close()
    r.anotar("despachos con personas", bool(personas), f"{len(personas)} despachos, {sum(len(v) for v in personas.values())} personas")

    # --- pantallas, con la sesión de Kratos simulada (no se toca el Kratos real) ---
    por_cookie = {p["kratos_identity_id"]: p["email"] for v in personas.values() for p in v}
    kratos.whoami = lambda cookies: ({"active": True, "identity": {"id": cookies.get("ory_kratos_session"), "traits": {"email": por_cookie[cookies.get("ory_kratos_session")]}}}
                                     if cookies.get("ory_kratos_session") in por_cookie else None)
    limiter.enabled = False
    app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000", PROPAGATE_EXCEPTIONS=False)
    malas, total = [], 0
    for d, lista in personas.items():
        for p in lista:
            cli = app.test_client()
            cli.set_cookie("ory_kratos_session", p["kratos_identity_id"], domain="127.0.0.1")
            for ruta in PANTALLAS:
                total += 1
                try:
                    resp = cli.get(ruta)
                    cuerpo = resp.get_data(as_text=True) if resp.status_code == 200 else ""
                    if resp.status_code >= 500 or "Ha ocurrido un error interno" in cuerpo:
                        malas.append(f"despacho {d} persona {p['id']} {ruta}: HTTP {resp.status_code}")
                except Exception as e:                                                               # noqa: BLE001
                    malas.append(f"despacho {d} persona {p['id']} {ruta}: {type(e).__name__}: {str(e)[:80]}")
    r.anotar("pantallas principales sin errores", not malas, f"{total} pantallas" + (f"; fallan {len(malas)}: {malas[:3]}" if malas else ""))

    # --- escritura de prueba que se deshace, con la conexión de cada despacho ---
    sin_escribir = []
    for d, lista in personas.items():
        try:
            c = db.get_connection(d) if motor == "postgres" else db.get_connection()
            try:
                antes = c.execute("SELECT count(*) FROM notas WHERE usuario_id = ?", (lista[0]["id"],)).fetchone()[0]
                c.execute("INSERT INTO notas (usuario_id, texto, creada_en) VALUES (?, 'prueba de humo', ?)", (lista[0]["id"], db.now_iso()))
                dentro = c.execute("SELECT count(*) FROM notas WHERE usuario_id = ?", (lista[0]["id"],)).fetchone()[0]
                c.rollback()
                despues = c.execute("SELECT count(*) FROM notas WHERE usuario_id = ?", (lista[0]["id"],)).fetchone()[0]
            finally:
                c.close()
            if not (dentro == antes + 1 and despues == antes):
                sin_escribir.append(d)
        except Exception as e:                                                                       # noqa: BLE001
            sin_escribir.append(f"{d} ({type(e).__name__}: {str(e)[:60]})")
    r.anotar("escritura de prueba (deshecha) en cada despacho", not sin_escribir, f"{len(personas)} despachos" + (f"; fallan: {sin_escribir[:3]}" if sin_escribir else ""))

    # --- búsqueda de texto ---
    try:
        from app.juridico import busqueda
        d0 = next(iter(personas), None)
        res = busqueda.buscar(d0, "impuesto sociedades") if d0 is not None else None
        r.anotar("búsqueda jurídica", res is not None, f"{res['total']} resultados" if res else "sin despachos")
    except Exception as e:                                                                           # noqa: BLE001
        r.anotar("búsqueda jurídica", False, f"{type(e).__name__}: {str(e)[:100]}")

    # --- backoffice ---
    try:
        from backoffice import auth
        from backoffice.main import create_app
        bo = auth.conectar()
        try:
            admins = bo.execute("SELECT count(*) FROM admins").fetchone()[0]
            auditoria = bo.execute("SELECT count(*) FROM auditoria").fetchone()[0]
        finally:
            bo.close()
        cliente_bo = create_app().test_client()
        codigo = cliente_bo.get("/login", base_url="http://127.0.0.1:8001").status_code
        r.anotar("backoffice", admins > 0 and codigo == 200, f"{admins} administradores, {auditoria} apuntes de auditoría, /login → {codigo}")
    except Exception as e:                                                                           # noqa: BLE001
        r.anotar("backoffice", False, f"{type(e).__name__}: {str(e)[:100]}")

    # --- solo PostgreSQL ---
    if motor == "postgres":
        c = db.get_connection(plataforma=True)
        try:
            citus = c.execute("SELECT 1 FROM pg_extension WHERE extname = 'citus'").fetchone()
            if citus:
                total_n, activos = c.execute("SELECT count(*), count(*) FILTER (WHERE isactive) FROM pg_dist_node").fetchone()
                sin_colocar = c.execute("SELECT count(*) FROM pg_dist_shard s WHERE NOT EXISTS (SELECT 1 FROM pg_dist_shard_placement p WHERE p.shardid = s.shardid)").fetchone()[0]
                r.anotar("Citus", total_n == activos and sin_colocar == 0, f"{activos}/{total_n} nodos activos, {sin_colocar} fragmentos sin ubicar")
            wal = c.execute("SELECT current_setting('archive_mode'), failed_count, last_archived_time FROM pg_stat_archiver").fetchone()
            import os
            produccion = bool(os.environ.get("GUILDA_PG_BACKUPS"))                                  # (en el ensayo sin copias el archivo puede estar apagado)
            r.anotar("archivo de WAL", wal[0] == "on" or not produccion, f"archive_mode={wal[0]}, fallos={wal[1]}, último={wal[2]}" + ("" if produccion else " (GUILDA_PG_BACKUPS sin definir: no se exige)"))
        except Exception as e:                                                                       # noqa: BLE001
            r.anotar("estado de PostgreSQL", False, f"{type(e).__name__}: {str(e)[:100]}")
        finally:
            c.close()
        # cada despacho solo ve lo suyo con el rol de la aplicación
        malos = []
        for d in list(personas)[:8]:
            try:
                ap_ = db.get_connection(d)
                try:
                    ajenos = ap_.execute("SELECT count(*) FROM notas WHERE tenant_id <> ?", (d,)).fetchone()[0]
                    visibles = ap_.execute("SELECT count(DISTINCT tenant_id) FROM clientes_fiscales").fetchone()[0]
                finally:
                    ap_.close()
                if ajenos or visibles > 1:
                    malos.append(d)
            except Exception as e:                                                                   # noqa: BLE001
                malos.append(f"{d} ({type(e).__name__})")
        r.anotar("aislamiento por despacho con el rol de la aplicación", not malos, "sin filas de otros despachos" if not malos else f"fugas o errores en: {malos[:3]}")

    # --- recuentos ---
    if args.instantanea or args.comparar:
        snap = instantanea(db)
        if args.instantanea:
            Path(args.instantanea).write_text(json.dumps({"motor": motor, "tablas": snap}, indent=1), encoding="utf-8")
            r.anotar("instantánea", True, f"{len(snap)} tablas, {sum(snap.values())} filas -> {args.instantanea}")
        if args.comparar:
            antes = json.loads(Path(args.comparar).read_text(encoding="utf-8"))
            distintas = {t: (antes["tablas"].get(t), snap.get(t)) for t in set(antes["tablas"]) | set(snap) if antes["tablas"].get(t) != snap.get(t) and t in antes["tablas"]}
            r.anotar("recuentos iguales a la instantánea anterior", not distintas, f"{len(snap)} tablas ({antes['motor']} → {motor})" + (f"; difieren: {dict(list(distintas.items())[:5])}" if distintas else ""))

    print(f"\n{'TODO BIEN' if r.todo_bien else 'HAY FALLOS'} · {len(r.filas)} comprobaciones en {time.monotonic() - t0:.0f} s")
    return 0 if r.todo_bien else 1


if __name__ == "__main__":
    sys.exit(main())
