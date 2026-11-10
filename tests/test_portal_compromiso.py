"""El compromiso del despacho con el cliente (K2 plazo, K3 ausencias) y el «visto» de los mensajes (K4)."""
from datetime import date, datetime, timedelta

import pytest

from app import db, portal_bandeja as pb, portal_buzon, portal_compromiso as pcm, portal_conversaciones as pc
from tests.test_portal_bandeja import _escenario


def test_el_plazo_se_guarda_y_se_valida(cliente):
    t, u, c, f1, c2, f2 = _escenario()
    assert pcm.ajustes(t)["plazo_respuesta_dias"] == 0
    assert pcm.fijar(t, plazo_respuesta_dias="2", mostrar_ausencias=True)["plazo_respuesta_dias"] == 2
    assert pcm.ajustes(t)["mostrar_ausencias"] == 1 and pcm.ajustes(t)["voz_cliente"] == 0
    for malo in ("11", "-1", "dos"):
        with pytest.raises(ValueError):
            pcm.fijar(t, plazo_respuesta_dias=malo)
    assert pcm.fijar(t, desconocida=1)["plazo_respuesta_dias"] == 2                         # lo que no es un ajuste se ignora


def test_los_dias_habiles_no_cuentan_el_fin_de_semana():
    viernes = datetime(2026, 11, 6, 10, 0)
    assert pcm.dias_habiles(viernes.isoformat(), datetime(2026, 11, 9, 9, 0)) == 1           # del viernes al lunes: un día laborable
    assert pcm.dias_habiles(viernes.isoformat(), datetime(2026, 11, 11, 9, 0)) == 3
    assert pcm.fuera_de_plazo(viernes.isoformat(), 2, datetime(2026, 11, 11, 9, 0)) and not pcm.fuera_de_plazo(viernes.isoformat(), 3, datetime(2026, 11, 11, 9, 0))
    assert not pcm.fuera_de_plazo(viernes.isoformat(), 0, datetime(2026, 12, 1)) and pcm.dias_habiles("no es fecha") == 0


def test_la_bandeja_marca_lo_que_supera_el_plazo(cliente):
    t, u, c, f1, c2, f2 = _escenario()
    pc.iniciar(f1, "Una duda", "Hola", "cliente", "uno@ejemplo.com")
    antes = (datetime.now() - timedelta(days=14)).isoformat(timespec="seconds")
    conn = db.get_connection(); conn.execute("UPDATE portal_conversaciones_mensajes SET creado_en = ? WHERE tenant_id = ?", (antes, t)); conn.commit(); conn.close()
    with cliente.application.test_request_context():
        assert pb.listar(t, u)[0]["fuera_de_plazo"] is False                                  # sin plazo configurado no se marca nada
        pcm.fijar(t, plazo_respuesta_dias=3)
        assert pb.listar(t, u)[0]["fuera_de_plazo"] is True


def test_la_ausencia_solo_se_cuenta_si_el_despacho_quiere_y_sin_motivo(cliente):
    t, u, c, f1, c2, f2 = _escenario()
    conn = db.get_connection(); conn.execute("UPDATE clientes_fiscales SET responsable_id = ? WHERE id = ?", (u, c)); conn.commit(); conn.close()
    hoy = date.today()
    conn = db.get_connection()
    conn.execute("INSERT INTO ausencias (tenant_id, usuario_id, tipo, desde, hasta, dias, motivo, estado, creada_en) VALUES (?, ?, 'baja', ?, ?, 3, 'Secreto médico', 'aprobada', ?)",
                 (t, u, hoy.isoformat(), (hoy + timedelta(days=5)).isoformat(), db.now_iso()))
    conn.commit(); conn.close()
    ficha = db.obtener_cliente_fiscal_por_id(c)
    assert pcm.ausencia_del_responsable(ficha) is None                                       # apagado por defecto
    pcm.fijar(t, mostrar_ausencias=True)
    a = pcm.ausencia_del_responsable(ficha)
    assert a and a["hasta"] == (hoy + timedelta(days=5)).isoformat() and "Secreto" not in str(a)
    assert pcm.ausencia_del_responsable(ficha, hoy + timedelta(days=9)) is None             # ya ha vuelto


def test_el_visto_aparece_cuando_el_equipo_abre_el_ultimo_mensaje_del_cliente(cliente):
    t, u, c, f1, c2, f2 = _escenario()
    cid = pc.iniciar(f1, "Una duda", "Hola", "cliente", "uno@ejemplo.com")
    with cliente.application.test_request_context():
        h = portal_buzon.conversaciones(f1)[0]
        assert h["ultimo_autor"] == "cliente" and h["visto"] is False
        pc.marcar_leida(f1, cid, "despacho")
        assert portal_buzon.conversaciones(f1)[0]["visto"] is True


def test_tiempos_dan_cifra_solo_con_casos_suficientes(cliente):
    from app import portal_peticiones as pp, portal_tiempos
    t, u, c, f1, c2, f2 = _escenario()
    hoy = datetime.now()
    ids = [pp.crear(f1, f"Doc {i}", por=u) for i in range(3)]                              # tres peticiones: subidas a los 2 días y cerradas a los 4
    conn = db.get_connection()
    for pid in ids:
        conn.execute("UPDATE portal_peticiones SET creado_en = ?, enviada_en = ?, revisada_en = ?, estado = 'revisada' WHERE id = ?",
                     ((hoy - timedelta(days=10)).isoformat(timespec="seconds"), (hoy - timedelta(days=8)).isoformat(timespec="seconds"), (hoy - timedelta(days=6)).isoformat(timespec="seconds"), pid))
    conn.commit(); conn.close()
    r = portal_tiempos.resumen(t, u)
    assert r["peticiones"] == {"n": 3, "hasta_subir": 2.0, "hasta_revisar": 4.0} and r["conversaciones"]["n"] == 0 and r["conversaciones"]["primera_respuesta"] is None
    pc.iniciar(f1, "Una duda", "Hola", "cliente", "uno@ejemplo.com")
    assert portal_tiempos.resumen(t, u)["conversaciones"] == {"n": 1, "sin_contestar": 1, "primera_respuesta": None, "dentro_de_plazo": None}


def test_el_selector_de_empresas_cuenta_lo_pendiente_de_cada_una(cliente):
    from app import portal_peticiones as pp
    from app.db_fiscal import crear_cliente_fiscal
    from tests.test_portal_personas_avisos import _despacho, _entrar, _html
    t, u, c1 = _despacho("Gestoria selector", cliente_email="dueno@ejemplo.com", cliente_nombre="Sociedad Uno SL")
    c2 = crear_cliente_fiscal(t, "Sociedad Dos SL", nif="B87654321", email="dueno@ejemplo.com")
    pp.crear(db.obtener_cliente_fiscal_por_id(c2), "Extracto del 3T", por=u)
    _entrar(cliente, c1, "dueno@ejemplo.com")
    assert "Sociedad Dos SL · 1 pendiente" in _html(cliente, "/portal/")


def test_la_escalada_deja_una_tarea_de_llamada_solo_si_el_despacho_la_activa(cliente):
    from datetime import datetime as dt
    from app import portal_avisos
    t, u, c, f1, c2, f2 = _escenario()
    conn = db.get_connection(); conn.execute("UPDATE clientes_fiscales SET responsable_id = ? WHERE id = ?", (u, c)); conn.commit(); conn.close()
    ficha = db.obtener_cliente_fiscal_por_id(c)
    portal_avisos._tarea_de_llamada(ficha, "Falta un documento", dt.now())
    conn = db.get_connection(); assert conn.execute("SELECT COUNT(*) FROM tareas_outlook WHERE usuario_id = ?", (u,)).fetchone()[0] == 0; conn.close()      # apagada: ninguna tarea
    pcm.fijar(t, escalada_avisos=True)
    portal_avisos._tarea_de_llamada(ficha, "Falta un documento", dt.now())
    conn = db.get_connection()
    filas = conn.execute("SELECT asunto, prioridad, cliente_fiscal_id FROM tareas_outlook WHERE usuario_id = ?", (u,)).fetchall()
    conn.close()
    assert len(filas) == 1 and filas[0]["asunto"].startswith("Llamar a Uno SL") and filas[0]["prioridad"] == "alta" and filas[0]["cliente_fiscal_id"] == c


def test_los_enlaces_del_portal_usan_la_direccion_de_los_clientes_si_existe(monkeypatch):
    from app import portal_recordatorios as pr
    monkeypatch.setenv("GUILDA_URL_PUBLICA", "https://app.ejemplo.com")
    monkeypatch.delenv("GUILDA_URL_PORTAL", raising=False)
    assert pr.url_portal() == "https://app.ejemplo.com/portal/entrar"
    monkeypatch.setenv("GUILDA_URL_PORTAL", "https://clientes.ejemplo.com/")
    assert pr.url_portal() == "https://clientes.ejemplo.com/portal/entrar" and pr.url_preferencias(1, "a@b.com").startswith("https://clientes.ejemplo.com/portal/preferencias/")
    assert "app.ejemplo.com" not in pr.url_portal("/portal/peticiones/3", 7)
