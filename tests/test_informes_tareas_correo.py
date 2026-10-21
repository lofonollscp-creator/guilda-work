"""Resumen semanal de tareas por correo (app/informes_tareas_correo.py): opt-in personal, una vez por semana, sin ruido, reintento sin duplicar y mismo alcance que la pantalla."""
from datetime import date

import pytest

from app import db, informes_tareas_correo as itc, notificaciones_email
from tests.conftest import iniciar_sesion_de_prueba

LUNES = date(2026, 10, 19)                      # lunes
MARTES = date(2026, 10, 20)
LUNES_SIGUIENTE = date(2026, 10, 26)


class Buzon:
    def __init__(self, falla=False):
        self.enviados, self.falla = [], falla

    def __call__(self, destino, asunto, plano, html):
        if self.falla:
            raise notificaciones_email.ErrorNotificacionesEmail("SMTP caído")
        self.enviados.append((destino, asunto, plano, html))


def _usuario(mail, tenant):
    uid = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail)
    db.asignar_tenant(uid, tenant)
    return uid


@pytest.fixture
def d(base_de_datos_temporal):
    t = db.crear_tenant("Despacho resumen correo")
    return type("D", (), {"t": t, "ana": _usuario("ana-resumen@ejemplo.com", t), "beto": _usuario("beto-resumen@ejemplo.com", t), "email": "ana-resumen@ejemplo.com"})


def _tarea(uid, asunto, vence):
    return db.crear_tarea_outlook(uid, asunto=asunto, fecha_vencimiento=vence)


def test_sin_activarlo_no_se_manda_nada(d):
    _tarea(d.ana, "Pendiente", "2026-10-21")
    buzon = Buzon()
    assert itc.enviar_pendientes(LUNES, buzon)["enviados"] == 0 and buzon.enviados == []
    assert itc.esta_suscrito(d.ana) is False


def test_quien_se_suscribe_a_media_semana_empieza_el_lunes_siguiente(d):
    _tarea(d.ana, "Pendiente", "2026-10-28")
    assert itc.suscribir(d.ana, True, hoy=MARTES) and itc.esta_suscrito(d.ana)
    buzon = Buzon()
    assert itc.enviar_pendientes(date(2026, 10, 23), buzon)["enviados"] == 0              # el viernes de la misma semana: ya está atendida
    r = itc.enviar_pendientes(LUNES_SIGUIENTE, buzon)
    assert r["enviados"] == 1 and len(buzon.enviados) == 1, r.get("detalle")


def test_el_correo_va_solo_a_su_dueno_con_su_contenido_y_el_enlace_al_informe(d):
    _tarea(d.ana, "Presentar el modelo 303", "2026-10-21")
    itc.suscribir(d.ana, True, hoy=date(2026, 10, 12))
    buzon = Buzon()
    itc.enviar_pendientes(LUNES, buzon)
    destino, asunto, plano, html = buzon.enviados[0]
    assert destino == d.email and "resumen semanal" in asunto.lower()
    assert "Presentar el modelo 303" in plano and "/tareas/informes" in html and "2026-10-21" in plano
    assert "Presentar el modelo 303" in html


def test_una_sola_vez_por_semana_aunque_la_pasada_corra_varios_dias(d):
    _tarea(d.ana, "Pendiente", "2026-10-21")
    itc.suscribir(d.ana, True, hoy=date(2026, 10, 12))
    buzon = Buzon()
    assert itc.enviar_pendientes(LUNES, buzon)["enviados"] == 1
    for dia in (LUNES, MARTES, date(2026, 10, 25)):
        assert itc.enviar_pendientes(dia, buzon)["enviados"] == 0
    assert len(buzon.enviados) == 1
    assert itc.enviar_pendientes(LUNES_SIGUIENTE, buzon)["enviados"] == 1


def test_si_el_lunes_estuvo_parado_sale_el_martes(d):
    _tarea(d.ana, "Pendiente", "2026-10-28")
    itc.suscribir(d.ana, True, hoy=date(2026, 10, 12))
    buzon = Buzon()
    assert itc.enviar_pendientes(MARTES, buzon)["enviados"] == 1


def test_sin_nada_que_contar_no_se_escribe_pero_la_semana_queda_atendida(d):
    itc.suscribir(d.ana, True, hoy=date(2026, 10, 12))
    buzon = Buzon()
    r = itc.enviar_pendientes(LUNES, buzon)
    assert r["vacios"] == 1 and r["enviados"] == 0 and buzon.enviados == []
    _tarea(d.ana, "Nueva", "2026-10-30")                                                  # aparece luego, esa misma semana
    assert itc.enviar_pendientes(MARTES, buzon)["enviados"] == 0                           # no se reabre la semana
    assert itc.enviar_pendientes(LUNES_SIGUIENTE, buzon)["enviados"] == 1


def test_si_el_envio_falla_no_se_marca_y_se_reintenta_sin_duplicar(d):
    _tarea(d.ana, "Pendiente", "2026-10-21")
    itc.suscribir(d.ana, True, hoy=date(2026, 10, 12))
    r = itc.enviar_pendientes(LUNES, Buzon(falla=True))
    assert r["errores"] == 1 and r["enviados"] == 0
    buzon = Buzon()
    assert itc.enviar_pendientes(MARTES, buzon)["enviados"] == 1                           # al día siguiente sale
    assert itc.enviar_pendientes(date(2026, 10, 22), buzon)["enviados"] == 0              # y ya no se repite


def test_un_fallo_con_una_persona_no_corta_a_las_demas(d):
    for u in (d.ana, d.beto):
        _tarea(u, "Pendiente", "2026-10-21")
        itc.suscribir(u, True, hoy=date(2026, 10, 12))
    llamadas = []

    def a_medias(destino, asunto, plano, html):
        llamadas.append(destino)
        if destino == d.email:
            raise notificaciones_email.ErrorNotificacionesEmail("rebota")

    r = itc.enviar_pendientes(LUNES, a_medias)
    assert r["errores"] == 1 and r["enviados"] == 1 and len(llamadas) == 2


def test_desactivar_y_reactivar(d):
    _tarea(d.ana, "Pendiente", "2026-10-21")
    itc.suscribir(d.ana, True, hoy=date(2026, 10, 12))
    itc.suscribir(d.ana, False)
    buzon = Buzon()
    assert itc.enviar_pendientes(LUNES, buzon)["enviados"] == 0 and not itc.esta_suscrito(d.ana)
    itc.suscribir(d.ana, True, hoy=MARTES)                                                 # reactivar a media semana: vuelve a esperar al lunes
    assert itc.enviar_pendientes(date(2026, 10, 23), buzon)["enviados"] == 0
    assert itc.enviar_pendientes(LUNES_SIGUIENTE, buzon)["enviados"] == 1


def test_sin_despacho_no_se_puede_suscribir(base_de_datos_temporal):
    suelto = db.crear_usuario_vinculado_a_kratos("suelto-resumen@ejemplo.com", "k-suelto-resumen")
    assert itc.suscribir(suelto, True) is False and itc.esta_suscrito(suelto) is False


def test_si_la_persona_pierde_el_despacho_la_suscripcion_se_apaga_sola(d):
    itc.suscribir(d.ana, True, hoy=date(2026, 10, 12))
    conn = db.get_connection()
    try:
        conn.execute("UPDATE usuarios SET tenant_id = NULL WHERE id = ?", (d.ana,))
        conn.commit()
    finally:
        conn.close()
    buzon = Buzon()
    r = itc.enviar_pendientes(LUNES, buzon)
    assert r["desactivados"] == 1 and buzon.enviados == [] and not itc.esta_suscrito(d.ana)


def test_sin_correo_saliente_configurado_no_se_toca_a_nadie(d, monkeypatch):
    _tarea(d.ana, "Pendiente", "2026-10-21")
    itc.suscribir(d.ana, True, hoy=date(2026, 10, 12))
    monkeypatch.setattr(notificaciones_email, "configurado", lambda: False)
    r = itc.enviar_pendientes(LUNES)
    assert r["sin_correo_saliente"] is True and r["enviados"] == 0
    buzon = Buzon()
    assert itc.enviar_pendientes(LUNES, buzon)["enviados"] == 1                           # al configurarlo, sigue pendiente


def test_el_resumen_no_incluye_tareas_privadas_de_otros(d):
    _tarea(d.beto, "Privada de Beto", "2026-10-21")
    _tarea(d.ana, "De Ana", "2026-10-21")
    itc.suscribir(d.ana, True, hoy=date(2026, 10, 12))
    buzon = Buzon()
    itc.enviar_pendientes(LUNES, buzon)
    assert "De Ana" in buzon.enviados[0][2] and "Privada de Beto" not in buzon.enviados[0][2] + buzon.enviados[0][3]


def test_el_texto_de_las_tareas_se_escapa_en_el_html(d):
    _tarea(d.ana, "<script>alert(1)</script>", "2026-10-21")
    itc.suscribir(d.ana, True, hoy=date(2026, 10, 12))
    buzon = Buzon()
    itc.enviar_pendientes(LUNES, buzon)
    assert "<script>alert(1)</script>" not in buzon.enviados[0][3]


def test_pantalla_activar_y_desactivar(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "pantalla-resumen@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho pantalla resumen")
    db.asignar_tenant(uid, t)
    html = cliente.get("/tareas/informes").get_data(as_text=True)
    assert "Resumen semanal por correo" in html and "Recibirlo cada lunes" in html
    r = cliente.post("/tareas/informes/resumen-semanal", data={"activar": "1"})
    assert r.status_code == 302 and itc.esta_suscrito(uid)
    html = cliente.get("/tareas/informes?resumen=activado").get_data(as_text=True)
    assert "Dejar de recibirlo" in html and "primer resumen llegará el próximo lunes" in html
    cliente.post("/tareas/informes/resumen-semanal", data={"activar": "0"})
    assert not itc.esta_suscrito(uid)


def test_pantalla_sin_despacho_lo_dice(cliente):
    iniciar_sesion_de_prueba(cliente, "sin-despacho-resumen@ejemplo.com", "contrasena123")
    cliente.post("/tareas/informes/resumen-semanal", data={"activar": "1"})
    assert "no pertenece a ningún despacho" in cliente.get("/tareas/informes?resumen=sin_despacho").get_data(as_text=True)


def test_borrar_el_despacho_borra_las_suscripciones(d):
    itc.suscribir(d.ana, True)
    assert itc.esta_suscrito(d.ana)
    db.borrar_tenant(d.t)
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM informes_tareas_suscripciones WHERE tenant_id = ?", (d.t,)).fetchone()[0] == 0
    finally:
        conn.close()
