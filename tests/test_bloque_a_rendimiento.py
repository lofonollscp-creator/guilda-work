"""Bloque A de rendimiento: las optimizaciones dan EXACTAMENTE los mismos resultados que
antes (equivalencias) y no vuelven atrás (presupuestos de consultas, sin escrituras al leer,
asistente flotante bajo demanda, listas largas recortadas)."""
import re
from datetime import datetime, timedelta

from app import db
from tests.conftest import iniciar_sesion_de_prueba


def _despacho(*emails):
    tenant = db.crear_tenant(f"Despacho perf {emails[0]}")
    ids = []
    for email in emails:
        uid = db.crear_usuario(email, "contrasena123")
        db.asignar_tenant(uid, tenant)
        ids.append(uid)
    return tenant, ids


def _fecha(dias):
    return (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d")


# --- dependencias -------------------------------------------------------------------------

def test_bloqueos_cuenta_solo_previas_abiertas_y_no_borradas():
    _, (ana,) = _despacho("a-dep@ejemplo.com")
    a, b, c, d = (db.crear_tarea_outlook(ana, n) for n in "abcd")
    for previa in (a, b, c):
        assert db.anadir_dependencia_tarea(ana, d, previa) if hasattr(db, "anadir_dependencia_tarea") else True
    if not hasattr(db, "anadir_dependencia_tarea"):
        conn = db.get_connection()
        conn.executemany("INSERT INTO tareas_dependencias (tarea_id, depende_de_id) VALUES (?, ?)", [(d, a), (d, b), (d, c)])
        conn.commit()
        conn.close()
    assert db.bloqueos_de_tareas([a, b, c, d]) == {d: 3}
    db.cambiar_estado_tarea_outlook(ana, a, "completada")
    db.eliminar_tarea_outlook(ana, b)
    assert db.bloqueos_de_tareas([d, a]) == {d: 1}
    db.cambiar_estado_tarea_outlook(ana, c, "completada")
    assert db.bloqueos_de_tareas([d]) == {} and db.tarea_bloqueada(d) is False
    assert db.bloqueos_de_tareas([]) == {}


def test_bloqueos_con_mas_de_500_tareas_en_la_consulta():
    _, (ana,) = _despacho("a-dep2@ejemplo.com")
    ids = [db.crear_tarea_outlook(ana, f"t{i}") for i in range(620)]
    conn = db.get_connection()
    conn.executemany("INSERT INTO tareas_dependencias (tarea_id, depende_de_id) VALUES (?, ?)", [(ids[i], ids[0]) for i in range(1, 620)])
    conn.commit()
    conn.close()
    resultado = db.bloqueos_de_tareas(ids)
    assert len(resultado) == 619 and set(resultado.values()) == {1}


# --- Mi día: el contador de la barra coincide con la lista ------------------------------------

def test_contar_mi_dia_coincide_con_tareas_para_hoy():
    _, (yo, otro) = _despacho("a-dia1@ejemplo.com", "a-dia2@ejemplo.com")
    db.crear_tarea_outlook(yo, "vencida propia", fecha_vencimiento=_fecha(-3))
    db.crear_tarea_outlook(yo, "de hoy propia", fecha_vencimiento=_fecha(0))
    db.crear_tarea_outlook(yo, "futura", fecha_vencimiento=_fecha(5))
    db.crear_tarea_outlook(yo, "sin fecha")
    hecha = db.crear_tarea_outlook(yo, "completada vencida", fecha_vencimiento=_fecha(-2))
    db.cambiar_estado_tarea_outlook(yo, hecha, "completada")
    borrada = db.crear_tarea_outlook(yo, "borrada", fecha_vencimiento=_fecha(-1))
    db.eliminar_tarea_outlook(yo, borrada)
    ajena = db.crear_tarea_outlook(otro, "asignada a mí", fecha_vencimiento=_fecha(-1))
    db.asignar_tarea_outlook(otro, ajena, yo)
    compartida = db.crear_tarea_outlook(otro, "compartida de hoy", fecha_vencimiento=_fecha(0))
    db.compartir_tarea_outlook(otro, compartida, yo, "observa")
    db.crear_tarea_outlook(otro, "privada de otro", fecha_vencimiento=_fecha(-9))
    for uid in (yo, otro):
        secciones = db.tareas_para_hoy(uid)
        assert db.contar_mi_dia(uid) == (len(secciones["vencidas"]), len(secciones["hoy"])), uid
    assert db.contar_mi_dia(yo) == (2, 2)


# --- no leídos ------------------------------------------------------------------------------------

def test_no_leidos_por_cuenta_carpeta_y_total_usan_el_indice_parcial():
    _, (yo, otro) = _despacho("a-nl1@ejemplo.com", "a-nl2@ejemplo.com")
    c1 = db.crear_cuenta_correo(yo, "A", "imap", "h", 993, "a@x.com")
    c2 = db.crear_cuenta_correo(yo, "B", "imap", "h", 993, "b@x.com")
    ajena = db.crear_cuenta_correo(otro, "C", "imap", "h", 993, "c@x.com")
    for cuenta, carpeta, n in ((c1, "INBOX", 3), (c1, "Archivo", 1), (c2, "INBOX", 2), (ajena, "INBOX", 7)):
        for i in range(n):
            m = db.guardar_mensaje_correo(cuenta_id=cuenta, uid=f"{carpeta}{i}", asunto="x", remitente="r@x.com", destinatarios="a@x.com",
                                          fecha="2026-03-10T10:00:00", cuerpo_texto="c", cuerpo_html=None, carpeta=carpeta)
    # uno leído de c1/INBOX no debe contar
    leido = db.guardar_mensaje_correo(cuenta_id=c1, uid="leido", asunto="x", remitente="r@x.com", destinatarios="a@x.com",
                                      fecha="2026-03-10T10:00:00", cuerpo_texto="c", cuerpo_html=None)
    db.marcar_leido_mensaje_correo(leido, True)
    assert db.contar_no_leidos_por_cuenta_y_carpeta(yo) == {c1: {"INBOX": 3, "Archivo": 1}, c2: {"INBOX": 2}}
    assert db.contar_no_leidos_total_correo(yo) == 6 and db.contar_no_leidos_total_correo(otro) == 7
    conn = db.get_connection()
    plan = " ".join(f[3] for f in conn.execute(
        "EXPLAIN QUERY PLAN SELECT cuenta_id, carpeta, COUNT(*) FROM correo_mensajes WHERE leido = 0 "
        "AND cuenta_id IN (SELECT id FROM correo_cuentas WHERE usuario_id = ?) GROUP BY cuenta_id, carpeta", (yo,)))
    conn.close()
    assert "idx_correo_no_leidos" in plan and "COVERING" in plan


# --- sin escrituras al leer -------------------------------------------------------------------------

def _sentencias(monkeypatch):
    registro = []
    original = db.get_connection

    def con_traza():
        c = original()
        c.set_trace_callback(lambda s: registro.append(s))
        return c
    monkeypatch.setattr(db, "get_connection", con_traza)
    return registro


def test_las_paginas_no_escriben_en_la_base_tras_la_primera_visita(cliente, monkeypatch):
    uid = iniciar_sesion_de_prueba(cliente, "a-esc@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, db.crear_tenant("Despacho esc"))
    for ruta in ("/tareas/", "/fiscal/vencimientos", "/notas"):
        cliente.get(ruta)  # primera visita: puede crear perfil, datos de fichaje y la marca de acceso
    registro = _sentencias(monkeypatch)
    for ruta in ("/tareas/", "/fiscal/vencimientos", "/notas", "/tareas/hoy"):
        assert cliente.get(ruta).status_code == 200
    escrituras = [s for s in registro if re.match(r"\s*(INSERT|UPDATE|DELETE|REPLACE)", s, re.I)]
    assert escrituras == []


def test_presupuesto_de_consultas_por_pantalla(cliente, monkeypatch):
    """Cada pantalla pedía 22-30 consultas aunque estuviera vacía. Tope holgado para que no vuelva a crecer sin querer."""
    uid = iniciar_sesion_de_prueba(cliente, "a-pres@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, db.crear_tenant("Despacho presupuesto"))
    cuenta = db.crear_cuenta_correo(uid, "Trabajo", "imap", "h", 993, "p@x.com")
    for ruta in ("/", "/tareas/", "/tareas/hoy", "/tareas/tablero", "/notas", f"/correo/?cuenta_id={cuenta}", "/fiscal/vencimientos"):
        cliente.get(ruta)
    registro = _sentencias(monkeypatch)
    tope = {"/": 30, "/tareas/": 24, "/tareas/hoy": 24, "/tareas/tablero": 24, "/notas": 24, f"/correo/?cuenta_id={cuenta}": 30, "/fiscal/vencimientos": 20}
    for ruta, maximo in tope.items():
        registro.clear()
        cliente.get(ruta)
        consultas = [s for s in registro if re.match(r"\s*(SELECT|INSERT|UPDATE|DELETE)", s, re.I)]
        assert len(consultas) <= maximo, f"{ruta}: {len(consultas)} consultas (tope {maximo})"


# --- asistente flotante bajo demanda ----------------------------------------------------------------------

def test_el_historial_del_asistente_no_viaja_en_cada_pagina_y_se_pide_al_abrir(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "a-ia@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, db.crear_tenant("Despacho ia"))
    db.agregar_mensaje_ia(uid, "user", "pregunta-muy-reconocible-123")
    db.agregar_mensaje_ia(uid, "assistant", "respuesta-muy-reconocible-456")
    for ruta in ("/tareas/", "/notas", "/fiscal/vencimientos"):
        html = cliente.get(ruta).get_data(as_text=True)
        assert "pregunta-muy-reconocible-123" not in html and 'id="ia-panel-flotante"' in html and 'data-url="/ia/panel"' in html
        assert 'id="ia-chat-flotante"' not in html
    panel = cliente.get("/ia/panel")
    assert panel.status_code == 200
    html = panel.get_data(as_text=True)
    assert "pregunta-muy-reconocible-123" in html and "respuesta-muy-reconocible-456" in html and 'id="ia-chat-flotante"' in html
    assert "ia-atajo" in html  # atajos incluidos
    assert "pregunta-muy-reconocible-123" in cliente.get("/").get_data(as_text=True)  # el inicio conserva su chat


def test_panel_del_asistente_exige_sesion(cliente):
    assert cliente.get("/ia/panel").status_code in (302, 401)


# --- listas largas recortadas ----------------------------------------------------------------------------------

def test_mi_dia_recorta_cada_seccion_y_ofrece_ver_el_resto(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "a-lim1@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, db.crear_tenant("Despacho lim"))
    for i in range(40):
        db.crear_tarea_outlook(uid, f"vencida-{i:02d}", fecha_vencimiento=_fecha(-1 - i))
    html = cliente.get("/tareas/hoy").get_data(as_text=True)
    assert len(re.findall(r"vencida-\d\d", html)) == 30
    assert "Ver las 10 restantes" in html and ">40<" in html  # el contador sigue siendo el real
    completa = cliente.get("/tareas/hoy?todas=vencidas").get_data(as_text=True)
    assert len(re.findall(r"vencida-\d\d", completa)) == 40 and "restantes" not in completa


def test_tablero_recorta_cada_columna(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "a-lim2@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, db.crear_tenant("Despacho lim2"))
    for i in range(30):
        db.crear_tarea_outlook(uid, f"tarjeta-{i:02d}")
    html = cliente.get("/tareas/tablero").get_data(as_text=True)
    assert len(re.findall(r"tarjeta-\d\d", html)) == 25 and "Mostrar las 5 restantes" in html
    assert len(re.findall(r"tarjeta-\d\d", cliente.get("/tareas/tablero?mas=no_iniciada").get_data(as_text=True))) == 30


def test_el_borrado_con_deshacer_lleva_los_textos_una_sola_vez_por_lista(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "a-del@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, db.crear_tenant("Despacho del"))
    for i in range(6):
        db.crear_tarea_outlook(uid, f"fila-{i}")
    html = cliente.get("/tareas/").get_data(as_text=True)
    assert html.count("data-eliminar-defecto") == 1 and html.count("data-mensaje-ok=") == 1
    assert html.count("data-eliminar-deshacer") == 6 and html.count("data-restaurar-url=") == 6
    js = cliente.get("/static/toasts.js").get_data(as_text=True)
    assert "data-eliminar-defecto" in js


# --- caché de URLs estáticas ----------------------------------------------------------------------------------------

def test_url_estatica_versionada_se_calcula_una_vez(cliente, monkeypatch):
    import os
    from app import main

    main._URL_ESTATICA.clear()
    llamadas = []
    real = os.path.getmtime
    monkeypatch.setattr(os.path, "getmtime", lambda p: llamadas.append(p) or real(p))
    uid = iniciar_sesion_de_prueba(cliente, "a-url@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, db.crear_tenant("Despacho url"))
    for i in range(8):
        db.crear_tarea_outlook(uid, f"u{i}")
    llamadas.clear()
    html = cliente.get("/tareas/").get_data(as_text=True)
    assert re.search(r'iconos\.svg\?v=\d+#icono-check', html) or re.search(r'iconos\.svg\?v=\d+#icono-', html)
    sprites = [p for p in llamadas if p.endswith("iconos.svg")]
    assert len(sprites) <= 1, f"{len(sprites)} stat() del mismo fichero en una página"
