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
EOF
sudo systemctl restart guilda-work
```

Si alguna de estas herramientas no la vas a desplegar nunca, quítala del
todo de la lista en `app/herramientas.py` — sin la variable de entorno
correspondiente, la página la sigue mostrando igual, apuntando a su
puerto de desarrollo local (`127.0.0.1:...`), que en el VPS no sirve de
nada.

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
   `hydra.`, `outline.`, `chat.`, `matrix.`, y los opcionales que tengas
   activos) apuntando todos a la IP del VPS.
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
