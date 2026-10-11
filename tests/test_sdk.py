"""SDK de Python y TypeScript y colección de Postman generados del contrato OpenAPI (`app/sdk_generador.py`)."""
import json
import re
import shutil
import urllib.parse

import pytest

from app import eventos, openapi, sdk_generador
from tests.test_rutas_api import _auth, _registrar


@pytest.fixture
def spec(base_de_datos_temporal):
    from app.main import app as flask_app
    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    with flask_app.test_request_context():
        return openapi.generar_spec()


def _modulo_python(spec):
    espacio: dict = {"__name__": "guilda_work"}
    exec(compile(sdk_generador.generar_python(spec, "http://test"), "guilda_work.py", "exec"), espacio)
    return espacio


def _transporte(cliente):
    def transporte(metodo, url, cabeceras, datos, timeout):
        partes = urllib.parse.urlsplit(url)
        r = cliente.open(partes.path + (f"?{partes.query}" if partes.query else ""), method=metodo, headers=cabeceras, data=datos)
        return r.status_code, dict(r.headers), r.get_data()
    return transporte


# --- Estructura ------------------------------------------------------------------------------------------------------------------------

def test_el_cliente_de_python_tiene_un_metodo_por_operacion_y_compila(spec):
    modulo = _modulo_python(spec)
    ids = {op["id"] for op in sdk_generador.operaciones(spec)}
    metodos = {n for n in vars(modulo["Cliente"]) if not n.startswith("_")}
    en_el_spec = sum(1 for ops in spec["paths"].values() for m, op in ops.items() if m in {"get", "post", "put", "patch", "delete"})
    assert ids <= metodos and len(ids) == en_el_spec >= 237       # un método por operación, sin fijar la cifra (crece con la API)
    assert {"paginar", "sincronizar_desde"} <= metodos and "verificar_firma_webhook" in modulo and "ErrorGuilda" in modulo
    import inspect
    firma = inspect.signature(modulo["Cliente"].crear_nota)
    assert firma.parameters["texto"].default is inspect.Parameter.empty and firma.parameters["texto"].kind is inspect.Parameter.KEYWORD_ONLY
    assert firma.parameters["categoria_id"].default is None and "idempotency_key" in firma.parameters
    assert list(inspect.signature(modulo["Cliente"].obtener_nota).parameters)[:2] == ["self", "nota_id"]
    assert "Argumentos:" in modulo["Cliente"].crear_nota.__doc__ and "texto (str, obligatorio)" in modulo["Cliente"].crear_nota.__doc__


def test_el_cliente_de_typescript_cubre_todo_con_tipos(spec):
    codigo = sdk_generador.generar_typescript(spec, "http://test")
    for op in sdk_generador.operaciones(spec):
        assert re.search(rf"\basync {re.escape(sdk_generador._camel(op['id']))}\(", codigo), op["id"]
    for esquema in spec["components"]["schemas"]:
        assert re.search(rf"export (interface|type) {esquema}\b", codigo), esquema
    assert "export class ErrorGuilda" in codigo and "verificarFirmaWebhook" in codigo and "export interface CrearNotaCuerpo" in codigo and "texto: string;" in codigo
    assert codigo.count("{") == codigo.count("}") and codigo.count("(") == codigo.count(")")
    assert "__VERSION__" not in codigo and "__BASE_URL__" not in codigo and "http://test" in codigo


def test_la_coleccion_de_postman_es_completa_y_coherente(spec):
    c = sdk_generador.generar_postman(spec, "http://test")
    assert c["info"]["schema"].endswith("v2.1.0/collection.json") and {v["key"] for v in c["variable"]} == {"base_url", "token"}
    assert c["auth"]["bearer"][0]["value"] == "{{token}}" and "Idempotency-Key" in "\n".join(c["event"][0]["script"]["exec"])
    peticiones = [i for carpeta in c["item"] for i in carpeta["item"]]
    ops = sdk_generador.operaciones(spec)
    assert len(peticiones) == len(ops) and {carpeta["name"] for carpeta in c["item"]} == {o["etiqueta"] for o in ops}
    assert len({p["id"] for p in peticiones}) == len(peticiones)
    rutas_spec = {r.replace("{", ":").replace("}", "") for r in spec["paths"]}
    for p in peticiones:
        url = p["request"]["url"]
        assert "/" + "/".join(url["path"]) in rutas_spec, url["raw"]
        assert url["raw"].startswith("{{base_url}}/api/v1/") and "{" not in "/".join(url["path"]).replace("{{base_url}}", "")
        for variable in url["variable"]:
            assert f":{variable['key']}" in url["raw"]
        cuerpo = p["request"].get("body")
        if cuerpo and cuerpo["mode"] == "raw":
            json.loads(cuerpo["raw"])
        for r in p["response"]:
            json.loads(r["body"])
    login = next(p for p in peticiones if p["id"] == "login")
    assert login["request"]["auth"] == {"type": "noauth"} and any("collectionVariables.set(\"token\"" in linea for linea in login["event"][0]["script"]["exec"])
    assert json.loads(next(p for p in peticiones if p["id"] == "crear_nota")["request"]["body"]["raw"])["texto"].startswith("Llamar")
    assert any(b["type"] == "file" for b in next(p for p in peticiones if p["id"] == "subir_adjuntos_nota")["request"]["body"]["formdata"])
    json.dumps(c)                                                            # serializable


def test_las_descargas_estan_en_la_documentacion_y_apuntan_a_la_instancia(cliente):
    for nombre, mime in (("guilda_work.py", "text/x-python"), ("guilda-work.ts", "application/typescript"), ("guilda-work.postman_collection.json", "application/json")):
        r = cliente.get(f"/docs/sdk/{nombre}")
        assert r.status_code == 200 and r.mimetype == mime and f'filename="{nombre}"' in r.headers["Content-Disposition"], nombre
        assert "127.0.0.1:8000" in r.get_data(as_text=True)                   # ya apunta a esta instancia
    compile(cliente.get("/docs/sdk/guilda_work.py").get_data(as_text=True), "x.py", "exec")
    assert cliente.get("/docs/sdk/otra_cosa.py").status_code == 404
    html = cliente.get("/docs/sdk").get_data(as_text=True)
    assert "guilda_work.py" in html and "guilda-work.ts" in html and "postman_collection" in html and "verificar_firma_webhook" in html


# --- El cliente de Python contra la API real ------------------------------------------------------------------------------------------------

def test_el_cliente_de_python_funciona_de_punta_a_punta(cliente, spec):
    m = _modulo_python(spec)
    g = m["Cliente"](base_url="http://test", transporte=_transporte(cliente), esperar=lambda s: None)
    sesion = g.registro(email="sdk@ejemplo.com", contrasena="contrasena123")
    assert sesion["token"] and g.token == sesion["token"]                         # el login/registro guarda el token
    nota = g.crear_nota(texto="desde el SDK", referencia_externa="SDK-1")
    assert nota["referencia_externa"] == "SDK-1" and g.ultima.status == 201 and g.ultima.request_id
    assert g.nota_por_referencia("SDK-1")["id"] == nota["id"]
    assert g.upsert_nota("SDK-1", texto="otra versión")["id"] == nota["id"]
    for i in range(5):
        g.crear_nota(texto=f"n{i}")
    pagina = g.listar_notas(limit=2, offset=1)
    assert len(pagina) == 2 and g.ultima.total == 6
    assert len(list(g.paginar(g.listar_notas, por_pagina=4))) == 6                # recorre todas las páginas
    assert [n["id"] for n in g.listar_notas(campos="id")][0] and set(g.listar_notas(campos="id")[0]) == {"id"}
    tarea = g.crear_tarea_outlook(asunto="T", fecha_vencimiento="2030-01-10")
    assert g.cambiar_estado_tarea(tarea["id"], estado="en_progreso")["estado"] == "en_progreso"
    assert g.accion_en_lote(ids=[tarea["id"]], accion="prioridad", valor="alta") == {"ok": 1, "fallos": 0}
    with pytest.raises(m["ErrorGuilda"]) as e:
        g.obtener_nota(99999)
    assert (e.value.status, e.value.codigo) == (404, "no_encontrado") and e.value.request_id and "no_encontrado" in str(e.value)
    with pytest.raises(m["ErrorGuilda"]) as e:
        g.cambiar_estado_tarea(tarea["id"], estado="inventado")
    assert e.value.codigo == "estado_invalido" and e.value.campo == "estado"
    # multipart y binario
    r = g.subir_adjuntos_nota(nota["id"], adjunto=[("a.txt", b"hola adjunto", "text/plain"), ("b.txt", b"segundo")])
    assert [x["ok"] for x in r] == [True, True]
    adj = g.listar_adjuntos_nota(nota["id"])
    assert g.descargar_adjunto_nota(adj[0]["id"]) in (b"hola adjunto", b"segundo")
    # sincronización
    cursor = g.sincronizar()["cursor"]
    g.crear_nota(texto="nueva")
    lotes = list(g.sincronizar_desde(cursor))
    assert lotes[0]["cambios"]["notas"][0]["texto"] == "nueva"
    # el token de otro usuario no ve lo de este
    otro = m["Cliente"](base_url="http://test", transporte=_transporte(cliente), esperar=lambda s: None)
    otro.registro(email="sdk2@ejemplo.com", contrasena="contrasena123")
    with pytest.raises(m["ErrorGuilda"]):
        otro.obtener_nota(nota["id"])


def test_reintentos_idempotencia_y_limite_del_cliente_de_python(cliente, spec):
    m = _modulo_python(spec)
    base = m["Cliente"](base_url="http://test", transporte=_transporte(cliente), esperar=lambda s: None)
    token = base.registro(email="sdk3@ejemplo.com", contrasena="contrasena123")["token"]
    real = _transporte(cliente)
    llamadas, esperas = [], []

    def inestable(metodo, url, cabeceras, datos, timeout):
        llamadas.append((metodo, dict(cabeceras)))
        if len(llamadas) == 1:
            raise ConnectionError("se cortó la red")                              # la petición llega, pero el cliente no lo sabe
        if len(llamadas) == 2:
            return 429, {"Retry-After": "7"}, b'{"ok": false, "error": "x", "codigo": "limite_excedido"}'
        return real(metodo, url, cabeceras, datos, timeout)

    g = m["Cliente"](token=token, base_url="http://test", transporte=inestable, esperar=esperas.append)
    nota = g.crear_nota(texto="una sola vez")
    assert nota["texto"] == "una sola vez" and g.ultima.reintentos == 2 and esperas[1] == 7.0           # respeta Retry-After
    claves = {c[1]["Idempotency-Key"] for c in llamadas}
    assert len(claves) == 1                                                       # misma clave en todos los intentos
    assert len(g.listar_notas()) == 1
    # un 5xx persistente agota los reintentos y devuelve el error
    g2 = m["Cliente"](token=token, base_url="http://test", transporte=lambda *a: (503, {}, b'{"ok": false, "error": "caido", "codigo": "error_interno"}'), reintentos=2, esperar=lambda s: None)
    with pytest.raises(m["ErrorGuilda"]) as e:
        g2.listar_notas()
    assert e.value.status == 503
    # un GET repetido con ETag usa la copia local
    g3 = m["Cliente"](token=token, base_url="http://test", transporte=real, usar_etag=True, esperar=lambda s: None)
    g3.listar_notas(); g3.listar_notas()
    assert g3.ultima.status == 304


def test_verificar_firma_webhook_del_cliente_de_python(spec):
    m = _modulo_python(spec)
    cuerpo = b'{"evento": "nota.creada", "datos": {"nota_id": 5}}'
    import time
    firma = eventos.firmar_v2(cuerpo, "secreto-123", int(time.time()))
    cab = {"X-Guilda-Signature-V2": firma}
    assert m["verificar_firma_webhook"](cuerpo, cab, "secreto-123") is True
    assert m["verificar_firma_webhook"](cuerpo + b" ", cab, "secreto-123") is False        # cuerpo alterado
    assert m["verificar_firma_webhook"](cuerpo, cab, "otro-secreto") is False
    vieja = eventos.firmar_v2(cuerpo, "secreto-123", int(time.time()) - 3600)
    assert m["verificar_firma_webhook"](cuerpo, {"x-guilda-signature-v2": vieja}, "secreto-123") is False   # repetición tardía
    assert m["verificar_firma_webhook"](cuerpo, {}, "secreto-123") is False


@pytest.mark.skipif(not shutil.which("tsc"), reason="sin TypeScript instalado (se comprueba a mano con node en Docker)")
def test_el_cliente_de_typescript_compila_en_modo_estricto(spec, tmp_path):
    import subprocess
    (tmp_path / "guilda-work.ts").write_text(sdk_generador.generar_typescript(spec))
    r = subprocess.run(["tsc", "--noEmit", "--strict", "--target", "es2020", "--lib", "es2020,dom", str(tmp_path / "guilda-work.ts")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[:2000]
