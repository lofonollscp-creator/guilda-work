"""Correos con el diseño de Guilda Work (app/correo_diseno.py + plantillas de Kratos): contenido, escape, contraste y que lleguen en texto plano y HTML."""
import re
import sys
from email import message_from_string, policy
from pathlib import Path

import pytest

from app import correo_diseno as d
from app import notificaciones_email as ne
from tests.a11y import contraste

RAIZ = Path(__file__).resolve().parent.parent


def test_construir_devuelve_texto_plano_y_html_con_lo_esencial():
    plano, html = d.construir("Tu acceso", ["Pulsa el botón."], boton=("Entrar", "https://app.guildawork.com/portal/acceso/abc"), codigo="123456", aviso="Ignóralo si no fuiste tú.")
    assert "Tu acceso" in plano and "Entrar: https://app.guildawork.com/portal/acceso/abc" in plano and "123456" in plano and "Ignóralo" in plano
    assert 'href="https://app.guildawork.com/portal/acceso/abc"' in html and ">Entrar<" in html and ">123456<" in html
    assert 'alt="Guilda Work"' in html and "email-fondo.jpg" in html and "email-logo.png" in html
    assert "<script" not in html.lower() and "backdrop-filter" not in html, "los clientes de correo no admiten ni scripts ni backdrop-filter"


def test_todo_texto_de_fuera_se_escapa():
    malo = '<img src=x onerror=alert(1)> "comillas" & <script>alert(2)</script>'
    plano, html = d.construir(malo, [malo], boton=(malo, 'https://x.test/?a="><script>alert(3)</script>'), cita=malo, preformateado=malo, aviso=malo, pie=malo)
    assert "<script>" not in html and "<img src=x" not in html
    assert '"><script>' not in html
    assert "&lt;script&gt;alert(2)&lt;/script&gt;" in html
    assert malo in plano, "el texto plano lleva el texto tal cual (no es HTML)"


def test_colores_del_correo_cumplen_aa_sobre_la_tarjeta():
    for nombre, color in (("texto", d.TEXTO), ("suave", d.TEXTO_SUAVE), ("apagado", d.TEXTO_APAGADO), ("acento", d.ACENTO)):
        assert contraste(color, d.FONDO_TARJETA) >= 4.5, nombre
    assert contraste(d.SOBRE_ACENTO, d.ACENTO) >= 4.5, "texto del botón sobre el lima"
    assert contraste(d.ACENTO, "#0a0a0c") >= 4.5, "código lima sobre su caja oscura"
    assert contraste(d.TEXTO_APAGADO, "#0c0e12") >= 4.5, "pie sobre su píldora"


def test_los_adornos_son_ligeros():
    for fichero in ("fotos/email-fondo.jpg", "email-logo.png"):
        assert 1_000 < (RAIZ / "app" / "static" / fichero).stat().st_size < 150_000, fichero


class _SMTP:
    enviados = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, u, p):
        pass

    def send_message(self, m):
        _SMTP.enviados.append(m)


@pytest.fixture
def smtp(monkeypatch):
    _SMTP.enviados = []
    monkeypatch.setattr(ne.smtplib, "SMTP", _SMTP)
    for k, v in (("PORTAL_SMTP_HOST", "smtp.x"), ("PORTAL_SMTP_USUARIO", "u"), ("PORTAL_SMTP_CONTRASENA", "p"), ("PORTAL_SMTP_REMITENTE", "avisos@x.test")):
        monkeypatch.setattr(ne, k, v)
    return _SMTP


def _partes(mensaje):
    m = message_from_string(mensaje.as_string(), policy=policy.default)
    return m.get_body(("plain",)).get_content(), m.get_body(("html",)).get_content(), m


def test_cada_aviso_sale_en_texto_plano_y_html(smtp):
    ne.enviar_enlace_portal("c@x.test", "https://app.guildawork.com/portal/acceso/tok")
    ne.enviar_solicitud_documento("c@x.test", "Modelo 036 <b>firmado</b>", "https://app.guildawork.com/portal/entrar")
    ne.enviar_enlace_pago("c@x.test", "Cuota trimestral", "https://pay.stripe.test/abc")
    ne.enviar_respuesta_portal("c@x.test", "Ya está <script>x</script>", "https://app.guildawork.com/portal/entrar")
    ne.enviar_recordatorio_vencimiento("c@x.test", "Cliente & Hijos", "303", "2T", "2026-10-20", 2, "https://app.guildawork.com/portal/entrar", "Gestoría <Demo>", "Facturas")
    assert len(smtp.enviados) == 5
    for m in smtp.enviados:
        plano, html, crudo = _partes(m)
        assert crudo.get_content_type() == "multipart/alternative" and len(plano) > 40 and html.startswith("<!doctype html>")
        assert "https://" in plano and "https://" in html and "<script" not in html.lower()
    assert "&lt;b&gt;firmado&lt;/b&gt;" in _partes(smtp.enviados[1])[1]
    assert "Cliente &amp; Hijos" in _partes(smtp.enviados[4])[1] and "Gestoría &lt;Demo&gt;" in _partes(smtp.enviados[4])[1]


def test_la_alerta_interna_mantiene_su_texto_plano_exacto(smtp, monkeypatch):
    monkeypatch.setattr(ne, "ALERTAS_ADMIN_EMAIL", "admin@x.test")
    ne.enviar_alerta_interna("[Guilda Work] copia atrasada", "línea 1\nlínea 2")
    plano, html, _ = _partes(smtp.enviados[0])
    assert plano == "línea 1\nlínea 2\n" and "copia atrasada" in html and "línea 2" in html


# ---- Plantillas de Kratos -----------------------------------------------------------------------------------------------------------------
def test_las_plantillas_de_kratos_estan_al_dia_con_el_generador(tmp_path):
    """Si cambia app/correo_diseno.py hay que regenerar deploy/kratos/courier-templates/ (scripts/generar_plantillas_kratos.py)."""
    sys.path.insert(0, str(RAIZ / "scripts"))
    import generar_plantillas_kratos as g

    g.DESTINO = tmp_path
    g.main()
    for ruta in g.PLANTILLAS:
        for nombre in ("email.subject.gotmpl", "email.body.gotmpl", "email.body.plaintext.gotmpl"):
            asi = (tmp_path / ruta / nombre).read_text(encoding="utf-8")
            esta = (RAIZ / "deploy" / "kratos" / "courier-templates" / ruta / nombre).read_text(encoding="utf-8")
            assert asi == esta, f"{ruta}/{nombre} desactualizada"


def test_las_plantillas_de_kratos_solo_usan_las_variables_que_kratos_da():
    permitidas = {"{{ .RecoveryCode }}", "{{ .VerificationCode }}", '{{- $l := printf "%v" (index .TransientPayload "lang") -}}', "{{- else -}}", "{{- end -}}",
                  '{{- if eq $l "ca" -}}', '{{- else if eq $l "en" -}}', '{{- else if eq $l "fr" -}}'}
    base = RAIZ / "deploy" / "kratos" / "courier-templates"
    ficheros = list(base.rglob("*.gotmpl"))
    assert len(ficheros) == 12
    for f in ficheros:
        usadas = set(re.findall(r"\{\{.*?\}\}", f.read_text(encoding="utf-8")))
        assert usadas <= permitidas, (f, usadas - permitidas)
    for carpeta, variable in (("recovery_code/valid", "{{ .RecoveryCode }}"), ("verification_code/valid", "{{ .VerificationCode }}")):
        for nombre in ("email.body.gotmpl", "email.body.plaintext.gotmpl"):          # el asunto NO lleva el código
            assert variable in (base / carpeta / nombre).read_text(encoding="utf-8")
    assert "template_override_path: /etc/config/kratos/courier-templates" in (RAIZ / "deploy" / "kratos" / "kratos.yml").read_text(encoding="utf-8")


# ---- Idioma y asunto de los correos de Kratos -----------------------------------------------------------------------------------------------
class _RespuestaFalsa:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"{}"


def _capturar(monkeypatch):
    from app import kratos as k

    vistos = []

    class Opener:
        def open(self, peticion, timeout=None):
            vistos.append(peticion.data.decode() if peticion.data else "")
            return _RespuestaFalsa()

    monkeypatch.setattr(k, "opener_sin_redireccion", lambda: Opener())
    return vistos


@pytest.mark.parametrize("cabecera,esperado", [("ca-ES,ca;q=0.9", "ca"), ("fr-FR", "fr"), ("en-GB,en;q=0.8", "en"), ("es-ES", "es"), ("de-DE", "es"), ("", "es")])
def test_el_proxy_de_kratos_dice_en_que_idioma_esta_la_pantalla(cliente, monkeypatch, cabecera, esperado):
    """La recuperación y la verificación mandan un correo desde Kratos: el idioma de la pantalla viaja como transient_payload (por defecto, castellano)."""
    import json
    import urllib.parse

    vistos = _capturar(monkeypatch)
    for ruta in ("recovery", "verification"):
        vistos.clear()
        r = cliente.post(f"/.ory/self-service/{ruta}?flow=abc", data={"method": "code", "email": "a@b.test", "csrf_token": "t"}, headers={"Accept-Language": cabecera})
        assert r.status_code == 200 and len(vistos) == 1
        campos = urllib.parse.parse_qs(vistos[0])
        assert campos["email"] == ["a@b.test"] and campos["method"] == ["code"] and campos["csrf_token"] == ["t"], "el resto del formulario llega intacto"
        assert json.loads(campos["transient_payload"][0]) == {"lang": esperado}


def test_el_proxy_no_toca_los_otros_formularios_ni_pisa_un_idioma_ya_indicado(cliente, monkeypatch):
    vistos = _capturar(monkeypatch)
    cliente.post("/.ory/self-service/settings?flow=abc", data={"method": "password", "password": "x"})
    cliente.post("/.ory/self-service/recovery?flow=abc", data={"method": "code", "email": "a@b.test", "transient_payload": '{"lang":"fr"}'}, headers={"Accept-Language": "ca"})
    assert "transient_payload" not in vistos[0]
    assert "fr" in vistos[1] and "ca" not in vistos[1]


def test_los_asuntos_de_kratos_no_llevan_el_codigo_y_hay_cuatro_idiomas():
    base = RAIZ / "deploy" / "kratos" / "courier-templates"
    for carpeta in ("recovery_code/valid", "verification_code/valid", "recovery_code/invalid", "verification_code/invalid"):
        asunto = (base / carpeta / "email.subject.gotmpl").read_text(encoding="utf-8")
        assert "Code }}" not in asunto and "{{ ." not in asunto, f"{carpeta}: el asunto no debe llevar el código"
        for idioma in ("ca", "en", "fr"):
            assert f'eq $l "{idioma}"' in asunto, (carpeta, idioma)
        cuerpo = (base / carpeta / "email.body.gotmpl").read_text(encoding="utf-8")
        for idioma in ("es", "ca", "en", "fr"):
            assert f'<html lang="{idioma}"' in cuerpo, (carpeta, idioma)
