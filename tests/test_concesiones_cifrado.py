"""Concesiones: API, MCP y aplicaciones OAuth leen lo cifrado con una clave envuelta con su propio secreto, aunque el despacho esté bloqueado, y solo mientras valgan."""
import pytest
from mcp.server.auth.provider import AccessToken

import mcp_tools
from app import almacen_documentos as alm
from app import cifrado_despacho as cd
from app import db, nucleo, rutas_hydra
from tests.conftest import iniciar_sesion_de_prueba

FRASE = "una frase de paso larga y segura"
SECRETO = b"CONTENIDO-CIFRADO-PARA-INTEGRACIONES"


@pytest.fixture(autouse=True)
def argon2_rapido(monkeypatch):
    monkeypatch.setattr(cd, "ARGON2", {"time_cost": 1, "memory_cost": 8, "parallelism": 1})
    alm.fijar_cifrador(None)


def _despacho(n=2, nombre="Despacho Conc"):
    t = db.crear_tenant(nombre)
    us = []
    for i in range(n):
        u = db.crear_usuario_vinculado_a_kratos(f"{nombre.lower().replace(' ', '')}-{i}@ejemplo.com", f"kratos-{nombre}-{i}")
        db.asignar_tenant(u, t)
        us.append(u)
    db.asignar_supervisor_tenant(us[0], True)
    return t, us


def _con_documento(t, u):
    c = nucleo.crear_cliente(t, "Cliente")
    cd.activar(t, u, FRASE)
    _, did = alm.guardar(u, "acta.txt", "text/plain", SECRETO, cliente_id=c)
    return c, did


# --- el mecanismo -----------------------------------------------------------------------------------------------------------------------------------
def test_crear_una_concesion_exige_el_despacho_desbloqueado(usuario_id):
    t, (u, _) = _despacho()
    cd.activar(t, u, FRASE)
    cd.bloquear(t)
    with pytest.raises(cd.DespachoBloqueado):
        cd.crear_concesion(t, u, "secreto-de-prueba", "oauth", "app")
    cd.desbloquear(t, u, FRASE)
    assert cd.crear_concesion(t, u, "secreto-de-prueba", "oauth", "app")
    with pytest.raises(ValueError):
        cd.crear_concesion(t, u, "x", "otra-cosa", "app")


def test_con_la_concesion_se_lee_aunque_el_despacho_este_bloqueado(usuario_id):
    t, (u, _) = _despacho()
    c, did = _con_documento(t, u)
    cd.crear_concesion(t, u, "secreto-de-integracion", "oauth", "Claude")
    cd.bloquear(t)
    with pytest.raises(cd.DespachoBloqueado):
        alm.leer(t, u, did)
    testigo = cd.fijar_concesion("mcp", "secreto-de-integracion")
    assert alm.leer(t, u, did)["contenido"] == SECRETO
    assert cd.accesos_recientes(t)[0]["via"] == "mcp"
    cd.restablecer_concesion(testigo)
    with pytest.raises(cd.DespachoBloqueado):
        alm.leer(t, u, did)


def test_un_secreto_equivocado_o_de_otro_despacho_no_abre_nada(usuario_id):
    t1, (u1, _) = _despacho(nombre="Despacho C1")
    t2, (u2, _) = _despacho(nombre="Despacho C2")
    _, d1 = _con_documento(t1, u1)
    cd.crear_concesion(t1, u1, "secreto-bueno", "oauth", "app")
    cd.bloquear(t1)
    for secreto in ("secreto-malo", "", None):
        testigo = cd.fijar_concesion("api", secreto)
        with pytest.raises(cd.DespachoBloqueado):
            alm.leer(t1, u1, d1)
        cd.restablecer_concesion(testigo)
    # una concesión del despacho 1 no sirve en el 2
    cd.activar(t2, u2, FRASE)
    c2 = nucleo.crear_cliente(t2, "C2")
    _, d2 = alm.guardar(u2, "x.txt", "text/plain", b"otro despacho", cliente_id=c2)
    cd.bloquear(t2)
    testigo = cd.fijar_concesion("api", "secreto-bueno")
    with pytest.raises(cd.DespachoBloqueado):
        alm.leer(t2, u2, d2)
    cd.restablecer_concesion(testigo)


def test_revocar_y_caducar_cortan_el_acceso_al_instante(usuario_id):
    t, (u, _) = _despacho()
    c, did = _con_documento(t, u)
    cid = cd.crear_concesion(t, u, "secreto-revocable", "oauth", "app")
    cd.crear_concesion(t, u, "secreto-caducado", "oauth", "vieja", caduca_en="2020-01-01T00:00:00")
    cd.bloquear(t)
    testigo = cd.fijar_concesion("api", "secreto-revocable")
    assert alm.leer(t, u, did)["contenido"] == SECRETO
    assert cd.revocar_concesion(t, cid) and not cd.revocar_concesion(t, cid)
    with pytest.raises(cd.DespachoBloqueado):
        alm.leer(t, u, did)
    cd.restablecer_concesion(testigo)
    testigo = cd.fijar_concesion("api", "secreto-caducado")
    with pytest.raises(cd.DespachoBloqueado):
        alm.leer(t, u, did)
    cd.restablecer_concesion(testigo)


def test_la_concesion_de_un_token_muere_con_el_token(usuario_id):
    t, (u, _) = _despacho()
    c, did = _con_documento(t, u)
    token = db.crear_token_api(u, "integración")
    cd.crear_concesion(t, u, token, "token", "integración")
    cd.bloquear(t)
    testigo = cd.fijar_concesion("api", token)
    assert alm.leer(t, u, did)["contenido"] == SECRETO
    assert cd.listar_concesiones(t)[0]["huerfana"] == 0
    db.revocar_token_api(token)
    with pytest.raises(cd.DespachoBloqueado):
        alm.leer(t, u, did)
    assert cd.listar_concesiones(t)[0]["huerfana"] == 1
    cd.restablecer_concesion(testigo)


# --- API REST -----------------------------------------------------------------------------------------------------------------------------------------
def _cab(token):
    return {"Authorization": f"Bearer {token}"}


def test_la_api_de_documentos_lista_y_descarga_con_concesion_y_da_423_sin_ella(cliente):
    t, (u, _) = _despacho()
    c, did = _con_documento(t, u)
    con = db.crear_token_api(u, "con concesión")
    sin = db.crear_token_api(u, "sin concesión")
    cd.crear_concesion(t, u, con, "token", "con concesión")
    cd.bloquear(t)
    lista = cliente.get(f"/api/v1/documentos?cliente_id={c}", headers=_cab(con)).get_json()["data"]
    assert lista[0]["nombre_archivo"] == "acta.txt" and lista[0]["contenido_disponible"] is True
    assert cliente.get(f"/api/v1/documentos?cliente_id={c}", headers=_cab(sin)).get_json()["data"][0]["contenido_disponible"] is False
    r = cliente.get(f"/api/v1/documentos/{did}/contenido", headers=_cab(con))
    assert r.status_code == 200 and r.data == SECRETO and r.headers["X-Content-Type-Options"] == "nosniff"
    r = cliente.get(f"/api/v1/documentos/{did}/contenido", headers=_cab(sin))
    assert r.status_code == 423 and r.get_json()["codigo"] == "despacho_bloqueado" and SECRETO not in r.data
    assert cliente.get("/api/v1/documentos", headers=_cab(con)).status_code == 400
    assert [x["via"] for x in cd.accesos_recientes(t)][0] == "api"
    # la concesión no se arrastra a la petición siguiente del mismo hilo
    assert cliente.get(f"/api/v1/documentos/{did}/contenido", headers=_cab(sin)).status_code == 423


def test_un_token_limitado_a_otra_area_no_llega_a_los_documentos(cliente):
    t, (u, _) = _despacho()
    c, did = _con_documento(t, u)
    tareas = db.crear_token_api(u, "solo tareas", areas=["tareas"])
    docs = db.crear_token_api(u, "solo documentos", areas=["documentos"])
    assert cliente.get(f"/api/v1/documentos?cliente_id={c}", headers=_cab(tareas)).status_code == 403
    assert cliente.get(f"/api/v1/documentos?cliente_id={c}", headers=_cab(docs)).status_code == 200


def test_la_api_no_enseña_documentos_de_otro_despacho(cliente):
    t1, (u1, _) = _despacho(nombre="Despacho A1")
    t2, (u2, _) = _despacho(nombre="Despacho A2")
    c, did = _con_documento(t1, u1)
    token2 = db.crear_token_api(u2, "otro")
    assert cliente.get(f"/api/v1/documentos?cliente_id={c}", headers=_cab(token2)).get_json()["data"] == []
    assert cliente.get(f"/api/v1/documentos/{did}/contenido", headers=_cab(token2)).status_code == 404


def test_crear_un_token_desde_la_web_con_acceso_a_documentos(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "conc-web@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho Web Conc")
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, True)
    cd.activar(t, uid, FRASE)
    antes = len(db.listar_tokens_api(uid))
    r = cliente.post("/mis-dispositivos/token", data={"nombre": "Integración", "documentos_cifrados": "1"})
    assert r.status_code == 200 and len(db.listar_tokens_api(uid)) == antes + 1 and cd.listar_concesiones(t)[0]["etiqueta"] == "Integración"
    cd.bloquear(t)
    r = cliente.post("/mis-dispositivos/token", data={"nombre": "Con el despacho bloqueado", "documentos_cifrados": "1"})
    assert r.status_code == 400 and len(db.listar_tokens_api(uid)) == antes + 1, "sin concesión no se deja un token a medias"


def test_un_miembro_normal_no_puede_dar_acceso_a_lo_cifrado(cliente):
    t = db.crear_tenant("Despacho Normal Conc")
    uid = iniciar_sesion_de_prueba(cliente, "conc-normal@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, t)
    otro = db.crear_usuario_vinculado_a_kratos("resp-conc@ejemplo.com", "k-resp-conc")
    db.asignar_tenant(otro, t)
    cd.activar(t, otro, FRASE)
    antes = len(db.listar_tokens_api(uid))
    assert cliente.post("/mis-dispositivos/token", data={"nombre": "x", "documentos_cifrados": "1"}).status_code == 400
    assert len(db.listar_tokens_api(uid)) == antes and cd.listar_concesiones(t) == []


def test_revocar_desde_la_pantalla(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "conc-rev@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho Rev")
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, True)
    cd.activar(t, uid, FRASE)
    cid = cd.crear_concesion(t, uid, "secreto-pantalla", "oauth", "Aplicación de prueba")
    assert "Aplicación de prueba" in cliente.get("/seguridad/cifrado").get_data(as_text=True)
    assert cliente.post(f"/seguridad/cifrado/concesiones/{cid}/revocar").status_code == 302
    assert cd.listar_concesiones(t) == [] and cliente.post(f"/seguridad/cifrado/concesiones/{cid}/revocar").status_code == 404


# --- MCP ----------------------------------------------------------------------------------------------------------------------------------------------
def _como_mcp(monkeypatch, token: AccessToken):
    monkeypatch.setattr(mcp_tools, "get_access_token", lambda: token)


def test_el_mcp_con_token_personal_lee_con_su_concesion(usuario_id, monkeypatch):
    t, (u, _) = _despacho()
    c, did = _con_documento(t, u)
    token = db.crear_token_api(u, "mcp")
    cd.crear_concesion(t, u, token, "token", "mcp")
    cd.bloquear(t)
    from app import mcp_acceso
    scopes = mcp_acceso.scopes_de_token_personal(db.autenticar_token_completo(token))
    _como_mcp(monkeypatch, AccessToken(token=token, client_id="token-personal", scopes=scopes, expires_at=None))
    leer = mcp_tools._con_guardian(mcp_tools.leer_documento_despacho)
    assert leer(documento_id=did)["texto"] == SECRETO.decode()
    assert cd.accesos_recientes(t)[0]["via"] == "mcp"
    sin = db.crear_token_api(u, "mcp sin concesión")
    _como_mcp(monkeypatch, AccessToken(token=sin, client_id="token-personal", scopes=mcp_acceso.scopes_de_token_personal(db.autenticar_token_completo(sin)), expires_at=None))
    with pytest.raises(ValueError, match="protegidos"):
        mcp_tools._con_guardian(mcp_tools.leer_documento_despacho)(documento_id=did)
    assert "aviso" in mcp_tools._con_guardian(mcp_tools.listar_documentos_despacho)(cliente_id=c)


def test_una_aplicacion_oauth_necesita_el_alcance_de_documentos(usuario_id, monkeypatch):
    t, (u, _) = _despacho()
    c, did = _con_documento(t, u)
    cd.crear_concesion(t, u, "secreto-oauth", "oauth", "Claude")
    cd.bloquear(t)
    base = [f"usuario:{u}"]
    _como_mcp(monkeypatch, AccessToken(token="x", client_id="claude-desktop", scopes=base + ["cs:secreto-oauth"], expires_at=None))
    with pytest.raises(ValueError, match="no tiene permiso para los documentos"):
        mcp_tools._con_guardian(mcp_tools.leer_documento_despacho)(documento_id=did)
    _como_mcp(monkeypatch, AccessToken(token="x", client_id="claude-desktop", scopes=base + ["guilda:documentos", "cs:secreto-oauth"], expires_at=None))
    assert mcp_tools._con_guardian(mcp_tools.leer_documento_despacho)(documento_id=did)["texto"] == SECRETO.decode()
    _como_mcp(monkeypatch, AccessToken(token="x", client_id="claude-desktop", scopes=base + ["guilda:documentos", "cs:secreto-revocado"], expires_at=None))
    with pytest.raises(ValueError, match="protegidos"):
        mcp_tools._con_guardian(mcp_tools.leer_documento_despacho)(documento_id=did)


# --- consentimiento de Hydra --------------------------------------------------------------------------------------------------------------------------
class _Hydra:
    def __init__(self, monkeypatch):
        self.llamadas = []
        monkeypatch.setattr(rutas_hydra.hydra, "aceptar_consent_request", lambda challenge, **kw: self.llamadas.append(kw) or "https://vuelta.test/")


def _consent(scopes):
    return {"requested_scope": scopes, "client": {"client_id": "c1", "client_name": "Claude"}}


def test_consentir_documentos_crea_la_concesion_y_mete_el_secreto_en_el_token(usuario_id, monkeypatch):
    t, (resp, _) = _despacho()
    cd.activar(t, resp, FRASE)
    h = _Hydra(monkeypatch)
    rutas_hydra._aceptar("ch", _consent(["openid", "guilda:documentos"]), db.obtener_usuario(resp))
    kw = h.llamadas[0]
    assert "guilda:documentos" in kw["scopes"] and kw["ext_access_token"]["guilda_cs"]
    c = cd.listar_concesiones(t)
    assert len(c) == 1 and c[0]["tipo"] == "oauth" and c[0]["etiqueta"] == "Claude"
    cd.bloquear(t)
    cl = nucleo.crear_cliente(t, "Cliente")
    cd.desbloquear(t, resp, FRASE)
    _, did = alm.guardar(resp, "a.txt", "text/plain", SECRETO, cliente_id=cl)
    cd.bloquear(t)
    testigo = cd.fijar_concesion("mcp", kw["ext_access_token"]["guilda_cs"])
    assert alm.leer(t, resp, did)["contenido"] == SECRETO
    cd.restablecer_concesion(testigo)


def test_consentir_documentos_sin_ser_responsable_o_con_el_despacho_bloqueado_los_quita_del_alcance(usuario_id, monkeypatch):
    t, (resp, normal) = _despacho()
    cd.activar(t, resp, FRASE)
    h = _Hydra(monkeypatch)
    rutas_hydra._aceptar("ch", _consent(["openid", "guilda:documentos"]), db.obtener_usuario(normal))
    cd.bloquear(t)
    rutas_hydra._aceptar("ch", _consent(["openid", "guilda:documentos"]), db.obtener_usuario(resp))
    for kw in h.llamadas:
        assert kw["scopes"] == ["openid"] and "ext_access_token" not in kw
    assert cd.listar_concesiones(t) == []


def test_sin_cifrado_activado_el_consentimiento_no_cambia(usuario_id, monkeypatch):
    t, (resp, _) = _despacho()
    h = _Hydra(monkeypatch)
    rutas_hydra._aceptar("ch", _consent(["openid", "guilda:documentos"]), db.obtener_usuario(resp))
    assert h.llamadas[0]["scopes"] == ["openid", "guilda:documentos"] and "ext_access_token" not in h.llamadas[0]


# --- expediente documental fiscal cifrado y rotación de la clave --------------------------------------------------------------------------------------
def test_el_expediente_fiscal_tambien_se_cifra_y_se_abre(usuario_id):
    t, (u, _) = _despacho()
    f = db.crear_cliente_fiscal(t, "Cliente Fiscal")
    _, antes = alm.guardar_de_cliente_fiscal(u, f, "antes.txt", "text/plain", SECRETO + b"-antes")
    cd.activar(t, u, FRASE)
    _, despues = alm.guardar_de_cliente_fiscal(u, f, "despues.txt", "text/plain", SECRETO + b"-despues")
    conn = db.get_connection()
    filas = {r["id"]: r for r in conn.execute("SELECT id, contenido, cifrado, sobre FROM cliente_documentos")}
    conn.close()
    for i in (antes, despues):
        assert filas[i]["cifrado"] == 1 and SECRETO not in bytes(filas[i]["contenido"])
    assert alm.leer_de_cliente_fiscal(t, f, antes, u)["contenido"] == SECRETO + b"-antes"
    assert cd.accesos_recientes(t)[0]["nombre_archivo"] == "antes.txt"
    cd.bloquear(t)
    with pytest.raises(cd.DespachoBloqueado):
        alm.leer_de_cliente_fiscal(t, f, despues, u)
    assert {d["nombre_archivo"] for d in alm.listar_de_cliente_fiscal(t, f)} == {"Documento protegido"}      # listar no necesita la clave; el nombre (nivel Medio) sí
    assert alm.eliminar_de_cliente_fiscal(u, f, antes)                                                   # ni borrar


def test_la_ficha_fiscal_descarga_por_web_y_da_423_bloqueado(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "fiscal-cif@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho Fiscal Cif")
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, True)
    f = db.crear_cliente_fiscal(t, "Cliente")
    cd.activar(t, uid, FRASE)
    _, did = alm.guardar_de_cliente_fiscal(uid, f, "a.txt", "text/plain", SECRETO)
    assert cliente.get(f"/fiscal/clientes/{f}/documentos/{did}").data == SECRETO
    cd.bloquear(t)
    r = cliente.get(f"/fiscal/clientes/{f}/documentos/{did}")
    assert r.status_code == 423 and SECRETO not in r.data
    token = db.crear_token_api(uid, "api")
    assert cliente.get(f"/api/v1/fiscal/clientes/{f}/documentos/{did}", headers=_cab(token)).status_code == 423
    cd.desbloquear(t, uid, FRASE)
    cd.crear_concesion(t, uid, token, "token", "api")
    cd.bloquear(t)
    assert cliente.get(f"/api/v1/fiscal/clientes/{f}/documentos/{did}", headers=_cab(token)).data == SECRETO


def test_rotar_la_clave_recifra_todo_cambia_la_recuperacion_y_revoca_concesiones(usuario_id):
    t, (u, _) = _despacho()
    f = db.crear_cliente_fiscal(t, "Fiscal")
    c, d1 = _con_documento(t, u)
    _, d2 = alm.guardar_de_cliente_fiscal(u, f, "fiscal.txt", "text/plain", SECRETO + b"-fiscal")
    cd.crear_concesion(t, u, "secreto-antiguo", "oauth", "app")
    conn = db.get_connection()
    publica_antes = conn.execute("SELECT publica FROM cifrado_despacho WHERE tenant_id = ?", (t,)).fetchone()[0]
    contenido_antes = bytes(conn.execute("SELECT contenido FROM documentos WHERE id = ?", (d1,)).fetchone()[0])
    conn.close()
    cd.bloquear(t)
    with pytest.raises(cd.ClaveIncorrecta):
        cd.rotar_clave(t, u, "frase equivocada del todo")
    recuperacion_nueva = cd.rotar_clave(t, u, FRASE)
    conn = db.get_connection()
    publica_despues = conn.execute("SELECT publica FROM cifrado_despacho WHERE tenant_id = ?", (t,)).fetchone()[0]
    contenido_despues = bytes(conn.execute("SELECT contenido FROM documentos WHERE id = ?", (d1,)).fetchone()[0])
    conn.close()
    assert publica_despues != publica_antes and contenido_despues != contenido_antes
    assert alm.leer(t, u, d1)["contenido"] == SECRETO and alm.leer_de_cliente_fiscal(t, f, d2, u)["contenido"] == SECRETO + b"-fiscal"
    assert cd.listar_concesiones(t) == []
    cd.bloquear(t)
    testigo = cd.fijar_concesion("api", "secreto-antiguo")
    with pytest.raises(cd.DespachoBloqueado):
        alm.leer(t, u, d1)
    cd.restablecer_concesion(testigo)
    cd.desbloquear(t, u, FRASE)                    # la misma frase sigue valiendo
    cd.bloquear(t)
    cd.recuperar(t, u, recuperacion_nueva, "frase nueva tras rotar la clave")
    assert alm.leer(t, u, d1)["contenido"] == SECRETO


def test_rotar_con_una_fila_manipulada_no_deja_nada_a_medias(usuario_id):
    t, (u, _) = _despacho()
    c, d1 = _con_documento(t, u)
    _, d2 = alm.guardar(u, "b.txt", "text/plain", b"segundo", cliente_id=c)
    conn = db.get_connection()
    ct = bytes(conn.execute("SELECT contenido FROM documentos WHERE id = ?", (d2,)).fetchone()[0])
    conn.execute("UPDATE documentos SET contenido = ? WHERE id = ?", (ct[:-2] + b"\x00\x00", d2))
    conn.commit()
    publica = conn.execute("SELECT publica FROM cifrado_despacho WHERE tenant_id = ?", (t,)).fetchone()[0]
    conn.close()
    with pytest.raises(cd.ContenidoAlterado):
        cd.rotar_clave(t, u, FRASE)
    conn = db.get_connection()
    assert conn.execute("SELECT publica FROM cifrado_despacho WHERE tenant_id = ?", (t,)).fetchone()[0] == publica
    conn.close()
    assert alm.leer(t, u, d1)["contenido"] == SECRETO, "el documento sano sigue con la clave de siempre"


def test_rotar_desde_la_pantalla(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "rotar-web@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho Rotar")
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, True)
    cd.activar(t, uid, FRASE)
    r = cliente.post("/seguridad/cifrado/rotar", data={"frase": FRASE}, follow_redirects=True)
    assert "Confirma que has entendido" in r.get_data(as_text=True)
    r = cliente.post("/seguridad/cifrado/rotar", data={"frase": "frase equivocada del todo", "entendido": "1"}, follow_redirects=True)
    assert "Frase incorrecta" in r.get_data(as_text=True)
    r = cliente.post("/seguridad/cifrado/rotar", data={"frase": FRASE, "entendido": "1"})
    assert r.status_code == 200 and "Guarda tu clave de recuperación" in r.get_data(as_text=True) and r.headers["Cache-Control"] == "no-store"


def test_nadie_lee_el_contenido_de_los_documentos_sin_pasar_por_el_almacen():
    """Garantía de §8.2.1: una sola capa de lectura. Cualquier `SELECT *` o de `contenido` sobre las tablas de documentos fuera del almacén se saltaría el cifrado."""
    import re
    from pathlib import Path
    raiz = Path(__file__).resolve().parent.parent
    permitidos = {"app/db.py", "app/db_fiscal.py", "app/almacen_documentos.py"}
    fuentes = [*(raiz / "app").glob("*.py"), raiz / "mcp_tools" / "__init__.py", *(raiz / "mcp_tools").glob("herramientas_*.py"), raiz / "mcp_server.py", raiz / "mcp_server_remoto.py", *(raiz / "scripts").glob("*.py")]
    for ruta in fuentes:
        rel = ruta.relative_to(raiz).as_posix()
        if rel in permitidos or not ruta.exists():
            continue
        texto = ruta.read_text(encoding="utf-8")
        for m in re.finditer(r'SELECT\s+(?P<campos>[^";]*?)\s+FROM\s+(documentos|cliente_documentos)\b', texto, re.I | re.S):
            campos = m.group("campos")
            assert not re.search(r"(^|[\s,(.])\*|\bcontenido\b", campos), f"{rel} lee el contenido de {m.group(2)} sin pasar por app/almacen_documentos.py"
