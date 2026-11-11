"""Pantalla de ajustes de IA con proveedores propios (P3): qué ve y qué puede cambiar cada persona."""
import pytest

from app import db, ia_asistente as a, ia_claves, ia_despacho as dz, ia_proveedores as pv
from tests.conftest import iniciar_sesion_de_prueba


@pytest.fixture
def equipo(cliente):
    t = db.crear_tenant("IA Ajustes")
    d = iniciar_sesion_de_prueba(cliente, "dir-aj@ejemplo.com", "contrasena123")
    db.asignar_tenant(d, t)
    db.asignar_supervisor_tenant(d, True)
    return cliente, t, d


def _como_empleado(cliente, t, email="emp-aj@ejemplo.com"):
    from app.main import app as flask_app
    web = flask_app.test_client()
    u = iniciar_sesion_de_prueba(web, email, "contrasena123")
    db.asignar_tenant(u, t)
    return web, u


def test_la_pantalla_enseña_los_proveedores_sin_claves(equipo):
    cliente, t, d = equipo
    dz.guardar(t, "openai", activo=True, modelo_asistente="gpt-4o-mini", claves_nuevas=["sk-secreta-1234567890"], por=d)
    html = cliente.get("/ia/ajustes").get_data(as_text=True)
    for nombre in ("OpenRouter", "OpenAI (ChatGPT)", "Anthropic (Claude)", "Google Gemini", "Mistral", "Ollama (local)"):
        assert nombre in html
    assert "sk-…7890" in html and "secreta-1234567890" not in html
    assert "Normas del despacho" in html and "Probar clave y modelo" in html


def test_la_persona_elige_su_proveedor_y_guarda_sus_claves_por_proveedor(equipo):
    cliente, t, d = equipo
    r = cliente.post("/ia/ajustes", data={"proveedor": "anthropic", "modelo": "", "modelo_personalizado": "claude-sonnet-5-5", "api_keys": "sk-ant-personal-123456\nsk-ant-segunda-1234567"})
    assert r.status_code == 302 and "error" not in r.headers["Location"]
    assert db.obtener_preferencias_ia(d)["proveedor_ia"] == "anthropic" and db.obtener_preferencias_ia(d)["modelo"] == "claude-sonnet-5-5"
    assert ia_claves.de_usuario("anthropic", d) == ["sk-ant-personal-123456", "sk-ant-segunda-1234567"]
    assert a.obtener_api_keys(d) == []                                                           # las de OpenRouter no se tocan
    assert a.candidatos(d, "facturas")[0]["proveedor"] == "anthropic"
    cliente.post("/ia/ajustes", data={"proveedor": "anthropic", "modelo_personalizado": "claude-sonnet-5-5", "borrar_api_keys": "on"})
    assert ia_claves.de_usuario("anthropic", d) == []
    assert "Proveedor de IA no válido" in cliente.post("/ia/ajustes", data={"proveedor": "inventado"}, follow_redirects=True).get_data(as_text=True)


def test_openrouter_sigue_siendo_el_predeterminado_y_guarda_como_siempre(equipo):
    cliente, t, d = equipo
    assert db.obtener_preferencias_ia(d)["proveedor_ia"] == "openrouter"
    cliente.post("/ia/ajustes", data={"modelo": "meta-llama/llama-3.1-70b-instruct:free", "api_keys": "sk-or-clave-1234567"})
    assert a.obtener_api_keys(d) == ["sk-or-clave-1234567"] and db.obtener_preferencias_ia(d)["modelo"] == "meta-llama/llama-3.1-70b-instruct:free"


def test_solo_la_direccion_cambia_los_proveedores_del_despacho(equipo):
    cliente, t, d = equipo
    web, u = _como_empleado(cliente, t)
    for ruta, datos in (("/ia/ajustes/despacho/openai", {"activo": "on", "modelo_asistente": "gpt-4o", "claves": "sk-intruso-1234567890"}), ("/ia/ajustes/despacho/normas", {"solo_ue": "on"}),
                        ("/ia/ajustes/despacho/openai/mover/arriba", {})):
        assert web.post(ruta, data=datos).status_code == 403
    assert ia_claves.de_despacho("openai", t) == [] and dz.config(t)["solo_ue"] is False
    assert "IA de tu despacho" in web.get("/ia/ajustes").get_data(as_text=True) and "Normas del despacho" not in web.get("/ia/ajustes").get_data(as_text=True)
    r = cliente.post("/ia/ajustes/despacho/openai", data={"activo": "on", "modelo_asistente": "gpt-4o-mini", "claves": "sk-direccion-1234567890"})
    assert r.status_code == 302 and "error" not in r.headers["Location"]
    assert [c["proveedor"] for c in dz.candidatos(t, "asistente")] == ["openai"]
    assert cliente.post("/ia/ajustes/despacho/inventado", data={}).status_code == 404


def test_errores_de_validacion_vuelven_a_la_pantalla_con_mensaje(equipo):
    cliente, t, d = equipo
    html = cliente.post("/ia/ajustes/despacho/openai", data={"activo": "on", "modelo_asistente": "gpt-4o"}, follow_redirects=True).get_data(as_text=True)
    assert "añade antes su clave" in html.lower()
    html = cliente.post("/ia/ajustes/despacho/normas", data={"facturas_modo": "auto", "umbral_confianza": "5"}, follow_redirects=True).get_data(as_text=True)
    assert "umbral" in html.lower()


def test_las_normas_se_guardan_y_aplican(equipo):
    cliente, t, d = equipo
    cliente.post("/ia/ajustes/despacho/normas", data={"solo_ue": "on", "facturas_modo": "auto", "umbral_confianza": "95"})
    assert dz.config(t) == {"solo_ue": True, "claves_personales": False, "facturas_modo": "auto", "umbral_confianza": 95, "lectura_texto": False, "separar_pdf": False, "ocr_local": "respaldo", "segunda_lectura": False, "voz": ""}
    r = cliente.post("/ia/ajustes", data={"proveedor": "openai", "modelo_personalizado": "gpt-4o"}, follow_redirects=True)
    assert "solo admite proveedores de la UE" in r.get_data(as_text=True)
    r = cliente.post("/ia/ajustes", data={"proveedor": "openrouter", "modelo_personalizado": "x/y"}, follow_redirects=True)
    assert "solo admite proveedores de la UE" in r.get_data(as_text=True)                         # OpenRouter reparte las consultas por todo el mundo: con «solo UE» tampoco vale
    cliente.post("/ia/ajustes/despacho/normas", data={"facturas_modo": "compartida", "umbral_confianza": "90"})      # sin «solo UE» y sin claves personales
    r = cliente.post("/ia/ajustes", data={"proveedor": "openrouter", "api_keys": "sk-or-1234567890"}, follow_redirects=True)
    assert "no permite claves personales" in r.get_data(as_text=True)


def test_probar_usa_la_clave_escrita_o_la_guardada_y_no_filtra_nada(equipo, monkeypatch):
    cliente, t, d = equipo
    llamadas = []
    monkeypatch.setattr(pv, "probar", lambda proveedor, modelo, clave, url=None: llamadas.append((proveedor, modelo, clave, url)) or "")
    r = cliente.post("/ia/ajustes/probar", data={"proveedor": "openai", "modelo": "gpt-4o-mini", "clave": "sk-escrita-1234567890", "ambito": "usuario"}).get_json()
    assert r["ok"] and llamadas[-1] == ("openai", "gpt-4o-mini", "sk-escrita-1234567890", None)
    ia_claves.guardar_de_usuario("openai", d, ["sk-guardada-1234567890"])
    cliente.post("/ia/ajustes/probar", data={"proveedor": "openai", "modelo": "gpt-4o-mini", "ambito": "usuario"})
    assert llamadas[-1][2] == "sk-guardada-1234567890"
    assert cliente.post("/ia/ajustes/probar", data={"proveedor": "anthropic", "modelo": "x"}).get_json() == {"ok": False, "error": "No hay ninguna clave que probar."}
    assert cliente.post("/ia/ajustes/probar", data={"proveedor": "anthropic", "modelo": "", "clave": "sk-ant-1234567890"}).get_json()["error"] == "Indica un modelo para probar."
    monkeypatch.setattr(pv, "probar", lambda *a, **k: "La clave no tiene saldo o crédito.")
    assert cliente.post("/ia/ajustes/probar", data={"proveedor": "openai", "modelo": "gpt-4o", "clave": "sk-escrita-1234567890"}).get_json() == {"ok": False, "error": "La clave no tiene saldo o crédito.", "mensaje": ""}
    web, u = _como_empleado(cliente, t)
    assert web.post("/ia/ajustes/probar", data={"proveedor": "openai", "modelo": "gpt-4o", "ambito": "despacho"}).status_code == 403


def test_listar_modelos_de_un_proveedor(equipo, monkeypatch):
    cliente, t, d = equipo
    r = cliente.get("/ia/modelos?proveedor=openai").get_json()
    assert r["modelos"] == [] and "clave" in r["error"] and "gpt-4o-mini" in r["sugeridos"]
    ia_claves.guardar_de_usuario("openai", d, ["sk-guardada-1234567890"])
    monkeypatch.setattr(pv, "listar_modelos", lambda proveedor, clave, url=None, timeout=15: ["gpt-4o", "gpt-4o-mini"])
    assert cliente.get("/ia/modelos?proveedor=openai").get_json()["modelos"] == ["gpt-4o", "gpt-4o-mini"]
    assert cliente.get("/ia/modelos?proveedor=inventado").status_code == 404


def test_el_modo_de_ocr_local_se_elige_en_las_normas_y_se_rechaza_lo_invalido(equipo):
    cliente, t, d = equipo
    html = cliente.get("/ia/ajustes").get_data(as_text=True)
    assert 'name="ocr_local"' in html and "Nada sale del servidor" in html
    cliente.post("/ia/ajustes/despacho/normas", data={"facturas_modo": "compartida", "umbral_confianza": "90", "ocr_local": "solo_local"})
    assert dz.config(t)["ocr_local"] == "solo_local"
    html = cliente.post("/ia/ajustes/despacho/normas", data={"facturas_modo": "compartida", "umbral_confianza": "90", "ocr_local": "siempre"}, follow_redirects=True).get_data(as_text=True)
    assert "OCR" in html and dz.config(t)["ocr_local"] == "solo_local"
