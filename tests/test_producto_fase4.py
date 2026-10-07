"""Fase 4 de producto: recordatorios sin duplicados con varios workers, Mi día con
tareas compartidas, informe de carga del equipo, API de la app móvil (ámbito de
tareas y resumen semanal de fichaje), catálogos de traducción y accesibilidad."""
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

from app import db, notificaciones, recordatorios_tareas
from tests.conftest import iniciar_sesion_de_prueba

RAIZ = Path(__file__).resolve().parent.parent


def _despacho(*emails):
    tenant = db.crear_tenant(f"Despacho F4 {emails[0]}")
    ids = []
    for email in emails:
        uid = db.crear_usuario(email, "contrasena123")
        db.asignar_tenant(uid, tenant)
        ids.append(uid)
    return tenant, ids


# --- recordatorios: un solo aviso aunque haya varios workers -----------------------------

def test_reservar_recordatorio_solo_lo_gana_uno():
    _, (ana,) = _despacho("f4-rec1@ejemplo.com")
    tarea = db.crear_tarea_outlook(ana, "Llamar al cliente")
    rid = db.anadir_recordatorio_tarea(ana, tarea, (datetime.now() - timedelta(minutes=1)).isoformat(timespec="minutes"))
    assert db.reservar_recordatorio_tarea(rid) is True
    assert db.reservar_recordatorio_tarea(rid) is False


def test_varios_workers_procesando_a_la_vez_envian_el_aviso_una_sola_vez(monkeypatch):
    _, (ana,) = _despacho("f4-rec2@ejemplo.com")
    ids = []
    for n in range(5):
        tarea = db.crear_tarea_outlook(ana, f"Tarea {n}")
        ids.append(db.anadir_recordatorio_tarea(ana, tarea, (datetime.now() - timedelta(minutes=1)).isoformat(timespec="minutes")))
    enviados = []
    candado = threading.Lock()

    def falso(usuario_id, tipo, titulo, cuerpo, **kw):
        with candado:
            enviados.append(cuerpo)
    monkeypatch.setattr(notificaciones, "crear_y_enviar", falso)

    puerta = threading.Barrier(4)
    resultados = []

    def worker():
        puerta.wait()
        resultados.append(recordatorios_tareas.procesar_recordatorios())
    hilos = [threading.Thread(target=worker) for _ in range(4)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert len(enviados) == 5 and sorted(enviados) == sorted(f"Tarea {n}" for n in range(5))
    assert sum(resultados) == 5
    assert recordatorios_tareas.procesar_recordatorios() == 0


# --- Mi día con tareas compartidas -----------------------------------------------------------

def test_mi_dia_incluye_compartidas_conmigo_sin_fecha():
    _, (ana, luis) = _despacho("f4-dia1@ejemplo.com", "f4-dia2@ejemplo.com")
    hoy = datetime.now().strftime("%Y-%m-%d")
    con_fecha = db.crear_tarea_outlook(ana, "Vence hoy", fecha_vencimiento=hoy)
    sin_fecha = db.crear_tarea_outlook(ana, "Revisar balance")
    privada = db.crear_tarea_outlook(ana, "Privada de Ana")
    db.compartir_tarea_outlook(ana, con_fecha, luis, "colabora")
    db.compartir_tarea_outlook(ana, sin_fecha, luis, "observa")
    seccion = db.tareas_para_hoy(luis)
    assert [t["asunto"] for t in seccion["hoy"]] == ["Vence hoy"]
    assert [t["asunto"] for t in seccion["compartidas"]] == ["Revisar balance"]
    todas = [t["asunto"] for lista in seccion.values() for t in lista]
    assert "Privada de Ana" not in todas
    assert db.tareas_para_hoy(ana)["compartidas"] == []  # las suyas no cuentan como compartidas


def test_pagina_mi_dia_muestra_la_seccion_de_compartidas(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "f4-dia3@ejemplo.com", "contrasena123")
    tenant = db.crear_tenant("Despacho F4 dia")
    db.asignar_tenant(uid, tenant)
    ana = db.crear_usuario("f4-dia4@ejemplo.com", "contrasena123")
    db.asignar_tenant(ana, tenant)
    t = db.crear_tarea_outlook(ana, "Preparar la renta")
    db.compartir_tarea_outlook(ana, t, uid, "colabora")
    assert "Preparar la renta" in cliente.get("/tareas/hoy").get_data(as_text=True)


# --- informe de carga del equipo --------------------------------------------------------------

def test_exportar_carga_del_equipo_csv(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "f4-carga1@ejemplo.com", "contrasena123")
    tenant = db.crear_tenant("Despacho F4 carga")
    db.asignar_tenant(uid, tenant)
    otro = db.crear_usuario("f4-carga2@ejemplo.com", "contrasena123")
    db.asignar_tenant(otro, tenant)
    db.guardar_perfil_usuario(otro, "=HYPERLINK(\"http://malo\")") if hasattr(db, "guardar_perfil_usuario") else None
    ayer = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    t = db.crear_tarea_outlook(uid, "Atrasada", fecha_vencimiento=ayer)
    db.asignar_tarea_outlook(uid, t, otro)
    db.crear_tarea_outlook(uid, "Normal")
    r = cliente.get("/tareas/carga.csv")
    assert r.status_code == 200 and r.mimetype == "text/csv" and "guilda_work_carga_equipo_" in r.headers["Content-Disposition"]
    texto = r.get_data(as_text=True)
    assert texto.startswith("﻿") and ";" in texto.splitlines()[0]
    assert len(texto.strip().splitlines()) == 3  # cabecera + dos personas
    assert "=HYPERLINK" not in texto.replace("'=HYPERLINK", "")  # nunca una fórmula suelta


def test_carga_csv_requiere_sesion(cliente):
    r = cliente.get("/tareas/carga.csv")
    assert r.status_code in (302, 401)


# --- API para la app móvil --------------------------------------------------------------------

def _registrar(cliente, email):
    resp = cliente.post("/api/v1/auth/registro", json={"email": email, "contrasena": "contrasena123"})
    assert resp.status_code == 201
    return resp.get_json()["data"]["token"], resp.get_json()["data"].get("usuario_id")


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_api_tareas_por_ambito_con_rol(cliente):
    token, _ = _registrar(cliente, "f4-api1@ejemplo.com")
    yo = db.obtener_usuario_por_email("f4-api1@ejemplo.com")["id"]
    tenant = db.crear_tenant("Despacho F4 api")
    db.asignar_tenant(yo, tenant)
    ana = db.crear_usuario("f4-api2@ejemplo.com", "contrasena123")
    db.asignar_tenant(ana, tenant)
    propia = db.crear_tarea_outlook(yo, "Mía")
    asignada = db.crear_tarea_outlook(ana, "Asignada a mí")
    db.asignar_tarea_outlook(ana, asignada, yo)
    compartida = db.crear_tarea_outlook(ana, "Compartida conmigo")
    db.compartir_tarea_outlook(ana, compartida, yo, "colabora")
    db.crear_tarea_outlook(ana, "Privada de Ana")

    def pedir(ambito=None):
        url = "/api/v1/tareas-outlook" + (f"?ambito={ambito}" if ambito else "")
        return cliente.get(url, headers=_h(token))
    assert [t["asunto"] for t in pedir().get_json()["data"]] == ["Mía"]  # por defecto, como siempre (y sin campo rol)
    assert "rol" not in pedir().get_json()["data"][0]
    roles = {t["asunto"]: t["rol"] for t in pedir("todas").get_json()["data"]}
    assert roles == {"Mía": "dueno", "Asignada a mí": "asignada", "Compartida conmigo": "compartida"}
    assert [t["asunto"] for t in pedir("asignadas").get_json()["data"]] == ["Asignada a mí"]
    assert [t["asunto"] for t in pedir("compartidas").get_json()["data"]] == ["Compartida conmigo"]
    assert pedir("inventado").status_code == 400
    assert pedir("todas").headers["X-Total-Count"] == "3"


def test_api_resumen_semanal_de_fichaje(cliente):
    token, _ = _registrar(cliente, "f4-api3@ejemplo.com")
    r = cliente.get("/api/v1/fichaje/resumen-semana", headers=_h(token))
    assert r.status_code == 200
    d = r.get_json()["data"]
    assert len(d["dias"]) == 7 and sum(1 for x in d["dias"] if x["hoy"]) == 1
    assert d["contratados"] is None and d["porcentaje"] is None and d["en_curso"] is False
    assert cliente.get("/api/v1/fichaje/resumen-semana").status_code == 401


# --- traducciones completas ---------------------------------------------------------------------

def test_los_catalogos_ca_en_fr_cubren_todos_los_textos():
    """Cada texto marcado con _() debe estar traducido a catalán, inglés y francés.
    Si falla: pybabel extract -F babel.cfg -o /tmp/m.pot . y añade las traducciones a
    translations/<idioma>/LC_MESSAGES/messages.po (sin 'fuzzy'); luego pybabel compile."""
    from babel.messages.extract import extract_from_dir
    from babel.messages.frontend import parse_mapping
    from babel.messages.pofile import read_po

    with open(RAIZ / "babel.cfg") as f:
        metodos, opciones = parse_mapping(f)
    esperados = set()
    for _fichero, _linea, mensaje, _com, _ctx in extract_from_dir(
        str(RAIZ), method_map=metodos, options_map=opciones, keywords={"_": None, "gettext": None, "ngettext": (1, 2), "_l": None, "lazy_gettext": None},
        directory_filter=lambda d: not any(p in Path(d).parts for p in (".venv", "node_modules", "tests", "mobile", "backoffice", "data")),
    ):
        esperados.add(mensaje if isinstance(mensaje, str) else mensaje[0])
    for idioma in ("ca", "en", "fr"):
        with open(RAIZ / "translations" / idioma / "LC_MESSAGES" / "messages.po", "rb") as f:
            cat = read_po(f, locale=idioma)
        faltan = []
        for ident in esperados:
            if not ident:
                continue
            m = cat.get(ident)
            if m is None or m.fuzzy or not m.string or (isinstance(m.string, (tuple, list)) and not any(m.string)):
                faltan.append(ident)
        assert not faltan, f"{idioma}: {len(faltan)} textos sin traducir, p. ej. {faltan[:5]}"


# --- accesibilidad ----------------------------------------------------------------------------------

def _luminancia(hexa: str) -> float:
    r, g, b = (int(hexa.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contraste(a: str, b: str) -> float:
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_contraste_del_tema_claro_y_foco_visible():
    css = (RAIZ / "app" / "static" / "style.css").read_text(encoding="utf-8")
    raiz = css[css.index(":root {"):css.index("}", css.index(":root {"))]
    valor = lambda nombre: re.search(rf"--{nombre}:\s*(#[0-9a-fA-F]{{6}})", raiz).group(1)  # noqa: E731
    fondo = valor("bg")
    for nombre in ("text", "text-muted", "primary-text", "danger-text", "success-text", "warning-text"):
        assert _contraste(valor(nombre), "#ffffff") >= 4.5 and _contraste(valor(nombre), fondo) >= 4.5, nombre
    assert _contraste(valor("focus-ring"), "#ffffff") >= 3 and _contraste(valor("focus-ring"), fondo) >= 3
    assert ":focus-visible { outline: 2px solid var(--focus-ring)" in css
    assert "(pointer: coarse)" in css and "min-height: 44px" in css
    # el texto semántico ya no usa los colores claros pensados para fondos
    assert not re.search(r"(?<![-\w])color: var\(--(danger|success|warning)\)", css)
