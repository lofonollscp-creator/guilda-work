"""Guilda Work — Registro Diario de Actividad.

Punto de entrada: arranca un servidor Flask local y lo muestra en una
ventana nativa de Windows (WebView2, vía pywebview) en lugar de abrir el
navegador del sistema.

Multiusuario (Fase 1 de la app móvil): en modo escritorio (esta misma app,
`main()`) no hay pantalla de login — se entra automáticamente como el
"usuario local" (`db.usuario_local_id()`), igual que siempre. El login de
verdad (`/login`, `/registro`) solo hace falta cuando la app se sirve fuera
de este modo (por ejemplo, ya alojada en internet para la futura app
móvil — ver `serve.py`), donde `MODO_ESCRITORIO` es False.
"""
import logging
import os
import secrets
import socket
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import sentry_sdk
import webview
from flask import Flask, Response, abort, g, jsonify, make_response, redirect, render_template, request, session, url_for
from flask_babel import Babel
from flask_babel import gettext as _
from sentry_sdk.integrations.flask import FlaskIntegration
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from . import ai_local, busqueda, captcha, correo, db, export, herramientas, ia_asistente, importador, kratos, push
from .auth import limiter, login_required
from .rutas_api import api_bp
from .rutas_backoffice import backoffice_bp
from .rutas_correo import correo_bp
from .rutas_docs import docs_bp
from .rutas_fichaje import fichaje_bp
from .rutas_fiscal import fiscal_bp
from .rutas_hydra import hydra_bp
from .rutas_ia import ia_bp
from .rutas_kratos_proxy import ip_requiere_captcha, kratos_proxy_bp
from .rutas_tareas import tareas_bp
from .rutas_tiquets import tiquets_bp

HOST = "127.0.0.1"
PORT = 5057
ATAJO_CAPTURA = "ctrl+alt+g"

# Si se empaqueta en modo ventana (--windowed / --noconsole), Windows no da
# stdout/stderr al proceso y quedan en None: el logging de Flask/Werkzeug
# escribe ahí por defecto y reventaría al arrancar. Los redirigimos a nada.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# Antes de esto no había ni un solo `logging.` en toda la app -- los errores
# no controlados solo dejaban el traceback de Werkzeug en la salida estándar
# capturada por systemd (journalctl), sin nivel/formato/timestamp propios.
# Va ANTES de crear `app` para que quede listo antes de que cualquier
# import de los módulos de rutas pueda registrar algo.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("guilda")

# Alertas de errores no controlados vía GlitchTip (autoalojado, protocolo
# compatible con Sentry -- ver docker-compose.yml). Sin GLITCHTIP_DSN
# (modo escritorio, tests, desarrollo local) sentry_sdk.init() con
# dsn=None es un no-op documentado: no manda nada a ningún sitio, así que
# no hace falta envolver esto en un if aparte.
sentry_sdk.init(
    dsn=os.environ.get("GLITCHTIP_DSN"),
    integrations=[FlaskIntegration()],
    traces_sample_rate=0.0,  # solo errores, sin trazas de rendimiento (evento aparte, no lo pedía este lote)
    send_default_pii=False,  # nunca mandar datos de usuario (emails, IPs) a las trazas
)

PROMPT_IA_POR_DEFECTO = "Resume mis actividades agrupadas por categoría, destacando lo más relevante y el tiempo dedicado a cada una."

# True solo dentro de main() (la app de escritorio empaquetada/pywebview):
# hace que cualquier visita entre automáticamente como el usuario local, sin
# pantalla de login. Falso por defecto (p.ej. al servir con waitress/serve.py
# para la futura app móvil), donde sí hace falta iniciar sesión de verdad.
MODO_ESCRITORIO = False

# Cuando se empaqueta con PyInstaller, los recursos (templates/static) viajan
# dentro de sys._MEIPASS/app (--add-data "app/templates;app/templates" los
# coloca ahí). En desarrollo normal, usamos la carpeta de este paquete.
if hasattr(sys, "_MEIPASS"):
    BASE_DIR = Path(sys._MEIPASS) / "app"
else:
    BASE_DIR = Path(__file__).resolve().parent

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
# Sin esto, con debug=False Jinja cachea las plantillas compiladas la primera
# vez y no recoge cambios en los .html hasta reiniciar el proceso. El coste
# (comprobar mtime en cada render) es insignificante para una app de un solo
# usuario local.
app.config["TEMPLATES_AUTO_RELOAD"] = True
# Necesaria para firmar la cookie de sesión (login). En desarrollo/escritorio
# se genera una aleatoria al arrancar (basta con que la sesión sobreviva
# mientras el proceso está vivo); en un despliegue real de verdad, fija
# GUILDA_SECRET_KEY como variable de entorno para que las sesiones no se
# invaliden cada vez que se reinicie el proceso.
app.secret_key = os.environ.get("GUILDA_SECRET_KEY") or secrets.token_hex(32)
# En modo hospedado, Caddy reenvía a Flask por localhost -- sin esto,
# request.remote_addr (y por tanto el rate-limit de app/auth.py y el
# contador de fallos de login de app/rutas_kratos_proxy.py) verían siempre
# la propia IP de Caddy (127.0.0.1), nunca la del visitante real. Caddy
# manda X-Forwarded-For de un solo salto por defecto en `reverse_proxy`,
# de ahí x_for=1 -- en modo escritorio (sin Caddy delante) no hay cabecera
# que reescribir, así que esto no cambia nada allí.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
limiter.init_app(app)

# Multi-idioma: castellano, catalán, inglés, francés. El usuario elegido
# manda (columna usuarios.idioma, ver /idioma/<codigo> más abajo); mientras
# no haya elegido ninguno, se usa el idioma del navegador si coincide con
# alguno de los soportados, y si no, castellano por defecto.
IDIOMAS_DISPONIBLES = ["es", "ca", "en", "fr"]

# Los catálogos .po/.mo viven en translations/ junto a app/ (no dentro de
# app/), porque pybabel extract recorre app/ Y templates/ desde la raíz del
# repo. Flask-Babel por defecto solo mira "translations" relativo a
# app.root_path (que es BASE_DIR = .../app), así que sin esto nunca
# encontraría los catálogos y serviría siempre castellano en silencio.
app.config["BABEL_TRANSLATION_DIRECTORIES"] = str(BASE_DIR.parent / "translations")


def _seleccionar_idioma():
    idioma_guardado = db.idioma_usuario(getattr(g, "usuario_id", None)) if getattr(g, "usuario_id", None) else None
    if idioma_guardado in IDIOMAS_DISPONIBLES:
        return idioma_guardado
    return request.accept_languages.best_match(IDIOMAS_DISPONIBLES) or "es"


babel = Babel(app, default_locale="es", locale_selector=_seleccionar_idioma)
app.register_blueprint(tareas_bp)
app.register_blueprint(tiquets_bp)
app.register_blueprint(fichaje_bp)
app.register_blueprint(fiscal_bp)
app.register_blueprint(correo_bp)
app.register_blueprint(ia_bp)
app.register_blueprint(api_bp)
app.register_blueprint(kratos_proxy_bp)
app.register_blueprint(hydra_bp)
app.register_blueprint(backoffice_bp)
app.register_blueprint(docs_bp)


@app.errorhandler(Exception)
def _registrar_excepcion_no_controlada(error):
    # Las HTTPException (404, 403, la propia abort(...) de las rutas...) no
    # son errores de programación -- se dejan pasar tal cual para que Flask
    # las convierta en su respuesta normal, sin registrarlas como fallo.
    if isinstance(error, HTTPException):
        return error
    logger.exception("Excepción no controlada en %s %s", request.method, request.path)
    sentry_sdk.capture_exception(error)
    return jsonify(error=_("Ha ocurrido un error interno. Se ha registrado para revisión.")) if request.path.startswith("/api/") else (
        _("Ha ocurrido un error interno. Se ha registrado para revisión."),
        500,
    )


KRATOS_SESSION_COOKIE = "ory_kratos_session"


@app.before_request
def _resolver_usuario_actual():
    # Modo escritorio (GuildaWork.exe): un único usuario local de confianza,
    # sin pantalla de login real — no pasa por Kratos en absoluto (Fase 7a).
    if MODO_ESCRITORIO:
        if "usuario_id" not in session:
            session["usuario_id"] = db.usuario_local_id()
        g.usuario_id = session.get("usuario_id")
        g.es_admin = db.es_admin(g.usuario_id)
        tenant = db.tenant_de_usuario(g.usuario_id)
        g.tenant_id = tenant["id"] if tenant else None
        g.gestor_fichajes = db.es_gestor_fichajes(g.usuario_id)
        return

    # Modo hospedado: identidad real vía Ory Kratos. Solo se llama a Kratos
    # si hay cookie de sesión de Kratos en la petición — evita una llamada
    # HTTP en cada visita anónima (página de login, assets, etc.).
    g.usuario_id = None
    g.es_admin = False
    g.tenant_id = None
    g.gestor_fichajes = False
    if KRATOS_SESSION_COOKIE not in request.cookies:
        return
    sesion_kratos = kratos.whoami(request.cookies)
    if not sesion_kratos or not sesion_kratos.get("active"):
        return
    identity_id = sesion_kratos["identity"]["id"]
    usuario = db.usuario_por_kratos_id(identity_id)
    if usuario is None:
        # Primera vez que se ve esta identidad (recién registrada en Kratos,
        # que ya le abrió sesión automáticamente): crea la fila local
        # vinculada sobre la marcha, sin contraseña propia que guardar.
        email = sesion_kratos["identity"]["traits"]["email"]
        g.usuario_id = db.crear_usuario_vinculado_a_kratos(email, identity_id)
    else:
        g.usuario_id = usuario["id"]
        g.es_admin = usuario["rol"] == "admin"
        g.tenant_id = usuario["tenant_id"]
        g.gestor_fichajes = bool(usuario["gestor_fichajes"])


@app.context_processor
def inyectar_modo_escritorio():
    # Función (no un valor fijado una vez) porque MODO_ESCRITORIO puede
    # cambiar de False a True después de que Flask ya esté creado (ver
    # activar_modo_escritorio() más abajo, usado por el lanzador .exe) --
    # leerlo aquí en cada petición evita que quede congelado al valor de
    # cuando se registró este context_processor.
    return {"modo_escritorio": MODO_ESCRITORIO}


@app.context_processor
def inyectar_idioma_actual():
    from flask_babel import get_locale

    return {"idioma_actual": str(get_locale()), "idiomas_disponibles": IDIOMAS_DISPONIBLES}


@app.context_processor
def inyectar_correo_badge():
    # El rail de iconos necesita este contador en cualquier página (para el
    # badge sobre el icono de Correo). La lista de menús ya no vive en un
    # sidebar global — cada ruta que la necesita (inicio(), captura()) la
    # pasa explícitamente en su propio contexto.
    if not g.usuario_id:
        return {}
    return {"correo_no_leidos_sidebar": db.contar_no_leidos_total_correo(g.usuario_id)}


@app.context_processor
def inyectar_ia_flotante():
    # El panel flotante del Asistente IA vive en base.html, así que necesita
    # su propio contexto en cualquier página que no sea ya /ia (ahí la ruta
    # pasa mensajes/pendiente explícitamente para el chat de página completa).
    if not g.usuario_id or (request.endpoint and request.endpoint.startswith("ia.")):
        return {}
    return {
        "ia_mensajes_flotante": db.listar_mensajes_ia(g.usuario_id),
        "ia_pendiente_flotante": ia_asistente.pendiente_actual(g.usuario_id),
    }


@app.context_processor
def inyectar_chatwoot_widget():
    # Widget de chat en vivo de Chatwoot (Fase 7g + soporte de tenants,
    # Fase 7c.3) — burbuja de "Contactar con soporte" en cualquier página
    # con sesión. CHATWOOT_WEBSITE_TOKEN es el token PÚBLICO del canal
    # "Website" de Chatwoot (pensado para ir embebido en HTML de cara al
    # navegador, no es un secreto — se crea en Chatwoot: Settings →
    # Inboxes → Add Inbox → Website). Sin la variable puesta (por
    # defecto, incluido en local), el widget simplemente no se muestra.
    website_token = os.environ.get("CHATWOOT_WEBSITE_TOKEN")
    if not g.usuario_id or not website_token:
        return {}
    usuario = db.obtener_usuario(g.usuario_id)
    tenant = db.tenant_de_usuario(g.usuario_id)
    return {
        "chatwoot_website_token": website_token,
        "chatwoot_base_url": os.environ.get("HERRAMIENTA_CHATWOOT_URL", "http://127.0.0.1:8011"),
        "chatwoot_usuario_email": usuario["email"] if usuario else "",
        "chatwoot_tenant_nombre": tenant["nombre"] if tenant else "",
    }


# --- Autenticación (Fase 7a: Ory Kratos) --------------------------------
#
# El navegador ya NO postea a estas rutas — el <form> de login.html/
# registro.html postea directo a la `action` que devuelve Kratos (reescrita
# a /.ory/..., ver app/rutas_kratos_proxy.py). Estas vistas solo:
# 1. Si no hay `flow` en la URL, redirigen a Kratos para que inicie uno
#    (que a su vez redirige de vuelta aquí, ya con `?flow=<id>`).
# 2. Si hay `flow`, recuperan sus nodos (campos + posibles errores de un
#    intento anterior) y renderizan la plantilla.
# En modo escritorio nunca se llega aquí (antes ya hay usuario_id).


def _flujo_o_redirigir(tipo: str):
    """Devuelve los datos del flujo (nodos + acción reescrita) para el
    `flow` de la URL actual, o None si hay que redirigir (sin flow, o el
    flow ya no es válido/ha caducado) — en ese caso ya deja preparada la
    respuesta de redirección en `g._redireccion_flujo`."""
    flow_id = request.args.get("flow")
    if not flow_id:
        g._redireccion_flujo = redirect(f"/.ory/self-service/{tipo}/browser")
        return None
    try:
        flujo = kratos.obtener_flujo(tipo, flow_id, request.cookies)
    except kratos.ErrorKratos:
        rutas_por_tipo = {
            "login": "login",
            "registration": "registro",
            "verification": "verificar_email",
            "recovery": "recuperar_contrasena",
            # Fase G1: cambiar contraseña/email estando logueado -- quinto
            # tipo de flujo Kratos, mismo mecanismo genérico que los otros
            # cuatro (_flujo_o_redirigir no necesita ningún cambio propio).
            "settings": "ajustes_cuenta",
        }
        g._redireccion_flujo = redirect(url_for(rutas_por_tipo.get(tipo, "login")))
        return None
    return {
        "nodos": flujo["ui"]["nodes"],
        "accion": kratos.reescribir_action_para_navegador(flujo["ui"]["action"]),
        "mensajes": flujo["ui"].get("messages", []),
    }


# Orígenes de la landing pública (fuera de este repo, /var/www/landing/),
# única fuente legítima de peticiones CORS a /contacto — no se abre CORS al
# resto de la app, solo a este endpoint público sin autenticación.
_ORIGENES_LANDING = {"https://guildawork.com", "https://www.guildawork.com"}


def _con_cors_landing(resp):
    origen = request.headers.get("Origin")
    if origen in _ORIGENES_LANDING:
        resp.headers["Access-Control-Allow-Origin"] = origen
        resp.headers["Access-Control-Allow-Methods"] = "POST"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.route("/contacto", methods=["POST", "OPTIONS"])
@limiter.limit("5/hour")
def contacto():
    """Formulario de contacto de la landing (guildawork.com) — no crea
    tenant ni usuario, solo guarda el interés en leads_contacto para que
    un admin lo procese a mano desde el backoffice (ver
    backoffice.crear_tenant/crear_usuario). Sin @login_required: lo llama
    un visitante anónimo desde fuera de la app."""
    if request.method == "OPTIONS":
        return _con_cors_landing(make_response("", 204))

    datos = request.get_json(silent=True) or {}
    nombre = (datos.get("nombre") or "").strip()
    email = (datos.get("email") or "").strip()
    if not nombre or not email or "@" not in email:
        return _con_cors_landing(
            make_response(jsonify({"ok": False, "error": "Faltan datos: nombre y email son obligatorios."}), 400)
        )
    db.crear_lead_contacto(
        nombre,
        email,
        empresa=(datos.get("empresa") or "").strip() or None,
        telefono=(datos.get("telefono") or "").strip() or None,
        mensaje=(datos.get("mensaje") or "").strip() or None,
    )
    return _con_cors_landing(make_response(jsonify({"ok": True})))


@app.route("/registro", methods=["GET"])
def registro():
    if g.usuario_id:
        return redirect(url_for("inicio"))
    datos = _flujo_o_redirigir("registration")
    if datos is None:
        return g._redireccion_flujo
    return render_template("registro.html", **datos)


@app.route("/login", methods=["GET"])
def login():
    if g.usuario_id:
        return redirect(url_for("inicio"))
    datos = _flujo_o_redirigir("login")
    if datos is None:
        return g._redireccion_flujo
    # Ver app/rutas_kratos_proxy.py: tras varios fallos seguidos desde esta
    # IP, se exige resolver un captcha antes de que el próximo POST de
    # login llegue a Kratos, en vez de banear directamente (eso lo sigue
    # haciendo CrowdSec como red de respaldo).
    datos["requiere_captcha"] = ip_requiere_captcha(request.remote_addr)
    datos["captcha_fallido"] = request.args.get("captcha_error") == "1"
    return render_template("login.html", **datos)


@app.route("/verificar-email", methods=["GET"])
def verificar_email():
    datos = _flujo_o_redirigir("verification")
    if datos is None:
        return g._redireccion_flujo
    return render_template("verificar_email.html", **datos)


@app.route("/recuperar-contrasena", methods=["GET"])
def recuperar_contrasena():
    if g.usuario_id:
        return redirect(url_for("inicio"))
    datos = _flujo_o_redirigir("recovery")
    if datos is None:
        return g._redireccion_flujo
    return render_template("recuperar_contrasena.html", **datos)


@app.route("/captcha/reto", methods=["GET"])
@limiter.limit("30/minute")
def captcha_reto():
    """Reto ALTCHA para el widget de login.html (ver app/captcha.py) --
    público y sin login_required a propósito, se pide antes de que exista
    ninguna sesión. Rate-limited para que no sirva para acumular retos sin
    intención de resolverlos."""
    return jsonify(captcha.generar_reto())


@app.route("/logout", methods=["POST"])
def logout():
    url = kratos.logout_url(request.cookies)
    return redirect(url or url_for("login"))


@app.route("/pendiente-activacion")
@login_required
def pendiente_activacion():
    return render_template("pendiente_activacion.html")


@app.route("/")
@login_required
def inicio():
    # Un usuario recién registrado por /registro (Kratos) no tiene tenant
    # hasta que un admin lo asigna a mano desde el backoffice (ver
    # backoffice.asignar_tenant_usuario) — sin este aviso, entraba en una
    # app completamente vacía sin ninguna pista de qué está pasando.
    # No aplica en modo escritorio (usuario local siempre provisionado) ni
    # a admins (jorge y compañía operan a propósito sin tenant asignado).
    if not MODO_ESCRITORIO and g.tenant_id is None and not g.es_admin:
        return redirect(url_for("pendiente_activacion"))
    menus = db.listar_categorias(g.usuario_id)
    activas = db.tareas_activas(g.usuario_id)
    activas_por_menu: dict[int, list] = {}
    for t in activas:
        activas_por_menu.setdefault(t["categoria_id"], []).append(t)
    entradas_hoy = db.contar_entradas_hoy_por_usuario(g.usuario_id)
    hoy = datetime.now().strftime("%Y-%m-%d")
    log_hoy = db.historial(g.usuario_id, desde=hoy, hasta=hoy)

    # Checklist de onboarding: los 3 pasos se calculan en caliente a partir
    # de datos que ya existen (nunca se trackean aparte, para que no puedan
    # desincronizarse) — solo se calculan si la tarjeta sigue visible, para
    # no gastar 2 consultas de más en cada visita una vez descartada.
    mostrar_onboarding = db.onboarding_visible(g.usuario_id)
    onboarding = None
    if mostrar_onboarding:
        onboarding = {
            "tiene_menu": bool(menus),
            "tiene_correo": bool(db.listar_cuentas_correo(g.usuario_id)),
            "ha_usado_ia": bool(db.listar_mensajes_ia(g.usuario_id)),
        }

    # Tarjeta de vencimientos fiscales próximos (calendario fiscal, solo
    # con tenant asignado -- igual que el resto de esa sección) -- mismo
    # criterio "tarjeta pulsable" que la de correos sin leer, próximos 30
    # días para no saturar la cifra con todo el año.
    total_vencimientos_proximos = None
    hasta_vencimientos_proximos = None
    if g.tenant_id is not None:
        hasta_vencimientos_proximos = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        total_vencimientos_proximos = len(
            db.listar_vencimientos_fiscales(g.tenant_id, estado="pendiente", hasta=hasta_vencimientos_proximos)
        )

    return render_template(
        "inicio.html",
        menus=menus,
        activas_por_menu=activas_por_menu,
        entradas_hoy=entradas_hoy,
        log_hoy=log_hoy,
        total_activas=len(activas),
        total_notas_hoy=len([f for f in log_hoy if f["origen"] == "nota"]),
        total_vencimientos_proximos=total_vencimientos_proximos,
        hasta_vencimientos_proximos=hasta_vencimientos_proximos,
        onboarding=onboarding,
    )


@app.route("/onboarding/ocultar", methods=["POST"])
@login_required
def ocultar_onboarding():
    db.ocultar_onboarding(g.usuario_id)
    return redirect(url_for("inicio"))


@app.route("/idioma/<codigo>", methods=["POST"])
@login_required
def cambiar_idioma(codigo):
    if codigo in IDIOMAS_DISPONIBLES:
        db.cambiar_idioma_usuario(g.usuario_id, codigo)
    # Vuelve a la misma página desde la que se cambió el idioma (el
    # selector vive en el panel de ajustes, presente en cualquier
    # pantalla) -- solo se fía de un referrer del propio origen, nunca de
    # uno externo.
    destino = request.referrer
    if destino and destino.startswith(request.host_url):
        return redirect(destino)
    return redirect(url_for("inicio"))


@app.route("/menus", methods=["POST"])
@login_required
def crear_menu():
    nombre = request.form.get("nombre", "").strip()
    color = request.form.get("color", "").strip() or None
    if nombre:
        db.crear_categoria(g.usuario_id, nombre, color)
    return redirect(url_for("inicio"))


@app.route("/menu/<int:menu_id>")
@login_required
def ver_menu(menu_id: int):
    menu = db.obtener_categoria(g.usuario_id, menu_id)
    if menu is None:
        abort(404)
    q = request.args.get("q") or None
    activas = [t for t in db.tareas_activas(g.usuario_id) if t["categoria_id"] == menu_id]
    log = db.historial(g.usuario_id, categoria_id=menu_id, texto=q)
    plantillas = db.listar_plantillas(menu_id)
    return render_template("menu.html", menu=menu, activas=activas, log=log, q=q or "", plantillas=plantillas)


@app.route("/menu/<int:menu_id>/plantillas", methods=["POST"])
@login_required
def crear_plantilla(menu_id: int):
    if db.obtener_categoria(g.usuario_id, menu_id) is None:
        abort(404)
    texto = request.form.get("texto", "").strip()
    if texto:
        db.crear_plantilla(menu_id, texto)
    return redirect(url_for("ver_menu", menu_id=menu_id))


@app.route("/plantilla/<int:plantilla_id>/eliminar", methods=["POST"])
@login_required
def eliminar_plantilla(plantilla_id: int):
    db.eliminar_plantilla(plantilla_id)
    return redirect(request.form.get("volver_a") or request.referrer or url_for("inicio"))


@app.route("/menu/<int:menu_id>/renombrar", methods=["POST"])
@login_required
def renombrar_menu(menu_id: int):
    if db.obtener_categoria(g.usuario_id, menu_id) is None:
        abort(404)
    nombre = request.form.get("nombre", "").strip()
    color = request.form.get("color", "").strip() or None
    if nombre:
        db.renombrar_categoria(g.usuario_id, menu_id, nombre, color)
    return redirect(url_for("ver_menu", menu_id=menu_id))


@app.route("/menu/<int:menu_id>/mover", methods=["POST"])
@login_required
def mover_menu(menu_id: int):
    direccion = request.form.get("direccion")
    if direccion in ("arriba", "abajo"):
        db.mover_categoria(g.usuario_id, menu_id, direccion)
    return redirect(request.referrer or url_for("inicio"))


@app.route("/menu/<int:menu_id>/favorito", methods=["POST"])
@login_required
def alternar_favorito_menu(menu_id: int):
    if db.obtener_categoria(g.usuario_id, menu_id) is None:
        abort(404)
    db.alternar_favorito_categoria(g.usuario_id, menu_id)
    return redirect(request.referrer or url_for("inicio"))


@app.route("/menus/reordenar", methods=["POST"])
@login_required
def reordenar_menus():
    """Recibe el orden final tras arrastrar en la barra lateral (fetch en
    segundo plano, sin recarga de página — ver app/static/sidebar.js)."""
    datos = request.get_json(silent=True) or {}
    orden_ids = [int(i) for i in datos.get("orden", []) if str(i).isdigit()]
    db.reordenar_categorias(g.usuario_id, orden_ids)
    return "", 204


@app.route("/menu/<int:menu_id>/eliminar", methods=["POST"])
@login_required
def eliminar_menu(menu_id: int):
    if db.obtener_categoria(g.usuario_id, menu_id) is None:
        abort(404)
    db.eliminar_categoria(g.usuario_id, menu_id)
    return redirect(url_for("inicio"))


@app.route("/notas", methods=["POST"])
@login_required
def crear_nota():
    texto = request.form.get("texto", "").strip()
    categoria_id = request.form.get("categoria_id") or None
    if texto:
        db.crear_nota(g.usuario_id, texto, categoria_id=categoria_id)
    return redirect(request.referrer or url_for("inicio"))


@app.route("/nota/<int:nota_id>/editar", methods=["GET", "POST"])
@login_required
def editar_nota(nota_id: int):
    nota = db.obtener_nota(g.usuario_id, nota_id)
    if nota is None:
        abort(404)
    if request.method == "POST":
        texto = request.form.get("texto", "").strip()
        volver_a = request.form.get("volver_a") or url_for("inicio")
        if texto:
            db.editar_nota(g.usuario_id, nota_id, texto)
        return redirect(volver_a)
    volver_a = request.args.get("volver_a") or request.referrer or url_for("inicio")
    return render_template("editar_nota.html", nota=nota, volver_a=volver_a)


@app.route("/nota/<int:nota_id>/eliminar", methods=["POST"])
@login_required
def eliminar_nota(nota_id: int):
    if db.obtener_nota(g.usuario_id, nota_id) is None:
        abort(404)
    db.eliminar_nota(g.usuario_id, nota_id)
    return redirect(request.form.get("volver_a") or request.referrer or url_for("inicio"))


@app.route("/tareas", methods=["POST"])
@login_required
def crear_tarea():
    nombre = request.form.get("nombre", "").strip()
    categoria_id = request.form.get("categoria_id")
    tipo = request.form.get("tipo", "duracion")
    if nombre and categoria_id:
        if db.obtener_categoria(g.usuario_id, int(categoria_id)) is None:
            abort(404)
        db.crear_tarea(g.usuario_id, nombre, int(categoria_id), tipo)
    return redirect(request.referrer or url_for("inicio"))


@app.route("/tarea/<int:tarea_id>/editar", methods=["GET", "POST"])
@login_required
def editar_tarea(tarea_id: int):
    tarea = db.obtener_tarea(g.usuario_id, tarea_id)
    if tarea is None:
        abort(404)
    error = None
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        inicio = request.form.get("inicio") or None
        fin = request.form.get("fin") or None
        volver_a = request.form.get("volver_a") or url_for("inicio")
        if nombre:
            db.editar_tarea(g.usuario_id, tarea_id, nombre)
        if inicio:
            error = db.editar_tiempos_tarea(g.usuario_id, tarea_id, inicio, fin)
        if error is None:
            return redirect(volver_a)
        tarea = db.obtener_tarea(g.usuario_id, tarea_id)
    volver_a = (
        request.form.get("volver_a")
        or request.args.get("volver_a")
        or request.referrer
        or url_for("inicio")
    )
    return render_template("editar_tarea.html", tarea=tarea, error=error, volver_a=volver_a)


@app.route("/tarea/<int:tarea_id>/eliminar", methods=["POST"])
@login_required
def eliminar_tarea(tarea_id: int):
    if db.obtener_tarea(g.usuario_id, tarea_id) is None:
        abort(404)
    db.eliminar_tarea(g.usuario_id, tarea_id)
    return redirect(request.form.get("volver_a") or request.referrer or url_for("inicio"))


@app.route("/tareas/<int:tarea_id>/pausar", methods=["POST"])
@login_required
def pausar_tarea(tarea_id: int):
    db.pausar_tarea(g.usuario_id, tarea_id)
    return redirect(request.referrer or url_for("inicio"))


@app.route("/tareas/<int:tarea_id>/reanudar", methods=["POST"])
@login_required
def reanudar_tarea(tarea_id: int):
    db.reanudar_tarea(g.usuario_id, tarea_id)
    return redirect(request.referrer or url_for("inicio"))


@app.route("/tareas/<int:tarea_id>/finalizar", methods=["POST"])
@login_required
def finalizar_tarea(tarea_id: int):
    db.finalizar_tarea(g.usuario_id, tarea_id)
    return redirect(request.referrer or url_for("inicio"))


HISTORIAL_POR_PAGINA = 50


def _contexto_historial(desde, hasta, categoria_id, q=None, pagina=1, **extra):
    pagina = max(pagina or 1, 1)
    offset = (pagina - 1) * HISTORIAL_POR_PAGINA
    # Se pide una fila de más (limite+1) solo para saber si hay página
    # siguiente, sin necesidad de un COUNT(*) aparte -- mismo truco que ya
    # usa app/rutas_tareas.py para su propia paginación.
    filas = db.historial(
        g.usuario_id, desde=desde, hasta=hasta, categoria_id=categoria_id, texto=q,
        limite=HISTORIAL_POR_PAGINA + 1, offset=offset,
    )
    hay_pagina_siguiente = len(filas) > HISTORIAL_POR_PAGINA
    filas = filas[:HISTORIAL_POR_PAGINA]
    preferencias_ia_local = db.obtener_preferencias_ia_local(g.usuario_id)
    ctx = {
        "filas": filas,
        "categorias": db.listar_categorias(g.usuario_id),
        "desde": desde or "",
        "hasta": hasta or "",
        "categoria_id": categoria_id or "",
        "q": q or "",
        "pagina": pagina,
        "hay_pagina_anterior": pagina > 1,
        "hay_pagina_siguiente": hay_pagina_siguiente,
        "proveedor_ia": preferencias_ia_local["proveedor_local"],
        "modelo_ia": preferencias_ia_local["modelo_local"],
        "prompt_ia": PROMPT_IA_POR_DEFECTO,
        "informe_texto": None,
        "informe_error": None,
    }
    ctx.update(extra)
    return ctx


@app.route("/historial")
@login_required
def historial():
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    categoria_id = request.args.get("categoria_id") or None
    categoria_id = int(categoria_id) if categoria_id else None
    q = request.args.get("q") or None
    pagina = request.args.get("pagina", 1, type=int)
    return render_template("historial.html", **_contexto_historial(desde, hasta, categoria_id, q=q, pagina=pagina))


@app.route("/export")
@login_required
def exportar():
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    categoria_id = request.args.get("categoria_id") or None
    categoria_id = int(categoria_id) if categoria_id else None
    formato = request.args.get("formato", "json")

    if formato == "csv":
        contenido = export.a_csv(g.usuario_id, desde, hasta, categoria_id)
        mimetype = "text/csv"
        nombre_archivo = "guilda_work_export.csv"
    elif formato == "md":
        contenido = export.a_markdown(g.usuario_id, desde, hasta, categoria_id)
        mimetype = "text/markdown"
        nombre_archivo = "guilda_work_resumen.md"
    else:
        contenido = export.a_json(g.usuario_id, desde, hasta, categoria_id)
        mimetype = "application/json"
        nombre_archivo = "guilda_work_export.json"

    return Response(
        contenido,
        mimetype=mimetype,
        headers={"Content-Disposition": f"attachment; filename={nombre_archivo}"},
    )


@app.route("/importar", methods=["GET"])
@login_required
def importar():
    return render_template("importar.html", resumen=None, error=None)


@app.route("/importar", methods=["POST"])
@login_required
def procesar_importacion():
    archivo = request.files.get("archivo")
    if archivo is None or not archivo.filename:
        return render_template("importar.html", resumen=None, error="Elige un archivo JSON o CSV exportado desde Guilda Work.")

    contenido = archivo.read().decode("utf-8", errors="replace")
    try:
        if archivo.filename.lower().endswith(".csv"):
            resumen = importador.importar_csv(g.usuario_id, contenido)
        else:
            resumen = importador.importar_json(g.usuario_id, contenido)
    except importador.ErrorImportacion as e:
        return render_template("importar.html", resumen=None, error=str(e))

    return render_template("importar.html", resumen=resumen, error=None)


@app.route("/informe-ia", methods=["POST"])
@login_required
def informe_ia():
    desde = request.form.get("desde") or None
    hasta = request.form.get("hasta") or None
    categoria_id = request.form.get("categoria_id") or None
    categoria_id = int(categoria_id) if categoria_id else None
    proveedor = request.form.get("proveedor", "ollama")
    modelo = request.form.get("modelo", "").strip()
    prompt = request.form.get("prompt", "").strip() or PROMPT_IA_POR_DEFECTO

    db.guardar_preferencias_ia_local(g.usuario_id, proveedor, modelo)

    datos = export.construir_export(g.usuario_id, desde, hasta, categoria_id)
    informe_texto = None
    informe_error = None
    try:
        informe_texto = ai_local.generar_informe(datos, prompt, proveedor, modelo, g.usuario_id)
    except ai_local.ErrorIALocal as e:
        informe_error = str(e)

    return render_template(
        "historial.html",
        **_contexto_historial(
            desde, hasta, categoria_id,
            proveedor_ia=proveedor, modelo_ia=modelo, prompt_ia=prompt,
            informe_texto=informe_texto, informe_error=informe_error,
        ),
    )


@app.route("/pregunta-ia", methods=["POST"])
@login_required
def pregunta_ia():
    """Modo "pregunta libre": chat con memoria contra los datos filtrados.

    Recibe y devuelve JSON (lo llama el JS del histórico por fetch), no HTML
    — el historial de la conversación lo guarda el navegador y lo reenvía en
    cada pregunta; el servidor no guarda nada de la conversación.
    """
    payload = request.get_json(silent=True) or {}
    desde = payload.get("desde") or None
    hasta = payload.get("hasta") or None
    categoria_id = payload.get("categoria_id") or None
    categoria_id = int(categoria_id) if categoria_id else None
    proveedor = payload.get("proveedor") or "ollama"
    modelo = str(payload.get("modelo") or "")
    pregunta = str(payload.get("pregunta") or "")

    historial_bruto = payload.get("historial") or []
    historial_mensajes = [
        {"role": m["role"], "content": m["content"]}
        for m in historial_bruto
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
    ]

    db.guardar_preferencias_ia_local(g.usuario_id, proveedor, modelo)

    datos = export.construir_export(g.usuario_id, desde, hasta, categoria_id)
    try:
        respuesta = ai_local.preguntar(datos, historial_mensajes, pregunta, proveedor, modelo, g.usuario_id)
        return {"ok": True, "respuesta": respuesta}
    except ai_local.ErrorIALocal as e:
        return {"ok": False, "error": str(e)}


@app.route("/busqueda/token", methods=["GET"])
@login_required
def token_busqueda():
    """Tenant token de Meilisearch para el buscador global (Ctrl/Cmd+K,
    ver app/static/busqueda.js) — el navegador llama a Meilisearch
    DIRECTAMENTE con este token (nunca a través de esta ruta), así que
    la clave maestra nunca sale del servidor. Corto de vida a propósito
    (ver app/busqueda.py:generar_token_busqueda) — el frontend pide uno
    nuevo cada vez que abre el buscador, no lo guarda entre sesiones.

    Fuera de /api/v1/* a propósito: esa ruta es la API por token Bearer
    de la app móvil (ver app/rutas_api.py), esta usa la cookie de sesión
    de la propia web — nunca se mezclan los dos mecanismos de auth en el
    mismo prefijo (mismo criterio que ya documenta rutas_api.py)."""
    try:
        token = busqueda.generar_token_busqueda(g.usuario_id)
    except busqueda.ErrorBusqueda as e:
        return {"ok": False, "error": str(e)}, 503
    return {"ok": True, "token": token, "url": busqueda.MEILISEARCH_URL, "indice": busqueda.INDICE}


@app.route("/busqueda/hibrida", methods=["GET"])
@login_required
def busqueda_hibrida():
    """Búsqueda semántica (RAG) — a diferencia de /busqueda/token, aquí
    el navegador NO habla con Meilisearch directamente: la búsqueda
    híbrida necesita calcular el embedding de la PREGUNTA con Ollama,
    solo alcanzable desde el servidor, así que esta ruta hace la
    llamada completa y devuelve los resultados ya filtrados por
    usuario (ver app/busqueda.py:buscar_hibrido, aislamiento verificado
    en vivo). Excepción deliberada al patrón "todo directo desde el
    navegador" de /busqueda/token — motivo documentado en HOSTING.md."""
    texto = request.args.get("q", "").strip()
    if not texto:
        return {"ok": True, "resultados": []}
    resultados = busqueda.buscar_hibrido(g.usuario_id, texto)
    return {"ok": True, "resultados": resultados}


@app.route("/herramientas", endpoint="herramientas")
@login_required
def herramientas_vista():
    # FacturaScripts no está en herramientas.HERRAMIENTAS porque no es una
    # instancia compartida con una URL fija como el resto del catálogo:
    # cada tenant tiene su propio contenedor, aprovisionado por
    # app/facturascripts.py:aprovisionar_tenant() al crear el tenant (ver
    # HOSTING.md 8.21). Se resuelve aquí, por tenant del usuario actual.
    tenant = db.tenant_de_usuario(g.usuario_id)
    facturascripts_url = tenant["facturascripts_url"] if tenant else None
    # Visibilidad por tenant (backoffice → detalle de tenant → Herramientas):
    # ausencia de fila en tenants_herramientas_ocultas = visible, así que un
    # usuario sin tenant asignado ve el catálogo completo sin filtrar.
    ocultas = db.herramientas_ocultas_de_tenant(tenant["id"]) if tenant else set()
    visibles = [h for h in herramientas.HERRAMIENTAS if h["id"] not in ocultas]
    return render_template(
        "herramientas.html",
        herramientas=visibles,
        facturascripts_url=facturascripts_url,
    )


@app.route("/mis-dispositivos")
@login_required
def mis_dispositivos():
    """Sesiones de la app móvil (tokens de app/rutas_api.py) — un usuario
    revoca aquí las suyas propias (p.ej. si pierde el móvil); un admin
    revoca además las de sus compañeros de tenant desde el backoffice (ver
    backoffice.dispositivos_tenant más abajo)."""
    return render_template("mis_dispositivos.html", dispositivos=db.listar_tokens_api(g.usuario_id))


@app.route("/mis-dispositivos/<int:token_id>/revocar", methods=["POST"])
@login_required
def revocar_dispositivo(token_id):
    db.revocar_token_api_por_id(g.usuario_id, token_id)
    return redirect(url_for("mis_dispositivos"))


@app.route("/ajustes/perfil", methods=["GET", "POST"])
@login_required
def ajustes_perfil():
    """Espacio de ajustes de usuario (Fase G1): nombre a mostrar, avatar y
    notificaciones -- a diferencia del dropdown "ajustes" de base.html
    (tema/idioma/densidad, ajustes de la APLICACIÓN), esto es el perfil
    del usuario en sí. Contraseña/email viven aparte en /ajustes/cuenta
    (flujo Kratos, no aplica a usuarios locales de escritorio)."""
    if request.method == "POST":
        db.guardar_perfil_usuario(
            g.usuario_id,
            nombre_mostrado=request.form.get("nombre_mostrado", ""),
            notificar_push_vencimientos="notificar_push_vencimientos" in request.form,
            notificar_push_tiquets="notificar_push_tiquets" in request.form,
            notificar_resumen_semanal="notificar_resumen_semanal" in request.form,
        )
        return redirect(url_for("ajustes_perfil"))
    usuario = db.obtener_usuario(g.usuario_id)
    return render_template(
        "ajustes_perfil.html",
        perfil=db.obtener_perfil_usuario(g.usuario_id),
        usuario=usuario,
        # Un usuario local (modo escritorio) nunca pasa por Kratos -- no
        # tiene contraseña/email que cambiar desde aquí (app/db.py:
        # es_local, ver _resolver_usuario_local).
        puede_cambiar_credenciales=not usuario["es_local"],
        # Sin flash() en este proyecto (ningún otro sitio lo usa) -- mismo
        # patrón que ya sigue /login con captcha_error: un parámetro de
        # query que la propia vista GET traduce a texto.
        error_avatar=request.args.get("error_avatar"),
    )


_AVATAR_TIPOS_PERMITIDOS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
_AVATAR_TAMANO_MAXIMO_BYTES = 5 * 1024 * 1024  # 5 MB, generoso para una foto de móvil sin comprimir


@app.route("/ajustes/perfil/avatar", methods=["POST"])
@login_required
def subir_avatar():
    fichero = request.files.get("avatar")
    if not fichero or not fichero.filename:
        return redirect(url_for("ajustes_perfil"))
    if fichero.mimetype not in _AVATAR_TIPOS_PERMITIDOS:
        return redirect(url_for("ajustes_perfil", error_avatar="formato"))
    datos = fichero.read(_AVATAR_TAMANO_MAXIMO_BYTES + 1)
    if len(datos) > _AVATAR_TAMANO_MAXIMO_BYTES:
        return redirect(url_for("ajustes_perfil", error_avatar="tamano"))
    try:
        # Recorte cuadrado centrado + redimensionado a 256×256 -- mismo
        # criterio de "componer con Pillow antes de guardar" ya usado para
        # el icono de la app móvil (ver mobile/assets/icon/), aplicado
        # aquí a algo subido por el usuario en vez de un asset del repo.
        from io import BytesIO

        from PIL import Image

        imagen = Image.open(BytesIO(datos))
        imagen = imagen.convert("RGB") if imagen.mode not in ("RGB", "RGBA") else imagen
        lado = min(imagen.size)
        izquierda = (imagen.width - lado) // 2
        arriba = (imagen.height - lado) // 2
        imagen = imagen.crop((izquierda, arriba, izquierda + lado, arriba + lado)).resize((256, 256))
        buffer = BytesIO()
        imagen.save(buffer, format="JPEG", quality=88)
        db.guardar_avatar_usuario(g.usuario_id, buffer.getvalue(), "image/jpeg")
    except Exception:
        return redirect(url_for("ajustes_perfil", error_avatar="procesar"))
    return redirect(url_for("ajustes_perfil"))


@app.route("/ajustes/perfil/avatar/eliminar", methods=["POST"])
@login_required
def eliminar_avatar():
    db.eliminar_avatar_usuario(g.usuario_id)
    return redirect(url_for("ajustes_perfil"))


@app.route("/avatar/<int:usuario_id>")
@login_required
def avatar_usuario(usuario_id: int):
    """Sirve el avatar subido, o 404 si no hay ninguno -- el llamador
    (plantilla) ya sabe caer al círculo de iniciales (avatar_color/
    iniciales, app/rutas_correo.py) cuando esta URL no responde 200,
    mismo patrón que usan hoy los avatares de contactos de correo."""
    perfil = db.obtener_perfil_usuario(usuario_id)
    if not perfil["avatar_contenido"]:
        abort(404)
    return Response(perfil["avatar_contenido"], mimetype=perfil["avatar_tipo_mime"])


@app.route("/ajustes/cuenta")
@login_required
def ajustes_cuenta():
    """Cambiar contraseña/email dentro de la app -- flujo `settings` de
    Kratos, quinto tipo (login/registration/verification/recovery ya
    estaban cableados, ver _flujo_o_redirigir). No aplica a usuarios
    locales de escritorio (es_local=1), que nunca pasan por Kratos."""
    if db.obtener_usuario(g.usuario_id)["es_local"]:
        abort(404)
    datos = _flujo_o_redirigir("settings")
    if datos is None:
        return g._redireccion_flujo
    return render_template("ajustes_cuenta.html", **datos)


@app.route("/estadisticas")
@login_required
def estadisticas():
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    return render_template(
        "estadisticas.html",
        desde=desde or "",
        hasta=hasta or "",
        por_categoria=db.estadisticas_por_categoria(g.usuario_id, desde, hasta),
        por_dia=db.estadisticas_por_dia(g.usuario_id, desde, hasta),
    )


@app.route("/captura")
@login_required
def captura():
    menus = db.listar_categorias(g.usuario_id)
    menu_id = request.args.get("menu")
    menu_id = int(menu_id) if menu_id and menu_id.isdigit() else (menus[0]["id"] if menus else None)
    return render_template("captura.html", menus=menus, menu_id=menu_id)


@app.route("/captura", methods=["POST"])
@login_required
def crear_captura():
    texto = request.form.get("texto", "").strip()
    categoria_id = request.form.get("categoria_id") or None
    if texto and categoria_id:
        db.crear_nota(g.usuario_id, texto, categoria_id=categoria_id)
    return {"ok": True}


@app.route("/papelera")
@login_required
def papelera():
    return render_template("papelera.html", items=db.papelera(g.usuario_id))


@app.route("/papelera/nota/<int:nota_id>/restaurar", methods=["POST"])
@login_required
def restaurar_nota(nota_id: int):
    db.restaurar_nota(g.usuario_id, nota_id)
    return redirect(url_for("papelera"))


@app.route("/papelera/nota/<int:nota_id>/eliminar-definitivamente", methods=["POST"])
@login_required
def eliminar_nota_definitivamente(nota_id: int):
    db.eliminar_nota_definitivamente(g.usuario_id, nota_id)
    return redirect(url_for("papelera"))


@app.route("/papelera/tarea/<int:tarea_id>/restaurar", methods=["POST"])
@login_required
def restaurar_tarea(tarea_id: int):
    db.restaurar_tarea(g.usuario_id, tarea_id)
    return redirect(url_for("papelera"))


@app.route("/papelera/tarea/<int:tarea_id>/eliminar-definitivamente", methods=["POST"])
@login_required
def eliminar_tarea_definitivamente(tarea_id: int):
    db.eliminar_tarea_definitivamente(g.usuario_id, tarea_id)
    return redirect(url_for("papelera"))


@app.route("/papelera/menu/<int:menu_id>/restaurar", methods=["POST"])
@login_required
def restaurar_menu(menu_id: int):
    db.restaurar_categoria(g.usuario_id, menu_id)
    return redirect(url_for("papelera"))


@app.route("/papelera/menu/<int:menu_id>/eliminar-definitivamente", methods=["POST"])
@login_required
def eliminar_menu_definitivamente(menu_id: int):
    db.eliminar_categoria_definitivamente(g.usuario_id, menu_id)
    return redirect(url_for("papelera"))


@app.route("/papelera/vaciar", methods=["POST"])
@login_required
def vaciar_papelera():
    db.vaciar_papelera_antigua(dias=0, usuario_id=g.usuario_id)
    return redirect(url_for("papelera"))


@app.route("/apagar", methods=["POST"])
@login_required
def apagar():
    """Cierra el servidor y termina el proceso por completo (evita procesos zombis).

    Todo lo que ya se ha guardado (notas, tareas, menús) está en SQLite con
    commit inmediato en cada operación, así que no hay nada "pendiente" que
    perder al cerrar: no hace falta guardar nada aquí, solo terminar el proceso.

    Solo tiene sentido en modo escritorio (un único proceso local de una
    sola persona) -- en modo hospedado apagaría el servicio para TODOS los
    tenants a la vez. Antes de este chequeo, la ruta no tenía ningún
    control de acceso: cualquiera sin sesión podía apagar el servicio
    entero con un POST a /apagar (encontrado en producción, corregido
    junto con esto)."""
    if not MODO_ESCRITORIO:
        abort(404)

    def _cerrar_proceso():
        time.sleep(0.6)  # da tiempo a que la respuesta llegue a la ventana
        os._exit(0)

    threading.Thread(target=_cerrar_proceso, daemon=True).start()
    return render_template("cerrado.html")


def _servidor_listo(host: str, port: int, timeout: float = 8.0) -> bool:
    """Espera a que el servidor Flask acepte conexiones antes de abrir la ventana."""
    fin = time.time() + timeout
    while time.time() < fin:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def _iniciar_servidor():
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)


# --- Ventana principal, bandeja del sistema y captura rápida ---------------
# Estado global sencillo: solo hay un proceso y una ventana principal, así
# que no hace falta nada más elaborado que unas variables de módulo.
_ventana_principal = None
_icono_bandeja = None
_ventana_captura = None


class _AppAPI:
    """Puente JS↔Python expuesto a las ventanas (window.pywebview.api.*)."""

    def abrir_captura(self):
        _abrir_captura()

    def cerrar_captura(self):
        _cerrar_captura()


def _abrir_captura():
    global _ventana_captura
    if _ventana_captura is not None:
        try:
            _ventana_captura.show()
            return
        except Exception:
            _ventana_captura = None
    _ventana_captura = webview.create_window(
        "Captura rápida — Guilda Work",
        f"http://{HOST}:{PORT}/captura",
        width=440,
        height=170,
        frameless=True,
        easy_drag=True,
        on_top=True,
        js_api=_AppAPI(),
    )

    def _al_cerrar_captura():
        global _ventana_captura
        _ventana_captura = None

    _ventana_captura.events.closed += _al_cerrar_captura


def _cerrar_captura():
    global _ventana_captura
    if _ventana_captura is not None:
        try:
            _ventana_captura.destroy()
        except Exception:
            pass
        _ventana_captura = None


def _mostrar_ventana_principal(icon=None, item=None):
    if _ventana_principal is not None:
        _ventana_principal.show()


def _salir_completamente(icon=None, item=None):
    if _icono_bandeja is not None:
        try:
            _icono_bandeja.stop()
        except Exception:
            pass
    os._exit(0)


def _al_intentar_cerrar_principal():
    """Si hay bandeja del sistema, ocultar en vez de cerrar; si no, cerrar de verdad."""
    if _icono_bandeja is not None:
        _ventana_principal.hide()
        return False
    return True


def _crear_icono_bandeja():
    """Icono en la bandeja del sistema. Si falla (entorno sin soporte), la app
    sigue funcionando con el comportamiento normal de cerrar al pulsar la X."""
    global _icono_bandeja
    try:
        import pystray
        from PIL import Image

        imagen = Image.open(BASE_DIR / "static" / "logo.png")
        menu = pystray.Menu(
            pystray.MenuItem("Abrir Guilda Work", _mostrar_ventana_principal, default=True),
            pystray.MenuItem("Captura rápida", lambda icon, item: _abrir_captura()),
            pystray.MenuItem("Cerrar", _salir_completamente),
        )
        _icono_bandeja = pystray.Icon("guilda_work", imagen, "Guilda Work", menu)
        _icono_bandeja.run_detached()
    except Exception:
        _icono_bandeja = None


def _registrar_atajo_global():
    """Atajo global (funciona con la ventana minimizada/en segundo plano).

    Si la librería no puede engancharse al teclado (permisos, entorno sin
    soporte...), la app sigue funcionando sin este atajo.
    """
    try:
        import keyboard

        keyboard.add_hotkey(ATAJO_CAPTURA, _abrir_captura)
    except Exception:
        pass


SINCRONIZACION_CORREO_INTERVALO_MINUTOS = 10


def _sincronizacion_correo_periodica():
    """Cada SINCRONIZACION_CORREO_INTERVALO_MINUTOS, sincroniza todas las
    cuentas de correo configuradas, para que el badge de "correo nuevo" de
    la barra lateral refleje mensajes recién llegados sin tener que pulsar
    "Sincronizar" a mano. Cada cuenta se sincroniza en su propio try/except:
    una cuenta con credenciales caducadas o sin red no debe impedir que se
    sincronicen las demás, ni tumbar este hilo. En modo escritorio solo hay
    un usuario real, así que se recorren las cuentas de todos los usuarios
    (en la práctica, solo el local) sin distinción."""
    while True:
        time.sleep(SINCRONIZACION_CORREO_INTERVALO_MINUTOS * 60)
        try:
            usuario_id = db.usuario_local_id()
            cuentas = db.listar_cuentas_correo(usuario_id)
        except Exception:
            continue
        for cuenta in cuentas:
            try:
                correo.sincronizar_bandeja(cuenta["id"])
            except Exception:
                pass  # un fallo de esta cuenta no debe impedir sincronizar las demás


RECORDATORIO_VENCIMIENTOS_INTERVALO_MINUTOS = 24 * 60
RECORDATORIO_VENCIMIENTOS_DIAS_ANTELACION = 7


def _recordatorio_vencimientos_fiscales():
    """Una vez al día, avisa por push a quien tenga asignado un vencimiento
    fiscal que vence dentro de RECORDATORIO_VENCIMIENTOS_DIAS_ANTELACION
    días. Mismo criterio defensivo que el resto de hilos periódicos: un
    fallo puntual (BD bloqueada, push mal configurado...) no debe tumbar
    el hilo, se reintenta en la siguiente vuelta.

    A diferencia de _sincronizacion_correo_periodica/_recordatorio_periodico
    (solo arrancan en main(), modo escritorio), este hilo se arranca TAMBIÉN
    desde serve.py -- los vencimientos fiscales son multi-tenant, tiene que
    funcionar en el despliegue real, no solo en la app de escritorio."""
    while True:
        time.sleep(RECORDATORIO_VENCIMIENTOS_INTERVALO_MINUTOS * 60)
        try:
            proximos = db.vencimientos_fiscales_proximos(dias=RECORDATORIO_VENCIMIENTOS_DIAS_ANTELACION)
        except Exception:
            continue
        for v in proximos:
            if not v["usuario_id"]:
                continue
            try:
                push.enviar_a_usuario(
                    v["usuario_id"],
                    "Vencimiento fiscal próximo",
                    f"{v['modelo']} de {v['cliente_nombre']} vence el {v['fecha_limite'][:10]}.",
                    {"tipo": "vencimiento_fiscal", "vencimiento_id": v["id"]},
                )
                # Dedup: sin esto, vencimientos_fiscales_proximos() lo
                # volvía a devolver cada día mientras siguiera pendiente y
                # dentro de la ventana, reenviando el mismo aviso hasta
                # RECORDATORIO_VENCIMIENTOS_DIAS_ANTELACION veces.
                db.marcar_recordatorio_vencimiento_fiscal_enviado(v["id"])
            except Exception:
                pass


RECORDATORIO_INTERVALO_MINUTOS = 60


def _recordatorio_periodico():
    """Cada RECORDATORIO_INTERVALO_MINUTOS, si no ha habido ninguna nota ni
    tarea nueva en ese rato, envía un aviso a la bandeja recordando anotar.
    No es un temporizador rígido: si ya estás anotando cosas, no molesta.
    """
    while True:
        time.sleep(RECORDATORIO_INTERVALO_MINUTOS * 60)
        if _icono_bandeja is None:
            continue
        try:
            usuario_id = db.usuario_local_id()
            if not db.hubo_actividad_reciente(usuario_id, RECORDATORIO_INTERVALO_MINUTOS):
                _icono_bandeja.notify(
                    "¿Qué has hecho en la última hora? Ctrl+Alt+G lo anota en dos segundos.",
                    "Guilda Work",
                )
        except Exception:
            pass  # un fallo del recordatorio no debe tumbar el hilo ni la app


def main():
    global _ventana_principal, MODO_ESCRITORIO
    MODO_ESCRITORIO = True
    db.init_db()
    try:
        db.hacer_backup_si_hace_falta()
    except Exception:
        pass  # una copia de seguridad fallida no debe impedir arrancar la app
    try:
        db.vaciar_papelera_antigua()
    except Exception:
        pass  # idem para la purga automática de la papelera
    try:
        export.generar_resumen_automatico_si_hace_falta()
    except Exception:
        pass  # idem para el resumen automático de ayer
    threading.Thread(target=_iniciar_servidor, daemon=True).start()
    _servidor_listo(HOST, PORT)

    _ventana_principal = webview.create_window(
        "Guilda Work",
        f"http://{HOST}:{PORT}/",
        width=1280,
        height=860,
        min_size=(960, 640),
        js_api=_AppAPI(),
    )
    _ventana_principal.events.closing += _al_intentar_cerrar_principal

    _crear_icono_bandeja()
    _registrar_atajo_global()
    threading.Thread(target=_recordatorio_periodico, daemon=True).start()
    threading.Thread(target=_sincronizacion_correo_periodica, daemon=True).start()
    threading.Thread(target=_recordatorio_vencimientos_fiscales, daemon=True).start()

    webview.start()

    # Solo se llega aquí si no hay bandeja (o algo la desactivó) y se cerró
    # la ventana principal de verdad: terminamos el proceso por completo
    # para no dejar el servidor de fondo corriendo (evita procesos zombis).
    os._exit(0)


if __name__ == "__main__":
    main()
