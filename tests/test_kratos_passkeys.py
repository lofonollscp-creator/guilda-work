"""Passkeys del equipo (W14), sin Kratos ni navegador: qué scripts se aceptan de un flujo, que la página de acceso y la de ajustes pintan lo necesario, y que la configuración real las declara."""
import json
import re
from pathlib import Path

from app import kratos

RAIZ = Path(__file__).resolve().parent.parent


def _script(src):
    return {"group": "webauthn", "type": "script", "attributes": {"node_type": "script", "src": src, "id": "webauthn_script"}}


def test_solo_se_aceptan_los_scripts_de_ory_y_siempre_a_traves_del_proxy():
    nodos = [_script(f"{kratos.KRATOS_PUBLIC_URL}/.well-known/ory/webauthn.js"), _script(f"{kratos.KRATOS_PUBLIC_URL}/.well-known/ory/webauthn.js"),
             _script("https://evil.example/x.js"), _script(f"{kratos.KRATOS_PUBLIC_URL}/otra/cosa.js"), _script(f"{kratos.KRATOS_PUBLIC_URL}/.well-known/ory/../../x.js"),
             {"group": "default", "type": "input", "attributes": {"node_type": "input", "name": "csrf_token"}}, {"attributes": {"node_type": "script", "src": 5}}]
    assert kratos.scripts_del_flujo(nodos) == ["/.ory/.well-known/ory/webauthn.js"]                      # una vez, del propio origen y nada más
    assert kratos.scripts_del_flujo([]) == []


def _flujo_login(con_passkey=True):
    nodos = [{"group": "default", "type": "input", "attributes": {"node_type": "input", "name": "csrf_token", "type": "hidden", "value": "tok"}, "messages": []},
             {"group": "default", "type": "input", "attributes": {"node_type": "input", "name": "identifier", "type": "text", "value": ""}, "messages": []},
             {"group": "password", "type": "input", "attributes": {"node_type": "input", "name": "password", "type": "password"}, "messages": []},
             {"group": "password", "type": "input", "attributes": {"node_type": "input", "name": "method", "type": "submit", "value": "password"}, "messages": []}]
    if con_passkey:
        nodos += [_script(f"{kratos.KRATOS_PUBLIC_URL}/.well-known/ory/webauthn.js"),
                  {"group": "passkey", "type": "input", "attributes": {"node_type": "input", "name": "passkey_login_trigger", "type": "button", "onclickTrigger": "oryPasskeyLogin"}, "messages": []},
                  {"group": "passkey", "type": "input", "attributes": {"node_type": "input", "name": "passkey_login", "type": "hidden", "value": ""}, "messages": []},
                  {"group": "passkey", "type": "input", "attributes": {"node_type": "input", "name": "passkey_challenge", "type": "hidden", "value": '{"publicKey":{"challenge":"abc"}}'}, "messages": []}]
    return nodos


def _pintar(plantilla, **contexto):
    from flask import g, render_template
    from app.main import app
    with app.test_request_context("/"):
        for k in ("usuario_id", "tenant_id", "es_admin", "supervisor_tenant", "gestor_fichajes"):                 # lo que fija el before_request en una petición de verdad (aquí, sin sesión)
            setattr(g, k, None)
        return render_template(plantilla, **contexto)


def test_la_pagina_de_acceso_ofrece_la_passkey_en_un_formulario_aparte(cliente):
    nodos = _flujo_login()
    html = _pintar("login.html", nodos=nodos, accion="/.ory/self-service/login?flow=1", mensajes=[], scripts=kratos.scripts_del_flujo(nodos), requiere_captcha=False, captcha_fallido=False, idioma_actual="es")
    assert "data-passkey-login" in html and "Entrar con passkey" in html
    form = re.search(r'<form id="form-passkey".*?</form>', html, re.S).group(0)
    assert 'name="method" value="passkey"' in form and 'name="passkey_login"' in form and 'name="csrf_token" value="tok"' in form and "challenge" in form
    principal = html.split('<form id="form-passkey"')[0]
    assert 'name="passkey_login"' not in principal and 'name="passkey_challenge"' not in principal           # nada de passkey dentro del formulario de la contraseña
    assert '<script src="/.ory/.well-known/ory/webauthn.js" defer></script>' in html and "kratos_passkeys.js" in html


def test_sin_passkeys_en_el_flujo_la_pagina_de_acceso_es_la_de_siempre(cliente):
    html = _pintar("login.html", nodos=_flujo_login(False), accion="/.ory/self-service/login?flow=1", mensajes=[], scripts=[], requiere_captcha=False, captcha_fallido=False, idioma_actual="es")
    assert "data-passkey-login" not in html and "form-passkey" not in html and "kratos_passkeys.js" not in html and "Entrar" in html


def test_los_ajustes_pintan_las_passkeys_y_sus_campos_solo_en_su_formulario(cliente):
    nodos = [{"group": "default", "type": "input", "attributes": {"node_type": "input", "name": "csrf_token", "type": "hidden", "value": "tok"}, "messages": []},
             {"group": "password", "type": "input", "attributes": {"node_type": "input", "name": "password", "type": "password"}, "meta": {"label": {"text": "Contraseña"}}, "messages": []},
             {"group": "password", "type": "input", "attributes": {"node_type": "input", "name": "method", "type": "submit", "value": "password"}, "meta": {"label": {"text": "Guardar"}}, "messages": []},
             _script(f"{kratos.KRATOS_PUBLIC_URL}/.well-known/ory/webauthn.js"),
             {"group": "passkey", "type": "input", "attributes": {"node_type": "input", "name": "passkey_register_trigger", "type": "button", "onclickTrigger": "oryPasskeySettingsRegistration"}, "meta": {"label": {"text": "Add passkey"}}, "messages": []},
             {"group": "passkey", "type": "input", "attributes": {"node_type": "input", "name": "passkey_settings_register", "type": "hidden", "value": ""}, "messages": []},
             {"group": "passkey", "type": "input", "attributes": {"node_type": "input", "name": "passkey_create_data", "type": "hidden", "value": "{}"}, "messages": []}]
    html = _pintar("ajustes_cuenta.html", nodos=nodos, accion="/.ory/self-service/settings?flow=1", mensajes=[], scripts=kratos.scripts_del_flujo(nodos))
    assert "Passkeys: entrar con huella, cara o PIN" in html and "data-passkey-registrar" in html and 'src="/.ory/.well-known/ory/webauthn.js"' in html
    formularios = re.findall(r"<form .*?</form>", html, re.S)
    con_campos = [f for f in formularios if 'name="passkey_create_data"' in f]
    assert len(con_campos) == 1 and 'data-passkey-registrar' in con_campos[0] and 'name="passkey_settings_register"' in con_campos[0]     # webauthn.js envía el formulario que los contiene: tiene que ser el suyo
    assert not [f for f in formularios if 'name="password"' in f and "passkey_create_data" in f]
    assert all('name="csrf_token"' in f for f in formularios if 'action="/.ory/' in f)                                                       # el csrf sigue en cada formulario


def test_la_configuracion_real_declara_las_passkeys_del_dominio_de_la_app():
    yml = (RAIZ / "deploy" / "kratos" / "kratos.yml").read_text(encoding="utf-8")
    assert re.search(r"passkey:\s+enabled: true", yml) and "id: app.guildawork.com" in yml and "https://app.guildawork.com" in yml
    esquema = json.loads((RAIZ / "deploy" / "kratos" / "identity.schema.json").read_text(encoding="utf-8"))
    cred = esquema["properties"]["traits"]["properties"]["email"]["ory.sh/kratos"]["credentials"]
    assert cred["passkey"] == {"display_name": True} and cred["password"] == {"identifier": True}
