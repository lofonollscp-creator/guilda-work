"""Herramientas conectadas que responden de verdad (app/estado_herramientas.py): catálogo web, app móvil, asistente de IA y MCP solo enseñan y ofrecen lo que funciona."""
import http.server
import threading

import pytest

import mcp_tools  # noqa: F401
from app import db, estado_herramientas as eh, herramientas, ia_herramientas as ih
from tests.conftest import iniciar_sesion_de_prueba


@pytest.fixture
def caidas(monkeypatch):
    """Hace que no respondan las herramientas indicadas (por id); el resto sí."""
    por_url = {h["url"]: h["id"] for h in herramientas.HERRAMIENTAS}
    muertas: set[str] = set()
    monkeypatch.setattr(eh, "CONSIDERAR_MARCA_ESTATICA", True)                                         # aquí sí cuenta lo que el catálogo marca como «no se despliega»
    monkeypatch.setattr(eh, "_sondear", lambda url: por_url.get(url) not in muertas)
    eh.reiniciar_cache()
    return muertas


def test_sondeo_real(monkeypatch):
    import importlib
    real = importlib.reload(eh)._sondear                                                          # la función de verdad, sin el parche del conftest
    class Manejador(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            codigo = {"/ok": 200, "/login": 401, "/falta": 404, "/mover": 302}.get(self.path, 500)
            self.send_response(codigo)
            if codigo == 302:
                self.send_header("Location", "http://127.0.0.1:9/fuera")
            self.end_headers()

        def log_message(self, *a):
            pass
    servidor = http.server.HTTPServer(("127.0.0.1", 0), Manejador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{servidor.server_port}"
        assert all(real(base + ruta) for ruta in ("/ok", "/login", "/falta", "/mover", "/error"))      # cualquier respuesta HTTP = viva (sin seguir la redirección)
    finally:
        servidor.shutdown()
    assert real("http://127.0.0.1:1/") is False and real("no-es-una-url") is False                   # puerto cerrado / basura = no responde


def test_estados_marca_caidas_y_las_no_desplegadas(caidas):
    caidas.update({"outline", "n8n"})
    e = eh.estados(forzar=True)
    assert e["outline"] is False and e["n8n"] is False and e["drive"] is True
    assert e["crm"] is False and e["portainer"] is False                                              # marcadas `disponible: False`: ni se comprueban
    assert eh.disponible("drive") and not eh.disponible("outline") and eh.disponible("id-que-no-existe")


def test_la_comprobacion_se_guarda_un_rato(monkeypatch):
    llamadas = []
    monkeypatch.setattr(eh, "_sondear", lambda url: llamadas.append(url) or True)
    eh.reiniciar_cache()
    eh.estados()
    n = len(llamadas)
    eh.estados()
    assert n > 0 and len(llamadas) == n                                                               # la segunda vez sale de la memoria
    eh.estados(forzar=True)
    assert len(llamadas) == 2 * n


def test_cada_herramienta_del_asistente_apunta_a_un_servicio_del_catalogo():
    ids = {h["id"] for h in herramientas.HERRAMIENTAS}
    nombres = {t.__name__ for t in mcp_tools.TOOLS}
    dependientes = {n: eh.servicio_de(n) for n in nombres if eh.servicio_de(n)}
    assert dependientes and set(dependientes.values()) <= ids
    assert eh.servicio_de("crm_listar_leads") == "crm" and eh.servicio_de("listar_tablas_hojas") == "hojas" and eh.servicio_de("citas_crear_reserva") == "citas"
    assert eh.servicio_de("listar_tareas") is None and eh.servicio_de("crear_nota") is None and eh.servicio_de("listar_reglas_automatizacion") is None


def test_el_asistente_no_ofrece_ni_ejecuta_herramientas_de_un_servicio_caido(caidas):
    caidas.add("drive")
    eh.reiniciar_cache()
    nombres = {t["function"]["name"] for t in ih.herramientas_para()}
    assert "drive_listar_archivos" not in nombres and "listar_tareas" in nombres and "crear_firma" not in nombres
    u = db.crear_usuario_vinculado_a_kratos("estado-ia@ejemplo.com", "k-estado-ia")
    with pytest.raises(ih.ErrorHerramientaIA, match="no está disponible ahora mismo"):
        ih.ejecutar(u, "drive_listar_archivos", {})
    caidas.clear()
    eh.reiniciar_cache()
    assert "drive_listar_archivos" in {t["function"]["name"] for t in ih.herramientas_para()}


def test_los_errores_de_un_servicio_llegan_al_chat_como_error_de_herramienta(monkeypatch):
    from app import nextcloud
    u = db.crear_usuario_vinculado_a_kratos("estado-ia2@ejemplo.com", "k-estado-ia2")

    def roto(**k):
        raise nextcloud.ErrorNextcloud("Nextcloud no contesta")
    monkeypatch.setattr(mcp_tools, "drive_listar_archivos", roto)
    with pytest.raises(ih.ErrorHerramientaIA, match="Nextcloud no contesta"):
        ih.ejecutar(u, "drive_listar_archivos", {})


def test_el_mcp_responde_con_un_mensaje_claro_si_el_servicio_no_responde(caidas):
    caidas.add("crm")
    eh.reiniciar_cache()
    with pytest.raises(ValueError, match="CRM"):
        eh.exigir_servicio("crm_listar_leads")
    eh.exigir_servicio("listar_tareas")                                                               # sin servicio: nunca se bloquea


def test_la_web_y_la_app_movil_solo_enseñan_lo_que_responde(cliente, caidas):
    uid = iniciar_sesion_de_prueba(cliente, "estado-web@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho herramientas vivas")
    db.asignar_tenant(uid, t)
    caidas.add("n8n")
    eh.reiniciar_cache()
    html = cliente.get("/herramientas").get_data(as_text=True)
    assert "Outline" in html and "n8n" not in html.lower().split("tools-page")[1]                       # la caída no se ve en la rejilla
    assert "no responden ahora mismo" not in html                                                      # y quien no es dirección no ve el aviso
    db.asignar_supervisor_tenant(uid, True)
    html = cliente.get("/herramientas").get_data(as_text=True)
    assert "no responden ahora mismo" in html and "n8n" in html.split("no responden ahora mismo")[1][:200]


def test_el_panel_de_salud_anota_cuales_no_responden(caidas):
    caidas.add("outline")
    eh.reiniciar_cache()
    eh.estados(forzar=True)
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM latidos WHERE nombre = 'herramientas_conectadas'").fetchone()
    finally:
        conn.close()
    assert f is not None and "Outline" in f["detalle"] and f["ultimo_error"]


def test_la_api_de_la_app_movil_tambien_filtra(cliente, caidas):
    from tests.test_api_tareas import _usuario
    t = db.crear_tenant("Despacho herramientas api")
    h, uid = _usuario(cliente, "estado-api@ejemplo.com", t)
    caidas.add("n8n")
    eh.reiniciar_cache()
    datos = {x["id"]: x for x in cliente.get("/api/v1/herramientas", headers=h).get_json()["data"]}
    assert datos["outline"]["disponible"] is True and datos["n8n"]["disponible"] is False and datos["crm"]["disponible"] is False      # la app móvil las enseña en gris
    assert "chat" not in datos


def test_lo_marcado_como_no_se_despliega_bloquea_sus_herramientas_aunque_el_puerto_respondiera(caidas):
    assert eh.disponible("crm") is False and eh.disponible("hojas") is False and eh.disponible("outline") is True
    with pytest.raises(ValueError, match="CRM"):
        eh.exigir_servicio("crm_listar_leads")
    nombres = {t["function"]["name"] for t in ih.herramientas_para()}
    assert "crm_listar_leads" not in nombres and "listar_tablas_hojas" not in nombres
