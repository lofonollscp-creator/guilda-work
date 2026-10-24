"""Mide, en una copia aislada y con datos sintéticos, los endpoints que usaría la app móvil: latencia, nº de sentencias SQL y tiempo en SQL.
Uso: probar.sh --ejecutar medir_api_movil.py <sqlite|postgres>   (postgres usa el contenedor de ensayo, base gw_carga)"""
import argparse, json, os, random, statistics, sys, tempfile, threading, time, pathlib
RAIZ = pathlib.Path.cwd()
sys.path.insert(0, str(RAIZ)); sys.path.insert(0, str(RAIZ / "scripts"))
motor = sys.argv[1]
SALIDA = pathlib.Path("/tmp/claude-0/-root/3cdd7a64-398c-4ed2-8b6b-201b1dfe5877/scratchpad") / f"api_{motor}.json"
from app import db
import prueba_carga as pc

tmp = pathlib.Path(tempfile.mkdtemp(prefix="guilda-api-"))
db.DB_PATH = tmp / "api.db"; db.BACKUPS_DIR = tmp / "backups"
db.init_db()
USUARIOS, DESPACHOS = 12, 3
infos = pc.sembrar(db, USUARIOS, 3000, 60, DESPACHOS)
conn = db.get_connection()
ahora = time.strftime("%Y-%m-%dT%H:%M:%S")
for inf in infos:
    for k in range(40):
        conn.execute("INSERT INTO notificaciones (usuario_id, tipo, titulo, cuerpo, creado_en) VALUES (?,?,?,?,?)", (inf["usuario"], "tarea_asignada", f"Aviso {k}", "cuerpo", ahora))
conn.commit(); conn.close()
if motor == "postgres":
    args = argparse.Namespace(url="postgresql://guilda:ensayo@127.0.0.1:55432/postgres", esquema="citus", pool=10)
    resultado = {}
    pc.preparar_postgres(args, db, resultado)
    print("migración:", resultado.get("migracion"), file=sys.stderr)
tokens = [db.crear_token_api(i["usuario"], "medida") for i in infos]
from app.auth import limiter
from app.main import app
app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
limiter.enabled = False

# contador de sentencias por petición (hilo actual)
local = threading.local()
if motor == "postgres":
    from app.bd import postgres as pg
    original = pg.ConexionPG.execute
    def execute(self, sql, params=None):
        t0 = time.perf_counter()
        try:
            return original(self, sql, params)
        finally:
            local.n = getattr(local, "n", 0) + 1; local.ms = getattr(local, "ms", 0.0) + (time.perf_counter() - t0) * 1000
    pg.ConexionPG.execute = execute
else:
    import sqlite3
    # SQLite: cuenta con trace callback en cada conexión nueva
    orig_conn = db.get_connection
    def get_connection():
        c = orig_conn()
        try:
            c.set_trace_callback(lambda s: setattr(local, "n", getattr(local, "n", 0) + 1))
        except Exception:
            pass
        return c
    db.get_connection = get_connection

ENDPOINTS = [
    "/api/v1/auth/me", "/api/v1/dashboard", "/api/v1/mi-dia", "/api/v1/tareas-outlook?limit=50", "/api/v1/tareas-outlook?ambito=todas&limit=50", "/api/v1/tareas-outlook/{tarea}",
    "/api/v1/tareas-outlook/tablero", "/api/v1/tareas-outlook/carga", "/api/v1/notas", "/api/v1/notificaciones", "/api/v1/fiscal/clientes", "/api/v1/fiscal/vencimientos",
    "/api/v1/fiscal/panel", "/api/v1/fichaje/estado", "/api/v1/fichaje/resumen-semana", "/api/v1/correo/cuentas", "/api/v1/correo/mensajes?cuenta_id={cuenta}",
    "/api/v1/buscar?q=factura", "/api/v1/sync", "/api/v1/sync?cursor=0", "/api/v1/herramientas", "/api/v1/companeros", "/api/v1/proyectos", "/api/v1/ia/ajustes", "/api/v1/perfil",
]
# calentamiento
cl = app.test_client()
for i, inf in enumerate(infos):
    for ruta in ("/api/v1/auth/me", "/api/v1/dashboard"):
        cl.get(ruta, headers={"Authorization": f"Bearer {tokens[i]}"})
res = {}
for ep in ENDPOINTS:
    lat, nq, qms, codigos = [], [], [], {}
    for k in range(36):
        i = k % len(infos); inf = infos[i]
        tarea = db.listar_tareas_outlook(inf["usuario"], limite=1)
        ruta = ep.replace("{tarea}", str(tarea[0]["id"]) if tarea else "1").replace("{cuenta}", str(inf["cuenta"]))
        local.n = 0; local.ms = 0.0
        t0 = time.perf_counter()
        r = cl.get(ruta, headers={"Authorization": f"Bearer {tokens[i]}"})
        lat.append((time.perf_counter() - t0) * 1000); nq.append(getattr(local, "n", 0)); qms.append(getattr(local, "ms", 0.0))
        codigos[r.status_code] = codigos.get(r.status_code, 0) + 1
        tam = len(r.data)
    lat.sort()
    res[ep] = {"p50": round(statistics.median(lat), 1), "p95": round(lat[int(len(lat) * .95) - 1], 1), "max": round(lat[-1], 1), "sql_med": statistics.median(nq), "sql_max": max(nq),
               "ms_sql_med": round(statistics.median(qms), 1), "codigos": codigos, "bytes": tam}
json.dump(res, open(SALIDA, "w"), indent=1)

# --- Seguridad del cursor de /sync bajo concurrencia (solo tiene sentido en PostgreSQL) ---
if motor == "postgres":
    u = infos[0]["usuario"]; tk = tokens[0]; H = {"Authorization": f"Bearer {tk}"}
    c0 = cl.get("/api/v1/sync", headers=H).get_json()["data"]["cursor"]
    A = db.get_connection()
    A.execute("INSERT INTO tareas_outlook (usuario_id, asunto, estado, prioridad, creada_en, actualizada_en) VALUES (?,?,?,?,?,?)", (u, "TX-A (empieza antes, termina después)", "no_iniciada", "normal", ahora, ahora))
    idB = db.crear_tarea_outlook(u, asunto="TX-B (empieza después, termina antes)")
    s1 = cl.get(f"/api/v1/sync?cursor={c0}", headers=H).get_json()["data"]
    A.commit(); A.close()
    s2 = cl.get(f"/api/v1/sync?cursor={s1['cursor']}", headers=H).get_json()["data"]
    todas = cl.get(f"/api/v1/sync?cursor={c0}", headers=H).get_json()["data"]
    def ids(s):
        return sorted(x.get("id") for x in s.get("cambios", {}).get("tareas_outlook", [])) if isinstance(s.get("cambios"), dict) else s
    print("SYNC1", json.dumps(s1)[:300], file=sys.stderr)
    print("SYNC2", json.dumps(s2)[:300], file=sys.stderr)
    print("SYNC_DESDE_C0", json.dumps(todas)[:400], file=sys.stderr)
    json.dump({"c0": c0, "s1": s1, "s2": s2, "desde_c0": todas}, open(SALIDA.with_name("api_sync_concurrencia.json"), "w"), indent=1, default=str)
print("fin", file=sys.stderr)
