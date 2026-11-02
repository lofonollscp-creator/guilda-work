"""Documentos prehechos que se firman con Documenso desde la ficha del cliente (app/documentos_firma.py)."""
from datetime import date

import pytest

from app import almacen_documentos, db, documentos_firma as df, documenso, nucleo

HOY = date(2026, 11, 2)


def _despacho(documenso_key="clave-de-prueba", cif="B12345678", direccion="Calle Mayor 1, 08001 Barcelona"):
    t = db.crear_tenant("Despacho Prueba")
    u = db.crear_usuario_vinculado_a_kratos("gestor@ejemplo.com", "k-gestor")
    db.asignar_tenant(u, t)
    db.guardar_datos_tenant(t, cif, direccion)
    if documenso_key:
        db.guardar_documenso_api_key(t, documenso_key)
    c = nucleo.crear_cliente(t, "Marta Soler SL", tipo="empresa", nif="B87654321", email="marta@soler.example", direccion="Av. Diagonal 100, Barcelona")
    return t, u, c


def _datos(clave):
    return {"hoja_encargo": {"servicios": "Contabilidad\nIVA trimestral", "honorarios": "120 € al mes + IVA"},
            "mandato_sepa": {"iban": "ES91 2100 0418 4502 0005 1332", "acreedor_sepa": "ES12ZZZ12345678"},
            "autorizacion_aeat": {"alcance": "Presentar declaraciones", "vigencia": "Hasta revocación"},
            "consentimiento_rgpd": {"contacto_rgpd": "datos@despacho.example"},
            "consentimiento_comercial": {"contacto_rgpd": "datos@despacho.example"}}[clave]


@pytest.mark.parametrize("clave", df.CLAVES)
def test_cada_documento_se_compone_con_los_datos_del_cliente_y_del_despacho(clave):
    t, u, c = _despacho()
    r = df.componer(t, c, clave, _datos(clave), lugar="Barcelona", hoy=HOY)
    assert "Marta Soler SL" in r["texto"] and "Despacho Prueba" in r["texto"] and "02/11/2026" in r["texto"]
    assert "{{" not in r["texto"] and "________" not in r["texto"]


def test_si_falta_un_dato_imprescindible_no_se_genera_y_se_dice_cual():
    t, u, c = _despacho(cif="", direccion="")
    sin_nif = nucleo.crear_cliente(t, "Sin NIF", email="x@y.example")
    with pytest.raises(df.ErrorDocumento) as e:
        df.componer(t, sin_nif, "hoja_encargo", _datos("hoja_encargo"), hoy=HOY)
    assert "NIF del cliente" in str(e.value) and "CIF del despacho" in str(e.value)
    assert df.formulario(t, sin_nif, "hoja_encargo")["faltan"]


def test_el_consentimiento_comercial_exige_correo_y_no_nif():
    t, u, c = _despacho()
    sin_correo = nucleo.crear_cliente(t, "Sin correo", nif="12345678Z")
    with pytest.raises(df.ErrorDocumento) as e:
        df.componer(t, sin_correo, "consentimiento_comercial", _datos("consentimiento_comercial"), hoy=HOY)
    assert "Correo del cliente" in str(e.value)


def test_el_mandato_sepa_valida_el_iban_y_genera_la_referencia():
    t, u, c = _despacho()
    malo = dict(_datos("mandato_sepa"), iban="ES00 0000 0000 0000 0000 0000")
    with pytest.raises(df.ErrorDocumento):
        df.componer(t, c, "mandato_sepa", malo, hoy=HOY)
    ok = df.componer(t, c, "mandato_sepa", _datos("mandato_sepa"), hoy=HOY)
    assert "ES9121000418450200051332" in ok["texto"] and f"GW{c}20261102" in ok["texto"] and "reembolso" in ok["texto"]
    b2b = df.componer(t, c, "mandato_sepa", dict(_datos("mandato_sepa"), esquema="B2B"), hoy=HOY)
    assert "no tiene derecho a que su entidad le reembolse" in b2b["texto"]


def test_los_campos_obligatorios_se_exigen():
    t, u, c = _despacho()
    with pytest.raises(df.ErrorDocumento) as e:
        df.componer(t, c, "hoja_encargo", {"servicios": "", "honorarios": "x"}, hoy=HOY)
    assert "Servicios" in str(e.value)


def test_el_despacho_cambia_el_texto_y_vuelve_al_de_serie():
    t, u, c = _despacho()
    with pytest.raises(df.ErrorDocumento):
        df.guardar_texto(t, u, "hoja_encargo", "Texto propio")                     # solo la dirección cambia los textos
    db.fijar_atributos_en_despacho(u, t, supervisor_tenant=1)
    with pytest.raises(df.ErrorDocumento) as e:
        df.guardar_texto(t, u, "hoja_encargo", "Hola {{variable_inventada}}")
    assert "variable_inventada" in str(e.value)
    df.guardar_texto(t, u, "hoja_encargo", "# Mi hoja\nPara {{cliente.nombre}}: {{servicios}} por {{honorarios}}.")
    assert df.texto_de(t, "hoja_encargo")[1] is True and any(f["propio"] for f in df.catalogo(t) if f["clave"] == "hoja_encargo")
    assert "Para Marta Soler SL: Contabilidad" in df.componer(t, c, "hoja_encargo", _datos("hoja_encargo"), hoy=HOY)["texto"]
    df.restaurar_texto(t, u, "hoja_encargo")
    assert df.texto_de(t, "hoja_encargo")[1] is False


def test_el_pdf_es_determinista_y_deja_el_hueco_de_la_firma():
    pdf1, n1 = df.pdf_de("Titulo", "# Titulo\nHola\n\n- uno\n- dos", "Despacho")
    pdf2, n2 = df.pdf_de("Titulo", "# Titulo\nHola\n\n- uno\n- dos", "Despacho")
    assert pdf1.startswith(b"%PDF") and pdf1 == pdf2 and n1 == n2 == 1
    largo, n = df.pdf_de("T", "# T\n" + "\n\n".join(f"Párrafo número {i} " + "texto " * 60 for i in range(40)), "D")
    assert n > 1


def test_borrador_envio_firma_y_efecto_al_firmar(monkeypatch):
    t, u, c = _despacho()
    enviados = []
    monkeypatch.setattr(documenso, "crear_documento", lambda clave, titulo, pdf, firmantes, **k: enviados.append((titulo, pdf, firmantes, k)) or {"id": "env_9"})
    monkeypatch.setattr(documenso, "enviar_a_firma", lambda clave, ident: {})
    estado = {"v": "PENDING"}
    monkeypatch.setattr(documenso, "estado_documento", lambda clave, ident: estado["v"])
    monkeypatch.setattr(documenso, "descargar_firmado", lambda clave, ident: b"%PDF-firmado")
    efectos = []
    monkeypatch.setitem(df.AL_FIRMAR, "consentimiento_comercial", lambda tenant, usuario, doc: efectos.append(doc["id"]))

    did = df.crear_borrador(t, u, c, "consentimiento_comercial", _datos("consentimiento_comercial"), lugar="Barcelona", hoy=HOY)
    d = df.obtener(t, c, did)
    assert d["estado"] == "borrador" and d["firmante_email"] == "marta@soler.example" and len(d["pdf_sha256"]) == 64
    assert df.ajustes(t)["contacto_rgpd"] == "datos@despacho.example" and df.ajustes(t)["lugar"] == "Barcelona"       # se recuerdan para el siguiente

    assert df.enviar(t, u, c, did) == "env_9"
    titulo, pdf, firmantes, extra = enviados[0]
    assert pdf.startswith(b"%PDF") and firmantes[0]["email"] == "marta@soler.example" and extra["pagina"] == 1 and tuple(extra["campo"]) == df.FIRMA
    assert df.obtener(t, c, did)["estado"] == "enviado"
    with pytest.raises(df.ErrorDocumento):
        df.enviar(t, u, c, did)                                                    # un envío no se repite

    assert df.refrescar(t, u, c, did) == "enviado" and not efectos
    estado["v"] = "COMPLETED"
    assert df.refrescar(t, u, c, did) == "firmado" and efectos == [did]
    d = df.obtener(t, c, did)
    assert d["estado"] == "firmado" and d["documento_firmado_id"]
    assert almacen_documentos.leer(t, u, d["documento_firmado_id"])["contenido"] == b"%PDF-firmado"
    with pytest.raises(df.ErrorDocumento):
        df.cancelar(t, u, c, did)                                                  # lo firmado no se cancela


def test_sin_documenso_se_puede_generar_pero_no_enviar():
    t, u, c = _despacho(documenso_key="")
    did = df.crear_borrador(t, u, c, "hoja_encargo", _datos("hoja_encargo"), hoy=HOY)
    assert not df.puede_enviar(t)
    with pytest.raises(df.ErrorDocumento):
        df.enviar(t, u, c, did)
    assert df.pdf_del_documento(t, c, did)[1].startswith(b"%PDF")


def test_un_rechazo_y_la_cancelacion_se_reflejan(monkeypatch):
    t, u, c = _despacho()
    monkeypatch.setattr(documenso, "crear_documento", lambda *a, **k: {"id": "e1"})
    monkeypatch.setattr(documenso, "enviar_a_firma", lambda *a: {})
    monkeypatch.setattr(documenso, "estado_documento", lambda *a: "REJECTED")
    did = df.crear_borrador(t, u, c, "hoja_encargo", _datos("hoja_encargo"), hoy=HOY)
    df.enviar(t, u, c, did)
    assert df.refrescar(t, u, c, did) == "rechazado"
    df.cancelar(t, u, c, did)
    assert df.obtener(t, c, did)["estado"] == "cancelado"


def test_otro_despacho_no_ve_ni_toca_los_documentos():
    t, u, c = _despacho()
    did = df.crear_borrador(t, u, c, "hoja_encargo", _datos("hoja_encargo"), hoy=HOY)
    t2 = db.crear_tenant("Otro despacho")
    c2 = nucleo.crear_cliente(t2, "Ajeno", nif="12345678Z")
    assert df.obtener(t2, c2, did) is None and df.listar_de_cliente(t2, c2) == []
    with pytest.raises(df.ErrorDocumento):
        df.componer(t2, c, "hoja_encargo", _datos("hoja_encargo"), hoy=HOY)       # el cliente no es de ese despacho


def test_el_aviso_automatico_anota_la_firma_y_avisa_a_quien_creo_el_documento(monkeypatch):
    t, u, c = _despacho()
    monkeypatch.setattr(documenso, "crear_documento", lambda *a, **k: {"id": "env_77"})
    monkeypatch.setattr(documenso, "enviar_a_firma", lambda *a: {})
    estado = {"v": "PENDING"}
    monkeypatch.setattr(documenso, "estado_documento", lambda *a: estado["v"])
    monkeypatch.setattr(documenso, "descargar_firmado", lambda *a: b"%PDF-firmado")
    avisos = []
    from app import notificaciones
    monkeypatch.setattr(notificaciones, "crear_y_enviar", lambda usuario, tipo, titulo, cuerpo, url=None, **k: avisos.append((usuario, tipo, titulo, cuerpo, url)))
    did = df.crear_borrador(t, u, c, "hoja_encargo", _datos("hoja_encargo"), hoy=HOY)
    df.enviar(t, u, c, did)

    assert df.refrescar_por_documenso("otro") == [] and df.refrescar_por_documenso("env_77") == ["enviado"] and not avisos      # sin firmar no se avisa
    estado["v"] = "COMPLETED"
    assert df.refrescar_por_documenso("env_77") == ["firmado"]
    assert df.obtener(t, c, did)["estado"] == "firmado" and len(avisos) == 1 and avisos[0][0] == u and avisos[0][2].startswith("Firmado") and avisos[0][4].endswith(f"/{did}")
    assert df.refrescar_por_documenso("env_77") == []                                                                     # ya no está pendiente: no se avisa dos veces


def test_el_barrido_de_respaldo_repasa_los_pendientes_de_todos_los_despachos(monkeypatch):
    t, u, c = _despacho()
    t2 = db.crear_tenant("Segundo")
    u2 = db.crear_usuario_vinculado_a_kratos("g2@ejemplo.com", "k-g2"); db.asignar_tenant(u2, t2)
    db.guardar_datos_tenant(t2, "B22222222", "Calle 2"); db.guardar_documenso_api_key(t2, "clave2")
    c2 = nucleo.crear_cliente(t2, "Cliente 2", nif="B3", email="c2@x.example", direccion="X")
    monkeypatch.setattr(documenso, "crear_documento", lambda *a, **k: {"id": "e" + a[1][:3]})
    monkeypatch.setattr(documenso, "enviar_a_firma", lambda *a: {})
    monkeypatch.setattr(documenso, "estado_documento", lambda clave, ident: "COMPLETED" if clave == "clave2" else "REJECTED")
    monkeypatch.setattr(documenso, "descargar_firmado", lambda *a: b"%PDF")
    from app import notificaciones
    avisos = []
    monkeypatch.setattr(notificaciones, "crear_y_enviar", lambda usuario, tipo, titulo, *a, **k: avisos.append(titulo))
    d1 = df.crear_borrador(t, u, c, "hoja_encargo", _datos("hoja_encargo"), hoy=HOY); df.enviar(t, u, c, d1)
    d2 = df.crear_borrador(t2, u2, c2, "hoja_encargo", _datos("hoja_encargo"), hoy=HOY); df.enviar(t2, u2, c2, d2)
    assert df.sincronizar_pendientes() == {"revisados": 2, "firmados": 1, "rechazados": 1}
    assert df.obtener(t, c, d1)["estado"] == "rechazado" and df.obtener(t2, c2, d2)["estado"] == "firmado" and sorted(a.split(":")[0] for a in avisos) == ["Firmado", "Rechazado"]
