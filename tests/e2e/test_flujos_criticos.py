"""Flujos críticos recorridos en un navegador real: el cliente en su portal (comentar con un archivo y descargarlo), el equipo contestándole, la revisión de una tarea de principio a fin y el constructor
de reglas de automatización (JavaScript). Cada prueba exige además que la página no dé errores de JavaScript."""
import re

import pytest

from app import db, tareas_trabajo as tt

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def _sin_errores(errores):
    assert errores == [], "\n".join(errores)


def test_el_cliente_comenta_con_un_archivo_y_el_equipo_le_contesta(servidor, abrir, entrar_como_equipo, tmp_path):
    equipo, errores_equipo = abrir()
    t = db.crear_tenant("Despacho e2e portal")
    uid = entrar_como_equipo(equipo, "e2e-equipo@ejemplo.com", despacho=t)
    c = db.crear_cliente_fiscal(t, "Cliente E2E", email="cliente-e2e@ejemplo.com")
    tid = db.crear_tarea_outlook(uid, asunto="Reunir las facturas", cliente_fiscal_id=c)
    tt.fijar_visible_cliente(uid, tid, True, True)

    # El cliente entra con su enlace de un solo uso y escribe, adjuntando un PDF.
    cliente, errores_cliente = abrir()
    cliente.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(c, '127.0.0.1')}")
    assert cliente.get_by_text("Reunir las facturas").first.is_visible()
    cliente.get_by_label(re.compile("Escribe un comentario")).fill("Os mando la factura de septiembre")
    archivo = tmp_path / "factura.pdf"
    archivo.write_bytes(PDF)
    cliente.get_by_label(re.compile("Adjuntar archivos")).set_input_files(str(archivo))
    cliente.get_by_role("button", name="Enviar").click()
    cliente.wait_for_load_state()
    assert cliente.get_by_text("Os mando la factura de septiembre").first.is_visible()
    enlace = cliente.get_by_role("link", name=re.compile("factura.pdf"))
    with cliente.expect_download() as descarga:
        enlace.click()
    assert descarga.value.suggested_filename == "factura.pdf"

    # El equipo lo ve en la ficha de la tarea (con el archivo) y contesta.
    equipo.goto(f"{servidor.url}/tareas/{tid}")
    assert equipo.get_by_text("Os mando la factura de septiembre").first.is_visible()
    assert equipo.get_by_role("link", name=re.compile("factura.pdf")).first.is_visible()
    equipo.get_by_label("Respuesta para el cliente").fill("Recibida, gracias")
    equipo.get_by_role("button", name="Contestar al cliente").click()
    equipo.wait_for_load_state()
    cliente.reload()
    assert cliente.get_by_text("Recibida, gracias").first.is_visible()
    _sin_errores(errores_cliente + errores_equipo)


def test_la_revision_de_una_tarea_de_principio_a_fin(servidor, abrir, entrar_como_equipo):
    t = db.crear_tenant("Despacho e2e revisión")
    quien, errores_1 = abrir()
    revisor, errores_2 = abrir()
    uid = entrar_como_equipo(quien, "e2e-quien@ejemplo.com", despacho=t)
    rev = entrar_como_equipo(revisor, "e2e-revisor@ejemplo.com", despacho=t)
    tid = db.crear_tarea_outlook(uid, asunto="Declaración para revisar")

    quien.goto(f"{servidor.url}/tareas/{tid}")
    quien.locator("#revision").get_by_label(re.compile("e2e-revisor|Revisor", re.I)).first.check()
    quien.get_by_role("button", name="Pedir revisión").click()
    quien.wait_for_load_state()
    assert db.obtener_tarea_outlook(uid, tid)["estado"] == "en_revision"
    assert quien.get_by_text("En revisión").first.is_visible()

    revisor.goto(f"{servidor.url}/tareas/{tid}")
    revisor.get_by_role("button", name="Aprobar").click()
    revisor.wait_for_load_state()
    assert tt.revision_pendiente(tid) is None and db.obtener_tarea_outlook(uid, tid)["estado"] == "no_iniciada"      # aprobada: vuelve a su estado
    quien.reload()
    assert quien.get_by_text("Aprobada").first.is_visible()
    assert rev
    _sin_errores(errores_1 + errores_2)


def test_el_constructor_de_reglas_muestra_cada_condicion_y_guarda_la_regla(servidor, abrir, entrar_como_equipo):
    t = db.crear_tenant("Despacho e2e reglas")
    pagina, errores = abrir()
    entrar_como_equipo(pagina, "e2e-direccion@ejemplo.com", despacho=t, direccion=True)
    pagina.goto(f"{servidor.url}/tareas/automatizaciones/regla")
    for disparador, campo in (("tarea.estado", "c_estado_e"), ("expediente.estado", "c_estado_x"), ("recurrencia.generada", "c_periodicidades_r"), ("certificado.caduca", "c_dias_cert")):
        pagina.select_option("#disparador", disparador)
        assert pagina.locator(f"[name={campo}]").first.is_visible(), disparador                        # el JavaScript enseña solo lo que corresponde
    pagina.select_option("#disparador", "tarea.estado")
    assert not pagina.locator("[name=c_dias_cert]").first.is_visible()
    pagina.get_by_label("Nombre").fill("Aviso al esperar")
    pagina.select_option("[name=c_estado_e]", "esperando")
    pagina.select_option("[name=a0_tipo]", "notificar")
    pagina.locator("[name=a0_titulo]").fill("En espera: {asunto}")
    pagina.get_by_role("button", name=re.compile("Guardar|Crear")).first.click()
    pagina.wait_for_load_state()
    from app import automatizaciones
    reglas = automatizaciones.listar_reglas(t)
    assert [r["disparador"] for r in reglas] == ["tarea.estado"] and reglas[0]["condiciones"] == {"estado": "esperando"}
    _sin_errores(errores)
