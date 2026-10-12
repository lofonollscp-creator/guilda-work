"""Módulo Gabinete de abogados (app/abogados.py): asuntos, partes, conflictos, vistas, plazos por notificación, provisión de fondos, minutas, hoja de encargo y enlace del cliente."""
from datetime import date, datetime, timedelta

import pytest

from app import abogados as ab
from app import almacen_documentos as alm
from app import db, nucleo, verticales


def _despacho(nombre="Bufete", n=2, modulo=True):
    t = db.crear_tenant(nombre)
    us = []
    for i in range(n):
        u = db.crear_usuario_vinculado_a_kratos(f"{nombre.lower()}-{i}@ejemplo.com", f"kratos-{nombre}-{i}")
        db.asignar_tenant(u, t)
        us.append(u)
    if modulo:
        verticales.fijar_activo(t, "abogados", True)
    return t, us


def _asunto(t, u, titulo="Reclamación de cantidad", tipo="procedimiento_judicial", cliente=None, **kw):
    c = cliente or nucleo.crear_cliente(t, "Cliente Uno S.L.", nif="B12345678")
    return c, nucleo.crear_expediente(t, u, c, titulo, tipo=tipo, **kw)


def test_el_modulo_ofrece_sus_tipos_solo_si_esta_activo(usuario_id):
    t, (u1, _) = _despacho("Sin modulo", modulo=False)
    c = nucleo.crear_cliente(t, "C")
    with pytest.raises(ValueError, match="no está disponible"):
        nucleo.crear_expediente(t, u1, c, "x", tipo="procedimiento_judicial")
    verticales.fijar_activo(t, "abogados", True)
    assert {"procedimiento_judicial", "asunto_extrajudicial"} <= set(verticales.tipos_expediente(t))
    x = nucleo.crear_expediente(t, u1, c, "Demanda", tipo="procedimiento_judicial")
    e = nucleo.obtener_expediente(t, x, u1)
    assert (e["estado"], e["vertical_id"]) == ("preparacion", "abogados")
    nucleo.cambiar_estado_expediente(t, u1, x, "pendiente_vista")
    nucleo.cambiar_estado_expediente(t, u1, x, "archivado")
    assert nucleo.obtener_expediente(t, x, u1)["cerrado_en"], "archivar cierra el asunto"
    assert verticales.tipo_de("asunto_extrajudicial").inicial == "abierto" and verticales.tipo_de("procedimiento_judicial").calendario == "procesal"
    assert [e.entradas_menu[0].endpoint for e in [verticales.VERTICALES["abogados"]]] == ["abogados.panel"]


def test_datos_del_procedimiento_y_partes(usuario_id):
    t, (u1, u2) = _despacho()
    c, x = _asunto(t, u1)
    d = ab.fijar_datos(t, u1, x, numero_procedimiento="123/2026", juzgado="Juzgado de 1ª Instancia nº 4", jurisdiccion="civil", procurador="Ana Gómez", cuantia="12.500,50", resumen_cliente="Reclamamos la deuda.")
    assert d["cuantia_centimos"] == 1250050 and d["jurisdiccion"] == "civil"
    assert ab.datos_de(nucleo.obtener_expediente(t, x, u1))["numero_procedimiento"] == "123/2026"
    ab.fijar_datos(t, u1, x, procurador="")
    assert "procurador" not in ab.datos_de(nucleo.obtener_expediente(t, x, u1)), "un campo vacío se quita"
    for kw in ({"jurisdiccion": "marciana"}, {"cuantia": "mucho"}, {"cuantia": "-5"}):
        with pytest.raises(ValueError):
            ab.fijar_datos(t, u1, x, **kw)
    p = ab.anadir_parte(t, u1, x, "contraparte", "Deudores Asociados S.A.", "A11111111")
    ab.anadir_parte(t, u1, x, "letrado_contrario", "Luis Pérez")
    ab.anadir_parte(t, u1, x, "cliente", "Cliente Uno S.L.")
    assert [p["rol"] for p in ab.listar_partes(t, u1, x)] == ["cliente", "contraparte", "letrado_contrario"]
    for rol, nombre in (("marciano", "x"), ("tercero", " ")):
        with pytest.raises(ValueError):
            ab.anadir_parte(t, u1, x, rol, nombre)
    ab.eliminar_parte(t, u1, x, p)
    assert len(ab.listar_partes(t, u1, x)) == 2
    general = nucleo.crear_expediente(t, u1, c, "Expediente general")
    with pytest.raises(ValueError, match="no encontrado"):
        ab.anadir_parte(t, u1, general, "tercero", "x")


def test_conflicto_de_intereses_en_los_dos_sentidos_y_con_expedientes_confidenciales(usuario_id):
    t, (u1, u2) = _despacho()
    c1, x1 = _asunto(t, u1, "Caso A")
    ab.anadir_parte(t, u1, x1, "cliente", "Cliente Uno S.L.", "B12345678")
    ab.anadir_parte(t, u1, x1, "contraparte", "Constructora Delta S.L.", "B99999999")
    # ¿Podemos aceptar como cliente a quien fue contraparte?
    h = ab.revisar_conflictos(t, u2, "constructora  delta s.l.", None, "cliente")
    assert len(h) == 1 and h[0]["motivo"] == "fue_contraparte" and h[0]["titulo"] == "Caso A" and h[0]["cliente"] == "Cliente Uno S.L."
    assert ab.revisar_conflictos(t, u2, "Otro nombre", "b-99999999", "cliente")[0]["motivo"] == "fue_contraparte", "coincide por NIF aunque el nombre cambie"
    assert ab.revisar_conflictos(t, u2, "Persona Nueva", None, "cliente") == []
    # ¿Y a quien ya es cliente como contraparte?
    h = ab.revisar_conflictos(t, u2, "Cliente Uno S.L.", None, "contraparte")
    assert {x["motivo"] for x in h} == {"es_cliente", "es_parte_cliente"}
    assert ab.revisar_conflictos(t, u2, "Constructora Delta S.L.", None, "contraparte") == [], "una contraparte no es conflicto como contraparte"
    # Un asunto confidencial al que no se tiene acceso solo avisa de que existe
    _, x2 = _asunto(t, u1, "Caso reservado", confidencial=True, cliente=nucleo.crear_cliente(t, "Cliente Secreto"))
    ab.anadir_parte(t, u1, x2, "contraparte", "Empresa Fantasma S.L.")
    oculto = ab.revisar_conflictos(t, u2, "Empresa Fantasma S.L.", None, "cliente")
    assert oculto[0]["oculto"] is True and oculto[0]["titulo"] is None and oculto[0]["cliente"] is None and "Secreto" not in str(oculto)
    visible = ab.revisar_conflictos(t, u1, "Empresa Fantasma S.L.", None, "cliente")
    assert visible[0]["titulo"] == "Caso reservado" and not visible[0].get("oculto")
    assert ab.revisar_conflictos(t, u2, "Empresa Fantasma S.L.", None, "cliente", supervisor=True)[0]["titulo"] == "Caso reservado"
    assert ab.revisar_conflictos(t, u1, "Constructora Delta S.L.", None, "cliente", excluir_expediente=x1) == []
    assert ab.revisar_conflictos(t, u1, "", None) == []
    t2, (o,) = _despacho("Otro bufete", 1)
    assert ab.revisar_conflictos(t2, o, "Constructora Delta S.L.", None, "cliente") == [], "los conflictos no cruzan despachos"


def test_vistas_agenda_y_calendario_ics(usuario_id):
    t, (u1, u2) = _despacho()
    c, x = _asunto(t, u1)
    v = ab.crear_vista(t, u1, x, "2030-05-14 10:30", "juicio", "Sala 3, Palacio de Justicia", "Llevar originales")
    ab.crear_vista(t, u1, x, "2030-06-01T09:00", "vista")
    vistas = ab.listar_vistas(t, u1, desde="2030-05-01", hasta="2030-05-31")
    assert [x["fecha_hora"] for x in vistas] == ["2030-05-14T10:30"] and vistas[0]["cliente_nombre"] == "Cliente Uno S.L."
    ab.cambiar_estado_vista(t, u1, v, "suspendida")
    ics = ab.vistas_a_ics(ab.listar_vistas(t, u1))
    assert ics.startswith("BEGIN:VCALENDAR") and "DTSTART:20300514T103000" in ics and "STATUS:CANCELLED" in ics and "Sala 3\\, Palacio de Justicia" in ics and ics.count("BEGIN:VEVENT") == 2
    assert [x["id"] for x in ab.listar_vistas(t, u1, estado="prevista")] != [v]
    for kw in ({"fecha_hora": "mañana"}, {"fecha_hora": "2030-05-14 10:30", "tipo": "fiesta"}):
        with pytest.raises(ValueError):
            ab.crear_vista(t, u1, x, **{"tipo": "vista", **kw})
    with pytest.raises(ValueError):
        ab.cambiar_estado_vista(t, u1, v, "volando")
    _, xc = _asunto(t, u1, "Reservado", confidencial=True)
    vc = ab.crear_vista(t, u1, xc, "2030-07-01 09:00")
    assert vc not in {v["id"] for v in ab.listar_vistas(t, u2)}
    with pytest.raises(ValueError):
        ab.cambiar_estado_vista(t, u2, vc, "celebrada")
    ab.eliminar_vista(t, u1, vc)
    assert vc not in {v["id"] for v in ab.listar_vistas(t, u1)}


def test_notificacion_genera_el_plazo_procesal_y_una_tarea(usuario_id):
    t, (u1, u2) = _despacho()
    c, x = _asunto(t, u1)
    c1 = ab.calcular_plazo(t, "2026-07-29", 5)
    assert c1["fecha_limite"] == "2026-09-03" and c1["unidad"] == "habiles", "agosto es inhábil en el calendario procesal"
    assert ab.calcular_plazo(t, "2026-10-01", 10, "naturales")["fecha_limite"] == "2026-10-13"
    nucleo.anadir_festivo(t, "2026-09-02", "Fiesta del partido judicial")
    assert ab.calcular_plazo(t, "2026-07-29", 5)["fecha_limite"] == "2026-09-04", "los festivos del despacho cuentan"
    for kw in ({"fecha_notificacion": "ayer", "plazo": 5}, {"fecha_notificacion": "2026-07-29", "plazo": 0}, {"fecha_notificacion": "2026-07-29", "plazo": 999}):
        with pytest.raises(ValueError):
            ab.calcular_plazo(t, **kw)
    hoy = date.today()
    pid = ab.registrar_notificacion(t, u1, x, "auto", (hoy - timedelta(days=1)).isoformat(), 5)
    p = [p for p in nucleo.listar_plazos(t, u1) if p["id"] == pid][0]
    assert p["critico"] == 1 and p["origen"] == "notificacion" and not p["revisado"] and p["expediente_id"] == x and "Auto notificada" in p["titulo"]
    assert p["fecha_limite"] > hoy.isoformat()
    tareas = db.listar_tareas_outlook(u1)
    assert any("Plazo:" in t_["asunto"] and "Reclamación" in t_["asunto"] for t_ in tareas)
    with pytest.raises(ValueError, match="resolución"):
        ab.registrar_notificacion(t, u1, x, "carta", "2026-07-29", 5)
    ab.registrar_notificacion(t, u1, x, "sentencia", "2026-07-29", 20, titulo="Apelar", crear_tarea=False, critico=False)
    assert [p for p in nucleo.listar_plazos(t, u1) if p["titulo"] == "Apelar"][0]["critico"] == 0
    _, general = _asunto(t, u1, "General", tipo="general")
    with pytest.raises(ValueError):
        ab.registrar_notificacion(t, u1, general, "auto", "2026-07-29", 5)


def test_provision_de_fondos_saldo_y_aviso_de_provision_baja(usuario_id):
    t, (u1, u2) = _despacho()
    c, x = _asunto(t, u1)
    assert ab.saldo(t, x)["saldo"] == 0 and ab.expedientes_con_provision_baja(t, u1) == []
    ab.registrar_movimiento(t, u1, x, "provision", "1.000,00", "Provisión inicial", "2026-10-01")
    ab.registrar_movimiento(t, u1, x, "suplido", "150,50", "Tasa judicial")
    ab.registrar_movimiento(t, u1, x, "devolucion", 5000, "Devolución parcial")
    s = ab.saldo(t, x)
    assert (s["provisiones"], s["suplidos"], s["devoluciones"], s["saldo"]) == (100000, 15050, 5000, 79950)
    assert ab.expedientes_con_provision_baja(t, u1) == [], "sin mínimo configurado no se avisa"
    ab.guardar_ajustes(t, serie="M", iva_pct=21, irpf_pct=15, bloque_minutos=6, provision_minima_centimos=100000, plantilla_encargo="")
    baja = ab.expedientes_con_provision_baja(t, u1)
    assert [b["expediente_id"] for b in baja] == [x] and baja[0]["saldo"] == 79950
    ab.registrar_movimiento(t, u1, x, "provision", 50000, "Reposición")
    assert ab.expedientes_con_provision_baja(t, u1) == []
    for kw in ({"tipo": "regalo"}, {"importe": 0}, {"importe": "-3"}, {"importe": "mucho"}, {"concepto": " "}, {"fecha": "ayer"}):
        args = {"tipo": "provision", "importe": 100, "concepto": "x", **kw}
        with pytest.raises(ValueError):
            ab.registrar_movimiento(t, u1, x, **args)
    assert ab.listar_movimientos(t, u1, x)[0]["concepto"] in ("Reposición", "Provisión inicial", "Devolución parcial", "Tasa judicial")
    _, xc = _asunto(t, u1, "Reservado", confidencial=True)
    assert ab.listar_movimientos(t, u2, xc) == []
    with pytest.raises(ValueError):
        ab.registrar_movimiento(t, u2, xc, "provision", 100, "colado")


@pytest.mark.parametrize("hon,sup,iva,irpf,esperado", [
    (100000, 0, 21, 0, {"iva": 21000, "irpf": 0, "total": 121000}),
    (100000, 0, 21, 15, {"iva": 21000, "irpf": 15000, "total": 106000}),
    (100000, 5050, 21, 15, {"iva": 21000, "irpf": 15000, "total": 111050}),       # los suplidos no llevan IVA ni retención
    (333, 0, 21, 15, {"iva": 70, "irpf": 50, "total": 353}),                       # 69,93 → 70 y 49,95 → 50
    (0, 1000, 21, 15, {"iva": 0, "irpf": 0, "total": 1000}),
])
def test_calculo_de_minuta(hon, sup, iva, irpf, esperado):
    c = ab.calcular_minuta(hon, sup, iva, irpf)
    assert {k: c[k] for k in esperado} == esperado and c["base"] == hon and c["suplidos"] == sup


def test_minuta_desde_horas_y_suplidos_con_numeracion_y_cargo_a_provision(usuario_id):
    t, (u1, u2) = _despacho()
    c, x = _asunto(t, u1)          # el cliente es una empresa (CIF): lleva retención
    nucleo.fijar_tarifa_usuario(t, u1, 20000)
    with pytest.raises(ValueError, match="No hay horas"):
        ab.crear_borrador_de_minuta(t, u1, x)
    nucleo.registrar_parte(t, u1, "Estudio del caso", minutos=70, expediente_id=x)
    nucleo.registrar_parte(t, u1, "Reunión interna", minutos=30, expediente_id=x, facturable=False)
    ab.registrar_movimiento(t, u1, x, "provision", 100000, "Provisión")
    ab.registrar_movimiento(t, u1, x, "suplido", "30,00", "Tasa")
    m = ab.crear_borrador_de_minuta(t, u1, x)
    mi, lineas = ab.obtener_minuta(t, m)
    assert mi["estado"] == "borrador" and mi["numero"] is None and mi["irpf_pct"] == 15 and mi["iva_pct"] == 21
    assert [l["tipo"] for l in lineas] == ["honorarios", "suplido"], "las horas no facturables no entran"
    hon = lineas[0]["importe_centimos"]
    assert hon == 24000, "70 min se redondean a 72 (bloques de 6) y a 200 €/h son 240 €"
    assert mi["base_centimos"] == hon and mi["suplidos_centimos"] == 3000 and mi["total_centimos"] == ab.calcular_minuta(hon, 3000, 21, 15)["total"]
    ab.anadir_linea_minuta(t, m, "Redacción de escrito", "100,00")
    ab.fijar_impuestos_minuta(t, m, 21, 7, "Con retención reducida")
    mi, _ = ab.obtener_minuta(t, m)
    assert mi["irpf_pct"] == 7 and mi["base_centimos"] == hon + 10000 and mi["notas"] == "Con retención reducida"
    pdf = ab.minuta_a_pdf(t, m)
    assert pdf.startswith(b"%PDF")
    with pytest.raises(ValueError):
        ab.fijar_impuestos_minuta(t, m, 99, 0)
    numero = ab.emitir_minuta(t, u1, m, cargar_a_provision=True)
    assert numero == f"M-{date.today().year}-001"
    mi, _ = ab.obtener_minuta(t, m)
    assert mi["estado"] == "emitida" and mi["cargada_a_provision"] == 1
    assert nucleo.listar_partes(t, u1, ver_todo=True, expediente_id=x, pendiente_de_facturar=True) == [], "las horas quedan facturadas"
    s = ab.saldo(t, x)
    assert s["honorarios"] == mi["total_centimos"] and s["saldo"] == 100000 - 3000 - mi["total_centimos"]
    for f in (lambda: ab.anadir_linea_minuta(t, m, "tarde", 1), lambda: ab.fijar_impuestos_minuta(t, m, 21, 0), lambda: ab.eliminar_borrador(t, m), lambda: ab.emitir_minuta(t, u1, m)):
        with pytest.raises(ValueError, match="emitida"):
            f()
    with pytest.raises(ValueError, match="No hay horas"):
        ab.crear_borrador_de_minuta(t, u1, x)
    nucleo.registrar_parte(t, u1, "Otra gestión", minutos=60, expediente_id=x)
    m2 = ab.crear_borrador_de_minuta(t, u1, x)
    assert ab.emitir_minuta(t, u1, m2) == f"M-{date.today().year}-002", "numeración correlativa"
    ab.cambiar_estado_minuta(t, u1, m2, "pagada")
    with pytest.raises(ValueError):
        ab.cambiar_estado_minuta(t, u1, m2, "pagada")
    # anular la primera libera lo facturado y quita el cargo a provisión
    ab.cambiar_estado_minuta(t, u1, m, "anulada")
    assert len(nucleo.listar_partes(t, u1, ver_todo=True, expediente_id=x, pendiente_de_facturar=True)) == 1
    assert ab.saldo(t, x)["honorarios"] == 0
    assert {mm["numero"] for mm in ab.listar_minutas(t, u1)} == {f"M-{date.today().year}-001", f"M-{date.today().year}-002"}
    assert [mm["estado"] for mm in ab.listar_minutas(t, u1, estado="pagada")] == ["pagada"]
    m3 = ab.crear_borrador_de_minuta(t, u1, x)
    ab.eliminar_borrador(t, m3)
    assert ab.obtener_minuta(t, m3)[0] is None


def test_minuta_sin_retencion_para_clientes_personas_y_otros_despachos_no_la_ven(usuario_id):
    t, (u1, _) = _despacho()
    persona = nucleo.crear_cliente(t, "María Particular", nif="12345678Z")
    _, x = _asunto(t, u1, cliente=persona)
    nucleo.registrar_parte(t, u1, "Consulta", minutos=30, expediente_id=x, tarifa_hora_centimos=10000)
    m = ab.crear_borrador_de_minuta(t, u1, x)
    assert ab.obtener_minuta(t, m)[0]["irpf_pct"] == 0
    t2, _ = _despacho("Otro bufete")
    assert ab.obtener_minuta(t2, m)[0] is None
    with pytest.raises(ValueError):
        ab.emitir_minuta(t2, u1, m)


def test_ajustes_del_despacho(usuario_id):
    t, _ = _despacho()
    assert ab.obtener_ajustes(t)["iva_pct"] == 21 and ab.obtener_ajustes(t)["plantilla_encargo"] is None and "HOJA DE ENCARGO" in ab.obtener_ajustes(t)["plantilla_encargo_efectiva"]
    ab.guardar_ajustes(t, serie="abg", iva_pct="21", irpf_pct="7", bloque_minutos="15", provision_minima_centimos="50000", plantilla_encargo="Mi plantilla {cliente}")
    a = ab.obtener_ajustes(t)
    assert (a["serie"], a["irpf_pct"], a["bloque_minutos"], a["plantilla_encargo_efectiva"]) == ("ABG", 7, 15, "Mi plantilla {cliente}")
    for kw in ({"serie": ""}, {"serie": "demasiado largo"}, {"iva_pct": 99}, {"irpf_pct": "x"}, {"bloque_minutos": 120}):
        args = {"serie": "M", "iva_pct": 21, "irpf_pct": 15, "bloque_minutos": 6, "provision_minima_centimos": 0, "plantilla_encargo": "", **kw}
        with pytest.raises(ValueError):
            ab.guardar_ajustes(t, **args)


def test_hoja_de_encargo_pdf_y_envio_a_firma(usuario_id, monkeypatch):
    from app import documenso

    t, (u1, _) = _despacho("Bufete Firma")
    c, x = _asunto(t, u1, "Divorcio de mutuo acuerdo")
    did = ab.generar_hoja_de_encargo(t, u1, x)
    d = alm.leer(t, u1, did)
    assert d["contenido"].startswith(b"%PDF") and d["categoria"] == "Hoja de encargo" and d["expediente_id"] == x and d["origen"] == "generado"
    otra = ab.generar_hoja_de_encargo(t, u1, x)
    assert otra != did and len(alm.listar(t, u1, expediente_id=x)) == 2, "cada generación es un documento nuevo (versiones)"
    llamadas = []
    monkeypatch.setattr(documenso, "crear_documento", lambda clave, titulo, pdf, firmantes: (llamadas.append(("crear", clave, titulo, firmantes)), {"id": "env_1"})[1])
    monkeypatch.setattr(documenso, "enviar_a_firma", lambda clave, ident: llamadas.append(("enviar", clave, ident)))
    conn = db.get_connection(); conn.execute("UPDATE tenants SET documenso_api_key = 'api_clave' WHERE id = ?", (t,)); conn.commit(); conn.close()
    assert ab.enviar_a_firma(t, u1, did, "cliente@ejemplo.com", "Cliente Uno") == "env_1"
    assert llamadas == [("crear", "api_clave", f"hoja_de_encargo_{x}.pdf", [{"email": "cliente@ejemplo.com", "nombre": "Cliente Uno"}]), ("enviar", "api_clave", "env_1")]
    assert any(e["tipo"] == "firma" for e in nucleo.linea_de_tiempo(t, u1, x))
    with pytest.raises(ValueError, match="email"):
        ab.enviar_a_firma(t, u1, did, "sin-arroba", "x")
    monkeypatch.setattr(documenso, "crear_documento", lambda *a: (_ for _ in ()).throw(documenso.ErrorDocumenso("Documenso caído")))
    with pytest.raises(ValueError, match="caído"):
        ab.enviar_a_firma(t, u1, did, "cliente@ejemplo.com", "x")


def test_enlace_de_solo_lectura_para_el_cliente(usuario_id):
    t, (u1, u2) = _despacho()
    c, x = _asunto(t, u1, "Reclamación a Delta")
    ab.fijar_datos(t, u1, x, resumen_cliente="Hemos presentado la demanda.")
    nucleo.cambiar_estado_expediente(t, u1, x, "pendiente_vista")
    ab.crear_vista(t, u1, x, (datetime.now() + timedelta(days=20)).isoformat(timespec="minutes"), "juicio", "Sala 2")
    ab.crear_vista(t, u1, x, (datetime.now() - timedelta(days=20)).isoformat(timespec="minutes"), "vista")
    _, privado = alm.guardar(u1, "informe_interno.pdf", "application/pdf", b"%PDF privado", expediente_id=x)
    _, compartido = alm.guardar(u1, "demanda.pdf", "application/pdf", b"%PDF demanda", expediente_id=x)
    nucleo.registrar_parte(t, u1, "Nota interna con tarifa", minutos=30, expediente_id=x)
    nucleo.crear_plazo(t, u1, "Plazo interno", "2030-01-01", expediente_id=x)
    ab.compartir_documento(t, u1, x, compartido, True)
    token = ab.crear_enlace(t, u1, x, dias=7)
    conn = db.get_connection()
    fila = conn.execute("SELECT * FROM abogados_enlaces").fetchone(); conn.close()
    assert token not in fila["token_hash"] and len(fila["token_hash"]) == 64, "en la base solo queda la huella"
    p = ab.datos_publicos(token)
    assert p["titulo"] == "Reclamación a Delta" and p["cliente"] == "Cliente Uno S.L." and p["estado_id"] == "pendiente_vista" and p["resumen"] == "Hemos presentado la demanda."
    assert len(p["vistas"]) == 1 and p["vistas"][0]["lugar"] == "Sala 2", "solo señalamientos futuros"
    assert [d["nombre_archivo"] for d in p["documentos"]] == ["demanda.pdf"]
    assert "Nota interna" not in str(p) and "Plazo interno" not in str(p) and "informe_interno" not in str(p) and "Delta" in p["titulo"]
    assert ab.documento_publico(token, compartido)["contenido"] == b"%PDF demanda" and ab.documento_publico(token, privado) is None
    assert ab.datos_publicos("token-inventado") is None and ab.datos_publicos("") is None and ab.datos_publicos("x" * 500) is None
    # caduca, se revoca y depende del módulo
    conn = db.get_connection(); conn.execute("UPDATE abogados_enlaces SET expira_en = '2000-01-01T00:00:00'"); conn.commit(); conn.close()
    assert ab.datos_publicos(token) is None
    conn = db.get_connection(); conn.execute("UPDATE abogados_enlaces SET expira_en = '2999-01-01T00:00:00'"); conn.commit(); conn.close()
    assert ab.datos_publicos(token) is not None
    verticales.fijar_activo(t, "abogados", False)
    assert ab.datos_publicos(token) is None, "sin el módulo, los enlaces dejan de funcionar"
    verticales.fijar_activo(t, "abogados", True)
    enlace = ab.listar_enlaces(t, x)[0]["id"]
    ab.revocar_enlace(t, u1, x, enlace)
    assert ab.datos_publicos(token) is None and ab.listar_enlaces(t, x)[0]["revocado_en"]
    ab.compartir_documento(t, u1, x, compartido, False)
    with pytest.raises(ValueError):
        ab.compartir_documento(t, u1, x, 999999, True)
    token2 = ab.crear_enlace(t, u1, x)
    assert ab.datos_publicos(token2) is not None
    nucleo.papelera_expediente(t, u1, x)
    assert ab.datos_publicos(token2) is None, "un asunto en la papelera ya no se enseña"


def test_el_panel_del_asunto_reune_todo(usuario_id):
    t, (u1, _) = _despacho()
    c, x = _asunto(t, u1)
    exp = nucleo.obtener_expediente(t, x, u1)
    paneles = verticales.paneles_para(t, u1, False, exp)
    assert len(paneles) == 1 and paneles[0]["plantilla"] == "abogados/_panel_expediente.html"
    ctx = paneles[0]["ctx"]
    assert ctx["es_judicial"] and ctx["fondos"]["saldo"] == 0 and ctx["ajustes"]["iva_pct"] == 21 and "estado_llano" in ctx
    _, general = _asunto(t, u1, "General", tipo="general")
    assert verticales.paneles_para(t, u1, False, nucleo.obtener_expediente(t, general, u1)) == []
    verticales.fijar_activo(t, "abogados", False)
    assert verticales.paneles_para(t, u1, False, exp) == [], "sin el módulo no hay panel"


def test_borrar_el_despacho_borra_los_datos_del_modulo(usuario_id):
    t, (u1, _) = _despacho()
    c, x = _asunto(t, u1)
    ab.anadir_parte(t, u1, x, "contraparte", "X")
    ab.crear_vista(t, u1, x, "2030-01-01 10:00")
    ab.registrar_movimiento(t, u1, x, "provision", 100, "p")
    ab.guardar_ajustes(t, serie="M", iva_pct=21, irpf_pct=15, bloque_minutos=6, provision_minima_centimos=0, plantilla_encargo="")
    nucleo.registrar_parte(t, u1, "h", minutos=10, expediente_id=x, tarifa_hora_centimos=100)
    ab.emitir_minuta(t, u1, ab.crear_borrador_de_minuta(t, u1, x))
    ab.crear_enlace(t, u1, x)
    db.borrar_tenant(t)
    conn = db.get_connection()
    for tabla in ("abogados_partes", "abogados_vistas", "abogados_fondos", "abogados_minutas", "abogados_minuta_lineas", "abogados_enlaces", "abogados_ajustes", "expedientes"):
        assert conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0] == 0, tabla
    conn.close()
