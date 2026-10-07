"""Fase 5: segundo factor y caducidad de contraseña del backoffice, vigilancia desde
fuera de la app, auditoría de dependencias, comprobación de migraciones y herramientas
de test."""
import base64
import importlib.util
import json
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import db, salud
from backoffice import auth, cartera, dependencias
from tests.test_backoffice_app import CLAVE, _csrf, bo, entrar  # noqa: F401 -- fixture

RAIZ = Path(__file__).resolve().parent.parent


# --- TOTP ----------------------------------------------------------------------------------

def test_totp_cumple_el_vector_de_la_rfc_6238():
    secreto = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    assert auth.codigo_totp(secreto, 59 // 30) == "287082"
    assert auth.codigo_totp(secreto, 1111111109 // 30) == "081804"
    assert auth.codigo_totp(secreto, 20000000000 // 30) == "353130"


def post(cliente, ruta, **datos):  # noqa: F811 -- como el de test_backoffice_app, pero con el token de /cuenta
    return cliente.post(ruta, data={**datos, "_csrf": _csrf(cliente.get("/cuenta").get_data(as_text=True))})


def _codigo_ahora(secreto, desplazamiento=0):
    return auth.codigo_totp(secreto, auth._paso_actual() + desplazamiento)


def _activar_2fa(cliente):
    post(cliente, "/cuenta/2fa/activar")
    html = cliente.get("/cuenta").get_data(as_text=True)
    secreto = re.search(r'id="clave-totp">([A-Z2-7]+)<', html).group(1)
    post(cliente, "/cuenta/2fa/confirmar", codigo=_codigo_ahora(secreto))
    html = cliente.get("/cuenta").get_data(as_text=True)
    return secreto


def test_activar_2fa_guarda_el_secreto_cifrado_y_da_codigos_de_recuperacion(bo):
    entrar(bo)
    post(bo, "/cuenta/2fa/activar")
    secreto = re.search(r'id="clave-totp">([A-Z2-7]+)<', bo.get("/cuenta").get_data(as_text=True)).group(1)
    assert "no es correcto" in bo.post("/cuenta/2fa/confirmar", data={"codigo": "000000", "_csrf": _csrf(bo.get("/cuenta").get_data(as_text=True))}, follow_redirects=True).get_data(as_text=True)
    post(bo, "/cuenta/2fa/confirmar", codigo=_codigo_ahora(secreto))
    html = bo.get("/cuenta").get_data(as_text=True)
    assert "ACTIVADA" in html and "Códigos de recuperación" in html
    assert len(re.findall(r"\b[0-9a-f]{4}-[0-9a-f]{4}\b", html)) == auth.CODIGOS_RECUPERACION
    assert "Códigos de recuperación" not in bo.get("/cuenta").get_data(as_text=True)  # solo se muestran una vez
    conn = auth.conectar()
    fila = conn.execute("SELECT totp_secreto, codigos_recuperacion FROM admins WHERE usuario = 'jorge'").fetchone()
    conn.close()
    assert secreto not in fila["totp_secreto"] and fila["totp_secreto"].startswith("gAAAA")
    assert all(len(h) == 64 for h in json.loads(fila["codigos_recuperacion"]))


def test_con_2fa_el_acceso_pide_el_codigo_y_no_hay_sesion_antes(bo):
    entrar(bo)
    secreto = _activar_2fa(bo)
    post(bo, "/logout")
    r = entrar(bo)
    assert r.status_code == 302 and "/login/2fa" in r.headers["Location"]
    assert bo.get("/").status_code == 302 and "/login" in bo.get("/").headers["Location"]  # sin sesión todavía
    pagina = bo.get("/login/2fa").get_data(as_text=True)
    mala = bo.post("/login/2fa", data={"codigo": "123456", "_csrf": _csrf(pagina)})
    assert mala.status_code == 401 and "Código incorrecto" in mala.get_data(as_text=True)
    assert bo.get("/").status_code == 302
    buena = bo.post("/login/2fa", data={"codigo": _codigo_ahora(secreto, 1), "_csrf": _csrf(bo.get("/login/2fa").get_data(as_text=True))})
    assert buena.status_code == 302 and bo.get("/").status_code == 200
    assert any(r["accion"] == "login" and "segundo factor" in (r["detalle"] or "") for r in auth.listar_auditoria())


def test_un_codigo_totp_no_se_puede_reutilizar(bo):
    entrar(bo)
    secreto = _activar_2fa(bo)
    codigo = _codigo_ahora(secreto, 1)  # el de la ventana siguiente: aún no usado
    post(bo, "/logout")
    entrar(bo)
    assert bo.post("/login/2fa", data={"codigo": codigo, "_csrf": _csrf(bo.get("/login/2fa").get_data(as_text=True))}).status_code == 302
    post(bo, "/logout")
    entrar(bo)
    repetido = bo.post("/login/2fa", data={"codigo": codigo, "_csrf": _csrf(bo.get("/login/2fa").get_data(as_text=True))})
    assert repetido.status_code == 401


def test_recuperacion_de_un_solo_uso_y_bloqueo_por_intentos(bo):
    admin_id = auth.crear_admin("ana", CLAVE, "Ana")
    secreto = auth.generar_secreto_totp()
    codigos = auth.activar_2fa(admin_id, secreto, auth.codigo_totp(secreto, auth._paso_actual()))
    admin, motivo = auth.verificar_segundo_factor(admin_id, codigos[0], "1.1.1.1")
    assert admin is not None and motivo == "recuperacion"
    assert auth.verificar_segundo_factor(admin_id, codigos[0], "1.1.1.1")[0] is None  # ya gastado
    for _ in range(auth.INTENTOS_MAX_POR_USUARIO):
        auth.verificar_segundo_factor(admin_id, "000000", "2.2.2.2")
    admin, motivo = auth.verificar_segundo_factor(admin_id, _codigo_ahora(secreto, 1), "2.2.2.2")
    assert admin is None and motivo == "bloqueado"  # ni el código bueno entra con el bloqueo puesto


def test_desactivar_2fa_pide_la_contrasena_y_no_en_modo_obligatorio(bo, monkeypatch):
    entrar(bo)
    _activar_2fa(bo)
    post(bo, "/cuenta/2fa/desactivar", actual="otra-cosa-larga-1")
    assert "ACTIVADA" in bo.get("/cuenta").get_data(as_text=True)
    monkeypatch.setenv("BACKOFFICE_2FA_OBLIGATORIO", "1")
    post(bo, "/cuenta/2fa/desactivar", actual=CLAVE)
    assert "ACTIVADA" in bo.get("/cuenta").get_data(as_text=True)
    monkeypatch.delenv("BACKOFFICE_2FA_OBLIGATORIO")
    post(bo, "/cuenta/2fa/desactivar", actual=CLAVE)
    assert "ACTIVADA" not in bo.get("/cuenta").get_data(as_text=True)


def test_modo_obligatorio_manda_a_activar_el_2fa_antes_de_nada(bo, monkeypatch):
    monkeypatch.setenv("BACKOFFICE_2FA_OBLIGATORIO", "1")
    r = entrar(bo)
    assert "/cuenta" in r.headers["Location"]
    assert "/cuenta" in bo.get("/tenants").headers["Location"] and bo.get("/cuenta").status_code == 200
    secreto = _activar_2fa(bo)
    assert bo.get("/tenants").status_code == 200  # cumplido: ya puede navegar


def test_contrasena_caducada_obliga_a_cambiarla(bo, monkeypatch):
    conn = auth.conectar()
    conn.execute("UPDATE admins SET password_cambiada_en = ? WHERE usuario = 'jorge'", ((datetime.now() - timedelta(days=400)).isoformat(),))
    conn.commit()
    conn.close()
    entrar(bo)
    assert "/cuenta" in bo.get("/").headers["Location"]
    assert "ha caducado" in bo.get("/cuenta").get_data(as_text=True)
    mal = post(bo, "/cuenta/clave", actual=CLAVE, nueva="corta", repetir="corta")
    assert bo.get("/").status_code == 302  # sigue bloqueado
    post(bo, "/cuenta/clave", actual=CLAVE, nueva=CLAVE, repetir=CLAVE)  # igual a la actual: se rechaza
    assert bo.get("/").status_code == 302
    post(bo, "/cuenta/clave", actual=CLAVE, nueva="una-clave-nueva-larga-2", repetir="una-clave-nueva-larga-2")
    assert bo.get("/").status_code == 200
    post(bo, "/logout")
    assert entrar(bo, clave="una-clave-nueva-larga-2").status_code == 302
    assert any(r["accion"] == "cuenta.clave" for r in auth.listar_auditoria())


def test_aviso_de_caducidad_proxima_y_sin_caducidad(bo, monkeypatch):
    conn = auth.conectar()
    conn.execute("UPDATE admins SET password_cambiada_en = ? WHERE usuario = 'jorge'", ((datetime.now() - timedelta(days=175)).isoformat(),))
    conn.commit()
    conn.close()
    entrar(bo)
    assert "Cámbiala pronto" in bo.get("/cuenta").get_data(as_text=True)
    monkeypatch.setenv("BACKOFFICE_CADUCIDAD_DIAS", "0")
    assert "no caduca" in bo.get("/cuenta").get_data(as_text=True)


def test_las_acciones_de_cuenta_exigen_sesion_y_csrf(bo):
    for ruta in ("/cuenta/clave", "/cuenta/2fa/activar", "/cuenta/2fa/confirmar", "/cuenta/2fa/desactivar"):
        assert bo.post(ruta, data={}).status_code in (302, 400)
    entrar(bo)
    for ruta in ("/cuenta/clave", "/cuenta/2fa/activar", "/cuenta/2fa/confirmar", "/cuenta/2fa/desactivar"):
        assert bo.post(ruta, data={}).status_code == 400


def test_verificacion_pendiente_caduca(bo, monkeypatch):
    entrar(bo)
    secreto = _activar_2fa(bo)
    post(bo, "/logout")
    entrar(bo)
    reloj = time.time() + auth.PRE2FA_MAX_SEGUNDOS + 5
    monkeypatch.setattr(time, "time", lambda: reloj)
    assert bo.get("/login/2fa").status_code == 302


def test_cli_quitar_2fa(bo):
    admin_id = auth.crear_admin("luis", CLAVE, "Luis")
    secreto = auth.generar_secreto_totp()
    auth.activar_2fa(admin_id, secreto, auth.codigo_totp(secreto, auth._paso_actual()))
    spec = importlib.util.spec_from_file_location("crear_admin_cli", RAIZ / "scripts" / "crear_admin_backoffice.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    import sys
    sys.argv = ["x", "luis", "--quitar-2fa"]
    assert modulo.main() == 0
    assert not auth.obtener_admin(admin_id)["totp_activo"]


# --- vigilancia desde fuera --------------------------------------------------------------------

def test_vigilar_app_avisa_tras_dos_sondas_fallidas_y_una_vez_al_dia(bo, monkeypatch):
    monkeypatch.setattr(salud, "vigilar", lambda ahora=None: [])
    cartera._fallos_sonda = 0
    enviados = []
    envio = lambda asunto, cuerpo: enviados.append(asunto)  # noqa: E731
    ahora = datetime(2026, 10, 7, 12, 0)
    assert cartera.vigilar_app(ahora, sonda=lambda: False, enviar=envio) == [] and enviados == []  # 1.ª: aún no
    assert cartera.vigilar_app(ahora, sonda=lambda: False, enviar=envio) == ["app_caida"] and len(enviados) == 1
    assert cartera.vigilar_app(ahora, sonda=lambda: False, enviar=envio) == [] and len(enviados) == 1  # mismo día
    assert cartera.vigilar_app(ahora, sonda=lambda: True, enviar=envio) == [] and cartera._fallos_sonda == 0
    cartera.vigilar_app(ahora + timedelta(days=1), sonda=lambda: False, enviar=envio)
    cartera.vigilar_app(ahora + timedelta(days=1), sonda=lambda: False, enviar=envio)
    assert len(enviados) == 2


def test_vigilar_app_incluye_los_latidos_atrasados(bo, monkeypatch):
    monkeypatch.setattr(salud, "vigilar", lambda ahora=None: ["latido:correo_sync"])
    cartera._fallos_sonda = 0
    assert cartera.vigilar_app(datetime.now(), sonda=lambda: True) == ["latido:correo_sync"]


def test_todos_los_latidos_del_codigo_tienen_etiqueta_en_el_panel_de_salud():
    """Un hilo con latido sin etiqueta es invisible en Salud y nadie se entera de que se para."""
    usados = set()
    for fichero in ("app/main.py", "serve.py", "backoffice/cartera.py", "scripts/generar_tareas_recurrentes.py", "scripts/generar_vencimientos_fiscales.py"):
        ruta = RAIZ / fichero
        if ruta.exists():
            usados |= set(re.findall(r'registrar_(?:ok|error)\(\s*"([a-z_]+)"', ruta.read_text(encoding="utf-8")))
    assert usados, "no se ha encontrado ningún latido: ¿ha cambiado la forma de registrarlos?"
    assert usados <= set(salud.ETIQUETAS_LATIDOS), f"latidos sin etiqueta: {sorted(usados - set(salud.ETIQUETAS_LATIDOS))}"


# --- dependencias -------------------------------------------------------------------------------

def test_imagenes_sin_fijar(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  a:\n    image: nextcloud:latest\n  b:\n    image: postgres:16-alpine\n  c:\n    image: ghcr.io/x/y:unstable\n"
        "  d:\n    image: foo/bar\n  e:\n    image: openproject/openproject:${TAG:-15}\n"
    )
    (tmp_path / "docker-compose.test.yml").write_text("services:\n  t:\n    image: oryd/kratos:latest\n")
    nombres = {i["imagen"] for i in dependencias.imagenes_sin_fijar(tmp_path)}
    assert nombres == {"nextcloud:latest", "ghcr.io/x/y:unstable", "foo/bar"}


def test_consulta_de_vulnerabilidades_con_osv_simulado():
    paquetes = [("flask", "1.0"), ("waitress", "3.0.2")]
    peticiones = []

    def post(ruta, cuerpo):
        peticiones.append(cuerpo)
        return {"results": [{"vulns": [{"id": "GHSA-1"}, {"id": "PYSEC-2"}]}, {}]}

    def get(ruta):
        return {"summary": "Fallo grave en Flask", "affected": [{"ranges": [{"events": [{"introduced": "0"}, {"fixed": "1.0.1"}]}]}]}
    afectados, error = dependencias.consultar_vulnerabilidades(paquetes, post=post, get=get)
    assert error is None and len(afectados) == 1
    assert afectados[0]["paquete"] == "flask" and afectados[0]["ids"] == ["GHSA-1", "PYSEC-2"] and afectados[0]["arreglado_en"] == "1.0.1"
    # a OSV solo viajan nombre, ecosistema y versión
    assert peticiones[0]["queries"][0] == {"package": {"name": "flask", "ecosystem": "PyPI"}, "version": "1.0"}


def test_osv_caido_no_rompe_y_deja_el_error(bo):
    def roto(ruta, cuerpo):
        raise OSError("sin red")
    r = dependencias.auditar(post=roto, get=roto)
    assert r["vulnerables"] == [] and "osv.dev" in r["error"]
    assert dependencias.ultima()["error"] == r["error"]


def test_auditoria_semanal_una_vez_por_semana_y_desactivable(bo, monkeypatch):
    llamadas = []
    falso = lambda ruta, cuerpo: llamadas.append(1) or {"results": [{}] * len(cuerpo["queries"])}  # noqa: E731
    lunes = datetime(2026, 10, 5, 10, 0)
    assert dependencias.auditar_si_toca(lunes, post=falso, get=falso) is True
    assert dependencias.auditar_si_toca(lunes + timedelta(days=2), post=falso, get=falso) is False  # misma semana
    assert dependencias.auditar_si_toca(lunes + timedelta(days=7), post=falso, get=falso) is True
    monkeypatch.setenv("BACKOFFICE_AUDITORIA_DEPENDENCIAS", "0")
    assert dependencias.auditar_si_toca(lunes + timedelta(days=30), post=falso, get=falso) is False


def test_pagina_de_dependencias_y_aviso_en_el_resumen(bo, monkeypatch):
    entrar(bo)
    assert "Todavía no se ha hecho ninguna comprobación" in bo.get("/dependencias").get_data(as_text=True)
    monkeypatch.setattr(dependencias, "_post", lambda ruta, cuerpo: {"results": [{"vulns": [{"id": "GHSA-9"}]}] + [{}] * (len(cuerpo["queries"]) - 1)})
    monkeypatch.setattr(dependencias, "_get", lambda ruta: {"summary": "Grave"})
    monkeypatch.setattr(dependencias, "consultar_vulnerabilidades", lambda p, post=dependencias._post, get=dependencias._get: ([{"paquete": "flask", "version": "1", "ids": ["GHSA-9"], "resumen": "Grave"}], None))
    post(bo, "/dependencias/comprobar")
    html = bo.get("/dependencias").get_data(as_text=True)
    assert "GHSA-9" in html and "Paquetes afectados" in html
    assert "DEPENDENCIAS CON VULNERABILIDADES: flask 1" in cartera.texto_resumen(cartera.construir_resumen())


# --- comprobación de migraciones -----------------------------------------------------------------

def _script_migraciones():
    spec = importlib.util.spec_from_file_location("comprobar_migraciones", RAIZ / "scripts" / "comprobar_migraciones.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_comprobar_migraciones_ok_no_toca_la_base_original(tmp_path):
    origen = tmp_path / "real.db"
    shutil_copia = sqlite3.connect(db.DB_PATH)
    destino = sqlite3.connect(origen)
    shutil_copia.backup(destino)
    destino.close()
    shutil_copia.close()
    antes = origen.read_bytes()
    modulo = _script_migraciones()
    ruta_real = db.DB_PATH
    try:
        assert modulo.comprobar(origen, RAIZ) == []
    finally:
        db.DB_PATH = ruta_real
    assert origen.read_bytes() == antes


def test_comprobar_migraciones_detecta_un_init_db_que_falla_o_pierde_filas(tmp_path, monkeypatch):
    origen = tmp_path / "real.db"
    conn = sqlite3.connect(db.DB_PATH)
    destino = sqlite3.connect(origen)
    conn.backup(destino)
    destino.close()
    conn.close()
    modulo = _script_migraciones()
    ruta_real = db.DB_PATH
    original = db.init_db
    try:
        monkeypatch.setattr(db, "init_db", lambda: (_ for _ in ()).throw(RuntimeError("columna inexistente")))
        assert "init_db() falla" in modulo.comprobar(origen, RAIZ)[0]

        def perder_filas():
            c = sqlite3.connect(db.DB_PATH)
            c.execute("DELETE FROM usuarios")
            c.commit()
            c.close()
        monkeypatch.setattr(db, "init_db", perder_filas)
        assert any("ha perdido filas" in p for p in modulo.comprobar(origen, RAIZ))
    finally:
        db.DB_PATH = ruta_real
        monkeypatch.setattr(db, "init_db", original)
    assert "No existe" in modulo.comprobar(tmp_path / "no-existe.db", RAIZ)[0]


# --- herramientas de test y despliegue --------------------------------------------------------------

def test_los_scripts_de_prueba_y_despliegue_son_validos():
    for nombre in ("probar.sh", "desplegar.sh"):
        ruta = RAIZ / "scripts" / nombre
        assert subprocess.run(["bash", "-n", str(ruta)], capture_output=True).returncode == 0, nombre
    assert (RAIZ / "scripts" / "probar.sh").stat().st_mode & 0o111
    desplegar = (RAIZ / "scripts" / "desplegar.sh").read_text()
    assert desplegar.index("comprobar_migraciones.py") < desplegar.index("git pull --ff-only")  # antes de tocar nada
    probar = (RAIZ / "scripts" / "probar.sh").read_text()
    assert "trap 'rm -rf" in probar and "--rapida" in probar
