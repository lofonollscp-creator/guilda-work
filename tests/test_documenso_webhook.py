"""Webhook entrante de Documenso (app/rutas_documenso_webhook.py)."""
from app import db, documentos_firma as df, documenso, nucleo


def _enviado(monkeypatch):
    t = db.crear_tenant("Despacho webhook")
    u = db.crear_usuario_vinculado_a_kratos("wh@ejemplo.com", "k-wh"); db.asignar_tenant(u, t)
    db.guardar_datos_tenant(t, "B1", "Calle 1"); db.guardar_documenso_api_key(t, "clave")
    c = nucleo.crear_cliente(t, "Cliente", nif="B2", email="c@x.example", direccion="X")
    monkeypatch.setattr(documenso, "crear_documento", lambda *a, **k: {"id": "env_wh"})
    monkeypatch.setattr(documenso, "enviar_a_firma", lambda *a: {})
    did = df.crear_borrador(t, u, c, "hoja_encargo", {"servicios": "x", "honorarios": "y"})
    df.enviar(t, u, c, did)
    return t, c, did


def test_sin_secreto_configurado_no_acepta_nada(cliente, monkeypatch):
    monkeypatch.delenv("DOCUMENSO_WEBHOOK_SECRET", raising=False)
    assert cliente.post("/webhooks/documenso", json={}, headers={"X-Documenso-Secret": ""}).status_code == 503


def test_exige_el_secreto_y_confirma_el_estado_con_la_api(cliente, monkeypatch):
    monkeypatch.setenv("DOCUMENSO_WEBHOOK_SECRET", "secreto-de-prueba")
    t, c, did = _enviado(monkeypatch)
    consultas = []
    monkeypatch.setattr(documenso, "estado_documento", lambda clave, ident: consultas.append(ident) or "COMPLETED")
    monkeypatch.setattr(documenso, "descargar_firmado", lambda *a: b"%PDF-firmado")
    cuerpo = {"event": "DOCUMENT_COMPLETED", "payload": {"id": "env_wh", "status": "COMPLETED"}}
    assert cliente.post("/webhooks/documenso", json=cuerpo).status_code == 401
    assert cliente.post("/webhooks/documenso", json=cuerpo, headers={"X-Documenso-Secret": "otro"}).status_code == 401
    assert consultas == [] and df.obtener(t, c, did)["estado"] == "enviado"
    r = cliente.post("/webhooks/documenso", json=cuerpo, headers={"X-Documenso-Secret": "secreto-de-prueba"})
    assert r.status_code == 200 and consultas == ["env_wh"] and df.obtener(t, c, did)["estado"] == "firmado"
    assert cliente.post("/webhooks/documenso", data="no es json", headers={"X-Documenso-Secret": "secreto-de-prueba"}).status_code == 200      # un aviso raro no rompe nada
    assert cliente.post("/webhooks/documenso", json={"event": "document.completed", "payload": {"id": "desconocido"}}, headers={"X-Documenso-Secret": "secreto-de-prueba"}).status_code == 200


def test_un_aviso_falso_no_cambia_el_estado_si_la_api_dice_otra_cosa(cliente, monkeypatch):
    monkeypatch.setenv("DOCUMENSO_WEBHOOK_SECRET", "s")
    t, c, did = _enviado(monkeypatch)
    monkeypatch.setattr(documenso, "estado_documento", lambda *a: "PENDING")
    cliente.post("/webhooks/documenso", json={"event": "DOCUMENT_COMPLETED", "payload": {"id": "env_wh"}}, headers={"X-Documenso-Secret": "s"})
    assert df.obtener(t, c, did)["estado"] == "enviado"
