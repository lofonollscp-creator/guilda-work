"""Tests de app/db.py.

Cubren sobre todo la lógica con más riesgo de romperse en silencio: el
cálculo de duración al pausar/reanudar tareas, el borrado en cascada de un
menú, y los filtros del histórico. La base de datos de cada test es un
archivo temporal aislado (ver conftest.py) — nunca se toca data/registro.db.
"""
from datetime import datetime, timedelta

from app import db


def _reloj(*momentos):
    """Sustituye db.now_iso() por una secuencia fija de timestamps, en orden.

    Cada llamada a now_iso() devuelve el siguiente `momento` de la lista, ya
    formateado en ISO. Permite probar la aritmética de fechas sin sleeps.
    """
    it = iter(momentos)

    def _siguiente():
        return next(it).isoformat(timespec="seconds")

    return _siguiente


# --- Categorías / menús -----------------------------------------------------

def test_crear_y_listar_categoria(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda", "#4a90d9")
    categorias = db.listar_categorias(usuario_id)
    assert len(categorias) == 1
    assert categorias[0]["id"] == cid
    assert categorias[0]["nombre"] == "Guilda"
    assert categorias[0]["color"] == "#4a90d9"


def test_renombrar_categoria(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    db.renombrar_categoria(usuario_id, cid, "Guilda Renombrada", "#e0a83a")
    cat = db.obtener_categoria(usuario_id, cid)
    assert cat["nombre"] == "Guilda Renombrada"
    assert cat["color"] == "#e0a83a"


def test_eliminar_categoria_manda_a_la_papelera_no_borra_de_verdad(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    tarea_id = db.crear_tarea(usuario_id, "Proceso", cid, "duracion")
    db.pausar_tarea(usuario_id, tarea_id)  # genera una fila en pausas
    db.crear_nota(usuario_id, "Nota suelta del menú", categoria_id=cid)
    db.crear_nota(usuario_id, "Nota ligada a la tarea", categoria_id=cid, tarea_id=tarea_id)
    db.crear_plantilla(cid, "Frase favorita")

    db.eliminar_categoria(usuario_id, cid)

    # Desaparece de las vistas normales...
    assert db.obtener_categoria(usuario_id, cid) is None
    assert db.obtener_tarea(usuario_id, tarea_id) is None
    assert db.historial(usuario_id) == []
    # ...pero no se ha borrado nada de verdad: sigue en la papelera y las
    # plantillas (no cubiertas por la papelera) siguen existiendo.
    origenes_en_papelera = {(item["origen"], item["id"]) for item in db.papelera(usuario_id)}
    assert ("menu", cid) in origenes_en_papelera
    assert ("tarea", tarea_id) in origenes_en_papelera
    assert len(db.listar_plantillas(cid)) == 1


def test_restaurar_categoria_recupera_menu_tareas_y_notas(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    tarea_id = db.crear_tarea(usuario_id, "Proceso", cid, "duracion")
    nota_id = db.crear_nota(usuario_id, "Nota", categoria_id=cid)

    db.eliminar_categoria(usuario_id, cid)
    db.restaurar_categoria(usuario_id, cid)

    assert db.obtener_categoria(usuario_id, cid) is not None
    assert db.obtener_tarea(usuario_id, tarea_id) is not None
    assert db.obtener_nota(usuario_id, nota_id) is not None


def test_restaurar_categoria_no_revive_algo_borrado_por_separado_antes(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    nota_independiente = db.crear_nota(usuario_id, "Nota borrada antes", categoria_id=cid)
    db.eliminar_nota(usuario_id, nota_independiente)  # a la papelera por su cuenta

    db.eliminar_categoria(usuario_id, cid)      # ahora se borra el menú entero
    db.restaurar_categoria(usuario_id, cid)     # y se restaura

    # La nota que ya estaba en la papelera antes de borrar el menú sigue allí.
    assert db.obtener_nota(usuario_id, nota_independiente) is None


def test_eliminar_categoria_definitivamente_borra_todo_de_verdad(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    tarea_id = db.crear_tarea(usuario_id, "Proceso", cid, "duracion")
    db.crear_nota(usuario_id, "Nota", categoria_id=cid)
    db.crear_plantilla(cid, "Frase favorita")

    db.eliminar_categoria_definitivamente(usuario_id, cid)

    assert db.obtener_categoria(usuario_id, cid) is None
    assert db.obtener_tarea(usuario_id, tarea_id) is None
    assert db.listar_plantillas(cid) == []
    assert not any(item["id"] == cid and item["origen"] == "menu" for item in db.papelera(usuario_id))


# --- Notas -------------------------------------------------------------------

def test_crear_editar_eliminar_nota(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    nota_id = db.crear_nota(usuario_id, "Texto original", categoria_id=cid)

    db.editar_nota(usuario_id, nota_id, "Texto corregido")
    assert db.obtener_nota(usuario_id, nota_id)["texto"] == "Texto corregido"

    db.eliminar_nota(usuario_id, nota_id)
    assert db.obtener_nota(usuario_id, nota_id) is None


# --- Tareas: creación ---------------------------------------------------------

def test_evento_instantaneo_no_tiene_fin_ni_duracion(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    tarea_id = db.crear_tarea(usuario_id, "Llamada a cliente", cid, "instantanea")
    tarea = db.obtener_tarea(usuario_id, tarea_id)
    assert tarea["estado"] == "finalizada"
    assert tarea["fin_en"] is None
    assert tarea["duracion_segundos"] is None


def test_tarea_duracion_arranca_en_curso(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    tarea_id = db.crear_tarea(usuario_id, "Proceso", cid, "duracion")
    tarea = db.obtener_tarea(usuario_id, tarea_id)
    assert tarea["estado"] == "en_curso"
    assert tarea["fin_en"] is None


# --- Pausar / reanudar: la parte más delicada del cálculo de duración -------

def test_finalizar_sin_pausas_cuenta_todo_el_tiempo(monkeypatch, usuario_id):
    t0 = datetime(2026, 1, 1, 10, 0, 0)
    t1 = t0 + timedelta(minutes=5)
    # El primer momento lo consume crear_categoria() (creada_en); no se comprueba.
    monkeypatch.setattr(db, "now_iso", _reloj(t0, t0, t1))

    cid = db.crear_categoria(usuario_id, "Guilda")
    tarea_id = db.crear_tarea(usuario_id, "Proceso", cid, "duracion")
    db.finalizar_tarea(usuario_id, tarea_id)

    tarea = db.obtener_tarea(usuario_id, tarea_id)
    assert tarea["estado"] == "finalizada"
    assert tarea["duracion_segundos"] == 5 * 60


def test_pausar_y_reanudar_descuenta_el_tiempo_pausado(monkeypatch, usuario_id):
    t0 = datetime(2026, 1, 1, 10, 0, 0)   # crear_tarea
    t1 = t0 + timedelta(seconds=60)       # pausar_tarea (1 min trabajado)
    t2 = t0 + timedelta(seconds=300)      # reanudar_tarea (4 min en pausa)
    t3 = t0 + timedelta(seconds=360)      # finalizar_tarea (1 min más trabajado)
    # El primer momento lo consume crear_categoria() (creada_en); no se comprueba.
    monkeypatch.setattr(db, "now_iso", _reloj(t0, t0, t1, t2, t3))

    cid = db.crear_categoria(usuario_id, "Guilda")
    tarea_id = db.crear_tarea(usuario_id, "Proceso", cid, "duracion")
    db.pausar_tarea(usuario_id, tarea_id)
    assert db.obtener_tarea(usuario_id, tarea_id)["estado"] == "pausada"

    db.reanudar_tarea(usuario_id, tarea_id)
    assert db.obtener_tarea(usuario_id, tarea_id)["estado"] == "en_curso"

    db.finalizar_tarea(usuario_id, tarea_id)
    tarea = db.obtener_tarea(usuario_id, tarea_id)
    # Trabajado: 60s antes de pausar + 60s tras reanudar = 120s. Los 240s de
    # pausa (t1→t2) no deben contar.
    assert tarea["duracion_segundos"] == 120


def test_finalizar_mientras_esta_pausada_cierra_la_pausa_abierta(monkeypatch, usuario_id):
    t0 = datetime(2026, 1, 1, 10, 0, 0)   # crear_tarea
    t1 = t0 + timedelta(seconds=30)       # pausar_tarea (30s trabajados)
    t2 = t0 + timedelta(seconds=120)      # finalizar_tarea, todavía en pausa
    # El primer momento lo consume crear_categoria() (creada_en); no se comprueba.
    monkeypatch.setattr(db, "now_iso", _reloj(t0, t0, t1, t2))

    cid = db.crear_categoria(usuario_id, "Guilda")
    tarea_id = db.crear_tarea(usuario_id, "Proceso", cid, "duracion")
    db.pausar_tarea(usuario_id, tarea_id)
    db.finalizar_tarea(usuario_id, tarea_id)

    tarea = db.obtener_tarea(usuario_id, tarea_id)
    assert tarea["estado"] == "finalizada"
    # Solo cuentan los 30s trabajados antes de pausar; los 90s en pausa no.
    assert tarea["duracion_segundos"] == 30


def test_tareas_activas_incluye_en_curso_y_pausadas(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    t1 = db.crear_tarea(usuario_id, "En curso", cid, "duracion")
    t2 = db.crear_tarea(usuario_id, "En pausa", cid, "duracion")
    db.pausar_tarea(usuario_id, t2)

    activas = {t["id"] for t in db.tareas_activas(usuario_id)}
    assert activas == {t1, t2}


# --- Ajuste manual de horas ---------------------------------------------------

def test_editar_tiempos_tarea_finalizada_recalcula_duracion(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    tarea_id = db.crear_tarea(usuario_id, "Proceso", cid, "duracion")
    db.finalizar_tarea(usuario_id, tarea_id)

    inicio = "2026-01-01T10:00:00"
    fin = "2026-01-01T11:05:00"
    error = db.editar_tiempos_tarea(usuario_id, tarea_id, inicio, fin)

    assert error is None
    tarea = db.obtener_tarea(usuario_id, tarea_id)
    assert tarea["duracion_segundos"] == 65 * 60


def test_editar_tiempos_tarea_rechaza_fin_anterior_al_inicio(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    tarea_id = db.crear_tarea(usuario_id, "Proceso", cid, "duracion")
    db.finalizar_tarea(usuario_id, tarea_id)

    error = db.editar_tiempos_tarea(usuario_id, tarea_id, "2026-01-01T11:00:00", "2026-01-01T10:00:00")
    assert error is not None


# --- Histórico y búsqueda -----------------------------------------------------

def test_historial_filtra_por_texto_y_categoria(usuario_id):
    lueira = db.crear_categoria(usuario_id, "Lueira")
    guilda = db.crear_categoria(usuario_id, "Guilda")
    db.crear_nota(usuario_id, "Llamada a cliente X", categoria_id=lueira)
    db.crear_nota(usuario_id, "Reunión interna", categoria_id=guilda)

    resultado = db.historial(usuario_id, texto="cliente")
    assert len(resultado) == 1
    assert resultado[0]["texto"] == "Llamada a cliente X"

    resultado_guilda = db.historial(usuario_id, categoria_id=guilda)
    assert len(resultado_guilda) == 1
    assert resultado_guilda[0]["categoria_nombre"] == "Guilda"


def test_historial_filtra_por_rango_de_fechas(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    db.crear_nota(usuario_id, "Nota", categoria_id=cid)

    hoy = datetime.now().strftime("%Y-%m-%d")
    manana = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    ayer = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    assert len(db.historial(usuario_id, desde=hoy, hasta=manana)) == 1
    assert len(db.historial(usuario_id, desde=manana)) == 0
    assert len(db.historial(usuario_id, hasta=ayer)) == 0


# --- Frases favoritas ----------------------------------------------------------

def test_plantillas_crear_listar_eliminar(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    pid = db.crear_plantilla(cid, "Llamada a cliente")
    assert [p["texto"] for p in db.listar_plantillas(cid)] == ["Llamada a cliente"]

    db.eliminar_plantilla(pid)
    assert db.listar_plantillas(cid) == []


# --- Estadísticas ----------------------------------------------------------

def test_estadisticas_por_categoria_suma_duraciones(monkeypatch, usuario_id):
    t0 = datetime(2026, 1, 1, 10, 0, 0)
    t1 = t0 + timedelta(minutes=10)
    # El primer y el último momento los consumen crear_categoria() y
    # crear_nota() (creada_en de cada una); no se comprueban.
    monkeypatch.setattr(db, "now_iso", _reloj(t0, t0, t1, t1))

    cid = db.crear_categoria(usuario_id, "Guilda")
    tarea_id = db.crear_tarea(usuario_id, "Proceso", cid, "duracion")
    db.finalizar_tarea(usuario_id, tarea_id)
    db.crear_nota(usuario_id, "Nota suelta", categoria_id=cid)

    stats = db.estadisticas_por_categoria(usuario_id)
    assert len(stats) == 1
    assert stats[0]["segundos_totales"] == 600
    assert stats[0]["num_tareas"] == 1
    assert stats[0]["num_notas"] == 1


# --- Copia de seguridad ----------------------------------------------------

def test_backup_crea_un_archivo_y_no_lo_duplica_el_mismo_dia(usuario_id):
    db.crear_categoria(usuario_id, "Guilda")  # asegura que exista la base de datos

    db.hacer_backup_si_hace_falta()
    archivos = list(db.BACKUPS_DIR.glob("registro_*.db"))
    assert len(archivos) == 1

    db.hacer_backup_si_hace_falta()
    archivos_tras_segunda_llamada = list(db.BACKUPS_DIR.glob("registro_*.db"))
    assert len(archivos_tras_segunda_llamada) == 1

    # La copia debe contener los datos reales, no un archivo vacío.
    import sqlite3
    con = sqlite3.connect(archivos[0])
    try:
        n = con.execute("SELECT COUNT(*) FROM categorias").fetchone()[0]
        assert n == 1
    finally:
        con.close()


# --- Papelera ------------------------------------------------------------

def test_eliminar_y_restaurar_nota(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    nota_id = db.crear_nota(usuario_id, "Nota", categoria_id=cid)

    db.eliminar_nota(usuario_id, nota_id)
    assert db.obtener_nota(usuario_id, nota_id) is None
    assert any(item["origen"] == "nota" and item["id"] == nota_id for item in db.papelera(usuario_id))

    db.restaurar_nota(usuario_id, nota_id)
    assert db.obtener_nota(usuario_id, nota_id) is not None
    assert not any(item["origen"] == "nota" and item["id"] == nota_id for item in db.papelera(usuario_id))


def test_eliminar_y_restaurar_tarea(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    tarea_id = db.crear_tarea(usuario_id, "Proceso", cid, "instantanea")

    db.eliminar_tarea(usuario_id, tarea_id)
    assert db.obtener_tarea(usuario_id, tarea_id) is None

    db.restaurar_tarea(usuario_id, tarea_id)
    assert db.obtener_tarea(usuario_id, tarea_id) is not None


def test_eliminar_definitivamente_no_deja_rastro(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    nota_id = db.crear_nota(usuario_id, "Nota", categoria_id=cid)
    tarea_id = db.crear_tarea(usuario_id, "Proceso", cid, "instantanea")

    db.eliminar_nota(usuario_id, nota_id)
    db.eliminar_nota_definitivamente(usuario_id, nota_id)
    db.eliminar_tarea(usuario_id, tarea_id)
    db.eliminar_tarea_definitivamente(usuario_id, tarea_id)

    ids_en_papelera = {(item["origen"], item["id"]) for item in db.papelera(usuario_id)}
    assert ("nota", nota_id) not in ids_en_papelera
    assert ("tarea", tarea_id) not in ids_en_papelera


def test_vaciar_papelera_antigua_purga_solo_lo_viejo(monkeypatch, usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    nota_vieja = db.crear_nota(usuario_id, "Nota vieja", categoria_id=cid)
    nota_reciente = db.crear_nota(usuario_id, "Nota reciente", categoria_id=cid)

    hace_40_dias = (datetime.now() - timedelta(days=40)).isoformat(timespec="seconds")
    hace_1_dia = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")

    monkeypatch.setattr(db, "_marca_papelera", lambda: hace_40_dias)
    db.eliminar_nota(usuario_id, nota_vieja)
    monkeypatch.setattr(db, "_marca_papelera", lambda: hace_1_dia)
    db.eliminar_nota(usuario_id, nota_reciente)

    db.vaciar_papelera_antigua(dias=30)

    ids_en_papelera = {(item["origen"], item["id"]) for item in db.papelera(usuario_id)}
    assert ("nota", nota_vieja) not in ids_en_papelera
    assert ("nota", nota_reciente) in ids_en_papelera


# --- Reordenar menús ---------------------------------------------------------

def test_crear_categoria_asigna_orden_creciente(usuario_id):
    a = db.crear_categoria(usuario_id, "Lueira")
    b = db.crear_categoria(usuario_id, "Guilda")
    menus = db.listar_categorias(usuario_id)
    assert [m["id"] for m in menus] == [a, b]  # por orden de creación, no alfabético


def test_crear_categoria_con_nombre_en_papelera_la_restaura_en_vez_de_fallar(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    db.eliminar_categoria(usuario_id, cid)
    assert db.obtener_categoria(usuario_id, cid) is None

    cid2 = db.crear_categoria(usuario_id, "Guilda")  # no debe lanzar IntegrityError

    assert cid2 == cid
    assert db.obtener_categoria(usuario_id, cid) is not None


def test_mover_categoria_arriba_y_abajo(usuario_id):
    a = db.crear_categoria(usuario_id, "Lueira")
    b = db.crear_categoria(usuario_id, "Guilda")
    c = db.crear_categoria(usuario_id, "Formación")
    assert [m["id"] for m in db.listar_categorias(usuario_id)] == [a, b, c]

    db.mover_categoria(usuario_id, c, "arriba")
    assert [m["id"] for m in db.listar_categorias(usuario_id)] == [a, c, b]

    db.mover_categoria(usuario_id, a, "arriba")  # ya es el primero, no debe pasar nada
    assert [m["id"] for m in db.listar_categorias(usuario_id)] == [a, c, b]

    db.mover_categoria(usuario_id, b, "abajo")  # ya es el último, no debe pasar nada
    assert [m["id"] for m in db.listar_categorias(usuario_id)] == [a, c, b]


def test_reordenar_categorias_aplica_el_orden_completo_recibido(usuario_id):
    a = db.crear_categoria(usuario_id, "Lueira")
    b = db.crear_categoria(usuario_id, "Guilda")
    c = db.crear_categoria(usuario_id, "Formación")
    assert [m["id"] for m in db.listar_categorias(usuario_id)] == [a, b, c]

    db.reordenar_categorias(usuario_id, [c, a, b])
    assert [m["id"] for m in db.listar_categorias(usuario_id)] == [c, a, b]


def test_reordenar_categorias_ignora_ids_inexistentes(usuario_id):
    a = db.crear_categoria(usuario_id, "Lueira")
    b = db.crear_categoria(usuario_id, "Guilda")

    db.reordenar_categorias(usuario_id, [b, 9999, a])  # el id 9999 no existe

    assert [m["id"] for m in db.listar_categorias(usuario_id)] == [b, a]


def test_alternar_favorito_categoria(usuario_id):
    cid = db.crear_categoria(usuario_id, "Lueira")
    assert db.obtener_categoria(usuario_id, cid)["favorito"] == 0

    db.alternar_favorito_categoria(usuario_id, cid)
    assert db.obtener_categoria(usuario_id, cid)["favorito"] == 1

    db.alternar_favorito_categoria(usuario_id, cid)
    assert db.obtener_categoria(usuario_id, cid)["favorito"] == 0


# --- Actividad reciente (para el recordatorio periódico) -------------------

def test_hubo_actividad_reciente(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    assert db.hubo_actividad_reciente(usuario_id, 60) is False

    db.crear_nota(usuario_id, "Nota", categoria_id=cid)
    assert db.hubo_actividad_reciente(usuario_id, 60) is True


# --- Importar datos ---------------------------------------------------------

def test_importar_nota_y_tarea_con_timestamps_explicitos(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    nota_id = db.importar_nota(usuario_id, "Nota importada", cid, "2026-01-01T10:00:00")
    tarea_id = db.importar_tarea(
        usuario_id, "Tarea importada", cid, "duracion",
        "2026-01-01T09:00:00", "2026-01-01T10:00:00", 3600,
    )

    nota = db.obtener_nota(usuario_id, nota_id)
    assert nota["texto"] == "Nota importada"
    assert nota["creada_en"] == "2026-01-01T10:00:00"

    tarea = db.obtener_tarea(usuario_id, tarea_id)
    assert tarea["estado"] == "finalizada"
    assert tarea["duracion_segundos"] == 3600
    assert tarea["inicio_en"] == "2026-01-01T09:00:00"
