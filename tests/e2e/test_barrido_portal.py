"""Barrido del PORTAL DE CLIENTE (entrando con su enlace de un solo uso) y de las pantallas sin sesión (entrar, registro, recuperar contraseña): mismas medidas que `test_barrido_pantallas`. Solo con GUILDA_BARRIDO=<carpeta>; escribe informe-portal.json."""
import json
import os
from pathlib import Path

import pytest

from app import db
from tests.e2e.test_barrido_pantallas import MEDIR
from tests.e2e.test_capturas_web import _sembrar

CARPETA = os.environ.get("GUILDA_BARRIDO")
pytestmark = pytest.mark.skipif(not CARPETA, reason="GUILDA_BARRIDO sin definir")
EXCLUIR = ("salir", "logout", "descargar", "export", "pdf", "csv", "static", "adjunto", "archivo", "borrar", "eliminar", "enviar", "manifest", "push", "comprobar")


def test_barrido_portal(servidor, abrir, entrar_como_equipo, chromium):
    t = db.crear_tenant("Despacho portal barrido")
    pagina, _ = abrir()
    uid = entrar_como_equipo(pagina, "portal-barrido@ejemplo.com", despacho=t, direccion=True)
    ids = _sembrar(uid, t)
    from datetime import date
    from app import facturas_contables as fc, facturas_portal, verticales
    verticales.fijar_activo(t, "contabilizacion", True)                       # el portal enseña sus facturas, la barra de secciones y el tablero
    hoy = date.today().isoformat()
    trimestre = fc.trimestre_de(hoy)
    v303 = db.crear_vencimiento_fiscal(t, ids["cliente"], "303", trimestre, hoy[:8] + "28", usuario_id=uid)
    db.crear_mensaje_vencimiento(v303, "empleado", "¿Nos mandas el extracto del banco del trimestre?", usuario_id=uid)
    nombres = ("Ferretería Paco", "Suministros Industriales del Levante, Sociedad Anónima", "ECLI:ES:TS:2099:12345ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    fids = [fc.crear_desde_portal(ids["cliente"], {"tipo": "recibida", "fecha": hoy, "numero": f"B-{i}", "tercero_nombre": n, "tercero_nif": "B11111111", "total": "121,00", "pct_iva": "21"}) for i, n in enumerate(nombres)]
    facturas_portal.devolver(t, uid, fids[1], "La foto sale movida y no se lee el NIF del proveedor; vuelve a hacerla con más luz y sin reflejos, por favor")
    facturas_portal.devolver(t, uid, fids[2], "No es de tu empresa")
    facturas_portal.escribir_como_cliente(ids["cliente"], fids[0], "¿Os hace falta algo más de esta factura? " * 6)
    facturas_portal.escribir_como_despacho(t, uid, fids[0], "Todo recibido, gracias; en cuanto la revisemos te avisamos desde aquí mismo.")
    from app import conformidad_declaracion, fiscal_nucleo as fn, fiscal_perfiles as fp
    from tests.escenarios_303 import ESCENARIOS
    verticales.fijar_activo(t, "fiscal", True)                                 # el portal enseña el modelo 303 que el despacho pide revisar
    try:
        fp.guardar_perfil(t, uid, ids["cliente"], {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    except fp.ErrorFiscal:                                                     # la siembra común puede haberlo creado ya
        pass
    for ap in ESCENARIOS["basico"][0]:
        try:
            fn.aprobar_apunte(t, uid, ids["cliente"], ap)
        except fp.ErrorFiscal:
            pass
    decl = fn.calcular_declaracion(t, uid, fn.crear_instantanea(t, uid, ids["cliente"], ejercicio=2026, periodo="2T")["id"])["id"]
    fn.revisar_declaracion(t, uid, decl)
    conformidad_declaracion.pedir(t, uid, decl)
    from app import justificantes
    justificantes.pedir(t, uid, ids["cliente"], [{"fecha": hoy, "importe": -31240, "concepto": "PAGO TARJETA FERRETERIA HERMANOS FERNANDEZ-VILLANUEVA DE LA VERA SOCIEDAD LIMITADA PROFESIONAL"}, {"fecha": hoy, "importe": 150000, "concepto": "TRANSFERENCIA CLIENTE X"}])
    j0 = justificantes.pendientes_del_cliente(ids["cliente"])[0]["id"]
    justificantes.responder(ids["cliente"], j0, "no_se", "No recuerdo qué era esto, lo miro y te cuento con más calma la semana que viene, gracias")
    conn = db.get_connection()
    conn.execute("UPDATE clientes_fiscales SET portal_honorarios = 1 WHERE id = ?", (ids["cliente"],))
    conn.execute("INSERT INTO honorarios_aplicados (tenant_id, vencimiento_id, cliente_fiscal_id, regla_nombre, concepto, importe_centimos, estado, confirmado_en) VALUES (?, ?, ?, 'Fija', 'Honorarios 303', 4500, 'confirmado', ?)",
                 (t, v303, ids["cliente"], db.now_iso()))
    conn.execute("UPDATE vencimientos_fiscales SET documenso_documento_id = 'env_barrido' WHERE id = ?", (v303,))
    conn.commit(); conn.close()
    db.subir_documento_vencimiento(v303, "justificante-presentacion-303-con-un-nombre-muy-largo-de-archivo.pdf", "application/pdf", b"%PDF-1.4\n%%EOF", origen="justificante")
    from app import portal_personas, portal_subida_rapida
    ficha = db.obtener_cliente_fiscal_por_id(ids["cliente"])
    conn = db.get_connection()
    conn.execute("UPDATE clientes_fiscales SET email = ? WHERE id = ?", ("titular-barrido@ejemplo.com", ids["cliente"]))
    conn.commit(); conn.close()
    ficha = db.obtener_cliente_fiscal_por_id(ids["cliente"])
    portal_personas.anadir(ficha, "administracion-con-un-nombre-de-correo-larguisimo@despacho-de-ejemplo-muy-largo.com", "Ana María Fernández-Villanueva de la Vera y Soto", "administracion")
    portal_personas.anadir(ficha, "asesor@ejemplo.com", "Asesor externo", "consulta")
    from app.db_fiscal import crear_cliente_fiscal
    crear_cliente_fiscal(t, "Segunda sociedad del mismo dueño, Sociedad Limitada Profesional", nif="B87654321", email="titular-barrido@ejemplo.com")
    token_subida = portal_subida_rapida.token_de(ficha)
    portal_subida_rapida.guardar_direccion_base(t, "facturas@despacho-de-ejemplo-muy-largo.com")
    token_preferencias = portal_personas.token_preferencias(ids["cliente"], "titular-barrido@ejemplo.com")
    for i, (fecha, tipo, total) in enumerate((("2026-02-10", "recibida", "121,00"), ("2026-03-10", "emitida", "242,00"), ("2025-08-10", "recibida", "60,50"), (hoy, "emitida", "363,00"))):
        fid = fc.crear_desde_portal(ids["cliente"], {"tipo": tipo, "fecha": fecha, "numero": f"S-{i}", "tercero_nombre": "Proveedor de la situación", "tercero_nif": "B11111111", "total": total, "pct_iva": "21"})
        conn = db.get_connection(); conn.execute("UPDATE facturas_contables SET estado = 'revisada' WHERE id = ?", (fid,)); conn.commit(); conn.close()
    conn = db.get_connection()
    conn.execute("UPDATE vencimientos_fiscales SET documento_solicitado = 'Extracto bancario completo del trimestre con todos los movimientos' WHERE id = ?", (v303,))
    conn.execute("INSERT INTO tareas_outlook (usuario_id, asunto, estado, porcentaje_completado, creada_en, actualizada_en, cliente_fiscal_id, visible_cliente, comentarios_cliente) VALUES (?, 'Preparar la declaración de la renta con un asunto bastante largo para ver cómo se parte', 'esperando', 40, '2026-10-01T10:00:00', '2026-11-03T09:00:00', ?, 1, 1)", (uid, ids["cliente"]))
    conn.commit(); conn.close()
    from app import portal_citas, portal_peticiones, portal_valoraciones
    from datetime import datetime, timedelta
    ficha_p = db.obtener_cliente_fiscal_por_id(ids["cliente"])
    pet_abierta = portal_peticiones.crear(ficha_p, "Extracto bancario completo del trimestre con todos los movimientos de todas las cuentas de la sociedad", "Necesitamos el de la cuenta principal y el de la de impuestos, en PDF o en CSV, con todos los movimientos del trimestre", (date.today() + timedelta(days=5)).isoformat(), por=uid)
    pet_cerrada = portal_peticiones.crear(ficha_p, "Escritura de constitución", por=uid)
    portal_peticiones.revisar(ficha_p, pet_cerrada, uid)
    portal_peticiones.reabrir(ficha_p, pet_cerrada, uid, "Falta la última página con las firmas de todos los socios, por favor súbela completa")
    portal_peticiones.revisar(ficha_p, pet_cerrada, uid)
    cita = portal_citas.solicitar(ficha_p, "titular-barrido@ejemplo.com", "videollamada", "Planificar el cierre del ejercicio y revisar las deducciones pendientes de la sociedad", "Martes o jueves por la mañana, mejor temprano")
    cita2 = portal_citas.solicitar(ficha_p, "titular-barrido@ejemplo.com", "visita", "Firmar unos documentos")
    portal_citas.confirmar(t, cita2, (datetime.now() + timedelta(days=4)).replace(hour=10, minute=0).isoformat(timespec="minutes"), "En la oficina de la calle Mayor, planta 2", uid)
    from app import portal_conversaciones
    conv = portal_conversaciones.iniciar(ficha_p, "Cambio de domicilio fiscal de la sociedad con efectos desde el próximo trimestre", "Nos mudamos a unas oficinas nuevas y necesitamos saber qué documentos hay que presentar y en qué plazo para no perder ninguna notificación", "cliente", "titular-barrido@ejemplo.com", peticion_id=pet_abierta)
    portal_conversaciones.responder(ficha_p, conv, "Hola. Hay que presentar el modelo 036 en el plazo de un mes desde el cambio. Si nos mandas la escritura o el contrato de alquiler de las nuevas oficinas lo preparamos nosotros", "despacho", "equipo@despacho.com")
    conv_cerrada = portal_conversaciones.iniciar(ficha_p, "Duda resuelta sobre el IVA", "¿Puedo deducir la factura del restaurante?", "despacho", "equipo@despacho.com")
    portal_conversaciones.cambiar_estado(ficha_p, conv_cerrada, abierta=False, por=uid)
    from app import portal_cuestionarios
    cuest = portal_cuestionarios.desde_plantilla(ficha_p, sorted(portal_cuestionarios.PLANTILLAS)[0], por=uid, fecha_limite=(date.today() + timedelta(days=5)).isoformat())
    cuest_largo = portal_cuestionarios.crear(ficha_p, "Cuestionario con un título larguísimo sobre el cambio de domicilio fiscal y de actividad de la sociedad", portal_cuestionarios.preguntas_desde_texto("¿Cuál es el nuevo domicilio completo de la sociedad, con calle, número, piso, código postal y municipio?\n¿Desde qué fecha exacta tiene efecto el cambio?"), por=uid)
    if os.environ.get("GUILDA_TEXTOS_LARGOS"):
        conn = db.get_connection()
        conn.execute("UPDATE clientes_fiscales SET nombre = ?", ("Construcciones y Reformas Hermanos Fernández-Villanueva de la Vera e Hijos Sociedad Limitada Profesional ECLI:ES:TS:2099:12345ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",))
        conn.commit()
        conn.close()
    rutas = sorted({r.rule for r in servidor.app.url_map.iter_rules() if r.rule.startswith("/portal") and "GET" in r.methods and not r.arguments and not any(x in r.rule.lower() for x in EXCLUIR)})
    rutas += [f"/portal/cuestionarios/{cuest}", f"/portal/cuestionarios/{cuest_largo}", f"/portal/conversaciones/nueva?peticion={pet_abierta}", f"/portal/conversaciones/{conv}", f"/portal/conversaciones/{conv_cerrada}", f"/portal/peticiones/{pet_abierta}", f"/portal/peticiones/{pet_cerrada}", f"/portal/facturas?trimestre={trimestre}", f"/portal/vencimientos/{v303}/documentos", f"/portal/vencimientos/{v303}/mensajes", f"/portal/facturas/{fids[0]}", f"/portal/facturas/{fids[1]}", f"/portal/declaraciones/{decl}", f"/portal/vencimientos/{v303}/firma", "/portal/justificantes", "/portal/buscar?q=ferreteria", "/portal/buscar?q=zzzz", f"/portal/preferencias/{token_preferencias}", f"/portal/subida/{token_subida}"]
    anonimas = ["/login", "/registro", "/recuperar-contrasena"]
    anchos = [int(a) for a in os.environ.get("GUILDA_ANCHOS", "375,768,1280").split(",")]
    lang = os.environ.get("GUILDA_IDIOMA", "es")
    informe = {}
    actual = {"k": ""}

    def recorrer(pg, lista, etiqueta):
        pg.context.set_extra_http_headers({"Accept-Language": lang})
        pg.on("pageerror", lambda e: informe.setdefault(actual["k"], {}).setdefault("js", []).append(str(e)[:140]))
        for ancho in anchos:
            pg.set_viewport_size({"width": ancho, "height": 800})
            for ruta in lista:
                actual["k"] = f"{etiqueta}{ruta}@{ancho}"
                try:
                    resp = pg.goto(servidor.url + ruta, wait_until="load")
                    pg.wait_for_timeout(120)
                    m = pg.evaluate(MEDIR)
                except Exception as e:
                    informe.setdefault(actual["k"], {})["error"] = str(e).splitlines()[0][:120]
                    continue
                d = informe.setdefault(actual["k"], {})
                d["http"] = resp.status if resp else 0
                d["final"] = pg.url.replace(servidor.url, "")[:60]
                d.update({k: v for k, v in m.items() if v})

    # sin sesión
    ctx = chromium.new_context(viewport={"width": 1280, "height": 800})
    recorrer(ctx.new_page(), anonimas, "anon:")
    ctx.close()
    # cliente del portal con su enlace
    ctx = chromium.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    pg.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(ids['cliente'], '127.0.0.1', email='titular-barrido@ejemplo.com')}")
    pg.wait_for_load_state("load")
    informe["entrada"] = {"final": pg.url.replace(servidor.url, "")}
    recorrer(pg, rutas, "portal:")
    ctx.close()
    Path(CARPETA).mkdir(parents=True, exist_ok=True)
    (Path(CARPETA) / "informe-portal.json").write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    print("BARRIDO PORTAL:", len(rutas) + len(anonimas), "pantallas x", len(anchos), "anchos")
