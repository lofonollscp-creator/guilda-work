"""Mide el tiempo, el peso y las consultas SQL de las pantallas principales con datos
sintéticos de un despacho con un año de uso (3.000 tareas, 40 proyectos, 500 notas y
30.000 correos). NUNCA toca la base real: crea la suya en un directorio temporal.

    scripts/probar.sh --perfil            (lo ejecuta en una copia aislada del repo)

Sirve para comparar antes y después de una optimización: las cifras son relativas
(un solo usuario, sin red), no de producción."""
import argparse
import collections
import random
import re
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

PANTALLAS = [
    "/", "/tareas/", "/tareas/?vista=asignadas", "/tareas/hoy", "/tareas/tablero", "/tareas/calendario", "/notas",
    "/correo/?cuenta_id={cuenta}", "/correo/?cuenta_id={cuenta}&q=factura", "/correo/?cuenta_id={cuenta}&mensaje_id=5",
    "/historial", "/estadisticas", "/fiscal/vencimientos", "/menu/{proyecto}",
]


def sembrar(db, tmp: Path, n_correos: int):
    random.seed(7)
    ahora = time.strftime("%Y-%m-%dT%H:%M:%S")
    dias = lambda n: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + n * 86400))  # noqa: E731
    t = db.crear_tenant("Perf Despacho")
    us = []
    for i in range(5):
        u = db.crear_usuario_vinculado_a_kratos(f"perf{i}@x.com", f"k{i}")
        db.asignar_tenant(u, t)
        us.append(u)
    yo = us[0]
    conn = db.get_connection()
    cats = [conn.execute("INSERT INTO categorias (usuario_id, nombre, color, creada_en) VALUES (?,?,?,?)", (yo, f"Proyecto {i}", "#4a6cf7", ahora)).lastrowid for i in range(40)]
    conn.commit()
    cf = [db.crear_cliente_fiscal(t, f"Cliente {i}", email=f"c{i}@cli.com") for i in range(200)]
    for i in range(600):
        conn.execute("INSERT INTO tareas (usuario_id,nombre,categoria_id,tipo,estado,inicio_en,fin_en,duracion_segundos) VALUES (?,?,?,?,?,?,?,?)",
                     (yo, f"Trabajo {i}", random.choice(cats), "duracion", "finalizada", dias(-random.randint(1, 300)), dias(-random.randint(0, 299)), random.randint(300, 9000)))
    estados = ["no_iniciada"] * 5 + ["en_progreso"] + ["completada"] * 6
    for i in range(3000):
        tid = conn.execute(
            """INSERT INTO tareas_outlook (usuario_id,asunto,cuerpo,estado,prioridad,fecha_vencimiento,creada_en,actualizada_en,categoria_id,asignada_a,cliente_fiscal_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (random.choice(us[:2]), f"Tarea {i} revisar documentación", "texto " * 30, random.choice(estados), random.choice(["baja", "normal", "alta"]),
             dias(random.randint(-20, 40)), dias(-random.randint(0, 300)), ahora, random.choice(cats), random.choice(us) if random.random() < 0.3 else None, random.choice(cf)),
        ).lastrowid
        if random.random() < 0.3:
            for k in range(3):
                conn.execute("INSERT INTO tarea_checklist (tarea_outlook_id,texto,hecha,orden) VALUES (?,?,?,?)", (tid, f"paso {k}", random.randint(0, 1), k))
    for i in range(500):
        conn.execute("INSERT INTO notas (usuario_id,texto,categoria_id,creada_en,titulo) VALUES (?,?,?,?,?)", (yo, "nota " * 60, random.choice(cats), dias(-random.randint(0, 300)), f"Nota {i}"))
    conn.commit()
    cuentas = [db.crear_cuenta_correo(yo, f"Cuenta {i}", "imap", "imap.x.com", 993, f"yo{i}@x.com") for i in range(3)]
    cuerpo = "Lorem ipsum dolor sit amet consectetur. " * 120
    filas = [(c, "INBOX", f"{c}-{i}", f"Asunto {i} modelo 303 factura", f"Cliente {i % 200} <c{i % 200}@cli.com>", f"yo{c}@x.com", dias(-random.random() * 400),
              cuerpo, f"<p>{cuerpo}</p>", f"<m{c}-{i}@x>", random.randint(0, 1), f"hilo{i % 3000}", ahora) for c in cuentas for i in range(n_correos)]
    conn.executemany("""INSERT INTO correo_mensajes (cuenta_id,carpeta,uid,asunto,remitente,destinatarios,fecha,cuerpo_texto,cuerpo_html,message_id,leido,hilo_clave,descargado_en)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", filas)
    conn.commit()
    conn.close()
    return cuentas[0], cats[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--correos", type=int, default=10000, help="correos por cuenta (3 cuentas)")
    parser.add_argument("--repeticiones", type=int, default=3)
    parser.add_argument("--cprofile", metavar="RUTA", help="perfil de Python (funciones más costosas) de UNA pantalla, p. ej. /tareas/hoy")
    parser.add_argument("--detalle", action="store_true", help="muestra también las consultas más lentas de cada pantalla")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="guilda-perfil-"))
    try:
        from app import db, kratos
        db.DB_PATH = tmp / "perf.db"
        db.BACKUPS_DIR = tmp / "backups"
        db.init_db()
        cuenta, proyecto = sembrar(db, tmp, args.correos)
        kratos.whoami = lambda c: {"active": True, "identity": {"id": "k0", "traits": {"email": "perf0@x.com"}}}
        from app.main import app
        app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
        cli = app.test_client()
        cli.set_cookie("ory_kratos_session", "x", domain="127.0.0.1")

        tiempos = collections.defaultdict(lambda: [0, 0.0])

        class Cur:
            def __init__(s, c, k): s.c, s.k = c, k
            def _t(s, f):
                t0 = time.perf_counter(); r = f(); tiempos[s.k][1] += (time.perf_counter() - t0) * 1000; return r
            def fetchall(s): return s._t(s.c.fetchall)
            def fetchone(s): return s._t(s.c.fetchone)
            def __iter__(s): return iter(s._t(s.c.fetchall))
            def __getattr__(s, n): return getattr(s.c, n)

        class Con:
            def __init__(s, c): object.__setattr__(s, "c", c)
            def execute(s, sql, *a):
                k = re.sub(r"\s+", " ", sql).strip()[:110]
                t0 = time.perf_counter(); cur = s.c.execute(sql, *a)
                tiempos[k][0] += 1; tiempos[k][1] += (time.perf_counter() - t0) * 1000
                return Cur(cur, k)
            def __getattr__(s, n): return getattr(s.c, n)
            def __setattr__(s, n, v): setattr(s.c, n, v)
        original = db.get_connection
        db.get_connection = lambda: Con(original())

        if args.cprofile:
            import cProfile
            import pstats
            ruta = args.cprofile.format(cuenta=cuenta, proyecto=proyecto)
            cli.get(ruta)
            perfil = cProfile.Profile()
            perfil.enable()
            cli.get(ruta)
            perfil.disable()
            pstats.Stats(perfil).sort_stats("tottime").print_stats(14)
            return 0

        print(f"{'pantalla':50s} {'ms':>5s} {'SQL ms':>7s} {'consultas':>9s} {'escrituras':>10s} {'KB':>5s}")
        for ruta in [p.format(cuenta=cuenta, proyecto=proyecto) for p in PANTALLAS]:
            medidas = []
            for _ in range(args.repeticiones + 1):  # la primera calienta cachés
                tiempos.clear()
                t0 = time.perf_counter()
                r = cli.get(ruta)
                total = (time.perf_counter() - t0) * 1000
                n = sum(v[0] for v in tiempos.values())
                esc = sum(v[0] for k, v in tiempos.items() if k.split(" ", 1)[0].upper() in ("INSERT", "UPDATE", "DELETE"))
                medidas.append((total, sum(v[1] for v in tiempos.values()), n, esc, len(r.data) // 1024, r.status_code))
            medidas = medidas[1:]
            ms = statistics.median(m[0] for m in medidas)
            sql = statistics.median(m[1] for m in medidas)
            ult = medidas[-1]
            marca = "" if ult[5] == 200 else f"  HTTP {ult[5]}"
            print(f"{ruta[:50]:50s} {ms:5.0f} {sql:7.0f} {ult[2]:9d} {ult[3]:10d} {ult[4]:5d}{marca}")
            if args.detalle:
                for k, (veces, t) in sorted(tiempos.items(), key=lambda kv: -kv[1][1])[:4]:
                    print(f"      {t:6.1f} ms {veces}x {k}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
