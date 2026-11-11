# Passkeys para el equipo (W14): por qué no están activadas y cómo se activarán

**Estado:** el portal de clientes ya tiene passkeys (`app/portal_passkeys.py`). El equipo entra por Kratos con contraseña y, opcionalmente, TOTP + códigos de recuperación. Para el equipo se ha hecho lo seguro: la pantalla **Seguridad → Acceso del equipo** (`app/seguridad_equipo.py`) dice quién tiene el segundo factor. Las passkeys del equipo **no se han activado** porque tocan el inicio de sesión de todas las personas y no se pueden comprobar sin un autenticador real y un Kratos de pruebas.

## Qué hay que hacer

1. **Kratos** (`deploy/kratos/kratos.yml`): activar `selfservice.methods.webauthn` con `passwordless: true`, `rp.id` = el dominio de la aplicación (sin puerto) y `rp.origins` con la URL pública. Es un cambio de configuración que **exige reiniciar Kratos**: si queda mal, Kratos no arranca y nadie puede entrar.
2. **Esquema de identidad** (`deploy/kratos/identity.schema.json`): marcar el correo con `ory.sh/kratos.credentials.webauthn.identifier: true` para poder iniciar sesión solo con passkey.
3. **Pantallas de acceso** (`app/rutas_kratos_proxy.py` y plantillas de login/ajustes): Kratos devuelve para WebAuthn nodos con `onclick` y un script `/.well-known/ory/webauthn.js`. Nuestra CSP prohíbe manejadores en línea, así que hay que enlazar esos botones desde un fichero JS propio (leyendo el `onclick` como datos, nunca ejecutándolo) y servir el script de Kratos desde el propio dominio.
4. **Ajustes → Seguridad**: alta, nombre y baja de passkeys de cada persona; y con passkey, `aal2` ya se cumple (sin pedir TOTP).

## Cómo probarlo antes de tocar producción

- Un Kratos de pruebas (otro contenedor, otro dominio local) con la misma configuración.
- Playwright con un **autenticador virtual** (`CDP: WebAuthn.addVirtualAuthenticator`) para registrar y usar una passkey de punta a punta.
- Plan de vuelta atrás: guardar `kratos.yml` y el esquema antes de cambiarlos, y comprobar `kratos --config … validate` antes de reiniciar.

## Decisión pendiente

Que alguien con acceso al servidor decida la ventana de cambio (reinicio de Kratos) y tenga a mano la copia de `kratos.yml`. Hasta entonces, lo que protege al equipo es el segundo factor TOTP, y la nueva pantalla ayuda a exigirlo a la dirección.
