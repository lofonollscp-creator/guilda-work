"""Puente de login/consentimiento para Ory Hydra (Fase 7b).

Hydra delega en esta app la decisión de "¿quién es este usuario?" y "¿da su
consentimiento?" — ver `deploy/hydra/hydra.yml` (`urls.login`/`urls.consent`/
`urls.logout` apuntan aquí). Como Guilda Work ya tiene sesiones reales vía
Kratos (Fase 7a, `app/main.py`), el puente es simple:

- Login: si ya hay sesión de Kratos (`g.usuario_id`, resuelto por el
  `before_request` de `app/main.py`), se acepta sin mostrar nada; si no,
  se manda al login de Kratos de siempre y se vuelve aquí al terminar.
- Consentimiento: los clientes propios (`skip_consent: true`, registrados con
  `scripts/registrar_cliente_hydra.py`) se aceptan sin pantalla. Cualquier otro
  —por ejemplo los que se dan de alta solos por Registro Dinámico, como ChatGPT—
  muestra una pantalla en la que la persona permite o deniega.
"""
import secrets
from urllib.parse import quote, urlparse

from flask import Blueprint, abort, g, redirect, render_template, request

from . import cifrado_despacho, db, hydra, kratos

hydra_bp = Blueprint("hydra_bridge", __name__, url_prefix="/hydra")


def _url_login_kratos() -> str:
    """Login de Kratos al que mandar a quien aún no tiene sesión válida aquí. Si ya dio la contraseña pero la cuenta tiene la
    verificación en dos pasos, se pide directamente el segundo factor (`aal=aal2`): sin eso Kratos lo daría por "ya autenticado",
    volvería a esta misma ruta y se entraría en un bucle."""
    aal = "&aal=aal2" if kratos.requiere_aal2(request.cookies) else ""
    return f"/.ory/self-service/login/browser?return_to={quote(request.url, safe='')}{aal}"


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

    return redirect(_url_login_kratos())


def _cliente_de_confianza(consent_request: dict) -> bool:
    """Los clientes propios de Guilda Work (Outline, Element, Drive...) se registran con `skip_consent` y no preguntan.
    Cualquier otro (p. ej. los que se dan de alta solos por Registro Dinámico, como ChatGPT) SÍ debe pedir permiso."""
    cliente = consent_request.get("client") or {}
    return bool(cliente.get("skip_consent"))


def _usuario_del_consent(consent_request: dict):
    subject = consent_request.get("subject")
    usuario = db.usuario_por_kratos_id(subject)
    if usuario is None:
        # Hydra puede saltarse el paso de /hydra/login si ya recuerda una
        # sesión de este mismo usuario iniciada para OTRO cliente OAuth2
        # (remember=true, ver hydra.aceptar_login_request) — en ese caso
        # la petición nunca pasa por _resolver_usuario_actual() de
        # main.py, y la fila local puede no existir todavía aunque la
        # identidad sea real en Kratos. Se provisiona aquí igual que allí.
        identidad = kratos.obtener_identidad(subject)
        if identidad:
            email = identidad.get("traits", {}).get("email", "")
            if email:
                usuario_id = db.crear_usuario_vinculado_a_kratos(email, subject)
                usuario = db.obtener_usuario(usuario_id)
    return usuario


ALCANCE_DOCUMENTOS = "guilda:documentos"


def _pide_documentos_cifrados(consent_request: dict, usuario) -> bool:
    """¿Pide la aplicación el acceso a documentos de un despacho que los tiene cifrados? (en uno sin cifrado no hace falta ninguna concesión)"""
    tenant = db.tenant_de_usuario(usuario["id"]) if usuario else None
    return bool(tenant and ALCANCE_DOCUMENTOS in consent_request.get("requested_scope", []) and cifrado_despacho.esta_activo(tenant["id"]))


def _puede_dar_documentos(usuario) -> bool:
    return bool(usuario) and (db.es_supervisor_tenant(usuario["id"]) or db.es_admin(usuario["id"]))


def _aceptar(challenge: str, consent_request: dict, usuario) -> str:
    """Acepta el consentimiento. Si la aplicación pide `guilda:documentos` y el despacho tiene el cifrado activado, solo un responsable puede concederlo, y solo con
    el despacho desbloqueado: se crea una concesión (la clave del despacho envuelta con un secreto que viaja dentro del token de la aplicación). Si no se puede,
    se acepta el resto de permisos SIN el de documentos (la aplicación sigue funcionando; solo no ve lo cifrado)."""
    tenant = db.tenant_de_usuario(usuario["id"]) if usuario else None
    scopes = list(consent_request.get("requested_scope", []))
    ext = None
    if _pide_documentos_cifrados(consent_request, usuario):
        cliente = consent_request.get("client") or {}
        try:
            if not _puede_dar_documentos(usuario):
                raise cifrado_despacho.DespachoBloqueado("solo un responsable puede conceder el acceso a documentos")
            secreto = secrets.token_urlsafe(32)
            cifrado_despacho.crear_concesion(tenant["id"], usuario["id"], secreto, "oauth", cliente.get("client_name") or cliente.get("client_id") or "Aplicación")
            ext = {"guilda_cs": secreto}
        except cifrado_despacho.DespachoBloqueado:
            scopes = [x for x in scopes if x != ALCANCE_DOCUMENTOS]
    return hydra.aceptar_consent_request(
        challenge,
        scopes=scopes,
        email=usuario["email"] if usuario else "",
        tenant_nombre=tenant["nombre"] if tenant else None,
        **({"ext_access_token": ext} if ext else {}),
    )


@hydra_bp.route("/consent", methods=["GET", "POST"])
def hydra_consent():
    challenge = request.values.get("consent_challenge")
    if not challenge:
        abort(400)

    consent_request = hydra.obtener_consent_request(challenge)
    usuario = _usuario_del_consent(consent_request)

    # Aplicación propia, o el usuario ya la autorizó (Hydra lo recuerda y marca `skip`): sin pantalla.
    if _cliente_de_confianza(consent_request) or consent_request.get("skip"):
        return redirect(_aceptar(challenge, consent_request, usuario))

    # Aplicación de terceros: hace falta que sea la propia persona, con sesión, quien decida.
    if not g.usuario_id:
        return redirect(_url_login_kratos())
    if usuario is None or usuario["id"] != g.usuario_id:
        abort(403)

    pide_docs = _pide_documentos_cifrados(consent_request, usuario)
    tenant = db.tenant_de_usuario(usuario["id"]) if pide_docs else None
    tenant_id = tenant["id"] if tenant else None
    necesita_frase = bool(pide_docs and _puede_dar_documentos(usuario) and not cifrado_despacho.estado(tenant_id)["desbloqueado"])
    if request.method == "POST":
        if request.form.get("decision") == "permitir":
            if necesita_frase and request.form.get("frase"):
                try:
                    cifrado_despacho.desbloquear(tenant_id, usuario["id"], request.form.get("frase"))
                except (cifrado_despacho.ClaveIncorrecta, cifrado_despacho.DemasiadosIntentos, ValueError) as e:
                    cliente = consent_request.get("client") or {}
                    return render_template(
                        "hydra_consentimiento.html", challenge=challenge, usuario=usuario, app_nombre=cliente.get("client_name") or cliente.get("client_id") or "Aplicación sin nombre",
                        app_web=cliente.get("client_uri"), scopes=consent_request.get("requested_scope", []), redirect_hosts=sorted({urlparse(u).netloc for u in cliente.get("redirect_uris", [])}),
                        pide_documentos=True, puede_dar_documentos=True, necesita_frase=True, error=str(e),
                    ), 400
            db.registrar_auditoria(g.usuario_id, "oauth.consentimiento", f"cliente {consent_request.get('client', {}).get('client_id')}: {' '.join(consent_request.get('requested_scope', []))}")
            return redirect(_aceptar(challenge, consent_request, usuario))
        return redirect(hydra.rechazar_consent_request(challenge))

    cliente = consent_request.get("client") or {}
    return render_template(
        "hydra_consentimiento.html", challenge=challenge, usuario=usuario,
        app_nombre=cliente.get("client_name") or cliente.get("client_id") or "Aplicación sin nombre",
        app_web=cliente.get("client_uri"), scopes=consent_request.get("requested_scope", []),
        redirect_hosts=sorted({urlparse(u).netloc for u in cliente.get("redirect_uris", [])}),
        pide_documentos=pide_docs, puede_dar_documentos=bool(pide_docs and _puede_dar_documentos(usuario)), necesita_frase=necesita_frase, error=None,
    )


@hydra_bp.route("/logout")
def hydra_logout():
    challenge = request.args.get("logout_challenge")
    if not challenge:
        abort(400)
    return redirect(hydra.aceptar_logout_request(challenge))
