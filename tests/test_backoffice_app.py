"""Backoffice independiente (paquete backoffice/): acceso propio, CSRF,
dashboard, tenants y usuarios. No usa Kratos ni la sesión de la app."""
import re
import time

import pytest

from app import db, kratos
from backoffice import auth, datos
from backoffice.main import create_app

CLAVE = "una-clave-larga-y-segura-1"


@pytest.fixture
def bo(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "backoffice.db")
    monkeypatch.setattr(auth, "SECRET_PATH", tmp_path / "bo_secret.key")
    auth.crear_admin("jorge", CLAVE, "Jorge")
    from backoffice import aprovisionamiento
    monkeypatch.setattr(aprovisionamiento, "aprovisionar_usuario", lambda *a, **k: [])
    return create_app(testing=True).test_client()


def _csrf(html: str) -> str:
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)


def entrar(cliente, usuario="jorge", clave=CLAVE):
    token = _csrf(cliente.get("/login").get_data(as_text=True))
    return cliente.post("/login", data={"usuario": usuario, "contrasena": clave, "_csrf": token})


def post(cliente, ruta, **datos_form):
    # Cualquier página autenticada trae un token válido en un formulario (logout).
    token = _csrf(cliente.get("/").get_data(as_text=True))
    return cliente.post(ruta, data={**datos_form, "_csrf": token})


# --- Acceso -----------------------------------------------------------------

def test_sin_sesion_redirige_al_login_y_healthz_es_publico(bo):
    assert bo.get("/").status_code == 302 and "/login" in bo.get("/").headers["Location"]
    assert bo.get("/tenants").status_code == 302 and bo.get("/usuarios").status_code == 302
    assert bo.get("/healthz").data == b"ok"


def test_login_correcto_incorrecto_y_mensaje_generico(bo):
    r = entrar(bo, clave="mala-mala-mala-1")
    assert r.status_code == 401 and "Usuario o contraseña incorrectos" in r.get_data(as_text=True)
    r = entrar(bo, usuario="noexiste", clave="cualquier-cosa-larga")
    assert r.status_code == 401 and "Usuario o contraseña incorrectos" in r.get_data(as_text=True)  # no delata si existe
    r = entrar(bo)
    assert r.status_code == 302 and bo.get("/").status_code == 200
    assert "bo_session" in r.headers.get("Set-Cookie", "") and "HttpOnly" in r.headers["Set-Cookie"] and "SameSite=Strict" in r.headers["Set-Cookie"]


def test_bloqueo_tras_varios_intentos_fallidos(bo):
    for _ in range(auth.INTENTOS_MAX_POR_USUARIO):
        assert entrar(bo, clave="mala-mala-mala-1").status_code == 401
    r = entrar(bo)  # incluso con la clave buena, ya bloqueado
    assert r.status_code == 429 and "Demasiados intentos" in r.get_data(as_text=True)


def test_redireccion_tras_login_solo_a_rutas_internas(bo):
    token = _csrf(bo.get("/login").get_data(as_text=True))
    r = bo.post("/login?siguiente=https://malo.example/", data={"usuario": "jorge", "contrasena": CLAVE, "_csrf": token})
    assert r.headers["Location"].endswith("/")
    bo.post("/logout", data={"_csrf": _csrf(bo.get("/").get_data(as_text=True))})
    token = _csrf(bo.get("/login").get_data(as_text=True))
    r = bo.post("/login?siguiente=//malo.example", data={"usuario": "jorge", "contrasena": CLAVE, "_csrf": token})
    assert "malo.example" not in r.headers["Location"]


def test_csrf_obligatorio_en_todo_post(bo):
    entrar(bo)
    assert bo.post("/tenants", data={"nombre": "X"}).status_code == 400
    assert bo.post("/tenants", data={"nombre": "X", "_csrf": "falso"}).status_code == 400
    assert bo.post("/logout").status_code == 400
    assert bo.post("/login", data={"usuario": "jorge", "contrasena": CLAVE}).status_code == 400


def test_logout_cierra_la_sesion(bo):
    entrar(bo)
    post(bo, "/logout")
    assert bo.get("/").status_code == 302


def test_la_sesion_caduca_por_inactividad_y_por_antiguedad(bo):
    entrar(bo)
    with bo.session_transaction() as s:
        s["visto"] = int(time.time()) - (auth.INACTIVIDAD_MAX_MIN + 1) * 60
    assert bo.get("/").status_code == 302
    entrar(bo)
    with bo.session_transaction() as s:
        s["inicio"] = int(time.time()) - (auth.SESION_MAX_HORAS + 1) * 3600
    assert bo.get("/").status_code == 302


def test_cabeceras_de_seguridad_y_nada_se_cachea(bo):
    entrar(bo)
    h = bo.get("/").headers
    assert h["X-Frame-Options"] == "DENY" and "default-src 'self'" in h["Content-Security-Policy"] and h["Cache-Control"] == "no-store"
    assert "script-src 'self'" in h["Content-Security-Policy"] and "'unsafe-inline'" not in h["Content-Security-Policy"].split("style-src")[0]


def test_contrasena_minima_y_cambio():
    with pytest.raises(ValueError):
        auth.crear_admin("corta", "123")
    with pytest.raises(ValueError):
        auth.crear_admin("mal usuario!", CLAVE)


def test_la_contrasena_solo_se_guarda_como_hash(bo):
    conn = auth.conectar()
    try:
        fila = conn.execute("SELECT password_hash FROM admins WHERE usuario = 'jorge'").fetchone()
    finally:
        conn.close()
    assert CLAVE not in fila["password_hash"] and fila["password_hash"].startswith(("scrypt:", "pbkdf2:"))


# --- Dashboard --------------------------------------------------------------

def test_dashboard_calcula_mrr_arr_y_riesgo(bo):
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO planes_guilda (nombre, precio_mensual_centimos, activo, creado_en) VALUES ('Pro', 11600, 1, ?)", (db.now_iso(),))
        plan = conn.execute("SELECT id FROM planes_guilda").fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    a, b, c = db.crear_tenant("Alfa"), db.crear_tenant("Beta"), db.crear_tenant("Gamma")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE tenants SET plan_id = ?, suscripcion_estado = 'activa' WHERE id IN (?, ?)", (plan, a, b))
        conn.execute("UPDATE tenants SET plan_id = ?, suscripcion_estado = 'pago_fallido' WHERE id = ?", (plan, c))
        conn.commit()
    finally:
        conn.close()
    k = datos.kpis_dashboard()
    assert k["suscripciones_activas"] == 2 and k["mrr"] == 23200 and k["arr"] == 278400
    assert k["pagos_en_riesgo"] == 1 and k["mrr_en_riesgo"] == 11600
    assert {"nombre": "Pro", "n": 3} in k["tiers"] and any(c_["nombre"] == "Gamma" and c_["motivo"] == "pago fallido" for c_ in k["churn"])
    entrar(bo)
    html = bo.get("/").get_data(as_text=True)
    assert "232 €" in html and "2.784 €" in html and "116 €" in html and "Pagos en riesgo" in html


# --- Tenants ----------------------------------------------------------------

def test_tenants_lista_busca_filtra_pagina_y_cambia_de_vista(bo):
    entrar(bo)
    for i in range(30):
        db.crear_tenant(f"Gestoría {i:02d}")
    susp = db.crear_tenant("Suspendida SL")
    db.alternar_activo_tenant(susp, False)
    html = bo.get("/tenants?por_pagina=10").get_data(as_text=True)
    assert "Mostrando 1–10 de 31" in html and "1 de 4" in html
    assert "Suspendida SL" in bo.get("/tenants?estado=suspendido").get_data(as_text=True)
    assert "Gestoría 05" not in bo.get("/tenants?estado=suspendido").get_data(as_text=True)
    assert "Gestoría 05" in bo.get("/tenants?q=05&vista=rejilla").get_data(as_text=True)
    assert "rejilla-cartas" in bo.get("/tenants?vista=rejilla").get_data(as_text=True)
    assert "Ningún tenant" in bo.get("/tenants?q=zzz").get_data(as_text=True)
    assert bo.get("/tenants?pagina=999&por_pagina=10").status_code == 200  # página fuera de rango: se acota
    assert bo.get("/tenants?por_pagina=7").status_code == 200  # valor no permitido: se ignora


def test_busqueda_trata_comodines_como_texto(bo):
    entrar(bo)
    db.crear_tenant("Cien%Seguro")
    db.crear_tenant("Ciento Uno")
    html = bo.get("/tenants?q=n%25S").get_data(as_text=True)
    assert "Cien%Seguro" in html and "Ciento Uno" not in html


def test_crear_renombrar_suspender_y_modulos_de_un_tenant(bo, monkeypatch):
    from backoffice import aprovisionamiento
    monkeypatch.setattr(aprovisionamiento, "aprovisionar", lambda *a, **k: [])
    entrar(bo)
    r = post(bo, "/tenants", nombre="Nueva Gestoría")
    assert r.status_code == 200 and "Tenant creado: Nueva Gestoría" in r.get_data(as_text=True)
    tid = db.listar_tenants()[0]["id"]
    assert post(bo, "/tenants", nombre="Nueva Gestoría").status_code == 302  # duplicado: aviso, sin crash
    assert "Ya existe un tenant" in bo.get("/tenants").get_data(as_text=True)
    post(bo, f"/tenants/{tid}/renombrar", nombre="Gestoría Renombrada")
    assert db.obtener_tenant(tid)["nombre"] == "Gestoría Renombrada"
    post(bo, f"/tenants/{tid}/activo")
    assert db.obtener_tenant(tid)["activo"] == 0
    post(bo, f"/tenants/{tid}/activo")
    assert db.obtener_tenant(tid)["activo"] == 1
    from app import herramientas
    modulo = herramientas.HERRAMIENTAS[0]["id"]
    post(bo, f"/tenants/{tid}/modulos/{modulo}")
    assert modulo in db.herramientas_ocultas_de_tenant(tid)
    post(bo, f"/tenants/{tid}/modulos/{modulo}")
    assert modulo not in db.herramientas_ocultas_de_tenant(tid)
    assert post(bo, f"/tenants/{tid}/modulos/inventado").status_code == 400
    post(bo, f"/tenants/{tid}/geolocalizacion")
    assert db.obtener_tenant(tid)["fichaje_geolocalizacion"] == 1


@pytest.mark.parametrize("seccion", ["resumen", "usuarios", "modulos", "suscripcion", "actividad", "rara"])
def test_cada_seccion_de_la_ficha_del_tenant_se_renderiza(bo, seccion):
    entrar(bo)
    tid = db.crear_tenant("Ficha")
    uid = db.crear_usuario_vinculado_a_kratos("miembro@ejemplo.com", "k-miembro")
    db.asignar_tenant(uid, tid)
    r = bo.get(f"/tenants/{tid}?seccion={seccion}")
    assert r.status_code == 200 and "Ficha" in r.get_data(as_text=True)
    if seccion == "usuarios":
        assert "miembro@ejemplo.com" in r.get_data(as_text=True)
    assert bo.get("/tenants/99999").status_code == 404
    assert post(bo, "/tenants/99999/activo").status_code == 404


# --- Usuarios ---------------------------------------------------------------

def _usuario(email, tenant=None):
    uid = db.crear_usuario_vinculado_a_kratos(email, "k-" + email)
    if tenant:
        db.asignar_tenant(uid, tenant)
    return uid


def test_usuarios_filtros_busqueda_y_vistas(bo):
    entrar(bo)
    t1, t2 = db.crear_tenant("Uno"), db.crear_tenant("Dos")
    _usuario("ana@uno.com", t1)
    gestor = _usuario("beto@dos.com", t2)
    db.asignar_gestor_fichajes(gestor, True)
    _usuario("huerfano@nada.com")
    html = bo.get("/usuarios").get_data(as_text=True)
    assert "ana@uno.com" in html and "beto@dos.com" in html and "huerfano@nada.com" in html
    assert "beto@dos.com" not in bo.get(f"/usuarios?tenant={t1}").get_data(as_text=True)
    assert "huerfano@nada.com" in bo.get("/usuarios?tenant=ninguno").get_data(as_text=True)
    assert "beto@dos.com" in bo.get("/usuarios?rol=gestor").get_data(as_text=True)
    assert "ana@uno.com" not in bo.get("/usuarios?rol=gestor").get_data(as_text=True)
    assert "ana@uno.com" in bo.get("/usuarios?q=ANA").get_data(as_text=True)
    assert "rejilla-cartas" in bo.get("/usuarios?vista=rejilla").get_data(as_text=True)
    assert bo.get("/usuarios?rol=usuario&orden=email&por_pagina=10&pagina=x").status_code == 200


def test_crear_usuario_muestra_la_clave_temporal_una_vez_y_no_la_audita(bo, monkeypatch):
    entrar(bo)
    creadas = []
    monkeypatch.setattr(kratos, "crear_identidad", lambda email, clave: creadas.append((email, clave)) or "identidad-1")
    tid = db.crear_tenant("Destino")
    r = post(bo, "/usuarios", email="Nuevo@Ejemplo.com", tenant_id=str(tid))
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Nuevo@Ejemplo.com".lower() in html
    email, clave = creadas[0]
    assert email == "nuevo@ejemplo.com" and clave in html and len(clave) >= 12
    assert db.obtener_usuario_por_email("nuevo@ejemplo.com")["tenant_id"] == tid
    assert clave not in bo.get("/usuarios").get_data(as_text=True)          # no se vuelve a mostrar
    assert all(clave not in (r_["detalle"] or "") for r_ in auth.listar_auditoria())  # ni se registra
    post(bo, "/usuarios", email="nuevo@ejemplo.com")
    assert "Ya existe un usuario" in bo.get("/usuarios").get_data(as_text=True)
    post(bo, "/usuarios", email="no-es-un-email")
    assert "email válido" in bo.get("/usuarios").get_data(as_text=True)


def test_crear_usuario_si_falla_la_identidad_no_deja_fila_local(bo, monkeypatch):
    entrar(bo)
    def falla(email, clave):
        raise kratos.ErrorKratos("Kratos caído")
    monkeypatch.setattr(kratos, "crear_identidad", falla)
    post(bo, "/usuarios", email="fallo@ejemplo.com")
    assert db.obtener_usuario_por_email("fallo@ejemplo.com") is None
    assert "Kratos caído" in bo.get("/usuarios").get_data(as_text=True)


def test_asignar_tenant_permisos_y_dispositivos(bo):
    entrar(bo)
    t = db.crear_tenant("Equipo")
    uid = _usuario("persona@ejemplo.com")
    assert bo.get(f"/usuarios/{uid}").status_code == 200
    post(bo, f"/usuarios/{uid}/tenant", tenant_id=str(t))
    assert db.obtener_usuario(uid)["tenant_id"] == t
    post(bo, f"/usuarios/{uid}/tenant", tenant_id="")
    assert db.obtener_usuario(uid)["tenant_id"] is None
    post(bo, f"/usuarios/{uid}/tenant", tenant_id="99999")
    for permiso, campo in (("admin", "rol"), ("gestor", "gestor_fichajes"), ("supervisor", "supervisor_tenant")):
        post(bo, f"/usuarios/{uid}/permiso/{permiso}")
        assert db.obtener_usuario(uid)[campo] in ("admin", 1)
        post(bo, f"/usuarios/{uid}/permiso/{permiso}")
        assert db.obtener_usuario(uid)[campo] in ("usuario", 0)
    assert post(bo, f"/usuarios/{uid}/permiso/superpoder").status_code == 400
    token = db.crear_token_api(uid, "Móvil", "solo_lectura")
    assert db.listar_tokens_api(uid)
    tid_token = db.listar_tokens_api(uid)[0]["id"]
    assert "Solo lectura" in bo.get(f"/usuarios/{uid}").get_data(as_text=True) and token
    post(bo, f"/usuarios/{uid}/dispositivos/{tid_token}/revocar")
    assert db.listar_tokens_api(uid) == []
    assert bo.get("/usuarios/99999").status_code == 404 and post(bo, "/usuarios/99999/permiso/admin").status_code == 404


def test_las_acciones_quedan_en_el_registro_de_actividad(bo):
    entrar(bo)
    tid = db.crear_tenant("Auditada")
    post(bo, f"/tenants/{tid}/activo")
    html = bo.get("/actividad").get_data(as_text=True)
    assert "tenant.suspender" in html and "login" in html and "jorge" in html


def test_admin_cli_crea_y_cambia_contrasena(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "otro.db")
    import importlib.util
    from pathlib import Path
    ruta = Path(__file__).resolve().parent.parent / "scripts" / "crear_admin_backoffice.py"
    spec = importlib.util.spec_from_file_location("crear_admin_bo", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    monkeypatch.setattr("sys.argv", ["x", "Nuevo.Admin", "--nombre", "Nuevo"])
    assert modulo.main() == 0
    salida = capsys.readouterr().out
    clave = re.search(r"Contraseña: (\S+)", salida).group(1)
    assert auth.verificar("nuevo.admin", clave, "1.1.1.1")[0] is not None
    monkeypatch.setattr("sys.argv", ["x", "nuevo.admin", "--cambiar"])
    assert modulo.main() == 0
    assert auth.verificar("nuevo.admin", clave, "1.1.1.1")[0] is None
