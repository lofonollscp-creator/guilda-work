"""Genera las plantillas de correo de Kratos (código de recuperación y de verificación) con el MISMO diseño que el resto de correos de Guilda Work
(app/correo_diseno.py). Salida: deploy/kratos/courier-templates/, que `kratos.yml` usa con `courier.template_override_path`.

    .venv/bin/python scripts/generar_plantillas_kratos.py

Después, para que Kratos las lea (solo se cargan al arrancar):  docker compose up -d --force-recreate kratos
Kratos no conoce el idioma de la persona al mandar estos correos: el texto va en castellano con una línea de seguridad en los cuatro idiomas."""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import correo_diseno  # noqa: E402

DESTINO = RAIZ / "deploy" / "kratos" / "courier-templates"

SEGURIDAD = (
    "Si no has sido tú, ignora este correo: no pasará nada.<br>"
    "Si no has estat tu, ignora aquest correu. · If this wasn't you, just ignore this email. · Si ce n'est pas vous, ignorez ce message."
)
INVALIDA = (
    "Si no has sido tú, ignora este correo.<br>"
    "Si no has estat tu, ignora aquest correu. · If this wasn't you, just ignore this email. · Si ce n'est pas vous, ignorez ce message."
)

PLANTILLAS = {
    "recovery_code/valid": dict(
        asunto="Tu código para recuperar la contraseña de Guilda Work: {{ .RecoveryCode }}",
        titulo="Recupera tu contraseña",
        parrafos=["Has pedido recuperar el acceso a tu cuenta de Guilda Work. Introduce este código en la pantalla de recuperación; caduca en 15 minutos:"],
        codigo="{{ .RecoveryCode }}", aviso=SEGURIDAD),
    "recovery_code/invalid": dict(
        asunto="Intento de recuperar una cuenta que no existe en Guilda Work",
        titulo="No encontramos tu cuenta",
        parrafos=["Alguien ha pedido recuperar una contraseña con esta dirección de correo, pero no hay ninguna cuenta de Guilda Work con ella.",
                  "Si fuiste tú, prueba con el email con el que te registraste (puede ser otro). Si necesitas ayuda, escríbenos."],
        codigo=None, aviso=INVALIDA),
    "verification_code/valid": dict(
        asunto="Tu código para verificar el correo de Guilda Work: {{ .VerificationCode }}",
        titulo="Verifica tu correo",
        parrafos=["Introduce este código para confirmar que esta dirección de correo es tuya; caduca en 15 minutos:"],
        codigo="{{ .VerificationCode }}", aviso=SEGURIDAD),
    "verification_code/invalid": dict(
        asunto="Intento de verificar una dirección que no está en Guilda Work",
        titulo="No encontramos tu cuenta",
        parrafos=["Alguien ha pedido verificar esta dirección de correo, pero no hay ninguna cuenta de Guilda Work con ella."],
        codigo=None, aviso=INVALIDA),
}


def main() -> None:
    for ruta, p in PLANTILLAS.items():
        carpeta = DESTINO / ruta
        carpeta.mkdir(parents=True, exist_ok=True)
        plano, html = correo_diseno.construir(p["titulo"], p["parrafos"], codigo=p["codigo"], aviso=p["aviso"].replace("<br>", "\n"), html_crudo=True, preencabezado=p["titulo"])
        # El aviso del HTML lleva <br> reales (html_crudo no los convierte); el texto plano, saltos de línea
        html = html.replace(p["aviso"].replace("<br>", "\n"), p["aviso"])
        (carpeta / "email.subject.gotmpl").write_text(p["asunto"] + "\n", encoding="utf-8")
        (carpeta / "email.body.gotmpl").write_text(html, encoding="utf-8")
        (carpeta / "email.body.plaintext.gotmpl").write_text(plano, encoding="utf-8")
        print("escrita", carpeta.relative_to(RAIZ))


if __name__ == "__main__":
    main()
