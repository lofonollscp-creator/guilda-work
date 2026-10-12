"""Recorrido con clics reales (Playwright + Chromium) sobre la instancia de demostración de scripts/servidor_demo.py: selectores con buscador, calendario propio, formularios, confirmaciones,
cifrado, tablero, perfil fiscal y menú móvil. Cada paso se anota como OK/FALLO; al fallar guarda una captura. Lo lanza scripts/comprobar_interaccion.sh (instancia nueva en cada ejecución)."""
import sys, traceback
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = "http://127.0.0.1:8099"
SAL = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp")
BASE = sys.argv[2] if len(sys.argv) > 2 else BASE
resultados, errores_js = [], []


def paso(nombre):
    def deco(f):
        def envuelta(pg, *a):
            try:
                f(pg, *a); resultados.append(("OK", nombre))
            except Exception as e:  # noqa: BLE001
                resultados.append(("FALLO", f"{nombre}: {str(e).splitlines()[0][:230]}"))
                try: pg.screenshot(path=str(SAL / f"fallo-{len(resultados)}.png"))
                except Exception: pass
        return envuelta
    return deco


@paso("selector con buscador: abrir, filtrar escribiendo y elegir")
def selector(pg):
    pg.goto(BASE + "/plazos/")
    pg.click("summary:has-text('Nuevo plazo')")
    pg.click("select[name=expediente_id]")
    panel = pg.locator(".selbus-panel:visible")
    expect(panel).to_be_visible()
    pg.fill(".selbus-buscar", "piso")
    opciones = pg.locator(".selbus-panel .selbus-opcion:visible")
    assert opciones.count() == 1, f"con «piso» deberían quedar 1 opción y quedan {opciones.count()}"
    opciones.first.click()
    assert pg.eval_on_selector("select[name=expediente_id]", "e=>e.value") == "4"
    expect(pg.locator(".selbus-panel:visible")).to_have_count(0)


@paso("selector con buscador: teclado (flechas + Intro) y Escape")
def selector_teclado(pg):
    pg.goto(BASE + "/plazos/")
    pg.click("summary:has-text('Nuevo plazo')")
    pg.click("select[name=cliente_id]")
    pg.keyboard.type("hijos")
    pg.keyboard.press("ArrowDown"); pg.keyboard.press("Enter")
    assert pg.eval_on_selector("select[name=cliente_id]", "e=>e.value") == "2", "no eligió «Hijos de Vidal» con el teclado"
    pg.click("select[name=cliente_id]")
    expect(pg.locator(".selbus-panel:visible")).to_be_visible()
    pg.keyboard.press("Escape")
    expect(pg.locator(".selbus-panel:visible")).to_have_count(0)


@paso("calendario propio: abrir, cambiar de mes y elegir un día")
def calendario(pg):
    pg.goto(BASE + "/plazos/")
    pg.click("summary:has-text('Nuevo plazo')")
    pg.click("input[name=fecha_limite]")
    expect(pg.locator(".ds-cal")).to_be_visible()
    pg.keyboard.press("PageDown")
    dias = pg.locator(".ds-cal .ds-cal-dia:not([disabled])")
    dias.nth(14).click()
    valor = pg.eval_on_selector("input[name=fecha_limite]", "e=>e.value")
    assert valor.startswith("2026-11-"), f"tras avanzar un mes debería ser noviembre y es {valor}"
    expect(pg.locator(".ds-cal")).to_have_count(0)


@paso("crear un plazo desde el formulario y marcarlo como cumplido")
def plazo(pg):
    pg.goto(BASE + "/plazos/")
    pg.click("summary:has-text('Nuevo plazo')")
    pg.fill("input[name=titulo]", "Plazo creado por la prueba")
    pg.click("details button[type=submit]")
    pg.wait_for_load_state()
    fila = pg.locator("tr", has_text="Plazo creado por la prueba")
    expect(fila).to_have_count(1)
    fila.get_by_role("button", name="Cumplido").click()
    pg.wait_for_load_state()
    expect(pg.locator("tr", has_text="Plazo creado por la prueba")).to_have_count(0)      # ya no está entre los «abiertos»
    pg.goto(BASE + "/plazos/?estado=cumplido")
    expect(pg.locator("tr", has_text="Plazo creado por la prueba")).to_have_count(1)      # y sigue en «Cumplidos»


@paso("registrar horas y ver el resumen")
def horas(pg):
    pg.goto(BASE + "/tiempo/")
    pg.fill("input[name=descripcion]", "Llamada de la prueba")
    pg.fill("input[name=horas]", "2")
    pg.fill("input[name=minutos]", "15")
    pg.click("form button:has-text('Registrar')")
    pg.wait_for_load_state()
    expect(pg.get_by_text("Llamada de la prueba").first).to_be_visible()
    assert "2 h 15" in pg.inner_text("body")


@paso("tablero de captación: cambiar de fase mueve la tarjeta")
def tablero(pg):
    pg.goto(BASE + "/inmobiliaria/tablero")
    def en_valoracion():
        return pg.eval_on_selector_all(".ds-tablero > *", "cs=>cs.filter(c=>c.textContent.trim().startsWith('Valoración')).map(c=>c.querySelectorAll('select[name=estado]').length)")[0]
    antes = en_valoracion()
    tarjeta = pg.locator("select[name=estado][data-autoenviar]").first
    with pg.expect_navigation():
        tarjeta.select_option(label="Valoración")
    pg.wait_for_load_state()
    assert en_valoracion() == antes + 1, f"la tarjeta no ha pasado a «Valoración» ({antes} antes, {en_valoracion()} después)"


@paso("confirmación de acción destructiva: cancelar no hace nada y aceptar sí")
def confirmar(pg):
    pg.goto(BASE + "/seguridad/privacidad")
    pg.click("form[data-confirmar-envio] button[type=submit]")
    dlg = pg.locator("dialog.ds-dialogo[open]")
    expect(dlg).to_be_visible()
    dlg.get_by_role("button").first.click()                    # el primero es «Cancelar»
    expect(pg.locator("dialog.ds-dialogo[open]")).to_have_count(0)
    assert "Papelera vaciada" not in pg.inner_text("body")
    pg.click("form[data-confirmar-envio] button[type=submit]")
    pg.locator("dialog.ds-dialogo[open]").get_by_role("button").last.click()
    pg.wait_for_load_state()
    assert "Papelera vaciada" in pg.inner_text("body"), "tras aceptar debería vaciarse y avisar"


@paso("cifrado: activar → clave de recuperación → bloquear → 423 → frase mala → desbloquear → descarga")
def cifrado(pg):
    pg.goto(BASE + "/seguridad/cifrado")
    pg.fill("input[name=frase]", "una frase de paso larga y segura")
    pg.fill("input[name=frase2]", "una frase de paso larga y segura")
    pg.click("input[name=entendido]")
    pg.click("button:has-text('Activar y cifrar')")
    pg.wait_for_load_state()
    clave = pg.inner_text(".ds-clave-recuperacion")
    assert len(clave.replace("-", "")) == 40, f"clave de recuperación rara: {clave!r}"
    pg.goto(BASE + "/seguridad/cifrado")
    assert "Guarda tu clave" not in pg.inner_text("body"), "la clave no debe volver a mostrarse"
    r = pg.request.get(BASE + "/clientes/1/documentos/1")
    assert r.status == 200 and b"Contrato" in r.body(), "desbloqueado debe descargar el documento"
    pg.click("button:has-text('Bloquear ahora')")
    pg.wait_for_load_state()
    r = pg.request.get(BASE + "/clientes/1/documentos/1")
    assert r.status == 423 and b"Contrato de ejemplo" not in r.body(), f"bloqueado debe dar 423 y dio {r.status}"
    pg.goto(BASE + "/clientes/1/documentos/1")
    assert "Documentos protegidos" in pg.inner_text("body")
    pg.goto(BASE + "/seguridad/cifrado")
    pg.fill("input[name=frase]", "frase equivocada del todo"); pg.click("button:has-text('Desbloquear')"); pg.wait_for_load_state()
    assert "Frase incorrecta" in pg.inner_text("body")
    pg.fill("input[name=frase]", "una frase de paso larga y segura"); pg.click("button:has-text('Desbloquear')"); pg.wait_for_load_state()
    assert pg.request.get(BASE + "/clientes/1/documentos/1").status == 200
    assert "Quién ha abierto" in pg.inner_text("body")


@paso("correo cifrado: activar (nivel Estricto), bloquear → protegido, desbloquear → legible y buscable, bajar de nivel")
def correo_cifrado(pg):
    frase = "una frase de paso larga y segura"
    pg.goto(BASE + "/seguridad/cifrado")          # (el paso anterior dejó activado y desbloqueado el cifrado de documentos: el correo usa la misma clave)
    assert "Desactivado" in pg.inner_text("#t-cor"), "el correo cifrado debe empezar desactivado (es opcional)"
    pg.select_option("form[action$='/correo/activar'] select[name=nivel]", "estricto")
    pg.click("button:has-text('Activar el correo cifrado')"); pg.wait_for_load_state()
    assert "2 mensajes protegidos" in pg.inner_text("body"), "debería haber sellado los 2 mensajes de demostración"
    pg.goto(BASE + "/correo/")
    cuerpo = pg.inner_text("body")
    assert "Reclamación del IVA trimestral" in cuerpo and "Marta Puig" in cuerpo, "desbloqueado, la bandeja se lee con normalidad"
    pg.fill("input[name=q]", "plenilunio")
    with pg.expect_navigation():
        pg.keyboard.press("Enter")
    assert "Reclamación del IVA" in pg.inner_text("body") and "Cita para la firma" not in pg.inner_text("body"), "la búsqueda por cuerpo debe funcionar con el correo cifrado"
    pg.goto(BASE + "/seguridad/cifrado"); pg.click("button:has-text('Bloquear ahora')"); pg.wait_for_load_state()
    pg.goto(BASE + "/correo/")
    cuerpo = pg.inner_text("body")
    assert "Protegido" in cuerpo and "Reclamación del IVA" not in cuerpo and "Marta Puig" not in cuerpo, "bloqueado y en Estricto la bandeja no debe enseñar nada del contenido"
    pg.screenshot(path=str(SAL / "correo-bloqueado.png"))
    pg.goto(BASE + "/seguridad/cifrado"); pg.fill("form[action$='/desbloquear'] input[name=frase]", frase); pg.click("button:has-text('Desbloquear')"); pg.wait_for_load_state()
    pg.goto(BASE + "/correo/")
    assert "Reclamación del IVA trimestral" in pg.inner_text("body")
    pg.goto(BASE + "/seguridad/cifrado")
    pg.select_option("form[action$='/cifrado/nivel'] select[name=nivel]", "laxo")
    pg.click("button:has-text('Cambiar nivel')"); pg.wait_for_load_state()
    assert "mensajes actualizados" in pg.inner_text("body")


@paso("abogados: añadir una parte y calcular (con festivos) y confirmar una notificación")
def abogados(pg):
    pg.goto(BASE + "/expedientes/3")
    pg.fill("input[name=nombre]", "Seguros Omega S.A.")
    pg.locator("form:has(input[name=nombre]) button[type=submit]").first.click()
    pg.wait_for_load_state()
    expect(pg.get_by_text("Seguros Omega S.A.").first).to_be_visible()
    pg.goto(BASE + "/expedientes/3")
    pg.click("text=Registrar notificación")
    pg.wait_for_selector("#n-res")
    pg.select_option("#n-res", "sentencia")
    pg.fill("#n-fecha", "2026-10-13")
    pg.fill("#n-plazo", "10")
    pg.click("button:has-text('Calcular')")
    pg.wait_for_load_state()
    cuerpo = pg.inner_text("body")
    assert "2026-10-27" in cuerpo, "10 días hábiles desde el 13/10/2026 (con el 12 festivo y fines de semana) deberían acabar el 27/10"
    pg.click("button:has-text('Confirmar y crear el plazo')")
    pg.wait_for_load_state()
    assert "Sentencia notificada el 2026-10-13" in pg.inner_text("body"), "el plazo no aparece en la ficha del asunto"


@paso("enlace público de solo lectura del cliente: se crea y se abre sin sesión, sin datos internos")
def enlace_publico(pg, ctx_anonimo):
    pg.goto(BASE + "/expedientes/3")
    pg.click("form[action$='/enlaces'] button[type=submit]")
    pg.wait_for_load_state()
    url = pg.inner_text("#enlace-cliente").strip()
    assert "/asunto/" in url, f"no se mostró el enlace: {url!r}"
    anon = ctx_anonimo.new_page()
    anon.goto(BASE + "/asunto/" + url.rsplit("/", 1)[1])
    cuerpo = anon.inner_text("body")
    assert "Procedimiento ordinario 45/2026" in cuerpo and "Horas" not in cuerpo and "Constructora Delta" not in cuerpo, "la página pública enseña lo que no debe o no carga"
    assert anon.locator("meta[name=robots][content*=noindex]").count() == 1
    anon.close()


@paso("portal del propietario (sin sesión) y su informe PDF")
def propietario(pg, ctx_anonimo):
    pg.goto(BASE + "/expedientes/4")
    pg.click("form[action$='/enlaces'] button[type=submit]")
    pg.wait_for_load_state()
    token = pg.inner_text("#enlace-propietario, #enlace-cliente").strip().rsplit("/", 1)[1]
    anon = ctx_anonimo.new_page()
    anon.goto(BASE + "/propietario/" + token)
    cuerpo = anon.inner_text("body")
    assert "Calle Mayor 12" in cuerpo and "comisi" not in cuerpo.lower(), "el portal del propietario enseña comisiones o no carga"
    r = anon.request.get(BASE + f"/propietario/{token}/informe.pdf")
    assert r.status == 200 and r.body().startswith(b"%PDF"), f"informe PDF: {r.status}"
    anon.close()


@paso("informe mensual del cliente fiscal en PDF y exportar los datos de un cliente (RGPD)")
def informes(pg):
    r = pg.request.get(BASE + "/fiscal/clientes/1/informe-mensual.pdf")
    assert r.status == 200 and r.body().startswith(b"%PDF"), f"informe mensual: {r.status}"
    r = pg.request.get(BASE + "/seguridad/clientes/1/exportar.json")
    assert r.status == 200 and "Carmen Soler" in r.text() and "contenido" not in r.json()["documentos"][0]


@paso("perfil fiscal: marcar atributos y aplicar los modelos sugeridos")
def fiscal(pg):
    pg.goto(BASE + "/fiscal/clientes/1/editar")
    pg.select_option("select[name=perfil_tipo]", "sociedad")
    pg.check("input[name=perfil_atributos][value=iva]")
    pg.check("input[name=aplicar_perfil]")
    pg.click("form button[type=submit]:has-text('Guardar')")
    pg.wait_for_load_state()
    pg.goto(BASE + "/fiscal/clientes/1/editar")
    marcados = pg.eval_on_selector_all("input[name=modelos_fiscales]:checked", "e=>e.map(x=>x.value)")
    assert marcados == ["303", "390", "200"], f"modelos tras aplicar el perfil: {marcados}"
    pg.goto(BASE + "/fiscal/clientes?estado=atrasado")
    assert "Taller" in pg.inner_text("body") and "Bar La Plaza" not in pg.inner_text("body")


@paso("móvil: el menú lateral se abre y se cierra")
def movil(pg_unused, ctx_movil):
    pg = ctx_movil.new_page()
    pg.goto(BASE + "/clientes/")
    assert pg.eval_on_selector("#rail-principal", "e=>e.getBoundingClientRect().right") <= 0, "el menú debería empezar cerrado"
    pg.click("#menu-movil-abrir")
    pg.wait_for_timeout(500)
    assert pg.eval_on_selector("#rail-principal", "e=>e.getBoundingClientRect().left") >= 0, "el menú no se ha abierto"
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(500)
    if pg.eval_on_selector("#rail-principal", "e=>e.getBoundingClientRect().right") > 0:
        pg.click("#menu-movil-abrir"); pg.wait_for_timeout(500)
    anchura = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert anchura <= 1, f"hay desplazamiento horizontal de página en móvil ({anchura}px)"
    pg.close()


with sync_playwright() as p:
    nav = p.chromium.launch(args=["--no-sandbox"])
    ctx = nav.new_context(viewport={"width": 1280, "height": 900}, locale="es-ES")
    ctx.add_init_script("window.addEventListener('securitypolicyviolation', e => console.error('CSP: ' + e.violatedDirective + ' ' + e.blockedURI))")
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errores_js.append(str(e)))
    pg.on("console", lambda m: errores_js.append(m.text[:200]) if m.type == "error" and "423" not in m.text else None)
    anonimo = nav.new_context(viewport={"width": 1280, "height": 900}, locale="es-ES")
    for f in (selector, selector_teclado, calendario, plazo, horas, tablero, confirmar, abogados, fiscal, informes):
        f(pg)
    enlace_publico(pg, anonimo)
    propietario(pg, anonimo)
    cifrado(pg)
    correo_cifrado(pg)
    movil(pg, nav.new_context(viewport={"width": 390, "height": 800}, locale="es-ES"))
    nav.close()
for estado, nombre in resultados:
    print(f"{estado:5s} {nombre}")
print("errores JS/CSP:", errores_js or "ninguno")
sys.exit(1 if any(e == "FALLO" for e, _ in resultados) or errores_js else 0)
