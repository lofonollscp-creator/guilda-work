"""Rutas de fichaje (app/rutas_fichaje.py) -- corrección de olvidos con
la hora real del evento (bug encontrado en la auditoría de esta sesión,
ver bitácora 2026-09-30: antes se guardaba siempre con la hora ACTUAL
del servidor). No existía ningún test a nivel de ruta para este módulo
hasta ahora."""
from datetime import datetime, timedelta

from tests.conftest import iniciar_sesion_de_prueba

from app import db


def test_admin_corregir_guarda_la_hora_indicada_no_la_actual(cliente):
    tenant_id = db.crear_tenant("Gestoria Fichaje Correccion")
    gestor_id = iniciar_sesion_de_prueba(cliente, "fichaje-gestor@ejemplo.com", "contrasena123")
    db.asignar_tenant(gestor_id, tenant_id)
    db.asignar_gestor_fichajes(gestor_id, True)
    trabajador_id = db.crear_usuario_vinculado_a_kratos(
        "fichaje-trabajador@ejemplo.com", "kratos-fichaje-trabajador"
    )
    db.asignar_tenant(trabajador_id, tenant_id)

    hace_dos_dias = (datetime.now() - timedelta(days=2)).replace(second=0, microsecond=0)
    resp = cliente.post(
        f"/fichaje/admin/{trabajador_id}/corregir",
        data={"tipo": "entrada", "marca_tiempo": hace_dos_dias.strftime("%Y-%m-%dT%H:%M"), "nota": "Olvido"},
    )
    assert resp.status_code == 302

    fichajes = db.listar_fichajes(trabajador_id)
    assert len(fichajes) == 1
    guardado = datetime.fromisoformat(fichajes[0]["marca_tiempo"])
    assert guardado == hace_dos_dias
    assert (datetime.now() - guardado).total_seconds() > 3600  # no es "ahora"


def test_admin_corregir_rechaza_fecha_futura(cliente):
    tenant_id = db.crear_tenant("Gestoria Fichaje Futuro")
    gestor_id = iniciar_sesion_de_prueba(cliente, "fichaje-gestor-futuro@ejemplo.com", "contrasena123")
    db.asignar_tenant(gestor_id, tenant_id)
    db.asignar_gestor_fichajes(gestor_id, True)
    trabajador_id = db.crear_usuario_vinculado_a_kratos(
        "fichaje-trabajador-futuro@ejemplo.com", "kratos-fichaje-trabajador-futuro"
    )
    db.asignar_tenant(trabajador_id, tenant_id)

    manana = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    resp = cliente.post(
        f"/fichaje/admin/{trabajador_id}/corregir",
        data={"tipo": "entrada", "marca_tiempo": manana},
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["Location"]
    assert db.listar_fichajes(trabajador_id) == []


def test_admin_corregir_rechaza_marca_tiempo_ausente_o_invalida(cliente):
    tenant_id = db.crear_tenant("Gestoria Fichaje Sin Hora")
    gestor_id = iniciar_sesion_de_prueba(cliente, "fichaje-gestor-sinhora@ejemplo.com", "contrasena123")
    db.asignar_tenant(gestor_id, tenant_id)
    db.asignar_gestor_fichajes(gestor_id, True)
    trabajador_id = db.crear_usuario_vinculado_a_kratos(
        "fichaje-trabajador-sinhora@ejemplo.com", "kratos-fichaje-trabajador-sinhora"
    )
    db.asignar_tenant(trabajador_id, tenant_id)

    resp = cliente.post(f"/fichaje/admin/{trabajador_id}/corregir", data={"tipo": "entrada"})
    assert resp.status_code == 302
    assert "error=" in resp.headers["Location"]
    assert db.listar_fichajes(trabajador_id) == []


def test_admin_corregir_requiere_gestor_del_mismo_tenant(cliente):
    tenant_propio = db.crear_tenant("Gestoria Fichaje Propio")
    tenant_ajeno = db.crear_tenant("Gestoria Fichaje Ajeno")
    gestor_id = iniciar_sesion_de_prueba(cliente, "fichaje-gestor-ajeno@ejemplo.com", "contrasena123")
    db.asignar_tenant(gestor_id, tenant_propio)
    db.asignar_gestor_fichajes(gestor_id, True)
    trabajador_id = db.crear_usuario_vinculado_a_kratos(
        "fichaje-trabajador-ajeno@ejemplo.com", "kratos-fichaje-trabajador-ajeno"
    )
    db.asignar_tenant(trabajador_id, tenant_ajeno)

    resp = cliente.post(
        f"/fichaje/admin/{trabajador_id}/corregir",
        data={"tipo": "entrada", "marca_tiempo": "2026-01-01T10:00"},
    )
    assert resp.status_code == 403


# --- Rediseño del panel (bloque 2 del rediseño interno, 2026-10-01) --------

def test_panel_estado_fuera_solo_muestra_boton_entrada(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "fichaje-panel-fuera@ejemplo.com", "contrasena123")
    db.guardar_fichaje_datos(usuario_id, "Trabajador de Prueba", "12345678A")
    html = cliente.get("/fichaje/").get_data(as_text=True)
    assert 'name="tipo" value="entrada"' in html
    assert 'name="tipo" value="pausa_inicio"' not in html
    assert 'name="tipo" value="pausa_fin"' not in html
    assert 'name="tipo" value="salida"' not in html


def test_panel_estado_dentro_muestra_pausa_y_salida_no_entrada(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "fichaje-panel-dentro@ejemplo.com", "contrasena123")
    db.guardar_fichaje_datos(usuario_id, "Trabajador de Prueba", "12345678A")
    db.fichar(usuario_id, None, "entrada")

    html = cliente.get("/fichaje/").get_data(as_text=True)
    assert 'name="tipo" value="entrada"' not in html
    assert 'name="tipo" value="pausa_inicio"' in html
    assert 'name="tipo" value="pausa_fin"' not in html
    assert 'name="tipo" value="salida"' in html
    # Feedback de tiempo transcurrido: el contador vive y arranca desde
    # la marca_tiempo del último evento real.
    assert 'class="task-timer" data-inicio="' in html


def test_panel_estado_en_pausa_muestra_solo_fin_de_pausa_y_salida(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "fichaje-panel-pausa@ejemplo.com", "contrasena123")
    db.guardar_fichaje_datos(usuario_id, "Trabajador de Prueba", "12345678A")
    db.fichar(usuario_id, None, "entrada")
    db.fichar(usuario_id, None, "pausa_inicio")

    html = cliente.get("/fichaje/").get_data(as_text=True)
    assert 'name="tipo" value="pausa_inicio"' not in html
    assert 'name="tipo" value="pausa_fin"' in html
    assert 'name="tipo" value="salida"' in html


# --- Historial agrupado por día (bloque 2 del rediseño interno) -----------

def test_historial_agrupa_por_dia_con_total_de_horas(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "fichaje-historial-grupo@ejemplo.com", "contrasena123")
    hoy = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    db.fichar(usuario_id, None, "entrada", marca_tiempo=hoy.isoformat(timespec="seconds"))
    db.fichar(usuario_id, None, "salida", marca_tiempo=(hoy + timedelta(hours=2)).isoformat(timespec="seconds"))

    html = cliente.get("/fichaje/historial").get_data(as_text=True)
    assert 'class="fichaje-dia"' in html
    assert "2.0 h trabajadas" in html


def test_historial_sin_fichajes_muestra_vacio(cliente):
    iniciar_sesion_de_prueba(cliente, "fichaje-historial-vacio@ejemplo.com", "contrasena123")
    html = cliente.get("/fichaje/historial").get_data(as_text=True)
    assert "Sin fichajes en este periodo." in html
    assert 'class="fichaje-dia"' not in html


# --- db.ultimo_fichaje() (bloque 2 del rediseño interno) -------------------

def test_ultimo_fichaje_ninguno_devuelve_none(usuario_id):
    assert db.ultimo_fichaje(usuario_id) is None


def test_ultimo_fichaje_devuelve_la_fila_mas_reciente(usuario_id):
    db.fichar(usuario_id, None, "entrada")
    db.fichar(usuario_id, None, "pausa_inicio")
    ultimo = db.ultimo_fichaje(usuario_id)
    assert ultimo["tipo"] == "pausa_inicio"
    assert ultimo["marca_tiempo"] is not None
