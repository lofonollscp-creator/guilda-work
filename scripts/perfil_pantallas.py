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
    "/correo/?cuenta_id={cuenta}", "/correo/?cuenta_id={cuenta}&q=factura", "/correo/?cuenta_id={cuenta}&q=inexistentezzz",
    "/correo/?cuenta_id={cuenta}&q=lorem+ipsum", "/correo/?cuenta_id={cuenta}&mensaje_id=5",
    "/guilda-fiscal/", "/guilda-fiscal/vencimientos?dias=180", "/guilda-fiscal/recordatorios", "/guilda-fiscal/{fiscal_cliente}?ejercicio=2026", "/guilda-fiscal/{fiscal_cliente}/130?ejercicio=2026&periodo=3T",
    "/guilda-fiscal/{fiscal_cliente}/recurrentes", "/guilda-fiscal/{fiscal_cliente}/390?ejercicio=2026",
    "/historial", "/estadisticas", "/fiscal/vencimientos", "/fiscal/clientes", "/menu/{proyecto}",
    # núcleo con un despacho grande (5.000 clientes, 3.000 expedientes, 4.000 plazos, 6.000 partes de horas)
    "/clientes/", "/clientes/?q=garcia", "/clientes/?pagina=40", "/clientes/{ncliente}", "/expedientes/", "/expedientes/?q=asunto+12", "/expedientes/{nexp}",
    "/plazos/", "/tiempo/", "/seguridad/privacidad",
    # contabilidad con volumen (AC4): una gestoría con 60 clientes y varios miles de facturas
    "/contabilidad/", "/contabilidad/?cliente_id={cfac}", "/contabilidad/?estado=pendiente", "/contabilidad/?cliente_id={cfac}&estado=revisada", "/contabilidad/{nfac}", "/contabilidad/panel-cierre",
    "/contabilidad/cola", "/contabilidad/calidad", "/contabilidad/lotes", "/contabilidad/justificantes", "/contabilidad/ajustes", "/contabilidad/cliente/{cfac}/terceros", "/contabilidad/cliente/{cfac}/reglas",
    "/proyecto/{proyecto}", "/proyecto/{proyecto}/lista", "/proyecto/{proyecto}/tablero", "/proyecto/{proyecto}/calendario",
    "/proyecto/{proyecto}/notas", "/proyecto/{proyecto}/actividad", "/correo/cuentas",
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
    _sembrar_nucleo(db, t, us)
    _sembrar_fiscal(db, t, us[0], cf)
    _sembrar_contabilidad(db, t, us[0], FACTURAS)
    return cuentas[0], cats[0]


NUCLEO = {}
# el portal del cliente (una persona entra con su enlace y ve SUS facturas: unas 100 de las 6.000)
PORTAL = ["/portal/", "/portal/facturas", "/portal/facturas/{pfac}", "/portal/justificantes", "/portal/extracto", "/portal/mensajes", "/portal/impuestos", "/portal/avisos", "/portal/documentos",
          "/portal/gestiones", "/portal/carpeta", "/portal/actividad"]
FACTURAS = 6000


def _sembrar_fiscal(db, t, yo, cf):
    """Guilda Fiscal con 200 titulares: perfil, 12 apuntes aprobados de 2026, 303 y 130 de cada trimestre en el calendario y una plantilla recurrente cada diez. Por la API del módulo, con sus comprobaciones."""
    from datetime import date

    from app import fiscal_nucleo as fn, fiscal_perfiles as fp, fiscal_recurrentes as fr, verticales
    from tests.escenarios_303 import compra, venta
    verticales.fijar_activo(t, "fiscal", True)
    db.asignar_supervisor_tenant(yo, True)
    random.seed(13)
    for n, c in enumerate(cf):
        fp.guardar_perfil(t, yo, c, {"forma_juridica": "persona_fisica" if n % 2 else "sociedad"}, vigente_desde="2026-01-01")
        for i in range(12):
            fecha = date(2026, random.randint(1, 9), random.randint(1, 28))
            fn.aprobar_apunte(t, yo, c, (venta if i % 2 else compra)(random.randint(50, 5000) * 100, numero=f"{i}", fecha=fecha))
        if n % 10 == 0:
            fr.crear(t, yo, c, fn.listar_apuntes(t, yo, c)[0]["id"], frecuencia="mensual")
    conn = db.get_connection()
    for c in cf:
        for modelo in ("303", "130"):
            for q, limite in ((1, "2026-04-20"), (2, "2026-07-20"), (3, "2026-10-20"), (4, "2027-01-30")):
                conn.execute("INSERT INTO vencimientos_fiscales (tenant_id, cliente_fiscal_id, usuario_id, modelo, periodo, fecha_limite, estado, creado_en) VALUES (?, ?, ?, ?, ?, ?, 'pendiente', '2026-01-01')",
                             (t, c, yo, modelo, f"2026-T{q}", limite))
    conn.commit()
    conn.close()
    NUCLEO.update(fiscal_cliente=cf[len(cf) // 2])


def _sembrar_contabilidad(db, t, yo, n_facturas):
    """Facturas para contabilizar: 60 clientes con la configuración de a3, `n_facturas` repartidas, de proveedores repetidos (como en la vida real), en todos los estados."""
    from app import facturas_contables as fc, verticales
    from app.db_fiscal import crear_cliente_fiscal
    verticales.fijar_activo(t, "contabilizacion", True)
    db.asignar_supervisor_tenant(yo, True)
    clientes = [crear_cliente_fiscal(t, f"Empresa conta {i} S.L.", nif=f"B{1000000 + i}{'A'}", email=f"titular{i}@cli.com") for i in range(60)]
    for c in clientes:
        fc.guardar_configuracion(t, yo, c, {"a3_empresa": str(10 + c % 80), "digitos": "8"})
    ultimo = None
    for i in range(n_facturas):
        c = clientes[i % len(clientes)]
        d = {"tipo": "recibida" if i % 5 else "emitida", "fecha": f"2026-{1 + i % 9:02d}-{1 + i % 27:02d}", "numero": f"F-{i}", "tercero_nombre": f"Proveedor {i % 150}",
             "tercero_nif": f"A{5000000 + i % 150}0", "concepto": "Servicios profesionales"}
        try:
            ultimo = fc.crear(t, yo, c, d, [{"base": f"{100 + i % 900},00", "pct_iva": "21"}])
        except ValueError:
            continue
        if c == clientes[len(clientes) // 2]:
            NUCLEO["pfac"] = ultimo
        if i % 3 == 0:
            try:
                fc.cambiar_estado(t, yo, ultimo, "revisada")
            except ValueError:
                pass
    NUCLEO.update(cfac=clientes[len(clientes) // 2], nfac=ultimo, pemail=f"titular{len(clientes) // 2}@cli.com")


def _sembrar_nucleo(db, t, us):
    """Despacho grande del núcleo común: ver la lista de pantallas. Se hace por la API del núcleo (con sus comprobaciones), no con SQL a mano."""
    from app import nucleo
    random.seed(11)
    apellidos = ["Garcia", "Soler", "Vidal", "Puig", "Ferrer", "Roca", "Casas", "Mas", "Font", "Serra"]
    ids = [nucleo.crear_cliente(t, f"{random.choice(apellidos)} {random.choice(apellidos)} {i}", nif=f"{10000000 + i}A", email=f"cli{i}@ej.com") for i in range(5000)]
    exps = [nucleo.crear_expediente(t, us[0], random.choice(ids), f"Asunto {i}", referencia=f"EXP-{i}") for i in range(3000)]
    hoy = time.time()
    fecha = lambda n: time.strftime("%Y-%m-%d", time.localtime(hoy + n * 86400))  # noqa: E731
    for i in range(4000):
        nucleo.crear_plazo(t, us[0], f"Plazo {i}", fecha(random.randint(-30, 120)), expediente_id=random.choice(exps), supervisor=True)
    for i in range(6000):
        nucleo.registrar_parte(t, us[random.randint(0, 4)], f"Trabajo {i}", minutos=random.choice([15, 30, 60, 90]), fecha=fecha(-random.randint(0, 200)), expediente_id=random.choice(exps))
    NUCLEO.update(ncliente=ids[len(ids) // 2], nexp=exps[len(exps) // 2])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--correos", type=int, default=10000, help="correos por cuenta (3 cuentas)")
    parser.add_argument("--repeticiones", type=int, default=3)
    parser.add_argument("--facturas", type=int, default=6000, help="facturas para contabilizar (60 clientes)")
    parser.add_argument("--cprofile", metavar="RUTA", help="perfil de Python (funciones más costosas) de UNA pantalla, p. ej. /tareas/hoy")
    parser.add_argument("--detalle", action="store_true", help="muestra también las consultas más lentas de cada pantalla")
    args = parser.parse_args()
    global FACTURAS
    FACTURAS = args.facturas

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
            ruta = args.cprofile.format(cuenta=cuenta, proyecto=proyecto, **NUCLEO)
            cli.get(ruta)
            perfil = cProfile.Profile()
            perfil.enable()
            cli.get(ruta)
            perfil.disable()
            pstats.Stats(perfil).sort_stats("tottime").print_stats(14)
            return 0

        def pasada(http, rutas):
            for ruta in rutas:
                medidas = []
                for _ in range(args.repeticiones + 1):  # la primera calienta cachés
                    tiempos.clear()
                    t0 = time.perf_counter()
                    r = http.get(ruta)
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

        print(f"{'pantalla':50s} {'ms':>5s} {'SQL ms':>7s} {'consultas':>9s} {'escrituras':>10s} {'KB':>5s}")
        pasada(cli, [p.format(cuenta=cuenta, proyecto=proyecto, **NUCLEO) for p in PANTALLAS])
        portal = app.test_client()
        token = db.crear_acceso_cliente_fiscal(NUCLEO["cfac"], "127.0.0.1", email=NUCLEO["pemail"])
        r = portal.get(f"/portal/entrar/{token}")
        print("(portal: entrada", r.status_code, ")")
        pasada(portal, [p.format(**NUCLEO) for p in PORTAL])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
