"""Módulo Inmobiliaria (app/inmobiliaria.py): inmuebles como operaciones, demandas con cruce explicable, visitas, ofertas, contratos con versiones, comisiones y portal del propietario."""
import io
from datetime import date, datetime, timedelta

import pytest

from app import almacen_documentos as alm
from app import db, nucleo, verticales
from app import inmobiliaria as im


def _agencia(nombre="Agencia", n=2, modulo=True):
    t = db.crear_tenant(nombre)
    us = []
    for i in range(n):
        u = db.crear_usuario_vinculado_a_kratos(f"{nombre.lower()}-{i}@ejemplo.com", f"kratos-{nombre}-{i}")
        db.asignar_tenant(u, t)
        us.append(u)
    if modulo:
        verticales.fijar_activo(t, "inmobiliaria", True)
    return t, us


def _piso(t, u, operacion="venta", direccion="Calle Mayor 12, 3º B", precio="250.000", propietario=None, **kw):
    prop = propietario or nucleo.crear_cliente(t, "Propietario Pérez", nif="12345678Z")
    datos = {"municipio": "Madrid", "tipo": "piso", "superficie_m2": 90, "habitaciones": 3, "banos": 2, "caracteristicas": ["ascensor", "terraza"], "precio": precio, **kw}
    iid, xid = im.crear_inmueble(t, u, prop, operacion, direccion, **datos)
    return prop, iid, xid


def _publicar(t, u, xid):
    for e in ("valoracion", "mandato", "publicado"):
        nucleo.cambiar_estado_expediente(t, u, xid, e)


# --- cálculos puros -------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("op,estado,esperado", [("venta", "contacto", "captacion"), ("venta", "mandato", "captacion"), ("venta", "publicado", "en_venta"), ("alquiler", "visitas", "en_alquiler"),
                                                ("venta", "reserva", "reservado"), ("venta", "cerrada", "vendido"), ("alquiler", "cerrada", "alquilado"), ("venta", "perdida", "retirado")])
def test_estado_comercial_segun_la_fase(op, estado, esperado):
    assert im.estado_comercial(op, estado) == esperado


@pytest.mark.parametrize("base,bp,minimo,iva,esperado", [
    (25000000, 300, 0, 21, {"honorarios": 750000, "iva": 157500, "total": 907500, "aplicado_minimo": False}),
    (5000000, 300, 300000, 21, {"honorarios": 300000, "iva": 63000, "total": 363000, "aplicado_minimo": True}),      # el mínimo manda
    (90000, 10000, 0, 21, {"honorarios": 90000, "iva": 18900, "total": 108900, "aplicado_minimo": False}),            # alquiler: una mensualidad (100 %)
    (33333, 300, 0, 21, {"honorarios": 1000, "iva": 210, "total": 1210, "aplicado_minimo": False}),
    (0, 300, 0, 21, {"honorarios": 0, "iva": 0, "total": 0, "aplicado_minimo": False}),
])
def test_calculo_de_comision(base, bp, minimo, iva, esperado):
    c = im.calcular_comision(base, bp, minimo, iva)
    assert {k: c[k] for k in esperado} == esperado


@pytest.mark.parametrize("total,reparto", [(100001, [(1, 50), (2, 50)]), (10000, [(1, 60), (2, 40)]), (100, [(1, 33), (2, 33), (3, 34)]), (1, [(1, 50), (2, 50)]), (907500, [(1, 100)])])
def test_el_reparto_no_pierde_ni_inventa_centimos(total, reparto):
    r = im.repartir(total, reparto)
    assert sum(c for _a, c in r) == total and [a for a, _c in r] == [a for a, _p in reparto]
    assert all(c >= 0 for _a, c in r)


@pytest.mark.parametrize("reparto", [[], [(1, 50)], [(1, 60), (2, 60)], [(1, 120), (2, -20)]])
def test_un_reparto_que_no_suma_100_se_rechaza(reparto):
    with pytest.raises(ValueError, match="100"):
        im.repartir(1000, reparto)


def _inm(**kw):
    base = {"tipo": "piso", "municipio": "Madrid", "precio_centimos": 25000000, "superficie_m2": 90, "habitaciones": 3, "banos": 2, "caracteristicas": ["ascensor", "terraza"]}
    return {**base, **kw}


def _dem(**kw):
    base = {"tipos": [], "municipios": [], "presupuesto_min_centimos": None, "presupuesto_max_centimos": None, "superficie_min": None, "habitaciones_min": None, "banos_min": None, "requisitos": []}
    return {**base, **kw}


def test_el_cruce_puntua_y_explica_cada_criterio():
    perfecto = im.puntuar(_dem(tipos=["piso"], municipios=["madrid"], presupuesto_max_centimos=26000000, superficie_min=80, habitaciones_min=3, banos_min=2, requisitos=["ascensor"]), _inm())
    assert perfecto["puntos"] == 100 and perfecto["cumple_todo"] and perfecto["faltan"] == []
    assert {r["criterio"] for r in perfecto["razones"]} >= {"tipo", "zona", "precio", "superficie", "habitaciones", "baños", "requisito:ascensor"}
    assert im.puntuar(_dem(), _inm())["puntos"] == 100, "sin preferencias todo encaja"
    # zona distinta: pierde 25; sin acentos ni mayúsculas
    assert im.puntuar(_dem(municipios=["Móstoles"]), _inm())["puntos"] == 75
    assert im.puntuar(_dem(municipios=["MADRID "]), _inm(municipio="Madrid"))["puntos"] == 100
    assert im.puntuar(_dem(municipios=["alcalá de henares"]), _inm(municipio="Alcalá de Henares"))["puntos"] == 100
    # precio: dentro, hasta un 10 % por encima (mitad), más allá (nada), por debajo del mínimo (mitad)
    assert im.puntuar(_dem(presupuesto_max_centimos=25000000), _inm())["puntos"] == 100
    assert im.puntuar(_dem(presupuesto_max_centimos=23000000), _inm())["puntos"] == 85       # +8,7 %
    assert im.puntuar(_dem(presupuesto_max_centimos=20000000), _inm())["puntos"] == 70       # +25 %
    assert im.puntuar(_dem(presupuesto_min_centimos=30000000), _inm())["puntos"] == 85
    # mínimos de superficie, habitaciones y baños
    assert im.puntuar(_dem(superficie_min=120), _inm())["puntos"] == 90 and im.puntuar(_dem(habitaciones_min=4), _inm())["puntos"] == 90 and im.puntuar(_dem(banos_min=3), _inm())["puntos"] == 95
    # cada requisito que falta resta 8
    falta = im.puntuar(_dem(requisitos=["ascensor", "piscina", "garaje"]), _inm())
    assert falta["puntos"] == 84 and falta["faltan"] == ["piscina", "garaje"] and not falta["cumple_todo"]
    peor = im.puntuar(_dem(tipos=["local"], municipios=["Sevilla"], presupuesto_max_centimos=1000000, superficie_min=500, habitaciones_min=9, banos_min=9, requisitos=["piscina"]), _inm())
    assert peor["puntos"] == 0


# --- inmuebles --------------------------------------------------------------------------------------------------------------------------------
def test_alta_de_un_inmueble_crea_su_operacion(usuario_id):
    t, (u1, u2) = _agencia()
    prop, iid, xid = _piso(t, u1)
    i, x = im.obtener_inmueble(t, u1, iid)
    assert i["referencia"] == f"INM-{date.today().year}-001" and i["precio_centimos"] == 25000000 and i["caracteristicas"] == ["ascensor", "terraza"]
    assert x["tipo"] == "operacion_venta" and x["estado"] == "contacto" and x["cliente_id"] == prop and "Piso en Calle Mayor 12" in x["titulo"]
    assert im.operacion_de(x) == "venta" and im.inmueble_de_expediente(t, u1, xid)[0]["id"] == iid
    assert [p["precio_centimos"] for p in im.historial_precios(iid)] == [25000000]
    _, i2, x2 = _piso(t, u1, "alquiler", "Calle Luna 3", "900,00", propietario=prop)
    assert im.obtener_inmueble(t, u1, i2)[0]["referencia"] == f"INM-{date.today().year}-002" and im.operacion_de(im.obtener_inmueble(t, u1, i2)[1]) == "alquiler"
    for kw in ({"operacion": "permuta"}, {"direccion": " "}, {"tipo": "castillo"}, {"certificado_energetico": "Z"}, {"superficie_m2": "mucha"}, {"precio": "caro"}):
        args = {"operacion": "venta", "direccion": "Calle X", **kw}
        with pytest.raises(ValueError):
            im.crear_inmueble(t, u1, prop, **args)
    otra = db.crear_tenant("Otra agencia")
    with pytest.raises(ValueError):
        im.crear_inmueble(otra, u1, prop, "venta", "Calle Y")


def test_precio_historial_y_edicion(usuario_id):
    t, (u1, _) = _agencia()
    _, iid, xid = _piso(t, u1)
    im.cambiar_precio(t, u1, iid, "239.000,00", "Bajada tras la primera visita")
    im.cambiar_precio(t, u1, iid, "239.000,00")
    assert [p["precio_centimos"] for p in im.historial_precios(iid)] == [23900000, 25000000], "un precio igual no se repite"
    im.editar_inmueble(t, u1, iid, municipio="Getafe", habitaciones="4", caracteristicas=["piscina", "inventada"], certificado_energetico="C", planta="")
    i = im.obtener_inmueble(t, u1, iid)[0]
    assert (i["municipio"], i["habitaciones"], i["caracteristicas"], i["certificado_energetico"], i["planta"]) == ("Getafe", 4, ["piscina"], "C", None)
    for kw in ({"direccion": ""}, {"tipo": "x"}, {"certificado_energetico": "Z"}, {"banos": "-3"}):
        with pytest.raises(ValueError):
            im.editar_inmueble(t, u1, iid, **kw)
    with pytest.raises(ValueError):
        im.cambiar_precio(t, u1, iid, "0")
    assert any(e["tipo"] == "precio" for e in nucleo.linea_de_tiempo(t, u1, xid))


def test_listado_con_filtros_y_permisos(usuario_id):
    t, (u1, u2) = _agencia()
    _, a, xa = _piso(t, u1, direccion="Calle Alcalá 1", municipio="Madrid", precio="300.000")
    _, b, xb = _piso(t, u1, "alquiler", "Calle del Mar 5", "1.000", municipio="Valencia")
    _, c, xc = _piso(t, u1, direccion="Plaza Reservada 9", municipio="Madrid", precio="500.000")
    nucleo.editar_expediente(t, u1, xc, confidencial=True)
    assert {i["id"] for i in im.listar_inmuebles(t, u1)} == {a, b, c} and {i["id"] for i in im.listar_inmuebles(t, u2)} == {a, b}, "el confidencial solo lo ve su gente"
    assert [i["id"] for i in im.listar_inmuebles(t, u1, operacion="alquiler")] == [b]
    assert [i["id"] for i in im.listar_inmuebles(t, u1, municipio="MADRID", precio_max="350.000")] == [a]
    assert [i["id"] for i in im.listar_inmuebles(t, u1, q="alcala")] == [a] and [i["id"] for i in im.listar_inmuebles(t, u1, q="perez")] != []
    _publicar(t, u1, xa)
    assert [i["id"] for i in im.listar_inmuebles(t, u1, estado="publicado")] == [a] and im.listar_inmuebles(t, u1, estado="publicado")[0]["estado_comercial"] == "en_venta"
    nucleo.cambiar_estado_expediente(t, u1, xb, "perdida")
    assert b not in {i["id"] for i in im.listar_inmuebles(t, u1, solo_activos=True)}
    assert im.obtener_inmueble(t, u2, c)[0] is None
    t2, (o,) = _agencia("Otra", 1)
    assert im.obtener_inmueble(t2, o, a)[0] is None and im.listar_inmuebles(t2, o) == []


# --- demandas y cruces ----------------------------------------------------------------------------------------------------------------------
def test_demandas_y_cruces_en_los_dos_sentidos(usuario_id):
    t, (u1, u2) = _agencia()
    _, i1, x1 = _piso(t, u1, direccion="Calle Alcalá 1", precio="250.000")
    _, i2, x2 = _piso(t, u1, direccion="Calle Sol 2", precio="450.000", municipio="Madrid")
    _, i3, x3 = _piso(t, u1, "alquiler", "Calle Luna 3", "900", municipio="Madrid")
    _publicar(t, u1, x1); _publicar(t, u1, x3)             # i2 sigue en captación: no se ofrece
    cli = nucleo.crear_cliente(t, "Comprador Gil")
    d = im.crear_demanda(t, u1, cli, "venta", tipos="piso", municipios="Madrid, Getafe", presupuesto_max="260.000", habitaciones_min=3, requisitos=["ascensor", "piscina"], notas="Con niños")
    dd = im.obtener_demanda(t, d)
    assert dd["tipos"] == ["piso"] and dd["municipios"] == ["Madrid", "Getafe"] and dd["presupuesto_max_centimos"] == 26000000 and dd["requisitos"] == ["ascensor", "piscina"] and dd["cliente_nombre"] == "Comprador Gil"
    por_inmueble = im.cruces_para_inmueble(t, u1, i1)
    assert [c["demanda"]["id"] for c in por_inmueble] == [d] and por_inmueble[0]["puntos"] == 92 and por_inmueble[0]["faltan"] == ["piscina"]
    assert im.cruces_para_inmueble(t, u1, i2) == [] and im.cruces_para_inmueble(t, u1, i3) == [], "ni en captación ni de otra operación"
    por_demanda = im.cruces_para_demanda(t, u1, d)
    assert [c["inmueble"]["id"] for c in por_demanda] == [i1] and any("Piscina" in r["detalle"] and not r["ok"] for r in por_demanda[0]["razones"])
    d2 = im.crear_demanda(t, u1, cli, "venta", tipos="local", municipios="Sevilla", presupuesto_max="10.000")
    assert d2 not in [c["demanda"]["id"] for c in im.cruces_para_inmueble(t, u1, i1)], "bajo el mínimo de 50 puntos no se sugiere"
    assert [c["demanda"]["id"] for c in im.cruces_para_inmueble(t, u1, i1, minimo=0)][0] == d
    im.cambiar_estado_demanda(t, d, "satisfecha")
    assert im.cruces_para_inmueble(t, u1, i1) == []
    assert {x["id"] for x in im.listar_demandas(t, estado=None)} == {d, d2} and [x["id"] for x in im.listar_demandas(t)] == [d2]
    for kw in ({"operacion": "trueque"}, {"presupuesto_min": "500", "presupuesto_max": "100"}, {"habitaciones_min": "muchas"}):
        args = {"operacion": "venta", **kw}
        with pytest.raises(ValueError):
            im.crear_demanda(t, u1, cli, **args)
    with pytest.raises(ValueError):
        im.crear_demanda(t, u1, 999999, "venta")
    with pytest.raises(ValueError):
        im.cambiar_estado_demanda(t, d, "rara")
    t2, _ = _agencia("Otra agencia 2", 1)
    assert im.obtener_demanda(t2, d) is None and im.listar_demandas(t2) == []


# --- visitas y ofertas ------------------------------------------------------------------------------------------------------------------------
def test_visitas_resultado_agenda_y_tareas(usuario_id):
    t, (u1, u2) = _agencia()
    _, iid, xid = _piso(t, u1)
    cli = nucleo.crear_cliente(t, "Visitante Ruiz")
    d = im.crear_demanda(t, u1, cli, "venta")
    manana = (datetime.now() + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0).isoformat(timespec="minutes")
    v = im.crear_visita(t, u1, iid, manana, demanda_id=d, agente_id=u2)
    v2 = im.crear_visita(t, u1, iid, manana, visitante="Pareja sin ficha")
    vistas = im.listar_visitas(t, u1, desde=date.today().isoformat())
    assert {x["id"] for x in vistas} == {v, v2} and vistas[0]["direccion"] and {x["visitante_nombre"] for x in vistas} == {"Visitante Ruiz", "Pareja sin ficha"}
    assert any("Visita:" in tarea["asunto"] for tarea in db.listar_tareas_outlook(u2)), "el agente recibe una tarea"
    assert [x["id"] for x in im.listar_visitas(t, u1, agente_id=u2)] == [v]
    im.registrar_resultado_visita(t, u2, v, "realizada", 4, "alto", "Le encantó la terraza")
    r = [x for x in im.listar_visitas(t, u1, inmueble_id=iid) if x["id"] == v][0]
    assert (r["estado"], r["valoracion"], r["interes"], r["comentario"]) == ("realizada", 4, "alto", "Le encantó la terraza")
    assert [x["id"] for x in im.listar_visitas(t, u1, estado="prevista")] == [v2] and im.mapa_url("Calle Mayor 12", "Madrid").startswith("https://www.openstreetmap.org/search?query=Calle%20Mayor%2012")
    for args in (("realizada", 9), ("inventada", 3), ("realizada", "mala")):
        with pytest.raises(ValueError):
            im.registrar_resultado_visita(t, u1, v, *args)
    with pytest.raises(ValueError, match="fecha"):
        im.crear_visita(t, u1, iid, "pronto", visitante="x")
    with pytest.raises(ValueError, match="quién"):
        im.crear_visita(t, u1, iid, manana)
    im.eliminar_visita(t, u1, v2)
    assert [x["id"] for x in im.listar_visitas(t, u1, inmueble_id=iid)] == [v]
    nucleo.editar_expediente(t, u1, xid, confidencial=True)
    assert im.listar_visitas(t, u2) == []
    with pytest.raises(ValueError):
        im.registrar_resultado_visita(t, u2, v, "realizada")


def test_ofertas(usuario_id):
    t, (u1, u2) = _agencia()
    _, iid, xid = _piso(t, u1)
    cli = nucleo.crear_cliente(t, "Oferente Sanz")
    o1 = im.registrar_oferta(t, u1, iid, "230.000", cliente_id=cli)
    o2 = im.registrar_oferta(t, u1, iid, "235.000,50", oferente="Alguien sin ficha", fecha="2026-10-01")
    assert {o["oferente_nombre"] for o in im.listar_ofertas(t, u1)} == {"Oferente Sanz", "Alguien sin ficha"}
    im.cambiar_estado_oferta(t, u1, o1, "rechazada")
    assert [o["id"] for o in im.listar_ofertas(t, u1, abiertas=True)] == [o2]
    for args in (("0",), ("nada",)):
        with pytest.raises(ValueError):
            im.registrar_oferta(t, u1, iid, args[0], oferente="x")
    with pytest.raises(ValueError, match="quién"):
        im.registrar_oferta(t, u1, iid, "100.000")
    with pytest.raises(ValueError):
        im.cambiar_estado_oferta(t, u1, o2, "negociando")
    with pytest.raises(ValueError):
        im.cambiar_estado_oferta(t, u1, 99999, "aceptada")


# --- contratos --------------------------------------------------------------------------------------------------------------------------------
def test_contratos_con_variables_versiones_y_firma(usuario_id, monkeypatch):
    from app import documenso

    t, (u1, _) = _agencia("Agencia Contratos")
    _, iid, xid = _piso(t, u1, ref_catastral="1234567VK1234A0001XX")
    c1 = im.generar_contrato(t, u1, iid, "arras", parte_nombre="Comprador Gil", parte_nif="87654321X", precio="245.000", arras="24.500", duracion="60 días")
    docs = alm.listar(t, u1, expediente_id=xid)
    assert len(docs) == 1 and docs[0]["categoria"] == "Contrato: Contrato de arras" and docs[0]["nombre_archivo"].endswith("_v1.pdf")
    contenido = alm.leer(t, u1, docs[0]["id"])["contenido"]
    assert contenido.startswith(b"%PDF")
    c2 = im.generar_contrato(t, u1, iid, "arras", parte_nombre="Comprador Gil", parte_nif="87654321X", precio="244.000")
    versiones = {(c["tipo"], c["version"]) for c in im.listar_contratos(t, u1, iid)}
    assert versiones == {("arras", 1), ("arras", 2)} and c1 != c2 and len(alm.listar(t, u1, expediente_id=xid)) == 2, "cada generación conserva la anterior"
    c3 = im.generar_contrato(t, u1, iid, "mandato_venta", parte_nombre="Agencia")
    assert {c["tipo"] for c in im.listar_contratos(t, u1, iid)} == {"arras", "mandato_venta"}
    import json
    datos = json.loads(db.get_connection().execute("SELECT datos FROM inmobiliaria_contratos WHERE id = ?", (c1,)).fetchone()[0])
    assert datos["precio"] == "245.000,00 €" and datos["arras"] == "24.500,00 €" and datos["ref_catastral"] == "1234567VK1234A0001XX" and datos["propietario"] == "Propietario Pérez" and datos["agencia"] == "Agencia Contratos"
    assert "{" not in "".join(v for v in datos.values())
    # plantilla propia
    im.guardar_ajustes(t, iva_pct=21, comision_venta_pct="3", comision_alquiler_meses="1", minimo_centimos=0, plantillas={"arras": "ARRAS de {parte} sobre {direccion} por {precio}."})
    assert im.obtener_ajustes(t)["plantillas_propias"]["arras"] and not im.obtener_ajustes(t)["plantillas_propias"]["alquiler"]
    c4 = im.generar_contrato(t, u1, iid, "arras", parte_nombre="Otra Persona")
    assert db.get_connection().execute("SELECT version FROM inmobiliaria_contratos WHERE id = ?", (c4,)).fetchone()[0] == 3
    # firma
    llamadas = []
    monkeypatch.setattr(documenso, "crear_documento", lambda clave, titulo, pdf, firmantes: (llamadas.append((clave, titulo, firmantes)), {"id": "env_7"})[1])
    monkeypatch.setattr(documenso, "enviar_a_firma", lambda clave, ident: llamadas.append(("enviar", ident)))
    conn = db.get_connection(); conn.execute("UPDATE tenants SET documenso_api_key = 'k' WHERE id = ?", (t,)); conn.commit(); conn.close()
    assert im.enviar_contrato_a_firma(t, u1, c4, "comprador@ejemplo.com", "Otra Persona") == "env_7" and llamadas[1] == ("enviar", "env_7")
    assert [c["estado"] for c in im.listar_contratos(t, u1, iid) if c["id"] == c4] == ["enviado_firma"]
    im.marcar_contrato_firmado(t, u1, c4)
    assert [c["estado"] for c in im.listar_contratos(t, u1, iid) if c["id"] == c4] == ["firmado"]
    for kw in ({"tipo": "hipoteca"}, {"parte_nombre": " "}):
        args = {"tipo": "arras", "parte_nombre": "x", **kw}
        with pytest.raises(ValueError):
            im.generar_contrato(t, u1, iid, **args)
    with pytest.raises(ValueError):
        im.guardar_ajustes(t, iva_pct=99, comision_venta_pct=3, comision_alquiler_meses=1, minimo_centimos=0, plantillas={})
    assert c3


# --- comisiones -------------------------------------------------------------------------------------------------------------------------------
def test_comision_propuesta_guardada_y_repartida(usuario_id):
    t, (u1, u2) = _agencia()
    _, iid, xid = _piso(t, u1, precio="250.000")
    p = im.proponer_comision(t, u1, iid)
    assert (p["base_centimos"], p["pct_bp"], p["honorarios"], p["iva"], p["total"]) == (25000000, 300, 750000, 157500, 907500)
    _, ia, xa = _piso(t, u1, "alquiler", "Calle Luna 3", "900,00")
    pa = im.proponer_comision(t, u1, ia)
    assert (pa["pct_bp"], pa["honorarios"], pa["total"]) == (10000, 90000, 108900), "alquiler: una mensualidad por defecto"
    c = im.guardar_comision(t, u1, iid, "245.000", 300, 0, 21, [(u1, 50), (u2, 50)])
    assert c["honorarios_centimos"] == 735000 and c["total_centimos"] == 889350 and [r["centimos"] for r in c["reparto"]] == [367500, 367500] and c["estado"] == "prevista"
    c = im.guardar_comision(t, u1, iid, "245.000", 300, "10.000", 21, [(u1, 70), (u2, 30)])
    assert c["honorarios_centimos"] == 1000000, "el mínimo de 10.000 € manda sobre el 3 %"
    assert [r["centimos"] for r in c["reparto"]] == [700000, 300000] and sum(r["centimos"] for r in c["reparto"]) == c["honorarios_centimos"]
    im.cambiar_estado_comision(t, u1, iid, "cobrada")
    assert im.obtener_comision(t, iid)["estado"] == "cobrada"
    for args in (("0", 300, 0, 21, [(u1, 100)]), ("1000", 300, 0, 99, [(u1, 100)]), ("1000", 300, 0, 21, [(u1, 90)]), ("1000", 300, 0, 21, [(999999, 100)]), ("1000", "x", 0, 21, [(u1, 100)])):
        with pytest.raises(ValueError):
            im.guardar_comision(t, u1, iid, *args)
    with pytest.raises(ValueError, match="Calcula"):
        im.cambiar_estado_comision(t, u1, ia, "cobrada")
    with pytest.raises(ValueError):
        im.cambiar_estado_comision(t, u1, iid, "regalada")


# --- fotos ------------------------------------------------------------------------------------------------------------------------------------
def _imagen(lado=3000, exif=True):
    from PIL import Image

    img = Image.new("RGB", (lado, lado // 2), (200, 30, 30))
    salida = io.BytesIO()
    if exif:
        e = Image.Exif()
        e[0x010F] = "MarcaCamara"            # Make
        e[0x8825] = {1: "N", 2: (40.0, 25.0, 0.0), 3: "W", 4: (3.0, 41.0, 0.0)}   # GPS
        img.save(salida, format="JPEG", exif=e)
    else:
        img.save(salida, format="PNG")
    return salida.getvalue()


def test_fotos_se_reducen_y_pierden_el_exif(usuario_id):
    from PIL import Image

    t, (u1, _) = _agencia()
    _, iid, xid = _piso(t, u1)
    original = _imagen()
    assert Image.open(io.BytesIO(original)).getexif().get(0x010F) == "MarcaCamara"
    did = im.subir_foto(t, u1, iid, "fachada.JPG", original)
    d = alm.leer(t, u1, did)
    foto = Image.open(io.BytesIO(d["contenido"]))
    assert d["tipo_mime"] == "image/jpeg" and d["categoria"] == "Foto" and max(foto.size) == 1600 and d["nombre_archivo"] == "fachada.jpg"
    assert len(foto.getexif()) == 0 and b"MarcaCamara" not in d["contenido"], "sin metadatos (ni GPS)"
    im.subir_foto(t, u1, iid, "otra.png", _imagen(800, exif=False))
    assert [f["nombre_archivo"] for f in im.fotos(t, u1, iid)] == ["fachada.jpg", "otra.jpg"]
    for contenido in (b"esto no es una imagen", b"", b"<svg onload=alert(1)>"):
        with pytest.raises(ValueError, match="imagen"):
            im.subir_foto(t, u1, iid, "x.jpg", contenido)


def test_limite_de_fotos(usuario_id, monkeypatch):
    t, (u1, _) = _agencia()
    _, iid, _x = _piso(t, u1)
    monkeypatch.setattr(im, "MAX_FOTOS", 2)
    from PIL import Image

    for n in range(2):
        buf = io.BytesIO(); Image.new("RGB", (50 + n, 50), (n, 0, 0)).save(buf, format="PNG")
        im.subir_foto(t, u1, iid, f"f{n}.png", buf.getvalue())
    buf = io.BytesIO(); Image.new("RGB", (70, 50), (9, 9, 9)).save(buf, format="PNG")
    with pytest.raises(ValueError, match="Máximo"):
        im.subir_foto(t, u1, iid, "f3.png", buf.getvalue())


# --- panel, feed e informe -------------------------------------------------------------------------------------------------------------------
def test_resumen_del_panel(usuario_id):
    t, (u1, _) = _agencia()
    _, i1, x1 = _piso(t, u1, direccion="Calle Uno 1")
    _, i2, x2 = _piso(t, u1, direccion="Calle Dos 2")
    _publicar(t, u1, x1); _publicar(t, u1, x2)
    im.crear_visita(t, u1, i1, datetime.now().replace(hour=23, minute=0).isoformat(timespec="minutes"), visitante="Hoy")
    im.registrar_oferta(t, u1, i1, "200.000", oferente="X")
    im.crear_demanda(t, u1, nucleo.crear_cliente(t, "C"), "venta")
    r = im.resumen(t, u1)
    assert r["n_activos"] == 2 and r["por_estado"] == {"publicado": 2} and len(r["visitas_hoy"]) == 1 and len(r["ofertas"]) == 1 and r["demandas"] == 1
    assert [i["id"] for i in r["sin_movimiento"]] == [i2], "el que no tiene visitas ni ofertas en 14 días se señala"


def test_feed_de_publicacion_sin_datos_privados(usuario_id):
    t, (u1, _) = _agencia()
    _, i1, x1 = _piso(t, u1, direccion="Calle Secreta 7", descripcion="Luminoso", certificado_energetico="D")
    _, i2, x2 = _piso(t, u1, direccion="Calle Oculta 8")
    _publicar(t, u1, x1)
    feed = im.feed_publicacion(t, u1)
    assert len(feed) == 1 and feed[0]["municipio"] == "Madrid" and feed[0]["precio_eur"] == 250000.0 and feed[0]["certificado_energetico"] == "D" and feed[0]["caracteristicas"] == ["ascensor", "terraza"]
    assert "Secreta" not in str(feed) and "Pérez" not in str(feed) and "direccion" not in feed[0] and "propietario" not in str(feed).lower()
    csv = im.feed_a_csv(feed)
    assert csv.startswith("﻿referencia;operacion") and "ascensor|terraza" in csv and "Secreta" not in csv
    nucleo.editar_expediente(t, u1, x1, descripcion="x")
    assert im.feed_a_csv([{**feed[0], "descripcion": "=HYPERLINK(\"x\")"}]).count("'=HYPERLINK") == 1


def test_portal_del_propietario(usuario_id):
    t, (u1, u2) = _agencia()
    prop, iid, xid = _piso(t, u1, direccion="Calle del Propietario 5")
    _publicar(t, u1, xid)
    comprador = nucleo.crear_cliente(t, "Interesado Secreto")
    d = im.crear_demanda(t, u1, comprador, "venta")
    v = im.crear_visita(t, u1, iid, (datetime.now() - timedelta(days=1)).isoformat(timespec="minutes"), demanda_id=d)
    im.registrar_resultado_visita(t, u1, v, "realizada", 5, "alto", "Le gustó mucho")
    im.crear_visita(t, u1, iid, (datetime.now() + timedelta(days=2)).isoformat(timespec="minutes"), visitante="Otro Secreto")
    im.registrar_oferta(t, u1, iid, "240.000", demanda_id=d)
    im.cambiar_precio(t, u1, iid, "245.000", "Ajuste")
    im.guardar_comision(t, u1, iid, "245.000", 300, 0, 21, [(u1, 100)])
    nucleo.registrar_parte(t, u1, "Horas internas privadas", minutos=30, expediente_id=xid)
    _, compartido = alm.guardar(u1, "nota_simple.pdf", "application/pdf", b"%PDF nota", expediente_id=xid)
    _, privado = alm.guardar(u1, "interno.pdf", "application/pdf", b"%PDF interno", expediente_id=xid)
    from app import abogados  # noqa: F401  (registro del otro módulo: el compartido es común)
    conn = db.get_connection(); conn.execute("UPDATE documentos SET compartido_cliente = 1 WHERE id = ?", (compartido,)); conn.commit(); conn.close()
    token = im.crear_enlace(t, u1, iid, 15)
    p = im.datos_propietario(token)
    assert p["direccion"] == "Calle del Propietario 5" and p["propietario"] == "Propietario Pérez" and p["estado_id"] == "publicado" and p["precio_centimos"] == 24500000
    assert p["visitas_total"] == 1 and p["valoracion_media"] == 5.0 and p["comentarios"][0]["comentario"] == "Le gustó mucho" and len(p["proximas"]) == 1
    assert [o["importe_centimos"] for o in p["ofertas"]] == [24000000] and [x["precio_centimos"] for x in p["precios"]] == [24500000, 25000000]
    assert [d_["nombre_archivo"] for d_ in p["documentos"]] == ["nota_simple.pdf"]
    texto = str(p)
    for secreto in ("Interesado Secreto", "Otro Secreto", "Horas internas", "interno.pdf", "comision", "Comisión"):
        assert secreto not in texto, secreto
    assert im.documento_publico(token, compartido)["contenido"] == b"%PDF nota" and im.documento_publico(token, privado) is None
    pdf = im.informe_publico_pdf(token)
    assert pdf.startswith(b"%PDF")
    inf = im.informe_propietario(t, iid, "2000-01-01", "2999-12-31")
    assert len(inf["visitas"]) == 1 and inf["valoracion_media"] == 5.0 and "Interesado" not in str(inf) and "Secreto" not in str(inf)
    # caduca, revoca, y deja de valer sin el módulo
    conn = db.get_connection(); conn.execute("UPDATE inmobiliaria_enlaces SET expira_en = '2000-01-01T00:00:00'"); conn.commit(); conn.close()
    assert im.datos_propietario(token) is None and im.informe_publico_pdf(token) is None
    conn = db.get_connection(); conn.execute("UPDATE inmobiliaria_enlaces SET expira_en = '2999-01-01T00:00:00'"); conn.commit(); conn.close()
    verticales.fijar_activo(t, "inmobiliaria", False)
    assert im.datos_propietario(token) is None
    verticales.fijar_activo(t, "inmobiliaria", True)
    assert im.datos_propietario(token) is not None and im.datos_propietario("inventado") is None and im.datos_propietario("") is None
    nucleo.papelera_expediente(t, u1, xid)
    assert im.datos_propietario(token) is None


def test_el_modulo_ofrece_sus_tipos_solo_si_esta_activo_y_borra_sus_datos(usuario_id):
    t, (u1, _) = _agencia("Sin modulo", modulo=False)
    c = nucleo.crear_cliente(t, "C")
    with pytest.raises(ValueError, match="no está disponible"):
        nucleo.crear_expediente(t, u1, c, "x", tipo="operacion_venta")
    verticales.fijar_activo(t, "inmobiliaria", True)
    assert {"operacion_venta", "operacion_alquiler"} <= set(verticales.tipos_expediente(t))
    assert [e.id for e in verticales.TIPO_GENERAL.estados] != [e.id for e in verticales.tipo_de("operacion_venta").estados]
    assert [e.id for e in verticales.tipo_de("operacion_venta").estados][-2:] == ["cerrada", "perdida"]
    prop, iid, xid = _piso(t, u1)
    im.crear_demanda(t, u1, c, "venta"); im.registrar_oferta(t, u1, iid, "1000", oferente="x"); im.crear_enlace(t, u1, iid)
    im.generar_contrato(t, u1, iid, "reserva", parte_nombre="X"); im.guardar_comision(t, u1, iid, "1000", 300, 0, 21, [(u1, 100)])
    im.guardar_ajustes(t, iva_pct=21, comision_venta_pct=3, comision_alquiler_meses=1, minimo_centimos=0, plantillas={})
    db.borrar_tenant(t)
    conn = db.get_connection()
    for tabla in ("inmobiliaria_inmuebles", "inmobiliaria_demandas", "inmobiliaria_ofertas", "inmobiliaria_contratos", "inmobiliaria_comisiones", "inmobiliaria_enlaces", "inmobiliaria_precios", "inmobiliaria_ajustes", "documentos"):
        assert conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0] == 0, tabla
    conn.close()
