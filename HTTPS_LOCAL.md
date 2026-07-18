# HTTPS local para desarrollo (Fase 8)

Algunos flujos de login (Outline, Element) necesitan HTTPS real para
completarse — no por nada de este proyecto, sino porque Outline exige
cookies `secure` en producción y la librería OIDC de Synapse exige
`https://` de verdad en sus endpoints. En local, con todo por
`http://127.0.0.1`, esos flujos se quedan bloqueados justo en el último
paso (ver Fase 7b y Fase 7d del plan de integraciones). Esto monta un
Caddy local con su propia autoridad de certificación de confianza para
poder verificar esos flujos de principio a fin sin necesitar el VPS.

**No es el camino por defecto** — `docker compose up -d` normal nunca
levanta esto (va detrás de un perfil de Docker Compose). Solo hace falta
cuando quieras verificar de verdad un login OIDC completo en local.

## 1. Levantar Caddy local

```bash
docker compose --profile https-local up -d caddy-local
```

La primera vez genera su propia CA (autoridad de certificación) dentro
del volumen `caddy-local-data` y emite certificados para `app.localhost`,
`hydra.localhost`, `outline.localhost`, `chat.localhost` y
`matrix.localhost` — dominios que el propio sistema operativo/navegador
resuelven solos a `127.0.0.1` (es un TLD especial, RFC 6761, no hace
falta tocar `hosts`).

## 2. Confiar la CA (una sola vez)

```bash
docker cp guilda-work-caddy-local:/data/caddy/pki/authorities/local/root.crt ./caddy-local-root.crt
```

En Windows (PowerShell):

```powershell
certutil -addstore -user Root .\caddy-local-root.crt
```

Bórralo después de importarlo (`rm caddy-local-root.crt`) — no hace
falta guardarlo, se puede volver a extraer del contenedor cuando haga
falta. Solo hay que confiarlo una vez por máquina de desarrollo (queda
instalado en el almacén de Windows hasta que lo quites tú mismo); se
regenera solo si borras el volumen `caddy-local-data`, en cuyo caso hay
que repetir este paso.

⚠️ Esto instala la CA en el almacén de certificados del **navegador real
del sistema** (Chrome/Edge en Windows leen el almacén de Windows). Un
navegador aislado/en sandbox (como el que usa Claude para verificar
visualmente) puede no compartir ese almacén — si ves
`ERR_CERT_AUTHORITY_INVALID` ahí, no es un fallo del montaje, es que ese
navegador en concreto no ve la CA. Compruébalo en tu Chrome/Edge normal.

## 3. Apuntar los servicios al HTTPS local

Esto es temporal (no toques el `.env` de siempre) — expórtalo en la
sesión de terminal donde vayas a hacer la prueba:

```bash
export GUILDA_ORIGIN="https://app.localhost:8443"
export HYDRA_PUBLIC_ORIGIN="https://hydra.localhost:8443"
export OUTLINE_PUBLIC_ORIGIN="https://outline.localhost:8443"
export OUTLINE_FORCE_HTTPS="true"
```

El `redirect_uri` con el que registraste tu cliente OAuth2 de Outline
(Fase 7b.3) apunta a `http://127.0.0.1:3001/...` — no sirve aquí. Registra
uno nuevo específico para esta verificación (Hydra permite tener varios
clientes a la vez sin pisarse):

```bash
.venv/bin/python scripts/registrar_cliente_hydra.py --nombre outline-https-local \
  --redirect-uri https://outline.localhost:8443/auth/oidc.callback
```

Copia el `client_id`/`client_secret` que imprima y expórtalos también:

```bash
export OUTLINE_OIDC_CLIENT_ID="..."
export OUTLINE_OIDC_CLIENT_SECRET="..."
```

Recrea los contenedores que necesitan recoger estas variables:

```bash
docker compose up -d --force-recreate kratos hydra outline
```

## 4. Probar

Navegador real (no el de vista previa): `https://outline.localhost:8443`
→ "Continuar con Guilda Work" → login real de Guilda Work en
`https://app.localhost:8443/login` → de vuelta en Outline ya
autenticado. Necesitas `serve.py` corriendo con `GUILDA_HOST=127.0.0.1`
(el de siempre) para el paso de login.

**✅ Verificado de principio a fin en navegador real** — funciona.

### Bug real encontrado y corregido: cookie de login de Hydra sin `Secure`

La primera vez que se probó esto en un navegador de verdad (no solo con
`curl`), el login se quedaba en bucle en Outline con el error real (visto
en los logs de Hydra): `request_forbidden — No CSRF value available in
the session cookie`. Diagnóstico completo:

- El error lo genera **Hydra**, no Outline — Outline solo reenvía el
  `error`/`error_description` que le llega en la propia URL de vuelta.
- La cookie de Hydra para el login (`ory_hydra_login_csrf_...`) lleva
  `SameSite=None` (la necesita para sobrevivir la ida y vuelta entre
  `hydra.localhost` → `app.localhost` → `hydra.localhost`) — pero Hydra
  la estaba poniendo **sin el atributo `Secure`**, porque veía la
  conexión que le reenvía Caddy como `http` (no confiaba en
  `X-Forwarded-Proto: https`). Chrome y todos los navegadores modernos
  **rechazan en silencio** cualquier cookie `SameSite=None` sin
  `Secure` — nunca llegaba a guardarse, de ahí "no hay ningún valor
  CSRF disponible".
- **Arreglo**: `SERVE_COOKIES_SECURE: "true"` en el servicio `hydra` de
  `docker-compose.yml` (clave real de Ory Hydra: `serve.cookies.secure`,
  "Sets the HTTP Cookie secure flag in development mode") — fuerza el
  flag `Secure` sin depender de que Hydra confíe en la cabecera del
  proxy. Seguro fijarlo siempre a `true`: el puerto de Hydra nunca se
  publica en `0.0.0.0` (solo `127.0.0.1`), así que nada fuera de este
  host puede alcanzarlo sin pasar por HTTPS real de todas formas.
- **Este bug también afecta al VPS** (Caddy allí hace exactamente el
  mismo reenvío en plano) — el arreglo está en `docker-compose.yml`, no
  en nada específico de este mock, así que ya viene aplicado también
  para el despliegue real sin ningún paso adicional en `HOSTING.md`.

## 5. Volver a la normalidad

```bash
docker compose up -d --force-recreate kratos hydra outline   # sin las variables de arriba exportadas
docker compose --profile https-local stop caddy-local
```

## Limitación conocida: Synapse (Element) no se ha verificado con este mock

Synapse necesita, además de todo lo de arriba, que su **propio
contenedor** confíe en la CA de Caddy — no solo el navegador — porque su
librería OIDC (`authlib`) hace las llamadas de token/userinfo/jwks
server-to-server exigiendo HTTPS real. Eso implica inyectar el
certificado de la CA dentro del contenedor de Synapse (vía
`SSL_CERT_FILE` o `update-ca-certificates`) además de resolver
`hydra.localhost`/`matrix.localhost` en la red interna de Docker (ya
resuelto — `caddy-local` tiene alias de red para esto, ver
`docker-compose.yml`). No se ha completado ni verificado en esta sesión
— la vía real, ya probada y funcionando, sigue siendo verificar Element
en el VPS (Fase 7d, sección 8.8 de `HOSTING.md`).
