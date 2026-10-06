"""Fábrica de la aplicación Flask del backoffice (proceso propio, ver
serve_backoffice.py). No importa app.main: solo la capa de datos de la
plataforma (app.db) y, para crear usuarios, app.kratos."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from flask import Flask, g, render_template, request, session

from . import auth

AQUI = Path(__file__).resolve().parent


def eur(centimos) -> str:
    """696 € / 1.234,50 € (sin decimales si son redondos)."""
    centimos = int(centimos or 0)
    euros, resto = divmod(abs(centimos), 100)
    texto = f"{euros:,}".replace(",", ".") + (f",{resto:02d}" if resto else "")
    return f"{'-' if centimos < 0 else ''}{texto} €"


def fecha(valor) -> str:
    if not valor:
        return "—"
    try:
        return datetime.fromisoformat(str(valor)).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return str(valor)[:16]


def iniciales(texto) -> str:
    partes = [p for p in str(texto or "?").replace("@", " ").replace(".", " ").split() if p]
    return ("".join(p[0] for p in partes[:2]) or "?").upper()


_COLORES = ("#2a9d8f", "#3b82f6", "#a855f7", "#f59e0b", "#ef4444", "#14b8a6", "#6366f1")


def color_avatar(texto) -> str:
    return _COLORES[sum(ord(c) for c in str(texto or "")) % len(_COLORES)]


def create_app(testing: bool = False) -> Flask:
    app = Flask(__name__, template_folder=str(AQUI / "templates"), static_folder=str(AQUI / "static"))
    app.config.update(
        SECRET_KEY=auth.clave_secreta(),
        SESSION_COOKIE_NAME="bo_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=not (testing or os.environ.get("BACKOFFICE_COOKIES_INSEGURAS") == "1"),
        MAX_CONTENT_LENGTH=1024 * 1024,
        TESTING=testing,
    )
    app.jinja_env.filters.update(eur=eur, fecha=fecha, iniciales=iniciales, color_avatar=color_avatar)

    from .rutas import bp

    from . import rutas_sistema  # noqa: F401 -- registra el resto de rutas en el mismo blueprint

    app.register_blueprint(bp)

    @app.before_request
    def _proteger_post():
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.endpoint != "static":
            auth.comprobar_csrf()

    @app.context_processor
    def _contexto():
        return {"csrf_token": auth.token_csrf, "admin": g.get("admin"), "endpoint": request.endpoint or ""}

    @app.after_request
    def _cabeceras(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "frame-ancestors 'none'; form-action 'self' https://checkout.stripe.com https://connect.stripe.com; base-uri 'self'"
        )
        if request.endpoint != "static":
            resp.headers["Cache-Control"] = "no-store"
        if not app.config["TESTING"]:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        return resp

    @app.errorhandler(404)
    def _no_encontrado(_e):
        return render_template("error.html", codigo=404, mensaje="No se ha encontrado lo que buscas."), 404

    @app.errorhandler(400)
    def _peticion_invalida(e):
        return render_template("error.html", codigo=400, mensaje=getattr(e, "description", "Petición no válida.")), 400

    @app.errorhandler(403)
    def _prohibido(_e):
        return render_template("error.html", codigo=403, mensaje="No tienes acceso."), 403

    return app
