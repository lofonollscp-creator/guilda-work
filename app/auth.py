"""Decoradores de autenticación compartidos por app/main.py y los blueprints
(rutas_correo.py, rutas_tareas.py, rutas_ia.py, rutas_api.py). Vive en su
propio módulo para que los blueprints puedan importarlo sin crear un import
circular con app/main.py (que a su vez importa los blueprints).

Dos mecanismos independientes que conviven porque atienden a clientes
distintos: `login_required` (cookie de sesión, navegador de escritorio) y
`token_required` (cabecera Authorization: Bearer, app móvil / Fase 2) —
nunca se usan juntos en la misma ruta.

`limiter` (Fase 3, hosting): instancia de Flask-Limiter sin `app` todavía
enlazada — vive aquí (no en main.py) por el mismo motivo que los
decoradores de arriba: rutas_api.py necesita decorar vistas con
`@limiter.limit(...)` sin crear un import circular con main.py, que es
quien luego llama a `limiter.init_app(app)`."""
from functools import wraps

from flask import g, jsonify, redirect, request, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from . import db

limiter = Limiter(key_func=get_remote_address)


def login_required(vista):
    @wraps(vista)
    def decorada(*args, **kwargs):
        if not g.usuario_id:
            return redirect(url_for("login", siguiente=request.path))
        return vista(*args, **kwargs)
    return decorada


def token_required(vista):
    @wraps(vista)
    def decorada(*args, **kwargs):
        cabecera = request.headers.get("Authorization", "")
        token = cabecera[7:] if cabecera.startswith("Bearer ") else None
        usuario_id = db.usuario_id_por_token(token) if token else None
        if usuario_id is None:
            return jsonify({"ok": False, "error": "Token inválido o ausente."}), 401
        g.usuario_id = usuario_id
        return vista(*args, **kwargs)
    return decorada
