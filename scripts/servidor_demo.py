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
# correo de demostración: una cuenta con dos mensajes (uno con adjunto), entrados por el mismo camino que la sincronización real
from email.message import EmailMessage
from app import correo
cuenta_correo = db.crear_cuenta_correo(yo, "Trabajo", "imap", "h", 993, "yo@despacho.com")
for n, (asunto, de, cuerpo, adj) in enumerate([("Reclamación del IVA trimestral", "Marta Puig <marta@cliente.example>", "Adjunto la documentación pedida, plenilunio.", True), ("Cita para la firma", "Notaría Roca <info@notaria.example>", "Le esperamos el jueves.", False)], 1):
    m = EmailMessage(); m["Subject"], m["From"], m["To"], m["Message-ID"], m["Date"] = asunto, de, "yo@despacho.com", f"<m{n}@demo.example>", "Mon, 12 Oct 2026 10:00:00 +0200"
    m.set_content(cuerpo)
    if adj: m.add_attachment(b"%PDF-demo", maintype="application", subtype="pdf", filename="nomina.pdf")
    correo._guardar_mensaje_imap(db.obtener_cuenta_correo(yo, cuenta_correo), "INBOX", str(n), bytes(m), set())
# personal: jornada, turnos, una ausencia por aprobar y fichajes de ayer para la bolsa de horas
from app import ausencias as _aus, turnos as _tur
db.guardar_fichaje_datos(yo, nombre_completo="Persona Demo", dni_nie="1X", jornada_semanal_horas=40)
db.guardar_fichaje_datos(ana, nombre_completo="Ana Demo", dni_nie="2X", jornada_semanal_horas=40)
_t1 = _tur.crear_tipo(t, yo, "Mañana", "08:00", "15:00", "#3b82f6"); _tur.crear_tipo(t, yo, "Tarde", "15:00", "22:00", "#f59e0b")
_lunes = _tur.lunes_de(hoy)
for _i in range(5):
    _tur.asignar(t, yo, ana, d((_lunes - hoy).days + _i), _t1)
_dia = hoy + timedelta(days=21)
while _dia.weekday() != 0: _dia += timedelta(days=1)
_aus.solicitar(t, ana, "vacaciones", _dia.isoformat(), (_dia + timedelta(days=4)).isoformat(), motivo="Semana de descanso")
_c = db.get_connection()
for _tipo, _h in (("entrada", "09:00"), ("salida", "18:00")):
    _c.execute("INSERT INTO fichajes (usuario_id, tenant_id, tipo, marca_tiempo, origen, creado_por, creado_en) VALUES (?, ?, ?, ?, 'web', ?, ?)", (yo, t, _tipo, f"{(hoy - timedelta(days=1)).isoformat()}T{_h}:00", yo, db.now_iso()))
_c.commit(); _c.close()
# certificados: uno que caduca pronto con un servicio registrado y otro sin cobertura
from datetime import datetime, timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from app import certificados as _cert
def _hacer_cert(cn, nif, dias):
    k = ec.generate_private_key(ec.SECP256R1()); n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn), x509.NameAttribute(NameOID.SERIAL_NUMBER, nif)]); ahora = datetime.now(timezone.utc)
    c = x509.CertificateBuilder().subject_name(n).issuer_name(n).public_key(k.public_key()).serial_number(x509.random_serial_number()).not_valid_before(ahora - timedelta(days=300)).not_valid_after(ahora + timedelta(days=dias)).sign(k, hashes.SHA256())
    return c.public_bytes(serialization.Encoding.PEM)
_c1 = _cert.importar(t, yo, _hacer_cert("MARTA PUIG", "IDCES-12345678Z", 25), ubicacion_externa="Tarjeta en la caja fuerte de Girona")["id"]
_cert.cambiar_estado_operativo(t, yo, _c1, "autorizado")
_cert.vincular(t, yo, _c1, cliente_fiscal_id=db.listar_clientes_fiscales(t)[0]["id"], servicio="presentacion", autorizacion="Apoderamiento firmado el 01/06/2026")
_cert.importar(t, yo, _hacer_cert("CONSTRUCCIONES VIDAL SL", "IDCES-B12345674", 400))
# fase E: responsables de cliente y un traspaso pendiente
from app import traspasos as _tr
_cl = db.listar_clientes_fiscales(t)
_tr.asignar_responsable(t, yo, _cl[0]["id"], ana)
_tr.asignar_responsable(t, yo, _cl[1]["id"], yo)
_tr.proponer(t, yo, _cl[1]["id"], ana, nota="Falta el modelo 303 del T3 y pedir el justificante de la domiciliación")
kratos.whoami = lambda c: {"active": True, "identity": {"id": "k-demo", "traits": {"email": "demo@ejemplo.com"}}}
from app.main import app
_wsgi = app.wsgi_app
app.wsgi_app = lambda environ, start: _wsgi({**environ, 'HTTP_COOKIE': 'ory_kratos_session=demo'}, start)   # solo en esta instancia temporal
from waitress import serve
puerto = int(sys.argv[1])
print("LISTO", tmp, flush=True)
serve(app, host="127.0.0.1", port=puerto, threads=4)
