"""Calendario de plazos del cliente para su agenda (L8)."""
from datetime import date, datetime, timedelta

import pytest

from app import db, portal_calendario as cal, portal_peticiones as pp, portal_subida_rapida
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures


def _vencimiento(t, u, c, modelo, periodo, dias, estado="pendiente"):
    limite = (date.today() + timedelta(days=dias)).isoformat()
    conn = db.get_connection()
    cur = conn.execute("INSERT INTO vencimientos_fiscales (tenant_id, cliente_fiscal_id, usuario_id, modelo, periodo, fecha_limite, estado, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (t, c, u, modelo, periodo, limite, estado, db.now_iso()))
    conn.commit(); conn.close()
    return cur.lastrowid, limite


def _lineas(texto):
    """El .ics con los pliegues deshechos."""
    return texto.replace("\r\n ", "").split("\r\n")


def test_el_calendario_lleva_los_vencimientos_sin_presentar_y_las_peticiones_con_fecha():
    t, u, c = _despacho("Cal contenido")
    vid, limite = _vencimiento(t, u, c, "303", "3T 2026", 10)
    _vencimiento(t, u, c, "111", "3T 2026", 5, estado="presentado")
    _vencimiento(t, u, c, "390", "2026", 900)
    pp.crear(_ficha(c), "Extracto, de enero; y más", fecha_limite=(date.today() + timedelta(days=4)).isoformat(), por=u)
    pp.crear(_ficha(c), "Sin fecha", por=u)
    texto = cal.contenido(_ficha(c))
    assert texto.startswith("BEGIN:VCALENDAR\r\n") and texto.endswith("END:VCALENDAR\r\n") and "\n" not in texto.replace("\r\n", "")
    lineas = _lineas(texto)
    assert f"UID:venc-{vid}@guildawork" in lineas and f"DTSTART;VALUE=DATE:{limite.replace('-', '')}" in lineas and "SUMMARY:Modelo 303 · 3T 2026" in lineas
    assert not any("Modelo 111" in l for l in lineas), "lo presentado no sale"
    assert not any("Modelo 390" in l for l in lineas), "lo que vence dentro de más de un año no sale"
    assert "SUMMARY:Subir: Extracto\\, de enero\; y más" in lineas and not any("Sin fecha" in l for l in lineas)
    assert lineas.count("BEGIN:VEVENT") == 2 and "TRIGGER:-P2D" in lineas


def test_las_lineas_largas_se_pliegan_a_75_octetos_sin_romper_caracteres():
    t, u, c = _despacho("Cal pliegue")
    pp.crear(_ficha(c), "ñ" * 100, fecha_limite=(date.today() + timedelta(days=4)).isoformat(), por=u)
    texto = cal.contenido(_ficha(c))
    assert all(len(l.encode()) <= 75 for l in texto.split("\r\n"))
    assert "SUMMARY:Subir: " + "ñ" * 100 in _lineas(texto)


def test_el_token_es_estable_por_cliente_y_cambia_al_renovar_el_enlace_de_subida():
    t, u, c = _despacho("Cal token")
    ficha = _ficha(c)
    a = cal.token_de(ficha)
    assert a == cal.token_de(ficha) and len(a) == 32 and cal.cliente_por_token(a, c)["id"] == c
    _t2, _u2, c2 = _despacho("Cal otro", cliente_email="otro@ejemplo.com", cliente_nombre="Otro SL")
    assert cal.token_de(_ficha(c2)) != a and cal.cliente_por_token(a, c2) is None
    portal_subida_rapida.renovar(ficha)
    assert cal.token_de(ficha) != a and cal.cliente_por_token(a, c) is None
    assert cal.cliente_por_token("xyz", c) is None and cal.cliente_por_token(a.upper(), c) is None and cal.cliente_por_token(a, 99999) is None


def test_la_ruta_publica_sirve_el_ics_solo_con_el_enlace_correcto(cliente):
    t, u, c = _despacho("Cal ruta")
    _vencimiento(t, u, c, "303", "3T 2026", 10)
    token = cal.token_de(_ficha(c))
    r = cliente.get(f"/portal/calendario/{c}/{token}.ics")
    assert r.status_code == 200 and r.mimetype == "text/calendar" and b"Modelo 303" in r.data and "private" in r.headers["Cache-Control"]
    assert cliente.get(f"/portal/calendario/{c}/{'0' * 32}.ics").status_code == 404
    assert cliente.get(f"/portal/calendario/{c + 1}/{token}.ics").status_code == 404


def test_mi_cuenta_ofrece_el_enlace_y_el_de_consulta_no(cliente, correo):
    from app import portal_personas
    t, u, c = _despacho("Cal cuenta")
    _entrar(cliente, c, "titular@ejemplo.com")
    pagina = _html(cliente, "/portal/cuenta")
    token = cal.token_de(_ficha(c))
    assert "Tus plazos en tu agenda" in pagina and f"webcal://work.ejemplo.com/portal/calendario/{c}/{token}.ics" in pagina and f"https://work.ejemplo.com/portal/calendario/{c}/{token}.ics" in pagina
    portal_personas.anadir(_ficha(c), "mira@ejemplo.com", "Mira", "consulta", por=u)
    cliente.post("/portal/salir")
    _entrar(cliente, c, "mira@ejemplo.com")
    assert "Tus plazos en tu agenda" not in _html(cliente, "/portal/cuenta")
