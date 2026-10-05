"""Tareas unificadas: la lista de tareas (tareas_outlook) y los registros de
tiempo (tareas con cronómetro) se enlazan por dentro (tareas.tarea_outlook_id);
checklist, asignación a compañeros del despacho, "Mi día", tablero y
recurrentes ampliadas."""
import sqlite3
from datetime import datetime

import pytest

from app import db
from tests.conftest import iniciar_sesion_de_prueba


# --- Utilidades ----------------------------------------------------------------

def _despacho(*emails):
    tenant = db.crear_tenant(f"Despacho {emails[0]}")
    ids = []
    for email in emails:
        uid = db.crear_usuario(email, "contrasena123")
        db.asignar_tenant(uid, tenant)
        ids.append(uid)
    return tenant, ids


def _fake_hoy(monkeypatch, anio, mes, dia):
    class Falsa(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(anio, mes, dia, 9, 0, 0)
    monkeypatch.setattr(db, "datetime", Falsa)


# --- Cronómetro enlazado -----------------------------------------------------------

def test_iniciar_cronometro_crea_el_registro_de_tiempo_enlazado(usuario_id):
    proyecto = db.crear_categoria(usuario_id, "Lueira")
    tarea = db.crear_tarea_outlook(usuario_id, "Declaración trimestral", categoria_id=proyecto)

    timer = db.iniciar_cronometro_tarea_outlook(usuario_id, tarea)

    registro = db.obtener_tarea(usuario_id, timer)
    assert registro["tarea_outlook_id"] == tarea and registro["estado"] == "en_curso"
    assert registro["nombre"] == "Declaración trimestral" and registro["categoria_id"] == proyecto
    assert db.obtener_tarea_outlook(usuario_id, tarea)["estado"] == "en_progreso"
    assert db.cronometros_de_tareas_outlook(usuario_id, [tarea])[tarea]["activo"]["id"] == timer


def test_no_se_puede_iniciar_dos_veces_ni_sin_proyecto(usuario_id):
    proyecto = db.crear_categoria(usuario_id, "Lueira")
    sin_proyecto = db.crear_tarea_outlook(usuario_id, "Sin proyecto")
    with pytest.raises(ValueError, match="proyecto"):
        db.iniciar_cronometro_tarea_outlook(usuario_id, sin_proyecto)
    timer = db.iniciar_cronometro_tarea_outlook(usuario_id, sin_proyecto, categoria_id=proyecto)
    assert timer
    with pytest.raises(ValueError, match="ya tiene"):
        db.iniciar_cronometro_tarea_outlook(usuario_id, sin_proyecto, categoria_id=proyecto)


def test_el_tiempo_acumulado_sale_en_la_tarea_y_en_el_historial_como_siempre(usuario_id):
    proyecto = db.crear_categoria(usuario_id, "Lueira")
    tarea = db.crear_tarea_outlook(usuario_id, "Nóminas", categoria_id=proyecto)
    timer = db.iniciar_cronometro_tarea_outlook(usuario_id, tarea)
    db.finalizar_tarea(usuario_id, timer)

    cronos = db.cronometros_de_tareas_outlook(usuario_id, [tarea])[tarea]
    assert cronos["activo"] is None
    assert cronos["total_segundos"] == db.obtener_tarea(usuario_id, timer)["duracion_segundos"]
    filas = [f for f in db.historial(usuario_id) if f["origen"] == "tarea" and f["texto"] == "Nóminas"]
    assert len(filas) == 1 and filas[0]["estado"] == "finalizada"


def test_completar_la_tarea_cierra_el_cronometro_en_marcha(usuario_id):
    proyecto = db.crear_categoria(usuario_id, "Lueira")
    tarea = db.crear_tarea_outlook(usuario_id, "Cierre", categoria_id=proyecto)
    timer = db.iniciar_cronometro_tarea_outlook(usuario_id, tarea)
    db.pausar_tarea(usuario_id, timer)

    db.completar_tarea_outlook(usuario_id, tarea)

    registro = db.obtener_tarea(usuario_id, timer)
    assert registro["estado"] == "finalizada" and registro["fin_en"] is not None
    assert db.obtener_tarea_outlook(usuario_id, tarea)["estado"] == "completada"


# --- Checklist ----------------------------------------------------------------------

def test_checklist_calcula_el_porcentaje_y_resume(usuario_id):
    tarea = db.crear_tarea_outlook(usuario_id, "Cierre de mes")
    a = db.agregar_item_checklist(usuario_id, tarea, "Conciliar bancos")
    db.agregar_item_checklist(usuario_id, tarea, "  Revisar   IVA ")
    assert [i["texto"] for i in db.listar_checklist(tarea)] == ["Conciliar bancos", "Revisar IVA"]

    assert db.alternar_item_checklist(usuario_id, a) is True

    assert db.obtener_tarea_outlook(usuario_id, tarea)["porcentaje_completado"] == 50
    assert db.resumen_checklist([tarea]) == {tarea: (1, 2)}
    db.alternar_item_checklist(usuario_id, a)
    assert db.obtener_tarea_outlook(usuario_id, tarea)["porcentaje_completado"] == 0


def test_checklist_limites_y_vacios(usuario_id):
    tarea = db.crear_tarea_outlook(usuario_id, "Muchas")
    assert db.agregar_item_checklist(usuario_id, tarea, "   ") is None
    for n in range(db.CHECKLIST_MAX_ITEMS):
        assert db.agregar_item_checklist(usuario_id, tarea, f"paso {n}")
    assert db.agregar_item_checklist(usuario_id, tarea, "uno más") is None
    otra = db.crear_tarea_outlook(usuario_id, "Otra")
    assert db.agregar_item_checklist(usuario_id, otra, "x" * 500)
    assert len(db.listar_checklist(otra)[0]["texto"]) == db.CHECKLIST_MAX_CARACTERES


def test_eliminar_la_tarea_definitivamente_borra_su_checklist(usuario_id):
    tarea = db.crear_tarea_outlook(usuario_id, "Temporal")
    db.agregar_item_checklist(usuario_id, tarea, "paso")
    db.eliminar_tarea_outlook_definitivamente(usuario_id, tarea)
    assert db.listar_checklist(tarea) == []


# --- Asignación ---------------------------------------------------------------------

def test_asignar_solo_dentro_del_despacho_y_no_a_uno_mismo():
    _, (ana, luis) = _despacho("ana@despacho.com", "luis@despacho.com")
    _, (ajeno,) = _despacho("ajeno@otro.com")
    tarea = db.crear_tarea_outlook(ana, "Preparar el 303")

    assert db.asignar_tarea_outlook(ana, tarea, ajeno) is False  # otro despacho
    assert db.asignar_tarea_outlook(ana, tarea, ana) is False     # a uno mismo
    assert db.asignar_tarea_outlook(ana, tarea, luis) is True
    assert db.obtener_tarea_outlook(ana, tarea)["asignada_a"] == luis
    assert db.asignar_tarea_outlook(ana, tarea, None) is True     # desasignar
    assert db.obtener_tarea_outlook(ana, tarea)["asignada_a"] is None
    # crear ya asignada a alguien ajeno: se ignora en silencio (como proyecto/cliente inválidos)
    sin = db.crear_tarea_outlook(ana, "x", asignada_a=ajeno)
    assert db.obtener_tarea_outlook(ana, sin)["asignada_a"] is None


def test_la_tarea_asignada_aparece_al_compañero_y_este_solo_puede_completarla():
    _, (ana, luis) = _despacho("ana2@despacho.com", "luis2@despacho.com")
    tarea = db.crear_tarea_outlook(ana, "Revisar nóminas", asignada_a=luis)

    assert [t["id"] for t in db.listar_tareas_outlook(luis)] == []  # por defecto, solo las propias
    visibles = db.listar_tareas_outlook(luis, incluir_asignadas=True)
    assert [t["id"] for t in visibles] == [tarea]
    assert visibles[0]["creador_nombre"] == "ana2@despacho.com"
    assert [t["id"] for t in db.listar_tareas_outlook(luis, solo_asignadas=True)] == [tarea]

    # Edición y borrado: solo del dueño
    db.editar_tarea_outlook(luis, tarea, asunto="Hackeada")
    assert db.obtener_tarea_outlook(ana, tarea)["asunto"] == "Revisar nóminas"
    db.eliminar_tarea_outlook(luis, tarea)
    assert db.obtener_tarea_outlook(ana, tarea) is not None
    assert db.obtener_tarea_outlook(luis, tarea) is None  # ni siquiera abre el editor

    # Completar, cambiar de estado y marcar el checklist: también quien la tiene asignada
    item = db.agregar_item_checklist(ana, tarea, "paso 1")
    assert db.agregar_item_checklist(luis, tarea, "intruso") is None
    assert db.alternar_item_checklist(luis, item) is True
    assert db.eliminar_item_checklist(luis, item) is False
    assert db.cambiar_estado_tarea_outlook(luis, tarea, "esperando") is True
    db.completar_tarea_outlook(luis, tarea)
    assert db.obtener_tarea_outlook(ana, tarea)["estado"] == "completada"


def test_un_tercero_no_ve_ni_toca_la_tarea():
    _, (ana, luis) = _despacho("ana3@despacho.com", "luis3@despacho.com")
    _, (otro,) = _despacho("otro3@fuera.com")
    tarea = db.crear_tarea_outlook(ana, "Privada", asignada_a=luis)

    assert db.listar_tareas_outlook(otro, incluir_asignadas=True) == []
    assert db.obtener_tarea_outlook_visible(otro, tarea) is None
    assert db.cambiar_estado_tarea_outlook(otro, tarea, "completada") is False
    assert db.obtener_tarea_outlook(ana, tarea)["estado"] == "no_iniciada"


def test_cliente_fiscal_y_correo_solo_se_enlazan_si_son_del_usuario(usuario_id):
    tenant, (ana,) = _despacho("ana4@despacho.com")
    otro_tenant = db.crear_tenant("Otro despacho")
    mio = db.crear_cliente_fiscal(tenant, "Panadería Soler")
    ajeno = db.crear_cliente_fiscal(otro_tenant, "Cliente ajeno")

    t1 = db.crear_tarea_outlook(ana, "A", cliente_fiscal_id=mio)
    t2 = db.crear_tarea_outlook(ana, "B", cliente_fiscal_id=ajeno, mensaje_correo_id=999999)
    assert db.obtener_tarea_outlook(ana, t1)["cliente_fiscal_id"] == mio
    assert db.obtener_tarea_outlook(ana, t2)["cliente_fiscal_id"] is None
    assert db.obtener_tarea_outlook(ana, t2)["mensaje_correo_id"] is None
    db.editar_tarea_outlook(ana, t1, cliente_fiscal_id=ajeno)
    assert db.obtener_tarea_outlook(ana, t1)["cliente_fiscal_id"] is None
    assert db.listar_tareas_outlook(ana, cliente_fiscal_id=mio) == []


# --- Mi día y estados ------------------------------------------------------------------

def test_mi_dia_reparte_vencidas_hoy_en_progreso_y_asignadas():
    _, (ana, luis) = _despacho("ana5@despacho.com", "luis5@despacho.com")
    hoy = datetime.now().strftime("%Y-%m-%d")
    vencida = db.crear_tarea_outlook(luis, "Vencida", fecha_vencimiento="2020-01-01")
    de_hoy = db.crear_tarea_outlook(luis, "De hoy", fecha_vencimiento=hoy + " 10:00")
    en_progreso = db.crear_tarea_outlook(luis, "En marcha", estado="en_progreso")
    asignada = db.crear_tarea_outlook(ana, "Asignada", asignada_a=luis)
    db.crear_tarea_outlook(luis, "Futura", fecha_vencimiento="2099-01-01")
    hecha = db.crear_tarea_outlook(luis, "Hecha", fecha_vencimiento="2020-01-01")
    db.completar_tarea_outlook(luis, hecha)

    dia = db.tareas_para_hoy(luis)

    assert [t["id"] for t in dia["vencidas"]] == [vencida]
    assert [t["id"] for t in dia["hoy"]] == [de_hoy]
    assert [t["id"] for t in dia["en_progreso"]] == [en_progreso]
    assert [t["id"] for t in dia["asignadas"]] == [asignada]


def test_reabrir_una_tarea_completada_limpia_su_fecha(usuario_id):
    tarea = db.crear_tarea_outlook(usuario_id, "Cerrada")
    db.completar_tarea_outlook(usuario_id, tarea)
    assert db.obtener_tarea_outlook(usuario_id, tarea)["fecha_completada"]

    assert db.cambiar_estado_tarea_outlook(usuario_id, tarea, "en_progreso") is True

    fila = db.obtener_tarea_outlook(usuario_id, tarea)
    assert fila["estado"] == "en_progreso" and fila["fecha_completada"] is None and fila["porcentaje_completado"] == 0
    assert db.cambiar_estado_tarea_outlook(usuario_id, tarea, "inventado") is False


# --- Recurrentes ampliadas -------------------------------------------------------------

def _generadas(usuario_id, asunto):
    return [t for t in db.listar_tareas_outlook(usuario_id) if t["asunto"] == asunto]


def test_recurrente_diaria_y_laborables(monkeypatch, usuario_id):
    db.crear_tarea_recurrente(usuario_id, "Diaria", "diaria", 0)
    db.crear_tarea_recurrente(usuario_id, "Laborable", "laborables", 0)

    _fake_hoy(monkeypatch, 2026, 10, 3)  # sábado
    db.generar_tareas_recurrentes()
    assert len(_generadas(usuario_id, "Diaria")) == 1 and _generadas(usuario_id, "Laborable") == []

    _fake_hoy(monkeypatch, 2026, 10, 5)  # lunes: una vez aunque el cron corra dos
    db.generar_tareas_recurrentes()
    db.generar_tareas_recurrentes()
    assert len(_generadas(usuario_id, "Diaria")) == 2 and len(_generadas(usuario_id, "Laborable")) == 1


def test_recurrente_trimestral_solo_el_primer_mes_de_cada_trimestre(monkeypatch, usuario_id):
    db.crear_tarea_recurrente(usuario_id, "Modelo 303", "trimestral", 20)

    _fake_hoy(monkeypatch, 2026, 5, 20)  # mayo: no es primer mes de trimestre
    assert db.generar_tareas_recurrentes() == 0
    _fake_hoy(monkeypatch, 2026, 4, 20)
    assert db.generar_tareas_recurrentes() == 1
    assert db.generar_tareas_recurrentes() == 0  # idempotente
    _fake_hoy(monkeypatch, 2026, 7, 20)
    assert db.generar_tareas_recurrentes() == 1


def test_recurrente_anual_usa_mes_y_dia_y_ajusta_a_fin_de_mes(monkeypatch, usuario_id):
    db.crear_tarea_recurrente(usuario_id, "Renta", "anual", 30, mes=6)
    db.crear_tarea_recurrente(usuario_id, "Fin de febrero", "anual", 31, mes=2)

    _fake_hoy(monkeypatch, 2026, 6, 29)
    assert db.generar_tareas_recurrentes() == 0
    _fake_hoy(monkeypatch, 2026, 6, 30)
    assert db.generar_tareas_recurrentes() == 1
    _fake_hoy(monkeypatch, 2026, 2, 28)  # 2026 no es bisiesto: el 31 de febrero cae el 28
    assert db.generar_tareas_recurrentes() == 1
    assert db.generar_tareas_recurrentes() == 0


def test_recurrente_con_periodicidad_invalida_se_rechaza(usuario_id):
    with pytest.raises(ValueError):
        db.crear_tarea_recurrente(usuario_id, "x", "quincenal", 1)


def test_migracion_de_recurrentes_conserva_reglas_y_claves_foraneas(usuario_id):
    """Base de datos antigua: CHECK solo con semanal/mensual y tareas que
    apuntan a la regla. La migración amplía el CHECK sin perder nada."""
    conn = sqlite3.connect(db.DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DROP TABLE tareas_recurrentes")
    conn.execute(
        """CREATE TABLE tareas_recurrentes (
               id INTEGER PRIMARY KEY, usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
               categoria_id INTEGER REFERENCES categorias(id), asunto TEXT NOT NULL,
               periodicidad TEXT NOT NULL CHECK (periodicidad IN ('semanal','mensual')),
               dia INTEGER NOT NULL, activa INTEGER NOT NULL DEFAULT 1, creado_en TEXT NOT NULL)"""
    )
    conn.execute(
        "INSERT INTO tareas_recurrentes (id, usuario_id, asunto, periodicidad, dia, creado_en) VALUES (7, ?, 'Vieja', 'mensual', 15, '2026-01-01T00:00:00')",
        (usuario_id,),
    )
    conn.execute(
        "INSERT INTO tareas_outlook (usuario_id, asunto, tarea_recurrente_id, creada_en) VALUES (?, 'Generada', 7, '2026-02-01T00:00:00')",
        (usuario_id,),
    )
    conn.commit()
    conn.close()

    db.init_db()
    db.init_db()  # idempotente

    reglas = db.listar_tareas_recurrentes(usuario_id)
    assert [(r["id"], r["asunto"], r["periodicidad"], r["dia"], r["mes"]) for r in reglas] == [(7, "Vieja", "mensual", 15, None)]
    db.crear_tarea_recurrente(usuario_id, "Nueva", "trimestral", 10)  # ya admite los periodos nuevos
    comprobacion = sqlite3.connect(db.DB_PATH)
    try:
        assert comprobacion.execute("PRAGMA foreign_key_check").fetchall() == []
        assert comprobacion.execute("SELECT tarea_recurrente_id FROM tareas_outlook WHERE asunto = 'Generada'").fetchone()[0] == 7
    finally:
        comprobacion.close()


# --- Rutas ----------------------------------------------------------------------------

def _entrar(cliente, email):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    tenant = db.crear_tenant(f"Despacho de {email}")
    db.asignar_tenant(uid, tenant)
    return uid, tenant


def test_la_lista_muestra_chips_cronometro_y_acepta_los_campos_nuevos(cliente):
    uid, tenant = _entrar(cliente, "rutas1@ejemplo.com")
    companero = db.crear_usuario("compi1@ejemplo.com", "contrasena123")
    db.asignar_tenant(companero, tenant)
    proyecto = db.crear_categoria(uid, "Lueira")
    cf = db.crear_cliente_fiscal(tenant, "Panadería Soler")

    r = cliente.post("/tareas/", data={
        "asunto": "Preparar 303", "categoria_id": proyecto, "cliente_fiscal_id": cf,
        "asignada_a": companero, "con_cronometro": "1", "prioridad": "alta",
    })
    assert r.status_code == 302

    html = cliente.get("/tareas/").get_data(as_text=True)
    assert "Preparar 303" in html and "Panadería Soler" in html and "Lueira" in html
    assert "task-timer" in html          # cronómetro en marcha
    assert "Para compi1@ejemplo.com" in html
    avisos = [n for n in db.listar_notificaciones(companero) if n["tipo"] == "tarea_asignada"]
    assert len(avisos) == 1 and "Preparar 303" in avisos[0]["cuerpo"]


def test_iniciar_cronometro_sin_proyecto_vuelve_con_un_aviso_claro(cliente):
    uid, _ = _entrar(cliente, "rutas2@ejemplo.com")
    tarea = db.crear_tarea_outlook(uid, "Sin proyecto")

    r = cliente.post(f"/tareas/{tarea}/cronometro/iniciar", follow_redirects=True)

    assert "Elige un proyecto" in r.get_data(as_text=True)
    assert db.tareas_activas(uid) == []


def test_mi_dia_y_tablero_se_pintan_y_el_tablero_mueve_tareas(cliente):
    uid, _ = _entrar(cliente, "rutas3@ejemplo.com")
    vencida = db.crear_tarea_outlook(uid, "Atrasadísima", fecha_vencimiento="2020-01-01")
    otra = db.crear_tarea_outlook(uid, "Para mover")

    dia = cliente.get("/tareas/hoy").get_data(as_text=True)
    assert "Atrasadísima" in dia and "Vencidas" in dia
    tablero = cliente.get("/tareas/tablero").get_data(as_text=True)
    assert "Para mover" in tablero and "tareas-columna" in tablero

    assert cliente.post(f"/tareas/{otra}/estado", data={"estado": "esperando"}).status_code == 302
    assert db.obtener_tarea_outlook(uid, otra)["estado"] == "esperando"
    assert cliente.post(f"/tareas/{otra}/estado", data={"estado": "nada"}).status_code == 404
    assert db.obtener_tarea_outlook(uid, vencida)["estado"] == "no_iniciada"


def test_editor_con_checklist_asignacion_y_rutas_de_checklist(cliente):
    uid, tenant = _entrar(cliente, "rutas4@ejemplo.com")
    companero = db.crear_usuario("compi4@ejemplo.com", "contrasena123")
    db.asignar_tenant(companero, tenant)
    tarea = db.crear_tarea_outlook(uid, "Con pasos")

    cliente.post(f"/tareas/{tarea}/checklist", data={"texto": "Primer paso"})
    item = db.listar_checklist(tarea)[0]["id"]
    html = cliente.get(f"/tareas/{tarea}/editar").get_data(as_text=True)
    assert "Primer paso" in html and "compi4@ejemplo.com" in html

    cliente.post(f"/tareas/checklist/{item}/alternar")
    assert db.listar_checklist(tarea)[0]["hecha"] == 1
    cliente.post(f"/tareas/{tarea}/asignar", data={"asignada_a": companero})
    assert db.obtener_tarea_outlook(uid, tarea)["asignada_a"] == companero
    cliente.post(f"/tareas/checklist/{item}/eliminar")
    assert db.listar_checklist(tarea) == []
    assert cliente.post("/tareas/checklist/9999/alternar").status_code == 404


def test_recurrentes_desde_el_formulario_con_los_periodos_nuevos(cliente):
    uid, _ = _entrar(cliente, "rutas5@ejemplo.com")
    cliente.post("/tareas/recurrentes", data={"asunto": "Cada día", "periodicidad": "diaria"})
    cliente.post("/tareas/recurrentes", data={"asunto": "Trimestral", "periodicidad": "trimestral", "dia_mes": "20"})
    cliente.post("/tareas/recurrentes", data={"asunto": "Anual", "periodicidad": "anual", "dia_mes": "30", "mes": "6"})
    cliente.post("/tareas/recurrentes", data={"asunto": "Mala", "periodicidad": "anual", "dia_mes": "30"})  # sin mes: se rechaza
    cliente.post("/tareas/recurrentes", data={"asunto": "Antigua", "periodicidad": "mensual", "dia": "5"})  # formulario antiguo

    reglas = {r["asunto"]: (r["periodicidad"], r["dia"], r["mes"]) for r in db.listar_tareas_recurrentes(uid)}
    assert reglas == {
        "Cada día": ("diaria", 0, None), "Trimestral": ("trimestral", 20, None),
        "Anual": ("anual", 30, 6), "Antigua": ("mensual", 5, None),
    }
    html = cliente.get("/tareas/recurrentes").get_data(as_text=True)
    assert "Cada trimestre" in html and "Cada año" in html


def test_dashboard_y_pagina_de_proyecto_muestran_las_tareas(cliente):
    uid, _ = _entrar(cliente, "rutas6@ejemplo.com")
    proyecto = db.crear_categoria(uid, "Guilda")
    db.crear_tarea_outlook(uid, "Vence hoy", categoria_id=proyecto, fecha_vencimiento=datetime.now().strftime("%Y-%m-%d"))

    inicio = cliente.get("/").get_data(as_text=True)
    assert "tareas para hoy" in inicio and "/tareas/hoy" in inicio
    pagina = cliente.get(f"/menu/{proyecto}").get_data(as_text=True)
    assert "Tareas pendientes" in pagina and "Vence hoy" in pagina
