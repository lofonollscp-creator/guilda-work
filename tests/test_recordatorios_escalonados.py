"""Recordatorios al cliente configurables: días antes y después, texto propio y aviso al equipo."""
from datetime import datetime, timedelta

import pytest

from app import db, notificaciones, notificaciones_email, portal_recordatorios
from tests.conftest import iniciar_sesion_de_prueba

HOY = datetime(2026, 4, 13, 9, 0)


def _dia(n):
    return (HOY + timedelta(days=n)).strftime("%Y-%m-%d")


@pytest.fixture
def smtp(monkeypatch):
    enviados = []
    monkeypatch.setattr(notificaciones_email, "configurado", lambda: True)
    monkeypatch.setattr(notificaciones_email, "_enviar", lambda d, a, c: enviados.append((d, a, c)))
    monkeypatch.setenv("GUILDA_URL_PUBLICA", "https://work.ejemplo.com")
    return enviados


@pytest.fixture
def avisos(monkeypatch):
    registro = []
    monkeypatch.setattr(notificaciones, "crear_y_enviar", lambda uid, tipo, titulo, cuerpo, url=None, datos=None: registro.append((uid, tipo, titulo, cuerpo, url)))
    return registro


def _despacho(email="cliente@ejemplo.com", nombre="Panadería"):
    tenant = db.crear_tenant(f"Gestoria {nombre} {email}")
    return tenant, db.crear_cliente_fiscal(tenant, nombre, email=email)


def test_configuracion_por_defecto_es_la_de_siempre():
    tenant, _ = _despacho()
    assert db.obtener_config_recordatorios(tenant) == {"dias_antes": [7, 2], "dias_despues": [], "avisar_equipo": False, "asunto": "", "cuerpo": ""}


def test_guardar_valida_y_normaliza():
    tenant, _ = _despacho()
    c = db.guardar_config_recordatorios(tenant, "2, 14 7;7", "7 2", True, "  Asunto  ", " Cuerpo ")
    assert c == {"dias_antes": [14, 7, 2], "dias_despues": [2, 7], "avisar_equipo": True, "asunto": "Asunto", "cuerpo": "Cuerpo"}
    for antes, despues, mensaje in (("x", "", "no es un número"), ("61", "", "no es un número"), ("-1", "", "no es un número"), ("1,2,3,4,5,6,7", "", "Como máximo 6"),
                                    ("7", "0", "no es un número"), ("7", "31", "no es un número"), ("7", "1 2 3 4 5", "Como máximo 4")):
        with pytest.raises(ValueError, match=mensaje):
            db.guardar_config_recordatorios(tenant, antes, despues, False)
    with pytest.raises(ValueError, match="asunto y el cuerpo"):
        db.guardar_config_recordatorios(tenant, "7", "", False, "solo asunto", "")
    assert db.obtener_config_recordatorios(tenant)["dias_antes"] == [14, 7, 2]                # lo inválido no pisa lo guardado
    db.guardar_config_recordatorios(tenant, "", "", False)                                    # sin avisos
    assert db.obtener_config_recordatorios(tenant)["dias_antes"] == []


def test_avisos_en_los_dias_elegidos_y_cada_despacho_los_suyos(smtp):
    t1, c1 = _despacho("uno@ejemplo.com", "Uno")
    t2, c2 = _despacho("dos@ejemplo.com", "Dos")
    db.guardar_config_recordatorios(t1, "14, 3", "", False)
    for t, c in ((t1, c1), (t2, c2)):
        for n in (14, 7, 3, 2):
            db.crear_vencimiento_fiscal(t, c, f"M{n}", "2026-T1", _dia(n))
    assert portal_recordatorios.procesar_recordatorios(HOY) == 4                               # t1: 14 y 3; t2 (por defecto): 7 y 2
    por_destino = {}
    for d, a, _ in smtp:
        por_destino.setdefault(d, []).append(a)
    assert sorted(por_destino["uno@ejemplo.com"]) == ["Recordatorio: el M14 vence dentro de 14 días", "Recordatorio: el M3 vence dentro de 3 días"]
    assert sorted(por_destino["dos@ejemplo.com"]) == ["Recordatorio: el M2 vence dentro de 2 días", "Recordatorio: el M7 vence dentro de 7 días"]
    assert portal_recordatorios.procesar_recordatorios(HOY) == 0


def test_aviso_el_mismo_dia_y_tras_el_vencimiento(smtp):
    tenant, cid = _despacho()
    db.guardar_config_recordatorios(tenant, "0", "2, 7", False)
    db.crear_vencimiento_fiscal(tenant, cid, "HOY", "2026-T1", _dia(0))
    db.crear_vencimiento_fiscal(tenant, cid, "HACE2", "2026-T1", _dia(-2))
    db.crear_vencimiento_fiscal(tenant, cid, "HACE7", "2026-T1", _dia(-7))
    db.crear_vencimiento_fiscal(tenant, cid, "HACE5", "2026-T1", _dia(-5))
    hecho = db.crear_vencimiento_fiscal(tenant, cid, "HECHO", "2026-T1", _dia(-2))
    db.marcar_presentado_vencimiento_fiscal(tenant, hecho)
    assert portal_recordatorios.procesar_recordatorios(HOY) == 3
    asuntos = sorted(a for _, a, _ in smtp)
    assert asuntos == ["Recordatorio: el HACE2 venció hace 2 días", "Recordatorio: el HACE7 venció hace 7 días", "Recordatorio: el HOY vence hoy"]
    cuerpo = next(c for _, a, c in smtp if "HACE2" in a)
    assert "venció hace 2 días" in cuerpo and "seguimos pendientes" in cuerpo
    assert portal_recordatorios.procesar_recordatorios(HOY) == 0                                # los negativos también quedan registrados
    assert portal_recordatorios.procesar_recordatorios(HOY + timedelta(days=1)) == 0


def test_texto_propio_con_marcas(smtp):
    tenant, cid = _despacho("pan@ejemplo.com", "Panadería")
    db.guardar_config_recordatorios(
        tenant, "3", "", False, "{cliente}: faltan {dias} días para el {modelo}",
        "Hola {cliente}, el {modelo} ({periodo}) vence {cuando}, el {fecha_limite}. Necesitamos: {documento}. {enlace} {desconocida} {{x}} {__class__}\n— {despacho}",
    )
    vid = db.crear_vencimiento_fiscal(tenant, cid, "303", "2T", _dia(3))
    conn = db.get_connection()
    conn.execute("UPDATE vencimientos_fiscales SET documento_solicitado = 'los extractos' WHERE id = ?", (vid,))
    conn.commit()
    conn.close()
    assert portal_recordatorios.procesar_recordatorios(HOY) == 1
    destino, asunto, cuerpo = smtp[0]
    assert asunto == "Panadería: faltan 3 días para el 303"
    assert cuerpo == ("Hola Panadería, el 303 (2T) vence dentro de 3 días, el 2026-04-16. Necesitamos: los extractos. "
                      "https://work.ejemplo.com/portal/entrar {desconocida} {{x}} {__class__}\n— Gestoria Panadería pan@ejemplo.com")


def test_aviso_al_equipo_si_no_entrega_lo_pedido(smtp, avisos):
    tenant, cid = _despacho()
    db.guardar_config_recordatorios(tenant, "7, 2", "", True)
    responsable = db.crear_usuario("resp@ejemplo.com", "contrasena123")
    supervisor = db.crear_usuario("sup@ejemplo.com", "contrasena123")
    for u in (responsable, supervisor):
        db.asignar_tenant(u, tenant)
    conn = db.get_connection()
    conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (supervisor,))
    conn.commit()
    conn.close()

    def vencimiento(modelo, dias, pedido="los extractos", responsable_id=None):
        vid = db.crear_vencimiento_fiscal(tenant, cid, modelo, "2T", _dia(dias), usuario_id=responsable_id)
        conn = db.get_connection()
        conn.execute("UPDATE vencimientos_fiscales SET documento_solicitado = ? WHERE id = ?", (pedido, vid))
        conn.commit()
        conn.close()
        return vid
    v_resp = vencimiento("A", 2, responsable_id=responsable)
    v_sin = vencimiento("B", 2, responsable_id=None)                          # sin responsable: lo reciben los supervisores
    vencimiento("C", 2, pedido="")                                            # no se pidió nada: no hay de qué avisar
    v_entregado = vencimiento("D", 2, responsable_id=responsable)
    db.subir_documento_vencimiento(v_entregado, "doc.pdf", "application/pdf", b"%PDF")        # el cliente sí entregó
    vencimiento("E", 7, responsable_id=responsable)                           # a 7 días: aún no es el último aviso
    portal_recordatorios.procesar_recordatorios(HOY)
    destinos = sorted((uid, url) for uid, tipo, titulo, cuerpo, url in avisos if tipo == "portal_sin_documentos")
    assert destinos == sorted([(responsable, f"/fiscal/vencimientos/{v_resp}/editar"), (supervisor, f"/fiscal/vencimientos/{v_sin}/editar")])
    texto = next(a for a in avisos if a[0] == responsable)
    assert texto[2] == "Panadería no ha entregado la documentación" and "los extractos" in texto[3] and "(2T)" in texto[3]
    portal_recordatorios.procesar_recordatorios(HOY)
    assert len([a for a in avisos if a[1] == "portal_sin_documentos"]) == 2                    # una sola vez


def test_el_aviso_al_equipo_funciona_sin_correo_ni_email_del_cliente(monkeypatch, avisos):
    monkeypatch.setattr(notificaciones_email, "configurado", lambda: False)
    tenant, cid = _despacho(email=None)
    db.guardar_config_recordatorios(tenant, "2", "", True)
    sup = db.crear_usuario("sup2@ejemplo.com", "contrasena123")
    db.asignar_tenant(sup, tenant)
    conn = db.get_connection()
    conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (sup,))
    conn.commit()
    conn.close()
    vid = db.crear_vencimiento_fiscal(tenant, cid, "303", "2T", _dia(2))
    conn = db.get_connection()
    conn.execute("UPDATE vencimientos_fiscales SET documento_solicitado = 'algo' WHERE id = ?", (vid,))
    conn.commit()
    conn.close()
    assert portal_recordatorios.procesar_recordatorios(HOY) == 0
    assert [(a[0], a[1]) for a in avisos] == [(sup, "portal_sin_documentos")]
    # sin la casilla no avisa
    tenant2, cid2 = _despacho(email=None, nombre="Otro")
    db.guardar_config_recordatorios(tenant2, "2", "", False)
    v2 = db.crear_vencimiento_fiscal(tenant2, cid2, "303", "2T", _dia(2))
    conn = db.get_connection()
    conn.execute("UPDATE vencimientos_fiscales SET documento_solicitado = 'algo' WHERE id = ?", (v2,))
    conn.commit()
    conn.close()
    portal_recordatorios.procesar_recordatorios(HOY)
    assert len(avisos) == 1


def test_pantalla_de_configuracion(cliente, smtp):
    uid = iniciar_sesion_de_prueba(cliente, "rec-1@ejemplo.com", "contrasena123")
    tenant = db.crear_tenant("Gestoria pantalla")
    db.asignar_tenant(uid, tenant)
    html = cliente.get("/fiscal/recordatorios").get_data(as_text=True)
    assert 'value="7, 2"' in html and "{cuando}" in html and "Recordatorios" in cliente.get("/fiscal/vencimientos").get_data(as_text=True)
    r = cliente.post("/fiscal/recordatorios", data={"dias_antes": "10, 3", "dias_despues": "5", "avisar_equipo": "on", "asunto": "Aviso {modelo}", "cuerpo": "Vence {cuando}: {documento}"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Guardado." in html and "Aviso 303" in html and "extractos bancarios de junio" in html and "dentro de 3 días" in html   # vista previa
    assert db.obtener_config_recordatorios(tenant) == {"dias_antes": [10, 3], "dias_despues": [5], "avisar_equipo": True, "asunto": "Aviso {modelo}", "cuerpo": "Vence {cuando}: {documento}"}
    malo = cliente.post("/fiscal/recordatorios", data={"dias_antes": "abc"}).get_data(as_text=True)
    assert "no es un número de días válido" in malo and db.obtener_config_recordatorios(tenant)["dias_antes"] == [10, 3]


def test_la_pantalla_exige_despacho(cliente):
    iniciar_sesion_de_prueba(cliente, "rec-3@ejemplo.com", "contrasena123")
    assert cliente.get("/fiscal/recordatorios").status_code in (403, 404)
