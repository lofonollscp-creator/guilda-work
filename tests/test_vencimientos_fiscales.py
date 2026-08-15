"""Capa BD del calendario fiscal: CRUD de clientes_fiscales/vencimientos_fiscales
y el generador de propuestas de app/vencimientos_fiscales.py."""
import datetime

from app import db
from app.vencimientos_fiscales import generar_vencimientos_propuestos


def _tenant_con_cliente(nombre_tenant="Gestoria", nombre_cliente="Cliente") -> tuple[int, int]:
    tenant_id = db.crear_tenant(nombre_tenant)
    cliente_id = db.crear_cliente_fiscal(tenant_id, nombre_cliente)
    return tenant_id, cliente_id


def test_crear_y_listar_cliente_fiscal():
    tenant_id, cliente_id = _tenant_con_cliente()
    clientes = db.listar_clientes_fiscales(tenant_id)
    assert len(clientes) == 1
    assert clientes[0]["id"] == cliente_id
    assert clientes[0]["nombre"] == "Cliente"


def test_editar_cliente_fiscal():
    tenant_id, cliente_id = _tenant_con_cliente()
    db.editar_cliente_fiscal(tenant_id, cliente_id, nombre="Cliente Renombrado", nif="B00000000")
    cliente = db.obtener_cliente_fiscal(tenant_id, cliente_id)
    assert cliente["nombre"] == "Cliente Renombrado"
    assert cliente["nif"] == "B00000000"


def test_eliminar_cliente_fiscal_es_borrado_suave():
    tenant_id, cliente_id = _tenant_con_cliente()
    db.eliminar_cliente_fiscal(tenant_id, cliente_id)
    assert db.obtener_cliente_fiscal(tenant_id, cliente_id) is None
    assert db.listar_clientes_fiscales(tenant_id) == []


def test_crear_editar_y_marcar_presentado_vencimiento():
    tenant_id, cliente_id = _tenant_con_cliente()
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T2", "2026-07-20")
    v = db.obtener_vencimiento_fiscal(tenant_id, v_id)
    assert v["estado"] == "pendiente"
    assert v["cliente_nombre"] == "Cliente"

    db.editar_vencimiento_fiscal(tenant_id, v_id, notas="revisar con el cliente")
    assert db.obtener_vencimiento_fiscal(tenant_id, v_id)["notas"] == "revisar con el cliente"

    db.marcar_presentado_vencimiento_fiscal(tenant_id, v_id)
    assert db.obtener_vencimiento_fiscal(tenant_id, v_id)["estado"] == "presentado"


def test_eliminar_vencimiento_es_borrado_suave():
    tenant_id, cliente_id = _tenant_con_cliente()
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T2", "2026-07-20")
    db.eliminar_vencimiento_fiscal(tenant_id, v_id)
    assert db.obtener_vencimiento_fiscal(tenant_id, v_id) is None


def test_listar_vencimientos_filtra_por_estado_cliente_y_fechas():
    tenant_id, cliente_a = _tenant_con_cliente(nombre_cliente="Cliente A")
    cliente_b = db.crear_cliente_fiscal(tenant_id, "Cliente B")

    v1 = db.crear_vencimiento_fiscal(tenant_id, cliente_a, "303", "2026-T1", "2026-04-20")
    v2 = db.crear_vencimiento_fiscal(tenant_id, cliente_a, "303", "2026-T2", "2026-07-20")
    v3 = db.crear_vencimiento_fiscal(tenant_id, cliente_b, "130", "2026-T1", "2026-04-20")
    db.marcar_presentado_vencimiento_fiscal(tenant_id, v1)

    assert {v["id"] for v in db.listar_vencimientos_fiscales(tenant_id)} == {v1, v2, v3}
    assert {v["id"] for v in db.listar_vencimientos_fiscales(tenant_id, estado="presentado")} == {v1}
    assert {v["id"] for v in db.listar_vencimientos_fiscales(tenant_id, cliente_fiscal_id=cliente_b)} == {v3}
    assert {v["id"] for v in db.listar_vencimientos_fiscales(tenant_id, desde="2026-05-01")} == {v2}
    assert {v["id"] for v in db.listar_vencimientos_fiscales(tenant_id, hasta="2026-05-01")} == {v1, v3}


def test_vencimientos_fiscales_proximos_cruza_tenants_y_respeta_ventana():
    tenant_a, cliente_a = _tenant_con_cliente("Gestoria A", "Cliente A")
    tenant_b, cliente_b = _tenant_con_cliente("Gestoria B", "Cliente B")
    usuario_a = db.crear_usuario_vinculado_a_kratos("prox-a@ejemplo.com", "kratos-a")
    usuario_b = db.crear_usuario_vinculado_a_kratos("prox-b@ejemplo.com", "kratos-b")

    hoy = datetime.date.today()
    cerca = (hoy + datetime.timedelta(days=2)).isoformat()
    lejos = (hoy + datetime.timedelta(days=30)).isoformat()

    v_cerca_a = db.crear_vencimiento_fiscal(tenant_a, cliente_a, "303", "T", cerca, usuario_id=usuario_a)
    v_cerca_b = db.crear_vencimiento_fiscal(tenant_b, cliente_b, "303", "T", cerca, usuario_id=usuario_b)
    v_lejos = db.crear_vencimiento_fiscal(tenant_a, cliente_a, "390", "anual", lejos, usuario_id=usuario_a)
    # Sin usuario asignado -- debe aparecer igualmente en la consulta (el
    # filtrado de "a quién avisar" es cosa de quien llama, no de esta query).
    v_sin_asignar = db.crear_vencimiento_fiscal(tenant_a, cliente_a, "111", "T", cerca)

    ids = {v["id"] for v in db.vencimientos_fiscales_proximos(dias=7)}
    assert ids == {v_cerca_a, v_cerca_b, v_sin_asignar}
    assert v_lejos not in ids


def test_generar_vencimientos_propuestos_trimestral_rueda_a_enero_siguiente():
    propuestas = generar_vencimientos_propuestos(["303"], 2026)
    assert len(propuestas) == 4
    por_periodo = {p["periodo"]: p["fecha_limite"] for p in propuestas}
    assert por_periodo["2026-T1"] == "2026-04-20"
    assert por_periodo["2026-T2"] == "2026-07-20"
    assert por_periodo["2026-T3"] == "2026-10-20"
    assert por_periodo["2026-T4"] == "2027-01-30"  # T4 cae en enero del año siguiente


def test_generar_vencimientos_propuestos_retenciones_t4_es_dia_20_no_30():
    propuestas = generar_vencimientos_propuestos(["111"], 2026)
    por_periodo = {p["periodo"]: p["fecha_limite"] for p in propuestas}
    assert por_periodo["2026-T4"] == "2027-01-20"


def test_generar_vencimientos_propuestos_anuales():
    propuestas = generar_vencimientos_propuestos(["390", "200"], 2026)
    por_modelo = {p["modelo"]: p["fecha_limite"] for p in propuestas}
    assert por_modelo["390"] == "2027-01-30"
    assert por_modelo["200"] == "2027-07-25"


def test_generar_vencimientos_propuestos_modelo_desconocido_se_ignora():
    assert generar_vencimientos_propuestos(["999-no-existe"], 2026) == []


def test_generar_vencimientos_propuestos_no_escribe_en_bd():
    tenant_id, cliente_id = _tenant_con_cliente()
    generar_vencimientos_propuestos(["303"], 2026)
    assert db.listar_vencimientos_fiscales(tenant_id) == []


def test_restaurar_cliente_fiscal_lo_devuelve_a_la_lista():
    tenant_id, cliente_id = _tenant_con_cliente()
    db.eliminar_cliente_fiscal(tenant_id, cliente_id)
    assert db.listar_clientes_fiscales(tenant_id) == []
    db.restaurar_cliente_fiscal(tenant_id, cliente_id)
    assert [c["id"] for c in db.listar_clientes_fiscales(tenant_id)] == [cliente_id]


def test_eliminar_cliente_fiscal_definitivamente_no_se_puede_restaurar():
    tenant_id, cliente_id = _tenant_con_cliente()
    db.eliminar_cliente_fiscal(tenant_id, cliente_id)
    db.eliminar_cliente_fiscal_definitivamente(tenant_id, cliente_id)
    db.restaurar_cliente_fiscal(tenant_id, cliente_id)  # no debe fallar aunque ya no exista
    assert db.listar_clientes_fiscales(tenant_id) == []


def test_restaurar_y_eliminar_definitivamente_vencimiento():
    tenant_id, cliente_id = _tenant_con_cliente()
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T2", "2026-07-20")
    db.eliminar_vencimiento_fiscal(tenant_id, v_id)
    assert db.obtener_vencimiento_fiscal(tenant_id, v_id) is None

    db.restaurar_vencimiento_fiscal(tenant_id, v_id)
    assert db.obtener_vencimiento_fiscal(tenant_id, v_id) is not None

    db.eliminar_vencimiento_fiscal(tenant_id, v_id)
    db.eliminar_vencimiento_fiscal_definitivamente(tenant_id, v_id)
    db.restaurar_vencimiento_fiscal(tenant_id, v_id)  # no debe fallar aunque ya no exista
    assert db.obtener_vencimiento_fiscal(tenant_id, v_id) is None


def test_papelera_fiscal_lista_clientes_y_vencimientos_eliminados():
    tenant_id, cliente_id = _tenant_con_cliente()
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T2", "2026-07-20")
    otro_cliente = db.crear_cliente_fiscal(tenant_id, "Otro cliente")

    assert db.papelera_fiscal(tenant_id) == []

    db.eliminar_vencimiento_fiscal(tenant_id, v_id)
    db.eliminar_cliente_fiscal(tenant_id, otro_cliente)

    items = db.papelera_fiscal(tenant_id)
    origenes = {(i["origen"], i["id"]) for i in items}
    assert ("vencimiento_fiscal", v_id) in origenes
    assert ("cliente_fiscal", otro_cliente) in origenes
    # El cliente activo (no eliminado) no aparece en su propia papelera.
    assert cliente_id not in {i["id"] for i in items if i["origen"] == "cliente_fiscal"}


def test_papelera_fiscal_aisla_por_tenant():
    tenant_a, cliente_a = _tenant_con_cliente("Gestoria A", "Cliente A")
    tenant_b, cliente_b = _tenant_con_cliente("Gestoria B", "Cliente B")
    db.eliminar_cliente_fiscal(tenant_a, cliente_a)
    db.eliminar_cliente_fiscal(tenant_b, cliente_b)

    assert {i["id"] for i in db.papelera_fiscal(tenant_a)} == {cliente_a}
    assert {i["id"] for i in db.papelera_fiscal(tenant_b)} == {cliente_b}


def test_modelos_fiscales_se_guardan_y_se_leen():
    tenant_id, cliente_id = _tenant_con_cliente()
    cliente = db.obtener_cliente_fiscal(tenant_id, cliente_id)
    assert db.modelos_fiscales_de_cliente(cliente) == []

    tenant_id2 = db.crear_tenant("Gestoria Modelos")
    c2 = db.crear_cliente_fiscal(tenant_id2, "Con modelos", modelos_fiscales=["303", "130"])
    assert db.modelos_fiscales_de_cliente(db.obtener_cliente_fiscal(tenant_id2, c2)) == ["303", "130"]

    db.editar_cliente_fiscal(tenant_id2, c2, modelos_fiscales=db.serializar_modelos_fiscales(["390"]))
    assert db.modelos_fiscales_de_cliente(db.obtener_cliente_fiscal(tenant_id2, c2)) == ["390"]


def test_listar_clientes_fiscales_filtra_por_nombre_o_nif():
    tenant_id, _ = _tenant_con_cliente(nombre_cliente="Panaderia SL")
    db.crear_cliente_fiscal(tenant_id, "Ferreteria Lopez", nif="B12345678")

    assert {c["nombre"] for c in db.listar_clientes_fiscales(tenant_id, q="panad")} == {"Panaderia SL"}
    assert {c["nombre"] for c in db.listar_clientes_fiscales(tenant_id, q="B12345678")} == {"Ferreteria Lopez"}
    assert db.listar_clientes_fiscales(tenant_id, q="no-existe-nada") == []


def test_generar_vencimientos_automaticos_solo_para_clientes_opt_in_con_modelos():
    tenant_id, _ = _tenant_con_cliente()
    con_auto = db.crear_cliente_fiscal(tenant_id, "Con Auto", modelos_fiscales=["390"])
    db.editar_cliente_fiscal(tenant_id, con_auto, generacion_automatica=1)
    sin_auto = db.crear_cliente_fiscal(tenant_id, "Sin Auto", modelos_fiscales=["390"])
    auto_sin_modelos = db.crear_cliente_fiscal(tenant_id, "Auto Sin Modelos")
    db.editar_cliente_fiscal(tenant_id, auto_sin_modelos, generacion_automatica=1)

    creados = db.generar_vencimientos_automaticos()
    assert creados > 0
    assert len(db.listar_vencimientos_fiscales(tenant_id, cliente_fiscal_id=con_auto)) > 0
    assert db.listar_vencimientos_fiscales(tenant_id, cliente_fiscal_id=sin_auto) == []
    assert db.listar_vencimientos_fiscales(tenant_id, cliente_fiscal_id=auto_sin_modelos) == []


def test_generar_vencimientos_automaticos_es_idempotente():
    tenant_id, _ = _tenant_con_cliente()
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Recurrente", modelos_fiscales=["303"])
    db.editar_cliente_fiscal(tenant_id, cliente_id, generacion_automatica=1)

    creados_1 = db.generar_vencimientos_automaticos()
    assert creados_1 > 0
    total_tras_primera = len(db.listar_vencimientos_fiscales(tenant_id, cliente_fiscal_id=cliente_id))

    creados_2 = db.generar_vencimientos_automaticos()
    assert creados_2 == 0
    assert len(db.listar_vencimientos_fiscales(tenant_id, cliente_fiscal_id=cliente_id)) == total_tras_primera


def test_sanear_vencimientos_fuera_plazo_marca_solo_lo_pendiente_vencido():
    tenant_id, cliente_id = _tenant_con_cliente()
    v_vencido = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2020-T1", "2020-04-20")
    v_futuro = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2099-T1", "2099-04-20")
    v_presentado = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2020-T2", "2020-07-20")
    db.marcar_presentado_vencimiento_fiscal(tenant_id, v_presentado)

    saneados = db.sanear_vencimientos_fuera_plazo()
    assert saneados == 1
    assert db.obtener_vencimiento_fiscal(tenant_id, v_vencido)["estado"] == "fuera_plazo"
    assert db.obtener_vencimiento_fiscal(tenant_id, v_futuro)["estado"] == "pendiente"
    # Uno ya presentado no se toca aunque su fecha haya pasado -- no tiene
    # sentido marcarlo "fuera de plazo" si ya se presentó.
    assert db.obtener_vencimiento_fiscal(tenant_id, v_presentado)["estado"] == "presentado"


def test_vencimientos_fiscales_proximos_excluye_lo_ya_avisado():
    tenant_id, cliente_id = _tenant_con_cliente()
    usuario_id = db.crear_usuario_vinculado_a_kratos("dedup@ejemplo.com", "kratos-dedup")
    cerca = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "T", cerca, usuario_id=usuario_id)

    assert v_id in {v["id"] for v in db.vencimientos_fiscales_proximos(dias=7)}

    db.marcar_recordatorio_vencimiento_fiscal_enviado(v_id)
    assert v_id not in {v["id"] for v in db.vencimientos_fiscales_proximos(dias=7)}
