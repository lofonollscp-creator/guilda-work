"""Memoria del cliente (W11): la escribe una persona, la IA solo propone y nunca cambia nada sola."""
import pytest

from app import cliente_memoria as cm, db, ia_asistente, portal_conversaciones
from tests.conftest import iniciar_sesion_de_prueba


def _equipo(cliente=None, n=1):
    from app import ia_propuestas
    ia_propuestas._ULTIMA_GENERACION.clear()                                                               # los ids de despacho se repiten entre pruebas
    t = db.crear_tenant(f"Memoria {n}")
    if cliente is not None:
        u = iniciar_sesion_de_prueba(cliente, f"memoria{n}@ejemplo.com", "contrasena123")
    else:
        u = db.crear_usuario_vinculado_a_kratos(f"memoria{n}@ejemplo.com", f"k-memoria{n}")
    db.asignar_tenant(u, t)
    fid = db.crear_cliente_fiscal(t, f"Cliente Memoria {n} SL", email=f"m{n}@ejemplo.com")
    return t, u, fid


def test_guardar_limpia_el_texto_y_deja_constancia():
    t, u, fid = _equipo()
    cm.guardar(t, u, fid, "  Prefiere WhatsApp \n\n  Cambió de domicilio en marzo  ")
    m = cm.obtener(t, fid)
    assert m["texto"] == "Prefiere WhatsApp\nCambió de domicilio en marzo" and m["actualizado_por"] == u and m["borrador"] == ""
    cm.guardar(t, u, fid, "x" * 5000)
    assert len(cm.obtener(t, fid)["texto"]) == cm.MAX_TEXTO
    assert cm.obtener(t, 99999)["texto"] == ""                                                       # sin memoria: vacía, no error


def test_la_ia_solo_deja_un_borrador_y_la_memoria_no_cambia_hasta_aceptarlo(monkeypatch):
    t, u, fid = _equipo(n=2)
    cm.guardar(t, u, fid, "- Prefiere WhatsApp")
    ficha = db.obtener_cliente_fiscal_por_id(fid)
    hilo = portal_conversaciones.iniciar(ficha, "Cambio de domicilio", "Nos mudamos a Girona en marzo, mandadme todo por WhatsApp", "cliente", "m2@ejemplo.com")
    vistos = []
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda uid, sistema, contenido: vistos.append(contenido) or "- Prefiere WhatsApp\n- Se mudó a Girona en marzo")
    borrador = cm.proponer_con_ia(t, u, fid)
    assert "Girona" in vistos[0] and "Prefiere WhatsApp" in vistos[0] and "Cambio de domicilio" in vistos[0]       # lleva lo ya sabido y lo que el cliente escribió
    m = cm.obtener(t, fid)
    assert m["texto"] == "- Prefiere WhatsApp" and m["borrador"] == borrador                                    # la memoria sigue igual
    cm.aceptar_borrador(t, u, fid)
    m = cm.obtener(t, fid)
    assert "Girona" in m["texto"] and m["borrador"] == ""
    with pytest.raises(cm.ErrorMemoria):
        cm.aceptar_borrador(t, u, fid)                                                                           # ya no hay nada que aceptar


def test_descartar_y_editar_a_mano_limpian_el_borrador(monkeypatch):
    t, u, fid = _equipo(n=3)
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda uid, s, c: "- Paga tarde")
    cm.proponer_con_ia(t, u, fid)
    cm.descartar_borrador(t, u, fid)
    assert cm.obtener(t, fid)["borrador"] == "" and cm.obtener(t, fid)["texto"] == ""
    cm.proponer_con_ia(t, u, fid)
    cm.guardar(t, u, fid, "Lo escribo yo")
    assert cm.obtener(t, fid)["borrador"] == "" and cm.obtener(t, fid)["texto"] == "Lo escribo yo"           # editar a mano manda sobre la propuesta
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda uid, s, c: "   ")
    with pytest.raises(cm.ErrorMemoria):
        cm.proponer_con_ia(t, u, fid)


def test_la_ficha_enseña_la_memoria_la_guarda_y_la_lleva_a_la_pregunta_del_asistente(cliente, monkeypatch):
    import re
    from urllib.parse import unquote
    t, u, fid = _equipo(cliente, 4)
    cid = db.obtener_cliente_fiscal(t, fid)["cliente_id"]
    db.crear_vencimiento_fiscal(t, fid, "303", "3T", "2020-01-01")                                           # algo que mostrar en el copiloto
    html = cliente.get(f"/clientes/{cid}").get_data(as_text=True)
    assert "Memoria del cliente" in html and "Propuesta de la IA" not in html
    r = cliente.post(f"/clientes/{cid}/memoria/guardar", data={"texto": "Prefiere WhatsApp"})
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/clientes/{cid}#memoria")
    html = cliente.get(f"/clientes/{cid}").get_data(as_text=True)
    assert "Prefiere WhatsApp" in html
    pregunta = unquote(re.search(r'href="/ia/\?q=([^"]+)"', html).group(1))
    assert "Esto es lo que ya sabemos de él: Prefiere WhatsApp" in pregunta
    monkeypatch.setattr(ia_asistente, "disponible", lambda uid, tarea="asistente": True)
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda uid, s, c: "- Propuesta nueva")
    cliente.post(f"/clientes/{cid}/memoria/proponer")
    html = cliente.get(f"/clientes/{cid}").get_data(as_text=True)
    assert "Propuesta de la IA (sin aplicar):" in html and "- Propuesta nueva" in html and "Aceptar propuesta" in html
    cliente.post(f"/clientes/{cid}/memoria/aceptar")
    assert cm.obtener(t, fid)["texto"] == "- Propuesta nueva"
    assert cliente.post(f"/clientes/{cid}/memoria/inventada").status_code == 404
