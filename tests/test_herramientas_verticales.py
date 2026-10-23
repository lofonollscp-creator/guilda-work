"""Herramientas de solo lectura de Gabinete de abogados e Inmobiliaria para el MCP y el asistente de IA (mcp_tools/herramientas_verticales.py)."""
from datetime import datetime, timedelta

import pytest

import mcp_tools
from app import abogados as ab
from app import db, herramientas_grupos as hg, ia_herramientas as ih, inmobiliaria as im, nucleo, verticales

ABOGADOS = ("abogados_provision_asunto", "abogados_partes_asunto", "abogados_agenda_vistas", "abogados_comprobar_conflicto")
INMOBILIARIA = ("inmobiliaria_listar_inmuebles", "inmobiliaria_cruces_de_demanda", "inmobiliaria_agenda_visitas", "inmobiliaria_resumen")


def _despacho(nombre, modulo, n=2):
    t = db.crear_tenant(nombre)
    us = []
    for i in range(n):
        u = db.crear_usuario_vinculado_a_kratos(f"{nombre.lower().replace(' ', '')}-{i}@ejemplo.com", f"kratos-{nombre}-{i}")
        db.asignar_tenant(u, t)
        us.append(u)
    if modulo:
        verticales.fijar_activo(t, modulo, True)
    return t, us


def test_son_de_lectura_sin_confirmacion_estan_en_su_grupo_y_en_el_mcp():
    for n in ABOGADOS + INMOBILIARIA:
        assert n in ih.LECTURA and not ih.necesita_confirmacion(n, modo_autonomo=False)
        assert hg.grupo_de(n) == "verticales"
        assert any(t.__name__ == n for t in mcp_tools.TOOLS)


def test_sin_el_modulo_activo_no_funcionan(usuario_id):
    t, (u1, _) = _despacho("Sin modulos", None)
    for n, args in (("abogados_agenda_vistas", {}), ("inmobiliaria_resumen", {})):
        with pytest.raises(ih.ErrorHerramientaIA, match="no está activo"):
            ih.ejecutar(u1, n, args)


def test_gabinete_cuenta_partes_agenda_y_conflictos(usuario_id):
    t, (u1, u2) = _despacho("Bufete IA", "abogados")
    c = nucleo.crear_cliente(t, "Cliente Uno S.L.", nif="B12345678")
    x = nucleo.crear_expediente(t, u1, c, "Reclamación", tipo="procedimiento_judicial")
    ab.registrar_movimiento(t, u1, x, "provision", "1.000,00", "Provisión inicial", "2026-10-01")
    ab.registrar_movimiento(t, u1, x, "suplido", "150,50", "Tasa judicial")
    ab.guardar_ajustes(t, serie="M", iva_pct=21, irpf_pct=15, bloque_minutos=6, provision_minima_centimos=100000, plantilla_encargo="")
    r = ih.ejecutar(u1, "abogados_provision_asunto", {"expediente_id": x})
    assert r["saldo_centimos"] == 84950 and r["por_debajo_de_la_minima"] is True and r["provisiones"] == "1.000,00 €"
    assert {m["concepto"] for m in r["ultimos_movimientos"]} == {"Provisión inicial", "Tasa judicial"}

    ab.anadir_parte(t, u1, x, "contraparte", "Deudores Asociados S.A.", "A11111111")
    assert [(p["rol"], p["nif"]) for p in ih.ejecutar(u1, "abogados_partes_asunto", {"expediente_id": x})] == [("contraparte", "A11111111")]

    manana = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%dT10:00")
    ab.crear_vista(t, u1, x, manana, "juicio", "Sala 3")
    lejos = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%dT10:00")
    ab.crear_vista(t, u1, x, lejos, "vista")
    assert [v["lugar"] for v in ih.ejecutar(u1, "abogados_agenda_vistas", {"dias": 30})] == ["Sala 3"]
    assert len(ih.ejecutar(u1, "abogados_agenda_vistas", {"dias": 120, "expediente_id": x})) == 2

    r = ih.ejecutar(u1, "abogados_comprobar_conflicto", {"nombre": "Deudores Asociados S.A.", "nif": "A11111111"})
    assert r["hay_conflicto"] is True and r["hallazgos"]
    assert ih.ejecutar(u1, "abogados_comprobar_conflicto", {"nombre": "Nadie Conocido"})["hay_conflicto"] is False
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(u1, "abogados_comprobar_conflicto", {"nombre": "x", "como": "tercero"})


def test_gabinete_respeta_confidenciales_y_otros_despachos(usuario_id):
    t, (u1, u2) = _despacho("Bufete Conf IA", "abogados")
    c = nucleo.crear_cliente(t, "Cliente")
    x = nucleo.crear_expediente(t, u1, c, "Reservado", tipo="procedimiento_judicial", confidencial=True)
    ab.registrar_movimiento(t, u1, x, "provision", 1000, "Secreto")
    ab.anadir_parte(t, u1, x, "contraparte", "Parte secreta")
    ab.crear_vista(t, u1, x, (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT10:00"), "vista")
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(u2, "abogados_provision_asunto", {"expediente_id": x})
    assert ih.ejecutar(u2, "abogados_partes_asunto", {"expediente_id": x}) == []
    assert ih.ejecutar(u2, "abogados_agenda_vistas", {}) == []
    t2, (o,) = _despacho("Otro Bufete", "abogados", 1)
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(o, "abogados_provision_asunto", {"expediente_id": x})


def test_inmobiliaria_inmuebles_cruces_visitas_y_resumen(usuario_id):
    t, (u1, u2) = _despacho("Agencia IA", "inmobiliaria")
    prop = nucleo.crear_cliente(t, "Propietario Pérez", nif="12345678Z")
    i1, x1 = im.crear_inmueble(t, u1, prop, "venta", "Calle Uno 1", municipio="Madrid", tipo="piso", superficie_m2=90, habitaciones=3, banos=2, precio="250.000")
    i2, x2 = im.crear_inmueble(t, u1, prop, "alquiler", "Calle Dos 2", municipio="Sitges", tipo="piso", precio="900")
    for x in (x1, x2):
        for e in ("valoracion", "mandato", "publicado"):
            nucleo.cambiar_estado_expediente(t, u1, x, e)
    ls = ih.ejecutar(u1, "inmobiliaria_listar_inmuebles", {"operacion": "venta"})
    assert [i["direccion"] for i in ls] == ["Calle Uno 1"] and ls[0]["precio"] == "250.000,00 €" and ls[0]["propietario_nombre"] == "Propietario Pérez"
    assert {i["direccion"] for i in ih.ejecutar(u1, "inmobiliaria_listar_inmuebles", {})} == {"Calle Uno 1", "Calle Dos 2"}
    assert [i["direccion"] for i in ih.ejecutar(u1, "inmobiliaria_listar_inmuebles", {"municipio": "Sitges"})] == ["Calle Dos 2"]

    d = im.crear_demanda(t, u1, nucleo.crear_cliente(t, "Comprador"), "venta", municipios=["Madrid"], presupuesto_max="300.000", habitaciones_min=2)
    cr = ih.ejecutar(u1, "inmobiliaria_cruces_de_demanda", {"demanda_id": d, "minimo": 1})
    assert cr and cr[0]["inmueble"]["direccion"] == "Calle Uno 1" and cr[0]["puntos"] > 0 and cr[0]["motivos"]

    im.crear_visita(t, u1, i1, (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT11:00"), visitante="Visitante Uno")
    im.crear_visita(t, u1, i1, (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%dT11:00"), visitante="Lejano")
    assert [v["visitante_nombre"] for v in ih.ejecutar(u1, "inmobiliaria_agenda_visitas", {"dias": 7})] == ["Visitante Uno"]
    im.registrar_oferta(t, u1, i1, "240.000", oferente="Oferente")
    r = ih.ejecutar(u1, "inmobiliaria_resumen", {})
    assert r["inmuebles_activos"] == 2 and r["demandas_activas"] == 1 and len(r["ofertas_abiertas"]) == 1
    assert [i["direccion"] for i in r["sin_movimiento_14_dias"]] == ["Calle Dos 2"]


def test_inmobiliaria_no_enseña_confidenciales_ni_otras_agencias(usuario_id):
    t, (u1, u2) = _despacho("Agencia Conf IA", "inmobiliaria")
    prop = nucleo.crear_cliente(t, "P")
    i1, x1 = im.crear_inmueble(t, u1, prop, "venta", "Calle Reservada 9", precio="100.000")
    _c = db.get_connection(); _c.execute("UPDATE expedientes SET confidencial = 1 WHERE id = ?", (x1,));  _c.commit(); _c.close()
    assert ih.ejecutar(u1, "inmobiliaria_listar_inmuebles", {}) and ih.ejecutar(u2, "inmobiliaria_listar_inmuebles", {}) == []
    t2, (o,) = _despacho("Otra Agencia", "inmobiliaria", 1)
    assert ih.ejecutar(o, "inmobiliaria_listar_inmuebles", {}) == []
