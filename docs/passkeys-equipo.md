# Passkeys para el equipo (W14)

**Estado:** activas en producción desde el 2026-11-11 (Kratos reiniciado con la configuración nueva). Sin comprobar todavía con un autenticador real (móvil o llave física).

## Qué hace
- En el acceso aparece **Entrar con passkey** (si Kratos las ofrece): un toque con huella, cara o PIN, sin escribir nada.
- En **Ajustes → Contraseña y email** hay una sección **Passkeys** para añadir (con el autenticador del dispositivo) y quitar passkeys.
- Una passkey cuenta como primer factor, igual que la contraseña: quien tiene además la verificación en dos pasos (TOTP) sigue dándola.
- **Seguridad → Acceso del equipo** enseña quién tiene el segundo factor y quién ha registrado alguna passkey.
- La contraseña sigue funcionando: la passkey es una opción más, no obligatoria.
- **Política de acceso (Seguridad → Acceso del equipo):** la dirección puede exigir a todo el equipo segundo factor *o* passkey con una fecha límite (como pronto dentro de 7 días). Hasta esa fecha cada persona que no cumple ve un aviso con los días que le quedan; pasada, solo puede entrar a Ajustes → Contraseña y email (y salir) y el acceso de la app móvil le responde 403 hasta que lo active. Si Kratos no responde, se da por cumplida. Las sesiones de API ya abiertas no se cierran. Código: `app/politica_acceso.py`, migración 055.
- **Avisos a la persona:** al añadir o quitar una passkey, el segundo factor o los códigos de recuperación se le notifica (`app/seguridad_avisos.py`, mediante el proxy `/.ory/`).
- **Panel de salud:** punto «Passkeys del equipo (Kratos)»: ámbar si Kratos deja de ofrecer el método tras un cambio o reinicio.

## Cómo está hecho
1. `deploy/kratos/kratos.yml`: método `passkey` con `rp.id = app.guildawork.com` y `origins = https://app.guildawork.com`. Una passkey solo funciona en ese dominio (el backoffice y el portal de clientes tienen sus propios accesos).
2. `deploy/kratos/identity.schema.json`: el correo lleva `credentials.passkey.display_name`.
3. El script oficial de Kratos (`webauthn.js`) se sirve desde el propio origen a través del proxy `/.ory/` (`kratos.scripts_del_flujo` solo admite scripts de `/.well-known/ory/`); la CSP no cambia. `app/static/kratos_passkeys.js` solo conecta los botones, sin manejadores en línea.
4. En el acceso, la passkey va en un formulario aparte del de la contraseña: `webauthn.js` lee sus campos por nombre y envía el formulario que los contiene. En Ajustes, los campos de la passkey viven solo en su formulario.

## Pruebas
- `tests/test_kratos_passkeys.py`: sin Kratos ni navegador (scripts admitidos, pantallas, configuración real).
- `tests/e2e/test_passkeys_equipo.py` (con `scripts/probar_navegador.sh`): arranca un **Kratos real en Docker** con la configuración de `deploy/kratos` (solo cambian puertos, dominio y base en memoria), usa un autenticador virtual del navegador y comprueba: entrar con contraseña → añadir passkey → salir → entrar solo con la passkey. Se salta si no hay Docker o imagen.

## Puesta en marcha (producción)
1. Copia de seguridad: `cp deploy/kratos/kratos.yml deploy/kratos/kratos.yml.bak && cp deploy/kratos/identity.schema.json deploy/kratos/identity.schema.json.bak` (o `git` ya tiene la versión anterior).
2. Desplegar el código (la app) y reiniciar los servicios.
3. Reiniciar Kratos para que lea la configuración y el esquema: `docker restart guilda-work-kratos` (unos segundos sin acceso nuevo; las sesiones abiertas siguen).
4. Comprobar: `curl -s localhost:4433/health/ready` y que el acceso muestra **Entrar con passkey**.
5. Vuelta atrás si algo falla: restaurar los dos ficheros y `docker restart guilda-work-kratos`.

## Límites
- Las passkeys son por dispositivo/gestor de contraseñas (iCloud, Google, 1Password…); quien cambie de dominio de la app tendría que registrarlas de nuevo.
- Las cuentas de la API móvil siguen entrando con contraseña (el flujo `api` de Kratos no se ha tocado); el diseño para que entren con passkey está en `docs/passkeys-movil-diseno.md`.
- No se puede quitar la contraseña: se puede *exigir* un segundo factor o una passkey, pero la contraseña sigue siendo el respaldo.
