"""Verificación en dos pasos (TOTP + códigos de recuperación) contra el Kratos real de pruebas: opcional, y quien la activa tiene
que dar el segundo factor en la web y en el login de la API; quien no, entra como siempre."""
import base64
import hashlib
import hmac
import re
import struct
import time

import pytest

from app import db, kratos
from tests.conftest import iniciar_sesion_de_prueba

CLAVE = "Contrasena-larga-123"


def _totp(secreto: str, desplazamiento: int = 0) -> str:
    clave = base64.b32decode(secreto.upper() + "=" * ((8 - len(secreto) % 8) % 8))
    contador = struct.pack(">Q", int(time.time() // 30) + desplazamiento)
    h = hmac.new(clave, contador, hashlib.sha1).digest()
    o = h[-1] & 15
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000).zfill(6)


def _login_api(email: str, codigo: str | None = None):
    """Login de la API de Kratos (sin navegador). Devuelve el token de sesión aal1 o aal2 según se pida."""
    _, f, _ = kratos._peticion(f"{kratos.KRATOS_PUBLIC_URL}/self-service/login/api")
    _, r, _ = kratos._peticion(f"{kratos.KRATOS_PUBLIC_URL}/self-service/login?flow={f['id']}", metodo="POST",
                               cuerpo={"method": "password", "identifier": email, "password": CLAVE})
    token = r["session_token"]
    if codigo is None:
        return token
    cab = {"X-Session-Token": token}
    _, f2, _ = kratos._peticion(f"{kratos.KRATOS_PUBLIC_URL}/self-service/login/api?aal=aal2", cabeceras=cab)
    estado, r2, _ = kratos._peticion(f"{kratos.KRATOS_PUBLIC_URL}/self-service/login?flow={f2['id']}", metodo="POST", cabeceras=cab,
                                     cuerpo={"method": "totp", "totp_code": codigo})
    assert estado == 200, r2
    return r2["session_token"]


def _activar_2fa(email: str) -> tuple[str, list[str]]:
    """Activa la app de autenticación y genera los códigos de recuperación. Devuelve (clave TOTP, códigos)."""
    cab = {"X-Session-Token": _login_api(email)}
    _, flujo, _ = kratos._peticion(f"{kratos.KRATOS_PUBLIC_URL}/self-service/settings/api", cabeceras=cab)
    secreto = next(n["attributes"]["text"]["text"] for n in flujo["ui"]["nodes"] if n["attributes"].get("id") == "totp_secret_key")
    estado, r, _ = kratos._peticion(f"{kratos.KRATOS_PUBLIC_URL}/self-service/settings?flow={flujo['id']}", metodo="POST", cabeceras=cab,
                                    cuerpo={"method": "totp", "totp_code": _totp(secreto)})
    assert estado == 200, r
    _, flujo, _ = kratos._peticion(f"{kratos.KRATOS_PUBLIC_URL}/self-service/settings/api", cabeceras=cab)
    _, r, _ = kratos._peticion(f"{kratos.KRATOS_PUBLIC_URL}/self-service/settings?flow={flujo['id']}", metodo="POST", cabeceras=cab,
                               cuerpo={"method": "lookup_secret", "lookup_secret_regenerate": True})
    codigos = [c["text"] for n in r["ui"]["nodes"] if n["attributes"].get("id") == "lookup_secret_codes"
               for c in n["attributes"]["text"]["context"]["secrets"] if c.get("text")]
    estado, r, _ = kratos._peticion(f"{kratos.KRATOS_PUBLIC_URL}/self-service/settings?flow={flujo['id']}", metodo="POST", cabeceras=cab,
                                    cuerpo={"method": "lookup_secret", "lookup_secret_confirm": True})
    assert estado == 200 and len(codigos) >= 8, (estado, len(codigos))
    return secreto, codigos


def _login_api_app(cliente, email, **extra):
    return cliente.post("/api/v1/auth/login", json={"email": email, "contrasena": CLAVE, **extra})


# --- API --------------------------------------------------------------------------------------------------------------------------

def test_sin_2fa_el_login_de_la_api_no_cambia(cliente):
    iniciar_sesion_de_prueba(cliente, "sin2fa@ejemplo.com", CLAVE)
    r = _login_api_app(cliente, "sin2fa@ejemplo.com")
    assert r.status_code == 200 and r.get_json()["data"]["token"]


def test_con_2fa_la_api_exige_el_codigo_y_acepta_la_app_y_los_codigos_de_recuperacion(cliente):
    iniciar_sesion_de_prueba(cliente, "con2fa@ejemplo.com", CLAVE)
    secreto, recuperacion = _activar_2fa("con2fa@ejemplo.com")
    pedido = _login_api_app(cliente, "con2fa@ejemplo.com")
    assert pedido.status_code == 401 and pedido.get_json()["codigo"] == "requiere_2fa" and pedido.get_json()["campo"] == "codigo_2fa"
    assert "token" not in str(pedido.get_json())                                    # la contraseña sola NO da acceso
    assert _login_api_app(cliente, "con2fa@ejemplo.com", codigo_2fa="000000").get_json()["codigo"] == "credenciales_o_codigo_incorrectos"
    bien = _login_api_app(cliente, "con2fa@ejemplo.com", codigo_2fa=_totp(secreto, 1))
    assert bien.status_code == 200 and bien.get_json()["data"]["token"]
    r1 = _login_api_app(cliente, "con2fa@ejemplo.com", codigo_2fa=recuperacion[0])
    assert r1.status_code == 200
    r2 = _login_api_app(cliente, "con2fa@ejemplo.com", codigo_2fa=recuperacion[0])               # un código de recuperación solo vale una vez
    assert r2.status_code == 401 and r2.get_json()["codigo"] == "credenciales_o_codigo_incorrectos"
    assert _login_api_app(cliente, "con2fa@ejemplo.com", codigo_2fa=recuperacion[1]).status_code == 200


def test_la_contrasena_equivocada_sigue_siendo_401_normal_aunque_haya_2fa(cliente):
    iniciar_sesion_de_prueba(cliente, "mal2fa@ejemplo.com", CLAVE)
    _activar_2fa("mal2fa@ejemplo.com")
    r = cliente.post("/api/v1/auth/login", json={"email": "mal2fa@ejemplo.com", "contrasena": "otra-contrasena-1"})
    assert r.status_code == 401 and r.get_json()["codigo"] != "requiere_2fa"


# --- Web --------------------------------------------------------------------------------------------------------------------------

def test_los_ajustes_de_cuenta_ofrecen_activar_la_app_de_autenticacion(cliente):
    iniciar_sesion_de_prueba(cliente, "ajustes2fa@ejemplo.com", CLAVE)
    html = cliente.get("/ajustes/cuenta", follow_redirects=True).get_data(as_text=True)
    assert "Verificación en dos pasos" in html and 'name="totp_code"' in html and "data:image/png;base64" in html
    assert re.search(r"<code>[A-Z2-7]{16,}</code>", html), "debería mostrar la clave por si no se puede escanear el QR"
    assert "Códigos de recuperación" in html


def test_una_sesion_con_solo_la_contrasena_pide_el_segundo_factor_en_la_web(cliente):
    iniciar_sesion_de_prueba(cliente, "web2fa@ejemplo.com", CLAVE)
    assert "Contraseña y email" in cliente.get("/ajustes/cuenta", follow_redirects=True).get_data(as_text=True)      # sesión normal
    secreto, _ = _activar_2fa("web2fa@ejemplo.com")
    # la sesión del navegador ya no basta: hay que dar el segundo factor
    r = cliente.get("/ajustes/cuenta", follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "Verificación en dos pasos" in html and 'name="totp_code"' in html and 'name="identifier"' not in html
    flow = re.search(r"[?&]flow=([0-9a-f-]+)", r.request.url).group(1)
    csrf = re.search(r'name="csrf_token" value="([^"]*)"', html).group(1)
    mal = cliente.post(f"/.ory/self-service/login?flow={flow}", data={"csrf_token": csrf, "method": "totp", "totp_code": "000000"}, follow_redirects=True)
    assert 'name="totp_code"' in mal.get_data(as_text=True)                  # sigue pidiéndolo
    nuevo_flow = re.search(r"[?&]flow=([0-9a-f-]+)", mal.request.url).group(1)
    csrf = re.search(r'name="csrf_token" value="([^"]*)"', mal.get_data(as_text=True)).group(1)
    bien = cliente.post(f"/.ory/self-service/login?flow={nuevo_flow}", data={"csrf_token": csrf, "method": "totp", "totp_code": _totp(secreto, 1)}, follow_redirects=True)
    assert 'name="totp_code"' not in bien.get_data(as_text=True)
    dentro = cliente.get("/ajustes/cuenta", follow_redirects=True).get_data(as_text=True)
    assert "Contraseña y email" in dentro and 'name="identifier"' not in dentro and "Verificación en dos pasos" not in dentro.split("<h2")[0]


def test_el_login_normal_no_enseña_nada_de_dos_pasos(cliente):
    html = cliente.get("/login", follow_redirects=True).get_data(as_text=True)
    assert 'name="identifier"' in html and "Verificación en dos pasos" not in html


def test_el_puente_de_hydra_pide_el_segundo_factor_en_vez_de_dar_vueltas(cliente, monkeypatch):
    """El conector de ChatGPT/Claude entra por /hydra/login: con 2FA pendiente tiene que acabar en el formulario del código."""
    from app import hydra
    iniciar_sesion_de_prueba(cliente, "hydra2fa@ejemplo.com", CLAVE)
    monkeypatch.setattr(hydra, "obtener_login_request", lambda challenge: {"skip": False})
    normal = cliente.get("/hydra/login?login_challenge=abc")                     # con sesión completa: acepta el login
    assert "login/browser" not in (normal.headers.get("Location") or "")
    _activar_2fa("hydra2fa@ejemplo.com")
    r = cliente.get("/hydra/login?login_challenge=abc")
    assert r.status_code == 302 and "/.ory/self-service/login/browser?" in r.headers["Location"] and "aal=aal2" in r.headers["Location"]
    pagina = cliente.get(r.headers["Location"], follow_redirects=True).get_data(as_text=True)
    assert 'name="totp_code"' in pagina and "Verificación en dos pasos" in pagina


# --- Backoffice: salida para quien pierde el móvil Y los códigos ----------------------------------------------------------------------

def test_el_backoffice_puede_quitar_la_verificacion_a_quien_perdio_el_movil(cliente, tmp_path, monkeypatch):
    from backoffice import auth as bo_auth
    from backoffice.main import create_app
    from tests.test_backoffice_app import CLAVE as CLAVE_BO, entrar, post
    monkeypatch.setattr(bo_auth, "DB_PATH", tmp_path / "backoffice.db")
    monkeypatch.setattr(bo_auth, "SECRET_PATH", tmp_path / "bo_secret.key")
    bo_auth.crear_admin("jorge", CLAVE_BO, "Jorge")
    bo = create_app(testing=True).test_client()
    entrar(bo)
    uid = iniciar_sesion_de_prueba(cliente, "perdido@ejemplo.com", CLAVE)
    secreto, _ = _activar_2fa("perdido@ejemplo.com")
    assert _login_api_app(cliente, "perdido@ejemplo.com").get_json()["codigo"] == "requiere_2fa"
    assert "Verificación en dos pasos" in bo.get(f"/usuarios/{uid}").get_data(as_text=True)
    post(bo, f"/usuarios/{uid}/quitar-2fa")
    assert "Verificación en dos pasos quitada" in bo.get(f"/usuarios/{uid}").get_data(as_text=True)
    assert any(a["accion"] == "usuario.quitar_2fa" for a in bo_auth.listar_auditoria())
    assert _login_api_app(cliente, "perdido@ejemplo.com").status_code == 200       # vuelve a entrar con solo la contraseña
    post(bo, f"/usuarios/{uid}/quitar-2fa")                                         # repetirlo no falla
    assert "no tenía la verificación" in bo.get(f"/usuarios/{uid}").get_data(as_text=True)
