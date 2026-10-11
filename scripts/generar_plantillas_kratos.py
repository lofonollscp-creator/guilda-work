"""Genera las plantillas de correo de Kratos (código de recuperación y de verificación) con el MISMO diseño que el resto de correos de Guilda Work
(app/correo_diseno.py), en castellano, catalán, inglés y francés. Salida: deploy/kratos/courier-templates/, que `kratos.yml` usa con
`courier.template_override_path`.

    .venv/bin/python scripts/generar_plantillas_kratos.py

Después, para que Kratos las lea (solo se cargan al arrancar):  docker compose up -d --force-recreate kratos

IDIOMA: Kratos no tiene plantillas por idioma, pero sí un campo `transient_payload` en el envío del formulario que le llega a la plantilla como
`.TransientPayload`. El proxy de Kratos de la app (app/rutas_kratos_proxy.py) añade `{"lang": "<idioma de la pantalla>"}` al pedir una recuperación
o una verificación, y cada plantilla elige su variante con un `if`. Sin idioma (o uno desconocido) sale la versión en castellano, que lleva además
una línea de seguridad en los cuatro idiomas. El asunto NO lleva el código (los asuntos se ven en notificaciones de pantalla bloqueada y en listados)."""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import correo_diseno  # noqa: E402

DESTINO = RAIZ / "deploy" / "kratos" / "courier-templates"
IDIOMAS = ("es", "ca", "en", "fr")

SEGURIDAD_MULTI = (
    "Si no has sido tú, ignora este correo: no pasará nada.\n"
    "Si no has estat tu, ignora aquest correu. · If this wasn't you, just ignore this email. · Si ce n'est pas vous, ignorez ce message."
)
INVALIDA_MULTI = (
    "Si no has sido tú, ignora este correo.\n"
    "Si no has estat tu, ignora aquest correu. · If this wasn't you, just ignore this email. · Si ce n'est pas vous, ignorez ce message."
)
PIES = {"es": "Guilda Work · el software de gestión de tu gestoría", "ca": "Guilda Work · el programari de gestió de la teva gestoria",
        "en": "Guilda Work · management software for your firm", "fr": "Guilda Work · le logiciel de gestion de votre cabinet"}

# código: marca de Kratos que se imprime en grande (None = el correo no lleva código)
PLANTILLAS = {
    "recovery_code/valid": {
        "codigo": "{{ .RecoveryCode }}",
        "es": dict(asunto="Recupera tu contraseña de Guilda Work", titulo="Recupera tu contraseña", aviso=SEGURIDAD_MULTI,
                   parrafos=["Has pedido recuperar el acceso a tu cuenta de Guilda Work. Introduce este código en la pantalla de recuperación; caduca en 15 minutos:"]),
        "ca": dict(asunto="Recupera la teva contrasenya de Guilda Work", titulo="Recupera la teva contrasenya", aviso="Si no has estat tu, ignora aquest correu: no passarà res.",
                   parrafos=["Has demanat recuperar l'accés al teu compte de Guilda Work. Introdueix aquest codi a la pantalla de recuperació; caduca en 15 minuts:"]),
        "en": dict(asunto="Recover your Guilda Work password", titulo="Recover your password", aviso="If this wasn't you, just ignore this email: nothing will happen.",
                   parrafos=["You asked to recover access to your Guilda Work account. Enter this code on the recovery screen; it expires in 15 minutes:"]),
        "fr": dict(asunto="Récupérez votre mot de passe Guilda Work", titulo="Récupérez votre mot de passe", aviso="Si ce n'est pas vous, ignorez ce message : il ne se passera rien.",
                   parrafos=["Vous avez demandé à récupérer l'accès à votre compte Guilda Work. Saisissez ce code sur l'écran de récupération ; il expire dans 15 minutes :"]),
    },
    "recovery_code/invalid": {
        "codigo": None,
        "es": dict(asunto="Alguien intentó recuperar una cuenta con este correo", titulo="No encontramos tu cuenta", aviso=INVALIDA_MULTI,
                   parrafos=["Alguien ha pedido recuperar una contraseña con esta dirección de correo, pero no hay ninguna cuenta de Guilda Work con ella.",
                             "Si fuiste tú, prueba con el email con el que te registraste (puede ser otro). Si necesitas ayuda, escríbenos."]),
        "ca": dict(asunto="Algú ha intentat recuperar un compte amb aquest correu", titulo="No trobem el teu compte", aviso="Si no has estat tu, ignora aquest correu.",
                   parrafos=["Algú ha demanat recuperar una contrasenya amb aquesta adreça de correu, però no hi ha cap compte de Guilda Work amb ella.",
                             "Si has estat tu, prova amb l'email amb què et vas registrar (pot ser un altre). Si necessites ajuda, escriu-nos."]),
        "en": dict(asunto="Someone tried to recover an account with this email", titulo="We couldn't find your account", aviso="If this wasn't you, just ignore this email.",
                   parrafos=["Someone asked to recover a password with this email address, but there is no Guilda Work account with it.",
                             "If it was you, try the email you signed up with (it may be a different one). If you need help, write to us."]),
        "fr": dict(asunto="Quelqu'un a tenté de récupérer un compte avec cet email", titulo="Nous ne trouvons pas votre compte", aviso="Si ce n'est pas vous, ignorez ce message.",
                   parrafos=["Quelqu'un a demandé à récupérer un mot de passe avec cette adresse email, mais aucun compte Guilda Work n'y est associé.",
                             "Si c'était vous, essayez avec l'email utilisé à l'inscription (ce peut être un autre). Si vous avez besoin d'aide, écrivez-nous."]),
    },
    "verification_code/valid": {
        "codigo": "{{ .VerificationCode }}",
        "es": dict(asunto="Verifica tu correo de Guilda Work", titulo="Verifica tu correo", aviso=SEGURIDAD_MULTI,
                   parrafos=["Introduce este código para confirmar que esta dirección de correo es tuya; caduca en 15 minutos:"]),
        "ca": dict(asunto="Verifica el teu correu de Guilda Work", titulo="Verifica el teu correu", aviso="Si no has estat tu, ignora aquest correu: no passarà res.",
                   parrafos=["Introdueix aquest codi per confirmar que aquesta adreça de correu és teva; caduca en 15 minuts:"]),
        "en": dict(asunto="Verify your Guilda Work email", titulo="Verify your email", aviso="If this wasn't you, just ignore this email: nothing will happen.",
                   parrafos=["Enter this code to confirm that this email address is yours; it expires in 15 minutes:"]),
        "fr": dict(asunto="Vérifiez votre email Guilda Work", titulo="Vérifiez votre email", aviso="Si ce n'est pas vous, ignorez ce message : il ne se passera rien.",
                   parrafos=["Saisissez ce code pour confirmer que cette adresse email est bien la vôtre ; il expire dans 15 minutes :"]),
    },
    "verification_code/invalid": {
        "codigo": None,
        "es": dict(asunto="Alguien intentó verificar este correo en Guilda Work", titulo="No encontramos tu cuenta", aviso=INVALIDA_MULTI,
                   parrafos=["Alguien ha pedido verificar esta dirección de correo, pero no hay ninguna cuenta de Guilda Work con ella."]),
        "ca": dict(asunto="Algú ha intentat verificar aquest correu a Guilda Work", titulo="No trobem el teu compte", aviso="Si no has estat tu, ignora aquest correu.",
                   parrafos=["Algú ha demanat verificar aquesta adreça de correu, però no hi ha cap compte de Guilda Work amb ella."]),
        "en": dict(asunto="Someone tried to verify this email in Guilda Work", titulo="We couldn't find your account", aviso="If this wasn't you, just ignore this email.",
                   parrafos=["Someone asked to verify this email address, but there is no Guilda Work account with it."]),
        "fr": dict(asunto="Quelqu'un a tenté de vérifier cet email dans Guilda Work", titulo="Nous ne trouvons pas votre compte", aviso="Si ce n'est pas vous, ignorez ce message.",
                   parrafos=["Quelqu'un a demandé à vérifier cette adresse email, mais aucun compte Guilda Work n'y est associé."]),
    },
}

ELEGIR = '{{- $l := printf "%v" (index .TransientPayload "lang") -}}'


def _variantes(textos: dict) -> str:
    """`{{ if eq $l "ca" }}…{{ else if … }}…{{ else }}castellano{{ end }}`: el castellano es la versión por defecto."""
    ramas = [f'{{{{- if eq $l "{i}" -}}}}{textos[i]}' for i in ("ca", "en", "fr")]
    return ELEGIR + "".join(r if n == 0 else r.replace("{{- if", "{{- else if", 1) for n, r in enumerate(ramas)) + "{{- else -}}" + textos["es"] + "{{- end -}}"


def main() -> None:
    for ruta, definicion in PLANTILLAS.items():
        carpeta = DESTINO / ruta
        carpeta.mkdir(parents=True, exist_ok=True)
        asuntos, planos, htmls = {}, {}, {}
        for i in IDIOMAS:
            t = definicion[i]
            plano, html = correo_diseno.construir(t["titulo"], t["parrafos"], codigo=definicion["codigo"], aviso=t["aviso"], html_crudo=True,
                                                  preencabezado=t["titulo"], idioma=i, pie=PIES[i])
            # En el HTML los saltos de línea del aviso (solo la versión en castellano lleva varias líneas) pasan a <br>
            html = html.replace(t["aviso"], t["aviso"].replace("\n", "<br>"))
            asuntos[i], planos[i], htmls[i] = t["asunto"], plano, html
        (carpeta / "email.subject.gotmpl").write_text(_variantes(asuntos) + "\n", encoding="utf-8")
        (carpeta / "email.body.gotmpl").write_text(_variantes(htmls), encoding="utf-8")
        (carpeta / "email.body.plaintext.gotmpl").write_text(_variantes(planos), encoding="utf-8")
        print("escrita", carpeta.relative_to(RAIZ))


if __name__ == "__main__":
    main()
