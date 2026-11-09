"""Mide el tiempo y las consultas SQL de las pantallas del PORTAL de cliente (y de las del equipo que lo atienden) con datos sintéticos de un despacho grande: un cliente con mucho historial y miles de clientes
más pequeños. NUNCA toca la base real: crea la suya en un directorio temporal.

    scripts/probar.sh --ejecutar scripts/perfil_portal.py [--clientes 2000] [--facturas 1500] [--detalle]

Las cifras son relativas (un solo usuario, SQLite, sin red): sirven para detectar pantallas que crecen con el volumen y para comparar antes y después de optimizar."""
import argparse
import collections
import random
import re
import shutil
import statistics
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

PORTAL = ["/portal/", "/portal/facturas", "/portal/impuestos", "/portal/mensajes", "/portal/avisos", "/portal/carpeta", "/portal/documentos", "/portal/documentos?q=contrato", "/portal/actividad",
          "/portal/cuestionarios", "/portal/peticiones", "/portal/justificantes", "/portal/buscar?q=factura", "/portal/gestiones", "/portal/dossier", "/portal/glosario", "/portal/cuenta"]
EQUIPO = ["/fiscal/portal-adopcion", "/fiscal/bandeja-portal", "/fiscal/dossiers", "/fiscal/portal-actividad", "/fiscal/clientes"]
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def sembrar(db, n_clientes: int, n_facturas: int):
    from app import almacen_documentos, facturas_contables as fc, portal_conversaciones as pc, portal_novedades, portal_peticiones, verticales
    from app.db_fiscal import crear_cliente_fiscal
    random.seed(11)
    t = db.crear_tenant("Perf Portal")
    u = db.crear_usuario_vinculado_a_kratos("perfportal@x.com", "kperf")
    db.asignar_tenant(u, t)
    db.asignar_supervisor_tenant(u, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    verticales.fijar_activo(t, "gestoria", True)
    grande = crear_cliente_fiscal(t, "Cliente Grande SL", nif="B12345678", email="grande@x.com")
    hoy = date.today()
    for i in range(n_facturas):
        f = hoy - timedelta(days=random.randint(0, 400))
        fid = fc.crear_desde_portal(grande, {"tipo": random.choice(["recibida", "recibida", "emitida"]), "fecha": f.isoformat(), "numero": f"F-{i}", "tercero_nombre": f"Proveedor {i % 120}", "tercero_nif": "B87654323",
                                           "total": f"{random.randint(20, 5000)},00", "pct_iva": "21"})
        if i % 40:                                                                      # casi todas revisadas: el portal limita las pendientes
            conn = db.get_connection(); conn.execute("UPDATE facturas_contables SET estado = 'revisada', revisado_en = ? WHERE id = ?", (datetime.now().isoformat(timespec="seconds"), fid)); conn.commit(); conn.close()
    ficha = db.obtener_cliente_fiscal_por_id(grande)
    for i in range(300):
        almacen_documentos.guardar_de_cliente_fiscal_sin_usuario(t, grande, f"contrato-{i}.pdf", "application/pdf", PDF + str(i).encode())
    conn = db.get_connection()
    conn.execute("UPDATE cliente_documentos SET portal_visible = 1, portal_origen = 'cliente', portal_carpeta = 'contratos', portal_texto = 'contrato de alquiler del local' WHERE cliente_fiscal_id = ?", (grande,))
    conn.commit(); conn.close()
    for i in range(150):
        cid = pc.iniciar(ficha, f"Asunto {i}", "Hola, una duda sobre el trimestre", "cliente" if i % 2 else "despacho", "grande@x.com")
        if i < 140:
            pc.cambiar_estado(ficha, cid, abierta=False)                                # el portal limita las abiertas: el resto, cerradas (historial)
    for i in range(60):
        db.crear_vencimiento_fiscal(t, grande, ["303", "130", "111"][i % 3], f"{i // 3 % 4 + 1}T {2020 + i // 12}", (hoy + timedelta(days=random.randint(-300, 90))).isoformat(), usuario_id=u)
    for i in range(80):
        portal_peticiones.crear(ficha, f"Petición {i}", por=u) if i < 20 else None
    for i in range(400):
        portal_novedades.anotar(ficha, f"Aviso {i}", "detalle", "/portal/")
    for i in range(n_clientes):
        c = crear_cliente_fiscal(t, f"Cliente {i}", nif=None, email=f"c{i}@x.com")
        if i % 5 == 0:
            pc.iniciar(db.obtener_cliente_fiscal_por_id(c), f"Duda {i}", "Hola", "cliente", f"c{i}@x.com")
    return t, u, grande


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clientes", type=int, default=2000)
    ap.add_argument("--facturas", type=int, default=1500)
    ap.add_argument("--repeticiones", type=int, default=3)
    ap.add_argument("--detalle", action="store_true")
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="guilda-perfil-portal-"))
    try:
        from app import db, kratos
        db.DB_PATH = tmp / "perf.db"
        db.BACKUPS_DIR = tmp / "backups"
        db.init_db()
        t0 = time.perf_counter()
        t, u, grande = sembrar(db, args.clientes, args.facturas)
        print(f"datos sintéticos listos en {time.perf_counter() - t0:.0f} s ({args.clientes} clientes, {args.facturas} facturas, 300 documentos)")
        kratos.whoami = lambda c: {"active": True, "identity": {"id": "kperf", "traits": {"email": "perfportal@x.com"}}}
        from app.main import app
        app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
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

        print(f"{'pantalla':44s} {'ms':>6s} {'SQL ms':>7s} {'consultas':>9s} {'KB':>5s}")
        for etiqueta, rutas, entrar in (("PORTAL", PORTAL, "portal"), ("EQUIPO", EQUIPO, "equipo")):
            cli = app.test_client()
            if entrar == "portal":
                cli.get(f"/portal/entrar/{db.crear_acceso_cliente_fiscal(grande, '127.0.0.1', email='grande@x.com')}")
            else:
                cli.set_cookie("ory_kratos_session", "x", domain="127.0.0.1")
            print(f"-- {etiqueta}")
            for ruta in rutas:
                medidas = []
                for _ in range(args.repeticiones + 1):
                    tiempos.clear()
                    t0 = time.perf_counter()
                    r = cli.get(ruta)
                    total = (time.perf_counter() - t0) * 1000
                    medidas.append((total, sum(v[1] for v in tiempos.values()), sum(v[0] for v in tiempos.values()), len(r.data) // 1024, r.status_code))
                medidas = medidas[1:]
                ult = medidas[-1]
                marca = "" if ult[4] == 200 else f"  HTTP {ult[4]}"
                print(f"{ruta[:44]:44s} {statistics.median(m[0] for m in medidas):6.0f} {statistics.median(m[1] for m in medidas):7.0f} {ult[2]:9d} {ult[3]:5d}{marca}")
                if args.detalle:
                    for k, (veces, tms) in sorted(tiempos.items(), key=lambda kv: -kv[1][1])[:3]:
                        print(f"      {tms:6.1f} ms {veces}x {k}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
