"""Revisión del portal de cliente en móvil: el equipo mira el portal de un cliente (vista previa) y el propio cliente recorre sus pestañas con textos kilométricos, midiendo desbordes y objetivos táctiles. Con
GUILDA_CAPTURAS_PORTAL=<carpeta> guarda además una captura de cada pantalla para revisarlas a ojo. Solo corre si se pide (GUILDA_BARRIDO o GUILDA_CAPTURAS_PORTAL)."""
import os
from datetime import date
from pathlib import Path

import pytest

from app import db, facturas_contables as fc, facturas_portal, justificantes, verticales
from tests.e2e.test_barrido_pantallas import MEDIR
from tests.e2e.test_capturas_web import _sembrar

CAPTURAS = os.environ.get("GUILDA_CAPTURAS_PORTAL")
pytestmark = pytest.mark.skipif(not (CAPTURAS or os.environ.get("GUILDA_BARRIDO")), reason="sin GUILDA_BARRIDO ni GUILDA_CAPTURAS_PORTAL")
LARGO = "Construcciones y Reformas Hermanos Fernández-Villanueva de la Vera e Hijos Sociedad Limitada Profesional"


def test_portal_en_movil(servidor, abrir, entrar_como_equipo, chromium):
    t = db.crear_tenant("Despacho portal móvil")
    pagina, _ = abrir()
    uid = entrar_como_equipo(pagina, "portal-movil@ejemplo.com", despacho=t, direccion=True)
    ids = _sembrar(uid, t)
    cid = ids["cliente"]
    verticales.fijar_activo(t, "contabilizacion", True)
    conn = db.get_connection()
    conn.execute("UPDATE clientes_fiscales SET nombre = ? WHERE id = ?", (LARGO, cid))
    conn.commit(); conn.close()
    hoy = date.today().isoformat()
    f = fc.crear_desde_portal(cid, {"tipo": "recibida", "fecha": hoy, "numero": "B-1", "tercero_nombre": LARGO, "tercero_nif": "B11111111", "total": "121,00", "pct_iva": "21"})
    facturas_portal.escribir_como_despacho(t, uid, f, "Necesitamos la factura original, la copia que has subido no se lee bien y sin ella no podemos contabilizarla este trimestre.")
    v = db.crear_vencimiento_fiscal(t, cid, "303", "2026-T3", hoy[:8] + "28", usuario_id=uid)
    db.crear_mensaje_vencimiento(v, "empleado", "¿Nos mandas el extracto del banco del trimestre completo, por favor, con todos los movimientos?", usuario_id=uid)
    justificantes.pedir(t, uid, cid, [{"fecha": hoy, "importe": -31240, "concepto": LARGO + " " + LARGO}])
    from app import portal_personas, portal_subida_rapida
    conn = db.get_connection(); conn.execute("UPDATE clientes_fiscales SET email = 'titular-movil@ejemplo.com' WHERE id = ?", (cid,)); conn.commit(); conn.close()
    ficha = db.obtener_cliente_fiscal_por_id(cid)
    portal_personas.anadir(ficha, "administracion-con-un-nombre-de-correo-larguisimo@despacho-de-ejemplo-muy-largo.com", LARGO, "administracion")
    portal_subida_rapida.guardar_direccion_base(t, "facturas@despacho-de-ejemplo-muy-largo.com")
    token = portal_subida_rapida.token_de(ficha)

    medidas = {}

    def medir(pg, ruta, etiqueta):
        pg.goto(servidor.url + ruta, wait_until="load")
        pg.wait_for_timeout(150)
        m = pg.evaluate(MEDIR)
        medidas[etiqueta] = {k: v for k, v in m.items() if k in ("desborde", "fuera_de_caja", "solapes", "sin_nombre", "pequenos", "pagina") and v}
        if CAPTURAS:
            Path(CAPTURAS).mkdir(parents=True, exist_ok=True)
            pg.screenshot(path=str(Path(CAPTURAS) / f"{etiqueta}.png"), full_page=True)

    # 1) el equipo, en vista previa (su sesión ya está abierta en `pagina`)
    pagina.set_viewport_size({"width": 360, "height": 800})
    resp = pagina.request.post(f"{servidor.url}/fiscal/clientes/{cid}/ver-portal")
    assert resp.status in (200, 302)
    medir(pagina, "/portal/", "preview-inicio")
    assert pagina.locator(".portal-vista-previa").is_visible()
    assert pagina.locator(".portal-solo-lectura button[type=submit]").first.evaluate("e => getComputedStyle(e).pointerEvents") == "none" if pagina.locator(".portal-solo-lectura button[type=submit]").count() else True
    pagina.request.post(f"{servidor.url}/portal/salir")

    # 2) el cliente con su enlace
    ctx = chromium.new_context(viewport={"width": 360, "height": 800})
    pg = ctx.new_page()
    pg.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(cid, '127.0.0.1', email='titular-movil@ejemplo.com')}")
    for ruta, etiqueta in (("/portal/", "inicio"), ("/portal/facturas", "facturas"), (f"/portal/facturas/{f}", "factura"), ("/portal/impuestos", "impuestos"), ("/portal/mensajes", "mensajes"),
                           ("/portal/carpeta", "carpeta"), ("/portal/justificantes", "justificantes"), (f"/portal/vencimientos/{v}/mensajes", "mensajes-modelo"),
                           ("/portal/cuenta", "cuenta"), ("/portal/buscar?q=construcciones", "buscar"), (f"/portal/subida/{token}", "subida-rapida")):
        medir(pg, ruta, etiqueta)
    ctx.close()
    problemas = {k: m for k, m in medidas.items() if any(m.get(c) for c in ("desborde", "fuera_de_caja", "solapes", "pagina", "pequenos", "sin_nombre"))}
    assert not problemas, problemas
