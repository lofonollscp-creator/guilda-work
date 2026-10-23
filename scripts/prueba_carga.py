"""Prueba de carga: N usuarios a la vez recorren la plataforma (85 % lecturas, 15 % escrituras) sobre una base de datos
SINTÉTICA y temporal (nunca toca la real). Mide por pantalla el tiempo mediano/p95/máximo y cuenta los errores
(sobre todo «database is locked» de SQLite con escrituras concurrentes).

    scripts/probar.sh --carga                         20 usuarios, 20 s, 5.000 vencimientos, ~2 s entre clics
    scripts/probar.sh --carga --usuarios 40 --segundos 30 --vencimientos 20000
    scripts/probar.sh --carga --pausa 0               estrés: todos a la vez sin pausas (para ver dónde se satura)

Fase 9 de la migración a PostgreSQL + Citus (docs/plan-migracion-postgresql-citus.md): con --motor postgres siembra los mismos datos en SQLite, los migra con
app/bd/migrar_datos.py a una base de ensayo con Citus, y recorre la aplicación con el rol SIN privilegios (guilda_app, con RLS) y varios despachos:

    scripts/probar.sh --carga --motor postgres --url postgresql://guilda:ensayo@127.0.0.1:55432/postgres --despachos 60 --usuarios 40 --segundos 60 --fondo --explicar

  --fondo      además de las personas: el trabajador del BOE (inserta normas y fragmentos), la sincronización de correo y las pasadas de automatizaciones/tareas recurrentes
  --explicar   al terminar, EXPLAIN (ANALYZE) de las 30 consultas que más tiempo han consumido (¿un solo fragmento? ¿recorridos secuenciales?)
  --json RUTA  guarda las cifras para compararlas entre ejecuciones

Las peticiones van en el mismo proceso que la aplicación (hilos, como waitress): mide la CPU y la base de datos de la app,
no la red ni Caddy. Las cifras sirven para comparar antes y después y para saber cuándo empieza a notarse."""
import argparse
import collections
import json
import os
import random
import shutil
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

CLAVE_APP = "carga-app"          # contraseñas de los roles de la base de ENSAYO (se fijan al crearla; nunca las de producción)
CLAVE_PLATAFORMA = "carga-plataforma"


def sembrar(db, n_usuarios: int, n_vencimientos: int, n_clientes: int = 300, n_despachos: int = 1):
    random.seed(11)
    ahora = time.strftime("%Y-%m-%dT%H:%M:%S")
    dias = lambda n: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + n * 86400))  # noqa: E731
    tenants = [db.crear_tenant(f"Carga Despacho {d}") for d in range(n_despachos)]
    usuarios = []
    for i in range(n_usuarios):
        u = db.crear_usuario_vinculado_a_kratos(f"carga{i}@x.com", f"k{i}")
        db.asignar_tenant(u, tenants[i % n_despachos])
        usuarios.append(u)
    clientes = {t: [db.crear_cliente_fiscal(t, f"Cliente {i}", email=f"c{i}@cli.com") for i in range(n_clientes)] for t in tenants}
    conn = db.get_connection()
    por_despacho = max(1, n_vencimientos // n_despachos)
    for t in tenants:
        propios = [u for i, u in enumerate(usuarios) if tenants[i % n_despachos] == t] or usuarios
        combinaciones = [(c, m, p) for c in clientes[t] for m in ("303", "130", "111", "115", "390") for p in ("1T", "2T", "3T", "4T")]       # (cliente, modelo, período) es único
        conn.executemany(
            "INSERT INTO vencimientos_fiscales (tenant_id, cliente_fiscal_id, usuario_id, modelo, periodo, fecha_limite, estado, creado_en) VALUES (?,?,?,?,?,?,?,?)",
            [(t, c, random.choice(propios), m, p, dias(random.randint(-30, 120))[:10], random.choice(["pendiente"] * 3 + ["presentado"]), ahora)
             for c, m, p in random.sample(combinaciones, min(por_despacho, len(combinaciones)))],
        )
    infos = []
    cuerpo = "Lorem ipsum dolor sit amet. " * 60
    for i, u in enumerate(usuarios):
        t = tenants[i % n_despachos]
        cat = conn.execute("INSERT INTO categorias (usuario_id, nombre, color, creada_en) VALUES (?,?,?,?)", (u, "Proyecto", "#4a6cf7", ahora)).lastrowid
        for k in range(100):
            conn.execute(
                "INSERT INTO tareas_outlook (usuario_id, asunto, estado, prioridad, fecha_vencimiento, creada_en, actualizada_en, categoria_id, cliente_fiscal_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (u, f"Tarea {k} revisar", random.choice(["no_iniciada", "en_progreso", "completada"]), random.choice(["baja", "normal", "alta"]), dias(random.randint(-10, 30)), ahora, ahora, cat, random.choice(clientes[t])),
            )
        for k in range(20):
            conn.execute("INSERT INTO notas (usuario_id, texto, categoria_id, creada_en, titulo) VALUES (?,?,?,?,?)", (u, "nota " * 40, cat, dias(-k), f"Nota {k}"))
        cuenta = conn.execute(
            "INSERT INTO correo_cuentas (usuario_id, nombre, protocolo, host, puerto, usuario, creada_en) VALUES (?, 'c', 'imap', 'h', 993, 'u', ?)", (u, ahora)).lastrowid
        conn.executemany(
            "INSERT INTO correo_mensajes (cuenta_id, carpeta, uid, asunto, remitente, destinatarios, fecha, cuerpo_texto, message_id, leido, hilo_clave, descargado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(cuenta, "INBOX", str(k), f"Asunto {k} factura", f"Cliente {k % 300} <c{k % 300}@cli.com>", "yo@x.com", dias(-random.random() * 200), cuerpo, f"<m{u}-{k}@x>",
              random.randint(0, 1), f"h{u}-{k % 150}", ahora) for k in range(400)],
        )
        infos.append({"usuario": u, "cuenta": cuenta, "proyecto": cat, "tenant": t})
    conn.commit()
    conn.close()
    return infos


LECTURAS = [
    ("/", 3), ("/tareas/", 3), ("/tareas/hoy", 2), ("/tareas/tablero", 1), ("/tareas/carga", 1), ("/notas", 2), ("/correo/?cuenta_id={cuenta}", 3),
    ("/correo/?cuenta_id={cuenta}&q=factura", 2), ("/fiscal/vencimientos", 2), ("/fiscal/clientes", 1), ("/proyecto/{proyecto}", 1), ("/estadisticas", 1),
]


def elegir_lectura():
    rutas, pesos = zip(*LECTURAS)
    return random.choices(rutas, pesos)[0]


# --- PostgreSQL + Citus --------------------------------------------------------------------------------------------------------------------------------

def preparar_postgres(args, db, resultado: dict):
    """Migra la base sembrada en SQLite a una base de ensayo con Citus y deja la aplicación apuntando a ella con los roles SIN privilegios."""
    import psycopg
    from psycopg.conninfo import make_conninfo
    from app import bd
    from app.bd import esquema, migrar_datos
    from app.bd import postgres as pg
    sys.path.insert(0, str(RAIZ / "scripts"))
    from migrar_a_postgres import _crear_base

    url_base = make_conninfo(args.url, dbname="gw_carga")
    t0 = time.monotonic()
    _crear_base(url_base, args.esquema)
    pg.fijar_url(url_base)
    c = pg.conectar()
    try:
        esquema.crear_si_falta(c, args.esquema)
    finally:
        c.close()
    pg.cerrar_pool()
    resultado["segundos_esquema"] = round(time.monotonic() - t0, 1)
    t0 = time.monotonic()
    informe: dict = {}
    with psycopg.connect(url_base, autocommit=True) as admin:
        migrar_datos.copiar(db.DB_PATH, admin, informe=informe)
        admin.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
        admin.execute(f"ALTER ROLE guilda_app PASSWORD '{CLAVE_APP}'")
        admin.execute(f"ALTER ROLE guilda_plataforma PASSWORD '{CLAVE_PLATAFORMA}'")
        admin.execute("ANALYZE")
    filas = sum(t["destino"] for t in informe["tablas"].values())
    resultado["migracion"] = {"segundos": round(time.monotonic() - t0, 1), "ok": informe["ok"], "filas": filas, "discrepancias": informe["discrepancias"][:10]}
    print(f"Migración a {args.esquema}: {filas:,} filas en {resultado['migracion']['segundos']} s · controles {'OK' if informe['ok'] else 'CON DISCREPANCIAS'}".replace(",", "."))
    if not informe["ok"]:
        print("  " + "\n  ".join(informe["discrepancias"][:10]))
    os.environ["GUILDA_PG_POOL_MAX"] = str(args.pool)
    pg.fijar_url(make_conninfo(url_base, user="guilda_app", password=CLAVE_APP), make_conninfo(url_base, user="guilda_plataforma", password=CLAVE_PLATAFORMA))
    pg.activar_esquema(args.esquema)
    bd.MOTOR = "postgres"
    return url_base


class Captura:
    """Cronometra cada sentencia que llega a PostgreSQL (con el despacho ya puesto en el texto) y guarda los argumentos de la más lenta para el EXPLAIN."""

    def __init__(self):
        from app.bd import postgres as pg
        self.pg = pg
        self.datos: dict[str, dict] = {}
        self.cerrojo = threading.Lock()
        self._original = pg.ConexionPG.execute
        original, captura = self._original, self

        def execute(conexion, sql, params=None):
            t0 = time.perf_counter()
            try:
                return original(conexion, sql, params)
            finally:
                ms = (time.perf_counter() - t0) * 1000
                try:
                    texto, args = conexion._argumentos(pg.preparar(sql), params)
                except Exception:                                                                          # noqa: BLE001
                    texto, args = None, None
                if texto:
                    with captura.cerrojo:
                        d = captura.datos.setdefault(texto, {"n": 0, "total": 0.0, "max": 0.0, "muestra": None})
                        d["n"] += 1
                        d["total"] += ms
                        if ms >= d["max"]:
                            d["max"] = ms
                            d["muestra"] = (args, getattr(conexion, "_despacho", None))
        pg.ConexionPG.execute = execute

    def restaurar(self):
        self.pg.ConexionPG.execute = self._original


def vigilar_bloqueos(url_base: str, parar: threading.Event, resultado: dict):
    """Muestrea cada 0,25 s qué sesiones esperan un bloqueo y cuántas están activas; al final, los interbloqueos y ficheros temporales de la base."""
    import psycopg
    muestras = esperas = maximo_esperando = maximo_activas = 0
    por_evento: collections.Counter = collections.Counter()
    with psycopg.connect(url_base, autocommit=True) as c:
        antes = c.execute("SELECT deadlocks, temp_files FROM pg_stat_database WHERE datname = current_database()").fetchone()
        while not parar.is_set():
            filas = c.execute("SELECT wait_event_type, wait_event, state FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid() AND backend_type = 'client backend'").fetchall()
            muestras += 1
            esperando = [f for f in filas if f[0] == "Lock"]
            if esperando:
                esperas += 1
                for f in esperando:
                    por_evento[f[1]] += 1
            maximo_esperando = max(maximo_esperando, len(esperando))
            maximo_activas = max(maximo_activas, sum(1 for f in filas if f[2] == "active"))
            parar.wait(0.25)
        despues = c.execute("SELECT deadlocks, temp_files FROM pg_stat_database WHERE datname = current_database()").fetchone()
    resultado.update({"muestras": muestras, "muestras_con_espera_de_bloqueo": esperas, "max_sesiones_esperando_bloqueo": maximo_esperando, "max_sesiones_activas": maximo_activas,
                      "esperas_por_tipo": dict(por_evento), "interbloqueos": despues[0] - antes[0], "ficheros_temporales": despues[1] - antes[1]})


def analizar_plan(plan: dict) -> dict:
    tareas, secuenciales = [], []

    def recorrer(nodo):
        if isinstance(nodo, dict):
            if "Task Count" in nodo:
                tareas.append(nodo["Task Count"])
            if nodo.get("Node Type") == "Seq Scan":
                filas = (nodo.get("Actual Rows") or 0) * (nodo.get("Actual Loops") or 1) + (nodo.get("Rows Removed by Filter") or 0)
                if filas > 2000:
                    secuenciales.append(f"{nodo.get('Relation Name')} ({filas} filas leídas)")
            for v in nodo.values():
                recorrer(v)
        elif isinstance(nodo, list):
            for v in nodo:
                recorrer(v)
    recorrer(plan)
    return {"ejecucion_ms": round(plan.get("Execution Time", 0), 2), "planificacion_ms": round(plan.get("Planning Time", 0), 2),
            "fragmentos": max([t for t in tareas if t] or [0]), "secuenciales_grandes": secuenciales[:5]}


def explicar(captura: Captura, url_app: str, n: int = 30) -> list[dict]:
    """EXPLAIN (ANALYZE, BUFFERS) de las `n` sentencias de lectura que más tiempo han sumado, con los argumentos de su ejecución más lenta y el rol de la aplicación."""
    import psycopg
    candidatas = sorted(((t, d) for t, d in captura.datos.items() if t.lstrip().upper().startswith(("SELECT", "WITH")) and d["muestra"]), key=lambda x: -x[1]["total"])[:n]
    salida = []
    with psycopg.connect(url_app, autocommit=True) as c:
        for texto, d in candidatas:
            args, despacho = d["muestra"]
            info = {"n": d["n"], "total_ms": round(d["total"]), "medio_ms": round(d["total"] / d["n"], 2), "max_ms": round(d["max"], 1), "sql": " ".join(texto.split())[:240]}
            try:
                with c.transaction():
                    c.execute("SELECT set_config('app.tenant_id', %s, true)", (str(despacho if despacho is not None else 0),))
                    info.update(analizar_plan(c.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + texto, args).fetchone()[0][0]))
                    raise psycopg.Rollback()
            except psycopg.Rollback:
                pass
            except Exception as e:                                                                          # noqa: BLE001
                info["error"] = str(e).splitlines()[0][:160]
            salida.append(info)
    return salida


def estadisticas_del_servidor(url_base: str, duracion: float) -> dict:
    """Lo que ve PostgreSQL por su lado (sin el tiempo de Python): sentencias, tiempo de ejecución, caché y las 10 más costosas."""
    import psycopg
    with psycopg.connect(url_base, autocommit=True) as c:
        n, t, hit, read = c.execute("SELECT coalesce(sum(calls), 0), coalesce(sum(total_exec_time), 0), coalesce(sum(shared_blks_hit), 0), coalesce(sum(shared_blks_read), 0) "
                                    "FROM pg_stat_statements WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())").fetchone()
        top = c.execute("SELECT calls, mean_exec_time, max_exec_time, left(regexp_replace(query, '\\s+', ' ', 'g'), 110) FROM pg_stat_statements "
                        "WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database()) AND query NOT LIKE '%%pg_stat_%%' ORDER BY total_exec_time DESC LIMIT 10").fetchall()
    from app.bd import tenant
    referencia = sorted(t for t, c in tenant.cargar_modelo().items() if c.nombre == "referencia")
    patron = r"^(INSERT INTO|UPDATE|DELETE FROM)\s+\"?(" + "|".join(referencia) + r")\"?[\s(]"
    with psycopg.connect(url_base, autocommit=True) as c:
        escrituras_ref = c.execute("SELECT coalesce(sum(calls), 0), coalesce(max(max_exec_time), 0) FROM pg_stat_statements WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database()) "
                                   "AND query ~* %s", (patron,)).fetchone()
        detalle_ref = c.execute("SELECT calls, mean_exec_time, left(regexp_replace(query, '\\s+', ' ', 'g'), 100) FROM pg_stat_statements WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database()) "
                                "AND query ~* %s ORDER BY calls DESC LIMIT 6", (patron,)).fetchall()
    return {"escrituras_en_tablas_de_referencia": {"sentencias": int(escrituras_ref[0]), "max_ms": round(float(escrituras_ref[1]), 1), "principales": [{"calls": int(a), "media_ms": round(float(b), 1), "sql": q} for a, b, q in detalle_ref]},
            "sentencias": int(n), "por_segundo": round(int(n) / max(duracion, 1), 1), "segundos_de_ejecucion": round(float(t) / 1000, 1), "media_ms": round(float(t) / max(int(n), 1), 2),
            "aciertos_cache_pct": round(100 * hit / max(hit + read, 1), 1),
            "mas_costosas": [{"calls": int(a), "media_ms": float(b), "max_ms": float(m), "sql": q} for a, b, m, q in top]}


# --- Trabajos de fondo ----------------------------------------------------------------------------------------------------------------------------------

def trabajos_de_fondo(db, infos, fin, medir, error):
    """Lo que en producción corre sin que nadie pulse nada: el trabajador del BOE, la sincronización de correo y las pasadas periódicas."""
    from app import automatizaciones
    from app.juridico import corpus
    corpus.registrar_fuente("carga-boe", "Fuente de carga", "boe", "legislacion")
    palabras = "deducción gastos impuesto sociedades arrendamiento contrato resolución recurso sentencia obligación tributaria plazo presentación declaración".split()
    pid = os.getpid()

    def boe():
        n = 0
        while time.monotonic() < fin:
            t0 = time.perf_counter()
            try:
                n += 1
                conn = db.get_connection()
                try:
                    doc = conn.execute("INSERT INTO jur_documentos (fuente_id, id_externo, coleccion, titulo, creado_en) VALUES ('carga-boe', ?, 'legislacion', ?, ?)",
                                       (f"BOE-{pid}-{n}", f"Norma sintética {n}", db.now_iso())).lastrowid
                    ver = conn.execute("INSERT INTO jur_versiones (documento_id, hash_texto, capturada_en, activa) VALUES (?, ?, ?, 1)", (doc, f"h{pid}-{n}", db.now_iso())).lastrowid
                    conn.executemany("INSERT INTO jur_fragmentos (version_id, orden, localizador, texto, hash) VALUES (?, ?, ?, ?, ?)",
                                     [(ver, k, f"art. {k}", " ".join(random.choices(palabras, k=60)), f"f{n}-{k}") for k in range(20)])
                    conn.commit()
                finally:
                    conn.close()
                medir("FONDO BOE: norma con 20 fragmentos", (time.perf_counter() - t0) * 1000)
            except Exception as e:                                                                           # noqa: BLE001
                error("FONDO BOE", e)
            time.sleep(1.0)

    def correo():
        n = 0
        while time.monotonic() < fin:
            info = random.choice(infos)
            t0 = time.perf_counter()
            try:
                n += 1
                conn = db.get_connection()
                try:
                    conn.executemany(
                        "INSERT INTO correo_mensajes (cuenta_id, carpeta, uid, asunto, remitente, destinatarios, fecha, cuerpo_texto, message_id, leido, hilo_clave, descargado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        [(info["cuenta"], "INBOX", f"n{pid}-{n}-{k}", f"Nuevo {k} factura", "x <x@cli.com>", "yo@x.com", db.now_iso(), "cuerpo " * 100, f"<n{pid}-{n}-{k}@x>", 0, f"hn{n}", db.now_iso())
                         for k in range(10)])
                    conn.commit()
                finally:
                    conn.close()
                medir("FONDO correo: 10 mensajes nuevos", (time.perf_counter() - t0) * 1000)
            except Exception as e:                                                                           # noqa: BLE001
                error("FONDO correo", e)
            time.sleep(0.5)

    def pasadas():
        while time.monotonic() < fin:
            for nombre, f in (("automatizaciones.procesar_eventos", automatizaciones.procesar_eventos), ("automatizaciones.ejecutar", automatizaciones.ejecutar),
                              ("tareas recurrentes", db.generar_tareas_recurrentes), ("tareas por vencimiento", db.generar_tareas_por_vencimiento)):
                t0 = time.perf_counter()
                try:
                    f()
                    medir(f"FONDO pasada: {nombre}", (time.perf_counter() - t0) * 1000)
                except Exception as e:                                                                       # noqa: BLE001
                    error(f"FONDO pasada: {nombre}", e)
            time.sleep(3.0)

    return [threading.Thread(target=f, daemon=True) for f in (boe, correo, pasadas)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--usuarios", type=int, default=20)
    ap.add_argument("--segundos", type=int, default=20)
    ap.add_argument("--vencimientos", type=int, default=5000)
    ap.add_argument("--escrituras", type=float, default=0.15, help="proporción de peticiones que escriben (0 a 1)")
    ap.add_argument("--pausa", type=float, default=2.0, help="segundos medios que una persona tarda entre un clic y el siguiente (0 = estrés: sin pausas)")
    ap.add_argument("--motor", choices=("sqlite", "postgres"), default="sqlite")
    ap.add_argument("--url", help="URL de un superusuario de PostgreSQL con Citus (base «postgres»): crea y borra la base gw_carga")
    ap.add_argument("--esquema", choices=("citus", "multitenant"), default="citus", help="citus (tablas distribuidas) o multitenant (el mismo esquema sin distribuir: lo que cuesta Citus)")
    ap.add_argument("--despachos", type=int, default=1, help="cuántos despachos reparten a las personas")
    ap.add_argument("--sin-calentar", action="store_true", help="no hace la primera visita de cada persona antes de medir (mide también el arranque en frío)")
    ap.add_argument("--procesos", type=int, default=1, help="reparte las personas entre N procesos (un solo proceso de Python se satura por el GIL antes que la base de datos)")
    ap.add_argument("--pool", type=int, default=20, help="conexiones máximas del pool de PostgreSQL (GUILDA_PG_POOL_MAX)")
    ap.add_argument("--fondo", action="store_true", help="con trabajos de fondo: BOE, sincronización de correo, automatizaciones")
    ap.add_argument("--explicar", action="store_true", help="EXPLAIN (ANALYZE) de las 30 consultas más costosas (solo PostgreSQL)")
    ap.add_argument("--json", help="guarda las cifras en este fichero")
    args = ap.parse_args()
    if args.motor == "postgres" and not args.url:
        ap.error("--motor postgres necesita --url")
    if args.explicar and args.procesos > 1:
        ap.error("--explicar necesita --procesos 1 (las sentencias se cronometran dentro de cada proceso)")
    n_clientes = 300 if args.despachos == 1 else 60

    tmp = Path(tempfile.mkdtemp(prefix="guilda-carga-"))
    try:
        from app import db, kratos
        db.DB_PATH = tmp / "carga.db"
        db.BACKUPS_DIR = tmp / "backups"
        db.init_db()
        t0 = time.monotonic()
        infos = sembrar(db, args.usuarios, args.vencimientos, n_clientes, args.despachos)
        resultado: dict = {"motor": args.motor, "esquema": args.esquema, "usuarios": args.usuarios, "despachos": args.despachos, "segundos": args.segundos, "pool": args.pool, "fondo": args.fondo,
                           "segundos_siembra_sqlite": round(time.monotonic() - t0, 1)}
        captura = url_base = None
        if args.motor == "postgres":
            url_base = preparar_postgres(args, db, resultado)
            if args.explicar:
                captura = Captura()
        por_cookie = {f"k{i}": f"carga{i}@x.com" for i in range(args.usuarios)}
        kratos.whoami = lambda cookies: ({"active": True, "identity": {"id": cookies.get("ory_kratos_session"), "traits": {"email": por_cookie[cookies.get("ory_kratos_session")]}}}
                                         if cookies.get("ory_kratos_session") in por_cookie else None)
        from app.auth import limiter
        from app.main import app
        app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000", PROPAGATE_EXCEPTIONS=False)
        limiter.enabled = False

        def ejecutar(indices, con_fondo, salida=None):
            """Hilos de las personas `indices` (y los trabajos de fondo si toca) durante `args.segundos`. Devuelve (medidas, errores, bloqueos de SQLite)."""
            medidas = collections.defaultdict(list)
            errores = collections.Counter()
            bloqueos = [0]
            cerrojo = threading.Lock()
            fin = time.monotonic() + args.segundos
            listos = threading.Barrier(len(indices) + 1)

            def medir(etiqueta, ms):
                with cerrojo:
                    medidas[etiqueta].append(ms)

            def error(etiqueta, e):
                with cerrojo:
                    errores[f"{etiqueta} -> {type(e).__name__}: {str(e).splitlines()[0][:100]}"] += 1

            def usuario(i: int):
                random.seed(1000 + i)
                info = infos[i]
                cli = app.test_client()
                cli.set_cookie("ory_kratos_session", f"k{i}", domain="127.0.0.1")
                listos.wait()
                if args.pausa > 0:
                    time.sleep(random.uniform(0, args.pausa))       # no todos pulsan a la vez en el primer segundo
                n = 0
                while time.monotonic() < fin:
                    n += 1
                    escribe = random.random() < args.escrituras
                    try:
                        if escribe:
                            op = random.choice(["crear tarea", "crear nota", "completar tarea"])
                            etiqueta = f"POST {op}"
                            t0 = time.perf_counter()
                            if op == "crear tarea":
                                r = cli.post("/tareas/", data={"asunto": f"Tarea de carga {i}-{n} ~1h", "categoria_id": info["proyecto"]})
                            elif op == "crear nota":
                                r = cli.post("/notas", data={"texto": f"Nota de carga {i}-{n}", "categoria_id": info["proyecto"]})
                            else:
                                tid = db.listar_tareas_outlook(info["usuario"], limite=1)
                                if not tid:
                                    continue
                                t0 = time.perf_counter()
                                r = cli.post(f"/tareas/{tid[0]['id']}/completar")
                        else:
                            ruta = elegir_lectura()
                            etiqueta = "GET " + ruta.split("?")[0].replace(str(info["cuenta"]), "{cuenta}").replace(str(info["proyecto"]), "{proyecto}")
                            t0 = time.perf_counter()
                            r = cli.get(ruta.format(cuenta=info["cuenta"], proyecto=info["proyecto"]))
                    except Exception as e:                                                                   # noqa: BLE001
                        error("excepción", e)
                        continue
                    ms = (time.perf_counter() - t0) * 1000
                    if args.pausa > 0:
                        time.sleep(random.uniform(0.5, 1.5) * args.pausa)
                    with cerrojo:
                        medidas[etiqueta].append(ms)
                        if r.status_code >= 500:
                            errores[f"{etiqueta} -> HTTP {r.status_code}"] += 1
                            if b"locked" in r.data.lower():
                                bloqueos[0] += 1

            hilos = [threading.Thread(target=usuario, args=(i,), daemon=True) for i in indices]
            if con_fondo:
                hilos += trabajos_de_fondo(db, infos, fin, medir, error)
            for h in hilos:
                h.start()
            listos.wait()
            for h in hilos:
                h.join(args.segundos + 120)
            resultado_local = (dict(medidas), dict(errores), bloqueos[0])
            if salida is not None:
                salida.put(resultado_local)
            return resultado_local

        if not args.sin_calentar:                     # primera visita de cada persona, una a una: crea su perfil (una escritura en una tabla de referencia de Citus) y calienta cachés
            for i in range(args.usuarios):
                c0 = app.test_client()
                c0.set_cookie("ory_kratos_session", f"k{i}", domain="127.0.0.1")
                c0.get("/")
                c0.get("/tareas/")
            if args.motor == "postgres":
                from app.bd import postgres as pg
                pg.cerrar_pool()                      # (los procesos hijos abren los suyos)
        parar = threading.Event()
        vigilancia: dict = {}
        vigilante = None
        if url_base:
            import psycopg
            with psycopg.connect(url_base, autocommit=True) as c:
                c.execute("SELECT pg_stat_statements_reset()")
            vigilante = threading.Thread(target=vigilar_bloqueos, args=(url_base, parar, vigilancia), daemon=True)
            vigilante.start()
        inicio = time.monotonic()
        if args.procesos <= 1:
            parciales = [ejecutar(list(range(args.usuarios)), args.fondo)]
        else:
            import multiprocessing
            ctx = multiprocessing.get_context("fork")
            cola = ctx.Queue()
            trozos = [list(range(args.usuarios))[k::args.procesos] for k in range(args.procesos)]
            hijos = [ctx.Process(target=ejecutar, args=(trozo, args.fondo and k == 0, cola), daemon=True) for k, trozo in enumerate(trozos) if trozo]
            for h in hijos:
                h.start()
            parciales = [cola.get(timeout=args.segundos + 300) for _ in hijos]
            for h in hijos:
                h.join(30)
        duracion = time.monotonic() - inicio
        parar.set()
        if vigilante:
            vigilante.join(10)
        medidas = collections.defaultdict(list)
        errores = collections.Counter()
        bloqueos = [0]
        for m, e, b in parciales:
            for k, v in m.items():
                medidas[k].extend(v)
            errores.update(e)
            bloqueos[0] += b

        total = sum(len(v) for k, v in medidas.items() if not k.startswith("FONDO"))
        print(f"{args.usuarios} usuarios · {args.despachos} despacho(s) · {args.motor} · {duracion:.0f} s · {args.vencimientos} vencimientos · pausa media {args.pausa:g} s · {total} peticiones · {total / duracion:.1f} peticiones/s\n")
        print(f"{'petición':50s} {'n':>5s} {'mediana':>8s} {'p95':>7s} {'máx':>7s}")
        peor_p95 = 0.0
        tabla = {}
        for etiqueta, v in sorted(medidas.items(), key=lambda kv: (kv[0].startswith("FONDO"), -len(kv[1]))):
            p95 = statistics.quantiles(v, n=20)[18] if len(v) >= 20 else max(v)
            if not etiqueta.startswith("FONDO"):
                peor_p95 = max(peor_p95, p95)
            tabla[etiqueta] = {"n": len(v), "mediana_ms": round(statistics.median(v), 1), "p95_ms": round(p95, 1), "max_ms": round(max(v), 1)}
            print(f"{etiqueta[:50]:50s} {len(v):5d} {statistics.median(v):6.0f}ms {p95:5.0f}ms {max(v):5.0f}ms")
        print()
        if errores:
            print("ERRORES:")
            for k, n in errores.most_common(10):
                print(f"  {n:4d}  {k}")
        print(f"Errores 5xx: {sum(errores.values())} (de ellos «database is locked»: {bloqueos[0]})")
        if vigilancia:
            print(f"Bloqueos en PostgreSQL: {vigilancia['muestras_con_espera_de_bloqueo']} de {vigilancia['muestras']} muestras con alguna sesión esperando (máx. {vigilancia['max_sesiones_esperando_bloqueo']} a la vez, "
                  f"{vigilancia['esperas_por_tipo'] or 'ninguno'}) · interbloqueos: {vigilancia['interbloqueos']} · sesiones activas a la vez (máx.): {vigilancia['max_sesiones_activas']}")
        veredicto = "MAL" if errores or peor_p95 >= 4000 else ("BIEN" if peor_p95 < 1500 else "ATENCIÓN")
        print(f"Veredicto: {veredicto} — peor p95 {peor_p95:.0f} ms" + ("" if not errores else ", hay errores"))
        resultado.update({"peticiones": total, "peticiones_por_segundo": round(total / duracion, 1), "tabla": tabla, "errores": dict(errores), "peor_p95_ms": round(peor_p95), "veredicto": veredicto,
                          "bloqueos": vigilancia})
        if url_base:
            resultado["servidor"] = estadisticas_del_servidor(url_base, duracion)
            sv = resultado["servidor"]
            print(f"\nEn el servidor (pg_stat_statements): {sv['sentencias']:,} sentencias en {duracion:.0f} s ({sv['por_segundo']}/s), {sv['segundos_de_ejecucion']} s de ejecución en total, media {sv['media_ms']} ms, "
                  f"aciertos de caché {sv['aciertos_cache_pct']} %".replace(",", "."))
            er = sv["escrituras_en_tablas_de_referencia"]
            print(f"   Escrituras en tablas de REFERENCIA de Citus (serializan a todos los escritores): {er['sentencias']} (máx. {er['max_ms']} ms)" + "".join(f"\n     {q['calls']:5d}× {q['media_ms']:7.1f} ms {q['sql']}" for q in er["principales"]))
            for q in sv["mas_costosas"]:
                print(f"   {q['calls']:6d}× media {q['media_ms']:7.2f} ms · máx {q['max_ms']:7.1f} ms · {q['sql']}")
        if captura:
            captura.restaurar()
            from psycopg.conninfo import make_conninfo
            plan = explicar(captura, make_conninfo(url_base, user="guilda_app", password=CLAVE_APP))
            resultado["explain"] = plan
            multi = [p for p in plan if p.get("fragmentos", 0) > 1]
            seq = [p for p in plan if p.get("secuenciales_grandes")]
            print(f"\nEXPLAIN de las {len(plan)} consultas más costosas: {len(multi)} tocan más de un fragmento, {len(seq)} recorren una tabla grande en secuencial, "
                  f"{sum(1 for p in plan if 'error' in p)} no se han podido explicar")
            for p in plan:
                marca = "·" if p.get("fragmentos", 1) <= 1 and not p.get("secuenciales_grandes") and "error" not in p else "!"
                print(f" {marca} {p['n']:5d}× {p['medio_ms']:7.2f} ms (máx {p['max_ms']:6.1f}) frag={p.get('fragmentos', '?')} {p.get('error', '')[:60]} {p['sql'][:110]}")
        if args.json:
            Path(args.json).write_text(json.dumps(resultado, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return 0 if not errores else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
