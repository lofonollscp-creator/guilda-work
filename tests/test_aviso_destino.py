"""Contrato unificado de los avisos para la app móvil (S-05): destino y canal de cada aviso, en el push y en `GET /notificaciones`."""
import json

import pytest

from app import aviso_destino as ad, db, notificaciones, push
from tests.test_rutas_api import _auth, _registrar


@pytest.mark.parametrize("tipo,datos,url,esperado", [
    ("tarea_asignada", {"tipo": "tarea_recordatorio", "tarea_id": 12}, "/tareas/12", {"tipo": "tarea", "id": 12}),
    ("tarea_asignada", None, "/tareas/7", {"tipo": "tarea", "id": 7}),
    ("portal_mensaje_nuevo", {"tipo": "portal_mensaje_nuevo", "vencimiento_id": 41}, "/fiscal/vencimientos/41/editar", {"tipo": "vencimiento", "id": 41}),
    ("obligacion", {"tipo": "obligacion"}, "/fiscal/vencimientos/9/editar", {"tipo": "vencimiento", "id": 9}),
    ("mencion", {"tipo": "mencion", "expediente_id": 5}, "/expedientes/5", {"tipo": "expediente", "id": 5}),
    ("certificado", {"tipo": "certificado", "certificado_id": 3}, "/certificados/3", {"tipo": "certificado", "id": 3}),
    ("aviso_fiscal", {"tipo": "aviso_fiscal", "alerta_id": 88}, "/fiscal/avisos", {"tipo": "aviso_fiscal", "id": 88}),
    ("portal_mensaje_nuevo", {"tipo": "portal_mensaje_nuevo", "factura_contable_id": 6}, "/contabilidad/6", {"tipo": "factura_contable", "id": 6}),
    ("tarea_asignada", {"tipo": "correo_equipo", "mensaje_id": 30}, "/correo/equipo/30", {"tipo": "correo", "id": 30}),
    ("correo_nuevo", {"tipo": "correo_nuevo", "cuenta_id": 2}, "/correo/?cuenta_id=2", {"tipo": "correo", "cuenta_id": 2}),
    ("ausencia", {"tipo": "ausencia"}, "/fichaje/ausencias/equipo", {"tipo": "ausencias"}),
    ("fichaje_salida_olvidada", {"tipo": "fichaje_salida_olvidada"}, "/fichaje/", {"tipo": "fichaje"}),
    ("resumen_diario", {"tipo": "resumen_diario"}, "/tareas/hoy", {"tipo": "hoy"}),
    ("automatizacion", None, "/tareas/automatizaciones", {"tipo": "aviso"}),
    ("prueba", None, None, {"tipo": "aviso"}),
])
def test_destino_de(tipo, datos, url, esperado):
    assert ad.destino_de(tipo, datos, url) == esperado


def test_cada_tipo_conocido_tiene_un_canal_valido():
    for tipo in ("tarea_asignada", "correo_nuevo", "vencimiento_fiscal", "ausencia", "resumen_diario", "algo_nuevo"):
        assert ad.canal_de(tipo) in ad.CANALES
    assert ad.canal_de("correo_nuevo") == "correo" and ad.canal_de("ausencia") == "equipo" and ad.canal_de("algo_nuevo") == "general"
    # el tipo de `datos` es más específico que el de la fila (p. ej. fila `tarea_asignada`, aviso real de correo del equipo)
    assert ad.canal_de("correo_equipo") == "correo"


def test_el_push_lleva_el_contrato_unificado(cliente, monkeypatch):
    uid = db.obtener_usuario_por_email(_registrar(cliente, "push@ejemplo.com") and "push@ejemplo.com")["id"]
    t = db.crear_tenant("Despacho push")
    db.asignar_tenant(uid, t)
    enviado = {}
    monkeypatch.setattr(push, "enviar_a_usuario", lambda u, titulo, cuerpo, datos=None, ignorar_silencio=False, canal=None: enviado.update(u=u, datos=datos, canal=canal))
    notificaciones.crear_y_enviar(uid, "tarea_asignada", "Te asignan", "Llamar", url="/tareas/12", datos={"tipo": "tarea_recordatorio", "tarea_id": 12})
    d = enviado["datos"]
    assert d["tipo"] == "tarea_recordatorio" and d["tarea_id"] == 12                     # lo que ya mandaba quien emite, intacto
    assert json.loads(d["destino"]) == {"tipo": "tarea", "id": 12} and d["destino_tipo"] == "tarea" and d["destino_id"] == 12
    assert d["despacho_id"] == t and d["canal"] == "tareas" and enviado["canal"] == "tareas"
    assert d["notificacion_id"] == db.listar_notificaciones(uid, 1)[0]["id"]


def test_un_aviso_sin_datos_tambien_lleva_tipo_y_destino(cliente, monkeypatch):
    uid = db.obtener_usuario_por_email(_registrar(cliente, "sindatos@ejemplo.com") and "sindatos@ejemplo.com")["id"]
    enviado = {}
    monkeypatch.setattr(push, "enviar_a_usuario", lambda u, titulo, cuerpo, datos=None, **k: enviado.update(datos=datos))
    notificaciones.crear_y_enviar(uid, "correo_envio_fallido", "No se pudo enviar", "x", "/correo/redactar?borrador_id=3")
    assert enviado["datos"]["tipo"] == "correo_envio_fallido" and enviado["datos"]["canal"] == "correo"
    assert json.loads(enviado["datos"]["destino"]) == {"tipo": "correo"}


def test_la_bandeja_de_avisos_trae_destino_y_filtros(cliente, monkeypatch):
    datos = _registrar(cliente, "bandeja@ejemplo.com")
    h = _auth(datos["token"])
    uid = db.obtener_usuario_por_email("bandeja@ejemplo.com")["id"]
    monkeypatch.setattr(push, "enviar_a_usuario", lambda *a, **k: None)
    notificaciones.crear_y_enviar(uid, "tarea_asignada", "Tarea", "a", url="/tareas/4")
    notificaciones.crear_y_enviar(uid, "ausencia", "Ausencia", "b", url="/fichaje/ausencias/equipo")
    todas = cliente.get("/api/v1/notificaciones", headers=h).get_json()["data"]
    por_tipo = {n["tipo"]: n for n in todas["notificaciones"]}
    assert por_tipo["tarea_asignada"]["destino"] == {"tipo": "tarea", "id": 4} and por_tipo["tarea_asignada"]["canal"] == "tareas"
    assert por_tipo["ausencia"]["destino"] == {"tipo": "ausencias"} and por_tipo["ausencia"]["canal"] == "equipo"
    solo = cliente.get("/api/v1/notificaciones?tipo=ausencia", headers=h).get_json()["data"]["notificaciones"]
    assert [n["tipo"] for n in solo] == ["ausencia"]
    assert cliente.get("/api/v1/notificaciones?desde=2999-01-01T00:00", headers=h).get_json()["data"]["notificaciones"] == []
    cliente.post("/api/v1/notificaciones/leidas", headers=h)
    assert cliente.get("/api/v1/notificaciones?no_leidas=1", headers=h).get_json()["data"]["notificaciones"] == []
