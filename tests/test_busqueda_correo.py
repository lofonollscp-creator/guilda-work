"""Operadores de búsqueda de correo: parser puro y bandeja/API reales."""
import pytest

from app import db
from app.busqueda_correo import interpretar
from tests.conftest import iniciar_sesion_de_prueba

CATS = [(1, "Facturas"), (2, "Personal"), (3, "Facturas recibidas")]
CLIS = [(10, "Sol y Mar SL"), (11, "Taller García"), (12, "Taller Gómez")]


def test_operadores_basicos():
    c = interpretar('de:ana asunto:"cierre de mes" adjunto: es:noleido otra cosa', CATS, CLIS)
    assert c.filtros == {"remitente": "ana", "asunto": "cierre de mes", "con_adjuntos": True}
    assert c.solo_no_leidos and c.texto == "otra cosa" and c.sin_resolver == []


@pytest.mark.parametrize("q,clave", [("from:ana", "remitente"), ("to:ana", "destinatarios"), ("subject:x", "asunto"), ("tiene:adjunto", "con_adjuntos"), ("has:attachment", "con_adjuntos"), ("es:starred", "solo_destacados"), ("es:destacado", "solo_destacados"), ("is:destacat", "solo_destacados")])
def test_alias_en_varios_idiomas(q, clave):
    assert clave in interpretar(q).filtros


def test_fechas_antes_es_exclusivo():
    c = interpretar("antes:2026-10-01 despues:2026-09")
    assert c.filtros == {"hasta": "2026-09-30", "desde": "2026-09-01"}
    assert interpretar("antes:ayer").texto == "antes:ayer" and "hasta" not in interpretar("antes:ayer").filtros     # no entendido: se queda como texto


def test_cliente_y_categoria_por_nombre_sin_acentos_y_unicos():
    assert interpretar('cliente:"sol y mar"', CATS, CLIS).filtros == {"cliente_fiscal_id": 10}
    assert interpretar("cliente:garcia", CATS, CLIS).filtros == {"cliente_fiscal_id": 11}
    assert interpretar("categoria:Facturas", CATS, CLIS).filtros == {"categoria_id": 1}          # exacta gana a «Facturas recibidas»
    c = interpretar("cliente:taller categoria:zzz", CATS, CLIS)                                    # ambiguo / inexistente
    assert c.filtros == {} and c.sin_resolver == ["cliente:taller", "categoria:zzz"] and c.texto == ""


def test_lo_que_no_es_operador_se_conserva():
    for q in ["hora: 10", "reunión a las 10:30", "http://x.com/a", "nota:algo", "re: factura", "de:", ""]:
        assert interpretar(q).filtros == {} and not interpretar(q).solo_no_leidos, q
    assert interpretar("re: factura de:").texto == "re: factura de:"
    assert interpretar("pedido de:luis urgente").texto == "pedido urgente"


def test_texto_hostil():
    for q in [":" * 300, 'de:"' * 100, "es:" * 200, "\x00de:x"]:
        interpretar(q, CATS, CLIS)


def _bandeja(cliente, email):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    return _sembrar(uid, email)


def _sembrar(uid, email):
    tenant = db.crear_tenant(f"Despacho bc {email}")
    db.asignar_tenant(uid, tenant)
    cuenta = db.crear_cuenta_correo(uid, "c", "imap", "h", 993, "u")
    cli = db.crear_cliente_fiscal(tenant, "Sol y Mar SL")
    conn = db.get_connection()
    filas = [
        (1, "Factura de octubre", "ana@x.com", "yo@x.com", "2026-10-02T10:00:00", 0, cli),
        (2, "Reunión", "luis@x.com", "ana@x.com", "2026-09-10T10:00:00", 1, None),
        (3, "Factura vieja", "ana@y.com", "yo@x.com", "2026-08-01T10:00:00", 1, cli),
    ]
    for uid_m, asunto, de, para, fecha, leido, c in filas:
        conn.execute("INSERT INTO correo_mensajes (cuenta_id, carpeta, uid, asunto, remitente, destinatarios, fecha, leido, cliente_fiscal_id, descargado_en) VALUES (?, 'INBOX', ?, ?, ?, ?, ?, ?, ?, '2026-10-01')", (cuenta, uid_m, asunto, de, para, fecha, leido, c))
    conn.commit()
    conn.close()
    return cuenta


def _asuntos(html):
    return [a for a in ("Factura de octubre", "Reunión", "Factura vieja") if a in html]


def test_la_bandeja_aplica_los_operadores(cliente):
    cuenta = _bandeja(cliente, "bc-1@x.com")
    def buscar(q):
        return cliente.get("/correo/", query_string={"cuenta_id": cuenta, "q": q}).get_data(as_text=True)
    assert _asuntos(buscar("de:ana")) == ["Factura de octubre", "Factura vieja"]
    assert _asuntos(buscar("de:ana@x")) == ["Factura de octubre"]
    assert _asuntos(buscar("para:ana")) == ["Reunión"]
    assert _asuntos(buscar("es:noleido")) == ["Factura de octubre"]
    assert _asuntos(buscar("cliente:sol")) == ["Factura de octubre", "Factura vieja"]
    assert _asuntos(buscar("cliente:sol antes:2026-09-01")) == ["Factura vieja"]
    assert _asuntos(buscar("asunto:factura despues:2026-09-01")) == ["Factura de octubre"]
    assert _asuntos(buscar("de:ana octubre")) == ["Factura de octubre"]           # operador + texto libre (FTS)
    html = buscar("cliente:nadie")
    assert "No se ha encontrado una única coincidencia" in html and "cliente:nadie" in html
    assert "100%" not in buscar("de:50%") and _asuntos(buscar("de:50%")) == []        # % es literal


def test_la_api_aplica_los_operadores(cliente):
    token = cliente.post("/api/v1/auth/registro", json={"email": "bc-2@x.com", "contrasena": "contrasena123"}).get_json()["data"]["token"]
    conn = db.get_connection()
    uid = conn.execute("SELECT id FROM usuarios WHERE email = 'bc-2@x.com'").fetchone()[0]
    conn.close()
    cuenta = _sembrar(uid, "bc-2@x.com")
    r = cliente.get("/api/v1/correo/mensajes", query_string={"cuenta_id": cuenta, "q": "de:ana es:noleido"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert [m["asunto"] for m in r.get_json()["data"]] == ["Factura de octubre"]
