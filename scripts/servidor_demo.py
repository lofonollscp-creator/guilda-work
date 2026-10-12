"""Instancia temporal y aislada para revisar la aplicación en un navegador: base de datos en un directorio temporal, Kratos simulado (cualquier petición entra como
la persona de demostración) y sin hilos de fondo. NO toca datos reales ni servicios. La arranca scripts/comprobar_interaccion.sh desde una COPIA del repositorio.
Uso: python scripts/servidor_demo.py PUERTO"""
import os, sys, tempfile, time
from datetime import date, timedelta
from pathlib import Path
os.environ.setdefault("GUILDA_SECRET_KEY", "demo-no-secreta-" + "x" * 40)
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
tmp = Path(tempfile.mkdtemp(prefix="guilda-demo-"))
from app import db, kratos
db.DB_PATH = tmp / "demo.db"
db.BACKUPS_DIR = tmp / "backups"
db.init_db()
from app import nucleo, verticales, abogados, inmobiliaria, almacen_documentos as alm, cifrado_despacho as cd
cd.ARGON2 = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}
t = db.crear_tenant("Despacho Demo")
yo = db.crear_usuario_vinculado_a_kratos("demo@ejemplo.com", "k-demo"); db.asignar_tenant(yo, t); db.asignar_supervisor_tenant(yo, True)
ana = db.crear_usuario_vinculado_a_kratos("ana@ejemplo.com", "k-ana"); db.asignar_tenant(ana, t)
for v in ("gestoria", "abogados", "inmobiliaria"):
    verticales.fijar_activo(t, v, True)
hoy = date.today(); d = lambda n: (hoy + timedelta(days=n)).isoformat()
cl = [nucleo.crear_cliente(t, n, nif=f"{12345670+i}A", email=f"c{i}@ej.com", telefono="600 000 00%d" % i) for i, n in enumerate(["Carmen Soler", "Hijos de Vidal S.L.", "Marta Puig", "Panadería Roca S.L."])]
e1 = nucleo.crear_expediente(t, yo, cl[0], "Reclamación de cantidad", referencia="12/2026")
nucleo.crear_plazo(t, yo, "Contestar demanda", d(3), expediente_id=e1, critico=True, supervisor=True)
nucleo.crear_plazo(t, yo, "Presentar alegaciones", d(20), expediente_id=e1, supervisor=True)
nucleo.registrar_parte(t, yo, "Estudio del caso", minutos=90, expediente_id=e1)
x = nucleo.crear_expediente(t, yo, cl[1], "Asunto reservado", confidencial=True)
alm.guardar(yo, "contrato.txt", "text/plain", "Contrato de ejemplo".encode(), cliente_id=cl[0])
# abogados
ea = nucleo.crear_expediente(t, yo, cl[2], "Procedimiento ordinario 45/2026", tipo="procedimiento_judicial", referencia="PO 45/2026")
abogados.anadir_parte(t, yo, ea, "contraparte", "Constructora Delta S.A.", nif="A11111111", supervisor=True)
try: abogados.registrar_notificacion(t, yo, ea, "auto", d(-1), 20, "habiles", supervisor=True)
except Exception as e: print("notif", e)
# inmobiliaria
try:
    i1, xi = inmobiliaria.crear_inmueble(t, yo, cl[3], "venta", "Calle Mayor 12, 3º", tipo="piso", municipio="Barcelona", superficie_m2=85, habitaciones=3, banos=2, precio="250.000", caracteristicas=["ascensor", "terraza"])
    i2, xi2 = inmobiliaria.crear_inmueble(t, yo, cl[1], "alquiler", "Av. Diagonal 400", tipo="oficina", municipio="Barcelona", superficie_m2=120, precio="1.800")
    inmobiliaria.crear_demanda(t, yo, cl[0], "venta", tipos=["piso"], municipios=["Barcelona"], presupuesto_max="260.000", habitaciones_min=2)
except Exception as e: print("inmob", e)
# clientes fiscales
for n in ("Taller Pérez", "Bar La Plaza"):
    f = db.crear_cliente_fiscal(t, n, nif="B123", email="f@ej.com"); db.crear_vencimiento_fiscal(t, f, "303", "2026-T3", d(-5 if n[0] == "T" else 4))
kratos.whoami = lambda c: {"active": True, "identity": {"id": "k-demo", "traits": {"email": "demo@ejemplo.com"}}}
from app.main import app
_wsgi = app.wsgi_app
app.wsgi_app = lambda environ, start: _wsgi({**environ, 'HTTP_COOKIE': 'ory_kratos_session=demo'}, start)   # solo en esta instancia temporal
from waitress import serve
puerto = int(sys.argv[1])
print("LISTO", tmp, flush=True)
serve(app, host="127.0.0.1", port=puerto, threads=4)
