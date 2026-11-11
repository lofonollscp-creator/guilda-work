"""Cuestionarios del cliente (Q8): plantillas y propios, respuestas validadas por tipo, avisos y revisión por el equipo."""
import re
import pytest

from app import db, portal_cuestionarios as pq
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures


def _equipo(http, t, email="eq-cuest@ejemplo.com"):
    uid = iniciar_sesion_de_prueba(http, email, "contrasena123")
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, True)
    return uid


def test_preguntas_desde_texto_tipos_obligatorias_y_limites():
    qs = pq.preguntas_desde_texto("¿Nombre?\n¿Hijos? | numero *\n\n¿Casado? | si no\n¿Desde cuándo? | fecha")
    assert [(q["texto"], q["tipo"], q["obligatoria"]) for q in qs] == [("¿Nombre?", "texto", False), ("¿Hijos?", "numero", True), ("¿Casado?", "si_no", False), ("¿Desde cuándo?", "fecha", False)]
    with pytest.raises(ValueError, match="al menos una"):
        pq.preguntas_desde_texto("  \n  ")
    with pytest.raises(ValueError, match="tipo de pregunta"):
        pq.preguntas_desde_texto("¿Algo? | inventado")
    with pytest.raises(ValueError, match="Como máximo"):
        pq.preguntas_desde_texto("\n".join(f"Pregunta {i}" for i in range(pq.MAX_PREGUNTAS + 1)))


def test_crear_valida_titulo_preguntas_opciones_fecha_y_tope():
    t, u, c = _despacho("Cuest crear")
    ficha = _ficha(c)
    q = [{"texto": "¿Algo?", "tipo": "texto", "obligatoria": True}]
    with pytest.raises(ValueError, match="título"):
        pq.crear(ficha, "ab", q)
    with pytest.raises(ValueError, match="al menos una"):
        pq.crear(ficha, "Título válido", [])
    with pytest.raises(ValueError, match="no es válida"):
        pq.crear(ficha, "Título válido", [{"texto": "x", "tipo": "raro"}])
    with pytest.raises(ValueError, match="al menos dos"):
        pq.crear(ficha, "Título válido", [{"texto": "¿Cuál?", "tipo": "opcion", "opciones": ["Solo una"]}])
    with pytest.raises(ValueError, match="fecha límite"):
        pq.crear(ficha, "Título válido", q, fecha_limite="mañana")
    for i in range(pq.MAX_ABIERTOS):
        pq.crear(ficha, f"Cuestionario {i}", q)
    with pytest.raises(ValueError, match="demasiados"):
        pq.crear(ficha, "Uno más", q)
    with pytest.raises(ValueError, match="no existe"):
        pq.desde_plantilla(ficha, "inventada")


def test_validar_respuestas_por_tipo():
    preguntas = [{"id": "p1", "texto": "Hijos", "tipo": "numero", "obligatoria": True}, {"id": "p2", "texto": "Casado", "tipo": "si_no", "obligatoria": True},
                 {"id": "p3", "texto": "Desde", "tipo": "fecha", "obligatoria": False}, {"id": "p4", "texto": "Cambio", "tipo": "opcion", "opciones": ["A", "B"], "obligatoria": False},
                 {"id": "p5", "texto": "Notas", "tipo": "texto", "obligatoria": False}]
    assert pq.validar_respuestas(preguntas, {"p1": "2,5", "p2": "si", "p3": "2026-05-01", "p4": "B", "p5": " algo "}) == {"p1": "2.5", "p2": "si", "p3": "2026-05-01", "p4": "B", "p5": "algo"}
    for malo, texto in (({"p2": "si"}, "Falta contestar"), ({"p1": "dos", "p2": "si"}, "escribe un número"), ({"p1": "1", "p2": "quizá"}, "sí o no"),
                        ({"p1": "1", "p2": "no", "p3": "31/12"}, "fecha válida"), ({"p1": "1", "p2": "no", "p4": "Z"}, "una de las opciones")):
        with pytest.raises(ValueError, match=texto):
            pq.validar_respuestas(preguntas, malo)
    assert pq.validar_respuestas(preguntas, {"p1": "0", "p2": "no"}) == {"p1": "0", "p2": "no"}


def test_el_equipo_manda_una_plantilla_el_cliente_contesta_y_el_equipo_lo_recibe(cliente, correo):
    t, u, c = _despacho("Cuest flujo")
    _equipo(cliente, t)
    r = cliente.post(f"/fiscal/clientes/{c}/cuestionarios", data={"plantilla": "renta", "avisar": "1", "fecha_limite": "2027-06-30"})
    assert r.status_code == 302 and "#cuestionario-" in r.headers["Location"]
    q = pq.listar(_ficha(c))[0]
    assert q["titulo"].startswith("Datos para tu declaración") and q["estado"] == "pendiente" and any("contestes un cuestionario" in m[2] or "contestes unas preguntas" in m[1] for m in correo)
    from app.main import app as flask_app
    web = flask_app.test_client()
    _entrar(web, c, "titular@ejemplo.com")
    inicio = _html(web, "/portal/")
    assert "Tu gestoría te pide que contestes" in inicio and f"/portal/cuestionarios/{q['id']}" in inicio
    assert q["titulo"] in _html(web, "/portal/cuestionarios") and "Por contestar" in _html(web, "/portal/cuestionarios")
    form = _html(web, f"/portal/cuestionarios/{q['id']}")
    assert "Cuántos hijos" in form and 'type="radio"' in form and "Enviar mis respuestas" in form
    faltan = web.post(f"/portal/cuestionarios/{q['id']}", data={"p1": "si"})
    assert faltan.status_code == 200 and "Falta contestar" in faltan.get_data(as_text=True) and pq.obtener(_ficha(c), q["id"])["estado"] == "pendiente"
    ok = web.post(f"/portal/cuestionarios/{q['id']}", data={"p1": "no", "p2": "2", "p3": "no", "p4": "no", "p7": "Nada más"})
    assert ok.status_code == 302 and "enviado=1" in ok.headers["Location"]
    hecho = pq.obtener(_ficha(c), q["id"])
    assert hecho["estado"] == "respondido" and hecho["respuestas"]["p2"] == "2" and hecho["respondido_por"] == "titular@ejemplo.com"
    assert "Tus respuestas" in _html(web, f"/portal/cuestionarios/{q['id']}") and "Enviar mis respuestas" not in _html(web, f"/portal/cuestionarios/{q['id']}")
    assert web.post(f"/portal/cuestionarios/{q['id']}", data={"p1": "si", "p2": "9", "p3": "no", "p4": "no"}).status_code == 403              # ya contestado: no se cambia
    notis = db.get_connection().execute("SELECT titulo FROM notificaciones WHERE usuario_id = ?", (u,)).fetchall()
    assert any("ha contestado" in n["titulo"] for n in notis)
    assert "Contestado: por revisar" in _html(cliente, f"/fiscal/clientes/{c}/editar") and "Nada más" in _html(cliente, f"/fiscal/clientes/{c}/editar")
    assert cliente.post(f"/fiscal/clientes/{c}/cuestionarios/{q['id']}/recibido").status_code == 302 and pq.obtener(_ficha(c), q["id"])["estado"] == "recibido"
    assert "Recibido por tu gestoría" in _html(web, "/portal/cuestionarios")
    assert "Tu gestoría te pide que contestes" not in re.sub(r'<details class="pv-campana.*?</details>', "", _html(web, "/portal/"), flags=re.S)                                                                  # ya no está pendiente


def test_reabrir_borra_las_respuestas_y_cancelar_lo_saca_de_pendientes(cliente, correo):
    t, u, c = _despacho("Cuest reabrir")
    _equipo(cliente, t)
    ficha = _ficha(c)
    qid = pq.desde_plantilla(ficha, "domicilio", u)
    assert pq.responder(ficha, qid, {"p1": "Calle Nueva 1", "p2": "2026-10-01", "p3": "si"}, "titular@ejemplo.com")
    assert pq.responder(ficha, qid, {"p1": "otra"}, "x") is False                                                    # ya no admite respuestas
    assert cliente.post(f"/fiscal/clientes/{c}/cuestionarios/{qid}/reabrir").status_code == 302
    q = pq.obtener(ficha, qid)
    assert q["estado"] == "pendiente" and q["respuestas"] is None and q["respondido_en"] is None
    cliente.post(f"/fiscal/clientes/{c}/cuestionarios/{qid}/cancelar")
    assert pq.obtener(ficha, qid)["estado"] == "cancelado" and pq.pendientes_del_cliente(c) == []
    assert cliente.post(f"/fiscal/clientes/{c}/cuestionarios/{qid}/cancelar").status_code == 302                                   # repetirlo no rompe (avisa)
    assert cliente.post(f"/fiscal/clientes/{c}/cuestionarios/{qid}/inventada").status_code == 404 and cliente.post(f"/fiscal/clientes/{c}/cuestionarios/99999/recibido").status_code == 404


def test_un_cuestionario_propio_con_preguntas_escritas(cliente, correo):
    t, u, c = _despacho("Cuest propio")
    _equipo(cliente, t)
    cliente.post(f"/fiscal/clientes/{c}/cuestionarios", data={"plantilla": "propio", "titulo": "Datos del vehículo", "preguntas": "Matrícula *\nKilómetros | numero\n¿De uso profesional? | si_no"})
    q = pq.listar(_ficha(c))[0]
    assert q["titulo"] == "Datos del vehículo" and [(p["tipo"], p["obligatoria"]) for p in q["preguntas"]] == [("texto", True), ("numero", False), ("si_no", False)]
    mal = cliente.post(f"/fiscal/clientes/{c}/cuestionarios", data={"plantilla": "propio", "titulo": "x", "preguntas": "¿Algo?"}, follow_redirects=True)
    assert "título" in mal.get_data(as_text=True)


def test_otro_cliente_no_ve_los_cuestionarios_ajenos_y_quien_solo_consulta_no_contesta(cliente, correo):
    from app import portal_personas
    t, u, c = _despacho("Cuest ajeno")
    t2, u2, c2 = _despacho("Cuest ajeno 2", cliente_email="otro@ejemplo.com", cliente_nombre="Otro SL")
    qid = pq.desde_plantilla(_ficha(c), "domicilio", u)
    _entrar(cliente, c2, "otro@ejemplo.com")
    assert cliente.get(f"/portal/cuestionarios/{qid}").status_code == 404 and cliente.post(f"/portal/cuestionarios/{qid}", data={"p1": "x"}).status_code == 404
    portal_personas.anadir(_ficha(c), "lector@ejemplo.com", "Lector", "consulta", por=u)
    from app.main import app as flask_app
    web = flask_app.test_client()
    _entrar(web, c, "lector@ejemplo.com")
    assert "Enviar mis respuestas" not in _html(web, f"/portal/cuestionarios/{qid}")
    assert web.post(f"/portal/cuestionarios/{qid}", data={"p1": "x", "p2": "2026-01-01", "p3": "si"}).status_code == 403
