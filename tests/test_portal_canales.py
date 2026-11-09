"""SMS y WhatsApp de los avisos del portal (B4): opt-in con código, topes, perfil y «no molestar», baja por mensaje y firma del webhook. Twilio se simula: nada sale a la red."""
import base64
import hashlib
import hmac
from datetime import datetime, timedelta

import pytest

from app import portal_canales as pc, portal_personas, portal_push, portal_silencio
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures

SID = "AC" + "0" * 32
CS = "HX" + "1" * 32


@pytest.fixture
def twilio(monkeypatch):
    """Un Twilio de mentira: el token vive en un diccionario y cada envío se anota."""
    claves, enviados = {}, []
    monkeypatch.setattr(pc.ia_claves, "de_despacho", lambda prov, t: claves.get((prov, t), []))
    monkeypatch.setattr(pc.ia_claves, "guardar_de_despacho", lambda prov, t, v: claves.__setitem__((prov, t), v))
    resultado = {"ok": True, "error": ""}

    def falso(cfg, token, canal, hacia, texto):
        enviados.append({"canal": canal, "hacia": hacia, "texto": texto})
        return resultado["ok"], resultado["error"]
    monkeypatch.setattr(pc, "_enviar", falso)
    falso.resultado = resultado
    return enviados, falso


def _activar(t, sms=True, whatsapp=False):
    pc.guardar_config(t, account_sid=SID, token="tok", remitente_sms="+34900000000" if sms else "", remitente_whatsapp="+34911111111" if whatsapp else "",
                      whatsapp_content_sid=CS if whatsapp else "", sms_activo=sms, whatsapp_activo=whatsapp)


def _alta(ficha, email, tel="600111222", canal="sms", enviados=None):
    pc.pedir_codigo(ficha, email, tel, canal)
    codigo = None
    import re
    codigo = re.search(r"\b(\d{6})\b", enviados[-1]["texto"]).group(1)
    assert pc.verificar(ficha, email, codigo)


def test_telefonos_en_formato_internacional():
    assert pc.telefono_e164("600 111 222") == "+34600111222" and pc.telefono_e164("0033 6 12 34 56 78") == "+33612345678"
    assert pc.telefono_e164("+34-911-222-333") == "+34911222333"
    for malo in ("", "123", "abc", "+0123456789", "5551234", None):
        assert pc.telefono_e164(malo) is None


def test_la_configuracion_se_valida_y_sin_ella_no_hay_canales(twilio):
    t, u, c = _despacho("Canales cfg")
    assert pc.disponibles(t) == []
    with pytest.raises(pc.ErrorCanal):
        pc.guardar_config(t, account_sid="malo", token="x", remitente_sms="+3490", remitente_whatsapp="", whatsapp_content_sid="", sms_activo=True, whatsapp_activo=False)
    with pytest.raises(pc.ErrorCanal):
        pc.guardar_config(t, account_sid=SID, token="x", remitente_sms="", remitente_whatsapp="", whatsapp_content_sid="", sms_activo=True, whatsapp_activo=False)
    with pytest.raises(pc.ErrorCanal):
        pc.guardar_config(t, account_sid=SID, token="x", remitente_sms="", remitente_whatsapp="+34911111111", whatsapp_content_sid="", sms_activo=False, whatsapp_activo=True)
    _activar(t, sms=True, whatsapp=True)
    assert pc.disponibles(t) == ["sms", "whatsapp"]
    pc.guardar_config(t, account_sid=SID, token="", remitente_sms="+34900000000", remitente_whatsapp="", whatsapp_content_sid="", sms_activo=True, whatsapp_activo=False)   # el token vacío conserva el anterior
    assert pc.disponibles(t) == ["sms"]


def test_alta_con_codigo_caduca_y_se_bloquea_tras_cinco_fallos(twilio):
    enviados, _ = twilio
    t, u, c = _despacho("Canales alta")
    _activar(t)
    ficha = _ficha(c)
    with pytest.raises(pc.ErrorCanal):
        pc.pedir_codigo(ficha, "titular@ejemplo.com", "no es un móvil", "sms")
    with pytest.raises(pc.ErrorCanal):
        pc.pedir_codigo(ficha, "titular@ejemplo.com", "600111222", "whatsapp")                 # canal no activado
    pc.pedir_codigo(ficha, "titular@ejemplo.com", "600111222", "sms")
    assert enviados[-1]["hacia"] == "+34600111222" and pc.de_persona(ficha, "titular@ejemplo.com")["verificado_en"] is None
    for _i in range(6):
        pc.verificar(ficha, "titular@ejemplo.com", "abcdef")
    import re
    bueno = re.search(r"\b(\d{6})\b", enviados[-1]["texto"]).group(1)
    assert pc.verificar(ficha, "titular@ejemplo.com", bueno) is False                           # demasiados fallos: hay que pedir otro código
    pc.pedir_codigo(ficha, "titular@ejemplo.com", "600111222", "sms")
    bueno = re.search(r"\b(\d{6})\b", enviados[-1]["texto"]).group(1)
    assert pc.verificar(ficha, "titular@ejemplo.com", bueno, ahora=datetime.now() + timedelta(minutes=11)) is False      # caducado
    assert pc.verificar(ficha, "titular@ejemplo.com", bueno) is True and pc.de_persona(ficha, "titular@ejemplo.com")["verificado_en"]


def test_no_se_pueden_pedir_mas_de_tres_codigos_por_hora(twilio):
    t, u, c = _despacho("Canales tope codigos")
    _activar(t)
    ficha = _ficha(c)
    for _i in range(pc.MAX_CODIGOS_HORA):
        pc.pedir_codigo(ficha, "titular@ejemplo.com", "600111222", "sms")
    with pytest.raises(pc.ErrorCanal):
        pc.pedir_codigo(ficha, "titular@ejemplo.com", "600111222", "sms")


def test_envia_solo_a_quien_confirmo_su_movil_con_titulo_y_enlace_sin_datos(twilio):
    enviados, _ = twilio
    t, u, c = _despacho("Canales envio")
    _activar(t, sms=True, whatsapp=True)
    ficha = _ficha(c)
    portal_personas.anadir(ficha, "consulta@ejemplo.com", "Con", "consulta", por=u)
    _alta(ficha, "titular@ejemplo.com", enviados=enviados)
    pc.pedir_codigo(ficha, "consulta@ejemplo.com", "611222333", "sms")                         # sin confirmar: no recibe nada
    n_antes = len(enviados)
    assert pc.enviar(ficha, "Tienes una factura por corregir", "/portal/facturas", accion=None) == 1
    assert len(enviados) == n_antes + 1 and enviados[-1]["hacia"] == "+34600111222" and "factura por corregir" in enviados[-1]["texto"] and "€" not in enviados[-1]["texto"]
    assert pc.envios_del_mes(t)["sms"] == 1


def test_whatsapp_usa_la_plantilla_y_no_manda_el_enlace_en_el_texto(twilio):
    enviados, _ = twilio
    t, u, c = _despacho("Canales wa")
    _activar(t, sms=False, whatsapp=True)
    ficha = _ficha(c)
    _alta(ficha, "titular@ejemplo.com", canal="whatsapp", enviados=enviados)
    pc.enviar(ficha, "Algo por firmar", "/portal/firmas", accion="decidir")
    assert enviados[-1]["canal"] == "whatsapp" and enviados[-1]["texto"] == "Algo por firmar"


def test_respeta_nivel_de_avisos_perfil_y_no_molestar(twilio):
    enviados, _ = twilio
    t, u, c = _despacho("Canales respeto")
    _activar(t)
    ficha = _ficha(c)
    _alta(ficha, "titular@ejemplo.com", enviados=enviados)
    n = len(enviados)
    portal_personas.fijar_avisos(ficha, "titular@ejemplo.com", "urgente")
    ficha = _ficha(c)                                                                            # la ficha guarda el nivel del titular: se vuelve a leer
    assert pc.enviar(ficha, "No urgente", "/portal/") == 0 and pc.enviar(ficha, "Urgente", "/portal/", urgente=True, ahora=datetime(2026, 11, 9, 12, 0)) == 1
    portal_personas.fijar_avisos(ficha, "titular@ejemplo.com", "todo")
    ficha, n = _ficha(c), len(enviados)
    ahora = datetime(2026, 11, 9, 23, 30)
    portal_silencio.guardar(ficha, "titular@ejemplo.com", "22:00", "08:00")
    assert pc.enviar(ficha, "A deshoras", "/portal/", ahora=ahora) == 0 and len(enviados) == n
    assert pc.enviar(ficha, "A mediodía", "/portal/", ahora=datetime(2026, 11, 9, 12, 0)) == 1


def test_topes_por_persona_y_por_despacho(twilio, monkeypatch):
    enviados, _ = twilio
    t, u, c = _despacho("Canales topes")
    _activar(t)
    ficha = _ficha(c)
    _alta(ficha, "titular@ejemplo.com", enviados=enviados)
    n = len(enviados)
    ahora = datetime(2026, 11, 9, 12, 0)
    llegados = sum(pc.enviar(ficha, f"Aviso {i}", "/portal/", ahora=ahora) for i in range(8))
    assert llegados == pc.MAX_DIA_PERSONA and len(enviados) == n + pc.MAX_DIA_PERSONA
    assert pc.enviar(ficha, "Al día siguiente", "/portal/", ahora=ahora + timedelta(days=1)) == 1
    monkeypatch.setattr(pc, "MAX_DIA_DESPACHO", 1)
    assert pc.enviar(ficha, "Tope del despacho", "/portal/", ahora=ahora + timedelta(days=1)) == 0


def test_un_fallo_de_twilio_no_rompe_el_aviso_y_un_movil_dado_de_baja_en_twilio_se_borra(twilio):
    enviados, falso = twilio
    t, u, c = _despacho("Canales fallo")
    _activar(t)
    ficha = _ficha(c)
    _alta(ficha, "titular@ejemplo.com", enviados=enviados)
    falso.resultado.update(ok=False, error="red")
    assert pc.enviar(ficha, "No sale", "/portal/") == 0 and pc.de_persona(ficha, "titular@ejemplo.com")["verificado_en"]
    falso.resultado.update(error="21610")
    pc.enviar(ficha, "Se dio de baja en Twilio", "/portal/")
    assert pc.de_persona(ficha, "titular@ejemplo.com") is None


def test_los_avisos_del_portal_pasan_por_los_canales(twilio):
    enviados, _ = twilio
    t, u, c = _despacho("Canales gancho")
    _activar(t)
    ficha = _ficha(c)
    _alta(ficha, "titular@ejemplo.com", enviados=enviados)
    n = len(enviados)
    portal_push.enviar(ficha, "Factura devuelta", "texto largo", "/portal/facturas")
    assert len(enviados) == n + 1


def test_baja_por_telefono_y_firma_del_webhook(twilio, cliente, monkeypatch):
    monkeypatch.setenv("GUILDA_URL_PUBLICA", "https://portal.ejemplo.com")
    enviados, _ = twilio
    t, u, c = _despacho("Canales baja")
    _activar(t)
    ficha = _ficha(c)
    _alta(ficha, "titular@ejemplo.com", enviados=enviados)
    url = "https://portal.ejemplo.com/portal/canales/twilio/%d" % t
    datos = {"From": "+34600111222", "Body": "BAJA"}
    firma = base64.b64encode(hmac.new(b"tok", (url + "BodyBAJAFrom+34600111222").encode(), hashlib.sha1).digest()).decode()
    assert pc.firma_valida("tok", url, datos, firma) and not pc.firma_valida("otro", url, datos, firma)
    assert cliente.post(f"/portal/canales/twilio/{t}", data=datos, headers={"X-Twilio-Signature": "mala"}).status_code == 403
    assert pc.de_persona(ficha, "titular@ejemplo.com") is not None
    r = cliente.post(f"/portal/canales/twilio/{t}", data=datos, headers={"X-Twilio-Signature": firma})
    assert r.status_code == 200 and b"<Response" in r.data
    assert pc.de_persona(ficha, "titular@ejemplo.com") is None


def test_mi_cuenta_ofrece_el_movil_solo_si_el_despacho_activo_algun_canal(cliente, correo, twilio):
    enviados, _ = twilio
    t, u, c = _despacho("Canales web")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "movil-telefono" not in _html(cliente, "/portal/cuenta")
    _activar(t)
    assert "movil-telefono" in _html(cliente, "/portal/cuenta")
    r = cliente.post("/portal/cuenta/movil/codigo", data={"telefono": "600111222", "canal": "sms"})
    assert r.status_code == 302 and enviados
    import re
    codigo = re.search(r"\b(\d{6})\b", enviados[-1]["texto"]).group(1)
    assert cliente.post("/portal/cuenta/movil/verificar", data={"codigo": "123456" if codigo != "123456" else "654321"}).status_code == 302
    assert pc.de_persona(_ficha(c), "titular@ejemplo.com")["verificado_en"] is None
    cliente.post("/portal/cuenta/movil/verificar", data={"codigo": codigo})
    assert "+34600111222" in _html(cliente, "/portal/cuenta")
    cliente.post("/portal/cuenta/movil/quitar")
    assert pc.de_persona(_ficha(c), "titular@ejemplo.com") is None
