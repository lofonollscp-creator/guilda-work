"""Recordatorio a los clientes antes del cierre del trimestre (facturas_contables.para_recordar / recordar, /contabilidad/recordatorios). El correo es siempre un doble: no sale nada."""
import pytest

from app import db, facturas_contables as fc, notificaciones_email as ne, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_facturas_contables import _datos, LINEA

URL = "http://portal.test/portal/entrar"


@pytest.fixture
def correo(monkeypatch):
    class C:
        enviados = []
        fallar = False
    c = C()
    monkeypatch.setattr(ne, "configurado", lambda: True)
    def enviar(destino, asunto, cuerpo, html=None):
        if c.fallar:
            raise ne.ErrorNotificacionesEmail("SMTP caído")
        c.enviados.append((destino, asunto, cuerpo, html))
    monkeypatch.setattr(ne, "_enviar", enviar)
    return c


def _despacho():
    t = db.crear_tenant("Despacho recordar")
    u = db.crear_usuario_vinculado_a_kratos("recordar1@ejemplo.com", "k-recordar1"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    ids = {n: crear_cliente_fiscal(t, n, nif=nif, email=mail) for n, nif, mail in (("Con facturas SL", "B11111111", "a@ejemplo.com"), ("Sin nada SL", "B22222222", "b@ejemplo.com"), ("Sin email SL", "B33333333", None))}
    return t, u, ids


def test_se_ve_cuanto_ha_anotado_cada_cliente_ese_trimestre(correo):
    t, u, ids = _despacho()
    fc.crear(t, u, ids["Con facturas SL"], _datos(fecha="2026-08-10"), [LINEA])
    fc.crear(t, u, ids["Con facturas SL"], _datos(numero="F-2", fecha="2026-01-10"), [LINEA])      # otro trimestre
    por = {c["nombre"]: c for c in fc.para_recordar(t, u, "2026-T3")}
    assert (por["Con facturas SL"]["anotadas"], por["Con facturas SL"]["por_revisar"]) == (1, 1) and por["Sin nada SL"]["anotadas"] == 0
    assert por["Sin email SL"]["puede"] is False and por["Sin nada SL"]["puede"] is True
    assert [c["nombre"] for c in fc.para_recordar(t, u, "2026-T3")][0] in ("Sin email SL", "Sin nada SL"), "primero los que menos han entregado"


def test_el_recordatorio_sale_con_el_trimestre_la_fecha_y_el_enlace_y_se_anota(correo):
    t, u, ids = _despacho()
    r = fc.recordar(t, u, [ids["Sin nada SL"]], "2026-T3", "2026-10-05", URL)
    assert r == {"enviados": 1, "omitidos": []}
    destino, asunto, cuerpo, html = correo.enviados[0]
    assert destino == "b@ejemplo.com" and "2026-T3" in asunto and "2026-T3" in cuerpo and "05" in cuerpo and URL in cuerpo and "Sin nada SL" in cuerpo
    assert next(c for c in fc.para_recordar(t, u, "2026-T3") if c["id"] == ids["Sin nada SL"])["reciente"] is True


def test_no_se_vuelve_a_escribir_al_mismo_cliente_enseguida_ni_se_escribe_a_quien_no_tiene_email(correo):
    t, u, ids = _despacho()
    fc.recordar(t, u, [ids["Sin nada SL"]], "2026-T3", None, URL)
    r = fc.recordar(t, u, [ids["Sin nada SL"], ids["Sin email SL"], ids["Sin nada SL"]], "2026-T3", None, URL)
    assert r["enviados"] == 0 and len(correo.enviados) == 1
    assert {m for _n, m in r["omitidos"]} == {"ya se le recordó hace menos de 3 días", "no tiene email"}
    assert fc.recordar(t, u, [ids["Sin nada SL"]], "2026-T4", None, URL)["enviados"] == 1, "otro trimestre sí"


def test_un_fallo_de_envio_no_cuenta_como_recordado(correo):
    t, u, ids = _despacho()
    correo.fallar = True
    r = fc.recordar(t, u, [ids["Sin nada SL"]], "2026-T3", None, URL)
    assert r["enviados"] == 0 and r["omitidos"][0][1] == "SMTP caído"
    correo.fallar = False
    assert fc.recordar(t, u, [ids["Sin nada SL"]], "2026-T3", None, URL)["enviados"] == 1


def test_sin_correo_configurado_o_con_datos_malos_no_se_envia_nada(correo, monkeypatch):
    t, u, ids = _despacho()
    with pytest.raises(ValueError, match="trimestre"):
        fc.recordar(t, u, [ids["Sin nada SL"]], "ayer", None, URL)
    with pytest.raises(ValueError, match="fecha"):
        fc.recordar(t, u, [ids["Sin nada SL"]], "2026-T3", "mañana", URL)
    monkeypatch.setattr(ne, "configurado", lambda: False)
    with pytest.raises(ValueError, match="no está configurado"):
        fc.recordar(t, u, [ids["Sin nada SL"]], "2026-T3", None, URL)
    assert correo.enviados == []


def test_no_se_escribe_a_clientes_de_otro_despacho(correo):
    t, u, ids = _despacho()
    t2 = db.crear_tenant("Otro despacho recordar")
    ajeno = crear_cliente_fiscal(t2, "Ajeno SL", nif="B44444444", email="ajeno@ejemplo.com")
    r = fc.recordar(t, u, [ajeno], "2026-T3", None, URL)
    assert r["enviados"] == 0 and correo.enviados == [] and "no es un cliente" in r["omitidos"][0][1]


def test_el_texto_del_cliente_no_inyecta_html_en_el_correo(correo):
    t, u, ids = _despacho()
    c = crear_cliente_fiscal(t, "<b>Mala</b> & Co", nif="B55555555", email="mala@ejemplo.com")
    fc.recordar(t, u, [c], "2026-T3", None, URL)
    html = correo.enviados[0][3]
    assert "<b>Mala</b>" not in html and "&lt;b&gt;Mala" in html


def test_desde_la_web_hay_que_confirmar_y_se_ve_el_resultado(cliente, correo):
    uid = iniciar_sesion_de_prueba(cliente, "recordarweb@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho recordar web"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Web SL", nif="B66666666", email="web@ejemplo.com")
    html = cliente.get("/contabilidad/recordatorios?trimestre=2026-T3").get_data(as_text=True)
    assert "Cliente Web SL" in html and "web@ejemplo.com" in html and "Enviar el recordatorio" in html
    assert "Recordar a los clientes" in cliente.get("/contabilidad/").get_data(as_text=True)
    r = cliente.post("/contabilidad/recordatorios", data={"trimestre": "2026-T3", "cliente_id": [c]})
    assert "confirmar" in r.get_data(as_text=True) and correo.enviados == []
    r = cliente.post("/contabilidad/recordatorios", data={"trimestre": "2026-T3", "cliente_id": [c], "confirmo": "1", "fecha_limite": "2026-10-05"})
    assert "Recordatorios enviados: 1" in r.get_data(as_text=True) and len(correo.enviados) == 1
    assert "/portal/entrar" in correo.enviados[0][2]
    assert "Reciente" in cliente.get("/contabilidad/recordatorios?trimestre=2026-T3").get_data(as_text=True)
