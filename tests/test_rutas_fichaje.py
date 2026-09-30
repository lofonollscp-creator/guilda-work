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
