

def test_la_voz_del_despacho_llega_al_borrador_de_respuesta(monkeypatch):
    from app import correo_ia, db, ia_despacho
    t = db.crear_tenant("Voz del despacho")
    u = db.crear_usuario_vinculado_a_kratos("voz@ejemplo.com", "k-voz")
    db.asignar_tenant(u, t)
    vistos = []
    monkeypatch.setattr(correo_ia.ia_asistente, "completar_texto", lambda uid, sistema, contenido: vistos.append(sistema) or "Hola")
    correo_ia.ejecutar(u, "responder", {"asunto": "x", "cuerpo_texto": "y", "cuerpo_html": "", "remitente": "z@z.com", "destinatarios": "yo@x.com"})
    assert "Voz del despacho" not in vistos[-1]                                      # sin voz escrita, el prompt es el de siempre
    ia_despacho.guardar_voz(t, "Tutea al cliente.\nFrases cortas.", u)
    correo_ia.ejecutar(u, "responder", {"asunto": "x", "cuerpo_texto": "y", "cuerpo_html": "", "remitente": "z@z.com", "destinatarios": "yo@x.com"})
    assert "Voz del despacho" in vistos[-1] and "Tutea al cliente.\nFrases cortas." in vistos[-1]
    correo_ia.ejecutar(u, "resumir", {"asunto": "x", "cuerpo_texto": "y", "cuerpo_html": "", "remitente": "z@z.com", "destinatarios": "yo@x.com"})
    assert "Voz del despacho" not in vistos[-1]                                      # solo al redactar respuestas
    assert ia_despacho.config(t)["voz"].startswith("Tutea") and ia_despacho.config(t)["solo_ue"] is False       # guardar la voz no toca las demás normas
