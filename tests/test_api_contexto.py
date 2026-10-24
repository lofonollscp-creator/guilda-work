"""API 1.5 para la app móvil: `/auth/me` con despachos, módulos y permisos; `426 actualiza_app`; apariencia en `/perfil`."""
import pytest

from app import api_contexto, db
from tests.test_rutas_api import _auth, _registrar


def _persona(cliente, email="movil@ejemplo.com"):
    datos = _registrar(cliente, email)
    return datos["token"], datos["usuario"]["id"] if "usuario" in datos else db.obtener_usuario_por_email(email)["id"]


def _me(cliente, token, **cabeceras):
    r = cliente.get("/api/v1/auth/me", headers={**_auth(token), **cabeceras})
    assert r.status_code == 200
    return r.get_json()["data"]


def test_me_conserva_lo_de_siempre_y_trae_el_contexto_nuevo(cliente):
    token, uid = _persona(cliente)
    t = db.crear_tenant("Alfa Asesores")
    db.asignar_tenant(uid, t)
    d = _me(cliente, token)
    assert d["email"] == "movil@ejemplo.com" and d["tenant_id"] == t          # lo de siempre
    assert d["despacho_activo"] == t
    assert d["despachos"] == [{"id": t, "nombre": "Alfa Asesores", "principal": True, "gestor_fichajes": False, "supervisor": False}]
    assert d["modulos"]["gestoria"] is True and d["modulos"]["abogados"] is False
    assert set(d["permisos"]) == {"fichaje_admin", "supervisor_fiscal", "admin"}
    assert d["cifrado"] == {"activo": False, "nivel": None}
    assert d["apariencia"] == {"tema": None, "densidad": None, "idioma": None}
    assert set(d["app"]) == {"version_minima", "version_recomendada", "url_tienda"}


def test_sin_despacho_la_lista_va_vacia(cliente):
    token, _ = _persona(cliente, "suelto@ejemplo.com")
    d = _me(cliente, token)
    assert d["despachos"] == [] and d["despacho_activo"] is None


def test_x_despacho_elige_el_despacho_y_los_permisos_son_de_cada_uno(cliente):
    token, uid = _persona(cliente, "multi@ejemplo.com")
    t1, t2 = db.crear_tenant("Alfa Asesores"), db.crear_tenant("Beta Abogados")
    db.asignar_tenant(uid, t1)
    db.anadir_usuario_a_tenant(uid, t2)
    db.fijar_atributos_en_despacho(uid, t1, supervisor_tenant=1)
    principal = _me(cliente, token)
    assert [x["id"] for x in principal["despachos"]] == [t1, t2] and principal["despacho_activo"] == t1
    assert principal["permisos"]["supervisor_fiscal"] is True
    otro = _me(cliente, token, **{"X-Despacho": str(t2)})
    assert otro["despacho_activo"] == t2 and otro["permisos"]["supervisor_fiscal"] is False
    ajeno = db.crear_tenant("Despacho ajeno")
    assert _me(cliente, token, **{"X-Despacho": str(ajeno)})["despacho_activo"] == t1      # uno que no es suyo: el principal


def test_version_minima_de_la_app(cliente, monkeypatch):
    token, _ = _persona(cliente, "version@ejemplo.com")
    monkeypatch.setenv("GUILDA_APP_VERSION_MINIMA", "1.2.0")
    monkeypatch.setenv("GUILDA_APP_URL_TIENDA", "https://tienda.ejemplo/guilda")
    r = cliente.get("/api/v1/categorias", headers={**_auth(token), "X-App-Version": "1.1.9"})
    assert r.status_code == 426
    cuerpo = r.get_json()
    assert cuerpo["codigo"] == "actualiza_app" and cuerpo["version_minima"] == "1.2.0" and cuerpo["url_tienda"] == "https://tienda.ejemplo/guilda"
    assert cliente.get("/api/v1/categorias", headers={**_auth(token), "X-App-Version": "1.2.0"}).status_code == 200
    assert cliente.get("/api/v1/categorias", headers={**_auth(token), "X-App-Version": "1.10.0"}).status_code == 200
    assert cliente.get("/api/v1/categorias", headers=_auth(token)).status_code == 200            # web e integraciones no mandan la cabecera
    assert cliente.get("/api/v1/health", headers={"X-App-Version": "0.1"}).status_code == 200     # la comprobación de vida nunca se bloquea
    assert _me(cliente, token)["app"]["version_minima"] == "1.2.0"


def test_sin_version_minima_fijada_nadie_se_bloquea(cliente, monkeypatch):
    token, _ = _persona(cliente, "libre@ejemplo.com")
    monkeypatch.delenv("GUILDA_APP_VERSION_MINIMA", raising=False)
    assert cliente.get("/api/v1/categorias", headers={**_auth(token), "X-App-Version": "0.0.1"}).status_code == 200


def test_la_apariencia_va_en_el_perfil_y_en_me(cliente):
    token, _ = _persona(cliente, "tema@ejemplo.com")
    r = cliente.put("/api/v1/perfil", headers=_auth(token), json={"tema": "dark", "densidad": "compacta", "idioma": "ca"})
    assert r.status_code == 200
    esperado = {"tema": "dark", "densidad": "compacta", "idioma": "ca"}
    assert r.get_json()["data"]["apariencia"] == esperado
    assert cliente.get("/api/v1/perfil", headers=_auth(token)).get_json()["data"]["apariencia"] == esperado
    assert _me(cliente, token)["apariencia"] == esperado


def test_un_valor_de_apariencia_no_valido_es_un_400_con_su_campo(cliente):
    token, _ = _persona(cliente, "malo@ejemplo.com")
    for campo, valor in (("tema", "morado"), ("densidad", "enorme"), ("idioma", "xx")):
        r = cliente.put("/api/v1/perfil", headers=_auth(token), json={campo: valor})
        assert r.status_code == 400 and r.get_json()["campo"] == campo and r.get_json()["codigo"] == "valor_invalido"
    assert cliente.get("/api/v1/perfil", headers=_auth(token)).get_json()["data"]["apariencia"]["tema"] is None


def test_actualizar_solo_el_nombre_no_toca_la_apariencia(cliente):
    token, _ = _persona(cliente, "nombre@ejemplo.com")
    cliente.put("/api/v1/perfil", headers=_auth(token), json={"tema": "light"})
    cliente.put("/api/v1/perfil", headers=_auth(token), json={"nombre_mostrado": "Ana"})
    d = cliente.get("/api/v1/perfil", headers=_auth(token)).get_json()["data"]
    assert d["nombre_mostrado"] == "Ana" and d["apariencia"]["tema"] == "light"


@pytest.mark.parametrize("a,b,esperado", [("1.0.0", "1.1.0", -1), ("1.10.0", "1.9.9", 1), ("1.2", "1.2.0", 0), ("1.2.3+45", "1.2.3", 0), ("2", "1.9.9", 1)])
def test_comparar_versiones(a, b, esperado):
    assert api_contexto.comparar_versiones(a, b) == esperado


def test_el_412_de_cliente_y_vencimiento_trae_la_version_actual(cliente):
    from tests.test_api_fiscal import _cliente_fiscal, _despacho, _venc
    h, _, _ = _despacho(cliente, "version412@ejemplo.com")
    cid = _cliente_fiscal(cliente, h)
    actual = cliente.get(f"/api/v1/fiscal/clientes/{cid}", headers=h).get_json()["data"]["version"]
    r = cliente.put(f"/api/v1/fiscal/clientes/{cid}", json={"notas": "x"}, headers={**h, "If-Match": f'"{actual + 7}"'})
    assert r.status_code == 412
    assert r.get_json()["codigo"] == "version_obsoleta" and r.get_json()["version_actual"] == actual and r.get_json()["request_id"]
    vid = _venc(cliente, h, cid).get_json()["data"]["id"]
    v_actual = cliente.get(f"/api/v1/fiscal/vencimientos/{vid}", headers=h).get_json()["data"]["version"]
    r = cliente.put(f"/api/v1/fiscal/vencimientos/{vid}", json={"notas": "x"}, headers={**h, "If-Match": f'"{v_actual + 7}"'})
    assert r.status_code == 412 and r.get_json()["version_actual"] == v_actual
