# Acceso con passkey en la app móvil (diseño, Y9)

**Estado:** solo diseño. No hay código. Hoy la app móvil entra con `POST /api/v1/auth/login` (correo y contraseña, más `codigo_2fa` si la cuenta tiene TOTP) y recibe un token de API.

## Qué se quiere
Que alguien con una passkey registrada en la web (`app.guildawork.com`) pueda entrar en la app móvil con huella, cara o PIN, sin escribir contraseña, y reciba el mismo token de siempre.

## Por qué no es un cambio pequeño
1. **El dominio de la passkey (`rp.id`) es `app.guildawork.com`.** Una app nativa solo puede usar una passkey de un dominio si ese dominio la *declara suya*:
   - iOS: fichero `https://app.guildawork.com/.well-known/apple-app-site-association` con `webcredentials.apps = ["<TEAMID>.<bundle id>"]` y el entitlement *Associated Domains* `webcredentials:app.guildawork.com`.
   - Android: `https://app.guildawork.com/.well-known/assetlinks.json` con el paquete y la huella SHA-256 del certificado de firma, con la relación `delegate_permission/common.get_login_creds`.
   - Además, en `deploy/kratos/kratos.yml`, `selfservice.methods.passkey.config.rp.origins` debe incluir el origen que Kratos verá desde la app (`android:apk-key-hash:…` en Android; en iOS el origen sigue siendo `https://app.guildawork.com`).
2. **El flujo `api` de Kratos** (`/self-service/login/api`) devuelve el desafío WebAuthn en los nodos `passkey_login_trigger` y `passkey_challenge`; la app tiene que pasarlo al gestor de credenciales del sistema (plugin Flutter `passkeys` o `credential_manager`) y devolver la aserción como `passkey_login`. Hoy el servidor hace el login con la API de administración de Kratos (`verificar_credenciales_admin`), que no admite passkeys.
3. **El servidor tendría que hacer de intermediario** (la app no habla con Kratos): `POST /api/v1/auth/passkey/inicio` → crea el flujo `api` y devuelve `{flujo, desafio}`; `POST /api/v1/auth/passkey/fin` → envía la aserción a Kratos, comprueba que el flujo acaba bien, mira la sesión que devuelve (`session_token`), saca la identidad, aplica la política de acceso y los mismos límites de intentos que `/auth/login` y entrega el token de API.
4. **El segundo factor:** una passkey ya es un factor fuerte (posesión + verificación biométrica o PIN). Si la cuenta además tiene TOTP, hay que decidir si la passkey lo sustituye (recomendado, como en la web hoy: Kratos pide AAL2 solo si la configuración lo exige) o no. Decisión pendiente.

## Pasos propuestos (orden)
1. Publicar `apple-app-site-association` y `assetlinks.json` desde la app web (rutas estáticas, sin autenticación; el `TEAMID` y la huella de firma los tiene que aportar quien publica la app en las tiendas).
2. Añadir los orígenes móviles a `kratos.yml` y probar en un Kratos de ensayo (como en `tests/e2e/test_passkeys_equipo.py`).
3. Endpoints de inicio y fin en `app/rutas_api.py` con pruebas que simulen a Kratos (no hay autenticador real en CI).
4. Pantalla de acceso en Flutter con el botón «Entrar con passkey» y el gestor de credenciales; el registro de la passkey sigue haciéndose en la web.
5. Prueba manual con un iPhone y un Android reales antes de activarlo.

## Riesgos
- Sin los ficheros de dominio asociado, la app **no** puede usar la passkey (falla en silencio en el sistema operativo).
- Un `origins` demasiado permisivo en Kratos debilita la protección contra suplantación: solo los orígenes exactos de la app.
- El plugin de passkeys de Flutter exige iOS 16 y Android 9 (API 28) o superiores.
- La política de acceso del despacho (`app/politica_acceso.py`) ya cierra `/auth/login` a quien no cumple pasada la fecha; el flujo nuevo debe pasar por la misma comprobación.

## Qué necesito de la dirección para empezar
- Identificador del paquete Android y del bundle iOS, el `TEAMID` de Apple y la huella SHA-256 del certificado de firma.
- Confirmar que la passkey sustituye al segundo factor en la app (punto 4).
