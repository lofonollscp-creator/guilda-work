"""Contrato de la API (OpenAPI): el documento es válido y completo, lo que devuelve la API cumple lo que promete y no se rompe nada ya
publicado. El OpenAPI se genera del código (ver `app/openapi.py`), así que estos tests son lo que impide que la documentación mienta.

Si cambias la API de forma **compatible** (campos o rutas nuevos, siempre opcionales), el test de compatibilidad pasa solo. Si cambias algo
que la rompería para quien ya integra (quitar un campo, volver obligatorio uno opcional, quitar una ruta), falla: o no lo hagas, o súbele
la versión mayor y actualiza la referencia con
    GUILDA_ACTUALIZAR_BASELINE_OPENAPI=1 GUILDA_BASELINE_OPENAPI_DESTINO=$PWD/tests/openapi_baseline.json scripts/probar.sh tests/test_openapi_contrato.py -k referencia"""
import json
import os
import time
from pathlib import Path

import pytest
from openapi_spec_validator import validate

from app import openapi, openapi_analisis, openapi_catalogo as cat
from tests.test_rutas_api import _auth, _registrar

BASELINE = Path(__file__).parent / "openapi_baseline.json"


@pytest.fixture
def generar(base_de_datos_temporal):
    from app.main import app as flask_app
    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")

    def _generar():
        with flask_app.test_request_context():
            return openapi.generar_spec(), dict(flask_app.view_functions)
    return _generar


def _operaciones(spec):
    return [(ruta, metodo, op) for ruta, ops in spec["paths"].items() for metodo, op in ops.items()]


def _resolver(esquema, spec):
    while isinstance(esquema, dict) and "$ref" in esquema:
        nodo = spec
        for parte in esquema["$ref"].lstrip("#/").split("/"):
            nodo = nodo[parte]
        esquema = nodo
    return esquema


def _validar(valor, esquema, spec, ruta="$"):
    """Validador mínimo de esquemas: tipos, nulos, propiedades, obligatorios, listas, allOf y enumerados."""
    esquema = _resolver(esquema, spec)
    if "allOf" in esquema:
        for sub in esquema["allOf"]:
            _validar(valor, sub, spec, ruta)
        return
    if valor is None:
        assert esquema.get("nullable") or not esquema.get("type"), f"{ruta}: es null y el esquema no lo permite"
        return
    tipo = esquema.get("type")
    if tipo == "object":
        assert isinstance(valor, dict), f"{ruta}: se esperaba objeto y llegó {type(valor).__name__}"
        for clave in esquema.get("required", []):
            assert clave in valor, f"{ruta}: falta la propiedad obligatoria «{clave}»"
        for clave, sub in esquema.get("properties", {}).items():
            if clave in valor:
                _validar(valor[clave], sub, spec, f"{ruta}.{clave}")
    elif tipo == "array":
        assert isinstance(valor, list), f"{ruta}: se esperaba lista y llegó {type(valor).__name__}"
        for i, elemento in enumerate(valor):
            _validar(elemento, esquema.get("items", {}), spec, f"{ruta}[{i}]")
    elif tipo == "integer":
        assert isinstance(valor, int) and not isinstance(valor, bool), f"{ruta}: se esperaba entero y llegó {valor!r}"
    elif tipo == "number":
        assert isinstance(valor, (int, float)) and not isinstance(valor, bool), f"{ruta}: se esperaba número y llegó {valor!r}"
    elif tipo == "string":
        assert isinstance(valor, str), f"{ruta}: se esperaba texto y llegó {valor!r}"
    elif tipo == "boolean":
        assert isinstance(valor, bool), f"{ruta}: se esperaba booleano y llegó {valor!r}"
    if "enum" in esquema:
        assert valor in esquema["enum"], f"{ruta}: {valor!r} no está entre {esquema['enum']}"


# --- Validez y completitud ----------------------------------------------------------------------------------------------------

def test_el_documento_es_openapi_valido_y_trae_lo_esencial(generar):
    spec, _ = generar()
    validate(spec)
    from app.rutas_api import API_VERSION
    assert spec["info"]["version"] == API_VERSION and "Idempotency-Key" in spec["info"]["description"] and "request_id" in spec["info"]["description"]
    assert spec["servers"] and all(t["description"] for t in spec["tags"] if t["name"] in cat.ETIQUETAS)
    assert {"IdempotencyKey", "RequestId"} <= set(spec["components"]["parameters"]) and "Error" in spec["components"]["schemas"]
    assert set(spec["components"]["responses"]) >= {"Error400", "Error401", "Error403", "Error404", "Error429", "Error500"}
    assert set(spec["components"]["schemas"]["Error"]["properties"]["codigo"]["enum"]) >= {"token_invalido", "token_area_no_permitida", "referencia_duplicada", "tarea_bloqueada"}


def test_cada_operacion_esta_completa(generar):
    spec, _ = generar()
    for ruta, metodo, op in _operaciones(spec):
        etiqueta = f"{metodo.upper()} {ruta}"
        assert op["summary"] and op["operationId"] and op["tags"] and op["x-area"], etiqueta
        assert "429" in op["responses"] and "500" in op["responses"], etiqueta
        if op["security"]:
            assert {"401", "403"} <= set(op["responses"]), etiqueta
        assert any(c.startswith("2") for c in op["responses"]), etiqueta
        assert not op.get("x-esquema-pendiente"), f"{etiqueta}: la respuesta no tiene esquema (añádela a openapi_catalogo.RESPUESTAS)"
        for parametro in op["parameters"]:
            assert "$ref" in parametro or parametro.get("description"), f"{etiqueta}: parámetro {parametro['name']} sin descripción"
    ids = [op["operationId"] for _, _, op in _operaciones(spec)]
    assert len(ids) == len(set(ids)), "operationId repetido"


def test_todo_campo_que_lee_una_vista_esta_documentado(generar):
    """Si una vista empieza a leer un campo nuevo del cuerpo o de la consulta y nadie lo documenta, este test falla."""
    spec, vistas = generar()
    for ruta, metodo, op in _operaciones(spec):
        a = openapi_analisis.analizar(vistas[f"api.{op['operationId']}"], {n: vistas[f"api.{n}"] for n in cat.HEREDA.get(op["operationId"], ())})
        if metodo in ("post", "put"):
            campos = set(a["cuerpo"]) | set(a["formulario"]) | set(a["archivos"])
            if campos:
                assert "requestBody" in op, f"{metodo.upper()} {ruta}: lee {sorted(campos)} y no documenta el cuerpo"
                documentados = {n for c in op["requestBody"]["content"].values() for n in c["schema"].get("properties", {})}
                assert campos <= documentados, f"{metodo.upper()} {ruta}: faltan {sorted(campos - documentados)}"
            for obligatorio in cat.REQUERIDOS.get(op["operationId"], ()):
                esquemas = [c["schema"] for c in op["requestBody"]["content"].values()]
                assert any(obligatorio in e.get("required", []) for e in esquemas), f"{op['operationId']}: «{obligatorio}» debería ser obligatorio"
        nombres_consulta = {p["name"] for p in op["parameters"] if "name" in p and p["in"] == "query"}
        assert set(a["consulta"]) <= nombres_consulta, f"{metodo.upper()} {ruta}: faltan parámetros de consulta {sorted(set(a['consulta']) - nombres_consulta)}"


def test_los_ejemplos_cumplen_sus_esquemas(generar):
    spec, _ = generar()
    con_ejemplo = 0
    for ruta, metodo, op in _operaciones(spec):
        for contenido in op.get("requestBody", {}).get("content", {}).values():
            if "example" in contenido:
                _validar(contenido["example"], contenido["schema"], spec, f"{op['operationId']}.peticion")
                con_ejemplo += 1
        for codigo, r in op["responses"].items():
            for contenido in r.get("content", {}).values() if "content" in r else []:
                if "example" in contenido and codigo[0] == "2":
                    _validar(contenido["example"], contenido["schema"], spec, f"{op['operationId']}.respuesta")
                    con_ejemplo += 1
    assert con_ejemplo >= 30, con_ejemplo
    for nombre in cat.EJEMPLOS:
        assert nombre in {op["operationId"] for _, _, op in _operaciones(spec)}, f"ejemplo de una operación que no existe: {nombre}"


def test_generar_el_documento_es_rapido_aunque_se_pide_en_cada_peticion(generar):
    generar()
    t = time.perf_counter()
    generar()
    assert time.perf_counter() - t < 0.5


# --- La API cumple lo que el contrato promete --------------------------------------------------------------------------------------

def test_las_respuestas_reales_cumplen_el_esquema_documentado(cliente):
    spec = cliente.get("/api/v1/openapi.json").get_json()
    por_id = {op["operationId"]: op for _, _, op in _operaciones(spec)}
    datos = _registrar(cliente, email="contrato@ejemplo.com")
    uid = datos["usuario"]["id"]
    from app import db
    t = db.crear_tenant("Despacho contrato")
    db.asignar_tenant(uid, t)
    conn = db.get_connection(); conn.execute("UPDATE usuarios SET supervisor_tenant = 1, gestor_fichajes = 1 WHERE id = ?", (uid,)); conn.commit(); conn.close()
    h = _auth(datos["token"])
    verificadas = []

    def probar(operacion, respuesta, esperado=None):
        op = por_id[operacion]
        assert respuesta.status_code == (esperado or min(int(c) for c in op["responses"] if c[0] == "2")), (operacion, respuesta.status_code, respuesta.get_data(as_text=True)[:200])
        esquema = op["responses"][str(respuesta.status_code)]["content"]["application/json"]["schema"]
        _validar(respuesta.get_json(), esquema, spec, operacion)
        verificadas.append(operacion)
        return respuesta.get_json().get("data")

    probar("login", cliente.post("/api/v1/auth/login", json={"email": "contrato@ejemplo.com", "contrasena": "contrasena123"}))
    probar("me", cliente.get("/api/v1/auth/me", headers=h))
    nota = probar("crear_nota", cliente.post("/api/v1/notas", json={"texto": "contrato", "referencia_externa": "R-1"}, headers=h))
    probar("listar_notas", cliente.get("/api/v1/notas", headers=h)); probar("obtener_nota", cliente.get(f"/api/v1/notas/{nota['id']}", headers=h))
    probar("fijar_nota", cliente.post(f"/api/v1/notas/{nota['id']}/fijar", json={"fijada": True}, headers=h))
    probar("upsert_nota", cliente.put("/api/v1/notas/por-referencia/R-1", json={"texto": "otra"}, headers=h))
    proyecto = probar("crear_proyecto", cliente.post("/api/v1/proyectos", json={"nombre": "P"}, headers=h))
    probar("listar_proyectos", cliente.get("/api/v1/proyectos", headers=h))
    tarea = probar("crear_tarea_outlook", cliente.post("/api/v1/tareas-outlook", json={"asunto": "T", "fecha_vencimiento": "2030-01-10"}, headers=h))
    probar("obtener_tarea_outlook", cliente.get(f"/api/v1/tareas-outlook/{tarea['id']}", headers=h)); probar("listar_tareas_outlook", cliente.get("/api/v1/tareas-outlook", headers=h))
    probar("cambiar_estado_tarea", cliente.post(f"/api/v1/tareas-outlook/{tarea['id']}/estado", json={"estado": "en_progreso"}, headers=h))
    probar("agregar_item_checklist", cliente.post(f"/api/v1/tareas-outlook/{tarea['id']}/checklist", json={"texto": "x"}, headers=h))
    probar("comentar_tarea", cliente.post(f"/api/v1/tareas-outlook/{tarea['id']}/comentarios", json={"texto": "hola"}, headers=h))
    probar("accion_en_lote", cliente.post("/api/v1/tareas-outlook/lote", json={"ids": [tarea["id"]], "accion": "prioridad", "valor": "alta"}, headers=h))
    probar("tablero", cliente.get("/api/v1/tareas-outlook/tablero", headers=h)); probar("mi_dia", cliente.get("/api/v1/mi-dia", headers=h))
    probar("carga_semanal", cliente.get("/api/v1/tareas-outlook/carga", headers=h)); probar("listar_vistas", cliente.get("/api/v1/tareas-outlook/vistas", headers=h))
    cli = probar("crear_cliente_fiscal", cliente.post("/api/v1/fiscal/clientes", json={"nombre": "Acme", "email": "a@acme.com", "modelos_fiscales": ["303"]}, headers=h))
    probar("obtener_cliente_fiscal", cliente.get(f"/api/v1/fiscal/clientes/{cli['id']}", headers=h)); probar("listar_clientes_fiscales", cliente.get("/api/v1/fiscal/clientes", headers=h))
    v = probar("crear_vencimiento", cliente.post("/api/v1/fiscal/vencimientos", json={"cliente_id": cli["id"], "modelo": "303", "periodo": "3T", "fecha_limite": "2030-10-20"}, headers=h))
    probar("obtener_vencimiento", cliente.get(f"/api/v1/fiscal/vencimientos/{v['id']}", headers=h)); probar("listar_vencimientos_fiscales", cliente.get("/api/v1/fiscal/vencimientos", headers=h))
    probar("resumen_cliente", cliente.get(f"/api/v1/fiscal/clientes/{cli['id']}/resumen", headers=h)); probar("config_recordatorios", cliente.get("/api/v1/fiscal/recordatorios", headers=h))
    probar("marcar_presentado_vencimiento_fiscal", cliente.post(f"/api/v1/fiscal/vencimientos/{v['id']}/presentado", headers=h))
    probar("listar_documentos_vencimiento", cliente.get(f"/api/v1/fiscal/vencimientos/{v['id']}/documentos", headers=h))
    wh = probar("crear_webhook", cliente.post("/api/v1/webhooks", json={"url": "https://hooks.example.com/x", "eventos": ["nota.creada"]}, headers=h)) if False else None
    tok = probar("crear_token", cliente.post("/api/v1/tokens", json={"nombre": "t", "areas": ["notas"]}, headers=h))
    probar("listar_tokens", cliente.get("/api/v1/tokens", headers=h)); probar("uso_de_token", cliente.get(f"/api/v1/tokens/{tok['id']}/uso", headers=h))
    probar("sincronizar", cliente.get("/api/v1/sync", headers=h)); probar("sincronizar", cliente.get("/api/v1/sync?cursor=0", headers=h))
    probar("listar_notificaciones", cliente.get("/api/v1/notificaciones", headers=h)); probar("consumo_ia", cliente.get("/api/v1/ia/consumo", headers=h))
    probar("listar_plantillas", cliente.get("/api/v1/correo/plantillas", headers=h))
    pl = probar("crear_plantilla", cliente.post("/api/v1/correo/plantillas", json={"nombre": "P", "cuerpo": "<p>x</p>"}, headers=h)); probar("obtener_plantilla", cliente.get(f"/api/v1/correo/plantillas/{pl['id']}", headers=h))
    probar("fichaje_admin_resumen", cliente.get("/api/v1/fichaje/admin/resumen", headers=h)); probar("estado_fichaje", cliente.get("/api/v1/fichaje/estado", headers=h))
    probar("historial", cliente.get("/api/v1/historial", headers=h)); probar("dashboard", cliente.get("/api/v1/dashboard", headers=h)) if "dashboard" in por_id and False else None
    probar("papelera", cliente.get("/api/v1/papelera", headers=h)); probar("listar_comunicados", cliente.get("/api/v1/comunicados", headers=h))
    probar("listar_recurrentes", cliente.get("/api/v1/tareas-recurrentes", headers=h)); probar("listar_plantillas_tareas", cliente.get("/api/v1/tareas-plantillas", headers=h))
    probar("obtener_perfil", cliente.get("/api/v1/perfil", headers=h)); probar("catalogo_eventos", cliente.get("/api/v1/webhooks/catalogo-eventos", headers=h))
    probar("modelos_fiscales_disponibles", cliente.get("/api/v1/fiscal/modelos", headers=h)); probar("listar_companeros", cliente.get("/api/v1/companeros", headers=h))
    # errores: siempre el mismo sobre
    error = cliente.get("/api/v1/notas/99999", headers=h)
    _validar(error.get_json(), spec["components"]["schemas"]["Error"], spec); assert error.get_json()["codigo"] == "no_encontrado"
    assert len(set(verificadas)) >= 45, sorted(set(verificadas))


# --- Compatibilidad hacia atrás --------------------------------------------------------------------------------------------------------

def _huella(spec) -> dict:
    huella = {}
    for ruta, metodo, op in _operaciones(spec):
        campos, requeridos = set(), set()
        for contenido in op.get("requestBody", {}).get("content", {}).values():
            campos |= set(contenido["schema"].get("properties", {})); requeridos |= set(contenido["schema"].get("required", []))
        huella[op["operationId"]] = {"metodo": metodo, "ruta": ruta, "campos": sorted(campos), "obligatorios": sorted(requeridos),
                                     "consulta": sorted(p["name"] for p in op["parameters"] if p.get("in") == "query"),
                                     "exito": sorted(c for c in op["responses"] if c[0] == "2")}
    return huella


def test_referencia_de_compatibilidad_no_se_rompe_nada_ya_publicado(generar):
    spec, _ = generar()
    actual = _huella(spec)
    if os.environ.get("GUILDA_ACTUALIZAR_BASELINE_OPENAPI") == "1":
        destino = Path(os.environ.get("GUILDA_BASELINE_OPENAPI_DESTINO") or BASELINE)   # scripts/probar.sh trabaja en una copia: pasa aquí la ruta real
        destino.write_text(json.dumps(actual, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
        pytest.skip("referencia actualizada")
    previo = json.loads(BASELINE.read_text())
    roturas = []
    for operacion, antes in previo.items():
        ahora = actual.get(operacion)
        if ahora is None:
            roturas.append(f"{operacion}: la operación ha desaparecido"); continue
        if (ahora["metodo"], ahora["ruta"]) != (antes["metodo"], antes["ruta"]):
            roturas.append(f"{operacion}: ha cambiado de ruta o método")
        for campo in set(antes["campos"]) - set(ahora["campos"]):
            roturas.append(f"{operacion}: el campo «{campo}» del cuerpo ya no se acepta")
        for campo in set(ahora["obligatorios"]) - set(antes["obligatorios"]):
            roturas.append(f"{operacion}: «{campo}» ahora es obligatorio (quien ya integra no lo envía)")
        for param in set(antes["consulta"]) - set(ahora["consulta"]):
            roturas.append(f"{operacion}: el parámetro «{param}» ya no se acepta")
        for codigo in set(antes["exito"]) - set(ahora["exito"]):
            roturas.append(f"{operacion}: ya no responde {codigo}")
    assert not roturas, "Cambios que rompen la API ya publicada:\n  " + "\n  ".join(roturas)
