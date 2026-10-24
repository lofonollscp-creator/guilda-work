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


import concurrent.futures as cf
from app.bd import postgres as pg
original = pg.ConexionPG.execute
SALTAR = {"on": False}
def execute(self, sql, params=None):
    if SALTAR["on"] and (sql.lstrip().startswith("UPDATE tokens_api SET ultimo_uso") or sql.lstrip().startswith("INSERT INTO tokens_api_uso")):
        return original(self, "select 1")
    return original(self, sql, params)
pg.ConexionPG.execute = execute
def trabajador(i, n, ruta):
    c = app.test_client(); lat = []
    for _ in range(n):
        t0 = time.perf_counter(); r = c.get(ruta, headers={"Authorization": f"Bearer {tokens[i % len(tokens)]}"}); lat.append(((time.perf_counter() - t0) * 1000, r.status_code))
    return lat
def prueba(hilos, n, ruta):
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(hilos) as ex:
        res = list(ex.map(lambda i: trabajador(i, n, ruta), range(hilos)))
    seg = time.perf_counter() - t0
    todas = sorted(x[0] for r in res for x in r)
    codigos = {}
    for r in res:
        for _, c in r: codigos[c] = codigos.get(c, 0) + 1
    return {"hilos": hilos, "peticiones": hilos * n, "rps": round(hilos * n / seg, 1), "p50": round(todas[len(todas)//2], 1), "p95": round(todas[int(len(todas)*.95)], 1), "max": round(todas[-1], 1), "codigos": codigos}
out = {}
for etiqueta, saltar in (("con_escrituras_de_uso", False), ("sin_escrituras_de_uso", True)):
    SALTAR["on"] = saltar
    for hilos in (1, 4, 8, 12):
        out[f"{etiqueta}_{hilos}h"] = prueba(hilos, 60, "/api/v1/auth/me")
        print(etiqueta, out[f"{etiqueta}_{hilos}h"], file=sys.stderr)
json.dump(out, open(SALIDA.with_name("api_concurrencia_uso.json"), "w"), indent=1)
sys.exit(0)
