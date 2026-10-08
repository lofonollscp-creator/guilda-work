"""Prueba de carga: N usuarios a la vez recorren la plataforma (85 % lecturas, 15 % escrituras) sobre una base de datos
SINTÉTICA y temporal (nunca toca la real). Mide por pantalla el tiempo mediano/p95/máximo y cuenta los errores
(sobre todo «database is locked» de SQLite con escrituras concurrentes).

    scripts/probar.sh --carga                         20 usuarios, 20 s, 5.000 vencimientos, ~2 s entre clics
    scripts/probar.sh --carga --usuarios 40 --segundos 30 --vencimientos 20000
    scripts/probar.sh --carga --pausa 0               estrés: todos a la vez sin pausas (para ver dónde se satura)

Las peticiones van en el mismo proceso que la aplicación (hilos, como waitress): mide la CPU y la base de datos de la app,
no la red ni Caddy. Las cifras sirven para comparar antes y después y para saber cuándo empieza a notarse."""
import argparse
import collections
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


def sembrar(db, n_usuarios: int, n_vencimientos: int, n_clientes: int = 300):
    random.seed(11)
    ahora = time.strftime("%Y-%m-%dT%H:%M:%S")
    dias = lambda n: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + n * 86400))  # noqa: E731
    tenant = db.crear_tenant("Carga Despacho")
    usuarios = []
    for i in range(n_usuarios):
        u = db.crear_usuario_vinculado_a_kratos(f"carga{i}@x.com", f"k{i}")
        db.asignar_tenant(u, tenant)
        usuarios.append(u)
    clientes = [db.crear_cliente_fiscal(tenant, f"Cliente {i}", email=f"c{i}@cli.com") for i in range(n_clientes)]
    conn = db.get_connection()
    conn.executemany(
        "INSERT INTO vencimientos_fiscales (tenant_id, cliente_fiscal_id, usuario_id, modelo, periodo, fecha_limite, estado, creado_en) VALUES (?,?,?,?,?,?,?,?)",
        [(tenant, random.choice(clientes), random.choice(usuarios), random.choice(["303", "130", "111", "115", "390"]), f"{random.choice(['1T', '2T', '3T', '4T'])}",
          dias(random.randint(-30, 120))[:10], random.choice(["pendiente"] * 3 + ["presentado"]), ahora) for _ in range(n_vencimientos)],
    )
    infos = []
    cuerpo = "Lorem ipsum dolor sit amet. " * 60
    for u in usuarios:
        cat = conn.execute("INSERT INTO categorias (usuario_id, nombre, color, creada_en) VALUES (?,?,?,?)", (u, "Proyecto", "#4a6cf7", ahora)).lastrowid
        for i in range(100):
            conn.execute(
                "INSERT INTO tareas_outlook (usuario_id, asunto, estado, prioridad, fecha_vencimiento, creada_en, actualizada_en, categoria_id, cliente_fiscal_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (u, f"Tarea {i} revisar", random.choice(["no_iniciada", "en_progreso", "completada"]), random.choice(["baja", "normal", "alta"]), dias(random.randint(-10, 30)), ahora, ahora, cat, random.choice(clientes)),
            )
        for i in range(20):
            conn.execute("INSERT INTO notas (usuario_id, texto, categoria_id, creada_en, titulo) VALUES (?,?,?,?,?)", (u, "nota " * 40, cat, dias(-i), f"Nota {i}"))
        cuenta = conn.execute(
            "INSERT INTO correo_cuentas (usuario_id, nombre, protocolo, host, puerto, usuario, creada_en) VALUES (?, 'c', 'imap', 'h', 993, 'u', ?)", (u, ahora)).lastrowid
        conn.executemany(
            "INSERT INTO correo_mensajes (cuenta_id, carpeta, uid, asunto, remitente, destinatarios, fecha, cuerpo_texto, message_id, leido, hilo_clave, descargado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
            .replace("?,?,?,?,?,?,?,?,?,?,?,?)", "?,?,?,?,?,?,?,?,?,?,?,?)"),
            [(cuenta, "INBOX", str(i), f"Asunto {i} factura", f"Cliente {i % 300} <c{i % 300}@cli.com>", "yo@x.com", dias(-random.random() * 200), cuerpo, f"<m{u}-{i}@x>",
              random.randint(0, 1), f"h{u}-{i % 150}", ahora) for i in range(400)],
        )
        infos.append({"usuario": u, "cuenta": cuenta, "proyecto": cat})
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--usuarios", type=int, default=20)
    ap.add_argument("--segundos", type=int, default=20)
    ap.add_argument("--vencimientos", type=int, default=5000)
    ap.add_argument("--escrituras", type=float, default=0.15, help="proporción de peticiones que escriben (0 a 1)")
    ap.add_argument("--pausa", type=float, default=2.0, help="segundos medios que una persona tarda entre un clic y el siguiente (0 = estrés: sin pausas)")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="guilda-carga-"))
    try:
        from app import db, kratos
        db.DB_PATH = tmp / "carga.db"
        db.BACKUPS_DIR = tmp / "backups"
        db.init_db()
        infos = sembrar(db, args.usuarios, args.vencimientos)
        por_cookie = {f"k{i}": f"carga{i}@x.com" for i in range(args.usuarios)}
        kratos.whoami = lambda cookies: ({"active": True, "identity": {"id": cookies.get("ory_kratos_session"), "traits": {"email": por_cookie[cookies.get("ory_kratos_session")]}}}
                                         if cookies.get("ory_kratos_session") in por_cookie else None)
        from app.auth import limiter
        from app.main import app
        app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
        limiter.enabled = False

        medidas = collections.defaultdict(list)
        errores = collections.Counter()
        bloqueos = [0]
        cerrojo = threading.Lock()
        fin = time.monotonic() + args.segundos
        listos = threading.Barrier(args.usuarios + 1)

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
                if escribe:
                    ruta, op = random.choice([("/tareas/", "crear tarea"), ("/notas", "crear nota"), ("/tareas/{t}/completar", "completar tarea")])
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
                ms = (time.perf_counter() - t0) * 1000
                if args.pausa > 0:
                    time.sleep(random.uniform(0.5, 1.5) * args.pausa)
                with cerrojo:
                    medidas[etiqueta].append(ms)
                    if r.status_code >= 500:
                        errores[f"{etiqueta} -> HTTP {r.status_code}"] += 1
                        if b"locked" in r.data.lower():
                            bloqueos[0] += 1

        hilos = [threading.Thread(target=usuario, args=(i,), daemon=True) for i in range(args.usuarios)]
        for h in hilos:
            h.start()
        listos.wait()
        inicio = time.monotonic()
        for h in hilos:
            h.join(args.segundos + 120)
        duracion = time.monotonic() - inicio

        total = sum(len(v) for v in medidas.values())
        print(f"{args.usuarios} usuarios · {duracion:.0f} s · {args.vencimientos} vencimientos · pausa media {args.pausa:g} s · {total} peticiones · {total / duracion:.1f} peticiones/s\n")
        print(f"{'petición':44s} {'n':>5s} {'mediana':>8s} {'p95':>7s} {'máx':>7s}")
        peor_p95 = 0.0
        for etiqueta, v in sorted(medidas.items(), key=lambda kv: -len(kv[1])):
            p95 = statistics.quantiles(v, n=20)[18] if len(v) >= 20 else max(v)
            peor_p95 = max(peor_p95, p95)
            print(f"{etiqueta[:44]:44s} {len(v):5d} {statistics.median(v):6.0f}ms {p95:5.0f}ms {max(v):5.0f}ms")
        print()
        if errores:
            print("ERRORES:")
            for k, n in errores.most_common(10):
                print(f"  {n:4d}  {k}")
        print(f"Errores 5xx: {sum(errores.values())} (de ellos «database is locked»: {bloqueos[0]})")
        veredicto = "MAL" if errores or peor_p95 >= 4000 else ("BIEN" if peor_p95 < 1500 else "ATENCIÓN")
        print(f"Veredicto: {veredicto} — peor p95 {peor_p95:.0f} ms" + ("" if not errores else ", hay errores"))
        return 0 if not errores else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
