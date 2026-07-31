"""Tests del cliente de Stalwart (app/stalwart.py) — se mockea
stalwart._jmap, sin un Stalwart de verdad.

El diseño en sí (namespace JMAP `x:`, credenciales secundarias como
objetos JMAP de nivel superior con accountId de la cuenta destino,
aislamiento real por accountId con 403 "forbidden" del servidor) se
verificó en vivo contra un contenedor real durante el desarrollo — ver
el docstring del propio módulo. Aquí solo se comprueba que
app/stalwart.py ORQUESTA las llamadas correctas."""
import pytest

from app import stalwart as s


def _mock_admin_ok(monkeypatch):
    monkeypatch.setattr(s, "STALWART_ADMIN_USER", "admin@guilda-test.local")
    monkeypatch.setattr(s, "STALWART_ADMIN_PASSWORD", "secreto")


def _respuesta(nombre: str, cuerpo: dict, id_llamada: str = "0") -> dict:
    return {"methodResponses": [[nombre, cuerpo, id_llamada]]}


def _respuesta_multi(*pasos: tuple[str, dict, str]) -> dict:
    return {"methodResponses": [[nombre, cuerpo, id_] for nombre, cuerpo, id_ in pasos]}


# --- aprovisionar_tenant ----------------------------------------------------

def test_aprovisionar_tenant_completo_ok(monkeypatch):
    _mock_admin_ok(monkeypatch)
    llamadas = []

    def fake_jmap(method_calls, *, cabeceras):
        metodo = method_calls[0][0]
        llamadas.append((metodo, method_calls))
        if metodo == "x:Tenant/query":
            return _respuesta_multi(
                ("x:Tenant/query", {"ids": []}, "0"),
                ("x:Tenant/get", {"list": []}, "1"),
            )
        if metodo == "x:Tenant/set":
            return _respuesta("x:Tenant/set", {"created": {"t1": {"id": "b"}}})
        if metodo == "x:Domain/query":
            return _respuesta_multi(
                ("x:Domain/query", {"ids": []}, "0"),
                ("x:Domain/get", {"list": []}, "1"),
            )
        if metodo == "x:Domain/set":
            return _respuesta("x:Domain/set", {"created": {"d1": {"id": "c"}}})
        if metodo == "x:Account/set":
            return _respuesta("x:Account/set", {"created": {"u1": {"id": "d"}}})
        if metodo == "x:ApiKey/query":
            return _respuesta("x:ApiKey/query", {"ids": []})
        if metodo == "x:ApiKey/set":
            return _respuesta("x:ApiKey/set", {"created": {"k1": {"id": "b", "secret": "API_abc123"}}})
        raise AssertionError(f"llamada inesperada: {metodo}")

    monkeypatch.setattr(s, "_jmap", fake_jmap)
    resultado = s.aprovisionar_tenant(7, "Lueira", "clientea.com")

    assert resultado == {
        "stalwart_tenant_id": "b", "domain_id": "c", "domain_name": "clientea.com",
        "account_id": "d", "api_key": "API_abc123",
    }
    # el Domain se crea con el dominio propio real del cliente, no derivado
    cuerpo_domain = next(mc for metodo, mc in llamadas if metodo == "x:Domain/set")[0][1]
    assert cuerpo_domain["create"]["d1"]["name"] == "clientea.com"
    assert cuerpo_domain["create"]["d1"]["memberTenantId"] == "b"
    # la Account se crea SIN credenciales (el servidor las rechaza si van ahí)
    cuerpo_account = next(mc for metodo, mc in llamadas if metodo == "x:Account/set")[0][1]
    assert "credentials" not in cuerpo_account["create"]["u1"]
    # el ApiKey se crea con accountId = la Account destino, no el admin
    cuerpo_apikey = next(mc for metodo, mc in llamadas if metodo == "x:ApiKey/set")[0][1]
    assert cuerpo_apikey["accountId"] == "d"
    assert "allowedIps" not in cuerpo_apikey["create"]["k1"]


def test_aprovisionar_tenant_idempotente_reutiliza_tenant_y_domain(monkeypatch):
    _mock_admin_ok(monkeypatch)

    def fake_jmap(method_calls, *, cabeceras):
        metodo = method_calls[0][0]
        if metodo == "x:Tenant/query":
            return _respuesta_multi(
                ("x:Tenant/query", {"ids": ["b"]}, "0"),
                ("x:Tenant/get", {"list": [{"id": "b", "name": "Lueira"}]}, "1"),
            )
        if metodo == "x:Domain/query":
            return _respuesta_multi(
                ("x:Domain/query", {"ids": ["c"]}, "0"),
                ("x:Domain/get", {"list": [{"id": "c", "name": "clientea.com"}]}, "1"),
            )
        if metodo == "x:Account/set":
            return _respuesta("x:Account/set", {"created": {"u1": {"id": "d"}}})
        if metodo == "x:ApiKey/query":
            return _respuesta("x:ApiKey/query", {"ids": []})
        if metodo == "x:ApiKey/set":
            return _respuesta("x:ApiKey/set", {"created": {"k1": {"id": "b", "secret": "API_xyz"}}})
        raise AssertionError(f"llamada inesperada: {metodo}")

    monkeypatch.setattr(s, "_jmap", fake_jmap)
    resultado = s.aprovisionar_tenant(7, "Lueira", "clientea.com")

    assert resultado["stalwart_tenant_id"] == "b"
    assert resultado["domain_id"] == "c"


def test_aprovisionar_tenant_borra_apikeys_previos_de_un_intento_anterior(monkeypatch):
    _mock_admin_ok(monkeypatch)
    llamadas = []

    def fake_jmap(method_calls, *, cabeceras):
        metodo = method_calls[0][0]
        llamadas.append((metodo, method_calls))
        if metodo == "x:Tenant/query":
            return _respuesta_multi(
                ("x:Tenant/query", {"ids": ["b"]}, "0"),
                ("x:Tenant/get", {"list": [{"id": "b", "name": "Lueira"}]}, "1"),
            )
        if metodo == "x:Domain/query":
            return _respuesta_multi(
                ("x:Domain/query", {"ids": ["c"]}, "0"),
                ("x:Domain/get", {"list": [{"id": "c", "name": "clientea.com"}]}, "1"),
            )
        if metodo == "x:Account/set":
            return _respuesta("x:Account/set", {"created": {"u1": {"id": "d"}}})
        if metodo == "x:ApiKey/query":
            return _respuesta("x:ApiKey/query", {"ids": ["viejo1", "viejo2"]})
        if metodo == "x:ApiKey/set" and "destroy" in method_calls[0][1]:
            return _respuesta("x:ApiKey/set", {"destroyed": ["viejo1", "viejo2"]})
        if metodo == "x:ApiKey/set":
            return _respuesta("x:ApiKey/set", {"created": {"k1": {"id": "b", "secret": "API_nuevo"}}})
        raise AssertionError(f"llamada inesperada: {metodo}")

    monkeypatch.setattr(s, "_jmap", fake_jmap)
    resultado = s.aprovisionar_tenant(7, "Lueira", "clientea.com")

    assert resultado["api_key"] == "API_nuevo"
    destroy_calls = [mc for metodo, mc in llamadas if metodo == "x:ApiKey/set" and "destroy" in mc[0][1]]
    assert len(destroy_calls) == 1
    assert destroy_calls[0][0][1]["destroy"] == ["viejo1", "viejo2"]


def test_aprovisionar_tenant_falla_si_stalwart_no_configurado(monkeypatch):
    monkeypatch.setattr(s, "STALWART_ADMIN_USER", None)
    monkeypatch.setattr(s, "STALWART_ADMIN_PASSWORD", None)
    with pytest.raises(s.ErrorStalwart):
        s.aprovisionar_tenant(7, "Lueira", "clientea.com")


def test_aprovisionar_tenant_propaga_error_si_account_set_falla(monkeypatch):
    _mock_admin_ok(monkeypatch)

    def fake_jmap(method_calls, *, cabeceras):
        metodo = method_calls[0][0]
        if metodo == "x:Tenant/query":
            return _respuesta_multi(
                ("x:Tenant/query", {"ids": []}, "0"),
                ("x:Tenant/get", {"list": []}, "1"),
            )
        if metodo == "x:Tenant/set":
            return _respuesta("x:Tenant/set", {"created": {"t1": {"id": "b"}}})
        if metodo == "x:Domain/query":
            return _respuesta_multi(
                ("x:Domain/query", {"ids": []}, "0"),
                ("x:Domain/get", {"list": []}, "1"),
            )
        if metodo == "x:Domain/set":
            return _respuesta("x:Domain/set", {"created": {"d1": {"id": "c"}}})
        if metodo == "x:Account/set":
            return _respuesta("x:Account/set", {"notCreated": {"u1": {"type": "invalidProperties"}}})
        raise AssertionError(f"llamada inesperada: {metodo}")

    monkeypatch.setattr(s, "_jmap", fake_jmap)
    with pytest.raises(s.ErrorStalwart):
        s.aprovisionar_tenant(7, "Lueira", "clientea.com")


# --- desaprovisionar_tenant -------------------------------------------------

def test_desaprovisionar_tenant_no_hace_nada_si_no_configurado(monkeypatch):
    monkeypatch.setattr(s, "STALWART_ADMIN_USER", None)
    monkeypatch.setattr(s, "STALWART_ADMIN_PASSWORD", None)
    llamado = []
    monkeypatch.setattr(s, "_jmap", lambda *a, **k: llamado.append(1))
    s.desaprovisionar_tenant("b", "c", "d")
    assert llamado == []


def test_desaprovisionar_tenant_borra_account_domain_tenant(monkeypatch):
    _mock_admin_ok(monkeypatch)
    llamadas = []
    monkeypatch.setattr(s, "_jmap", lambda method_calls, *, cabeceras: llamadas.append(method_calls[0][0]) or {"methodResponses": []})

    s.desaprovisionar_tenant("b", "c", "d")

    assert llamadas == ["x:Account/set", "x:Domain/set", "x:Tenant/set"]


def test_desaprovisionar_tenant_no_falla_con_ids_ausentes(monkeypatch):
    _mock_admin_ok(monkeypatch)
    llamadas = []
    monkeypatch.setattr(s, "_jmap", lambda method_calls, *, cabeceras: llamadas.append(method_calls[0][0]) or {"methodResponses": []})

    s.desaprovisionar_tenant(None, None, None)

    assert llamadas == []


# --- API de negocio (listar_mensajes / leer_mensaje / enviar_mensaje) ------

def test_listar_mensajes_sin_api_key_devuelve_lista_vacia():
    assert s.listar_mensajes("") == []


def test_listar_mensajes_delega_con_accountid_resuelto(monkeypatch):
    monkeypatch.setattr(s, "_account_id_propio", lambda api_key: "d")
    capturado = {}

    def fake_jmap(method_calls, *, cabeceras):
        capturado["method_calls"] = method_calls
        capturado["cabeceras"] = cabeceras
        return {"methodResponses": [["Email/get", {"list": [{"id": "e1", "subject": "Hola"}]}, "2"]]}

    monkeypatch.setattr(s, "_jmap", fake_jmap)
    resultado = s.listar_mensajes("API_abc", mailbox="INBOX", limite=5)

    assert resultado == [{"id": "e1", "subject": "Hola"}]
    assert capturado["cabeceras"] == {"Authorization": "Bearer API_abc"}
    assert all(mc[1]["accountId"] == "d" for mc in capturado["method_calls"])


def test_leer_mensaje_sin_api_key_lanza_error():
    with pytest.raises(s.ErrorStalwart):
        s.leer_mensaje("", "abc")


def test_leer_mensaje_no_encontrado_lanza_error(monkeypatch):
    monkeypatch.setattr(s, "_account_id_propio", lambda api_key: "d")
    monkeypatch.setattr(s, "_jmap", lambda method_calls, *, cabeceras: {"methodResponses": [["Email/get", {"list": []}, "0"]]})
    with pytest.raises(s.ErrorStalwart):
        s.leer_mensaje("API_abc", "no-existe")


def test_enviar_mensaje_sin_api_key_lanza_error():
    with pytest.raises(s.ErrorStalwart):
        s.enviar_mensaje("", "a@b.com", "Asunto", "Cuerpo")


def test_enviar_mensaje_delega_con_accountid_resuelto(monkeypatch):
    monkeypatch.setattr(s, "_account_id_propio", lambda api_key: "d")

    def fake_jmap(method_calls, *, cabeceras):
        return {"methodResponses": [["EmailSubmission/set", {"created": {"envio": {"id": "sub1"}}}, "2"]]}

    monkeypatch.setattr(s, "_jmap", fake_jmap)
    resultado = s.enviar_mensaje("API_abc", "ana@ejemplo.com", "Hola", "Cuerpo")

    assert resultado == {"id": "sub1"}


def test_enviar_mensaje_propaga_error_si_no_se_crea(monkeypatch):
    monkeypatch.setattr(s, "_account_id_propio", lambda api_key: "d")
    monkeypatch.setattr(
        s, "_jmap",
        lambda method_calls, *, cabeceras: {"methodResponses": [["EmailSubmission/set", {"notCreated": {"envio": {}}}, "2"]]},
    )
    with pytest.raises(s.ErrorStalwart):
        s.enviar_mensaje("API_abc", "ana@ejemplo.com", "Hola", "Cuerpo")
