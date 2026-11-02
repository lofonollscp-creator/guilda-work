"""Marketing del Comercial (app/marketing.py): consentimientos, grupos, plantillas y envíos con constancia."""
import json
from datetime import datetime, timedelta

import pytest

from app import acceso, comercial as co, db, documentos_firma as df, documenso, marketing as mk, nucleo, verticales
from app.marketing import ErrorMarketing


@pytest.fixture
def d(base_de_datos_temporal):
    t = db.crear_tenant("Despacho marketing")
    verticales.fijar_activo(t, "comercial", True)
    db.guardar_datos_tenant(t, "B12345678", "Calle Mayor 1, 08001 Barcelona")

    class E:
        pass
    e = E()
    e.t = t

    def u(mail, sup=False):
        x = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail)
        db.asignar_tenant(x, t)
        if sup:
            db.asignar_supervisor_tenant(x, True)
        return x
    e.sup, e.ana, e.aud = u("sup-mk@ejemplo.com", True), u("ana-mk@ejemplo.com"), u("aud-mk@ejemplo.com")
    acceso.dar_membresia(t, e.sup, e.aud, "auditor", "organizacion")
    return e


def _consentir(d, email, **kw):
    return mk.registrar_consentimiento(d.t, d.ana, email, origen=kw.pop("origen", "formulario"), evidencia=kw.pop("evidencia", "Casilla marcada en el formulario web"), **kw)


def test_el_consentimiento_exige_prueba_y_una_baja_prevalece(d):
    with pytest.raises(ErrorMarketing):
        mk.registrar_consentimiento(d.t, d.ana, "a@x.example", origen="formulario", evidencia="  ")
    with pytest.raises(ErrorMarketing):
        mk.registrar_consentimiento(d.t, d.ana, "no-es-correo", origen="formulario", evidencia="x")
    with pytest.raises(ErrorMarketing):
        mk.registrar_consentimiento(d.t, d.aud, "a@x.example", origen="formulario", evidencia="x")           # quien solo audita no registra
    c = _consentir(d, "  Ana@X.example ", nombre="Ana")
    assert c["estado"] == "consentido" and c["email"] == "ana@x.example" and c["consentido_en"]
    b = mk.registrar_baja(d.t, None, "ana@x.example", origen="baja_en_correo")
    assert b["estado"] == "baja" and b["baja_en"]
    assert mk.registrar_baja(d.t, None, "nunca-registrado@x.example")["estado"] == "baja"                    # una baja sin registro previo queda igualmente excluida
    mk.marcar_rebotado(d.t, None, "ana@x.example")                                                           # solo rebota quien estaba consentido
    again = _consentir(d, "ana@x.example")
    assert again["estado"] == "consentido" and again["baja_en"] is None                                      # puede volver a consentir con prueba nueva
    mk.marcar_rebotado(d.t, None, "ana@x.example")
    with pytest.raises(ErrorMarketing):
        _consentir(d, "ana@x.example")


def test_el_documento_firmado_registra_el_consentimiento_con_su_prueba(d, monkeypatch):
    db.guardar_documenso_api_key(d.t, "clave")
    c = nucleo.crear_cliente(d.t, "Cliente Firma", nif="B1", email="firma@cliente.example", direccion="X 1")
    monkeypatch.setattr(documenso, "crear_documento", lambda *a, **k: {"id": "e1"})
    monkeypatch.setattr(documenso, "enviar_a_firma", lambda *a: {})
    monkeypatch.setattr(documenso, "estado_documento", lambda *a: "COMPLETED")
    monkeypatch.setattr(documenso, "descargar_firmado", lambda *a: b"%PDF-firmado")
    did = df.crear_borrador(d.t, d.ana, c, "consentimiento_comercial", {"contacto_rgpd": "datos@despacho.example"})
    assert mk.obtener_contacto(d.t, "firma@cliente.example") is None
    df.enviar(d.t, d.ana, c, did)
    assert mk.obtener_contacto(d.t, "firma@cliente.example") is None                                          # enviar no es consentir
    df.refrescar(d.t, d.ana, c, did)
    k = mk.obtener_contacto(d.t, "firma@cliente.example")
    assert k["estado"] == "consentido" and k["origen"] == "documento_firmado" and k["documento_firma_id"] == did and k["cliente_id"] == c and "Documenso" in k["evidencia"]


def test_la_audiencia_aplica_siempre_los_filtros_de_proteccion_de_datos(d):
    a = nucleo.crear_cliente(d.t, "Con consentimiento", email="ok@x.example", etiquetas=["vip"])
    b = nucleo.crear_cliente(d.t, "Sin consentimiento", email="no@x.example", etiquetas=["vip"])
    c = nucleo.crear_cliente(d.t, "De baja", email="baja@x.example", etiquetas=["vip"])
    e = nucleo.crear_cliente(d.t, "Sin correo", etiquetas=["vip"])
    f = nucleo.crear_cliente(d.t, "Compartido uno", email="comun@x.example", etiquetas=["vip"])
    g = nucleo.crear_cliente(d.t, "Compartido dos", email="COMUN@x.example", etiquetas=["vip"])
    h = nucleo.crear_cliente(d.t, "Rebotado", email="rebota@x.example", etiquetas=["vip"])
    i = nucleo.crear_cliente(d.t, "En la papelera", email="papelera@x.example", etiquetas=["vip"])
    otro = nucleo.crear_cliente(d.t, "Otra etiqueta", email="otra@x.example", etiquetas=["nuevo"])
    nucleo.anadir_contacto(d.t, a, "Familiar", email="familiar@x.example")      # un contacto de la ficha no es el titular: no recibe nada
    for email in ("ok@x.example", "baja@x.example", "comun@x.example", "rebota@x.example", "papelera@x.example", "otra@x.example"):
        _consentir(d, email)
    mk.registrar_baja(d.t, None, "baja@x.example")
    mk.marcar_rebotado(d.t, None, "rebota@x.example")
    conn = db.get_connection(); conn.execute("UPDATE clientes SET papelera_en = '2026-01-01' WHERE id = ?", (i,)); conn.commit(); conn.close()

    r = mk.audiencia(d.t, d.ana, {"fuente": "clientes", "etiquetas": ["vip"]})
    assert sorted(x["email"] for x in r["destinatarios"]) == ["comun@x.example", "ok@x.example"]
    assert r["excluidos"] == {"sin_correo": 1, "sin_consentimiento": 1, "baja": 1, "rebotado": 1, "duplicado": 1} and r["candidatos"] == 7
    assert [x["email"] for x in mk.audiencia(d.t, d.ana, {"etiquetas": ["nuevo", "vip"], "etiquetas_modo": "todas"})["destinatarios"]] == []
    assert [x["email"] for x in mk.audiencia(d.t, d.ana, {"etiquetas": ["nuevo"]})["destinatarios"]] == ["otra@x.example"]


def test_los_prospectos_tambien_cuentan_si_han_consentido(d):
    co.crear_oportunidad(d.t, d.ana, "Prospecto A", contacto_nombre="Paula", contacto_email="paula@x.example")
    co.crear_oportunidad(d.t, d.ana, "Prospecto B", contacto_nombre="Pablo", contacto_email="pablo@x.example")
    _consentir(d, "paula@x.example", nombre="Paula")
    r = mk.audiencia(d.t, d.ana, {"fuente": "prospectos"})
    assert [x["email"] for x in r["destinatarios"]] == ["paula@x.example"] and r["excluidos"] == {"sin_consentimiento": 1}


def test_las_plantillas_validan_escapan_y_siempre_llevan_la_baja(d):
    with pytest.raises(ErrorMarketing):
        mk.bloques_validos([])
    with pytest.raises(ErrorMarketing):
        mk.bloques_validos([{"tipo": "boton", "texto": "Ir", "url": "javascript:alert(1)"}])
    with pytest.raises(ErrorMarketing):
        mk.bloques_validos([{"tipo": "texto", "texto": "Hola {{secreto}}"}])
    bloques = mk.bloques_validos([{"tipo": "titulo", "texto": "Hola {{nombre}}"}, {"tipo": "texto", "texto": "<script>x</script>\nlinea 2"},
                                  {"tipo": "boton", "texto": "Ir", "url": "https://ejemplo.com/?a=1&b=2"}, {"tipo": "divisor"}])
    html = mk.render_html(bloques, {"nombre": "<b>Ana</b>", "enlace_baja": "https://app/baja/abc"}, {"nombre": "Despacho", "cif": "B1", "direccion": "Calle 1"})
    assert "<script>" not in html and "&lt;b&gt;Ana&lt;/b&gt;" in html and "https://app/baja/abc" in html and "Darme de baja" in html and "Calle 1" in html and "&amp;b=2" in html
    assert "https://app/baja/abc" in mk.render_texto(bloques, {"nombre": "Ana", "enlace_baja": "https://app/baja/abc"}, {"nombre": "D", "cif": "C", "direccion": "L"})
    tid = mk.crear_plantilla(d.t, d.ana, "Bienvenida", "Hola {{nombre}}", bloques)
    assert mk.obtener_plantilla(d.t, tid)["bloques"][0]["texto"] == "Hola {{nombre}}"
    mk.editar_plantilla(d.t, d.ana, tid, "Bienvenida v2", "Nuevo asunto", bloques[:2])
    assert mk.obtener_plantilla(d.t, tid)["asunto"] == "Nuevo asunto" and len(mk.obtener_plantilla(d.t, tid)["bloques"]) == 2
    assert "Darme de baja" in mk.vista_previa(d.t, bloques)


def test_el_token_de_baja_se_verifica_y_no_se_puede_manipular(d):
    tok = mk.token_baja(d.t, "ana@x.example")
    assert mk.verificar_token_baja(tok) == (d.t, "ana@x.example")
    assert mk.verificar_token_baja(tok[:-2] + "00") is None and mk.verificar_token_baja("zz") is None
    otro = bytes.fromhex(tok).decode().replace(f"{d.t}:", f"{d.t + 1}:", 1)
    assert mk.verificar_token_baja(otro.encode().hex()) is None


def _preparar_envio(d, n=3):
    for i in range(n):
        nucleo.crear_cliente(d.t, f"Cliente {i}", email=f"c{i}@x.example", etiquetas=["vip"])
        _consentir(d, f"c{i}@x.example")
    g = mk.crear_grupo(d.t, d.ana, "VIP", {"etiquetas": ["vip"]})
    eid = mk.crear_envio(d.t, d.ana, "Novedades", g, "Hola {{nombre}}", [{"tipo": "texto", "texto": "Hola {{nombre}}"}])
    return g, eid


def test_programar_exige_direccion_recuento_y_datos_legales_y_congela_la_audiencia(d, monkeypatch):
    monkeypatch.setenv("MARKETING_SMTP_HOST", "smtp.ejemplo.com"); monkeypatch.setenv("MARKETING_SMTP_USUARIO", "u")
    monkeypatch.setenv("MARKETING_SMTP_CONTRASENA", "p"); monkeypatch.setenv("MARKETING_SMTP_REMITENTE", "no-responder@ejemplo.com")
    g, eid = _preparar_envio(d)
    r = mk.revisar(d.t, d.ana, eid)
    assert len(r["audiencia"]["destinatarios"]) == 3 and r["problemas"] == []
    with pytest.raises(ErrorMarketing) as e:
        mk.programar(d.t, d.ana, eid, "3", url_base="https://app.ejemplo.com")
    assert "dirección" in str(e.value)
    with pytest.raises(ErrorMarketing) as e:
        mk.programar(d.t, d.sup, eid, "2", url_base="https://app.ejemplo.com")
    assert "Escribe 3" in str(e.value)
    p = mk.programar(d.t, d.sup, eid, "3", url_base="https://app.ejemplo.com/")
    assert p["estado"] == "programado" and p["total"] == 3 and p["url_base"] == "https://app.ejemplo.com" and len(mk.destinatarios_de(d.t, eid)) == 3
    with pytest.raises(ErrorMarketing):
        mk.programar(d.t, d.sup, eid, "3", url_base="https://app.ejemplo.com")                                # no se programa dos veces


def test_sin_datos_legales_ni_canal_no_se_programa(d, monkeypatch):
    for v in ("MARKETING_SMTP_HOST", "MARKETING_SMTP_USUARIO", "MARKETING_SMTP_CONTRASENA", "MARKETING_SMTP_REMITENTE"):
        monkeypatch.delenv(v, raising=False)
    db.guardar_datos_tenant(d.t, "", "")
    g, eid = _preparar_envio(d)
    problemas = mk.revisar(d.t, d.ana, eid)["problemas"]
    assert any("CIF" in p for p in problemas) and any("MARKETING_SMTP" in p for p in problemas)
    with pytest.raises(ErrorMarketing):
        mk.programar(d.t, d.sup, eid, "3", url_base="https://x")
    assert mk.procesar_pendientes()["sin_canal"] is True


def test_el_lote_envia_solo_a_quien_sigue_consentido_y_deja_constancia(d, monkeypatch):
    for v, x in (("MARKETING_SMTP_HOST", "h"), ("MARKETING_SMTP_USUARIO", "u"), ("MARKETING_SMTP_CONTRASENA", "p"), ("MARKETING_SMTP_REMITENTE", "r@x")):
        monkeypatch.setenv(v, x)
    g, eid = _preparar_envio(d, 4)
    mk.programar(d.t, d.sup, eid, "4", url_base="https://app.ejemplo.com")
    mk.registrar_baja(d.t, None, "c1@x.example")                                                              # se da de baja DESPUÉS de programar
    enviados = []

    def enviador(destino, asunto, texto, html, enlace):
        if destino == "c2@x.example":
            raise OSError("buzón lleno")
        enviados.append((destino, asunto, enlace))
    r = mk.procesar_pendientes(enviador=enviador, lote=2, ahora=datetime.now() + timedelta(seconds=1))
    assert r["enviados"] + r["errores"] + r["omitidos"] == 2 and mk.obtener_envio(d.t, eid)["estado"] == "enviando"
    r2 = mk.procesar_pendientes(enviador=enviador, lote=10, ahora=datetime.now() + timedelta(seconds=1))
    e = mk.obtener_envio(d.t, eid)
    assert e["estado"] == "enviado" and e["enviados"] == 2 and e["errores"] == 1 and e["terminado_en"]
    assert sorted(x[0] for x in enviados) == ["c0@x.example", "c3@x.example"] and all(x[1] == "Hola Cliente " + x[0][1] for x in enviados)
    assert all(x[2].startswith("https://app.ejemplo.com/baja/") for x in enviados)
    estados = {x["email"]: x["estado"] for x in mk.destinatarios_de(d.t, eid)}
    assert estados == {"c0@x.example": "enviado", "c1@x.example": "omitido", "c2@x.example": "error", "c3@x.example": "enviado"}
    assert mk.procesar_pendientes(enviador=enviador, ahora=datetime.now() + timedelta(seconds=1)) == {"enviados": 0, "errores": 0, "omitidos": 0}        # nada se reenvía


def test_cancelar_prueba_y_exportar(d, monkeypatch):
    g, eid = _preparar_envio(d)
    salidas = []
    mk.enviar_prueba(d.t, d.ana, eid, "yo@despacho.example", url_base="https://app", enviador=lambda *a: salidas.append(a))
    assert salidas[0][0] == "yo@despacho.example" and salidas[0][1].startswith("[PRUEBA] ") and mk.obtener_contacto(d.t, "yo@despacho.example") is None
    csv = mk.exportar_audiencia_csv(mk.audiencia(d.t, d.ana, {"etiquetas": ["vip"]})["destinatarios"]).decode("utf-8-sig")
    assert csv.splitlines()[0] == "email,nombre" and "c0@x.example,Cliente 0" in csv
    mk.cancelar_envio(d.t, d.ana, eid)
    assert mk.obtener_envio(d.t, eid)["estado"] == "cancelado"
    with pytest.raises(ErrorMarketing):
        mk.cancelar_envio(d.t, d.ana, eid)


def test_la_ia_solo_recibe_el_texto_de_la_plantilla(d, monkeypatch):
    from app import ia_asistente, reuniones
    monkeypatch.setattr(reuniones, "configurada", lambda u: True)
    vistos = []
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda u, sistema, contenido: vistos.append((sistema, contenido)) or "Asunto 1\nAsunto 2")
    assert mk.asistente_ia(d.t, d.ana, "asuntos", "Hola {{nombre}}", "anunciar la renta") == "Asunto 1\nAsunto 2"
    assert "anunciar la renta" in vistos[0][1] and "Hola {{nombre}}" in vistos[0][1]
    with pytest.raises(ErrorMarketing):
        mk.asistente_ia(d.t, d.ana, "inventada", "x")
    monkeypatch.setattr(reuniones, "configurada", lambda u: False)
    with pytest.raises(ErrorMarketing):
        mk.asistente_ia(d.t, d.ana, "redactar", "x")


def test_aislamiento_entre_despachos(d):
    t2 = db.crear_tenant("Otro")
    _consentir(d, "ana@x.example")
    assert mk.obtener_contacto(t2, "ana@x.example") is None and mk.listar_contactos(t2) == []
    g = mk.crear_grupo(d.t, d.ana, "G", {})
    assert mk.obtener_grupo(t2, g) is None and mk.listar_grupos(t2) == []


# --- Rebotes ------------------------------------------------------------------------------------------------------------------

def _dsn(email, estado="5.1.1", accion="failed", detalle="smtp; 550 5.1.1 user unknown"):
    """Un informe de entrega como lo manda un servidor de correo (RFC 3464), escrito a mano."""
    return (f"From: MAILER-DAEMON@mx.ejemplo.com\nTo: no-responder@despacho.example\nSubject: Undelivered Mail Returned to Sender\nMIME-Version: 1.0\n"
            f'Content-Type: multipart/report; report-type=delivery-status; boundary="lim"\n\n--lim\nContent-Type: text/plain\n\nNo se pudo entregar.\n\n'
            f"--lim\nContent-Type: message/delivery-status\n\nReporting-MTA: dns; mx.ejemplo.com\n\nFinal-Recipient: rfc822; {email}\nAction: {accion}\nStatus: {estado}\n"
            f"Diagnostic-Code: {detalle}\n\n--lim--\n").encode()


def test_el_informe_de_entrega_se_interpreta_y_lo_demas_se_ignora(d):
    r = mk.parsear_dsn(_dsn("Ana@X.example"))
    assert r == [{"email": "ana@x.example", "estado": "5.1.1", "accion": "failed", "detalle": "smtp; 550 5.1.1 user unknown", "tipo": "duro"}]
    assert mk.parsear_dsn(_dsn("b@x.example", "4.2.2", "delayed", "smtp; 452 mailbox full"))[0]["tipo"] == "blando"
    assert mk.parsear_dsn(_dsn("c@x.example", "2.0.0", "delivered")) == []
    assert mk.parsear_dsn(b"Subject: Fuera de la oficina\n\nVuelvo el lunes.") == [] and mk.parsear_dsn(b"\xff\xfe basura") == []


def test_un_rebote_duro_corta_el_correo_y_los_blandos_al_repetirse(d):
    _consentir(d, "duro@x.example"); _consentir(d, "blando@x.example")
    assert mk.registrar_rebote(d.t, "duro@x.example", tipo="duro", codigo="5.1.1", origen="dsn")["rebotado"]
    assert mk.obtener_contacto(d.t, "duro@x.example")["estado"] == "rebotado"
    ahora = datetime.now()
    for i in range(2):
        assert not mk.registrar_rebote(d.t, "blando@x.example", tipo="blando", origen="dsn", ahora=ahora - timedelta(days=i))["rebotado"]
    assert mk.obtener_contacto(d.t, "blando@x.example")["estado"] == "consentido"
    assert mk.registrar_rebote(d.t, "blando@x.example", tipo="blando", origen="dsn", ahora=ahora)["rebotado"]
    assert mk.obtener_contacto(d.t, "blando@x.example")["estado"] == "rebotado" and len(mk.listar_rebotes(d.t)) == 4
    _consentir(d, "viejo@x.example")
    for i in range(3):                                                                                       # tres blandos, pero repartidos en más de 30 días: no bastan
        mk.registrar_rebote(d.t, "viejo@x.example", tipo="blando", origen="dsn", ahora=ahora - timedelta(days=40 * i))
    assert mk.obtener_contacto(d.t, "viejo@x.example")["estado"] == "consentido"
    with pytest.raises(ErrorMarketing):
        mk.registrar_rebote(d.t, "x@x.example", tipo="raro", origen="dsn")


def test_el_servidor_que_rechaza_el_buzon_en_el_envio_lo_marca_como_rebotado(d, monkeypatch):
    import smtplib
    for v, x in (("MARKETING_SMTP_HOST", "h"), ("MARKETING_SMTP_USUARIO", "u"), ("MARKETING_SMTP_CONTRASENA", "p"), ("MARKETING_SMTP_REMITENTE", "r@x")):
        monkeypatch.setenv(v, x)
    g, eid = _preparar_envio(d, 2)
    mk.programar(d.t, d.sup, eid, "2", url_base="https://app.ejemplo.com")

    def enviador(destino, *a):
        if destino == "c0@x.example":
            raise smtplib.SMTPRecipientsRefused({destino: (550, b"5.1.1 user unknown")})
    mk.procesar_pendientes(enviador=enviador, ahora=datetime.now() + timedelta(seconds=1))
    assert mk.obtener_contacto(d.t, "c0@x.example")["estado"] == "rebotado" and mk.obtener_contacto(d.t, "c1@x.example")["estado"] == "consentido"
    estados = {x["email"]: (x["estado"], x["error"]) for x in mk.destinatarios_de(d.t, eid)}
    assert estados["c0@x.example"][0] == "error" and "550" in estados["c0@x.example"][1] and estados["c1@x.example"][0] == "enviado"
    assert mk.listar_rebotes(d.t)[0]["origen"] == "smtp"


class _ImapFalso:
    def __init__(self, mensajes):
        self.mensajes, self.vistos, self.cerrado = mensajes, [], False
    def select(self, carpeta): return "OK", []
    def search(self, *a): return "OK", [b" ".join(str(i + 1).encode() for i in range(len(self.mensajes)))]
    def fetch(self, num, partes): return "OK", [(b"1 (RFC822)", self.mensajes[int(num) - 1]), b")"]
    def store(self, num, *a): self.vistos.append(int(num))
    def logout(self): self.cerrado = True


def test_el_buzon_de_rebotes_registra_los_de_nuestros_envios_y_marca_los_mensajes(d, monkeypatch):
    for v, x in (("MARKETING_SMTP_HOST", "h"), ("MARKETING_SMTP_USUARIO", "u"), ("MARKETING_SMTP_CONTRASENA", "p"), ("MARKETING_SMTP_REMITENTE", "r@x")):
        monkeypatch.setenv(v, x)
    g, eid = _preparar_envio(d, 2)
    mk.programar(d.t, d.sup, eid, "2", url_base="https://app.ejemplo.com")
    mk.procesar_pendientes(enviador=lambda *a: None, ahora=datetime.now() + timedelta(seconds=1))
    imap = _ImapFalso([_dsn("c0@x.example"), _dsn("ajeno@otro.example"), b"Subject: hola\n\nnormal"])
    r = mk.revisar_buzon_de_rebotes(imap=imap)
    assert r == {"leidos": 3, "rebotes": 1} and imap.vistos == [1, 2, 3] and imap.cerrado
    assert mk.obtener_contacto(d.t, "c0@x.example")["estado"] == "rebotado" and mk.listar_rebotes(d.t)[0]["envio_id"] == eid and mk.listar_rebotes(d.t)[0]["origen"] == "dsn"
    for v in ("MARKETING_IMAP_HOST", "MARKETING_IMAP_USUARIO", "MARKETING_IMAP_CONTRASENA"):
        monkeypatch.delenv(v, raising=False)
    assert mk.revisar_buzon_de_rebotes() == {"leidos": 0, "rebotes": 0, "sin_buzon": True}


def test_solo_la_direccion_reactiva_un_rebotado_y_con_motivo(d):
    _consentir(d, "r@x.example")
    mk.registrar_rebote(d.t, "r@x.example", tipo="duro", origen="dsn")
    with pytest.raises(ErrorMarketing):
        mk.reactivar_rebotado(d.t, d.ana, "r@x.example", "ya funciona")
    with pytest.raises(ErrorMarketing):
        mk.reactivar_rebotado(d.t, d.sup, "r@x.example", " ")
    with pytest.raises(ErrorMarketing):
        mk.reactivar_rebotado(d.t, d.sup, "otro@x.example", "x")
    c = mk.reactivar_rebotado(d.t, d.sup, "r@x.example", "El cliente confirma que su buzón funciona")
    assert c["estado"] == "consentido" and "Reactivado tras rebote" in c["evidencia"]


# --- Canales de envío: Brevo y Mailchimp -----------------------------------------------------------------------------------------

class _Proveedor:
    """Un proveedor falso: apunta lo que recibe y devuelve lo que se le diga."""
    etiquetas = {"nombre": "{{ contact.FIRSTNAME }}", "email": "{{ contact.EMAIL }}", "enlace_baja": "{{ unsubscribe }}"}

    def __init__(self, bajas=None, falla=None):
        self.recibido, self._bajas, self.falla = [], bajas or {"baja": [], "rebotado": []}, falla

    def verificar(self):
        if self.falla == "verificar":
            from app.marketing_proveedores import ErrorProveedor
            raise ErrorProveedor("Brevo respondió 401: clave no válida")
        return "Despacho SL"

    def enviar(self, nombre, asunto, html, destinatarios):
        if self.falla == "enviar":
            from app.marketing_proveedores import ErrorProveedor
            raise ErrorProveedor("Brevo respondió 500")
        self.recibido.append((nombre, asunto, html, destinatarios))
        return {"lista": 7, "campana": 9}

    def bajas(self, ref):
        return self._bajas


def _canal(d, proveedor="brevo", probar=True, prov=None):
    mk.guardar_proveedor(d.t, d.sup, proveedor, "xkeysib-secreta-1234", {"remitente_nombre": "Despacho", "remitente_email": "hola@despacho.example"})
    if probar:
        mk.probar_proveedor(d.t, d.sup, proveedor, proveedores={proveedor: prov or _Proveedor()})


def test_la_configuracion_de_un_canal_la_hace_la_direccion_oculta_la_clave_y_exige_probarla(d):
    with pytest.raises(ErrorMarketing):
        mk.guardar_proveedor(d.t, d.ana, "brevo", "k", {})                                                    # solo la dirección
    with pytest.raises(ErrorMarketing):
        mk.guardar_proveedor(d.t, d.sup, "brevo", "", {})                                                     # sin clave nueva ni anterior
    with pytest.raises(ErrorMarketing):
        mk.guardar_proveedor(d.t, d.sup, "inventado", "k", {})
    _canal(d, probar=False)
    c = mk.obtener_proveedor(d.t, "brevo")
    assert c["clave_final"] == "1234" and c["verificado_en"] is None and c["ajustes"]["remitente_email"] == "hola@despacho.example"
    with pytest.raises(ErrorMarketing):
        mk.crear_envio(d.t, d.ana, "E", mk.crear_grupo(d.t, d.ana, "G", {}), "A", [{"tipo": "texto", "texto": "x"}], canal="brevo")        # sin probar no se usa
    with pytest.raises(ErrorMarketing) as e:
        mk.probar_proveedor(d.t, d.sup, "brevo", proveedores={"brevo": _Proveedor(falla="verificar")})
    assert "401" in str(e.value) and mk.obtener_proveedor(d.t, "brevo")["verificado_en"] is None
    assert mk.probar_proveedor(d.t, d.sup, "brevo", proveedores={"brevo": _Proveedor()}) == "Despacho SL" and mk.obtener_proveedor(d.t, "brevo")["verificado_en"]
    mk.guardar_proveedor(d.t, d.sup, "brevo", "", {"remitente_email": "otro@despacho.example"})             # cambiar un ajuste conserva la clave pero exige volver a probar
    assert mk.obtener_proveedor(d.t, "brevo")["clave_final"] == "1234" and mk.obtener_proveedor(d.t, "brevo")["verificado_en"] is None
    mk.quitar_proveedor(d.t, d.sup, "brevo")
    assert mk.obtener_proveedor(d.t, "brevo") is None


def test_un_envio_por_proveedor_sube_solo_a_los_consentidos_y_aplica_las_bajas_de_vuelta(d):
    prov = _Proveedor()
    _canal(d, prov=prov)
    for i in range(3):
        nucleo.crear_cliente(d.t, f"Cliente {i}", email=f"c{i}@x.example", etiquetas=["vip"])
    _consentir(d, "c0@x.example"); _consentir(d, "c1@x.example")                                              # c2 nunca consintió
    g = mk.crear_grupo(d.t, d.ana, "VIP", {"etiquetas": ["vip"]})
    eid = mk.crear_envio(d.t, d.ana, "Novedades", g, "Hola {{nombre}}", [{"tipo": "texto", "texto": "Hola {{nombre}}"}, {"tipo": "boton", "texto": "Ver", "url": "https://ejemplo.com"}], canal="brevo")
    assert mk.revisar(d.t, d.sup, eid)["problemas"] == []                                                    # no hace falta el SMTP propio
    mk.programar(d.t, d.sup, eid, "2", url_base="https://app.ejemplo.com")
    mk.registrar_baja(d.t, None, "c1@x.example")                                                              # se da de baja después de programar
    r = mk.procesar_pendientes(proveedores={"brevo": prov}, ahora=datetime.now() + timedelta(seconds=1))
    assert r == {"enviados": 1, "errores": 0, "omitidos": 0}                                                  # la baja ya había sacado a c1 de los pendientes
    nombre, asunto, html, dest = prov.recibido[0]
    assert dest == [{"email": "c0@x.example", "nombre": "Cliente 0"}] and asunto == "Hola {{ contact.FIRSTNAME }}"
    assert "{{ unsubscribe }}" in html and "Darme de baja" in html and "{{ contact.FIRSTNAME }}" in html
    e = mk.obtener_envio(d.t, eid)
    assert e["estado"] == "enviado" and e["enviados"] == 1 and e["proveedor_estado"] == "entregado_al_proveedor" and json.loads(e["proveedor_ref"]) == {"lista": 7, "campana": 9}
    assert {x["email"]: x["estado"] for x in mk.destinatarios_de(d.t, eid)} == {"c0@x.example": "enviado", "c1@x.example": "omitido"}
    assert len(prov.recibido) == 1 and mk.procesar_pendientes(proveedores={"brevo": prov}, ahora=datetime.now() + timedelta(seconds=1))["enviados"] == 0 and len(prov.recibido) == 1      # no se reenvía

    _consentir(d, "c0@x.example")
    prov._bajas = {"baja": ["c0@x.example"], "rebotado": ["nadie@x.example"]}                                # el proveedor informa de una baja
    s = mk.sincronizar_proveedores(proveedores={"brevo": prov})
    assert s == {"envios": 1, "bajas": 1, "rebotes": 0, "errores": 0} and mk.obtener_contacto(d.t, "c0@x.example")["estado"] == "baja"
    assert mk.sincronizar_proveedores(proveedores={"brevo": prov})["bajas"] == 0                              # ya está de baja: no se repite


def test_si_el_proveedor_falla_el_envio_se_cancela_y_no_se_reintenta(d):
    prov = _Proveedor(falla="enviar")
    _canal(d)
    nucleo.crear_cliente(d.t, "C", email="c@x.example", etiquetas=["vip"]); _consentir(d, "c@x.example")
    g = mk.crear_grupo(d.t, d.ana, "VIP", {"etiquetas": ["vip"]})
    eid = mk.crear_envio(d.t, d.ana, "E", g, "A", [{"tipo": "texto", "texto": "Hola"}], canal="brevo")
    mk.programar(d.t, d.sup, eid, "1", url_base="https://app")
    r = mk.procesar_pendientes(proveedores={"brevo": prov}, ahora=datetime.now() + timedelta(seconds=1))
    e = mk.obtener_envio(d.t, eid)
    assert r["errores"] == 1 and e["estado"] == "cancelado" and "500" in e["ultimo_error"]
    assert mk.procesar_pendientes(proveedores={"brevo": prov}, ahora=datetime.now() + timedelta(seconds=1))["errores"] == 0               # no se reintenta solo


def test_mailchimp_devuelve_bajas_y_rebotes_por_separado(d):
    prov = _Proveedor(bajas={"baja": ["b@x.example"], "rebotado": ["r@x.example"]})
    _canal(d, "mailchimp", prov=prov)
    nucleo.crear_cliente(d.t, "A", email="a@x.example", etiquetas=["vip"])
    for e in ("a@x.example", "b@x.example", "r@x.example"):
        _consentir(d, e)
    g = mk.crear_grupo(d.t, d.ana, "VIP", {"etiquetas": ["vip"]})
    eid = mk.crear_envio(d.t, d.ana, "E", g, "A", [{"tipo": "texto", "texto": "Hola"}], canal="mailchimp")
    mk.programar(d.t, d.sup, eid, "1", url_base="https://app")
    mk.procesar_pendientes(proveedores={"mailchimp": prov}, ahora=datetime.now() + timedelta(seconds=1))
    s = mk.sincronizar_proveedores(proveedores={"mailchimp": prov})
    assert s["bajas"] == 1 and s["rebotes"] == 1 and mk.obtener_contacto(d.t, "b@x.example")["estado"] == "baja" and mk.obtener_contacto(d.t, "r@x.example")["estado"] == "rebotado"
