"""Puente de login/consentimiento para Ory Hydra (Fase 7b).

Hydra delega en esta app la decisión de "¿quién es este usuario?" y "¿da su
consentimiento?" — ver `deploy/hydra/hydra.yml` (`urls.login`/`urls.consent`/
`urls.logout` apuntan aquí). Como Guilda Work ya tiene sesiones reales vía
Kratos (Fase 7a, `app/main.py`), el puente es simple:

- Login: si ya hay sesión de Kratos (`g.usuario_id`, resuelto por el
  `before_request` de `app/main.py`), se acepta sin mostrar nada; si no,
  se manda al login de Kratos de siempre y se vuelve aquí al terminar.
- Consentimiento: se acepta siempre sin pantalla intermedia — los únicos
  clientes OAuth2 de este Hydra son los que registra Guilda Work
  (`scripts/registrar_cliente_hydra.py`), todos con `skip_consent: true`.
"""
from urllib.parse import quote

from flask import Blueprint, abort, g, redirect, request

from . import db, hydra

hydra_bp = Blueprint("hydra_bridge", __name__, url_prefix="/hydra")


@hydra_bp.route("/login")
def hydra_login():
    challenge = request.args.get("login_challenge")
    if not challenge:
        abort(400)

    login_request = hydra.obtener_login_request(challenge)
    if login_request.get("skip"):
        return redirect(hydra.aceptar_login_request(challenge, login_request["subject"]))

    if g.usuario_id:
        usuario = db.obtener_usuario(g.usuario_id)
        subject = usuario["kratos_identity_id"] or str(usuario["id"])
        return redirect(hydra.aceptar_login_request(challenge, subject))

    return redirect(f"/.ory/self-service/login/browser?return_to={quote(request.url, safe='')}")


@hydra_bp.route("/consent")
def hydra_consent():
    challenge = request.args.get("consent_challenge")
    if not challenge:
        abort(400)

    consent_request = hydra.obtener_consent_request(challenge)
    usuario = db.usuario_por_kratos_id(consent_request.get("subject"))
    email = usuario["email"] if usuario else ""
    redirect_to = hydra.aceptar_consent_request(
        challenge, scopes=consent_request.get("requested_scope", []), email=email
    )
    return redirect(redirect_to)


@hydra_bp.route("/logout")
def hydra_logout():
    challenge = request.args.get("logout_challenge")
    if not challenge:
        abort(400)
    return redirect(hydra.aceptar_logout_request(challenge))
