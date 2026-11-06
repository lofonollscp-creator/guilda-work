"""Conversaciones libres entre el cliente y su gestoría en el portal (N3): abrir, contestar, leído por cada lado, cerrar, ligarlas a una petición, avisos y aislamiento."""
import pytest

from app import db, portal_conversaciones as pc, portal_peticiones as pp
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures


def _equipo(http, t, email="eq-conv@ejemplo.com"):
    uid = iniciar_sesion_de_prueba(http, email, "contrasena123")
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, True)
    return uid


def test_iniciar_valida_asunto_texto_y_tope_de_abiertas():
    t, u, c = _despacho("Conv valida")
    ficha = _ficha(c)
    with pytest.raises(ValueError, match="asunto"):
        pc.iniciar(ficha, "ab", "hola", "cliente")
    with pytest.raises(ValueError, match="mensaje"):
        pc.iniciar(ficha, "Una duda", "   ", "cliente")
    with pytest.raises(ValueError, match="Quién"):
        pc.iniciar(ficha, "Una duda", "hola", "otro")
    ids = [pc.iniciar(ficha, f"Hilo {i}", "hola", "cliente") for i in range(pc.MAX_ABIERTAS)]
    with pytest.raises(ValueError, match="demasiadas"):
        pc.iniciar(ficha, "Uno más", "hola", "cliente")
    pc.cambiar_estado(ficha, ids[0], abierta=False, por=u)
    pc.iniciar(ficha, "Ahora sí", "hola", "cliente")


def test_las_marcas_de_leido_son_de_cada_lado():
    t, u, c = _despacho("Conv leido")
    ficha = _ficha(c)
    cid = pc.iniciar(ficha, "Duda del IVA", "¿Puedo deducir esto?", "cliente", "titular@ejemplo.com")
    assert pc.sin_leer_equipo(t, c) == 1 and pc.sin_leer_cliente(ficha) == 0
    pc.responder(ficha, cid, "Sí, puedes.", "despacho", "eq@despacho.com")
    assert pc.sin_leer_cliente(ficha) == 1
    pc.marcar_leida(ficha, cid, "equipo")
    assert pc.sin_leer_equipo(t, c) == 0 and pc.sin_leer_cliente(ficha) == 1
    pc.marcar_leida(ficha, cid, "cliente")
    assert pc.sin_leer_cliente(ficha) == 0
    h = pc.listar(ficha)[0]
    assert h["mensajes"] == 2 and h["ultimo_de"] == "despacho" and h["ultimo_texto"] == "Sí, puedes."


def test_cerrar_reabrir_y_quien_puede_escribir_en_uno_cerrado():
    t, u, c = _despacho("Conv cerrar")
    ficha = _ficha(c)
    cid = pc.iniciar(ficha, "Algo", "hola", "despacho")
    assert pc.cambiar_estado(ficha, cid, abierta=False, por=u) and not pc.cambiar_estado(ficha, cid, abierta=False, por=u)
    assert pc.responder(ficha, cid, "¿seguimos?", "despacho") is False                  # el equipo primero reabre
    assert pc.responder(ficha, cid, "Una cosa más", "cliente") is True                  # el cliente sí, y lo reabre
    assert pc.obtener(ficha, cid)["estado"] == "abierta"
    assert pc.responder(ficha, 99999, "hola", "cliente") is False


def test_un_hilo_ajeno_no_se_ve_ni_se_contesta():
    t, u, c = _despacho("Conv propia")
    t2, u2, c2 = _despacho("Conv ajena", cliente_email="otro@ejemplo.com", cliente_nombre="Otro SL")
    cid = pc.iniciar(_ficha(c), "Privado", "secreto", "cliente")
    assert pc.obtener(_ficha(c2), cid) is None and pc.listar(_ficha(c2)) == []
    assert pc.responder(_ficha(c2), cid, "intruso", "cliente") is False


def test_el_cliente_abre_un_hilo_desde_el_portal_y_avisa_al_equipo(cliente, correo):
    t, u, c = _despacho("Conv portal")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "Nueva conversación" in _html(cliente, "/portal/mensajes")
    assert "Asunto" in _html(cliente, "/portal/conversaciones/nueva")
    malo = cliente.post("/portal/conversaciones/nueva", data={"asunto": "x", "texto": "hola"})
    assert malo.status_code == 200 and "asunto" in malo.get_data(as_text=True)
    r = cliente.post("/portal/conversaciones/nueva", data={"asunto": "Cambio de domicilio", "texto": "Me mudo el mes que viene"})
    assert r.status_code == 302 and "enviado=1" in r.headers["Location"]
    cid = pc.listar(_ficha(c))[0]["id"]
    pagina = _html(cliente, f"/portal/conversaciones/{cid}")
    assert "Cambio de domicilio" in pagina and "Me mudo el mes que viene" in pagina
    notis = db.get_connection().execute("SELECT titulo FROM notificaciones WHERE usuario_id = ?", (u,)).fetchall()
    assert any("Cliente P SL" in n["titulo"] and "Cambio de domicilio" in n["titulo"] for n in notis)
    assert "Cambio de domicilio" in _html(cliente, "/portal/mensajes")
    r = cliente.post(f"/portal/conversaciones/{cid}", data={"texto": "Y además cambia el teléfono"})
    assert r.status_code == 302
    assert pc.obtener(_ficha(c), cid)["mensajes"][-1]["texto"] == "Y además cambia el teléfono"


def test_la_gestoria_escribe_el_cliente_lo_ve_sin_leer_y_se_marca_al_abrirlo(cliente, correo):
    t, u, c = _despacho("Conv equipo")
    uid = _equipo(cliente, t)
    r = cliente.post(f"/fiscal/clientes/{c}/conversaciones", data={"asunto": "Falta una factura", "texto": "Nos falta la de agosto", "avisar": "1"})
    assert r.status_code == 302 and "#conversacion-" in r.headers["Location"]
    cid = pc.listar(_ficha(c))[0]["id"]
    assert any("Falta una factura" in m[2] or "Nos falta" in m[2] for m in correo), "se avisó al cliente por correo"
    assert "Falta una factura" in _html(cliente, f"/fiscal/clientes/{c}/editar")
    assert pc.sin_leer_cliente(_ficha(c)) == 1
    from app.main import app as flask_app
    web = flask_app.test_client()
    _entrar(web, c, "titular@ejemplo.com")
    assert 'portal-nav-insignia' in _html(web, "/portal/mensajes")
    _html(web, f"/portal/conversaciones/{cid}")
    assert pc.sin_leer_cliente(_ficha(c)) == 0
    web.post(f"/portal/conversaciones/{cid}", data={"texto": "Os la mando hoy"})
    assert pc.sin_leer_equipo(t, c) == 1
    assert cliente.post(f"/fiscal/clientes/{c}/conversaciones/{cid}/responder", data={"texto": "Recibida, gracias"}).status_code == 302
    assert pc.sin_leer_equipo(t, c) == 0 and pc.obtener(_ficha(c), cid)["mensajes"][-1]["de"] == "despacho"
    assert cliente.post(f"/fiscal/clientes/{c}/conversaciones/{cid}/cerrar").status_code == 302
    assert pc.obtener(_ficha(c), cid)["estado"] == "cerrada"
    cliente.post(f"/fiscal/clientes/{c}/conversaciones/{cid}/responder", data={"texto": "no debe entrar"})
    assert pc.obtener(_ficha(c), cid)["mensajes"][-1]["texto"] == "Recibida, gracias"
    assert cliente.post(f"/fiscal/clientes/{c}/conversaciones/{cid}/inventada").status_code == 404


def test_hilo_sobre_una_peticion_y_roles_de_solo_lectura(cliente, correo):
    t, u, c = _despacho("Conv peticion")
    pid = pp.crear(_ficha(c), "Extracto del 3T", por=u)
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "Preguntar a tu gestoría" in _html(cliente, f"/portal/peticiones/{pid}")
    assert "Sobre: Extracto del 3T" in _html(cliente, f"/portal/conversaciones/nueva?peticion={pid}")
    assert cliente.get("/portal/conversaciones/nueva?peticion=99999").status_code == 404
    cliente.post("/portal/conversaciones/nueva", data={"asunto": "Sobre: Extracto del 3T", "texto": "¿Vale el PDF del banco?", "peticion": pid})
    h = pc.listar(_ficha(c))[0]
    assert h["peticion_id"] == pid
    assert "Extracto del 3T" in _html(cliente, f"/portal/conversaciones/{h['id']}")


def test_otro_cliente_no_abre_un_hilo_ajeno_por_la_url(cliente, correo):
    t, u, c = _despacho("Conv url")
    t2, u2, c2 = _despacho("Conv url otra", cliente_email="otro@ejemplo.com", cliente_nombre="Otro SL")
    cid = pc.iniciar(_ficha(c), "Privado", "secreto", "cliente")
    _entrar(cliente, c2, "otro@ejemplo.com")
    assert cliente.get(f"/portal/conversaciones/{cid}").status_code == 404
    assert cliente.post(f"/portal/conversaciones/{cid}", data={"texto": "intruso"}).status_code == 404
