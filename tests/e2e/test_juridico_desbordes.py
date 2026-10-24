"""Asistente jurídico: ninguna pantalla desborda en horizontal (móvil, tableta y escritorio), ni con textos largos sin espacios (URL, ECLI, títulos del BOE)."""
import json

from app import db, ia_asistente, reuniones, verticales
from tests.conftest import iniciar_sesion_de_prueba
from tests.juridico_ayudas import conector_consolidada, conector_diario, habilitar, transporte_boe
from tests.test_juridico_asistente import ok_articulo1

ANCHOS = [360, 390, 768, 1024, 1366]

MEDIR = """() => {
  const de = document.documentElement, ancho = de.clientWidth, fuera = [], dentro = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || getComputedStyle(el).position === 'fixed') continue;
    if (r.right > ancho + 1 || r.left < -1) fuera.push({t: el.tagName.toLowerCase(), c: (typeof el.className === 'string' ? el.className : '').slice(0, 40), x: (el.textContent || '').trim().slice(0, 40), r: Math.round(r.right), w: Math.round(r.width)});
    const p = el.parentElement;
    if (p && p !== document.body && el.closest('main, .main-content, #contenido, .content')) {
      const rp = p.getBoundingClientRect(), ov = getComputedStyle(p).overflowX;
      if (r.right > rp.right + 2 && ov === 'visible' && rp.width > 0) dentro.push({t: el.tagName.toLowerCase(), c: (typeof el.className === 'string' ? el.className : '').slice(0, 40), p: p.tagName.toLowerCase() + '.' + (typeof p.className === 'string' ? p.className : '').slice(0, 30), x: (el.textContent || '').trim().slice(0, 30), sobra: Math.round(r.right - rp.right)});
    }
  }
  return {scrollW: de.scrollWidth, clientW: ancho, fuera: fuera.slice(0, 12), dentro: dentro.slice(0, 12)};
}"""


def test_ninguna_pantalla_juridica_desborda(servidor, abrir, entrar_como_equipo, monkeypatch):
    app = servidor.app
    t = db.crear_tenant("Despacho Jurídico Prueba con un nombre bastante largo S.L.P.")
    verticales.fijar_activo(t, "juridico", True)
    habilitar("boe-consolidada")
    habilitar("boe-diario-tc")
    from app.juridico import ingesta
    tr = transporte_boe()
    ingesta.sincronizar("boe-consolidada", conector_consolidada(tr), "2099-01-01", "2099-01-31")
    ingesta.sincronizar("boe-diario-tc", conector_diario(tr), "2099-01-10", "2099-01-10")
    # Datos reales son más largos que los sintéticos: títulos del BOE, ECLI y URLs sin espacios.
    conn = db.get_connection()
    largo = "Real Decreto Legislativo 1/2020, de 5 de marzo, por el que se aprueba el texto refundido de la Ley del Impuesto sobre la Renta de las Personas Físicas y otras disposiciones tributarias complementarias"
    conn.execute("UPDATE jur_documentos SET titulo = ?, ecli = 'ECLI:ES:TC:2099:1234ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', url_canonica = 'https://www.boe.es/buscar/act.php?id=BOE-A-2099-0001&p=20990101&tn=1#a1-muy-largo-sin-espacios-que-no-parte'", (largo,))
    conn.commit()
    conn.close()

    pagina, errores = abrir()
    cl = app.test_client()
    app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    try:
        admin = iniciar_sesion_de_prueba(cl, "jur-barrido@ejemplo.com", "contrasena123")
    finally:
        app.config["SERVER_NAME"] = None
    db.asignar_tenant(admin, t)
    db.asignar_supervisor_tenant(admin, True)
    conn = db.get_connection(); conn.execute("UPDATE usuarios SET rol = 'admin' WHERE id = ?", (admin,)); conn.commit(); conn.close()
    pagina.context.add_cookies([{"name": c.key, "value": c.value, "url": servidor.url} for c in cl._cookies.values()])

    # una consulta y un informe de verdad (con el modelo simulado), con una pregunta larguísima
    monkeypatch.setattr(reuniones, "configurada", lambda u: True)
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda u, s, contenido: json.dumps(ok_articulo1(contenido)))
    pregunta = "¿Qué límite tiene la deducción de gastos de ejemplo https://www.agenciatributaria.es/AEAT.internet/Inicio/_Segmentos_/Empresas_y_profesionales/muy/largo/sin/espacios/que/no/parte/nunca.html para un autónomo?"
    r = cl.post("/juridico/consultar", data={"pregunta": pregunta, "fecha_juridica": "2099-01-15", "coleccion": ["legislacion"]}, base_url="http://127.0.0.1:8000")
    run_id = int(r.headers["Location"].rstrip("/").split("/")[-1])
    g = cl.post(f"/juridico/consulta/{run_id}/informe", data={"titulo": "Límite de gastos deducibles en estimación directa para autónomos con varios locales y actividades distintas"}, base_url="http://127.0.0.1:8000")
    informe_id = int(g.headers["Location"].rstrip("/").split("/")[-1])
    did = db.get_connection().execute("SELECT id FROM jur_documentos WHERE id_externo = 'BOE-A-2099-0001'").fetchone()["id"]

    paginas = {
        "inicio": "/juridico/", "biblioteca": "/juridico/biblioteca", "biblioteca_q": "/juridico/biblioteca?q=deducci%C3%B3n&coleccion=legislacion",
        "documento": f"/juridico/documento/{did}", "consulta": f"/juridico/consulta/{run_id}", "informes": "/juridico/informes",
        "informe": f"/juridico/informes/{informe_id}", "fuentes": "/juridico/fuentes",
    }
    resumen = {}
    for ancho in ANCHOS:
        pagina.set_viewport_size({"width": ancho, "height": 900})
        for nombre, ruta in paginas.items():
            pagina.goto(servidor.url + ruta)
            pagina.wait_for_load_state("networkidle")
            if nombre == "fuentes":
                for d in pagina.query_selector_all("details"):
                    d.evaluate("e => e.open = true")
            m = pagina.evaluate(MEDIR)
            resumen[f"{nombre}@{ancho}"] = m
    malos = {k: (v["scrollW"], v["clientW"], v["dentro"][:3]) for k, v in resumen.items() if v["scrollW"] > v["clientW"] + 1 or v["dentro"]}
    assert not malos, malos
    assert not errores, errores
