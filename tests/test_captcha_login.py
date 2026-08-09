"""Captcha de respaldo en el login (ver app/rutas_kratos_proxy.py) — en vez
de que CrowdSec banee directamente una IP tras varios fallos de login
seguidos, se le exige resolver un captcha ALTCHA antes de que el siguiente
intento llegue a Kratos de verdad. IPs y usuarios distintos por test para
que un test no contamine al siguiente: el contador de fallos es un
diccionario a nivel de módulo, igual de efímero que la cola de eventos de
app/eventos.py, sin fixture de reset."""
import re

import altcha

from app import captcha, rutas_kratos_proxy as proxy_kratos
from app import kratos


def _flow_y_csrf(cliente, ip: str):
    resp = cliente.get("/login", follow_redirects=True, headers={"X-Forwarded-For": ip})
    html = resp.get_data(as_text=True)
    flow_id = re.search(r"[?&]flow=([0-9a-f-]+)", resp.request.url).group(1)
    csrf = re.search(r'name="csrf_token" value="([^"]*)"', html).group(1)
    return flow_id, csrf


def _intentar_login(cliente, ip: str, flow_id: str, csrf: str, identifier: str, password: str, altcha_payload: str | None = None):
    datos = {"csrf_token": csrf, "identifier": identifier, "password": password, "method": "password"}
    if altcha_payload is not None:
        datos["altcha"] = altcha_payload
    return cliente.post(
        f"/.ory/self-service/login?flow={flow_id}",
        data=datos,
        headers={"X-Forwarded-For": ip},
        follow_redirects=False,
    )


def _resolver_reto() -> str:
    import base64
    import json

    reto = captcha.generar_reto()
    solucion = altcha.solve_challenge_v1(
        challenge=reto["challenge"], salt=reto["salt"], algorithm=reto["algorithm"], max_number=reto["maxnumber"]
    )
    payload = altcha.PayloadV1(
        algorithm=reto["algorithm"], challenge=reto["challenge"], salt=reto["salt"],
        signature=reto["signature"], number=solucion.number,
    )
    return base64.b64encode(json.dumps(payload.__dict__).encode()).decode()


def test_ip_no_requiere_captcha_antes_de_fallar(cliente):
    assert not proxy_kratos.ip_requiere_captcha("198.51.100.1")


def test_tres_fallos_seguidos_activan_el_captcha(cliente):
    ip = "198.51.100.2"
    identity_id = kratos.crear_identidad("captcha-test@ejemplo.com", "ContrasenaSegura#123")
    from app import db
    db.crear_usuario_vinculado_a_kratos("captcha-test@ejemplo.com", identity_id)

    for _ in range(3):
        flow_id, csrf = _flow_y_csrf(cliente, ip)
        _intentar_login(cliente, ip, flow_id, csrf, "captcha-test@ejemplo.com", "incorrecta-a-proposito")

    assert proxy_kratos.ip_requiere_captcha(ip)


def test_intento_sin_captcha_no_llega_a_kratos_una_vez_marcada(cliente):
    ip = "198.51.100.3"
    identity_id = kratos.crear_identidad("captcha-test2@ejemplo.com", "ContrasenaSegura#123")
    from app import db
    db.crear_usuario_vinculado_a_kratos("captcha-test2@ejemplo.com", identity_id)

    for _ in range(3):
        flow_id, csrf = _flow_y_csrf(cliente, ip)
        _intentar_login(cliente, ip, flow_id, csrf, "captcha-test2@ejemplo.com", "incorrecta-a-proposito")
    assert proxy_kratos.ip_requiere_captcha(ip)

    # Contraseña CORRECTA pero sin campo altcha -- debe cortarse antes de
    # Kratos, la propia app redirige de vuelta con captcha_error=1 en vez
    # de que Kratos procese nada.
    flow_id, csrf = _flow_y_csrf(cliente, ip)
    resp = _intentar_login(cliente, ip, flow_id, csrf, "captcha-test2@ejemplo.com", "ContrasenaSegura#123")
    assert resp.status_code in (302, 303)
    assert "captcha_error=1" in resp.headers["Location"]


def test_resolver_el_captcha_permite_entrar_y_resetea_el_contador(cliente):
    ip = "198.51.100.4"
    identity_id = kratos.crear_identidad("captcha-test3@ejemplo.com", "ContrasenaSegura#123")
    from app import db
    db.crear_usuario_vinculado_a_kratos("captcha-test3@ejemplo.com", identity_id)

    for _ in range(3):
        flow_id, csrf = _flow_y_csrf(cliente, ip)
        _intentar_login(cliente, ip, flow_id, csrf, "captcha-test3@ejemplo.com", "incorrecta-a-proposito")
    assert proxy_kratos.ip_requiere_captcha(ip)

    flow_id, csrf = _flow_y_csrf(cliente, ip)
    payload = _resolver_reto()
    resp = _intentar_login(cliente, ip, flow_id, csrf, "captcha-test3@ejemplo.com", "ContrasenaSegura#123", altcha_payload=payload)

    # Login correcto de verdad: Kratos redirige a default_browser_return_url,
    # no de vuelta a /login.
    assert resp.status_code in (302, 303)
    assert "/login" not in resp.headers["Location"]
    assert not proxy_kratos.ip_requiere_captcha(ip)


def test_ip_en_ips_sin_captcha_nunca_se_marca(cliente, monkeypatch):
    ip = "198.51.100.5"
    monkeypatch.setattr(proxy_kratos, "_IPS_SIN_CAPTCHA", {ip})
    identity_id = kratos.crear_identidad("captcha-test4@ejemplo.com", "ContrasenaSegura#123")
    from app import db
    db.crear_usuario_vinculado_a_kratos("captcha-test4@ejemplo.com", identity_id)

    for _ in range(5):
        flow_id, csrf = _flow_y_csrf(cliente, ip)
        _intentar_login(cliente, ip, flow_id, csrf, "captcha-test4@ejemplo.com", "incorrecta-a-proposito")

    assert not proxy_kratos.ip_requiere_captcha(ip)


def test_login_normal_no_se_rompe_por_un_campo_altcha_de_mas(cliente):
    """Kratos rechaza el flujo ENTERO si el POST trae un campo que no
    reconoce entre sus propios nodos (protección contra manipular el
    formulario) -- así que el proxy tiene que quitar `altcha` del cuerpo
    antes de reenviar, incluso en una IP que ni está marcada (el campo
    puede llegar igualmente si el navegador lo manda desde una visita
    anterior). Sin ese cuidado, un login perfectamente normal con
    credenciales correctas se rompía en cuanto el campo altcha viajaba en
    el formulario."""
    ip = "198.51.100.250"
    identity_id = kratos.crear_identidad("control-altcha@ejemplo.com", "ContrasenaSegura#123")
    from app import db
    db.crear_usuario_vinculado_a_kratos("control-altcha@ejemplo.com", identity_id)

    flow_id, csrf = _flow_y_csrf(cliente, ip)
    resp = _intentar_login(cliente, ip, flow_id, csrf, "control-altcha@ejemplo.com", "ContrasenaSegura#123", altcha_payload="campo-extra-basura")
    assert resp.status_code in (302, 303)
    assert "/login" not in resp.headers["Location"]
