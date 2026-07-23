# Hosting en un VPS (Fase 3 de la app móvil)

Guía lista para ejecutar el día que decidas contratar un VPS. Mientras
tanto, la vía gratuita para tener la API accesible desde internet es
[`CASERO.md`](CASERO.md) (Tailscale Funnel, sin coste, sin dominio, sobre
tu propio PC). Contratar y pagar el VPS es algo que tienes que hacer tú
— esta guía empieza justo después de tener el servidor creado.

## Elegir proveedor

| Proveedor | Precio aprox./mes | Notas |
|---|---|---|
| **Hetzner Cloud** (CX22) | ~€4,5 | Mejor relación calidad/precio, datacenters en Alemania/Finlandia. Recomendación por defecto si no quieres complicarte. |
| **Contabo** | ~€4-5 | Más RAM/disco por el precio, pero rendimiento más variable (servidores más compartidos). |
| **DigitalOcean** | ~$6 | Muy bien documentado, buena opción si es tu primer VPS. |
| **Oracle Cloud "Always Free"** | Gratis de verdad | 4 núcleos ARM + 24GB RAM gratis para siempre, pero el proceso de alta de cuenta es errático (a veces rechaza tarjetas o "recupera" recursos sin avisar). Vale la pena intentarlo si no te importa la posible fricción inicial. |

Para el uso de esta app (un solo backend Flask + SQLite, tráfico bajo), la
oferta más pequeña de cualquiera de ellos sobra: 1 vCPU / 1-2GB RAM.
Elige **Ubuntu 22.04 o 24.04 LTS** como sistema operativo al crear el
servidor.

## 1. Acceso y hardening básico

```bash
# Desde tu PC, conéctate como root la primera vez:
ssh root@TU_IP

# Crea un usuario normal (no sigas usando root para todo):
adduser guilda
usermod -aG sudo guilda

# Cortafuegos: solo SSH, HTTP y HTTPS
ufw allow OpenSSH
ufw allow 80
ufw allow 443
ufw enable

# Desactiva el login por contraseña (usa solo tu clave SSH) — edita
# /etc/ssh/sshd_config y pon PasswordAuthentication no, luego:
systemctl restart sshd
```

A partir de aquí, conéctate siempre como `guilda`, no como `root`.

**Antes de desactivar `PasswordAuthentication`**, asegúrate de tener tu
clave ya copiada — si no, te quedas fuera. Genera un par de claves en tu
propio equipo (no en el servidor) y cópiala:

```bash
# En tu propio equipo, no en el servidor:
ssh-keygen -t ed25519 -C "tu-email@ejemplo.com"
ssh-copy-id -i ~/.ssh/id_ed25519.pub guilda@TU_IP
```

Si trabajas desde varios equipos (portátil de casa, otro de la
oficina...), repite `ssh-copy-id` con la clave pública de cada uno —
todas quedan añadidas a `~/.ssh/authorized_keys` del usuario `guilda` en
el servidor, sin que haga falta compartir una única clave privada entre
dispositivos.

## 2. Instalar dependencias y traer el código

```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv git

git clone https://github.com/lofonollscp-creator/guilda-work.git
cd guilda-work
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 3. Variables de entorno de producción

```bash
python3.11 -c "import secrets; print(secrets.token_hex(32))"
```

Copia el resultado y créalo como archivo (no lo subas nunca a git):

```bash
sudo tee /etc/guilda-work.env > /dev/null <<'EOF'
GUILDA_SECRET_KEY=pega-aqui-el-valor-generado
GUILDA_HOST=127.0.0.1
GUILDA_PORT=8000
EOF
sudo chmod 600 /etc/guilda-work.env
```

`GUILDA_HOST=127.0.0.1` (no `0.0.0.0`) porque quien de verdad va a estar
expuesto a internet es Caddy, no `serve.py` directamente — `serve.py`
solo escucha en local y Caddy hace de proxy inverso delante.

## 4. Hostname sin dominio propio (sslip.io)

Sin comprar un dominio todavía, usa un hostname que resuelve
automáticamente a la IP de tu servidor — permite que Caddy pida un
certificado Let's Encrypt real sin más:

```
203.0.113.10  →  203-0-113-10.sslip.io
```

(sustituye por la IP real de tu VPS, con guiones en vez de puntos).

## 5. Caddy: proxy inverso con HTTPS automático

Se elige Caddy sobre nginx+certbot porque la configuración es una
`Caddyfile` de 3 líneas y renueva los certificados solo, sin cron.

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

Copia la plantilla [`deploy/Caddyfile`](deploy/Caddyfile) a
`/etc/caddy/Caddyfile`, sustituye `HOSTNAME` por tu `*.sslip.io` (o tu
dominio real más adelante), y:

```bash
sudo systemctl reload caddy
```

La plantilla ya trae un subdominio por servicio (`app.`, `hydra.`,
`outline.`, y opcionalmente `metabase.`/`n8n.`/`minio.`) — hace falta si
en algún momento despliegas también el resto del stack de Docker (ver
sección "Desplegar el resto del stack" más abajo). Si por ahora solo vas
a tener `serve.py` funcionando, puedes borrar los bloques que no uses
todavía y añadirlos cuando le toque el turno a cada pieza.

## 6. systemd: que `serve.py` arranque solo y se reinicie si muere

Copia la plantilla [`deploy/guilda-work.service`](deploy/guilda-work.service)
a `/etc/systemd/system/guilda-work.service`, ajusta `USUARIO` y las rutas
a las tuyas, y:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now guilda-work
sudo systemctl status guilda-work
```

## 7. Verificar

```bash
curl https://app.tu-hostname.sslip.io/api/v1/categorias
```

Debería responder `401` con `{"ok": false, "error": "Token inválido o
ausente."}` — confirma que Caddy y `serve.py` están sirviendo tráfico real
con HTTPS válido.

## 8. Desplegar el resto del stack (Metabase/MinIO/n8n/Kratos/Hydra/Outline/Element+Synapse)

Todo esto vive en `docker-compose.yml`, ya en el repo que clonaste en el
paso 2 — no hace falta clonar nada aparte. Los puertos que publica cada
contenedor están fijados a `127.0.0.1` a propósito (ver la cabecera del
propio `docker-compose.yml`): Docker manipula `iptables` directamente al
publicar puertos, así que un puerto publicado en `0.0.0.0` **salta por
encima de `ufw`** — con `127.0.0.1:` explícito, la única puerta de
entrada real desde internet es Caddy (que sí corre en el host y alcanza
`localhost`).

### 8.1 Instalar Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker guilda
# cierra sesión y vuelve a entrar para que el grupo surta efecto
```

### 8.2 Variables de entorno del stack

```bash
cd ~/guilda-work
python3.11 -c "import secrets; print(secrets.token_hex(32))"   # repite para cada secreto
```

Crea `.env` (NUNCA se sube a git, ya está en `.gitignore`) con, como
mínimo:

```bash
# Contraseñas propias, una por servicio — no dejes los valores por
# defecto del docker-compose.yml en un servidor real:
MINIO_ROOT_PASSWORD=...
KRATOS_DB_PASSWORD=...
HYDRA_DB_PASSWORD=...
HYDRA_SYSTEM_SECRET=...          # 32+ caracteres
OUTLINE_DB_PASSWORD=...
OUTLINE_SECRET_KEY=...           # openssl rand -hex 32
OUTLINE_UTILS_SECRET=...         # openssl rand -hex 32

# Orígenes públicos — sustituye por tu hostname real de sslip.io o dominio
GUILDA_ORIGIN=https://app.tu-hostname.sslip.io
HYDRA_PUBLIC_ORIGIN=https://hydra.tu-hostname.sslip.io
OUTLINE_PUBLIC_ORIGIN=https://outline.tu-hostname.sslip.io
OUTLINE_FORCE_HTTPS=true

# Se rellenan en el paso 8.4, tras registrar el cliente OAuth2 de Outline
OUTLINE_OIDC_CLIENT_ID=
OUTLINE_OIDC_CLIENT_SECRET=
```

### 8.3 Arrancar Kratos + Hydra primero (Outline los necesita ya arriba)

```bash
docker compose up -d postgres-kratos kratos-migrate kratos postgres-hydra hydra-migrate hydra
curl http://127.0.0.1:4433/health/ready   # 200
curl http://127.0.0.1:4445/admin/health/ready   # 200
```

### 8.4 Registrar el cliente OAuth2 de Outline

```bash
.venv/bin/python scripts/registrar_cliente_hydra.py --nombre outline \
  --redirect-uri https://outline.tu-hostname.sslip.io/auth/oidc.callback
```

Copia el `client_id`/`client_secret` que imprime a `OUTLINE_OIDC_CLIENT_ID`/
`OUTLINE_OIDC_CLIENT_SECRET` en `.env`.

### 8.5 MinIO + bucket de Outline

```bash
docker compose up -d minio
docker run --rm --network guilda-work_default --entrypoint sh minio/mc -c \
  "mc alias set localminio http://minio:9000 guilda_admin \$MINIO_ROOT_PASSWORD && \
   mc mb -p localminio/outline-uploads"
```

(el nombre de la red puede variar según el nombre de la carpeta del
repo — `docker network ls` para confirmarlo si el comando falla).

### 8.6 Arrancar Outline y el resto

```bash
docker compose up -d
docker compose ps   # todo "Up"/"healthy"
```

### 8.7 Verificar

- `curl https://hydra.tu-hostname.sslip.io/health/ready` → `200`.
- Navegador: `https://app.tu-hostname.sslip.io/login` — mismo login de
  siempre, ahora con HTTPS real.
- Navegador: `https://outline.tu-hostname.sslip.io` → "Continuar con
  Guilda Work" → a diferencia de la verificación local (que se quedaba
  bloqueada por exigir HTTPS), aquí Caddy sí da HTTPS de verdad, así que
  el login completo debería funcionar de principio a fin.

### 8.8 Element + Synapse (chat)

A diferencia de Kratos/Hydra/Outline, Synapse **no** tiene ninguna
convención de variables de entorno para sobreescribir su configuración
— por eso `deploy/synapse/guilda-overrides.yaml` (el archivo real, con
el `client_secret` de Hydra) está en `.gitignore` y no llega con el
`git clone`. Hay que crearlo a mano, una vez, en el servidor:

```bash
cd ~/guilda-work
cp deploy/synapse/guilda-overrides.yaml.example deploy/synapse/guilda-overrides.yaml
```

Añade a `.env` (repite el patrón de contraseñas del paso 8.2):

```bash
SYNAPSE_DB_PASSWORD=...
SYNAPSE_SERVER_NAME=chat.tu-hostname.sslip.io
```

Levanta Postgres primero y registra el cliente OAuth2 de Element (mismo
script que Outline en 8.4):

```bash
docker compose up -d postgres-synapse
.venv/bin/python scripts/registrar_cliente_hydra.py --nombre element \
  --redirect-uri https://matrix.tu-hostname.sslip.io/_synapse/client/oidc/callback
```

Edita `deploy/synapse/guilda-overrides.yaml` (el real, no el `.example`)
con un editor de texto (`nano deploy/synapse/guilda-overrides.yaml`) y
rellena, dentro del bloque `oidc_providers`:

- `client_id` / `client_secret`: los que acaba de imprimir el comando de
  arriba.
- **Las cuatro URLs de Hydra** (`issuer`, `authorization_endpoint`,
  `token_endpoint`, `userinfo_endpoint`, `jwks_uri`) — sustitúyelas
  TODAS por `https://hydra.tu-hostname.sslip.io/` seguido de la ruta que
  ya tenga cada una (p. ej. `token_endpoint:
  "https://hydra.tu-hostname.sslip.io/oauth2/token"`). Es importante que
  sean las cinco `https://`, no el hostname interno de Docker
  (`http://hydra:4444/...`) que usa el archivo por defecto para pruebas
  en local — la librería OIDC de Synapse (`authlib`) rechaza cualquier
  URL que no sea HTTPS de verdad para estos tres endpoints, es la razón
  por la que la verificación en local (ver el plan de la Fase 7d) se
  quedó bloqueada justo en este punto.
- `public_baseurl` (al principio del archivo): cambia
  `http://127.0.0.1:8008/` por `https://matrix.tu-hostname.sslip.io/`.

El `.example` ya trae `listeners: ... x_forwarded: true` — imprescindible
para que el login SSO funcione detrás de Caddy (sin esto, Synapse no
confía en `X-Forwarded-Proto` y el botón de login entra en un bucle
infinito de redirecciones a sí mismo; encontrado y corregido verificando
Element con el mock de HTTPS local, ver `HTTPS_LOCAL.md`). **Si ya tenías
Element desplegado antes de este cambio**, añade ese bloque a tu
`guilda-overrides.yaml` real y reinicia Synapse
(`docker compose up -d --force-recreate synapse`) — esto es
probablemente lo que causaba el error de login de Element de las
primeras pruebas.

Arranca el resto:

```bash
docker compose up -d postgres-synapse synapse-migrate-config synapse element-web
docker compose up -d   # o simplemente esto, que arranca todo lo que falte
```

`synapse-migrate-config` genera `homeserver.yaml` la primera vez y
termina solo (no se reinicia) — si `synapse` no arranca, comprueba antes
que ese paso haya terminado bien (`docker compose logs synapse-migrate-config`).

Verificar:
- `curl https://matrix.tu-hostname.sslip.io/_matrix/client/versions` → `200`.
- Navegador: `https://chat.tu-hostname.sslip.io` → "Iniciar sesión" →
  "Continuar con Guilda Work" → login real de Guilda Work → de vuelta
  dentro de Element ya autenticado (a diferencia de la verificación
  local, que se quedaba bloqueada en el intercambio de token por la
  misma exigencia de HTTPS de arriba — aquí sí hay HTTPS real, así que
  el login completo debería funcionar de principio a fin).
- Crear una sala y enviar un mensaje, para confirmar que Synapse
  funciona de extremo a extremo y no solo el login.

### 8.9 Página de Herramientas (Fase 7e)

`/herramientas` (icono en el rail lateral de Guilda Work) enlaza a todo
lo de arriba — por defecto apunta a los puertos de desarrollo local
(`127.0.0.1:...`), hay que decirle las URLs públicas reales. Esto lo lee
`serve.py`, así que va en `/etc/guilda-work.env` (el del paso 3), no en
el `.env` de Docker:

```bash
sudo tee -a /etc/guilda-work.env > /dev/null << 'EOF'
HERRAMIENTA_OUTLINE_URL=https://outline.tu-hostname.sslip.io
HERRAMIENTA_ELEMENT_URL=https://chat.tu-hostname.sslip.io
HERRAMIENTA_METABASE_URL=https://metabase.tu-hostname.sslip.io
HERRAMIENTA_N8N_URL=https://n8n.tu-hostname.sslip.io
HERRAMIENTA_MINIO_URL=https://minio.tu-hostname.sslip.io
HERRAMIENTA_OPENPROJECT_URL=https://openproject.tu-hostname.sslip.io
HERRAMIENTA_CHATWOOT_URL=https://chatwoot.tu-hostname.sslip.io
HERRAMIENTA_MATRIX_HOMESERVER_URL=https://matrix.tu-hostname.sslip.io
HERRAMIENTA_VAULTWARDEN_URL=https://vaultwarden.tu-hostname.sslip.io
HERRAMIENTA_UPTIME_KUMA_URL=https://status.tu-hostname.sslip.io
EOF
sudo systemctl restart guilda-work
```

Si alguna de estas herramientas no la vas a desplegar nunca, quítala del
todo de la lista en `app/herramientas.py` — sin la variable de entorno
correspondiente, la página la sigue mostrando igual, apuntando a su
puerto de desarrollo local (`127.0.0.1:...`), que en el VPS no sirve de
nada.

`HERRAMIENTA_MATRIX_HOMESERVER_URL` es distinta de
`HERRAMIENTA_ELEMENT_URL`: esta última es Element-web (la interfaz web,
`chat.*`), la primera es el propio Synapse (`matrix.*`) — la usa el
cliente Matrix nativo de la app móvil (Fase 9), que habla directo con el
homeserver sin pasar por Element-web.

### 8.10 OpenProject (Fase 7f)

Sin SSO (confirmado en su documentación oficial: es un Enterprise
add-on de pago, no está en la edición community) — login aparte con el
usuario administrador que crea el `seeder` la primera vez.

Añade a `.env` (mismo patrón que el resto — genera secretos nuevos, no
reutilices los de otro servicio):

```bash
OPENPROJECT_DB_PASSWORD=...
OPENPROJECT_SECRET_KEY_BASE=...        # openssl rand -hex 64
OPENPROJECT_SEED_ADMIN_USER_PASSWORD=...   # mínimo 10 caracteres
OPENPROJECT_SEED_ADMIN_USER_MAIL=admin@tu-dominio.com
OPENPROJECT_HTTPS=true
OPENPROJECT_HOST_NAME=openproject.tu-hostname.sslip.io
```

Arranca el seeder primero (crea el esquema y el usuario administrador),
luego el resto:

```bash
docker compose up -d postgres-openproject memcached-openproject openproject-seeder
docker compose logs -f openproject-seeder   # espera a que termine (Ctrl+C al ver que sale)
docker compose up -d openproject-web openproject-worker openproject-cron
```

Verificar:
- `curl https://openproject.tu-hostname.sslip.io/` → redirige a `/login`.
- Navegador: entra con `admin` / la contraseña de
  `OPENPROJECT_SEED_ADMIN_USER_PASSWORD` — pide cambiarla en el primer
  inicio de sesión (normal, no es un fallo). Confirma que ves los
  proyectos de ejemplo que trae sembrados ("Scrum project", "Demo
  project") y que puedes crear una tarea nueva en uno de ellos.
- Añade `HERRAMIENTA_OPENPROJECT_URL` al bloque de la sección 8.9 de
  arriba, si no lo hiciste ya.

### 8.11 Chatwoot (Fase 7g)

Sin SSO (confirmado en su documentación oficial: SAML/SSO es un plan
Enterprise de pago, no está en la community edition) — login aparte, con
la cuenta de administrador que crea el propio asistente de primer
arranque (no hay usuario sembrado por variables de entorno como en
OpenProject).

Añade a `.env`:

```bash
CHATWOOT_DB_PASSWORD=...
CHATWOOT_REDIS_PASSWORD=...
CHATWOOT_SECRET_KEY_BASE=...   # openssl rand -hex 64
CHATWOOT_PUBLIC_ORIGIN=https://chatwoot.tu-hostname.sslip.io
```

Arranca el paso de preparación (crea el esquema, `db:chatwoot_prepare`)
antes que la web:

```bash
docker compose up -d postgres-chatwoot redis-chatwoot chatwoot-prepare
docker compose logs -f chatwoot-prepare   # espera a que termine (Ctrl+C al ver que sale)
docker compose up -d chatwoot-web chatwoot-sidekiq
```

Verificar:
- `curl https://chatwoot.tu-hostname.sslip.io/` → `302` (redirige al
  asistente de primer arranque o al login).
- Navegador: completa el asistente de primer arranque (crea la cuenta de
  administrador — nombre, empresa, email, contraseña), inicia sesión, y
  completa el formulario breve de "Please review the following details"
  (rol, industria, tamaño de empresa — son desplegables nativos del
  navegador; si usas un gestor de formularios automatizado ten en cuenta
  que a veces cuesta interactuar con ellos, hazlo a mano si hace falta).
  Después crea una bandeja de entrada (Settings → Inboxes → Add Inbox) y
  envía un mensaje de prueba por el widget de chat para confirmar que
  `chatwoot-sidekiq` también funciona (gran parte de Chatwoot depende de
  trabajos en segundo plano).
- Añade `HERRAMIENTA_CHATWOOT_URL` al bloque de la sección 8.9.

### 8.12 Tenants + widget de soporte de Chatwoot (Fase 7c.3)

Guilda Work incluye un modelo mínimo de "tenants" (organizaciones) para
poder identificar de qué organización viene cada usuario cuando escribe
por el widget de soporte. **No aísla datos** entre tenants — es solo una
etiqueta de agrupación para el backoffice y para Chatwoot, no toca el
resto del esquema ni los permisos.

Gestión por CLI:

```bash
python cli.py crear-tenant "Lueira"
python cli.py listar-tenants
python cli.py asignar-tenant persona@ejemplo.com Lueira
```

(También hay un backoffice web para esto — ver sección 8.13 — la CLI
sigue funcionando igual, útil para scripts o para el primer arranque.)

Para que aparezca la burbuja de "Contactar con soporte" (widget de chat
en vivo de Chatwoot) en Guilda Work:

1. En Chatwoot: Settings → Inboxes → Add Inbox → Website. Dale un nombre
   (p.ej. "Guilda Work") y la URL pública de Guilda Work. Al terminar,
   Chatwoot te da un `website_token` — es el identificador **público**
   del canal (pensado para ir embebido en HTML de cara al navegador, no
   es un secreto).
2. Añade a `.env` (local) o `/etc/guilda-work.env` (VPS):
   ```bash
   CHATWOOT_WEBSITE_TOKEN=<website_token del paso anterior>
   ```
3. (Opcional pero recomendado) En Chatwoot: Settings → Custom Attributes
   → Add Attribute → crea un atributo `tenant` (tipo texto, alcance
   Conversación o Contacto). Sin este paso, Guilda Work sigue mandando el
   nombre del tenant vía `setCustomAttributes()`, pero no se mostrará en
   ningún sitio dentro de Chatwoot porque el atributo no existe.
4. Reinicia el proceso de `serve.py` (o el servicio systemd) para que
   recoja la variable de entorno nueva.

Verificar: inicia sesión en Guilda Work con un usuario que tenga tenant
asignado, confirma que aparece la burbuja de chat en cualquier página, y
que al escribir un mensaje de prueba llega a Chatwoot con el atributo
`tenant` relleno en la conversación.

### 8.13 Backoffice web de tenants y usuarios (Fase 7c)

Página `/backoffice` dentro de la propia Guilda Work para crear/renombrar/
borrar tenants y crear/asignar/quitar usuarios sin pasar por la CLI —
protegida por `usuarios.rol = 'admin'` (columna que existe en el esquema
desde el principio pero hasta ahora no la usaba nadie).

Primer admin (imprescindible, no hay forma de auto-promoverse desde la
UI si no hay ya un admin):

```bash
python cli.py hacer-admin tu-email@ejemplo.com
python cli.py quitar-admin tu-email@ejemplo.com   # por si hace falta revertirlo
```

Una vez dentro de `/backoffice` (aparece un icono nuevo en el rail
lateral solo para administradores):
- Crear/renombrar/borrar tenants (al borrar uno, sus usuarios quedan sin
  tenant asignado, no se borran).
- Crear un usuario nuevo directamente (email + tenant opcional): crea la
  identidad en Kratos con una contraseña temporal generada al vuelo, que
  se muestra **una sola vez** en pantalla para pasársela a esa persona.
  Si están configurados los tokens de la sección 8.15, el mismo botón da
  de alta a esa persona también en OpenProject y Chatwoot (con la misma
  contraseña) y en Metabase (sin contraseña propia, ver 8.15).
- Reasignar el tenant de cualquier usuario desde un desplegable en la
  propia tabla.
- Dar/quitar el rol de admin a otros usuarios (no se puede uno quitar el
  rol a sí mismo, para no quedarse fuera sin nadie más que lo revierta).

### 8.14 `sqlite-web` (extra, opcional)

Herramienta de código abierto ([coleifer/sqlite-web](https://github.com/coleifer/sqlite-web))
para hacer consultas SQL ad-hoc sobre **toda** la base de datos —
deliberadamente separada del backoffice de la sección 8.13: no distingue
tenants/usuarios, no usa el login de Guilda Work (contraseña propia), y
ve tablas sensibles (`tokens_api`, `sesiones`). Por eso el servicio en
`docker-compose.yml` solo escucha en `127.0.0.1` (nunca detrás de
Caddy/dominio público) y monta la base de datos **de solo lectura**
(evita corromper el archivo mientras `serve.py` escribe en él a la vez).

Añade a `.env`:

```bash
SQLITE_WEB_PASSWORD=...
```

```bash
docker compose up -d sqlite-web
```

Acceso solo por túnel SSH, nunca abriendo el puerto al exterior:

```bash
ssh -L 8012:127.0.0.1:8012 tu-usuario@tu-vps
# luego, en tu navegador: http://127.0.0.1:8012
```

### 8.15 Alta automática en OpenProject/Chatwoot/Metabase (Fase 7c)

Cuando el backoffice (sección 8.13) crea un usuario nuevo, puede darlo de
alta también en las herramientas sin SSO — evita repetirlo a mano en
cada una. **n8n se queda fuera**: su edición community no tiene una API
de alta de usuarios con contraseña propia sin invitación por email.

Cada integración es independiente y opcional — si falta su token, esa
herramienta simplemente no se toca (no rompe el alta del resto).

**OpenProject**: inicia sesión, ve a tu cuenta → "Tokens de acceso" →
genera uno, y añádelo a `.env`:
```bash
OPENPROJECT_API_TOKEN=...
```

**Chatwoot**: no tiene UI para esto en la edición self-hosted — se crea
una sola vez por consola de Rails (usa la **Platform API**, que confirma
el email automáticamente, a diferencia del alta normal de agentes):
```bash
docker exec -it guilda-work-chatwoot-web bundle exec rails runner "
  app = PlatformApp.find_or_create_by!(name: 'Guilda Work')
  app.platform_app_permissibles.find_or_create_by!(permissible: Account.find(1))
  puts app.access_token.token
"
```
```bash
CHATWOOT_PLATFORM_API_TOKEN=...   # el token que imprime el comando de arriba
CHATWOOT_ACCOUNT_ID=1             # el id de tu cuenta de Chatwoot, normalmente 1
```

**Metabase** (opcional): Admin → Configuración → Autenticación →
Claves de API → crea una, y añádela:
```bash
METABASE_API_KEY=...
```
Limitación real de Metabase: su API no admite fijar una contraseña
elegida — solo crea la cuenta (email/nombre). La persona tiene que
completar el alta con "¿Olvidaste tu contraseña?" en el login de
Metabase la primera vez.

### 8.16 Vaultwarden (gestor de contraseñas)

Servidor Bitwarden-compatible, código abierto — un solo sitio cifrado
para las contraseñas/tokens de todo este stack (los de Hydra,
OpenProject, Chatwoot, MinIO... en vez de repartidos entre `.env` y
notas sueltas). Sin SSO: la edición gratuita no ofrece OIDC/SAML (eso es
un add-on de pago de Bitwarden) — login aparte, con la cuenta que crees
en su propio primer arranque.

Añade a `.env`:

```bash
VAULTWARDEN_ADMIN_TOKEN=...   # python -c "import secrets; print(secrets.token_urlsafe(48))"
VAULTWARDEN_SIGNUPS_ALLOWED=true   # ponlo a false en cuanto tengas tu cuenta creada
VAULTWARDEN_PUBLIC_ORIGIN=https://vaultwarden.tu-hostname.sslip.io
```

```bash
docker compose up -d vaultwarden
```

Verificar: `curl https://vaultwarden.tu-hostname.sslip.io/alive` → un
timestamp en JSON. Entra por navegador, crea tu cuenta (arriba a la
derecha, "Crear cuenta"), y una vez dentro pon
`VAULTWARDEN_SIGNUPS_ALLOWED=false` en `.env` y reinicia el contenedor
(`docker compose up -d --force-recreate vaultwarden`) para que nadie más
pueda registrarse.

El panel de administración (`/admin`, gestión de usuarios/organización a
nivel de servidor) pide `VAULTWARDEN_ADMIN_TOKEN` — guárdalo tú también
dentro del propio Vaultwarden una vez que lo tengas funcionando.

### 8.17 Uptime Kuma (monitorización)

Avisa si algún contenedor de este stack (ya son unos diez: Kratos,
Hydra, Outline, Synapse, OpenProject, Chatwoot, Metabase, n8n, MinIO,
Vaultwarden) se cae. Sin variables de entorno de credenciales — el
primer acceso por navegador pide crear la cuenta admin directamente ahí.

A propósito NO monta `/var/run/docker.sock` (daría acceso equivalente a
root sobre el host) — los monitores se añaden a mano desde la propia UI,
apuntando a cada servicio por su **nombre interno de Docker** (misma red
que el resto de `docker-compose.yml`, así que Uptime Kuma los alcanza
sin publicar nada nuevo). Sugerencias de monitores HTTP(S)/TCP para
pegar directamente al crearlos ("Añadir un nuevo monitor" → tipo HTTP(s)
o TCP Port):

| Servicio | URL/host a monitorizar |
|---|---|
| Guilda Work | `http://host.docker.internal:8000/login` (corre fuera de Docker) |
| Kratos | `http://kratos:4433/health/ready` |
| Hydra | `http://hydra:4444/health/ready` |
| Outline | `http://outline:3000` |
| Synapse | `http://synapse:8008/health` |
| OpenProject | `http://openproject-web:8080/health_checks/default` |
| Chatwoot | `http://chatwoot-web:3000/` |
| Metabase | `http://metabase:3000/api/health` |
| n8n | `http://n8n:5678/healthz` |
| MinIO | `http://minio:9000/minio/health/live` |
| Vaultwarden | `http://vaultwarden:80/alive` |

```bash
docker compose up -d uptime-kuma
```

Añade a `.env` (opcional, solo si cambias la URL pública por defecto):
```bash
HERRAMIENTA_UPTIME_KUMA_URL=https://status.tu-hostname.sslip.io
```

### 8.18 OpenVPN (acceso VPN al servidor)

Acceso de red completo al VPS por VPN — útil para llegar a paneles que
se quedan a propósito solo en `127.0.0.1` (`sqlite-web`, `/admin` de
Vaultwarden) sin depender de abrir un túnel SSH puntual cada vez, y como
capa extra de defensa en profundidad además del acceso SSH ya descrito
en la sección 1.

A diferencia del resto de servicios de `docker-compose.yml`, este NO se
autoconfigura al arrancar — hace falta inicializar su PKI una sola vez
antes del primer `docker compose up -d openvpn`. Su puerto (1194/UDP) es
la única excepción real a "todo se publica en 127.0.0.1" de este
proyecto: OpenVPN no es HTTP, Caddy no puede hacerle de proxy, así que
la propia VPN es la puerta de entrada de red (mismo criterio ya
aceptado para el puerto 22/SSH vía `ufw allow OpenSSH`).

```bash
ufw allow 1194/udp
```

**Inicialización, una sola vez:**

```bash
docker run -v ovpn-data:/etc/openvpn --rm kylemanna/openvpn \
  ovpn_genconfig -u udp://TU_IP_O_HOSTNAME

# Pide una passphrase para la CA — elígela tú y no la compartas.
docker run -v ovpn-data:/etc/openvpn --rm -it kylemanna/openvpn ovpn_initpki

docker compose up -d openvpn
```

**Generar un cliente** (uno por dispositivo, mismo criterio que las
claves SSH de la sección 1):

```bash
docker run -v ovpn-data:/etc/openvpn --rm -it kylemanna/openvpn \
  easyrsa build-client-full NOMBRE_DISPOSITIVO nopass

docker run -v ovpn-data:/etc/openvpn --rm kylemanna/openvpn \
  ovpn_getclient NOMBRE_DISPOSITIVO > NOMBRE_DISPOSITIVO.ovpn
```

Copia `NOMBRE_DISPOSITIVO.ovpn` a tu equipo e impórtalo en el cliente
oficial [OpenVPN Connect](https://openvpn.net/client/) (Windows/macOS/
Android/iOS) — paso manual, no automatizable desde aquí.

**Revocar un dispositivo** (perdido, robado, o ya no lo usas):

```bash
docker run -v ovpn-data:/etc/openvpn --rm -it kylemanna/openvpn \
  easyrsa revoke NOMBRE_DISPOSITIVO
docker run -v ovpn-data:/etc/openvpn --rm -it kylemanna/openvpn \
  easyrsa gen-crl
docker compose up -d --force-recreate openvpn
```

## 9. Backups (opcional, recomendado)

`app/db.py` ya tiene `hacer_backup_si_hace_falta()`, la misma función que
usa la app de escritorio. Un cron simple que la invoque y copie el
resultado fuera del VPS (a otro almacenamiento barato, o simplemente por
`scp` a tu PC) es suficiente para no depender solo del disco del
servidor:

```bash
# crontab -e (usuario guilda)
0 4 * * * /home/guilda/guilda-work/.venv/bin/python -c "from app import db; db.hacer_backup_si_hace_falta()"
```

## Migrar de sslip.io a un dominio propio

Cuando compres un dominio:
1. Crea un registro DNS **A** para cada subdominio que uses (`app.`,
   `hydra.`, `outline.`, `chat.`, `matrix.`, `openproject.`, `chatwoot.`,
   y los opcionales que tengas activos) apuntando todos a la IP del VPS.
2. Cambia `HOSTNAME` en `/etc/caddy/Caddyfile` por tu dominio (todos los
   bloques comparten el mismo `HOSTNAME`, solo cambia el prefijo de cada
   uno).
3. Actualiza también `GUILDA_ORIGIN`/`HYDRA_PUBLIC_ORIGIN`/
   `OUTLINE_PUBLIC_ORIGIN` en `.env` (sección 8.2) al nuevo dominio, y
   `docker compose up -d` para que los contenedores recojan el cambio.
   Para Synapse (sección 8.8), edita también
   `deploy/synapse/guilda-overrides.yaml` a mano — sus URLs no se leen
   de `.env`.
4. `sudo systemctl reload caddy` — Caddy pide los nuevos certificados solo.

## Fuera de alcance de esta guía

- Sincronizar datos entre esta instancia VPS y la base de datos local del
  PC de escritorio si usas las dos a la vez — hoy serían dos bases de
  datos independientes. Si llega a hacer falta, se plantea como una fase
  aparte.
