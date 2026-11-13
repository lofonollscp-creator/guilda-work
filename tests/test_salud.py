"""Bloque 8: latidos, panel de salud del backoffice y vigilante diario."""
import os
from datetime import datetime, timedelta

import pytest

from app import db, notificaciones_email, salud
from tests.conftest import iniciar_sesion_de_prueba

AHORA = datetime(2026, 6, 10, 12, 0)


def _por_clave(items):
    return {i["clave"]: i for i in items}


@pytest.fixture
def backups_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "BACKUPS_DIR", tmp_path)
    return tmp_path


def _copia(carpeta, edad: timedelta, ahora=AHORA):
    f = carpeta / "registro_2026-06-01.db"
    f.write_bytes(b"x" * 2048)
    t = (ahora - edad).timestamp()
    os.utime(f, (t, t))
    return f


# --- latidos ----------------------------------------------------------------

def test_registrar_latido_ok_y_error_y_limite_de_frecuencia():
    salud.registrar_ok("avisos_fichaje", 900, "bien")
    fila = db.listar_latidos()["avisos_fichaje"]
    assert fila["ultimo_ok"] and fila["detalle"] == "bien" and fila["intervalo_segundos"] == 900
    salud.registrar_error("avisos_fichaje", 900, "se rompió")
    fila = db.listar_latidos()["avisos_fichaje"]
    assert fila["ultimo_error"] and fila["detalle"] == "se rompió"
    # la cola de envíos limita la escritura a una por minuto
    salud._ultimo_latido_escrito.pop("correo_envios", None)
    salud.registrar_ok("correo_envios", 10, "uno", minimo_segundos=60)
    salud.registrar_ok("correo_envios", 10, "dos", minimo_segundos=60)
    assert db.listar_latidos()["correo_envios"]["detalle"] == "uno"


def test_estado_de_un_latido_verde_ambar_rojo_gris_y_error():
    def fila(ok=None, error=None, intervalo=3600, detalle=None):
        return {"ultimo_ok": ok.isoformat() if ok else None, "ultimo_error": error.isoformat() if error else None,
                "intervalo_segundos": intervalo, "detalle": detalle}
    est = lambda f: salud._estado_latido("avisos_fichaje", f, AHORA)["estado"]  # noqa: E731
    assert est(None) == salud.GRIS and est(fila()) == salud.GRIS
    assert est(fila(ok=AHORA - timedelta(minutes=30))) == salud.VERDE
    assert est(fila(ok=AHORA - timedelta(hours=3))) == salud.AMBAR      # 3 h > 2,5 intervalos
    assert est(fila(ok=AHORA - timedelta(hours=10))) == salud.ROJO
    assert est(fila(ok=AHORA - timedelta(minutes=5), error=AHORA, detalle="boom")) == salud.ROJO
    assert est(fila(ok=AHORA, error=AHORA - timedelta(hours=1))) == salud.VERDE  # error antiguo, ya recuperado


# --- comprobaciones ---------------------------------------------------------

def test_backup_verde_ambar_rojo_y_sin_copias(backups_tmp):
    assert salud._estado_backup(AHORA)["estado"] == salud.ROJO
    _copia(backups_tmp, timedelta(hours=5))
    assert salud._estado_backup(AHORA)["estado"] == salud.VERDE
    _copia(backups_tmp, timedelta(days=3))
    assert salud._estado_backup(AHORA)["estado"] == salud.AMBAR
    _copia(backups_tmp, timedelta(days=40))
    item = salud._estado_backup(AHORA)
    assert item["estado"] == salud.ROJO and "40 d" in item["detalle"]


def test_correo_por_cuenta_con_error_y_sincronizacion_atrasada(monkeypatch):
    uid = db.crear_usuario_vinculado_a_kratos("b8-correo@ejemplo.com", "kratos-b8-correo")
    ok = db.crear_cuenta_correo(uid, "Buena", "imap", "h", 993, "a@x.com")
    vieja = db.crear_cuenta_correo(uid, "Vieja", "imap", "h", 993, "b@x.com")
    rota = db.crear_cuenta_correo(uid, "Rota", "imap", "h", 993, "c@x.com")
    nueva = db.crear_cuenta_correo(uid, "Nueva", "imap", "h", 993, "d@x.com")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE correo_cuentas SET ultima_sincronizacion = ? WHERE id = ?", ((AHORA - timedelta(minutes=3)).isoformat(), ok))
        conn.execute("UPDATE correo_cuentas SET ultima_sincronizacion = ? WHERE id = ?", ((AHORA - timedelta(days=2)).isoformat(), vieja))
        conn.execute("UPDATE correo_cuentas SET ultimo_error_sincronizacion = 'Contraseña caducada', ultimo_error_sincronizacion_en = ? WHERE id = ?",
                     ((AHORA - timedelta(hours=12)).isoformat(), rota))
        conn.commit()
    finally:
        conn.close()
    items = _por_clave(salud._estado_correo(AHORA))
    assert items[f"correo:{ok}"]["estado"] == salud.VERDE
    assert items[f"correo:{vieja}"]["estado"] == salud.ROJO
    assert items[f"correo:{rota}"]["estado"] == salud.ROJO and "Contraseña caducada" in items[f"correo:{rota}"]["detalle"]
    assert items[f"correo:{nueva}"]["estado"] == salud.GRIS


def test_webhooks_envios_atascados_y_disco(monkeypatch):
    tenant = db.crear_tenant("Salud webhooks")
    propietario = db.crear_usuario_vinculado_a_kratos("b8-wh@ejemplo.com", "kratos-b8-wh")
    wid = db.crear_webhook(propietario, tenant, "https://ejemplo.com/h", ["nota.creada"])["id"]
    conn = db.get_connection()
    try:
        for i in range(10):
            conn.execute("INSERT INTO webhooks_entregas (webhook_id, evento, estado_http, intento_num, entregado_en, error) VALUES (?, 'nota.creada', 500, 1, ?, 'x')",
                         (wid, (AHORA - timedelta(hours=1)).isoformat()))
        conn.execute("INSERT INTO webhooks_entregas (webhook_id, evento, estado_http, intento_num, entregado_en) VALUES (?, 'nota.creada', 200, 1, ?)",
                     (wid, (AHORA - timedelta(hours=1)).isoformat()))
        conn.execute("INSERT INTO webhooks_entregas (webhook_id, evento, estado_http, intento_num, entregado_en, error) VALUES (?, 'nota.creada', 500, 1, ?, 'viejo')",
                     (wid, (AHORA - timedelta(days=3)).isoformat()))
        conn.commit()
    finally:
        conn.close()
    assert salud._estado_webhooks(AHORA)["estado"] == salud.ROJO and "10 intento" in salud._estado_webhooks(AHORA)["detalle"]

    uid = db.crear_usuario_vinculado_a_kratos("b8-env@ejemplo.com", "kratos-b8-env")
    cuenta = db.crear_cuenta_correo(uid, "T", "imap", "h", 993, "e@x.com", smtp_host="s", smtp_puerto=587)
    db.encolar_envio_correo(uid, cuenta, "a@b.com", "", "", "x", "<p>x</p>", None, [], (AHORA - timedelta(minutes=30)).isoformat())
    envios = _por_clave(salud._estado_envios(AHORA))
    assert envios["envios_atascados"]["estado"] == salud.ROJO and envios["envios_fallidos"]["estado"] == salud.VERDE

    from collections import namedtuple
    Uso = namedtuple("Uso", "total used free")
    for libre, esperado in ((50, salud.VERDE), (25, salud.VERDE), (15, salud.AMBAR), (8, salud.ROJO), (2, salud.ROJO)):
        monkeypatch.setattr(salud.shutil, "disk_usage", lambda p, l=libre: Uso(100 * 1024**3, 0, l * 1024**3))
        assert salud._estado_disco()["estado"] == esperado


def test_un_fallo_en_una_comprobacion_no_rompe_el_panel(monkeypatch, backups_tmp):
    def roto(*a, **k):
        raise RuntimeError("disco ilegible")
    monkeypatch.setattr(salud, "_estado_disco", roto)
    items = _por_clave(salud.panel(AHORA))
    assert items["disco"]["estado"] == salud.GRIS and "No se pudo comprobar" in items["disco"]["detalle"]
    assert "backup" in items and "latido:correo_sync" in items and "bd" in items


def test_peor_estado():
    assert salud.peor_estado([]) == salud.VERDE
    assert salud.peor_estado([{"estado": "verde"}, {"estado": "ambar"}]) == salud.AMBAR
    assert salud.peor_estado([{"estado": "gris"}, {"estado": "rojo"}, {"estado": "ambar"}]) == salud.ROJO


# --- vigilante --------------------------------------------------------------

def test_vigilante_avisa_una_vez_al_dia_por_motivo(monkeypatch, backups_tmp):
    enviados = []
    monkeypatch.setattr(notificaciones_email, "enviar_alerta_interna", lambda asunto, cuerpo: enviados.append((asunto, cuerpo)))
    monkeypatch.setattr(salud, "_estado_disco", lambda: salud._item("Servidor", "disco", "Disco", salud.VERDE, "ok"))
    # backup inexistente = rojo
    primeras = salud.vigilar(AHORA)
    assert "backup" in primeras and len(enviados) == 1
    assert "Última copia de seguridad" in enviados[0][1] and "panel Salud del backoffice" in enviados[0][1]
    assert salud.vigilar(AHORA + timedelta(hours=3)) == [] and len(enviados) == 1  # mismo día: nada nuevo
    # al día siguiente vuelve a avisar del mismo motivo
    assert "backup" in salud.vigilar(AHORA + timedelta(days=1)) and len(enviados) == 2
    # un motivo NUEVO el mismo día sí se avisa, sin repetir el viejo
    _copia(backups_tmp, timedelta(hours=1), AHORA + timedelta(days=1))
    salud.registrar_error("avisos_fichaje", 900, "boom")
    nuevos = salud.vigilar(AHORA + timedelta(days=1, hours=1))
    assert nuevos == ["latido:avisos_fichaje"] and len(enviados) == 3


def test_vigilante_sin_smtp_no_marca_el_aviso_y_reintenta(monkeypatch, backups_tmp):
    def sin_destino(asunto, cuerpo):
        raise notificaciones_email.ErrorNotificacionesEmail("ALERTAS_ADMIN_EMAIL no está configurada.")
    monkeypatch.setattr(notificaciones_email, "enviar_alerta_interna", sin_destino)
    assert salud.vigilar(AHORA) == []
    enviados = []
    monkeypatch.setattr(notificaciones_email, "enviar_alerta_interna", lambda a, c: enviados.append(a))
    assert "backup" in salud.vigilar(AHORA + timedelta(minutes=10)) and len(enviados) == 1


def test_solo_ambar_o_gris_no_avisa(monkeypatch, backups_tmp):
    enviados = []
    monkeypatch.setattr(notificaciones_email, "enviar_alerta_interna", lambda a, c: enviados.append(a))
    monkeypatch.setattr(salud, "panel", lambda ahora=None: [salud._item("g", "x", "X", salud.AMBAR, "d"), salud._item("g", "y", "Y", salud.GRIS, "d")])
    assert salud.vigilar(AHORA) == [] and enviados == []


# --- página del backoffice --------------------------------------------------



def test_script_de_tareas_recurrentes_deja_su_latido(monkeypatch):
    import importlib.util
    from pathlib import Path
    ruta = Path(__file__).resolve().parent.parent / "scripts" / "generar_tareas_recurrentes.py"
    spec = importlib.util.spec_from_file_location("gen_rec", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    modulo.main()
    assert db.listar_latidos()["tareas_recurrentes"]["ultimo_ok"]


def _encolar(t, n, estado="pendiente", hace_min=0, terminado=False):
    from app import ia_trabajos
    ahora = datetime.now()
    conn = db.get_connection()
    for i in range(n):
        conn.execute("INSERT INTO ia_trabajos (tenant_id, tipo, referencia, lote, estado, creado_en, terminado_en) VALUES (?, 'factura', ?, 'L', ?, ?, ?)",
                     (t, i, estado, (ahora - timedelta(minutes=hace_min)).isoformat(timespec="seconds"), ahora.isoformat(timespec="seconds") if terminado else None))
    conn.commit(); conn.close()


def test_la_cola_de_ia_se_pone_ambar_y_roja_si_nadie_coge_los_trabajos():
    t = db.crear_tenant("Salud cola IA")
    ahora = datetime.now()
    assert salud._estado_cola_ia(ahora)["estado"] == salud.VERDE and "Sin trabajos" in salud._estado_cola_ia(ahora)["detalle"]
    _encolar(t, 2, hace_min=5)
    assert salud._estado_cola_ia(ahora)["estado"] == salud.VERDE                      # esperando poco: normal
    _encolar(t, 1, hace_min=20)
    assert salud._estado_cola_ia(ahora)["estado"] == salud.AMBAR
    _encolar(t, 1, hace_min=90)
    i = salud._estado_cola_ia(ahora)
    assert i["estado"] == salud.ROJO and "4 pendiente(s)" in i["detalle"] and i["valor"] >= 90


def test_la_cola_de_ia_avisa_si_falla_mas_de_la_mitad():
    t = db.crear_tenant("Salud cola IA errores")
    _encolar(t, 3, estado="error", terminado=True)
    _encolar(t, 1, estado="hecha", terminado=True)
    i = salud._estado_cola_ia(datetime.now())
    assert i["estado"] == salud.AMBAR and "1 hechas y 3 con error" in i["detalle"]


def test_el_panel_incluye_la_cola_de_ia():
    assert any(i["clave"] == "cola_ia" for i in salud.panel(datetime.now()))


def test_el_panel_avisa_si_kratos_deja_de_ofrecer_passkeys(monkeypatch):
    from app import kratos
    def flujo(con_passkey):
        nodos = [{"attributes": {"name": "identifier"}}] + ([{"attributes": {"name": "passkey_login"}}] if con_passkey else [])
        return lambda url, **kw: (200, {"ui": {"nodes": nodos}}, {})
    for respuesta, esperado in ((flujo(True), "verde"), (flujo(False), "ambar"), (lambda url, **kw: (502, {}, {}), "ambar")):
        salud._PASSKEYS_CACHE.update(hasta=0.0, ofrece=None)
        monkeypatch.setattr(kratos, "_peticion", respuesta)
        assert salud._estado_passkeys()["estado"] == esperado
    salud._PASSKEYS_CACHE.update(hasta=0.0, ofrece=None)


def test_dependencias_con_vulnerabilidades_en_el_panel(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(db, "BACKUPS_DIR", tmp_path)
    assert salud._estado_dependencias(AHORA)["estado"] == salud.GRIS
    ruta = tmp_path / "cve_estado.json"

    def escribir(fecha, vulnerables):
        ruta.write_text(json.dumps({"fecha": fecha.isoformat(), "vulnerables": vulnerables}), encoding="utf-8")
    escribir(AHORA - timedelta(days=2), [])
    assert salud._estado_dependencias(AHORA)["estado"] == salud.VERDE
    escribir(AHORA - timedelta(days=2), [{"paquete": "pillow", "version": "12.3.0", "ids": ["CVE-1"], "corregida": ["13.0.0"]}])
    r = salud._estado_dependencias(AHORA)
    assert r["estado"] == salud.AMBAR and "pillow 12.3.0 → 13.0.0" in r["detalle"]
    escribir(AHORA - timedelta(days=30), [])
    assert salud._estado_dependencias(AHORA)["estado"] == salud.AMBAR and "temporizador" in salud._estado_dependencias(AHORA)["detalle"]


def test_la_tendencia_del_disco_estima_los_dias_que_quedan(tmp_path):
    from datetime import datetime, timedelta
    from app import salud
    ruta = tmp_path / "t.json"
    inicio = datetime(2026, 11, 1)
    gb = 1024 ** 3
    assert salud._tendencia_disco(20 * gb, inicio, ruta) is None                           # un solo dato: no se puede saber
    salud._tendencia_disco(18 * gb, inicio + timedelta(days=1), ruta)
    dias = salud._tendencia_disco(16 * gb, inicio + timedelta(days=2), ruta)                # 2 GB al día, quedan 16 GB
    assert dias == 8
    assert salud._tendencia_disco(16 * gb, inicio + timedelta(days=2), ruta) == 8           # el mismo día no duplica la muestra
