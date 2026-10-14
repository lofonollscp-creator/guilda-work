"""Ficha única del cliente (app/ficha_cliente.py, `/clientes/<id>`): una pantalla con pestañas en lugar de dos fichas paralelas."""
import pytest

from app import db, espocrm, facturascripts, nucleo
from tests.conftest import iniciar_sesion_de_prueba


def _con_despacho(cliente, email):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant(f"Despacho {email}")
    db.asignar_tenant(uid, t)
    return uid, t


def _fiscal(t, nombre="Cliente Fiscal", **kw):
    fid = db.crear_cliente_fiscal(t, nombre, **kw)
    return fid, db.obtener_cliente_fiscal(t, fid)["cliente_id"]


def _enlaces_de_pestanas(html):
    return {p for p in ("resumen", "fiscal", "tareas", "documentos", "mensajes") if f"pestana={p}" in html}


def test_un_cliente_sin_gestion_fiscal_solo_tiene_resumen_y_documentos(cliente):
    uid, t = _con_despacho(cliente, "fc-nucleo@ejemplo.com")
    cid = nucleo.crear_cliente(t, "Solo núcleo")
    html = cliente.get(f"/clientes/{cid}").get_data(as_text=True)
    assert _enlaces_de_pestanas(html) == {"resumen", "documentos"}
    # Pedir una pestaña que no existe para este cliente cae en el resumen, no en un error.
    r = cliente.get(f"/clientes/{cid}?pestana=fiscal")
    assert r.status_code == 200 and "Contactos" in r.get_data(as_text=True)


def test_un_cliente_con_gestion_fiscal_tiene_las_cinco_pestanas_y_abre_en_el_resumen(cliente):
    uid, t = _con_despacho(cliente, "fc-cinco@ejemplo.com")
    fid, cid = _fiscal(t)
    html = cliente.get(f"/clientes/{cid}").get_data(as_text=True)
    assert _enlaces_de_pestanas(html) == {"resumen", "fiscal", "tareas", "documentos", "mensajes"}
    assert "Contactos" in html, "sin ?pestana= se abre el resumen"
    assert cliente.get(f"/clientes/{cid}?pestana=inventada").status_code == 200


def test_la_ruta_antigua_de_fiscal_lleva_a_la_pestana_fiscal_de_la_ficha_unica(cliente):
    uid, t = _con_despacho(cliente, "fc-redir@ejemplo.com")
    fid, cid = _fiscal(t)
    r = cliente.get(f"/fiscal/clientes/{fid}")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/clientes/{cid}?pestana=fiscal")
    r = cliente.get(f"/fiscal/clientes/{fid}?pestana=tareas")
    assert r.headers["Location"].endswith(f"/clientes/{cid}?pestana=tareas")


def test_las_fichas_de_otro_despacho_no_existen_por_ninguna_de_las_dos_rutas(cliente):
    uid, t = _con_despacho(cliente, "fc-ajeno@ejemplo.com")
    otro = db.crear_tenant("Despacho ajeno ficha")
    fid, cid = _fiscal(otro, "Ajeno")
    assert cliente.get(f"/fiscal/clientes/{fid}").status_code == 404
    assert cliente.get(f"/clientes/{cid}").status_code == 404 and cliente.get(f"/clientes/{cid}?pestana=fiscal").status_code == 404


def test_la_pestana_fiscal_lista_los_vencimientos_y_la_cabecera_lleva_el_semaforo(cliente):
    uid, t = _con_despacho(cliente, "fc-fiscal@ejemplo.com")
    fid, cid = _fiscal(t)
    db.crear_vencimiento_fiscal(t, fid, "303", "2020-T1", "2020-04-20")          # vencido y pendiente: atrasado
    html = cliente.get(f"/clientes/{cid}?pestana=fiscal").get_data(as_text=True)
    assert "303" in html and "2020-T1" in html and "Generar vencimientos" in html
    assert "Atrasado" in html
    # El semáforo está en la cabecera: también se ve desde las otras pestañas.
    assert "Atrasado" in cliente.get(f"/clientes/{cid}").get_data(as_text=True)


def test_las_integraciones_externas_solo_se_consultan_al_abrir_la_pestana_fiscal(cliente, monkeypatch):
    uid, t = _con_despacho(cliente, "fc-integ@ejemplo.com")
    fid, cid = _fiscal(t)
    db.editar_cliente_fiscal(t, fid, facturascripts_cliente_codigo="C1", espocrm_cuenta_id="E1")
    llamadas = []

    def facturas(*a, **k):
        llamadas.append("facturas")
        return []

    def contactos(*a, **k):
        llamadas.append("espocrm")
        return []

    monkeypatch.setattr(facturascripts, "listar_facturas", facturas)
    monkeypatch.setattr(espocrm, "listar_contactos_de_cuenta", contactos)
    for pestana in ("resumen", "tareas", "documentos", "mensajes"):
        assert cliente.get(f"/clientes/{cid}?pestana={pestana}").status_code == 200
    assert llamadas == []
    assert cliente.get(f"/clientes/{cid}?pestana=fiscal").status_code == 200
    assert sorted(llamadas) == ["espocrm", "facturas"]


def test_un_fallo_de_facturascripts_no_rompe_la_ficha(cliente, monkeypatch):
    uid, t = _con_despacho(cliente, "fc-caido@ejemplo.com")
    fid, cid = _fiscal(t)
    db.editar_cliente_fiscal(t, fid, facturascripts_cliente_codigo="C1")

    def cae(*a, **k):
        raise facturascripts.ErrorFacturaScripts("caído")

    monkeypatch.setattr(facturascripts, "listar_facturas", cae)
    r = cliente.get(f"/clientes/{cid}?pestana=fiscal")
    assert r.status_code == 200 and "Todavía no hay facturas para este cliente." in r.get_data(as_text=True)


def test_el_registro_de_accesos_anota_la_ficha_solo_al_abrir_la_pestana_fiscal(cliente):
    uid, t = _con_despacho(cliente, "fc-acceso@ejemplo.com")
    fid, cid = _fiscal(t)
    acciones = lambda: [a["accion"] for a in db.listar_accesos_cliente(t, fid)]
    cliente.get(f"/clientes/{cid}"); cliente.get(f"/clientes/{cid}?pestana=tareas")
    assert acciones() == []
    cliente.get(f"/clientes/{cid}?pestana=fiscal")
    assert acciones() == ["ficha_vista"]


def test_la_pestana_tareas_lista_las_del_cliente_y_enlaza_su_vencimiento(cliente):
    uid, t = _con_despacho(cliente, "fc-tareas@ejemplo.com")
    fid, cid = _fiscal(t)
    otro_fid, _ = _fiscal(t, "Otro cliente")
    v = db.crear_vencimiento_fiscal(t, fid, "303", "2026-T3", "2026-10-20")
    db.crear_tarea_outlook(uid, "Pedir facturas", cliente_fiscal_id=fid, vencimiento_id=v)
    hecha = db.crear_tarea_outlook(uid, "Ya hecha", cliente_fiscal_id=fid)
    db.completar_tarea_outlook(uid, hecha)
    db.crear_tarea_outlook(uid, "De otro cliente", cliente_fiscal_id=otro_fid)
    html = cliente.get(f"/clientes/{cid}?pestana=tareas").get_data(as_text=True)
    assert "Pedir facturas" in html and "Ya hecha" in html and "De otro cliente" not in html
    assert f"/fiscal/vencimientos/{v}/editar" in html and "(1 abiertas)" in html
    assert html.index("Pedir facturas") < html.index("Ya hecha"), "las abiertas van primero"


def test_la_pestana_documentos_reune_los_del_cliente_el_expediente_fiscal_y_lo_que_sube_el_cliente(cliente):
    uid, t = _con_despacho(cliente, "fc-docs@ejemplo.com")
    fid, cid = _fiscal(t)
    from app import almacen_documentos as alm
    assert alm.guardar(uid, "contrato.txt", "text/plain", b"contrato", cliente_id=cid)[0] == "ok"
    assert alm.guardar_de_cliente_fiscal(uid, fid, "modelo303.pdf", "application/pdf", b"%PDF-1.4 x")[0] == "ok"
    v = db.crear_vencimiento_fiscal(t, fid, "303", "2026-T3", "2026-10-20")
    db.subir_documento_vencimiento(v, "factura-cliente.pdf", "application/pdf", b"%PDF-1.4 y")
    html = cliente.get(f"/clientes/{cid}?pestana=documentos").get_data(as_text=True)
    assert "contrato.txt" in html and "modelo303.pdf" in html and "factura-cliente.pdf" in html and 'id="expediente"' in html


def test_un_cliente_sin_gestion_fiscal_ve_sus_documentos_sin_expediente_fiscal(cliente):
    uid, t = _con_despacho(cliente, "fc-docs-nucleo@ejemplo.com")
    cid = nucleo.crear_cliente(t, "Solo núcleo")
    from app import almacen_documentos as alm
    alm.guardar(uid, "nota.txt", "text/plain", b"hola", cliente_id=cid)
    html = cliente.get(f"/clientes/{cid}?pestana=documentos").get_data(as_text=True)
    assert "nota.txt" in html and 'id="expediente"' not in html


def test_subir_al_expediente_deja_en_la_pestana_documentos(cliente):
    import io
    uid, t = _con_despacho(cliente, "fc-subida@ejemplo.com")
    fid, cid = _fiscal(t)
    r = cliente.post(f"/fiscal/clientes/{fid}/documentos", data={"archivo": [(io.BytesIO(b"contenido"), "extracto.pdf")]}, content_type="multipart/form-data")
    assert r.status_code == 302 and f"/clientes/{cid}" in r.headers["Location"] and "pestana=documentos" in r.headers["Location"] and r.headers["Location"].endswith("#expediente")
    assert "extracto.pdf" in cliente.get(r.headers["Location"]).get_data(as_text=True)


def test_la_pestana_mensajes_junta_los_del_portal_de_todos_los_vencimientos_y_los_correos(cliente):
    uid, t = _con_despacho(cliente, "fc-msg@ejemplo.com")
    fid, cid = _fiscal(t)
    v1 = db.crear_vencimiento_fiscal(t, fid, "303", "2026-T3", "2026-10-20")
    v2 = db.crear_vencimiento_fiscal(t, fid, "130", "2026-T3", "2026-10-20")
    db.crear_mensaje_vencimiento(v1, "cliente", "Mensaje del 303")
    db.crear_mensaje_vencimiento(v2, "empleado", "Respuesta del 130", usuario_id=uid)
    html = cliente.get(f"/clientes/{cid}?pestana=mensajes").get_data(as_text=True)
    assert "Mensaje del 303" in html and "Respuesta del 130" in html
    vacio = _fiscal(t, "Sin mensajes")[1]
    assert "Todavía no hay mensajes" in cliente.get(f"/clientes/{vacio}?pestana=mensajes").get_data(as_text=True)
