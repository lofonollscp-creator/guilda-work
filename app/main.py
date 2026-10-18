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
import json
import logging
import os
import secrets
import socket
import sqlite3
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

import sentry_sdk
import webview
from flask import Flask, Response, abort, g, jsonify, make_response, redirect, render_template, request, session, url_for
from flask_babel import Babel, format_date, format_datetime, get_locale
from flask_babel import gettext as _
from flask_babel import ngettext
from sentry_sdk.integrations.flask import FlaskIntegration
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from .notas_formato import nota_a_html
from . import ai_local, ayuda, busqueda, seguridad_csp, captcha, comunicados, correo, mantenimiento, onboarding_despacho, ver_como, db, export, generador_documentos, herramientas, verticales, fichaje_avisos, recordatorios_tareas, ia_asistente, ia_atajos, importador, kratos, notificaciones, peticion, portal_recordatorios, proyecto_plantillas, salud
from .auth import limiter, login_required
from .rutas_api import api_bp
from . import rutas_api_ampliada, rutas_api_control_fiscal, rutas_api_documentos, rutas_api_extras, rutas_api_fiscal, rutas_api_tareas, rutas_api_verticales  # noqa: F401 -- registran más rutas en api_bp
from .rutas_proyectos import proyectos_bp
from .rutas_backoffice import backoffice_bp
from .rutas_facturacion_proxy import FACTURACION_ORIGIN, facturacion_proxy_bp
from .rutas_stripe_webhook import stripe_webhook_bp
from .rutas_citas import citas_bp
from .rutas_videollamadas import videollamadas_bp
from .rutas_correo import correo_bp
from .rutas_docs import docs_bp
from .rutas_fichaje import fichaje_bp
from .rutas_fiscal import fiscal_bp
from .rutas_certificados import certificados_bp
from .rutas_control_fiscal import control_fiscal_bp
from .rutas_hydra import hydra_bp
from .rutas_ia import ia_bp
from .rutas_kratos_proxy import ip_requiere_captcha, kratos_proxy_bp
from .rutas_notificaciones import notificaciones_bp
from .rutas_portal_cliente import portal_bp
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
# Límite global de tamaño de petición (bug encontrado en la auditoría de
# 2026-10-01): sin esto, un endpoint sin su propio chequeo explícito de
# tamaño (p.ej. /api/correo/enviar, que decodifica adjuntos en base64
# desde un cuerpo JSON) podía agotar memoria con peticiones grandes
# repetidas. 32MB da margen de sobra sobre el límite más alto ya
# existente en la app (25MB para adjuntos que manda el asistente IA,
# ver mcp_tools.TAMANO_MAXIMO_ADJUNTO_ASISTENTE_BYTES) más el overhead
# de multipart/base64. Flask convierte un cuerpo más grande en un 413
# automático (RequestEntityTooLarge, ya es una HTTPException -- el
# manejador de errores de más abajo la deja pasar tal cual).
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
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
app.add_template_filter(nota_a_html, "nota_html")
app.add_template_filter(lambda valor: json.loads(valor) if valor else [], "fromjson")
app.add_template_filter(lambda d: format_date(d, "EEEEE").upper(), "dia_inicial")


def _fecha_hora(valor, solo_fecha=False):
    """«11 oct 2026, 20:43» (o «11 oct 2026») en el idioma del usuario, a partir de una fecha ISO («2026-10-11T20:43:13»).
    Si no es una fecha válida devuelve el texto tal cual: nunca rompe una pantalla por un dato raro."""
    if not valor:
        return ""
    try:
        momento = datetime.fromisoformat(str(valor).strip().replace(" ", "T", 1))
    except ValueError:
        return str(valor)
    return format_date(momento.date(), "d MMM y") if solo_fecha or len(str(valor).strip()) <= 10 else format_datetime(momento, "d MMM y, HH:mm")


app.add_template_filter(_fecha_hora, "fecha_y_hora")
app.add_template_filter(lambda valor: _fecha_hora(valor, solo_fecha=True), "fecha_dia")


def _msg_kratos(mensaje) -> str:
    """Texto de un mensaje o etiqueta de Kratos (que llegan en inglés) en el idioma de la persona. Se reconocen por el principio del texto
    inglés (no por el id numérico: las variables, como los minutos que lleva caducado un flujo, no cambian el principio); si no se
    reconoce, se muestra tal cual lo manda Kratos."""
    texto = (mensaje.get("text") if isinstance(mensaje, dict) else str(mensaje or "")) or ""
    conocidos = (
        ("An email containing a recovery code has been sent", _("Si ese email tiene una cuenta, te hemos mandado un código de recuperación. Revisa tu bandeja de entrada (y el correo no deseado).")),
        ("An email containing a verification code has been sent", _("Te hemos mandado un código de verificación. Revisa tu bandeja de entrada (y el correo no deseado).")),
        ("The recovery code is invalid or has already been used", _("El código de recuperación no es válido o ya se ha usado. Pide uno nuevo.")),
        ("The verification code is invalid or has already been used", _("El código de verificación no es válido o ya se ha usado. Pide uno nuevo.")),
        ("The recovery flow expired", _("Ha pasado demasiado tiempo. Empieza de nuevo la recuperación de la contraseña.")),
        ("The verification flow expired", _("Ha pasado demasiado tiempo. Vuelve a pedir la verificación.")),
        ("You successfully recovered your account", _("Cuenta recuperada. Elige ahora una contraseña nueva.")),
        ("Your changes have been saved", _("Cambios guardados.")),
        ("The provided credentials are invalid", _("El email o la contraseña no son correctos.")),
        ("Recovery code", _("Código de recuperación")),
        ("Verification code", _("Código de verificación")),
        ("Resend code", _("Reenviar el código")),
        ("Continue", _("Continuar")),
        ("Submit", _("Enviar")),
        ("Password", _("Contraseña")),
    )
    for ingles, traducido in conocidos:
        if texto == ingles or (len(ingles) > 20 and texto.startswith(ingles)):
            return traducido
    return texto


app.add_template_filter(_msg_kratos, "msg_kratos")


def _comentario_html(texto, mencionados=()):
    """Escapa el comentario, resalta las @menciones y respeta los saltos de línea."""
    import re

    from markupsafe import Markup, escape

    html = str(escape(texto or ""))
    for nombre in sorted(mencionados or (), key=len, reverse=True):
        marca = "@" + str(escape(nombre))
        html = re.sub(re.escape(marca), lambda m: f'<span class="mencion">{m.group(0)}</span>', html, flags=re.IGNORECASE)
    return Markup(html.replace("\n", "<br>"))


app.add_template_filter(_comentario_html, "comentario_html")
from .rutas_abogados import abogados_bp, asunto_bp  # noqa: E402
from .rutas_inmobiliaria import inmobiliaria_bp, propietario_bp  # noqa: E402
from .rutas_seguridad import seguridad_bp  # noqa: E402
from .rutas_nucleo import clientes_bp, expedientes_bp, plazos_bp, tiempo_bp  # noqa: E402
from .rutas_importar_clientes import importar_clientes_bp  # noqa: E402
app.register_blueprint(abogados_bp)
app.register_blueprint(inmobiliaria_bp)
app.register_blueprint(seguridad_bp)
app.register_blueprint(propietario_bp)
app.register_blueprint(asunto_bp)
app.register_blueprint(clientes_bp)
app.register_blueprint(importar_clientes_bp)
app.register_blueprint(expedientes_bp)
app.register_blueprint(plazos_bp)
app.register_blueprint(tiempo_bp)
app.register_blueprint(tareas_bp)
app.register_blueprint(proyectos_bp)
app.register_blueprint(tiquets_bp)
app.register_blueprint(fichaje_bp)
app.register_blueprint(fiscal_bp)
app.register_blueprint(certificados_bp)
app.register_blueprint(control_fiscal_bp)
app.register_blueprint(citas_bp)
app.register_blueprint(videollamadas_bp)
app.register_blueprint(correo_bp)
from .rutas_contactos import contactos_bp  # noqa: E402
app.register_blueprint(contactos_bp)
from .rutas_marca import marca_bp  # noqa: E402
app.register_blueprint(marca_bp)
app.register_blueprint(ia_bp)
app.register_blueprint(api_bp)
app.register_blueprint(kratos_proxy_bp)
app.register_blueprint(hydra_bp)
app.register_blueprint(backoffice_bp)
app.register_blueprint(facturacion_proxy_bp)
app.register_blueprint(stripe_webhook_bp)
app.register_blueprint(docs_bp)
app.register_blueprint(portal_bp)
app.register_blueprint(notificaciones_bp)


@app.errorhandler(Exception)
def _registrar_excepcion_no_controlada(error):
    # Las HTTPException (404, 403, la propia abort(...) de las rutas...) no
    # son errores de programación -- se dejan pasar tal cual para que Flask
    # las convierta en su respuesta normal, sin registrarlas como fallo.
    if isinstance(error, HTTPException):
        if request.path.startswith("/api/") and error.code:
            # 404/405 de enrutado (antes de entrar en el blueprint): también JSON uniforme, nunca HTML, para la API.
            from .rutas_api import _codigo_de
            return jsonify(ok=False, error=error.description, codigo=_codigo_de(error.code), request_id=peticion.id_actual()), error.code
        return error
    logger.exception("Excepción no controlada en %s %s [req %s]", request.method, request.path, peticion.id_actual())
    sentry_sdk.capture_exception(error)
    return (jsonify(ok=False, error=_("Ha ocurrido un error interno. Se ha registrado para revisión."), codigo="error_interno", request_id=peticion.id_actual()), 500) if request.path.startswith("/api/") else (
        _("Ha ocurrido un error interno. Se ha registrado para revisión."),
        500,
    )


@app.before_request
def _id_de_peticion():
    rid = peticion.asignar_id()
    sentry_sdk.set_tag("request_id", rid)


@app.after_request
def _cabecera_id_de_peticion(respuesta):
    rid = peticion.id_actual()
    if rid:
        respuesta.headers["X-Request-Id"] = rid
    if respuesta.status_code >= 500:
        try:  # el registro de errores nunca debe empeorar la respuesta que ya es un error
            plantilla = request.url_rule.rule if request.url_rule else request.path.split("?")[0]
            db.registrar_error_servidor(request.method, plantilla, respuesta.status_code, rid)
        except Exception:  # noqa: BLE001
            logger.warning("No se pudo anotar el error 5xx en errores_servidor", exc_info=True)
    return respuesta


@app.before_request
def _nonce_de_csp():
    g.csp_nonce = seguridad_csp.nuevo_nonce()


@app.context_processor
def inyectar_nonce_de_csp():
    return {"csp_nonce": g.get("csp_nonce", "")}


@app.route("/csp-report", methods=["POST"])
@limiter.limit("30 per minute")
def informe_de_csp():
    """Recoge los avisos del navegador sobre lo que la CSP bloquearía/bloquea. Sin autenticación (el navegador no manda cookies de
    sesión aquí de forma fiable), limitado por IP y solo escribe una línea corta en el registro."""
    cuerpo = request.get_json(silent=True, force=True) if request.content_length and request.content_length < 8192 else None
    logger.warning("CSP: %s", seguridad_csp.resumir_informe(cuerpo if isinstance(cuerpo, dict) else None))
    return "", 204


@app.after_request
def _cabeceras_de_seguridad(respuesta):
    """Cabeceras que impiden que otra web meta esta en un iframe (clickjacking) o que el navegador adivine tipos. Sin una CSP
    estricta de scripts a propósito: la app usa scripts en línea y exigiría nonces. HSTS solo detrás de HTTPS (Caddy manda
    X-Forwarded-Proto) y sin includeSubDomains, para no afectar a los demás subdominios."""
    cabeceras = respuesta.headers
    cabeceras.setdefault("X-Content-Type-Options", "nosniff")
    cabeceras.setdefault("X-Frame-Options", "SAMEORIGIN")
    cabeceras.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    nonce = g.get("csp_nonce")
    forma = seguridad_csp.modo()
    if nonce and forma != "no":
        cabecera = "Content-Security-Policy" if forma == "forzar" else "Content-Security-Policy-Report-Only"
        cabeceras.setdefault(cabecera, seguridad_csp.politica(nonce, con_informe=forma == "reportar"))
    # Lo que se hace cumplir SIEMPRE, también en modo informe (no puede romper nada): sin marcos ajenos, sin plugins, sin <base> ajeno.
    cabeceras.setdefault("Content-Security-Policy", "frame-ancestors 'self'; object-src 'none'; base-uri 'self'")
    if request.headers.get("X-Forwarded-Proto") == "https":
        cabeceras.setdefault("Strict-Transport-Security", "max-age=31536000")
    return respuesta


KRATOS_SESSION_COOKIE = "ory_kratos_session"


@app.before_request
def _resolver_usuario_actual():
    # Modo escritorio (GuildaWork.exe): un único usuario local de confianza,
    # sin pantalla de login real — no pasa por Kratos en absoluto (Fase 7a).
    g.ver_como = None
    if MODO_ESCRITORIO:
        if "usuario_id" not in session:
            session["usuario_id"] = db.usuario_local_id()
        g.usuario_id = session.get("usuario_id")
        g.es_admin = db.es_admin(g.usuario_id)
        tenant = db.tenant_de_usuario(g.usuario_id)
        g.tenant_id = tenant["id"] if tenant else None
        g.gestor_fichajes = db.es_gestor_fichajes(g.usuario_id)
        g.supervisor_tenant = db.es_supervisor_tenant(g.usuario_id)
        return

    # Modo hospedado: identidad real vía Ory Kratos. Solo se llama a Kratos
    # si hay cookie de sesión de Kratos en la petición — evita una llamada
    # HTTP en cada visita anónima (página de login, assets, etc.).
    g.usuario_id = None
    g.es_admin = False
    g.tenant_id = None
    g.gestor_fichajes = False
    g.supervisor_tenant = False
    g.custodio_certificados = False
    # «Ver como» (soporte, solo lectura): la sesión de suplantación sustituye a la de Kratos.
    g.ver_como = None
    ver = session.get("ver_como")
    if ver:
        suplantado = db.obtener_usuario(ver["usuario_id"]) if ver_como.sesion_valida(ver) else None
        if suplantado is None or suplantado["rol"] == "admin":
            session.pop("ver_como", None)
        else:
            g.usuario_id, g.es_admin, g.tenant_id = suplantado["id"], False, suplantado["tenant_id"]
            g.gestor_fichajes, g.supervisor_tenant = bool(suplantado["gestor_fichajes"]), bool(suplantado["supervisor_tenant"])
            g.ver_como = ver
            return
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
        try:
            g.usuario_id = db.crear_usuario_vinculado_a_kratos(email, identity_id)
        except sqlite3.IntegrityError:
            # Dos peticiones casi simultáneas de la misma identidad recién
            # registrada (dos pestañas, doble clic, red lenta) -- la otra ya
            # ganó la carrera (kratos_identity_id es UNIQUE en `usuarios`),
            # se reutiliza su fila en vez de dejar que el IntegrityError
            # llegue sin capturar hasta el manejador de errores genérico.
            usuario = db.usuario_por_kratos_id(identity_id)
            g.usuario_id = usuario["id"]
            g.es_admin = usuario["rol"] == "admin"
            g.tenant_id = usuario["tenant_id"]
            g.gestor_fichajes = bool(usuario["gestor_fichajes"])
            g.supervisor_tenant = bool(usuario["supervisor_tenant"])
            g.custodio_certificados = bool(usuario["custodio_certificados"])
    else:
        g.usuario_id = usuario["id"]
        g.es_admin = usuario["rol"] == "admin"
        g.tenant_id = usuario["tenant_id"]
        g.gestor_fichajes = bool(usuario["gestor_fichajes"])
        g.supervisor_tenant = bool(usuario["supervisor_tenant"])
        g.custodio_certificados = bool(usuario["custodio_certificados"])
        g.apariencia = {"tema": usuario["tema"], "densidad": usuario["densidad"]}      # ya está en la fila leída: sin consulta extra
        if request.endpoint != "static":
            db.registrar_acceso(usuario["id"])


_RUTAS_ABIERTAS_EN_MANTENIMIENTO = ("/static/", "/.ory/", "/webhooks/", "/soporte/ver-como", "/login", "/logout", "/idioma/")


@app.before_request
def _ver_como_solo_lectura():
    if g.get("ver_como") and request.method not in ("GET", "HEAD", "OPTIONS") and request.endpoint != "salir_ver_como":
        mensaje = _("Estás en modo «ver como»: solo lectura. No se puede modificar nada.")
        return (jsonify(error=mensaje), 403) if request.path.startswith("/api/") else (mensaje, 403)


@app.before_request
def _modo_mantenimiento():
    """Cierre de la plataforma (o de un despacho) decidido en el backoffice. Los administradores globales y el
    «ver como» pasan; también el login, el proxy de Kratos y los webhooks entrantes."""
    if MODO_ESCRITORIO or g.get("es_admin") or g.get("ver_como") or request.path.startswith(_RUTAS_ABIERTAS_EN_MANTENIMIENTO):
        return
    try:
        cierre = mantenimiento.vigente_para(g.get("tenant_id"))
    except Exception:
        return  # una avería aquí nunca debe tumbar la plataforma
    if not cierre:
        return
    texto = cierre["mensaje"] or _("Estamos realizando tareas de mantenimiento. Volveremos en unos minutos.")
    if request.path.startswith("/api/"):
        resp = jsonify(error=texto, mantenimiento=True)
        resp.status_code = 503
    else:
        resp = make_response(render_template("mantenimiento.html", mensaje=texto, hasta=cierre["hasta"]), 503)
    resp.headers["Retry-After"] = "300"
    return resp


@app.route("/soporte/ver-como/<token>")
def entrar_ver_como(token: str):
    datos = ver_como.canjear(token)
    if datos is None:
        abort(404)
    session["ver_como"] = datos
    db.registrar_auditoria(None, "ver_como.inicio", f"{datos['admin']} entra como usuario {datos['usuario_id']} ({datos['email']})")
    return redirect(url_for("inicio"))


@app.route("/soporte/ver-como/salir", methods=["POST"])
def salir_ver_como():
    ver = session.pop("ver_como", None)
    if ver:
        db.registrar_auditoria(None, "ver_como.fin", f"{ver.get('admin')} sale de usuario {ver.get('usuario_id')}")
    return redirect(os.environ.get("GUILDA_BACKOFFICE_URL", "https://backoffice.guildawork.com"))


@app.context_processor
def inyectar_ayuda_contextual():
    url, especifica = ayuda.url_de(request.endpoint, str(get_locale() or "es")[:2])
    return {"ayuda_url": url, "ayuda_especifica": especifica}


@app.context_processor
def inyectar_verticales():
    """Módulos de negocio activos del despacho (Gestoría, Gabinete de abogados, Inmobiliaria): base.html monta el menú con ellos."""
    activos = verticales.activos_de(g.get("tenant_id"))
    return {"verticales_activos": activos, "entradas_verticales": verticales.entradas_de_menu(g.get("tenant_id"))}


@app.context_processor
def inyectar_marca():
    """Marca del despacho (nombre, logo y color propios) para el menú lateral y la hoja de estilo; None si no la ha personalizado o no hay sesión."""
    if g.get("usuario_id") is None:
        return {"marca_despacho": None}
    from . import marca
    return {"marca_despacho": marca.obtener(g.get("tenant_id"))}


@app.context_processor
def inyectar_ver_como():
    return {"ver_como_activo": g.get("ver_como")}


_URL_ESTATICA: dict[str, tuple[float, str]] = {}


@app.context_processor
def inyectar_url_for_versionado():
    # Caddy sirve /static/* con "Cache-Control: public, max-age=604800"
    # (deploy/Caddyfile) -- 7 días de caché de navegador para que los
    # estáticos no viajen en cada petición. Pero la URL nunca cambiaba
    # entre despliegues, así que un usuario con la web ya abierta (o
    # cualquier caché intermedia) seguía sirviendo el style.css/iconos.svg
    # VIEJO hasta que esos 7 días expiraran -- el HTML nuevo llegaba, el
    # CSS no, y el cambio parecía "no aplicado" aunque el despliegue
    # hubiera ido bien. Se soluciona añadiendo ?v=<mtime del fichero> a
    # cada url_for('static', ...) generada desde una plantilla: cada
    # despliegue cambia el mtime -> cambia la URL -> la caché de 7 días
    # ya no puede servir el estático antiguo bajo la URL nueva. Sobrescribe
    # el propio nombre `url_for` visible en Jinja (patrón estándar de
    # Flask), no toca las llamadas Python a flask.url_for.
    def url_for_versionado(endpoint, **values):
        if endpoint == "static" and "filename" in values and "v" not in values:
            # Una fila de tarea pinta ~8 iconos y cada url_for hacía un stat() del fichero
            # más construir la URL (3.400 por página en "Mi día"): se recuerda 30 s por fichero.
            if set(values) == {"filename"}:
                guardada = _URL_ESTATICA.get(values["filename"])
                if guardada and time.monotonic() - guardada[0] < 30:
                    return guardada[1]
            ruta = os.path.join(app.static_folder, values["filename"])
            try:
                values["v"] = int(os.path.getmtime(ruta))
            except OSError:
                pass
            url = url_for(endpoint, **values)
            if set(values) <= {"filename", "v"}:
                _URL_ESTATICA[values["filename"]] = (time.monotonic(), url)
            return url
        return url_for(endpoint, **values)

    return {"url_for": url_for_versionado}


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
    # badge sobre el icono de Correo). La lista de proyectos ya no vive en un
    # sidebar global — cada ruta que la necesita (inicio(), captura()) la
    # pasa explícitamente en su propio contexto.
    if not g.usuario_id:
        return {}
    por_cuenta = peticion.memo("no_leidos", lambda: db.contar_no_leidos_por_cuenta_y_carpeta(g.usuario_id))
    return {"correo_no_leidos_sidebar": sum(sum(c.values()) for c in por_cuenta.values())}


@app.context_processor
def inyectar_comunicados():
    """Banner de comunicados publicados desde el backoffice; nunca debe romper una página."""
    if not g.usuario_id:
        return {}
    try:
        return {"comunicados_activos": peticion.memo("comunicados", lambda: comunicados.activos_para(g.usuario_id, g.tenant_id))}
    except Exception:
        return {}


@app.route("/comunicados/<int:comunicado_id>/cerrar", methods=["POST"])
@login_required
def cerrar_comunicado(comunicado_id: int):
    comunicados.cerrar(g.usuario_id, comunicado_id)
    destino = request.referrer or ""
    mismo_sitio = urllib.parse.urlparse(destino).netloc in ("", request.host)
    return redirect(destino if destino and mismo_sitio else url_for("inicio"))


@app.context_processor
def inyectar_notificaciones_badge():
    if not g.usuario_id:
        return {}
    return {"notificaciones_no_leidas": db.contar_notificaciones_no_leidas(g.usuario_id)}


@app.context_processor
def inyectar_chip_jornada():
    """Estado de la jornada para el chip de la barra superior (base.html):
    'dentro' o 'en_pausa' con la hora de la entrada; None si el usuario no
    ha fichado hoy, no ha completado sus datos de fichaje o algo falla (el
    chip es solo un atajo, nunca debe romper una página)."""
    if not g.usuario_id:
        return {}
    try:
        if not db.fichaje_datos_completos(g.usuario_id):
            return {"chip_jornada": None}
        estado = db.estado_actual_fichaje(g.usuario_id)
        if estado not in ("dentro", "en_pausa"):
            return {"chip_jornada": None}
        entrada = db.entrada_abierta_fichaje(g.usuario_id)
        return {"chip_jornada": {"estado": estado, "desde": entrada[11:16] if entrada else None, "desde_iso": entrada}}
    except Exception:
        return {"chip_jornada": None}


@app.context_processor
def inyectar_barra_superior():
    """Datos de la barra superior (base.html): fecha, pendientes de "Mi día",
    cronómetro de tarea en curso. Es un atajo informativo: si algo falla la
    barra se queda sin ese dato, nunca rompe la página."""
    if not g.usuario_id:
        return {}
    from zoneinfo import ZoneInfo

    tenant = peticion.memo("tenant", lambda: db.obtener_tenant(g.tenant_id) if g.tenant_id else None)
    zona = tenant["zona_horaria"] if tenant and tenant["zona_horaria"] and db.zona_horaria_valida(tenant["zona_horaria"]) else db.ZONA_HORARIA_DEFECTO
    ahora_zona = datetime.now(ZoneInfo(zona))
    datos = {
        "barra_fecha": format_date(ahora_zona.date(), "full"),
        "barra_hora": ahora_zona.strftime("%H:%M:%S"),
        "barra_zona": zona,
        "barra_mi_dia": 0,
        "barra_cronometro": None,
        "barra_correo": None,
    }
    try:
        cuentas = db.listar_cuentas_correo(g.usuario_id)
        if cuentas:
            error = next((c for c in cuentas if c["ultimo_error_sincronizacion"]), None)
            ultimas = [c["ultima_sincronizacion"] for c in cuentas if c["ultima_sincronizacion"]]
            minutos = None
            if ultimas:
                minutos = max(0, int((datetime.now() - datetime.fromisoformat(max(ultimas))).total_seconds() // 60))
            datos["barra_correo"] = {
                "error": error["ultimo_error_sincronizacion"] if error else None, "minutos": minutos,
                # Cambios hechos aquí (leído, borrado…) que el servidor de correo rechazó tras varios intentos.
                "sin_enviar": db.contar_operaciones_correo_con_error(g.usuario_id),
            }
    except Exception:
        pass
    try:
        vencidas, de_hoy = db.contar_mi_dia(g.usuario_id)
        datos["barra_mi_dia"] = vencidas + de_hoy
        datos["barra_mi_dia_vencidas"] = vencidas
    except Exception:
        pass
    try:
        activas = [t for t in db.tareas_activas(g.usuario_id) if t["estado"] == "en_curso"]
        if activas:
            t = activas[0]
            datos["barra_cronometro"] = {"nombre": t["nombre"], "inicio": t["inicio_en"], "pausado": t.get("segundos_pausados", 0), "mas": len(activas) - 1}
    except Exception:
        pass
    return datos


@app.context_processor
def inyectar_perfil_rail():
    """Avatar/nombre/tenant para la tarjeta de cuenta fija abajo del
    rail (base.html) -- mismas funciones ya usadas por
    /ajustes/perfil, sin repetir la consulta ahí."""
    if not g.usuario_id:
        return {}
    return {
        "perfil_rail": db.obtener_perfil_usuario(g.usuario_id),
        "usuario_rail": peticion.memo("usuario", lambda: db.obtener_usuario(g.usuario_id)),
        "tenant_rail": peticion.memo("tenant", lambda: db.obtener_tenant(g.tenant_id) if g.tenant_id else None),
    }


@app.context_processor
def inyectar_ia_flotante():
    # El panel flotante del Asistente IA vive en base.html, así que necesita
    # su propio contexto en cualquier página que no sea ya /ia (ahí la ruta
    # pasa mensajes/pendiente explícitamente para el chat de página completa).
    # El panel flotante YA NO lleva el historial del chat en cada página (era todo el
    # historial de la conversación activa, sin límite, oculto, en cada vista): se pide a
    # /ia/panel al abrirlo. Solo el inicio pinta su chat de dashboard en la propia página.
    if not g.usuario_id or request.endpoint != "inicio":
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
        # Iniciar el flujo server-side (en vez de mandar al navegador
        # directo a /.ory/self-service/.../browser) evita que Kratos
        # decida el destino él mismo -- redirigiría a su
        # SELFSERVICE_FLOWS_*_UI_URL configurado, que es un único valor
        # fijo (siempre el origen "principal" de la app, ver
        # docker-compose.yml). Sin este paso, cualquier subdominio nuevo
        # que reutilice estas mismas rutas de login (p.ej. el backoffice,
        # ver HOSTING.md) acabaría rebotando al usuario fuera de su
        # propio origen a mitad del flujo -- entrar en él ahí y salir
        # con la sesión puesta en un dominio distinto. Iniciarlo aquí y
        # redirigir (ruta relativa, sin dominio) de vuelta a esta misma
        # URL con ?flow=<id> mantiene TODO el flujo en el origen desde el
        # que se entró, sea cual sea.
        try:
            # Cuenta con verificación en dos pasos que ya dio la contraseña: el flujo que toca es el del segundo factor (aal2).
            aal = "aal2" if tipo == "login" and kratos.requiere_aal2(request.cookies) else None
            ubicacion, cabeceras_set_cookie = kratos.iniciar_flujo(tipo, request.cookies, aal=aal)
        except kratos.ErrorKratos:
            g._redireccion_flujo = redirect(request.path)
            return None
        flow_id_nuevo = urllib.parse.parse_qs(urllib.parse.urlparse(ubicacion).query).get("flow", [None])[0]
        if not flow_id_nuevo:
            g._redireccion_flujo = redirect(request.path)
            return None
        respuesta = redirect(f"{request.path}?flow={flow_id_nuevo}")
        # La cookie anti-CSRF que Kratos acaba de fijar para este flujo
        # tiene que llegar al navegador real -- sin esto, el POST
        # posterior al proxy falla la validación CSRF de Kratos (ver
        # docstring de kratos.iniciar_flujo).
        for cabecera in cabeceras_set_cookie:
            respuesta.headers.add("Set-Cookie", cabecera)
        g._redireccion_flujo = respuesta
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


def _carga_equipo_para_inicio(usuario_id):
    """Panel del equipo: solo tiene sentido si hay más de una persona implicada."""
    try:
        carga = db.carga_equipo(usuario_id)
    except Exception:
        return []
    return carga if len(carga) > 1 else []


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
        if g.tenant_id is not None:
            # Puesta en marcha del despacho (gestoría): pasos guiados con enlace directo a cada pantalla.
            titulos = {
                "clientes": _("Crea tu primer cliente fiscal"),
                "vencimientos": _("Genera los vencimientos fiscales"),
                "correo": _("Conecta una cuenta de correo del despacho"),
                "recordatorios": _("Revisa los recordatorios automáticos a tus clientes"),
                "portal": _("Da acceso al portal a un cliente"),
                "presentado": _("Marca un vencimiento como presentado"),
            }
            despacho = onboarding_despacho.resumen(g.tenant_id)
            for paso in despacho["pasos"]:
                paso["titulo"] = titulos[paso["clave"]]
                paso["url"] = url_for(paso["endpoint"])
            onboarding["despacho"] = despacho

    # Tarjeta de vencimientos fiscales próximos (calendario fiscal, solo
    # con tenant asignado -- igual que el resto de esa sección) -- mismo
    # criterio "tarjeta pulsable" que la de correos sin leer, próximos 30
    # días para no saturar la cifra con todo el año.
    total_vencimientos_proximos = None
    hasta_vencimientos_proximos = None
    vencimientos_proximos = []
    if g.tenant_id is not None:
        hasta_vencimientos_proximos = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        pendientes = db.listar_vencimientos_fiscales(
            g.tenant_id, estado="pendiente", hasta=hasta_vencimientos_proximos
        )
        total_vencimientos_proximos = len(pendientes)
        # Panel "Próximos vencimientos": los 4 más cercanos con los días que
        # faltan (negativo = ya vencido), calculados aquí para que la
        # plantilla solo pinte.
        for v in sorted(pendientes, key=lambda v: v["fecha_limite"])[:4]:
            dias = (datetime.strptime(v["fecha_limite"][:10], "%Y-%m-%d").date() - datetime.now().date()).days
            vencimientos_proximos.append({
                "modelo": v["modelo"], "cliente": v["cliente_nombre"],
                "fecha": v["fecha_limite"][:10], "dias": dias,
            })

    # Saludo y panel "Mi día" (vencidas + de hoy + asignadas a mí).
    hora = datetime.now().hour
    saludo = _("Buenos días") if hora < 14 else (_("Buenas tardes") if hora < 21 else _("Buenas noches"))
    perfil = db.obtener_perfil_usuario(g.usuario_id)
    nombre_usuario = ((perfil["nombre_mostrado"] if perfil else None) or "").strip()
    if not nombre_usuario:
        nombre_usuario = (db.obtener_usuario(g.usuario_id)["email"] or "").split("@")[0]
    secciones_mi_dia = db.tareas_para_hoy(g.usuario_id)
    mi_dia = []
    for clave in ("vencidas", "hoy", "asignadas"):
        for t in secciones_mi_dia[clave]:
            if all(t["id"] != x["id"] for x in mi_dia):
                mi_dia.append({
                    "id": t["id"], "asunto": t["asunto"], "prioridad": t["prioridad"],
                    "vencimiento": (t["fecha_vencimiento"] or "")[:16], "vencida": clave == "vencidas",
                    "mia": t["usuario_id"] == g.usuario_id,
                })

    return render_template(
        "inicio.html",
        menus=menus,
        activas_por_menu=activas_por_menu,
        entradas_hoy=entradas_hoy,
        log_hoy=log_hoy,
        total_activas=len(activas),
        total_mi_dia=len(mi_dia),
        proyectos_compartidos=db.listar_proyectos_compartidos_conmigo(g.usuario_id),
        plantillas_proyecto=proyecto_plantillas.catalogo(g.usuario_id),
        carga_equipo=_carga_equipo_para_inicio(g.usuario_id),
        mi_dia=mi_dia[:5],
        vencimientos_proximos=vencimientos_proximos,
        saludo=saludo,
        nombre_usuario=nombre_usuario,
        fecha_larga=format_date(datetime.now().date(), "full"),
        total_notas_hoy=len([f for f in log_hoy if f["origen"] == "nota"]),
        total_vencimientos_proximos=total_vencimientos_proximos,
        hasta_vencimientos_proximos=hasta_vencimientos_proximos,
        onboarding=onboarding,
        hoy_iso=hoy,
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


ICONOS_MENU_VALIDOS = {
    "folder", "flag", "star", "zap", "book-open", "briefcase", "building-2",
    "users", "layers", "target", "bookmark", "tag", "layout-grid",
    "clipboard-list", "puzzle", "rocket",
}


def _icono_menu_valido(valor: str | None) -> str | None:
    return valor if valor in ICONOS_MENU_VALIDOS else None


@app.route("/menus", methods=["POST"])
@login_required
def crear_menu():
    nombre = request.form.get("nombre", "").strip()
    color = request.form.get("color", "").strip() or None
    icono = _icono_menu_valido(request.form.get("icono", "").strip())
    if nombre:
        categoria_id = db.crear_categoria(g.usuario_id, nombre, color, icono)
        clave = request.form.get("plantilla", "").strip()
        estructura = proyecto_plantillas.estructura_de(g.usuario_id, clave) if clave else None
        if estructura:
            db.aplicar_plantilla_proyecto(g.usuario_id, categoria_id, estructura)
            return redirect(url_for("proyectos.lista", proyecto_id=categoria_id))
    return redirect(url_for("inicio"))


def _total_mi_dia(usuario_id: int) -> int:
    """Cuántas tareas piden atención hoy (vencidas, de hoy y asignadas a mí)."""
    secciones = db.tareas_para_hoy(usuario_id)
    return len(secciones["vencidas"]) + len(secciones["hoy"]) + len(secciones["asignadas"])


@app.route("/menu/<int:menu_id>")
@login_required
def ver_menu(menu_id: int):
    if request.args.get("registro") != "1":
        # Un proyecto compartido (o uno propio) se abre en su página de proyecto; el registro cronológico
        # de notas y eventos de siempre queda en la pestaña «Registro» (?registro=1).
        if db.obtener_proyecto(g.usuario_id, menu_id) is None:
            abort(404)
        return redirect(url_for("proyectos.resumen", proyecto_id=menu_id))
    menu = db.obtener_categoria(g.usuario_id, menu_id)
    if menu is None:
        abort(404)
    q = request.args.get("q") or None
    activas = [t for t in db.tareas_activas(g.usuario_id) if t["categoria_id"] == menu_id]
    log = db.historial(g.usuario_id, categoria_id=menu_id, texto=q)
    plantillas = db.listar_plantillas(menu_id)
    tareas_pendientes = db.listar_tareas_outlook(
        g.usuario_id, categoria_id=menu_id, excluir_completadas=True, incluir_asignadas=True,
    )
    return render_template(
        "menu.html", menu=menu, activas=activas, log=log, q=q or "", plantillas=plantillas,
        tareas_pendientes=tareas_pendientes, notas_fijadas=db.listar_notas_fijadas(g.usuario_id, menu_id),
    )


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
    icono = _icono_menu_valido(request.form.get("icono", "").strip())
    if nombre:
        db.renombrar_categoria(g.usuario_id, menu_id, nombre, color, icono)
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


@app.route("/notas", methods=["GET"])
@login_required
def lista_notas():
    """Pantalla Notas: lista (fijadas primero, filtro por proyecto y
    búsqueda) con el editor de la nota elegida al lado."""
    categoria_id = request.args.get("categoria_id", type=int)
    q = (request.args.get("q") or "").strip() or None
    solo_compartidas = request.args.get("compartidas") == "1"
    notas = db.listar_notas(
        g.usuario_id, categoria_id=categoria_id, texto=q, incluir_compartidas=not solo_compartidas, solo_compartidas=solo_compartidas
    )
    nota_id = request.args.get("nota", type=int)
    nueva = request.args.get("nueva") == "1"
    nota = None
    if not nueva:
        nota = next((n for n in notas if n["id"] == nota_id), None) if nota_id else None
        if nota is None and nota_id is None and notas:
            nota = notas[0]
    detalle = None
    if nota is not None:
        completa = db.obtener_nota_visible(g.usuario_id, nota["id"])
        rol_nota = db.rol_en_nota(g.usuario_id, nota["id"])
        es_dueno_nota = rol_nota == "dueno"
        # Los vínculos (tarea, correo) son del dueño: a un compañero no se le muestran.
        tarea = db.obtener_tarea_outlook(g.usuario_id, completa["tarea_outlook_id"]) if es_dueno_nota and completa["tarea_outlook_id"] else None
        mensaje = None
        if es_dueno_nota and completa["mensaje_correo_id"] and db.mensaje_correo_pertenece_a_usuario(g.usuario_id, completa["mensaje_correo_id"]):
            mensaje = db.obtener_mensaje_correo(completa["mensaje_correo_id"])
        detalle = {
            "nota": completa, "tarea": tarea, "mensaje": mensaje,
            "adjuntos": db.listar_adjuntos_nota(nota["id"]),
            "rol": rol_nota, "participantes": db.participantes_de_nota(nota["id"]),
        }
    return render_template(
        "notas.html",
        notas=notas, detalle=detalle, nueva=nueva, q=q or "", categoria_id=categoria_id,
        solo_compartidas=solo_compartidas, companeros=db.listar_companeros_tenant(g.usuario_id),
        n_participantes=db.contar_participantes_notas([n["id"] for n in notas]),
        menus=db.listar_categorias(g.usuario_id),
        clientes_fiscales=db.listar_clientes_fiscales(g.tenant_id) if g.tenant_id else [],
        adjuntos_max=db.NOTAS_ADJUNTOS_MAXIMO_POR_NOTA,
        adjuntos_por_nota=db.contar_adjuntos_notas([n["id"] for n in notas]),
    )


@app.route("/notas", methods=["POST"])
@login_required
def crear_nota():
    texto = request.form.get("texto", "").strip()
    titulo = request.form.get("titulo", "").strip()
    categoria_id = request.form.get("categoria_id") or None
    if texto or titulo:
        db.crear_nota(g.usuario_id, texto, categoria_id=categoria_id, titulo=titulo or None)
    return redirect(request.referrer or url_for("inicio"))


@app.route("/nota/<int:nota_id>/editar", methods=["GET", "POST"])
@login_required
def editar_nota(nota_id: int):
    if db.rol_en_nota(g.usuario_id, nota_id) not in ("dueno", "colabora"):
        abort(404)
    nota = db.obtener_nota_visible(g.usuario_id, nota_id)
    if nota is None:
        abort(404)
    # Esta ficha antigua (adjuntos, fijar, borrar) es del dueño: un colaborador
    # edita desde la pantalla Notas.
    if request.method == "GET" and nota["usuario_id"] != g.usuario_id:
        return redirect(url_for("lista_notas", nota=nota_id))
    if request.method == "POST":
        texto = request.form.get("texto", "").strip()
        titulo = request.form.get("titulo", "").strip()
        volver_a = request.form.get("volver_a") or url_for("inicio")
        if texto or titulo:
            cliente = request.form.get("cliente_fiscal_id", type=int)
            db.editar_nota(
                g.usuario_id, nota_id, texto, titulo=titulo or None, fijada=request.form.get("fijada") == "1",
                cliente_fiscal_id=cliente,
            )
        return redirect(volver_a)
    volver_a = request.args.get("volver_a") or request.referrer or url_for("inicio")
    return render_template(
        "editar_nota.html", nota=nota, volver_a=volver_a,
        adjuntos=db.listar_adjuntos_nota(nota_id),
        clientes_fiscales=db.listar_clientes_fiscales(g.tenant_id) if g.tenant_id else [],
        adjuntos_max=db.NOTAS_ADJUNTOS_MAXIMO_POR_NOTA,
        error=(request.args.get("error") or "")[:200] or None,
    )


@app.route("/nota/<int:nota_id>/compartir", methods=["POST"])
@login_required
def compartir_nota(nota_id: int):
    """Solo el dueño: comparte la nota con un compañero del despacho."""
    try:
        otro = int(request.form.get("usuario_id", ""))
    except ValueError:
        abort(404)
    rol = request.form.get("rol", "colabora")
    if not db.compartir_nota(g.usuario_id, nota_id, otro, rol):
        abort(404)
    try:
        if db.notificacion_tipo_activa(otro, "tarea_asignada"):
            nota = db.obtener_nota_visible(otro, nota_id)
            quien = db.nombre_mostrado_usuario(g.usuario_id) or db.obtener_usuario(g.usuario_id)["email"]
            titulo = (nota["titulo"] or nota["texto"].split("\n")[0])[:60]
            notificaciones.crear_y_enviar(
                otro, "tarea_asignada", "Nota compartida", f"{quien} ha compartido contigo la nota: {titulo}",
                url=url_for("lista_notas", nota=nota_id, compartidas=1), datos={"tipo": "nota_compartida", "nota_id": nota_id},
            )
    except Exception:  # noqa: BLE001
        pass
    return redirect(url_for("lista_notas", nota=nota_id))


@app.route("/nota/<int:nota_id>/compartir/quitar", methods=["POST"])
@login_required
def dejar_de_compartir_nota(nota_id: int):
    try:
        otro = int(request.form.get("usuario_id", ""))
    except ValueError:
        abort(404)
    if not db.dejar_de_compartir_nota(g.usuario_id, nota_id, otro):
        abort(404)
    if otro == g.usuario_id:
        return redirect(url_for("lista_notas"))
    return redirect(url_for("lista_notas", nota=nota_id))


@app.route("/nota/<int:nota_id>/fijar", methods=["POST"])
@login_required
def fijar_nota(nota_id: int):
    if not db.alternar_fijada_nota(g.usuario_id, nota_id):
        abort(404)
    return redirect(request.form.get("volver_a") or request.referrer or url_for("inicio"))


@app.route("/nota/<int:nota_id>/adjuntos", methods=["POST"])
@login_required
def subir_adjuntos_nota(nota_id: int):
    """Sube uno o varios archivos a la nota. Si alguno no es válido se avisa del
    primer error; los válidos anteriores ya quedan adjuntos."""
    if db.obtener_nota(g.usuario_id, nota_id) is None:
        abort(404)
    volver_a = request.form.get("volver_a") or url_for("inicio")
    error = None
    for fichero in request.files.getlist("adjunto"):
        if not fichero or not fichero.filename:
            continue
        # Se lee como mucho LIMITE+1 bytes: no se carga un archivo enorme entero en memoria.
        contenido = fichero.read(db.NOTAS_ADJUNTOS_TAMANO_MAXIMO + 1)
        try:
            db.agregar_adjunto_nota(g.usuario_id, nota_id, fichero.filename, fichero.mimetype, contenido)
        except ValueError as e:
            error = error or f"{fichero.filename}: {e}"
    return redirect(url_for("editar_nota", nota_id=nota_id, volver_a=volver_a, error=error))


@app.route("/nota/adjunto/<int:adjunto_id>")
@login_required
def descargar_adjunto_nota(adjunto_id: int):
    adjunto = db.obtener_adjunto_nota(g.usuario_id, adjunto_id)
    if adjunto is None:
        abort(404)
    en_linea = request.args.get("ver") == "1" and adjunto["tipo_mime"].startswith("image/")
    respuesta = Response(adjunto["contenido"], mimetype=adjunto["tipo_mime"])
    nombre = adjunto["nombre"].replace('"', "")
    respuesta.headers["Content-Disposition"] = f'{"inline" if en_linea else "attachment"}; filename="{nombre}"'
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    return respuesta


@app.route("/nota/adjunto/<int:adjunto_id>/eliminar", methods=["POST"])
@login_required
def eliminar_adjunto_nota(adjunto_id: int):
    adjunto = db.obtener_adjunto_nota(g.usuario_id, adjunto_id)
    if adjunto is None:
        abort(404)
    db.eliminar_adjunto_nota(g.usuario_id, adjunto_id)
    return redirect(url_for("editar_nota", nota_id=adjunto["nota_id"], volver_a=request.form.get("volver_a") or url_for("inicio")))


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
    categoria_id = request.form.get("categoria_id", type=int)
    tipo = request.form.get("tipo", "duracion")
    if nombre and categoria_id:
        if db.obtener_categoria(g.usuario_id, categoria_id) is None:
            abort(404)
        db.crear_tarea(g.usuario_id, nombre, categoria_id, tipo)
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
        "resumen": db.resumen_historial(g.usuario_id, desde=desde, hasta=hasta, categoria_id=categoria_id, texto=q),
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
    elif formato == "pdf":
        contenido = export.a_pdf(g.usuario_id, desde, hasta, categoria_id)
        mimetype = "application/pdf"
        nombre_archivo = "guilda_work_informe.pdf"
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


@app.route("/informe-ia/pdf", methods=["POST"])
@login_required
def informe_ia_pdf():
    """PDF del informe de IA que se acaba de generar en pantalla (el servidor no lo guarda: llega en el formulario)."""
    texto = (request.form.get("texto") or "").strip()
    if not texto:
        abort(400)
    contenido = generador_documentos.texto_a_pdf(_("Informe de Guilda Work"), texto, notas=_("Informe redactado con IA; revísalo antes de usarlo."))
    return Response(contenido, mimetype="application/pdf", headers={"Content-Disposition": "attachment; filename=guilda_work_informe_ia.pdf"})


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
        token = busqueda.generar_token_busqueda(g.usuario_id, tenant_id=g.tenant_id)
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
    resultados = busqueda.buscar_hibrido(g.usuario_id, texto, tenant_id=g.tenant_id)
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


@app.route("/facturacion/abrir", endpoint="abrir_facturacion")
@login_required
def abrir_facturacion():
    """Enlace de un solo uso hacia facturacion.guildawork.com (ver
    app/rutas_facturacion_proxy.py) -- reemplaza el href directo a la URL
    interna 127.0.0.1:PUERTO, que solo era alcanzable desde dentro del
    propio VPS."""
    tenant = db.tenant_de_usuario(g.usuario_id)
    if tenant is None or not tenant["facturascripts_url"]:
        abort(404)
    token = db.crear_acceso_facturacion(tenant["id"], g.usuario_id)
    return redirect(f"{FACTURACION_ORIGIN}/entrar?token={token}")


@app.route("/mis-dispositivos")
@login_required
def mis_dispositivos():
    """Sesiones de la app móvil (tokens de app/rutas_api.py) — un usuario
    revoca aquí las suyas propias (p.ej. si pierde el móvil); un admin
    revoca además las de sus compañeros de tenant desde el backoffice (ver
    backoffice.dispositivos_tenant más abajo)."""
    from . import api_areas

    return render_template("mis_dispositivos.html", dispositivos=db.listar_tokens_api(g.usuario_id), token_nuevo=None, areas_api=api_areas.AREAS)


@app.route("/mis-dispositivos/token", methods=["POST"])
@login_required
def crear_token_desde_web():
    """Token de API para una integración (permisos, áreas y caducidad a elegir).
    Se muestra una única vez en la propia respuesta: no viaja por URL ni se guarda en claro."""
    from . import api_areas

    permisos = request.form.get("permisos") or "completo"
    if permisos not in db.PERMISOS_TOKEN_API:
        abort(400)
    nombre = (request.form.get("nombre") or "").strip()[:80] or _("Token de API")
    caduca_en = None
    dias = request.form.get("caduca_dias", type=int)
    if dias:
        if not 1 <= dias <= 3650:
            abort(400)
        caduca_en = (datetime.now() + timedelta(days=dias)).isoformat(timespec="seconds")
    try:
        token = db.crear_token_api(g.usuario_id, nombre, permisos, areas=request.form.getlist("areas"), caduca_en=caduca_en,
                                   origenes_cors=request.form.get("origenes_cors"), ips_permitidas=request.form.get("ips_permitidas"))
    except ValueError as error:
        abort(400, str(error))
    if request.form.get("documentos_cifrados"):
        # Acceso a los documentos cifrados con este token, también con el despacho bloqueado: solo un responsable, y con el despacho desbloqueado ahora.
        from . import cifrado_despacho
        try:
            if not (g.get("supervisor_tenant") or g.get("es_admin")) or g.get("tenant_id") is None:
                raise ValueError(_("Solo un responsable del despacho puede dar a un token acceso a los documentos cifrados."))
            cifrado_despacho.crear_concesion(g.tenant_id, g.usuario_id, token, "token", nombre, caduca_en)
        except (ValueError, cifrado_despacho.DespachoBloqueado) as error:
            db.revocar_token_api(token)         # sin concesión no se deja un token a medias
            abort(400, str(error))
    return render_template(
        "mis_dispositivos.html", dispositivos=db.listar_tokens_api(g.usuario_id), areas_api=api_areas.AREAS,
        token_nuevo={"token": token, "nombre": nombre, "permisos": permisos, "areas": api_areas.validar_areas(request.form.getlist("areas")), "caduca_en": caduca_en},
    )


@app.route("/mis-dispositivos/<int:token_id>/revocar", methods=["POST"])
@login_required
def revocar_dispositivo(token_id):
    db.revocar_token_api_por_id(g.usuario_id, token_id)
    return redirect(url_for("mis_dispositivos"))


@app.route("/ajustes/perfil", methods=["GET", "POST"])
@login_required
def ajustes_perfil():
    """Mi perfil: cómo apareces (nombre, foto, cargo, teléfono), qué avisos recibes y cuándo («no molestar»), apariencia, seguridad de la
    cuenta y tus datos. A diferencia del panel de ajustes de la barra (tema/idioma/densidad, ajustes de la APLICACIÓN), esto es la
    persona. Contraseña/email viven aparte en /ajustes/cuenta (flujo Kratos, no aplica a usuarios locales de escritorio)."""
    if request.method == "POST":
        db.guardar_perfil_usuario(
            g.usuario_id,
            nombre_mostrado=request.form.get("nombre_mostrado", ""),
            cargo=request.form.get("cargo", ""),
            telefono=request.form.get("telefono", ""),
            silencio_desde=request.form.get("silencio_desde", "") if "silencio_activo" in request.form else "",
            silencio_hasta=request.form.get("silencio_hasta", "") if "silencio_activo" in request.form else "",
            notificar_push_vencimientos="notificar_push_vencimientos" in request.form,
            notificar_push_tiquets="notificar_push_tiquets" in request.form,
            notificar_resumen_semanal="notificar_resumen_semanal" in request.form,
            notificar_push_correo="notificar_push_correo" in request.form,
            notificar_push_portal_mensajes="notificar_push_portal_mensajes" in request.form,
            resumen_diario="resumen_diario" in request.form,
            resumen_diario_email="resumen_diario_email" in request.form,
            resumen_diario_hora=int(request.form["resumen_diario_hora"]) if request.form.get("resumen_diario_hora", "").strip().isdigit() else None,
        )
        return redirect(url_for("ajustes_perfil", aviso="guardado"))
    usuario = db.obtener_usuario(g.usuario_id)
    tenant = db.tenant_de_usuario(g.usuario_id)
    return render_template(
        "ajustes_perfil.html",
        perfil=db.obtener_perfil_usuario(g.usuario_id),
        usuario=usuario,
        despacho=tenant["nombre"] if tenant else None,
        dispositivos=len(db.listar_tokens_api(g.usuario_id)),
        en_silencio=db.en_horas_de_silencio(g.usuario_id),
        # Un usuario local (modo escritorio) nunca pasa por Kratos -- no
        # tiene contraseña/email que cambiar desde aquí (app/db.py:
        # es_local, ver _resolver_usuario_local).
        puede_cambiar_credenciales=not usuario["es_local"],
        # Sin flash() en este proyecto (ningún otro sitio lo usa) -- un parámetro de query que la propia vista GET traduce a texto.
        error_avatar=request.args.get("error_avatar"),
        aviso=request.args.get("aviso"),
    )


@app.route("/ajustes/perfil/prueba-notificacion", methods=["POST"])
@login_required
def prueba_notificacion():
    """Manda una notificación de prueba a la propia persona (en la app y, si tiene el móvil vinculado, push; la prueba ignora «no molestar»)."""
    notificaciones.crear_y_enviar(
        g.usuario_id, "prueba", _("Notificación de prueba"), _("Si ves esto, las notificaciones funcionan."),
        url_for("ajustes_perfil"), ignorar_silencio=True,
    )
    return redirect(url_for("ajustes_perfil", aviso="prueba") + "#notificaciones")


def _secciones_ajustes() -> list[dict]:
    """Todo lo configurable de la aplicación, por grupos, con el estado actual de cada cosa (para que esta pantalla sea un cuadro de mandos
    y no solo una lista de enlaces). Solo aparece lo que la persona puede usar."""
    uid = g.usuario_id
    usuario = db.obtener_usuario(uid)
    perfil = db.obtener_perfil_usuario(uid)
    n_cuentas = len(db.listar_cuentas_correo(uid))
    n_dispositivos = len(db.listar_tokens_api(uid))
    avisos_off = sum(1 for c in ("notificar_push_vencimientos", "notificar_push_tiquets", "notificar_push_correo", "notificar_push_portal_mensajes") if not perfil[c])

    def u(endpoint, **kw):
        return url_for(endpoint, **kw)

    cuenta = [
        {"id": "perfil", "icono": "user", "titulo": _("Mi perfil"), "texto": _("Nombre, foto, cargo y teléfono."), "url": u("ajustes_perfil"), "estado": (perfil["nombre_mostrado"] or usuario["email"])},
        {"id": "notificaciones", "icono": "bell", "titulo": _("Notificaciones"), "texto": _("Qué avisos recibes, «no molestar» y prueba de envío."), "url": u("ajustes_perfil") + "#notificaciones",
         "estado": _("%(n)s desactivados", n=avisos_off) if avisos_off else _("Todas activas")},
    ]
    if not usuario["es_local"]:
        cuenta.append({"id": "seguridad", "icono": "lock", "titulo": _("Contraseña, email y verificación en dos pasos"), "texto": _("Cambia tus credenciales y protege la cuenta con un segundo factor."), "url": u("ajustes_cuenta"), "estado": None})
    cuenta.append({"id": "dispositivos", "icono": "smartphone", "titulo": _("Mis dispositivos"), "texto": _("Móviles con sesión iniciada: revísalos y cierra los que no uses."), "url": u("mis_dispositivos"),
                   "estado": ngettext("%(n)s dispositivo", "%(n)s dispositivos", n_dispositivos, n=n_dispositivos)})
    trabajo = [
        {"id": "correo", "icono": "mail", "titulo": _("Correo"), "texto": _("Firma, categorías, reglas, plantillas y envío."), "url": u("correo.ajustes"), "estado": None},
        {"id": "cuentas", "icono": "send", "titulo": _("Cuentas de correo"), "texto": _("Conecta, sincroniza o desconecta tus buzones."), "url": u("correo.cuentas"),
         "estado": ngettext("%(n)s cuenta", "%(n)s cuentas", n_cuentas, n=n_cuentas)},
        {"id": "plantillas", "icono": "layout-list", "titulo": _("Plantillas de tareas"), "texto": _("Listas de tareas que se repiten en cada cliente o proyecto."), "url": u("tareas.plantillas"), "estado": None},
        {"id": "recurrentes", "icono": "refresh-cw", "titulo": _("Tareas recurrentes"), "texto": _("Tareas que se crean solas cada semana, mes o año."), "url": u("tareas.recurrentes"), "estado": None},
        {"id": "fichaje", "icono": "clock", "titulo": _("Fichaje: mis datos"), "texto": _("Nombre completo y DNI/NIE para el registro horario."), "url": u("fichaje.mis_datos"), "estado": None},
    ]
    from . import acceso
    if g.tenant_id is not None and acceso.es_directivo(uid):
        trabajo.append({"id": "marca", "icono": "sparkles", "titulo": _("Marca del despacho"), "texto": _("Nombre, logo y color propios para tu equipo."), "url": u("marca.ajustes"), "estado": None})
    if g.tenant_id is not None:
        trabajo.append({"id": "recordatorios", "icono": "bell", "titulo": _("Recordatorios a clientes"), "texto": _("Avisos automáticos de vencimientos a tus clientes."), "url": u("fiscal.recordatorios"), "estado": None})
    asistente = [
        {"id": "ia", "icono": "bot", "titulo": _("Asistente de IA"), "texto": _("Modelo, claves, atajos y modo solo lectura."), "url": u("ia.ajustes"), "estado": None},
        {"id": "modelos", "icono": "sparkles", "titulo": _("Modelos disponibles"), "texto": _("Qué modelos puedes usar y su coste."), "url": u("ia.modelos"), "estado": None},
    ]
    datos = [
        {"id": "exportar", "icono": "download", "titulo": _("Exportar"), "texto": _("Histórico, tareas y notas en JSON, CSV o Markdown."), "url": u("exportar"), "estado": None},
        {"id": "importar", "icono": "upload", "titulo": _("Importar"), "texto": _("Trae tus datos desde otra copia o aplicación."), "url": u("importar"), "estado": None},
        {"id": "papelera", "icono": "trash-2", "titulo": _("Papelera"), "texto": _("Recupera lo que borraste por error."), "url": u("papelera"), "estado": None},
        {"id": "herramientas", "icono": "wrench", "titulo": _("Herramientas conectadas"), "texto": _("Catálogo de aplicaciones integradas en tu gestoría."), "url": u("herramientas"), "estado": None},
    ]
    return [
        {"titulo": _("Tu cuenta"), "items": cuenta},
        {"titulo": _("Trabajo diario"), "items": trabajo},
        {"titulo": _("Asistente de IA"), "items": asistente},
        {"titulo": _("Tus datos"), "items": datos},
    ]


@app.route("/ajustes")
@app.route("/ajustes/")
@login_required
def ajustes():
    """Centro de ajustes: un solo sitio desde el que llegar a todo lo configurable, con buscador y el estado de cada cosa."""
    usuario = db.obtener_usuario(g.usuario_id)
    return render_template(
        "ajustes.html", secciones=_secciones_ajustes(), usuario=usuario, perfil=db.obtener_perfil_usuario(g.usuario_id),
    )


_AVATAR_TIPOS_PERMITIDOS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
_AVATAR_TAMANO_MAXIMO_BYTES = 5 * 1024 * 1024  # 5 MB, generoso para una foto de móvil sin comprimir


@app.route("/ajustes/apariencia", methods=["POST"])
@login_required
def guardar_apariencia():
    """Tema y densidad en la cuenta: los llaman sidebar.js y ajustes.js al cambiarlos (el navegador sigue guardándolos para pintar sin parpadeo)."""
    datos = request.get_json(silent=True) or {}
    tema, densidad = datos.get("tema"), datos.get("densidad")
    if tema not in (None, *db.TEMAS_VALIDOS) or densidad not in (None, *db.DENSIDADES_VALIDAS) or (tema is None and densidad is None):
        return jsonify({"ok": False}), 400
    db.guardar_apariencia_usuario(g.usuario_id, tema, densidad)
    return jsonify({"ok": True})


@app.context_processor
def inyectar_apariencia_cuenta():
    """Tema y densidad guardados en la cuenta (si los hay): base.html los aplica antes de pintar, así te siguen entre dispositivos."""
    ap = g.get("apariencia")
    return {"apariencia_cuenta": ap if ap and (ap["tema"] or ap["densidad"]) else None}


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
    mismo patrón que usan hoy los avatares de contactos de correo.

    Solo el propio usuario o alguien de su mismo tenant puede pedir este
    avatar -- usuario_id es un parámetro de ruta libre, sin este chequeo
    cualquier sesión válida podía enumerar IDs y ver el avatar de
    cualquiera, de cualquier tenant."""
    if usuario_id != g.usuario_id:
        tenant_objetivo = db.tenant_de_usuario(usuario_id)
        if tenant_objetivo is None or tenant_objetivo["id"] != g.tenant_id:
            abort(404)
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


@app.route("/ajustes-cuenta")
@login_required
def ajustes_cuenta_alias():
    """Kratos redirige aquí (SELFSERVICE_FLOWS_SETTINGS_UI_URL y RECOVERY_AFTER_DEFAULT_BROWSER_RETURN_URL, ver docker-compose.yml) al
    terminar de recuperar la contraseña con el código: sin esta ruta la persona caía en un 404 justo cuando iba a elegir su contraseña
    nueva. Es la misma pantalla que /ajustes/cuenta (los enlaces de la app usan esa)."""
    return ajustes_cuenta()


@app.route("/estadisticas")
@login_required
def estadisticas():
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    # Pestaña "Equipo" -- solo tiene sentido con un tenant asignado (en
    # modo escritorio o para un admin sin tenant, g.tenant_id es None y
    # no hay ningún equipo que agregar).
    equipo = db.estadisticas_equipo_por_usuario(g.tenant_id, desde, hasta) if g.tenant_id is not None else []
    tiempo_medio_resolucion = (
        db.tiempo_medio_resolucion_vencimientos(g.tenant_id) if g.tenant_id is not None else None
    )
    return render_template(
        "estadisticas.html",
        desde=desde or "",
        hasta=hasta or "",
        por_categoria=db.estadisticas_por_categoria(g.usuario_id, desde, hasta),
        por_dia=db.estadisticas_por_dia(g.usuario_id, desde, hasta),
        equipo=equipo,
        tiempo_medio_resolucion=tiempo_medio_resolucion,
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

    Todo lo que ya se ha guardado (notas, tareas, proyectos) está en SQLite con
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
                # Bug encontrado en la auditoría de 2026-09-30/10-01:
                # faltaba usuario_id -- sincronizar_bandeja(usuario_id,
                # cuenta_id) siempre lanzaba TypeError aquí, silenciado por
                # el except de abajo, así que este auto-sync nunca llegó a
                # sincronizar nada desde que existe.
                correo.sincronizar_bandeja(usuario_id, cuenta["id"])
            except Exception:
                pass  # un fallo de esta cuenta no debe impedir sincronizar las demás


SINCRONIZACION_CORREO_SERVIDOR_MINUTOS_POR_DEFECTO = 5
SINCRONIZACION_CORREO_SERVIDOR_ESPERA_INICIAL_SEGUNDOS = 60


def minutos_sincronizacion_correo_servidor() -> int:
    """Intervalo (minutos) del auto-sync del servidor: GUILDA_CORREO_SYNC_MINUTOS,
    5 por defecto; 0 (o un valor negativo) lo desactiva."""
    try:
        return int(os.environ.get("GUILDA_CORREO_SYNC_MINUTOS", SINCRONIZACION_CORREO_SERVIDOR_MINUTOS_POR_DEFECTO))
    except ValueError:
        return SINCRONIZACION_CORREO_SERVIDOR_MINUTOS_POR_DEFECTO


def _sincronizacion_correo_servidor():
    """Auto-sync del correo en el SERVIDOR (multi-usuario). A diferencia de
    _sincronizacion_correo_periodica -- solo para la app de escritorio, un
    único usuario --, recorre las cuentas de todos los usuarios. Sin esto,
    en producción el correo solo se descargaba al pulsar "Sincronizar"
    (sin avisos de correo nuevo, bandeja desactualizada)."""
    minutos = minutos_sincronizacion_correo_servidor()
    if minutos <= 0:
        return
    time.sleep(SINCRONIZACION_CORREO_SERVIDOR_ESPERA_INICIAL_SEGUNDOS)
    while True:
        try:
            resumen = correo.sincronizar_todas_las_cuentas()
            salud.registrar_ok("correo_sync", minutos * 60, f"{resumen.get('cuentas', 0)} cuenta(s), {resumen.get('errores', 0)} con error")
        except Exception as e:  # noqa: BLE001 -- el hilo no debe morir nunca
            logging.getLogger("guilda").exception("Fallo en el auto-sync de correo del servidor")
            salud.registrar_error("correo_sync", minutos * 60, f"{type(e).__name__}: {e}")
        time.sleep(minutos * 60)


def _idle_correo_servidor():
    """Correo casi instantáneo (IMAP IDLE): mantiene una conexión en espera por cada cuenta IMAP y
    sincroniza al momento cuando el servidor avisa. GUILDA_CORREO_IDLE=0 lo desactiva y
    GUILDA_CORREO_IDLE_MAX (100) limita cuántas cuentas a la vez. El auto-sync periódico sigue activo."""
    from . import correo_idle
    if not correo_idle.habilitado():
        return
    gestor = correo_idle.GestorIdle(correo_idle.maximo_cuentas())
    time.sleep(SINCRONIZACION_CORREO_SERVIDOR_ESPERA_INICIAL_SEGUNDOS)
    while True:
        try:
            gestor.revisar()
        except Exception:  # noqa: BLE001 -- el hilo no debe morir nunca
            logging.getLogger("guilda").exception("Fallo en el gestor de IMAP IDLE")
        time.sleep(60)


SEGUIMIENTOS_CORREO_INTERVALO_MINUTOS = 15


def _seguimientos_correo_servidor():
    """Cada 15 minutos revisa los correos de los que se espera respuesta: los que ya han contestado se cierran y
    de los que han pasado de plazo sin respuesta se avisa una vez (ver correo.procesar_seguimientos)."""
    intervalo = SEGUIMIENTOS_CORREO_INTERVALO_MINUTOS * 60
    time.sleep(120)
    while True:
        try:
            r = correo.procesar_seguimientos()
            salud.registrar_ok("correo_seguimientos", intervalo, f"{r['respondidos']} respondido(s), {r['avisados']} aviso(s)")
        except Exception as e:  # noqa: BLE001 -- el hilo no debe morir nunca
            logging.getLogger("guilda").exception("Fallo en el seguimiento de respuestas de correo")
            salud.registrar_error("correo_seguimientos", intervalo, f"{type(e).__name__}: {e}")
        time.sleep(intervalo)


ENVIOS_CORREO_INTERVALO_SEGUNDOS = 10


def _envios_correo_servidor():
    """Cola de envío del correo (deshacer envío y programados): cada pocos
    segundos envía lo pendiente cuya hora ha llegado. El estado se reclama
    con un UPDATE condicional, así que aunque corran dos procesos nunca se
    envía el mismo correo dos veces."""
    while True:
        try:
            correo.procesar_envios_pendientes()
            salud.registrar_ok("correo_envios", ENVIOS_CORREO_INTERVALO_SEGUNDOS, minimo_segundos=60)
        except Exception as e:  # noqa: BLE001 -- el hilo no debe morir nunca
            logging.getLogger("guilda").exception("Fallo en la cola de envío de correo")
            salud.registrar_error("correo_envios", ENVIOS_CORREO_INTERVALO_SEGUNDOS, f"{type(e).__name__}: {e}")
        time.sleep(ENVIOS_CORREO_INTERVALO_SEGUNDOS)


VIGILANTE_SALUD_INTERVALO_MINUTOS = 60


def _vigilante_salud_servidor():
    """Cada hora revisa el panel de salud y avisa por correo (ALERTAS_ADMIN_EMAIL)
    de lo que esté en rojo, como mucho una vez al día por motivo (ver app/salud.py).
    Espera 10 minutos tras arrancar para que las demás tareas ya hayan dado señales."""
    time.sleep(600)
    while True:
        try:
            salud.vigilar()
            salud.registrar_ok("vigilante_salud", VIGILANTE_SALUD_INTERVALO_MINUTOS * 60)
        except Exception as e:  # noqa: BLE001 -- el hilo no debe morir nunca
            logging.getLogger("guilda").exception("Fallo en el vigilante de salud")
            salud.registrar_error("vigilante_salud", VIGILANTE_SALUD_INTERVALO_MINUTOS * 60, f"{type(e).__name__}: {e}")
        time.sleep(VIGILANTE_SALUD_INTERVALO_MINUTOS * 60)


RECORDATORIOS_PORTAL_INTERVALO_HORAS = 6


def _recordatorios_portal_servidor():
    """Cada 6 horas envía a los clientes los recordatorios de vencimientos a 7
    y 2 días (ver app/portal_recordatorios.py). Se repite varias veces al día
    a propósito: si el correo falla, se reintenta, y nunca se duplica porque
    cada envío correcto queda registrado."""
    salud.registrar_ok("recordatorios_portal", RECORDATORIOS_PORTAL_INTERVALO_HORAS * 3600, "arrancado")
    time.sleep(300)
    while True:
        try:
            enviados = portal_recordatorios.procesar_recordatorios()
            salud.registrar_ok("recordatorios_portal", RECORDATORIOS_PORTAL_INTERVALO_HORAS * 3600, f"{enviados} enviado(s)")
        except Exception as e:  # noqa: BLE001 -- el hilo no debe morir nunca
            logging.getLogger("guilda").exception("Fallo en los recordatorios del portal")
            salud.registrar_error("recordatorios_portal", RECORDATORIOS_PORTAL_INTERVALO_HORAS * 3600, f"{type(e).__name__}: {e}")
        time.sleep(RECORDATORIOS_PORTAL_INTERVALO_HORAS * 3600)


AVISOS_FICHAJE_INTERVALO_MINUTOS = 15


def _avisos_fichaje_servidor():
    """Cada 15 minutos avisa de las jornadas de fichaje abiertas demasiado
    tiempo (ver app/fichaje_avisos.py)."""
    while True:
        try:
            fichaje_avisos.procesar_avisos()
            fichaje_avisos.procesar_avisos_turno()
            salud.registrar_ok("avisos_fichaje", AVISOS_FICHAJE_INTERVALO_MINUTOS * 60)
        except Exception as e:  # noqa: BLE001 -- el hilo no debe morir nunca
            logging.getLogger("guilda").exception("Fallo en los avisos de fichaje")
            salud.registrar_error("avisos_fichaje", AVISOS_FICHAJE_INTERVALO_MINUTOS * 60, f"{type(e).__name__}: {e}")
        time.sleep(AVISOS_FICHAJE_INTERVALO_MINUTOS * 60)


def _recordatorios_tareas_servidor():
    """Cada minuto envía los recordatorios de tarea que ya han llegado a su hora
    (ver app/recordatorios_tareas.py)."""
    while True:
        try:
            recordatorios_tareas.procesar_recordatorios()
            salud.registrar_ok("recordatorios_tareas", 180, minimo_segundos=300)
        except Exception as e:  # noqa: BLE001 -- el hilo no debe morir nunca
            logging.getLogger("guilda").exception("Fallo en los recordatorios de tareas")
            salud.registrar_error("recordatorios_tareas", 180, f"{type(e).__name__}: {e}")
        time.sleep(60)


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
    salud.registrar_ok("recordatorios_vencimientos", RECORDATORIO_VENCIMIENTOS_INTERVALO_MINUTOS * 60, "arrancado")
    while True:
        time.sleep(RECORDATORIO_VENCIMIENTOS_INTERVALO_MINUTOS * 60)
        try:
            proximos = db.vencimientos_fiscales_proximos(dias=RECORDATORIO_VENCIMIENTOS_DIAS_ANTELACION)
        except Exception as e:
            salud.registrar_error("recordatorios_vencimientos", RECORDATORIO_VENCIMIENTOS_INTERVALO_MINUTOS * 60, f"{type(e).__name__}: {e}")
            continue
        salud.registrar_ok("recordatorios_vencimientos", RECORDATORIO_VENCIMIENTOS_INTERVALO_MINUTOS * 60)
        for v in proximos:
            if not v["usuario_id"]:
                continue
            try:
                if not db.notificacion_tipo_activa(v["usuario_id"], "vencimiento_fiscal"):
                    db.marcar_recordatorio_vencimiento_fiscal_enviado(v["id"])
                    continue
                notificaciones.crear_y_enviar(
                    v["usuario_id"],
                    "vencimiento_fiscal",
                    "Vencimiento fiscal próximo",
                    f"{v['modelo']} de {v['cliente_nombre']} vence el {v['fecha_limite'][:10]}.",
                    url=f"/fiscal/vencimientos/{v['id']}/editar",
                    datos={"tipo": "vencimiento_fiscal", "vencimiento_id": v["id"]},
                )
                # Dedup: sin esto, vencimientos_fiscales_proximos() lo
                # volvía a devolver cada día mientras siguiera pendiente y
                # dentro de la ventana, reenviando el mismo aviso hasta
                # RECORDATORIO_VENCIMIENTOS_DIAS_ANTELACION veces.
                db.marcar_recordatorio_vencimiento_fiscal_enviado(v["id"])
            except Exception:
                pass


RESUMEN_IA_SEMANAL_INTERVALO_MINUTOS = 7 * 24 * 60  # una vez por semana


def _resumen_ia_semanal():
    """Fase G2: resumen semanal del asistente de IA, opt-in por usuario
    (usuario_perfil.notificar_resumen_semanal, ver /ajustes/perfil).
    Reutiliza ai_local.generar_informe() (ya existente, usado hoy solo
    bajo demanda desde /informe-ia) sobre los últimos 7 días de
    actividad, y lo manda por push. Mismo criterio defensivo que el
    resto de hilos periódicos, y mismo motivo que
    _recordatorio_vencimientos_fiscales para arrancar también desde
    serve.py: no es un hilo solo de escritorio.

    Solo genera el resumen si el usuario tiene OpenRouter configurado
    como proveedor de informes (ia_preferencias.proveedor_local) -- un
    Ollama/LM Studio locales normalmente corren en el propio ordenador
    del usuario, no son alcanzables desde este proceso (el servidor
    hospedado, o incluso el de escritorio si está apagado en ese
    momento), así que un resumen automático solo tiene sentido con un
    proveedor en la nube."""
    salud.registrar_ok("resumen_ia_semanal", RESUMEN_IA_SEMANAL_INTERVALO_MINUTOS * 60, "arrancado")
    while True:
        time.sleep(RESUMEN_IA_SEMANAL_INTERVALO_MINUTOS * 60)
        try:
            usuarios = db.usuarios_con_resumen_semanal_activo()
        except Exception as e:
            salud.registrar_error("resumen_ia_semanal", RESUMEN_IA_SEMANAL_INTERVALO_MINUTOS * 60, f"{type(e).__name__}: {e}")
            continue
        salud.registrar_ok("resumen_ia_semanal", RESUMEN_IA_SEMANAL_INTERVALO_MINUTOS * 60)
        hoy = datetime.now()
        desde = (hoy - timedelta(days=7)).strftime("%Y-%m-%d")
        hasta = hoy.strftime("%Y-%m-%d")
        for usuario_id in usuarios:
            try:
                prefs = db.obtener_preferencias_ia_local(usuario_id)
                if prefs["proveedor_local"] != "openrouter" or not prefs["modelo_local"]:
                    continue
                datos = export.construir_export(usuario_id, desde, hasta, None)
                if not datos.get("registros"):
                    continue  # nada que resumir esta semana, no molestar con un push vacío
                resumen = ai_local.generar_informe(
                    datos,
                    "Resume mis actividades de esta última semana, agrupadas por categoría, en 5-8 líneas como mucho.",
                    "openrouter", prefs["modelo_local"], usuario_id,
                )
                notificaciones.crear_y_enviar(
                    usuario_id, "resumen_ia_semanal", "Tu resumen semanal", resumen[:200],
                    url="/historial", datos={"tipo": "resumen_ia_semanal"},
                )
            except Exception:
                continue


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
    threading.Thread(target=_resumen_ia_semanal, daemon=True).start()

    webview.start()

    # Solo se llega aquí si no hay bandeja (o algo la desactivó) y se cerró
    # la ventana principal de verdad: terminamos el proceso por completo
    # para no dejar el servidor de fondo corriendo (evita procesos zombis).
    os._exit(0)


if __name__ == "__main__":
    main()
