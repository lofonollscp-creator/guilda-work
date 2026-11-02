"""Los conectores de Brevo y Mailchimp (app/marketing_proveedores.py) con un transporte HTTP falso: comprueba que cada llamada va al punto de acceso, con la cabecera y el cuerpo que documenta el proveedor."""
import hashlib

import pytest

from app import marketing_proveedores as mp
from app.marketing_proveedores import Brevo, ErrorProveedor, Mailchimp


class Servidor:
    """Responde según `(método, ruta)` y apunta cada llamada."""

    def __init__(self, respuestas):
        self.respuestas, self.llamadas = respuestas, []

    def __call__(self, metodo, url, cabeceras, cuerpo=None):
        self.llamadas.append((metodo, url, cabeceras, cuerpo))
        for (m, trozo), (estado, resp) in self.respuestas.items():
            if m == metodo and ((trozo.endswith("*") and trozo[:-1] in url) or (not trozo.endswith("*") and url.endswith(trozo))):
                return estado, resp
        return 404, {"message": "no previsto: " + url}


DEST = [{"email": "ana@x.example", "nombre": "Ana"}, {"email": "beto@x.example", "nombre": ""}]


def test_brevo_crea_lista_sube_contactos_crea_la_campana_y_la_envia(monkeypatch):
    s = Servidor({("GET", "/account"): (200, {"companyName": "Despacho SL"}), ("GET", "/contacts/folders?limit=50&offset=0"): (200, {"folders": [{"id": 3, "name": "Todos"}]}),
                  ("POST", "/contacts/lists"): (201, {"id": 11}), ("POST", "/contacts"): (201, {"id": 1}), ("POST", "/emailCampaigns"): (201, {"id": 42}),
                  ("POST", "/emailCampaigns/42/sendNow"): (204, {})})
    monkeypatch.setattr(mp, "_peticion", s)
    b = Brevo("xkeysib-1", {"remitente_nombre": "Despacho", "remitente_email": "hola@despacho.example"})
    assert b.verificar() == "Despacho SL"
    ref = b.enviar("Novedades", "Hola", "<p>x</p>", DEST)
    assert ref == {"lista": 11, "campana": 42}
    assert all(c[2]["api-key"] == "xkeysib-1" and c[1].startswith("https://api.brevo.com/v3/") for c in s.llamadas)
    lista = next(c for c in s.llamadas if c[1].endswith("/contacts/lists"))
    assert lista[3] == {"name": "Novedades", "folderId": 3}
    contactos = [c[3] for c in s.llamadas if c[0] == "POST" and c[1].endswith("/contacts")]
    assert contactos[0] == {"email": "ana@x.example", "listIds": [11], "updateEnabled": True, "attributes": {"FIRSTNAME": "Ana"}} and len(contactos) == 2
    campana = next(c for c in s.llamadas if c[1].endswith("/emailCampaigns"))
    assert campana[3] == {"name": "Novedades", "subject": "Hola", "sender": {"name": "Despacho", "email": "hola@despacho.example"}, "htmlContent": "<p>x</p>", "recipients": {"listIds": [11]}}
    assert s.llamadas[-1][:2] == ("POST", "https://api.brevo.com/v3/emailCampaigns/42/sendNow")


def test_brevo_reintenta_sin_atributos_si_la_cuenta_no_los_tiene_y_falla_con_un_error_claro(monkeypatch):
    contactos = [(400, {"message": "Invalid attribute"}), (201, {"id": 1})]
    cuerpos = []

    def falso(metodo, url, cabeceras, cuerpo=None):
        if url.endswith("/contacts/lists"):
            return 201, {"id": 5}
        if url.endswith("/contacts/folders?limit=50&offset=0"):
            return 200, {"folders": [{"id": 1}]}
        if url.endswith("/contacts"):
            cuerpos.append(cuerpo)
            return contactos.pop(0)
        return 201, {"id": 8}
    monkeypatch.setattr(mp, "_peticion", falso)
    assert Brevo("k", {"remitente_email": "a@b.c"}).enviar("N", "A", "<p/>", DEST[:1])["lista"] == 5
    assert "attributes" in cuerpos[0] and "attributes" not in cuerpos[1]
    monkeypatch.setattr(mp, "_peticion", Servidor({("GET", "/account"): (401, {"message": "Key not found"})}))
    with pytest.raises(ErrorProveedor) as e:
        Brevo("mala", {}).verificar()
    assert "401" in str(e.value) and "Key not found" in str(e.value)
    with pytest.raises(ErrorProveedor):
        Brevo("k", {}).enviar("N", "A", "<p/>", DEST)                                                  # sin remitente
    with pytest.raises(ErrorProveedor):
        Brevo("k", {"remitente_email": "a@b.c"}).enviar("N", "A", "<p/>", [{"email": f"{i}@x.example", "nombre": ""} for i in range(2001)])


def test_brevo_trae_las_bajas_paginando(monkeypatch):
    paginas = {0: {"count": 600, "contacts": [{"email": "a@x.example", "emailBlacklisted": True}] + [{"email": f"n{i}@x.example", "emailBlacklisted": False} for i in range(499)]},
               500: {"count": 600, "contacts": [{"email": "B@x.example", "emailBlacklisted": True}] + [{"email": f"m{i}@x.example", "emailBlacklisted": False} for i in range(99)]}}
    monkeypatch.setattr(mp, "_peticion", lambda m, url, c, b=None: (200, paginas[int(url.rsplit("offset=", 1)[1])]))
    assert Brevo("k", {}).bajas({"lista": 11}) == {"baja": ["a@x.example", "b@x.example"], "rebotado": []}


def test_mailchimp_usa_el_centro_de_datos_de_la_clave_sube_miembros_crea_segmento_y_campana(monkeypatch):
    huella = hashlib.md5(b"ana@x.example").hexdigest()
    s = Servidor({("GET", "/ping"): (200, {}), ("GET", "/lists/aud1?fields=name"): (200, {"name": "Clientes"}), ("PUT", f"/lists/aud1/members/{huella}"): (200, {}),
                  ("PUT", "/members/*"): (200, {}), ("POST", "/lists/aud1/segments"): (200, {"id": 77}), ("POST", "/campaigns"): (200, {"id": "abc123"}),
                  ("PUT", "/campaigns/abc123/content"): (200, {}), ("POST", "/campaigns/abc123/actions/send"): (204, {})})
    monkeypatch.setattr(mp, "_peticion", s)
    m = Mailchimp("0123456789abcdef-us21", {"audiencia_id": "aud1", "remitente_nombre": "Despacho", "remitente_email": "hola@despacho.example"})
    assert m.verificar() == "audiencia «Clientes»"
    ref = m.enviar("Novedades", "Hola", "<p>x</p>", DEST)
    assert ref == {"audiencia": "aud1", "segmento": 77, "campana": "abc123"}
    assert all(c[1].startswith("https://us21.api.mailchimp.com/3.0/") and c[2]["Authorization"].startswith("Basic ") for c in s.llamadas)
    miembro = next(c for c in s.llamadas if f"/members/{huella}" in c[1])
    assert miembro[3] == {"email_address": "ana@x.example", "status_if_new": "subscribed", "merge_fields": {"FNAME": "Ana"}}
    seg = next(c for c in s.llamadas if c[1].endswith("/segments"))
    assert seg[3] == {"name": "Novedades", "static_segment": ["ana@x.example", "beto@x.example"]}
    camp = next(c for c in s.llamadas if c[0] == "POST" and c[1].endswith("/campaigns"))
    assert camp[3] == {"type": "regular", "recipients": {"list_id": "aud1", "segment_opts": {"saved_segment_id": 77}},
                       "settings": {"subject_line": "Hola", "title": "Novedades", "from_name": "Despacho", "reply_to": "hola@despacho.example"}}
    assert next(c for c in s.llamadas if c[1].endswith("/content"))[3] == {"html": "<p>x</p>"}
    assert s.llamadas[-1][:2] == ("POST", "https://us21.api.mailchimp.com/3.0/campaigns/abc123/actions/send")


def test_mailchimp_valida_la_clave_y_separa_bajas_de_rebotes(monkeypatch):
    with pytest.raises(ErrorProveedor):
        Mailchimp("sincentro", {}).verificar()
    with pytest.raises(ErrorProveedor):
        Mailchimp("k-us1", {}).enviar("N", "A", "<p/>", DEST)                                          # sin audiencia

    def falso(metodo, url, cabeceras, cuerpo=None):
        estado = url.split("status=")[1].split("&")[0]
        return 200, {"total_items": 1, "members": [{"email_address": {"unsubscribed": "Baja@x.example", "cleaned": "rebota@x.example"}[estado]}]}
    monkeypatch.setattr(mp, "_peticion", falso)
    assert Mailchimp("k-us1", {}).bajas({"audiencia": "aud1"}) == {"baja": ["baja@x.example"], "rebotado": ["rebota@x.example"]}


def test_los_errores_de_red_se_convierten_en_un_error_legible(monkeypatch):
    import urllib.error
    import urllib.request

    def cae(*a, **k):
        raise urllib.error.URLError("sin red")
    monkeypatch.setattr(urllib.request, "urlopen", cae)
    with pytest.raises(ErrorProveedor) as e:
        mp._peticion("GET", "https://api.brevo.com/v3/account", {})
    assert "No se ha podido conectar" in str(e.value)
