"""Backoffice: salud de la cartera, histórico de ingresos, alertas semanales,
tareas periódicas y borrado/exportación de tenants con datos."""
from datetime import date, datetime, timedelta

import pytest

from app import db
from backoffice import aprovisionamiento, auth, cartera, facturacion
from tests.test_backoffice_app import entrar, post
from tests.test_backoffice_app import bo  # noqa: F401 -- fixture


def _tenant(nombre, usuarios=1):
    t = db.crear_tenant(nombre)
    ids = []
    for n in range(usuarios):
        uid = db.crear_usuario_vinculado_a_kratos(f"{nombre.lower().replace(' ', '')}{n}@ejemplo.com", f"k-{nombre}-{n}")
        db.asignar_tenant(uid, t)
        ids.append(uid)
    return t, ids


def _con_uso(uid, dias=1):
    """Una nota reciente = actividad."""
    cuando = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    conn = db.get_connection()
    conn.execute("INSERT INTO notas (usuario_id, texto, creada_en) VALUES (?, 'x', ?)", (uid, cuando))
    conn.commit()
    conn.close()


def _estado(t, estado):
    db.actualizar_suscripcion_estado(t, estado)


# --- puntuación ------------------------------------------------------------------------

def test_puntuacion_por_niveles():
    activo, (u,) = _tenant("Cartera Activo")
    _con_uso(u, 1)
    _estado(activo, "activa")
    p = cartera.puntuacion_tenant(activo)
    assert p["nivel"] == "sano" and p["puntos"] >= 70

    dormido, (u2,) = _tenant("Cartera Dormido")
    _con_uso(u2, 60)
    p2 = cartera.puntuacion_tenant(dormido)
    assert p2["nivel"] == "riesgo" and any("Sin actividad" in m for m in p2["motivos"])

    impago, (u3,) = _tenant("Cartera Impago")
    _con_uso(u3, 1)
    _estado(impago, "pago_fallido")
    p3 = cartera.puntuacion_tenant(impago)
    assert "Pago fallido" in p3["motivos"] and p3["puntos"] < p["puntos"]


def test_tenant_nuevo_y_suspendido():
    vacio = db.crear_tenant("Cartera Vacío")
    assert cartera.puntuacion_tenant(vacio)["nivel"] == "nuevo" and cartera.puntuacion_tenant(vacio)["puntos"] is None
    t, (u,) = _tenant("Cartera Suspendido")
    _con_uso(u, 1)
    db.alternar_activo_tenant(t, False)
    assert cartera.puntuacion_tenant(t)["puntos"] == 0


def test_cartera_ordena_de_peor_a_mejor():
    sano, (u,) = _tenant("Orden Sano")
    _con_uso(u, 1)
    _estado(sano, "activa")
    malo, (u2,) = _tenant("Orden Malo")
    _con_uso(u2, 90)
    c = cartera.cartera()
    nombres = [f["nombre"] for f in c["filas"]]
    assert nombres.index("Orden Malo") < nombres.index("Orden Sano")
    assert c["cuenta"]["riesgo"] >= 1 and c["cuenta"]["sano"] >= 1


# --- histórico de ingresos --------------------------------------------------------------

def test_snapshot_idempotente_y_movimientos(bo):
    plan_a = db.crear_plan_guilda("Básico", None, 2900, None)
    plan_b = db.crear_plan_guilda("Pro", None, 7900, None)
    t1, _u = _tenant("Hist Alta")
    t2, _u = _tenant("Hist Baja")
    t3, _u = _tenant("Hist Cambio")
    for t, plan in ((t2, plan_a), (t3, plan_a)):
        db.asignar_plan_tenant(t, plan)
        _estado(t, "activa")
    hoy = date.today()
    assert cartera.tomar_snapshot(hoy - timedelta(days=2)) is True
    assert cartera.tomar_snapshot(hoy - timedelta(days=2)) is False  # idempotente

    db.asignar_plan_tenant(t1, plan_b)
    _estado(t1, "activa")                       # alta
    _estado(t2, "cancelada")                    # baja
    db.asignar_plan_tenant(t3, plan_b)          # mejora (29 -> 79)
    cartera.tomar_snapshot(hoy - timedelta(days=1))

    h = cartera.historial_ingresos()
    tipos = {e["tenant"]: (e["tipo"], e["delta"]) for e in h["eventos"]}
    assert tipos["Hist Alta"] == ("alta", 7900)
    assert tipos["Hist Baja"] == ("baja", -2900)
    assert tipos["Hist Cambio"] == ("mejora", 5000)
    assert h["meses"][-1]["mrr"] == 7900 + 7900  # t1 + t3
    assert h["resumen_mes"] is not None


def test_historial_vacio_sin_snapshots(bo):
    assert cartera.historial_ingresos()["meses"] == []


# --- alertas semanales -------------------------------------------------------------------

def test_resumen_menciona_riesgo_y_cobros_pendientes(bo):
    t, (u,) = _tenant("Alerta Riesgo")
    _con_uso(u, 90)
    conn = auth.conectar()
    conn.execute("INSERT INTO cobros (tenant_id, concepto, importe_centimos, stripe_session_id, url, estado, creado_en) "
                 "VALUES (?, 'Formación', 15000, 'cs_1', 'https://x', 'pendiente', ?)",
                 (t, (datetime.now() - timedelta(days=5)).isoformat(timespec="seconds")))
    conn.commit()
    conn.close()
    texto = cartera.texto_resumen(cartera.construir_resumen())
    assert "TENANTS EN RIESGO" in texto and "Alerta Riesgo" in texto and "Formación" in texto and "150,00 €" in texto


def test_resumen_semanal_solo_los_lunes_y_una_vez(bo):
    enviados = []
    lunes = datetime(2026, 10, 5, 9, 0)     # lunes
    assert lunes.weekday() == 0
    assert cartera.resumen_semanal_si_toca(lunes - timedelta(hours=2), enviar=lambda: enviados.append(1)) is False  # 7:00
    assert cartera.resumen_semanal_si_toca(lunes + timedelta(days=1), enviar=lambda: enviados.append(1)) is False   # martes
    assert cartera.resumen_semanal_si_toca(lunes, enviar=lambda: enviados.append(1)) is True
    assert cartera.resumen_semanal_si_toca(lunes + timedelta(hours=3), enviar=lambda: enviados.append(1)) is False  # misma semana
    assert cartera.resumen_semanal_si_toca(lunes + timedelta(days=7), enviar=lambda: enviados.append(1)) is True
    assert len(enviados) == 2


def test_si_falla_el_envio_no_se_reintenta_cada_pasada(bo):
    lunes = datetime(2026, 10, 12, 9, 0)

    def roto():
        raise RuntimeError("sin SMTP")
    with pytest.raises(RuntimeError):
        cartera.resumen_semanal_si_toca(lunes, enviar=roto)
    assert cartera.resumen_semanal_si_toca(lunes + timedelta(minutes=10), enviar=roto) is False


def test_paso_periodico_aisla_fallos_y_deja_latido(bo, monkeypatch):
    monkeypatch.setattr(cartera, "vigilar_app", lambda ahora=None: [])
    monkeypatch.setattr(cartera.dependencias, "auditar_si_toca", lambda ahora=None: False)
    monkeypatch.setattr(cartera, "refrescar_cobros_pendientes", lambda: (_ for _ in ()).throw(RuntimeError("stripe caído")))
    r = cartera.paso_periodico(datetime(2026, 10, 6, 10, 0), enviar=lambda: None)
    assert r["snapshot"] is True and any("cobros" in e for e in r["errores"])
    assert "backoffice_tareas" in db.listar_latidos() and db.listar_latidos()["backoffice_tareas"]["ultimo_error"]
    monkeypatch.setattr(cartera, "refrescar_cobros_pendientes", lambda: 0)
    assert cartera.paso_periodico(datetime(2026, 10, 6, 10, 20), enviar=lambda: None)["errores"] == []


def test_refrescar_cobros_pendientes(bo, monkeypatch):
    t, _u = _tenant("Cobros Auto")
    conn = auth.conectar()
    ahora = datetime.now().isoformat(timespec="seconds")
    viejo = (datetime.now() - timedelta(days=40)).isoformat(timespec="seconds")
    for sid, creado in (("cs_a", ahora), ("cs_b", ahora), ("cs_viejo", viejo)):
        conn.execute("INSERT INTO cobros (tenant_id, concepto, importe_centimos, stripe_session_id, url, estado, creado_en) "
                     "VALUES (?, 'x', 100, ?, 'u', 'pendiente', ?)", (t, sid, creado))
    conn.commit()
    conn.close()
    monkeypatch.setattr(facturacion, "configurado", lambda: True)
    vistos = []

    def falso(tenant_id, cobro_id):
        vistos.append(cobro_id)
        if len(vistos) == 1:
            raise ValueError("Stripe no responde")
        return "pagado"
    monkeypatch.setattr(facturacion, "refrescar_cobro", falso)
    assert cartera.refrescar_cobros_pendientes() == 1 and len(vistos) == 2  # el de 40 días ni se mira
    monkeypatch.setattr(facturacion, "configurado", lambda: False)
    assert cartera.refrescar_cobros_pendientes() == 0


# --- pantallas -------------------------------------------------------------------------------

def test_pantallas_de_cartera(bo, monkeypatch):
    entrar(bo)
    t, (u,) = _tenant("Pantalla Cartera")
    _con_uso(u, 1)
    cartera.tomar_snapshot(date.today())
    assert "Salud de la cartera" in bo.get("/").get_data(as_text=True)
    assert "Salud</th>" in bo.get("/tenants").get_data(as_text=True)
    ficha = bo.get(f"/tenants/{t}?seccion=actividad").get_data(as_text=True)
    assert "Salud del cliente" in ficha and "Actividad reciente" in ficha
    assert "Evolución" in bo.get("/ingresos").get_data(as_text=True)
    assert "Texto del resumen" in bo.get("/alertas").get_data(as_text=True)
    enviados = []
    monkeypatch.setattr(cartera, "enviar_resumen", lambda r=None: enviados.append(1))
    post(bo, "/alertas/enviar")
    assert enviados == [1] and any(r["accion"] == "alertas.enviar" for r in auth.listar_auditoria())


def test_enviar_alertas_sin_correo_configurado_no_da_500(bo, monkeypatch):
    from app import notificaciones_email
    entrar(bo)
    monkeypatch.setattr(notificaciones_email, "ALERTAS_ADMIN_EMAIL", "")
    r = post(bo, "/alertas/enviar")
    assert r.status_code == 302
    assert "ALERTAS_ADMIN_EMAIL" in bo.get("/alertas").get_data(as_text=True)


# --- borrado y exportación de tenants con datos ----------------------------------------------------

def _tenant_con_datos(nombre):
    t, (u,) = _tenant(nombre)
    c = db.crear_cliente_fiscal(t, "Cliente X", email="x@x.com")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T1", "2026-04-20")
    db.subir_documento_vencimiento(v, "a.pdf", "application/pdf", b"%PDF")
    conn = db.get_connection()
    conn.execute("INSERT INTO vencimientos_fiscales_pagos (vencimiento_id, stripe_checkout_session_id, importe_centimos, pagado_en) VALUES (?, 's', 100, '2026-01-01')", (v,))
    conn.commit()
    conn.close()
    db.crear_acceso_cliente_fiscal(c, "127.0.0.1")
    w = db.crear_webhook(u, t, "https://ejemplo.com/h", ["nota.creada"])
    db.registrar_entrega_webhook(w["id"], "nota.creada", 200, 1, None) if hasattr(db, "registrar_entrega_webhook") else None
    nota = db.crear_nota(u, "una nota") if hasattr(db, "crear_nota") else None
    return t, u, c, v


def test_borrar_tenant_con_clientes_vencimientos_y_webhooks():
    t, u, c, v = _tenant_con_datos("Borrado Completo")
    db.borrar_tenant(t)
    assert db.obtener_tenant(t) is None and db.obtener_cliente_fiscal(t, c) is None
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM vencimientos_fiscales WHERE id = ?", (v,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM vencimientos_fiscales_pagos WHERE vencimiento_id = ?", (v,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM webhooks WHERE tenant_id = ?", (t,)).fetchone()[0] == 0
    assert conn.execute("SELECT tenant_id FROM usuarios WHERE id = ?", (u,)).fetchone()[0] is None  # el usuario sigue existiendo
    conn.close()


def test_borrar_tenant_con_fichajes_exige_confirmacion_y_es_atomico():
    t, u, c, v = _tenant_con_datos("Borrado Fichajes")
    db.fichar(u, t, "entrada")
    with pytest.raises(ValueError, match="fichajes"):
        db.borrar_tenant(t)
    assert db.obtener_tenant(t) is not None and db.obtener_cliente_fiscal(t, c) is not None  # no se tocó nada
    db.borrar_tenant(t, incluir_fichajes=True)
    assert db.obtener_tenant(t) is None and db.contar_fichajes_tenant(t) == 0


def test_ruta_de_borrado_no_retira_integraciones_si_hay_fichajes(bo, monkeypatch):
    entrar(bo)
    t, u, c, v = _tenant_con_datos("Ruta Fichajes")
    db.fichar(u, t, "entrada")
    llamadas = []
    monkeypatch.setattr(aprovisionamiento, "desaprovisionar_tenant", lambda ten: llamadas.append(ten["id"]) or [])
    post(bo, f"/tenants/{t}/borrar", confirmacion="Ruta Fichajes")
    assert llamadas == [] and db.obtener_tenant(t) is not None
    assert "fichajes" in bo.get(f"/tenants/{t}?seccion=avanzado").get_data(as_text=True)
    post(bo, f"/tenants/{t}/borrar", confirmacion="Ruta Fichajes", borrar_fichajes="1")
    assert llamadas == [t] and db.obtener_tenant(t) is None


def test_exportacion_incluye_tareas_compartidas_correo_de_equipo_y_fichajes():
    t, u, c, v = _tenant_con_datos("Exporta Todo")
    db.fichar(u, t, "entrada")
    datos = db.exportar_datos_tenant(t)
    for clave in ("tareas_lista", "comentarios_tareas", "correo_equipo_asignaciones", "correo_equipo_notas_internas", "fichajes"):
        assert clave in datos
    assert len(datos["fichajes"]) == 1
