"""Inicio del portal con una sola acción principal (Q3): lo siguiente, el resto recogido y «estás al día»."""
from app import portal_conversaciones as pc, portal_peticiones as pp
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures


def test_sin_nada_pendiente_dice_que_esta_al_dia(cliente, correo):
    t, u, c = _despacho("Inicio vacio")
    _entrar(cliente, c, "titular@ejemplo.com")
    html = _html(cliente, "/portal/")
    assert "portal-al-dia" in html and "Estás al día" in html and "portal-hoy-principal" not in html


def test_con_una_cosa_pendiente_es_la_principal_con_su_boton_y_sin_lista_de_otras(cliente, correo):
    t, u, c = _despacho("Inicio una")
    pid = pp.crear(_ficha(c), "Extracto del 3T", por=u)
    _entrar(cliente, c, "titular@ejemplo.com")
    html = _html(cliente, "/portal/")
    assert "portal-hoy-principal" in html and "Lo siguiente que tienes que hacer" in html and "Extracto del 3T" in html and f"/portal/peticiones/{pid}" in html
    assert "portal-hoy-otras" not in html and "Estás al día" not in html


def test_con_varias_la_primera_destaca_y_las_demas_van_recogidas(cliente, correo):
    t, u, c = _despacho("Inicio varias")
    ficha = _ficha(c)
    pp.crear(ficha, "Primera petición", por=u)
    pp.crear(ficha, "Segunda petición", por=u)
    pc.iniciar(ficha, "Duda del trimestre", "¿Podéis mirar esto?", "despacho", "eq@despacho.com")
    _entrar(cliente, c, "titular@ejemplo.com")
    html = _html(cliente, "/portal/")
    assert html.count("portal-hoy-principal") >= 1 and "Otras 2 cosas pendientes" in html and "portal-hoy-otras" in html
    assert "Duda del trimestre" in html                                                       # el mensaje nuevo de la gestoría también cuenta como pendiente


def test_un_mensaje_leido_de_la_gestoria_deja_de_ser_pendiente(cliente, correo):
    t, u, c = _despacho("Inicio leido")
    ficha = _ficha(c)
    cid = pc.iniciar(ficha, "Aviso importante", "Mira esto", "despacho", "eq@despacho.com")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "Aviso importante" in _html(cliente, "/portal/")
    cliente.get(f"/portal/conversaciones/{cid}")
    assert "Aviso importante" not in _html(cliente, "/portal/") and "Estás al día" in _html(cliente, "/portal/")
