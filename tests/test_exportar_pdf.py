"""Exportación a PDF de los fichajes propios, del histórico, del informe de IA y de la carga del equipo."""
from datetime import datetime, timedelta

from app import db, export
from tests.conftest import iniciar_sesion_de_prueba


def _es_pdf(resp) -> bool:
    return resp.status_code == 200 and resp.mimetype == "application/pdf" and resp.data.startswith(b"%PDF")


def test_mis_fichajes_en_pdf_solo_con_mis_datos(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "pdf-fichaje@ejemplo.com", "contrasena123")
    ayer = (datetime.now() - timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    db.fichar(uid, None, "entrada", marca_tiempo=ayer.isoformat(timespec="seconds"))
    db.fichar(uid, None, "salida", marca_tiempo=(ayer + timedelta(hours=2)).isoformat(timespec="seconds"))
    resp = cliente.get("/fichaje/historial.pdf")
    assert _es_pdf(resp) and "mis_fichajes.pdf" in resp.headers["Content-Disposition"]
    assert b"historial.pdf" in cliente.get("/fichaje/historial").data, "el botón está en la página"


def test_el_pdf_de_fichajes_requiere_sesion(cliente):
    assert cliente.get("/fichaje/historial.pdf").status_code in (302, 401)


def test_historial_en_pdf(cliente, usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda <b>")
    db.crear_nota(usuario_id, "Nota con <i>marcas</i> & símbolos", categoria_id=cid)
    assert export.a_pdf(usuario_id).startswith(b"%PDF")
    assert export.a_pdf(usuario_id, desde="2999-01-01").startswith(b"%PDF"), "sin datos tampoco falla"


def test_ruta_export_pdf(cliente):
    iniciar_sesion_de_prueba(cliente, "pdf-export@ejemplo.com", "contrasena123")
    assert _es_pdf(cliente.get("/export?formato=pdf"))


def test_informe_ia_en_pdf_escapa_el_texto(cliente):
    iniciar_sesion_de_prueba(cliente, "pdf-ia@ejemplo.com", "contrasena123")
    resp = cliente.post("/informe-ia/pdf", data={"texto": "Resumen\n\n<para>mal cerrado</b> & más\n" * 3})
    assert _es_pdf(resp)
    assert cliente.post("/informe-ia/pdf", data={"texto": "  "}).status_code == 400


def test_carga_del_equipo_en_pdf(cliente):
    iniciar_sesion_de_prueba(cliente, "pdf-carga@ejemplo.com", "contrasena123")
    assert _es_pdf(cliente.get("/tareas/carga.pdf"))
