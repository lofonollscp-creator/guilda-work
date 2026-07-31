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

### 8.19 EspoCRM (CRM) — con SSO y aislamiento real por tenant

CRM de código abierto (AGPL-3.0). Único de los evaluados con OIDC nativo
en el core gratuito — mismo patrón exacto que Outline/Element: Ory Hydra
+ `scripts/registrar_cliente_hydra.py`, sin ningún puente SAML ni pieza
extra.

**El aislamiento entre tenants NO es automático — depende de completar
estos pasos, sobre todo el de Roles.** El id_token que emite Hydra ya
lleva el nombre del tenant en el claim `groups` (`app/hydra.py`,
`app/rutas_hydra.py`), y `app/rutas_backoffice.py: crear_tenant()` ya
crea el Equipo correspondiente en EspoCRM al darlo de alta (vía
`app/espocrm.py`, si `ESPOCRM_API_KEY` está configurada) — pero sin el
paso de Roles de más abajo, cualquier usuario vería los registros de
todos los tenants igual, Equipos o no.

Añade a `.env`:
```bash
ESPOCRM_DB_PASSWORD=...
ESPOCRM_ADMIN_USERNAME=admin
ESPOCRM_ADMIN_PASSWORD=...   # mínimo 8 caracteres, instalación desatendida
ESPOCRM_PUBLIC_ORIGIN=https://crm.tu-hostname.sslip.io
```

```bash
docker compose up -d postgres-espocrm espocrm
```

**Registrar el cliente OAuth2** (mismo comando que ya se usó para
Outline/Element en 8.4/8.8):
```bash
.venv/bin/python scripts/registrar_cliente_hydra.py --nombre crm \
  --redirect-uri https://crm.tu-hostname.sslip.io/oauth-callback.php
```
(confirma el path exacto de callback contra la pantalla de
Administration → Authentication → OIDC de tu versión de EspoCRM antes de
registrar el cliente — puede variar entre versiones).

**Configurar OIDC en EspoCRM** (Administration → Authentication → método
OIDC, una sola vez):
- Client ID / Client Secret: los que imprime el comando de arriba.
- Authorization Endpoint: `https://hydra.tu-hostname.sslip.io/oauth2/auth`
  (pública, la ve el navegador).
- Token Endpoint / Userinfo Endpoint: `http://hydra:4444/oauth2/token` /
  `http://hydra:4444/userinfo` (hostname interno de Docker — llamadas
  servidor-a-servidor, mismo criterio que `OIDC_TOKEN_URI`/
  `OIDC_USERINFO_URI` de Outline en `docker-compose.yml`).
- Group Claim: `groups`.

**Configurar el mapeo de Equipos** (Administration → Authentication →
OIDC → Team Mapping / `oidcTeams`, una sola vez por tenant nuevo):
añade una fila por cada tenant, con el valor del claim `groups` (el
nombre exacto del tenant en Guilda Work) apuntando al Equipo del mismo
nombre que ya creó `app/espocrm.py`. **Verificar al desplegar** si hace
falta esta fila explícita o si EspoCRM asocia ya por coincidencia directa
de nombre — no confirmado sin una instancia real delante.

**Configurar Roles — el paso que de verdad aísla los datos**
(Administration → Roles → rol por defecto, una sola vez): en
Lead/Contact/Account/Opportunity (y cualquier otra entidad con datos de
cliente), nivel de acceso **"Team"**, no "All". Sin este cambio, el
Equipo asignado por OIDC no restringe nada — los Equipos sin un Rol que
los aproveche son solo una etiqueta, igual que el `tenant_id` del propio
Guilda Work hoy (ver nota más abajo).

**Nota — deuda pendiente, fuera de alcance de esta integración**: el
modelo de tenant del resto de Guilda Work (tareas/notas/categorías) sigue
siendo solo una etiqueta en `usuarios.tenant_id`, sin ningún filtro real
en las consultas — a diferencia de EspoCRM (aislado de verdad tras los
pasos de arriba), el resto de la app no lo está todavía. Señalado como
algo a abordar en el futuro, no automatizado aquí.

### 8.20 Nextcloud (Drive) — con SSO y aislamiento por tenant

Espacio de archivos tipo Drive, código abierto (AGPLv3). El directorio
de cada usuario ya es privado por diseño en Nextcloud — más fuerte por
defecto que EspoCRM, que dependía de un Rol bien configurado. El riesgo
real aquí es otro: que alguien comparta un archivo a mano con un usuario
de otro tenant, y **eso sí exige un paso manual explícito** (ver más
abajo).

Añade a `.env`:
```bash
NEXTCLOUD_DB_PASSWORD=...
NEXTCLOUD_ADMIN_USER=admin
NEXTCLOUD_ADMIN_PASSWORD=...   # mínimo 8 caracteres, instalación desatendida
NEXTCLOUD_TRUSTED_DOMAINS=drive.tu-hostname.sslip.io
```

```bash
docker compose up -d postgres-nextcloud nextcloud
```

**Habilitar las apps necesarias** (una sola vez):
```bash
docker exec -u www-data guilda-work-nextcloud php occ app:enable user_oidc
docker exec -u www-data guilda-work-nextcloud php occ app:enable groupfolders
```

**Registrar el cliente OAuth2** (mismo comando que EspoCRM/Outline):
```bash
.venv/bin/python scripts/registrar_cliente_hydra.py --nombre drive \
  --redirect-uri https://drive.tu-hostname.sslip.io/apps/user_oidc/code
```
(confirma el path exacto de callback contra Configuración → Administración
→ Autenticación OpenID Connect de tu versión de Nextcloud antes de
registrar el cliente).

**Configurar el proveedor OIDC** (Configuración → Administración →
Autenticación OpenID Connect, una sola vez):
- Identifier / Client ID / Client Secret: los que imprime el comando de
  arriba.
- Discovery endpoint: `https://hydra.tu-hostname.sslip.io/.well-known/openid-configuration`.
- Group mapping (`mappingGroups`): claim `groups` — el mismo que ya
  manda Hydra para EspoCRM, ningún cambio adicional en `app/hydra.py`.

**Configurar Group folders** — `app/rutas_backoffice.py: crear_tenant()`
ya crea, vía `app/nextcloud.py`, un Grupo y un Group Folder por tenant al
darlo de alta (si `NEXTCLOUD_ADMIN_USER`/`NEXTCLOUD_ADMIN_PASSWORD` están
en el entorno del propio Guilda Work, no solo en el contenedor). No hace
falta nada manual aquí salvo tener la app activada (paso de arriba).

**El paso que de verdad cierra el aislamiento** (Configuración →
Administración → Compartir ficheros, una sola vez): activa
**"Restringir a los usuarios compartir solo con usuarios de sus mismos
grupos"** y el autocompletado limitado a los grupos propios. Sin esto,
un usuario de un tenant puede compartir un archivo a mano con cualquier
otro usuario del sistema, tenant o no — los Grupos por sí solos no lo
impiden, igual que los Roles de EspoCRM.

**Migrar a MinIO como almacenamiento primario** (opcional pero
recomendado — reutiliza el MinIO ya desplegado en vez de un volumen
nuevo; no es configurable por variables de entorno de forma fiable, hace
falta este comando de un solo uso):
```bash
docker exec -u www-data guilda-work-nextcloud php occ config:system:set \
  objectstore class --value="OC\\Files\\ObjectStore\\S3"
docker exec -u www-data guilda-work-nextcloud php occ config:system:set \
  objectstore arguments bucket --value="nextcloud-data"
docker exec -u www-data guilda-work-nextcloud php occ config:system:set \
  objectstore arguments hostname --value="minio"
docker exec -u www-data guilda-work-nextcloud php occ config:system:set \
  objectstore arguments port --value="9000" --type=integer
docker exec -u www-data guilda-work-nextcloud php occ config:system:set \
  objectstore arguments use_ssl --value=false --type=boolean
docker exec -u www-data guilda-work-nextcloud php occ config:system:set \
  objectstore arguments key --value="guilda_admin"
docker exec -u www-data guilda-work-nextcloud php occ config:system:set \
  objectstore arguments secret --value="$MINIO_ROOT_PASSWORD"
docker exec -u www-data guilda-work-nextcloud php occ config:system:set \
  objectstore arguments use_path_style --value=true --type=boolean
```
**Solo funciona en una instalación recién creada, sin archivos todavía**
— confirma esto contra la documentación oficial de Nextcloud antes de
ejecutarlo si ya hay datos subidos, no está pensado como migración en
caliente.

**Nota — misma deuda pendiente que EspoCRM** (ver 8.19): el modelo de
tenant del resto de Guilda Work sigue sin aislamiento real. No se repite
aquí, solo se recuerda.

### 8.21 FacturaScripts (facturación/contabilidad) — una instancia por tenant

A diferencia de EspoCRM/Nextcloud, aquí **no hay aislamiento lógico
posible dentro de una instancia compartida** — investigado y confirmado
que el plugin oficial "MultiEmpresa" no restringe qué usuario ve qué
empresa, solo aplica valores por defecto. Con datos económicos de por
medio, cada tenant tiene su **propia instancia física** de
FacturaScripts + su propia base de datos, aprovisionadas automáticamente
al crear el tenant desde el backoffice (`app/facturascripts.py`).

**Requisito previo — el usuario de `serve.py` necesita poder usar Docker**
(a diferencia del resto de la app, que solo habla HTTP con contenedores
ya existentes, aquí los crea):
```bash
sudo usermod -aG docker $(whoami)
# cerrar sesión y volver a entrar para que el grupo nuevo tenga efecto
```

**Levantar el Postgres compartido** (una sola vez — las bases de cada
tenant se crean solas dentro de él, ver más abajo):
```bash
# .env
FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD=...   # openssl rand -hex 32

docker compose up -d postgres-facturascripts
```

**Qué pasa al crear un tenant nuevo** (automático, sin nada que hacer a
mano): `app/facturascripts.py:aprovisionar_tenant()` crea un rol y una
base de datos exclusivos en el Postgres compartido
(`REVOKE CONNECT ... FROM PUBLIC`, para que ni siquiera con las
credenciales de otro tenant se pueda entrar), levanta un contenedor
nuevo (`guilda-work-facturascripts-tenant-<id>`, puerto `8100 + id`) y
lo instala. **Nota técnica** (verificado en vivo, no solo leyendo
documentación): el instalador HTTP oficial de FacturaScripts documenta
un modo `unattended=1` pensado para esto, pero en la versión publicada
actualmente tiene un fallo real que lo rompe en el primer arranque —
en vez de depender de esa vía, `aprovisionar_tenant()` escribe
`config.php`/`.htaccess` directamente en el contenedor (mismo
contenido que generaría el instalador) y dispara el paso de
inicialización por consola — confirmado que el resultado es idéntico
al de una instalación normal (login real, usuario admin creado). El
backoffice te enseña **una sola vez**, justo después de crear el
tenant, la URL y la contraseña de administrador generada — apúntala
ahí, no se vuelve a mostrar.

**El único paso manual que queda — crear la API Key** (no hay forma de
generarla sin una sesión ya iniciada, así que no es automatizable sin
scriptear también el login):
1. Entra en la URL del tenant con el usuario/contraseña que te enseñó el
   backoffice.
2. Ajustes → API Keys → crear una nueva.
3. Pégala en el campo "FacturaScripts" de la fila de ese tenant, en el
   backoffice — sin este paso, las tools de MCP `facturas_*` para ese
   tenant devuelven un error legible pidiéndolo, no fallan en silencio.

**Al borrar un tenant**: `app/facturascripts.py:desaprovisionar_tenant()`
para y borra su contenedor y su base de datos automáticamente — no hace
falta limpieza manual.

**MCP**: a diferencia del resto de herramientas del catálogo (una
instancia compartida, sin necesidad de decir de cuál se habla), las
tools `facturas_listar_clientes`/`facturas_crear_cliente`/
`facturas_listar_facturas`/`facturas_crear_factura` llevan un primer
parámetro `tenant` (el nombre tal cual aparece en el backoffice) —
imprescindible aquí porque cada tenant es una instancia física distinta.

### 8.22 Documenso (firma electrónica de documentos)

A diferencia de FacturaScripts, aquí la instancia SÍ es compartida (como
EspoCRM/Nextcloud) — pero a diferencia de EspoCRM/Nextcloud, **no hay
SSO** (confirmado en la documentación oficial: *"SSO is only available
on the Enterprise plan"*) y **no hay API para crear Equipos ni invitar
miembros** (verificado en vivo, descargando el spec OpenAPI real
directamente de un contenedor en marcha — 89 endpoints, ninguno de
Equipos). El aislamiento entre tenants lo da un token de API generado a
mano **desde dentro de la página de configuración de cada Equipo**.

**Certificado de firma** (obligatorio — sin él, el contenedor no
arranca): ver [`deploy/documenso/README.md`](../deploy/documenso/README.md)
para generar uno autofirmado con `openssl` en un minuto.

Añade a `.env`:
```bash
DOCUMENSO_DB_PASSWORD=...
DOCUMENSO_NEXTAUTH_SECRET=...          # openssl rand -hex 32
DOCUMENSO_ENCRYPTION_KEY=...           # openssl rand -hex 32
DOCUMENSO_ENCRYPTION_SECONDARY_KEY=... # openssl rand -hex 32 (una clave DISTINTA a la anterior)
DOCUMENSO_SIGNING_PASSPHRASE=...       # la misma que usaste al generar cert.p12
DOCUMENSO_SMTP_HOST=...
DOCUMENSO_SMTP_FROM_ADDRESS=firmas@tu-hostname
DOCUMENSO_PUBLIC_ORIGIN=https://firmas.tu-hostname.sslip.io
```

**SMTP es un requisito real aquí** (a diferencia del resto del stack):
el registro de cada persona y las notificaciones de firma dependen de
poder mandar correos — confirmado en vivo que sin esto la cuenta se crea
pero se queda bloqueada en "confirma tu correo" para siempre.

```bash
docker compose up -d postgres-documenso documenso
```

**Por cada tenant nuevo (100% manual, sin atajo por API)**:
1. El admin de Guilda Work se registra/inicia sesión en Documenso
   (`https://firmas.tu-hostname`, correo + contraseña — confirma el
   correo, hace falta SMTP funcionando de verdad).
2. Ajustes → Organizaciones/Equipos → crea un Equipo con el nombre del
   tenant.
3. Invita a los usuarios de ese tenant al Equipo (por email — cada uno
   acepta y crea su propia cuenta).
4. **Entra en la página del Equipo** (no en tu cuenta personal) →
   Ajustes → Tokens de API → crea uno — es el origen desde donde se
   genera lo que le da al token el contexto de ese Equipo en concreto.
5. Pega el token en la fila de ese tenant, en el backoffice.

**MCP**: igual que FacturaScripts, `firmas_listar_documentos`/
`firmas_crear_documento`/`firmas_enviar_a_firma`/`firmas_descargar_firmado`
llevan un primer parámetro `tenant` — imprescindible porque el
aislamiento depende de qué token de Equipo se use, no de una instancia
física distinta. `firmas_crear_documento` coloca un único campo de firma
por firmante en la primera página, en una posición por defecto — para
colocar campos a medida (varias páginas, varios campos), usa la propia
interfaz web de Documenso.

### 8.23 Paperless-ngx (gestión documental/OCR)

A diferencia de Documenso, aquí **sí hay SSO real** (OIDC vía
django-allauth, desde Paperless-ngx ≥ 2.5.0) y **sí hay aprovisionamiento
100% automático por API** (Grupo + usuario de servicio + token, ver
`app/paperless.py`) — confirmado leyendo el propio código fuente de
Paperless-ngx, no solo su documentación. **No hace falta ningún paso
manual por tenant.**

Añade a `.env`:
```bash
PAPERLESS_DB_PASSWORD=...
PAPERLESS_SECRET_KEY=...                # openssl rand -hex 32 — obligatoria, sin ella el contenedor no arranca (verificado en vivo)
PAPERLESS_ADMIN_USER=admin
PAPERLESS_ADMIN_PASSWORD=...            # openssl rand -hex 16 — crea el superusuario al primer arranque
PAPERLESS_PUBLIC_ORIGIN=https://documentos.tu-hostname.sslip.io
```

**Registrar el cliente OAuth2** (mismo comando que EspoCRM/Drive/Outline;
la ruta de callback la fija django-allauth, no es configurable —
`/accounts/oidc/<provider_id>/login/callback/`, con `provider_id=hydra`,
que es el que se usa en `docker-compose.yml`):
```bash
.venv/bin/python scripts/registrar_cliente_hydra.py --nombre documentos \
  --redirect-uri https://documentos.tu-hostname.sslip.io/accounts/oidc/hydra/login/callback/
```
Añade `PAPERLESS_OIDC_CLIENT_ID`/`PAPERLESS_OIDC_CLIENT_SECRET` a `.env`
con lo que imprima el comando.

```bash
docker compose up -d paperless-broker postgres-paperless paperless
```

**Aislamiento entre tenants**: `PAPERLESS_SOCIAL_ACCOUNT_SYNC_GROUPS=true`
(ya en `docker-compose.yml`) sincroniza los Grupos del usuario contra el
claim `groups` del id_token de Hydra **en cada login** — reutiliza el
mismo claim que ya manda `app/hydra.py` desde la Fase CRM, cero cambios
adicionales ahí. Los Grupos deben existir ya en Paperless-ngx cuando el
usuario inicia sesión por primera vez — los crea
`app/paperless.py:aprovisionar_tenant()` al dar de alta el tenant desde
el backoffice (antes de que nadie de ese tenant haya iniciado sesión
nunca), así que el orden normal (crear tenant → crear usuarios → que
inicien sesión) ya deja todo listo sin intervención.

El aislamiento real, a nivel de base de datos, lo aplica
`DocumentPermissionsFilter` de Paperless-ngx (confirmado en su código
fuente, `src/documents/views.py`) sobre el `owner`/`set_permissions` de
cada documento — `app/paperless.py:subir_documento()` los aplica
automáticamente al Grupo del tenant que sube el documento, no hace falta
tocar nada a mano en la interfaz de Paperless-ngx para que funcione.

**Nota de despliegue local (sin dominio real)**: django-allauth resuelve
el documento de descubrimiento OIDC de Hydra **una sola vez, server-side,
desde dentro del propio contenedor de Paperless-ngx** — y ese documento
siempre reporta el origen **público** configurado en Hydra para todos sus
endpoints (autorización, token, userinfo), a diferencia de Outline/
Element, que sí permiten fijar por separado un endpoint interno de
Docker para las llamadas servidor-a-servidor. En el VPS real (dominio
público, resoluble también desde dentro de Docker) esto no es un
problema; en local, sin dominio real, hace falta la misma alias de red
que ya usa `caddy-local` para Synapse/Outline (ver `HTTPS_LOCAL.md`) para
poder verificar el login SSO de verdad.

**Gotenberg/Tika** (conversión de documentos de Office a PDF) quedan
**fuera de este MVP a propósito** — Paperless-ngx funciona bien con
PDFs/imágenes/escaneos sin ellos, que es el grueso de lo que recibe una
gestoría. Si hace falta más adelante, añadir los servicios
`gotenberg`/`tika` oficiales y las variables
`PAPERLESS_TIKA_ENABLED`/`PAPERLESS_TIKA_GOTENBERG_ENDPOINT`/
`PAPERLESS_TIKA_ENDPOINT` (ver documentación oficial de Paperless-ngx).

**MCP**: igual que FacturaScripts/Documenso, `documentos_listar`/
`documentos_subir`/`documentos_descargar` llevan un primer parámetro
`tenant`. `documentos_subir` sube el PDF (base64), espera a que
Paperless-ngx termine de procesarlo (OCR incluido) y le aplica los
permisos que cierran el aislamiento — puede tardar unos segundos en
documentos largos, es esperado.

**Nota sobre `desaprovisionar_tenant` (borrar un tenant)**: solo borra el
Grupo y el usuario de servicio en Paperless-ngx, no sus documentos —
verificado en vivo que un documento cuyo propietario se borra queda con
`owner: null`, y Paperless-ngx trata los documentos sin propietario como
**visibles para cualquier usuario autenticado** con permiso de ver
documentos (comportamiento propio de Paperless-ngx, no un fallo de
`app/paperless.py`). Si se borra un tenant que ya tenía documentos
subidos, hay que borrarlos a mano desde la interfaz de Paperless-ngx
antes (o reasignarlos) para que no queden visibles a otros tenants —
mismo tipo de limpieza manual que ya hace falta hoy al borrar un tenant
de FacturaScripts con facturas ya emitidas.

### 8.24 Baserow (hojas de cálculo tipo base de datos)

Híbrido entre Paperless-ngx y Documenso: **sí hay API real para crear el
Workspace y su token** de un tenant (100% automático, ver
`app/baserow.py`), pero **no hay API para añadir un usuario ya existente
a un Workspace** — solo invitación por email + aceptación manual (la
persona crea su propia cuenta de Baserow, sin SSO — confirmado que SSO
es Enterprise-only también en self-hosted).

**Paso manual único, antes de dar de alta ningún tenant**: crear el
primer superusuario admin de Baserow — a diferencia de
`PAPERLESS_ADMIN_USER`, no hay variable de entorno que lo autocree.
Registrarse la primera vez desde `https://hojas.tu-hostname` con el
correo/contraseña que luego irán en `BASEROW_ADMIN_EMAIL`/
`BASEROW_ADMIN_PASSWORD`.

Añade a `.env`:
```bash
BASEROW_DB_PASSWORD=...
BASEROW_REDIS_PASSWORD=...
BASEROW_SECRET_KEY=...                  # openssl rand -hex 32 — obligatoria (misma lección que PAPERLESS_SECRET_KEY)
BASEROW_ADMIN_EMAIL=admin@tu-hostname
BASEROW_ADMIN_PASSWORD=...              # la misma cuenta creada a mano en el paso anterior
BASEROW_PUBLIC_ORIGIN=https://hojas.tu-hostname.sslip.io
BASEROW_SMTP_HOST=...
BASEROW_SMTP_FROM_ADDRESS=hojas@tu-hostname
```

**SMTP es un requisito real aquí** (igual que Documenso): sin él, las
invitaciones a un Workspace no se mandan, solo quedan registradas en los
logs del worker de Baserow — el admin tendría que ir a buscarlas ahí a
mano, nada práctico para el día a día.

```bash
docker compose up -d redis-baserow postgres-baserow baserow
```

**Flujo normal, sin pasos manuales por tenant salvo la aceptación de
cada persona**:
1. `crear_tenant()` provisiona su Workspace + token automáticamente.
2. `crear_usuario()` con ese tenant asignado dispara la invitación por
   email al Workspace automáticamente (`app/baserow.py:invitar_usuario`).
3. La persona abre el correo y acepta — ahí crea su propia contraseña de
   Baserow (sin SSO, cuenta separada del resto del stack).

**MCP**: `hojas_listar_tablas`/`hojas_listar_filas`/`hojas_crear_fila`
llevan un primer parámetro `tenant`, cuarto cliente del catálogo con
este patrón (junto a `facturas_*`/`firmas_*`/`documentos_*`).
`hojas_crear_fila` espera los nombres de columna de Baserow tal cual
como claves del diccionario `campos` — hay que consultarlos antes con
`hojas_listar_tablas`/la propia interfaz de Baserow, no hay
autodescubrimiento de columnas en estas tools.

**Hallazgos reales verificados en vivo, corregidos en `app/baserow.py`**:
- Baserow **no rechaza nombres de Workspace duplicados** — a diferencia
  de EspoCRM/Nextcloud/Paperless-ngx, `POST /api/workspaces/` siempre
  crea uno nuevo aunque ya exista otro con el mismo nombre.
  `aprovisionar_tenant()` busca primero por nombre antes de crear, no al
  revés, para que reintentar no genere Workspaces duplicados.
- `DELETE /api/workspaces/{id}/` solo manda el Workspace a la papelera
  (soft delete) — `desaprovisionar_tenant()` hace una segunda llamada a
  `DELETE /api/trash/workspace/{id}/` para vaciarla y borrarlo de
  verdad. Incluso así, su token de base de datos sigue aceptándose como
  credencial válida (devuelve listas vacías en vez de un 401/403
  explícito) — no hay fuga de datos de otro tenant en ningún caso, solo
  que el error no es tan explícito como cabría esperar.
- La invitación a un Workspace exige un campo `base_url` (la URL base
  de la página de aceptación, confirmado en el propio código fuente del
  frontend de Baserow: `/workspace-invitation/<token>`) — sin él, la
  API la rechaza con un 400.

### 8.25 Cal.diy (reserva de citas, tipo Cal.com) — instancia compartida

**Cal.com dejó de ser open source en julio de 2026** (el repositorio
pasó a privado). La continuación libre real es
[Cal.diy](https://www.cal.diy) (`github.com/calcom/cal.diy`, licencia
MIT) — mismo motor, sin SSO/SAML ni Equipos/Organizaciones reales en la
edición libre (el flag `ORGANIZATIONS_ENABLED` del propio
`.env.example` del repo está marcado explícitamente "solo para
entornos no-prod", no es una función de producción).

A diferencia de FacturaScripts, aquí **no hay una instancia por
tenant**: `NEXT_PUBLIC_WEBAPP_URL` de Cal.diy es una variable de
**compilación** de Next.js, no de ejecución (confirmado en la
documentación oficial de Docker de Cal.diy) — una imagen no puede
servir URLs distintas por contenedor sin reconstruirse, así que un
contenedor físico por tenant no es viable. En su lugar: **una única
instancia compartida** + **un usuario de servicio de Cal.diy por
tenant** (aislamiento a nivel de cuenta individual, ver
`app/calcom.py`).

**Nota de honestidad, igual que el resto de esta guía**: el diseño de
`app/calcom.py` se verificó leyendo el **código fuente real** del
repositorio (`apps/web/app/api/auth/setup/route.ts`,
`.../signup/route.ts` y su `selfHostedHandler.ts`, no solo
documentación), pero **no se ha podido levantar un contenedor real y
probarlo de punta a punta** durante el desarrollo — el monorepo es
demasiado grande para compilarlo en el entorno de desarrollo de este
proyecto (ni siquiera el `git clone` terminó en menos de 3 minutos).
**La primera vez que despliegues esto, trátalo como el resto de
integraciones de este documento que sí se verificaron en vivo: revisa
con calma que cada paso funciona como se describe, y ajusta
`app/calcom.py` si algo no coincide** (lo más probable: nombres exactos
de campos de la API v2, o el comportamiento exacto de
`/api/auth/signup` en tu versión concreta).

**Sin imagen prehecha publicada** (ni Docker Hub ni el mirror de Scarf
que menciona el propio `docker-compose.yml` oficial de Cal.diy tienen
un tag descargable) — `docker-compose.yml` construye la imagen desde el
propio repositorio como contexto de build remoto
(`https://github.com/calcom/cal.diy.git#main`), así no hace falta
vendorizar un monorepo de Next.js dentro de este repositorio. Compilar
tarda bastante (es un monorepo Next.js/Turborepo) — dale tiempo la
primera vez.

**Importante**: `NEXT_PUBLIC_WEBAPP_URL`/`NEXT_PUBLIC_API_V2_URL` se
hornean en el bundle de cliente en el momento de construir la imagen —
define `CALCOM_PUBLIC_ORIGIN`/`CALCOM_API_PUBLIC_ORIGIN` con tu dominio
público REAL **antes** de construir. Si más adelante cambias de
dominio, hay que reconstruir la imagen (`docker compose build
calcom-web`), no basta con cambiar la variable de entorno.

Añade a `.env`:
```bash
CALCOM_DB_PASSWORD=...
CALCOM_REDIS_PASSWORD=...
CALCOM_NEXTAUTH_SECRET=...        # openssl rand -base64 32
CALCOM_ENCRYPTION_KEY=...         # openssl rand -base64 24
CALCOM_JWT_SECRET=...             # openssl rand -base64 32
CALCOM_ADMIN_EMAIL=admin@tu-hostname
CALCOM_ADMIN_PASSWORD=...         # mínimo 15 caracteres, mayúscula+minúscula+número
CALCOM_PUBLIC_ORIGIN=https://citas.tu-hostname.sslip.io
CALCOM_API_PUBLIC_ORIGIN=https://citas-api.tu-hostname.sslip.io
```

```bash
docker compose up -d --build redis-calcom postgres-calcom calcom-web calcom-api
```

**Bootstrap del admin de la instancia** (una sola vez, no por tenant):
```bash
.venv/bin/python -c "from app import calcom; calcom.bootstrap_admin()"
```

**Qué pasa al crear un tenant nuevo** (automático):
`app/calcom.py:aprovisionar_tenant()` da de alta un usuario de servicio
(`tenant-<slug>@calcom.local`) vía el registro estándar de Cal.diy. El
backoffice te enseña **una sola vez**, justo después de crear el
tenant, el email y la contraseña generada — apúntala ahí, no se vuelve
a mostrar.

**El único paso manual que queda — crear la API Key** (no se ha
encontrado, ni en el código ni en la documentación, un endpoint admin
para crear API Keys de otro usuario en la edición self-hosted):
1. Entra en `https://citas.tu-hostname` con el email/contraseña que te
   enseñó el backoffice.
2. Configuración → Developer → API Keys → crear una nueva.
3. Pégala en el campo "Cal.diy" de la fila de ese tenant, en el
   backoffice — sin este paso, las tools de MCP `citas_*` para ese
   tenant devuelven un error legible pidiéndolo, no fallan en silencio.

**Al borrar un tenant**: a diferencia de FacturaScripts/Paperless-ngx/
Baserow, aquí no hay nada que desaprovisionar por API — si quieres
borrar también la cuenta de Cal.diy del tenant, es una acción manual
del admin desde la propia instancia.

**MCP**: `citas_listar_tipos_evento`/`citas_listar_reservas`/
`citas_crear_reserva`/`citas_cancelar_reserva` llevan un primer
parámetro `tenant`, quinto cliente del catálogo con este patrón (junto
a `facturas_*`/`firmas_*`/`documentos_*`/`hojas_*`) — aquí porque el
aislamiento depende de qué cuenta de servicio se use, no de una
instancia física distinta.

**Verificación real de aislamiento pendiente** (mismo criterio que el
resto de integraciones de este documento): al desplegar, crea dos
tenants de prueba, genera el API Key de cada uno desde su cuenta, y
confirma que con el de uno no se puede listar ni cancelar reservas del
otro — es la prueba real de que el aislamiento a nivel de cuenta
individual (sin Equipos de pago) funciona de verdad, no algo que se
pueda dar por hecho solo con la documentación.

### 8.26 Listmonk (newsletter/envíos masivos) — instancia compartida, sin pasos manuales

[Listmonk](https://listmonk.app) (`github.com/knadh/listmonk`, AGPLv3,
un único binario Go + Postgres, sin edición de pago) — gestor de
newsletters/mailing lists.

**Aislamiento entre tenants — verificado en vivo, no solo leído en el
código**: se levantó un contenedor real (Postgres + imagen oficial
`listmonk/listmonk:latest`), se creó una Lista y un Rol de lista por
cada uno de dos tenants de prueba, y se confirmó de verdad que el token
de un tenant no puede leer ni escribir en la lista del otro
(`GET /api/subscribers?list_id=<de otro tenant>` devuelve vacío,
`POST /api/subscribers` en la lista ajena devuelve
`403 Permission denied: lists`) — la prueba real de aislamiento, mismo
criterio que EspoCRM/Nextcloud/Paperless-ngx/Baserow.

**Diseño de dos roles, encontrado probándolo en vivo (no estaba
documentado así de antemano)**: un Rol de lista solo puede llevar
`list:get`/`list:manage` (Listmonk rechaza `subscribers:*`/`campaigns:*`
ahí con `400 Invalid fields`) — los permisos de ACCIÓN
(`subscribers:get`/`manage`, `campaigns:get`/`manage`/`send`) van en un
Rol de USUARIO compartido por todos los tenants ("Tenant", creado una
sola vez); lo que de verdad restringe QUÉ lista puede tocar cada tenant
es su propio Rol de lista. Ver el docstring de `app/listmonk.py` para
el detalle completo.

**Sin ningún paso manual** — a diferencia de FacturaScripts/Documenso/
Cal.diy: `POST /api/users` con `"type": "api"` genera el token en el
momento y lo devuelve en la propia respuesta de creación, confirmado en
vivo. `app/listmonk.py:aprovisionar_tenant()` encadena Lista → Rol de
lista → usuario de servicio → guarda el token, todo automático.

Añade a `.env`:
```bash
LISTMONK_DB_PASSWORD=...
LISTMONK_ADMIN_USER=admin@tu-hostname
LISTMONK_ADMIN_PASSWORD=...
```

```bash
docker compose up -d postgres-listmonk listmonk
```

Con `LISTMONK_ADMIN_USER`/`PASSWORD` definidas, el propio comando de
arranque (`--install --idempotent --yes`) instala el esquema y crea el
superadmin la primera vez — no hace falta ningún script propio.

**Configurar SSO (OIDC vía Hydra)** — opcional pero recomendado, un
único paso de instancia, no por tenant:
1. Registra el cliente OAuth2 (mismo patrón que EspoCRM/Nextcloud/
   Paperless-ngx):
   ```bash
   .venv/bin/python scripts/registrar_cliente_hydra.py --nombre newsletter --redirect-uri https://newsletter.tu-hostname/admin/auth/oidc
   ```
2. Entra como superadmin → Ajustes → Seguridad → OIDC, y define Client
   ID/Secret, la URL del proveedor (endpoints internos vía hostname
   Docker `http://hydra:4444/...`, igual que Outline/EspoCRM/Nextcloud).
3. **Nota importante, no un paso que puedas saltarte**: el campo
   "Rol de lista por defecto" de esa pantalla solo se usa si alguien
   entra por SSO SIN haber sido dado de alta antes desde el backoffice
   de Guilda Work (caso raro, pero posible) — en el flujo normal, cada
   persona ya se creó en Listmonk con el Rol de lista correcto en el
   momento en que se le asignó su tenant (`crear_usuario()`,
   `app/rutas_backoffice.py`), así que Listmonk la encuentra por email y
   hereda ese Rol, no el de por defecto. Déjalo vacío o apuntando a un
   Rol sin listas si quieres que un alta "huérfana" por SSO no vea nada
   por error.

**Requisito real**: Listmonk necesita SMTP saliente de verdad para
mandar las campañas — no es opcional como en otras integraciones donde
solo afecta a notificaciones. Configúralo desde Ajustes → SMTP con el
superadmin, una sola vez.

**Qué pasa al crear un tenant nuevo** (100% automático): Lista + Rol de
lista + usuario de servicio tipo `api`, con el token ya guardado — nada
que mostrar ni pegar a mano.

**Qué pasa al dar de alta a una persona con tenant asignado**: se crea
(o actualiza) su cuenta de Listmonk con `password_login=false` (entra
solo por SSO) y el Rol de lista de su tenant — cuando entre por primera
vez vía Hydra, Listmonk la reconoce por email.

**MCP**: `newsletter_listar_suscriptores`/`newsletter_crear_suscriptor`/
`newsletter_listar_campanas`/`newsletter_crear_campana`/
`newsletter_enviar_campana` llevan un primer parámetro `tenant`, sexto
cliente del catálogo con este patrón.

### 8.27 Stalwart (correo propio) — instancia compartida, sin pasos manuales, dominio propio por cliente

[Stalwart Mail Server](https://stalw.art) (`stalwartlabs/stalwart`,
Rust, AGPLv3 — un único binario JMAP+IMAP+SMTP+CalDAV/CardDAV/WebDAV) —
backend de correo alternativo al cliente IMAP genérico de
`app/correo.py`, con una API moderna (JSON, no IMAP crudo) mucho mejor
para MCP.

**Aviso de reputación, no técnico**: montar un servidor de correo
SALIENTE propio implica gestionar SPF/DKIM/DMARC y la reputación de la
IP desde cero — un dominio nuevo sin histórico tiende a caer en spam al
principio. No es un problema de esta integración, es inherente a
autoalojar correo saliente; ten esto en cuenta antes de mover tráfico
real de producción.

**Aislamiento entre tenants — verificado en vivo, no solo leído en la
documentación**: la propia página de comparación de Stalwart
(`stalw.art/compare`) marca "multi-tenancy" como función Enterprise
(de pago) — se verificó contra un contenedor real, SIN ninguna licencia
configurada (`"edition":"community"` confirmado en `/api/account`), que
Tenant/Domain/Account SÍ se pueden crear gratis, y que el aislamiento es
real: con dos Accounts de dos Tenants distintos, cada una con su propio
ApiKey, una llamada con el `accountId` de la cuenta del OTRO tenant es
rechazada por el propio servidor (`403 forbidden`, no un filtro de
cliente). Lo que de verdad es Enterprise-only es la conveniencia
administrativa (cuotas por tenant desde la UI, directorios externos por
dominio), no el mecanismo de scoping en sí.

**El punto que costó más resolver**: añadir una credencial (API Key) a
una cuenta NUNCA se hace sobre la propia cuenta — ni siquiera la WebUI
oficial de Stalwart puede hacerlo así (choca con el mismo error real del
servidor, `"Secondary credentials cannot be set directly"`). El
mecanismo real es que cada tipo de credencial secundaria es su propio
objeto JMAP (`x:ApiKey`), creado con el `accountId` de la cuenta
DESTINO, no del admin. Ver el docstring de `app/stalwart.py` para el
detalle completo — quedó resuelto y 100% automático, sin ningún paso
manual.

**Dominio propio de cada cliente** (decisión tomada con el usuario, no
un esquema de subdominios de tu propio hostname): cada tenant usa su
dominio real (p.ej. `clientea.com`), que ese cliente debe delegar hacia
tu servidor Stalwart:
- **MX**: apuntando al hostname de tu instancia de Stalwart.
- **SPF**: `TXT` autorizando la IP/hostname de tu servidor como emisor.
- **DKIM**: Stalwart puede generar su propio par de claves DKIM (visto
  en su asistente de instalación) — publica la clave pública que te dé
  como registro `TXT` en el dominio del cliente.
- **DMARC**: `TXT` con la política que decidáis (recomendado empezar en
  modo `p=none` para observar antes de aplicar `quarantine`/`reject`).

Es el único dato manual de todo el aprovisionamiento: el dominio se
introduce al dar de alta el tenant desde `/backoffice` (campo "Dominio
de correo (Stalwart, opcional)") — si se deja vacío, ese tenant
simplemente no tiene Stalwart aprovisionado, sin bloquear el resto del
alta.

**Puertos — EXCEPCIÓN explícita a "todo detrás de Caddy en 443"**
(mismo criterio ya aceptado para SSH/OpenVPN): los puertos de correo
real no son HTTP, Caddy no puede hacerles de proxy — se publican
directamente en el host:

| Puerto | Protocolo |
|---|---|
| 25 | SMTP (recepción entre servidores) |
| 587 | SMTP Submission (envío autenticado) |
| 465 | SMTPS (envío autenticado, TLS implícito) |
| 143 / 993 | IMAP / IMAPS |
| 110 / 995 | POP3 / POP3S |
| 4190 | ManageSieve |

Solo el puerto de administración HTTP (8080 dentro del contenedor,
publicado en 8025 en el host) va detrás de Caddy, como el resto de
herramientas.

**Arranque — NO admite bootstrap 100% por variables de entorno** (a
diferencia de Kratos/Hydra/Listmonk), verificado en vivo:

```bash
docker compose up -d stalwart
docker logs guilda-work-stalwart   # imprime un admin temporal: username + password
```

1. Entra en `https://correo-stalwart.tu-hostname/` (o
   `http://127.0.0.1:8025/` en local) con el admin temporal.
2. Completa el asistente de instalación (5 pasos: identidad del
   servidor — hostname y dominio por defecto —, almacenamiento,
   directorio de cuentas, logging, gestión de DNS). Al terminar te
   enseña el email y la contraseña del admin PERMANENTE — apúntala, no
   se vuelve a mostrar.
3. Reinicia el contenedor para que el admin permanente quede activo:
   ```bash
   docker restart guilda-work-stalwart
   ```
4. Añade a `.env`:
   ```bash
   HERRAMIENTA_STALWART_URL=http://127.0.0.1:8025
   STALWART_ADMIN_USER=admin@tu-hostname
   STALWART_ADMIN_PASSWORD=...
   ```
5. Reinicia Guilda Work (`STALWART_ADMIN_USER`/`PASSWORD` se leen al
   arrancar `app/stalwart.py`).

**Qué pasa al crear un tenant nuevo con dominio_correo relleno** (100%
automático): Tenant + Domain (con ese dominio real) + Account + ApiKey,
con el token ya guardado — nada que pegar a mano.

**MCP**: `correo_stalwart_listar_mensajes`/`correo_stalwart_leer_mensaje`/
`correo_stalwart_enviar_mensaje` llevan un primer parámetro `tenant`,
séptimo cliente del catálogo con este patrón.

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

## 10. MCP remoto (ChatGPT)

`mcp_server.py` (local, `stdio`) ya vale para Claude Code/Desktop y Codex
CLI sin nada de esto — esta sección es solo para conectar **ChatGPT**,
que exige un servidor MCP remoto por HTTPS con OAuth 2.1 (ver README.md,
sección "Conector remoto para ChatGPT"). `mcp_server_remoto.py` expone el
mismo catálogo de tools que el local, pero delega toda la autorización en
Ory Hydra (ya desplegado en la sección 8.3) — no gestiona logins propios.

**1. Instalar dependencias del servidor MCP** (si no lo hiciste ya para
`mcp_server.py`):
```bash
.venv/bin/pip install -r requirements-mcp.txt
```

**2. Activar el Registro Dinámico de Cliente en Hydra** — ya está en
`deploy/hydra/hydra.yml` (`oidc.dynamic_client_registration.enabled: true`),
solo hace falta recrear el contenedor para que lo recoja:
```bash
docker compose up -d --force-recreate hydra
```

**3. Variables de entorno** (añade a `.env`/`/etc/guilda-work.env`):
```bash
MCP_REMOTO_ORIGIN=https://mcp.tu-hostname.sslip.io
HYDRA_PUBLIC_ORIGIN=https://hydra.tu-hostname.sslip.io   # ya definida si desplegaste Outline/EspoCRM
MCP_REMOTO_PUERTO=8017
```

**4. Bloque de Caddy** — ya está en `deploy/Caddyfile`
(`mcp.HOSTNAME { reverse_proxy localhost:8017 }`), solo falta que Caddy
recargue la configuración (mismo mecanismo que el resto de subdominios de
esta guía).

**5. Arrancarlo como proceso persistente** (mismo patrón que `serve.py`
en la sección 6): copia
[`deploy/guilda-work-mcp.service`](deploy/guilda-work-mcp.service) a
`/etc/systemd/system/guilda-work-mcp.service`, ajusta `USUARIO`/rutas, y:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now guilda-work-mcp
```

**6. Variables de las herramientas que quieras exponer** — cada una es
opcional por separado (ver README.md): `ESPOCRM_API_KEY`,
`NEXTCLOUD_ADMIN_USER`/`NEXTCLOUD_ADMIN_PASSWORD` (ya definidas si
desplegaste el CRM/Drive), `OPENPROJECT_API_TOKEN`,
`CHATWOOT_AGENT_API_TOKEN` (**token de un agente normal**, generado en su
propio perfil → Ajustes de acceso a la API — distinto de
`CHATWOOT_PLATFORM_API_TOKEN`, que solo gestiona altas de usuarios),
`METABASE_API_KEY`, `N8N_API_KEY`, `OUTLINE_API_TOKEN`,
`SYNAPSE_BOT_ACCESS_TOKEN` (token de un usuario "bot" dedicado —
créalo con `register_new_matrix_user` dentro del contenedor de Synapse,
nunca reutilices el token de una persona real), `MINIO_ROOT_PASSWORD`
(ya definida), `UPTIME_KUMA_API_KEY`. **Vaultwarden no tiene variable
aquí a propósito** — queda excluido del MCP bajo cualquier circunstancia.

**7. Verificar**:
```bash
curl https://mcp.tu-hostname.sslip.io/.well-known/oauth-protected-resource
```
Debería devolver un JSON con `resource`/`authorization_servers` (RFC9728)
— confirma que el servidor está sirviendo y anuncia Hydra como su
autorización. La verificación completa (ChatGPT conectándose de verdad,
flujo OAuth de punta a punta) solo se puede hacer añadiendo el conector
desde los Ajustes de ChatGPT una vez todo lo de arriba esté desplegado.

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
