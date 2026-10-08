"""Backoffice: seguimiento de la salud de los clientes (histórico, tendencia, siguiente paso, contactos y silencio)."""
from datetime import date, datetime, timedelta

import pytest

from app import db
from backoffice import auth, cartera, seguimiento
from tests.test_backoffice_app import bo, entrar, post  # noqa: F401 -- fixture


def _tenant(nombre, email, activo=True):
    t = db.crear_tenant(nombre)
    uid = db.crear_usuario_vinculado_a_kratos(email, "kratos-" + email)
    db.asignar_tenant(uid, t)
    return t, uid


def _actividad(uid, n, dias_atras):
    """n notas creadas hace `dias_atras` días."""
    conn = db.get_connection()
    for _ in range(n):
        conn.execute("INSERT INTO notas (usuario_id, texto, creada_en) VALUES (?, 'x', ?)", (uid, (datetime.now() - timedelta(days=dias_atras)).isoformat(timespec="seconds")))
    conn.commit()
    conn.close()


def test_tendencia_compara_dos_semanas_con_las_dos_anteriores():
    t, uid = _tenant("Tendencia", "tend@ejemplo.com")
    _actividad(uid, 3, 2)          # últimas dos semanas
    _actividad(uid, 12, 20)        # las dos anteriores
    _actividad(uid, 50, 60)        # demasiado antiguo: no cuenta
    r = seguimiento.tendencia_uso(t)
    assert (r["actual"], r["anterior"], r["variacion"]) == (3, 12, -75) and seguimiento.cae_el_uso(r)
    t2, uid2 = _tenant("Nueva", "nueva@ejemplo.com")
    _actividad(uid2, 4, 1)
    r2 = seguimiento.tendencia_uso(t2)
    assert (r2["actual"], r2["anterior"], r2["variacion"]) == (4, 0, None) and not seguimiento.cae_el_uso(r2)
    assert seguimiento.tendencia_uso(db.crear_tenant("Vacío"))["variacion"] is None


def test_historial_diario_idempotente_y_variacion(bo):
    t, uid = _tenant("Historial", "hist@ejemplo.com")
    _actividad(uid, 1, 0)
    hoy = date.today()
    assert seguimiento.tomar_historial(hoy) is True and seguimiento.tomar_historial(hoy) is False
    fila = seguimiento.historial(t)[0]
    assert fila["fecha"] == hoy.isoformat() and fila["puntos"] is not None
    # foto antigua inventada: hace 8 días tenía 20 puntos
    conn = auth.conectar()
    conn.execute("INSERT INTO salud_historial (fecha, tenant_id, puntos, nivel) VALUES (?, ?, 20, 'riesgo')", ((hoy - timedelta(days=8)).isoformat(), t))
    conn.commit()
    conn.close()
    serie = seguimiento.historial(t)
    assert seguimiento.variacion_puntos(fila["puntos"], serie) == fila["puntos"] - 20
    assert seguimiento.variacion_puntos(fila["puntos"], serie[1:]) is None            # sin foto de hace una semana: no se inventa
    assert seguimiento.variacion_puntos(None, serie) is None


def test_la_pasada_periodica_guarda_el_historial(bo):
    _tenant("Periódica", "per@ejemplo.com")
    r = cartera.paso_periodico(datetime.now())
    assert r["errores"] == [] and r["salud"] is True
    assert cartera.paso_periodico(datetime.now())["salud"] is False


def test_siguiente_paso_segun_lo_que_mas_pesa():
    t, uid = _tenant("Pasos", "pasos@ejemplo.com")
    act = {"funciones": [{"nombre": "Notas", "estado": "nunca usado"}, {"nombre": "Fichaje", "estado": "sin uso reciente"}, {"nombre": "Tareas", "estado": "en uso"}]}
    sin_caida = {"actual": 5, "anterior": 5, "variacion": 0}
    def paso(motivos, nivel="atencion", tendencia=sin_caida):
        return seguimiento.accion_sugerida({"nivel": nivel, "motivos": motivos}, act, tendencia)
    assert "cobro" in paso(["Pago fallido"])
    assert "puesta en marcha" in paso(["Nunca se ha usado"], "riesgo")
    assert "sin usarla" in paso(["Sin actividad desde hace 40 días"], "riesgo")
    assert "ha caído un 60 %" in paso([], tendencia={"actual": 2, "anterior": 5, "variacion": -60})
    assert "Notas, Fichaje" in paso(["Usa muy pocas funciones"])
    assert "suscripción" in paso(["Tiene plan pero no suscripción"])
    assert paso([], "sano") is None
    assert "suspendido" in paso(["Tenant suspendido"], "riesgo")


def test_contacto_y_silencio_afectan_al_resumen_semanal(bo):
    t, uid = _tenant("Silenciado", "sil@ejemplo.com")            # sin actividad: en riesgo
    otro, uid2 = _tenant("Sin silenciar", "nosil@ejemplo.com")
    r = cartera.construir_resumen()
    assert {f["nombre"] for f in r["riesgo"]} >= {"Silenciado", "Sin silenciar"} and r["en_seguimiento"] == []
    with pytest.raises(ValueError):
        seguimiento.registrar_contacto(t, "  ", "jorge")
    with pytest.raises(ValueError):
        seguimiento.registrar_contacto(t, "Llamado", "jorge", 365)
    seguimiento.registrar_contacto(t, "Hablé con la gestora; entran el lunes", "jorge", 14)
    seg = seguimiento.obtener(t)
    assert seg["ultimo_contacto"] and seguimiento.silenciado(seg) and seguimiento.silenciados()[t] == seg["posponer_hasta"]
    r = cartera.construir_resumen()
    assert "Silenciado" not in {f["nombre"] for f in r["riesgo"]} and "Sin silenciar" in {f["nombre"] for f in r["riesgo"]}
    assert [f["nombre"] for f in r["en_seguimiento"]] == ["Silenciado"]
    texto = cartera.texto_resumen(r)
    assert "En seguimiento" in texto and "Silenciado (" in texto
    from backoffice import metricas
    assert metricas.notas_tenant(t)[0]["texto"].startswith("Contacto: Hablé con la gestora")      # queda también como nota interna
    seguimiento.reanudar(t, "jorge")
    assert not seguimiento.silenciado(seguimiento.obtener(t)) and seguimiento.silenciados() == {}
    assert "Silenciado" in {f["nombre"] for f in cartera.construir_resumen()["riesgo"]}
    # un contacto sin silencio no silencia
    seguimiento.registrar_contacto(otro, "Solo un correo", "jorge")
    assert not seguimiento.silenciado(seguimiento.obtener(otro)) and seguimiento.obtener(otro)["ultimo_contacto"]


def test_ranking_ordena_filtra_y_resume(bo):
    sano, usano = _tenant("Muy sano", "sano@ejemplo.com")
    _actividad(usano, 5, 0)
    malo, _ = _tenant("Muy parado", "parado@ejemplo.com")
    db.crear_tenant("Sin usuarios")
    r = seguimiento.ranking()
    nombres = [f["nombre"] for f in r["filas"]]
    assert nombres.index("Muy parado") < nombres.index("Muy sano") and nombres[-1] == "Sin usuarios"            # peores primero, nuevos al final
    assert sum(r["cuenta"].values()) == len(nombres)
    parado = next(f for f in r["filas"] if f["nombre"] == "Muy parado")
    assert parado["siguiente"] and parado["variacion"] is None and parado["tendencia"]["actual"] == 0
    solo = seguimiento.ranking("riesgo")
    assert solo["filtro"] == "riesgo" and all(f["nivel"] == "riesgo" for f in solo["filas"])
    assert seguimiento.ranking("inventado")["filtro"] is None


def test_pantallas_y_formularios(bo):
    entrar(bo)
    t, uid = _tenant("Pantalla Salud", "pantalla@ejemplo.com")
    html = bo.get("/salud-clientes").get_data(as_text=True)
    assert "Pantalla Salud" in html and "Siguiente paso" in html and "Salud de clientes" in html
    assert "Pantalla Salud" not in bo.get("/salud-clientes?nivel=sano").get_data(as_text=True)
    ficha = bo.get(f"/tenants/{t}?seccion=actividad").get_data(as_text=True)
    assert "Frente a hace 7 días" in ficha and "Registrar contacto" in ficha and "Siguiente paso" in ficha
    r = post(bo, f"/tenants/{t}/seguimiento/contacto", texto="Le llamé por teléfono", posponer_dias="14")
    assert r.status_code == 302
    ficha = bo.get(f"/tenants/{t}?seccion=actividad").get_data(as_text=True)
    assert "EN SEGUIMIENTO hasta" in ficha and "Le llamé por teléfono" in ficha and "Volver a avisar" in ficha
    assert "EN SEGUIMIENTO hasta" in bo.get("/salud-clientes").get_data(as_text=True)
    assert post(bo, f"/tenants/{t}/seguimiento/contacto", texto="", posponer_dias="0").status_code == 302
    assert post(bo, f"/tenants/{t}/seguimiento/contacto", texto="x", posponer_dias="abc").status_code == 302
    post(bo, f"/tenants/{t}/seguimiento/reanudar")
    assert not seguimiento.silenciado(seguimiento.obtener(t))
    assert post(bo, "/tenants/99999/seguimiento/contacto", texto="x").status_code == 404
    assert post(bo, "/tenants/99999/seguimiento/reanudar").status_code == 404
    acciones = [a["accion"] for a in auth.listar_auditoria(20)]
    assert "tenant.contacto" in acciones and "tenant.seguimiento_fin" in acciones


def test_exige_sesion(bo):
    assert bo.get("/salud-clientes").status_code == 302
    assert bo.post("/tenants/1/seguimiento/contacto", data={}).status_code in (302, 400, 403)
