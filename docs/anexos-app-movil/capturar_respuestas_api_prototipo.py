"""Siembra datos sintéticos en la copia aislada y captura respuestas reales de GET /api/v1 para probar modelos Dart."""
import json, pathlib, re, sys, time, random
sys.path.insert(0, str(pathlib.Path.cwd()))
SALIDA = pathlib.Path("/tmp/claude-0/-root/3cdd7a64-398c-4ed2-8b6b-201b1dfe5877/scratchpad/capturas")
SALIDA.mkdir(exist_ok=True)
from app.main import app
from app import db

db.init_db()
random.seed(3)
ahora = time.strftime("%Y-%m-%dT%H:%M:%S")
dias = lambda n: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + n * 86400))  # noqa: E731
t = db.crear_tenant("Despacho Demo")
uid = db.crear_usuario_vinculado_a_kratos("demo@x.com", "k-demo")
db.asignar_tenant(uid, t)
otro = db.crear_usuario_vinculado_a_kratos("otro@x.com", "k-otro")
db.asignar_tenant(otro, t)
cli = db.crear_cliente_fiscal(t, "Cliente Uno SL", email="uno@cli.com")
cli2 = db.crear_cliente_fiscal(t, "Cliente Dos SA", email="dos@cli.com")
conn = db.get_connection()
cat = conn.execute("INSERT INTO categorias (usuario_id, nombre, color, creada_en) VALUES (?,?,?,?)", (uid, "Proyecto A", "#4a6cf7", ahora)).lastrowid
for k in range(6):
    conn.execute(
        "INSERT INTO tareas_outlook (usuario_id, asunto, estado, prioridad, fecha_vencimiento, creada_en, actualizada_en, categoria_id, cliente_fiscal_id) VALUES (?,?,?,?,?,?,?,?,?)",
        (uid, f"Tarea {k}", ["no_iniciada", "en_progreso", "completada"][k % 3], ["baja", "normal", "alta"][k % 3], dias(k - 2), ahora, ahora, cat, cli))
for k in range(4):
    conn.execute("INSERT INTO notas (usuario_id, texto, categoria_id, creada_en, titulo) VALUES (?,?,?,?,?)", (uid, "nota " * 5, cat, dias(-k), f"Nota {k}"))
for k, (m, p) in enumerate([("303", "3T"), ("130", "3T"), ("111", "4T")]):
    conn.execute("INSERT INTO vencimientos_fiscales (tenant_id, cliente_fiscal_id, usuario_id, modelo, periodo, fecha_limite, estado, creado_en) VALUES (?,?,?,?,?,?,?,?)",
                 (t, cli, uid, m, p, dias(k * 10 - 5)[:10], "pendiente" if k else "presentado", ahora))
cuenta = conn.execute("INSERT INTO correo_cuentas (usuario_id, nombre, protocolo, host, puerto, usuario, creada_en) VALUES (?, 'c', 'imap', 'h', 993, 'u', ?)", (uid, ahora)).lastrowid
for k in range(3):
    conn.execute("INSERT INTO correo_mensajes (cuenta_id, carpeta, uid, asunto, remitente, destinatarios, fecha, cuerpo_texto, message_id, leido, hilo_clave, descargado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 (cuenta, "INBOX", str(k), f"Asunto {k}", "Cliente <c@cli.com>", "yo@x.com", dias(-k), "cuerpo", f"<m{k}@x>", k % 2, f"h{k}", ahora))
conn.commit()
conn.close()
token = db.crear_token_api(uid, "captura")
cl = app.test_client()
H = {"Authorization": f"Bearer {token}"}

spec = json.load(open("/tmp/claude-0/-root/3cdd7a64-398c-4ed2-8b6b-201b1dfe5877/scratchpad/openapi_vivo.json"))
resultados = {}
ids_por_prefijo = {}
gets = [(p, o) for p, ms in spec["paths"].items() for m, o in ms.items() if m == "get"]
sin_param = [(p, o) for p, o in gets if "{" not in p]
con_param = [(p, o) for p, o in gets if "{" in p]
SALTAR = ("/export", "/openapi.json", "/health", "/avatar", "/ia/mensajes", "/sync")
for p, o in sin_param:
    ruta = p
    if any(ruta.endswith(s) for s in SALTAR):
        continue
    q = {}
    for par in o.get("parameters", []):
        if "$ref" in par: continue
        if par.get("required") and par["in"] == "query":
            q[par["name"]] = {"q": "a", "cliente_id": str(cli)}.get(par["name"], "1")
    r = cl.get(ruta, headers=H, query_string=q)
    resultados[ruta] = r.status_code
    if r.status_code == 200 and r.is_json:
        cuerpo = r.get_json()
        (SALIDA / (ruta.strip("/").replace("/", "__") + ".json")).write_text(json.dumps(cuerpo, ensure_ascii=False))
        d = cuerpo.get("data")
        if isinstance(d, list) and d and isinstance(d[0], dict) and "id" in d[0]:
            ids_por_prefijo[ruta] = d[0]["id"]
for p, o in con_param:
    m = re.fullmatch(r"(.*)/\{[a-z_]+\}(/[a-z\-]+)?", p)
    if not m: continue
    base, resto = m.group(1), m.group(2) or ""
    if base not in ids_por_prefijo: continue
    ruta = f"{base}/{ids_por_prefijo[base]}{resto}"
    q = {}
    for par in o.get("parameters", []):
        if "$ref" in par: continue
        if par.get("required") and par["in"] == "query": q[par["name"]] = "1"
    r = cl.get(ruta, headers=H, query_string=q)
    resultados[p] = r.status_code
    if r.status_code == 200 and r.is_json:
        (SALIDA / (p.strip("/").replace("/", "__").replace("{", "").replace("}", "") + ".json")).write_text(json.dumps(r.get_json(), ensure_ascii=False))
json.dump(resultados, open(SALIDA / "_estados.json", "w"), indent=1)
import collections
print(collections.Counter(resultados.values()), file=sys.stderr)
print({k: v for k, v in resultados.items() if v >= 400}, file=sys.stderr)
