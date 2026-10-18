# Hosting en un VPS (Fase 3 de la app móvil)

Guía lista para ejecutar el día que decidas contratar un VPS. Mientras
tanto, la vía gratuita para tener la API accesible desde internet es
[`CASERO.md`](CASERO.md) (Tailscale Funnel, sin coste, sin dominio, sobre
tu propio PC). Contratar y pagar el VPS es algo que tienes que hacer tú
— esta guía empieza justo después de tener el servidor creado.


<!-- INDICE -->
## Mapa por temas

Esta guía está en orden cronológico; aquí está ordenada por temas.

**Poner el servidor en marcha**
- [Elegir proveedor](#elegir-proveedor)
- [1. Acceso y hardening básico](#1-acceso-y-hardening-básico)
- [2. Instalar dependencias y traer el código](#2-instalar-dependencias-y-traer-el-código)
- [3. Variables de entorno de producción](#3-variables-de-entorno-de-producción)
- [4. Hostname sin dominio propio (sslip.io)](#4-hostname-sin-dominio-propio-sslipio)
- [5. Caddy: proxy inverso con HTTPS automático](#5-caddy-proxy-inverso-con-https-automático)
- [6. systemd: que `serve.py` arranque solo y se reinicie si muere](#6-systemd-que-servepy-arranque-solo-y-se-reinicie-si-muere)
- [7. Verificar](#7-verificar)
- [Dimensionar el servidor para el stack completo](#dimensionar-el-servidor-para-el-stack-completo)
- [Migrar de sslip.io a un dominio propio](#migrar-de-sslipio-a-un-dominio-propio)

**Resto del stack y copias de seguridad**
- [8. Desplegar el resto del stack (Metabase/MinIO/n8n/Kratos/Hydra/Outline/Element+Synapse)](#8-desplegar-el-resto-del-stack-metabaseminion8nkratoshydraoutlineelementsynapse)
- [9. Backups (recomendado)](#9-backups-recomendado)
- [Copia de seguridad con Restic en el segundo disco](#copia-de-seguridad-con-restic-en-el-segundo-disco)

**Producto y operación (backoffice)**
- [Backoffice independiente (backoffice.guildawork.com)](#backoffice-independiente-backofficeguildaworkcom)
- [Comunicados y buscador del backoffice](#comunicados-y-buscador-del-backoffice)
- [Modo mantenimiento y «ver como»](#modo-mantenimiento-y-ver-como)
- [Puesta en marcha guiada del despacho](#puesta-en-marcha-guiada-del-despacho)
- [Tope de consumo de IA por despacho](#tope-de-consumo-de-ia-por-despacho)

**API, MCP y seguridad de acceso**
- [10. MCP remoto (ChatGPT)](#10-mcp-remoto-chatgpt)
- [API ampliada y herramientas de IA/MCP por grupos](#api-ampliada-y-herramientas-de-iamcp-por-grupos)
- [API robusta para uso externo, sincronización y webhooks persistentes](#api-robusta-para-uso-externo-sincronización-y-webhooks-persistentes)
- [Tokens de API: áreas, caducidad y registro de uso](#tokens-de-api-áreas-caducidad-y-registro-de-uso)
- [Fase 0 de OAuth2 y primer paquete de mejoras de API/MCP](#fase-0-de-oauth2-y-primer-paquete-de-mejoras-de-apimcp)
- [API de tareas completa](#api-de-tareas-completa)
- [API fiscal completa](#api-fiscal-completa)
- [API: adjuntos de notas, envío de correo, plantillas y administración del fichaje](#api-adjuntos-de-notas-envío-de-correo-plantillas-y-administración-del-fichaje)
- [Hydra sin `--dev` (2026-10-10)](#hydra-sin---dev-2026-10-10)
- [MCP: medido, limitado y auditado](#mcp-medido-limitado-y-auditado)
- [OpenAPI completo y contrato de la API](#openapi-completo-y-contrato-de-la-api)
- [SDK de Python y TypeScript y colección de Postman](#sdk-de-python-y-typescript-y-colección-de-postman)
- [Estado del servicio, errores 5xx, límites por tipo y restricciones de token](#estado-del-servicio-errores-5xx-límites-por-tipo-y-restricciones-de-token)
- [Revisión de seguridad (2026-10-11) y limpieza de disco](#revisión-de-seguridad-2026-10-11-y-limpieza-de-disco)
- [Política de contenido (CSP) estricta para scripts](#política-de-contenido-csp-estricta-para-scripts)
- [Verificación en dos pasos (TOTP) para los usuarios de la app](#verificación-en-dos-pasos-totp-para-los-usuarios-de-la-app)
- [Foto de montaña en el inicio de sesión](#foto-de-montaña-en-el-inicio-de-sesión)

**Documentación y ayuda**
- [Ayuda contextual (enlaces al centro de ayuda)](#ayuda-contextual-enlaces-al-centro-de-ayuda)

**Otros**
- [Fuera de alcance de esta guía](#fuera-de-alcance-de-esta-guía)
- [Aspecto de la app: superficies de cristal](#aspecto-de-la-app-superficies-de-cristal)
- [Exportar a PDF (informes y fichajes)](#exportar-a-pdf-informes-y-fichajes)
- [El asistente de IA como soporte de la plataforma](#el-asistente-de-ia-como-soporte-de-la-plataforma)
- [Sistema de diseño (componentes y candado)](#sistema-de-diseño-componentes-y-candado)
- [Núcleo común y módulos de negocio (Día 3 del plan maestro)](#núcleo-común-y-módulos-de-negocio-día-3-del-plan-maestro)
- [Módulo Gabinete de abogados (Día 4 del plan maestro)](#módulo-gabinete-de-abogados-día-4-del-plan-maestro)
- [Módulo Inmobiliaria (Día 5 del plan maestro)](#módulo-inmobiliaria-día-5-del-plan-maestro)
- [Día 6 del plan maestro: gestoría, informes, asistente con contexto y móvil](#día-6-del-plan-maestro-gestoría-informes-asistente-con-contexto-y-móvil)
- [Día 7 del plan maestro: cifrado de documentos, privacidad, rendimiento y cierre](#día-7-del-plan-maestro-cifrado-de-documentos-privacidad-rendimiento-y-cierre)
- [Semana 2 del plan maestro: accesos de máquinas a lo cifrado, expediente fiscal y rotación de la clave](#semana-2-del-plan-maestro-accesos-de-máquinas-a-lo-cifrado-expediente-fiscal-y-rotación-de-la-clave)
- [Revisión en el navegador de lo hecho desde el Día 3](#revisión-en-el-navegador-de-lo-hecho-desde-el-día-3)
- [Correo cifrado con niveles (semana 2 del plan maestro)](#correo-cifrado-con-niveles-semana-2-del-plan-maestro)
- [Pendientes de la semana 2 cerrados: concesión de servicio y nombres de documentos por nivel](#pendientes-de-la-semana-2-cerrados-concesión-de-servicio-y-nombres-de-documentos-por-nivel)
- [`db.py` y `mcp_tools` divididos por dominios (sin cambiar su comportamiento)](#dbpy-y-mcp_tools-divididos-por-dominios-sin-cambiar-su-comportamiento)
- [Resumen diario de pendientes (13 oct 2026)](#resumen-diario-de-pendientes-13-oct-2026)
- [Ausencias, vacaciones y permisos (13 oct 2026)](#ausencias-vacaciones-y-permisos-13-oct-2026)
- [Turnos, bolsa de horas, herramientas de IA/MCP, backoffice y ayuda (13 oct 2026)](#turnos-bolsa-de-horas-herramientas-de-iamcp-backoffice-y-ayuda-13-oct-2026)
- [Certificados digitales (fase B de la especificación de control fiscal, 13 oct 2026)](#certificados-digitales-fase-b-de-la-especificación-de-control-fiscal-13-oct-2026)
- [Control fiscal — fase E: traspasos y panel (14 oct 2026)](#control-fiscal--fase-e-traspasos-y-panel-14-oct-2026)
- [Control fiscal — fase A: cimientos (13 oct 2026)](#control-fiscal--fase-a-cimientos-13-oct-2026)
- [Catálogo de reglas fiscales y laborales (backoffice)](#catálogo-de-reglas-fiscales-y-laborales-backoffice)
- [Importar clientes desde Excel o CSV](#importar-clientes-desde-excel-o-csv)
- [Hoy: la bandeja única de lo que necesita a cada persona](#hoy-la-bandeja-única-de-lo-que-necesita-a-cada-persona)
- [Barra lateral a medida y fichas con una sola fila de pestañas](#barra-lateral-a-medida-y-fichas-con-una-sola-fila-de-pestañas)
- [Facturación conectada con los expedientes](#facturación-conectada-con-los-expedientes)
- [Facturas para contabilizar y fichero de enlace de a3 (SUENLACE.DAT)](#facturas-para-contabilizar-y-fichero-de-enlace-de-a3-suenlacedat)

<!-- /INDICE -->

## Elegir proveedor

| Proveedor | Precio aprox./mes | Notas |
|---|---|---|
| **Hetzner Cloud** (CX22) | ~€4,5 | Mejor relación calidad/precio, datacenters en Alemania/Finlandia. Recomendación por defecto si no quieres complicarte. |
| **Contabo** | ~€4-5 | Más RAM/disco por el precio, pero rendimiento más variable (servidores más compartidos). |
| **DigitalOcean** | ~$6 | Muy bien documentado, buena opción si es tu primer VPS. |
| **Oracle Cloud "Always Free"** | Gratis de verdad | 4 núcleos ARM + 24GB RAM gratis para siempre, pero el proceso de alta de cuenta es errático (a veces rechaza tarjetas o "recupera" recursos sin avisar). Vale la pena intentarlo si no te importa la posible fricción inicial. |

Para el uso de esta app **sola** (un solo backend Flask + SQLite, tráfico
bajo), la oferta más pequeña de cualquiera de ellos sobra: 1 vCPU / 1-2GB
RAM. Si vas a levantar también el stack de herramientas conectadas (paso
8), esa cifra ya no aplica — ver "Dimensionar el servidor para el stack
completo" más abajo, justo antes del paso 8.
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

Variables opcionales:

| Variable | Por defecto | Para qué |
|---|---|---|
| `GUILDA_THREADS` | `16` | Hilos de waitress (su valor propio es 4). |
| `GUILDA_POOL_CONEXIONES` | `1` | Reutiliza las conexiones a `registro.db` dentro de cada hilo en vez de abrir una por consulta (abrirla cuesta ~3 ms por el esquema; con el pool, 16 peticiones simultáneas pasan de 12 a ~185 por segundo). `0` lo apaga y vuelve al comportamiento anterior. |
| `GUILDA_BACKUPS_DIR` | `data/backups` | Carpeta de la copia única de `registro.db` (ver §9.1). |
| `GUILDA_LIMITER_URI` | `memory://` | Almacén de los contadores del limitador de peticiones. |
| `GUILDA_CORREO_SYNC_MINUTOS` | `5` | Cada cuántos minutos el servidor sincroniza el correo de todas las cuentas. `0` lo desactiva. |
| `GUILDA_CORREO_IDLE` | `1` | Correo casi instantáneo con IMAP IDLE: una conexión en espera por cuenta IMAP que sincroniza al aviso del servidor. `0` lo desactiva (queda el auto-sync periódico). |
| `GUILDA_CORREO_IDLE_MAX` | `100` | Máximo de cuentas con IDLE a la vez (una conexión y un hilo por cuenta). |
| `GUILDA_CERT_HOSTS` | (el de `GUILDA_URL_PUBLICA`) | Dominios cuyo certificado HTTPS vigila el panel de salud, separados por comas. Ámbar a 21 días de caducar y rojo a 7. |
| `GUILDA_CADUCIDADES` | (vacío) | Cosas que caducan y nadie más vigila: `Secreto de Microsoft=2028-10-01;Dominio guildawork.com=2027-03-15`. Ámbar a 45 días y rojo a 14; el vigilante avisa por correo de lo que esté en rojo. |
| `GUILDA_CORREO_PROPIO_HOST` | `mail.guildawork.com` | Servidor IMAP/SMTP al que se conectan los buzones que el despacho crea en un paso (Cuentas de correo → «Crear un buzón del despacho»). **Ojo:** desde el propio servidor ese nombre apunta a la IP pública y el cortafuegos (ufw) no deja entrar a 993/465 desde el propio host, así que la conexión falla; para que funcione desde aquí, añade `127.0.0.1 mail.guildawork.com` a `/etc/hosts` (el certificado es el del nombre, no el de la IP; comprobado: 127.0.0.1:993 con ese nombre verifica bien). |
| `GUILDA_FICHAJE_AVISO_TURNO_MARGEN_HORAS` | `1` | Horas de margen tras el fin de su turno (cuadrante de Fichaje › Turnos) con la jornada todavía abierta antes de avisar a la persona, una vez por jornada. Un valor negativo desactiva este aviso. Sin turno asignado ese día no se avisa. |
| `GUILDA_CORREO_PROPIO_IMAP` | `993` | Puerto IMAP (TLS) de esos buzones. |
| `GUILDA_CORREO_PROPIO_SMTP` | `465` | Puerto SMTP (TLS implícito) de esos buzones. |
| `GUILDA_URL_PUBLICA` | _(vacío)_ | URL pública de la app (p. ej. `https://work.tudominio.com`), sin barra final. La usan los correos que se mandan sin petición web de por medio —recordatorios de vencimientos a clientes— para enlazar al portal. Sin ella el correo sale sin enlace. |
| `GUILDA_FICHAJE_AVISO_HORAS` | `10` | Horas con la jornada de fichaje abierta tras las cuales se avisa (una vez por jornada) de que quizá se olvidó la salida. `0` lo desactiva. Se comprueba cada 15 minutos. |

**Sincronización del correo**: `serve.py` lanza un hilo que, cada
`GUILDA_CORREO_SYNC_MINUTOS`, descarga el correo nuevo de las cuentas de
todos los usuarios (a los 60 s de arrancar y luego a intervalos). Sin él, el
correo solo se descargaba al pulsar "Sincronizar". Si una cuenta falla
(contraseña caducada, servidor caído), el error se muestra en *Correo →
Cuentas* y en la bandeja; tras 3 fallos seguidos solo se reintenta cada 6
ciclos para no insistir con credenciales malas. Para comprobarlo:
`ultima_sincronizacion` de `correo_cuentas` debe avanzar cada pocos minutos.

**Limitador de peticiones**: por defecto sus contadores viven en la memoria
del proceso, así que se reinician con cada reinicio del servicio y no se
comparten entre procesos. Con un solo proceso de waitress (la instalación
actual) es suficiente. Solo si se lanzan varios procesos haría falta un
almacén compartido, por ejemplo `GUILDA_LIMITER_URI=redis://127.0.0.1:6379`
(requiere instalar el paquete `redis` y tener un Redis en marcha).

### Correo con OAuth2 (Gmail y Microsoft 365)

Opcional. Si no se configura, la opción «Conectar con Google/Microsoft» no aparece en Correo → Cuentas
y siguen funcionando las cuentas con contraseña (o contraseña de aplicación). Cada instalación registra
**su propia aplicación** y la configura por entorno:

| Variable | Descripción |
|---|---|
| `GUILDA_OAUTH_GOOGLE_CLIENT_ID` / `GUILDA_OAUTH_GOOGLE_CLIENT_SECRET` | Cliente OAuth de Google Cloud. |
| `GUILDA_OAUTH_MICROSOFT_CLIENT_ID` / `GUILDA_OAUTH_MICROSOFT_CLIENT_SECRET` | Registro de aplicación de Azure (Entra ID). |
| `GUILDA_OAUTH_MICROSOFT_TENANT` | `common` (por defecto: cuentas de trabajo y personales) u `organizations`, o el id de un tenant concreto. |
| `GUILDA_PUBLIC_URL` | Opcional. Dirección pública (`https://work.ejemplo.com`) para construir la URI de retorno si el proxy no la transmite bien. |

**URIs de redirección** (registrarlas tal cual en cada proveedor):
`https://TU-DOMINIO/correo/oauth/google/callback` y `https://TU-DOMINIO/correo/oauth/microsoft/callback`.

**Google Cloud** (console.cloud.google.com): proyecto → *APIs y servicios* → (no hace falta habilitar la Gmail API) 
con la *Pantalla de consentimiento OAuth* (tipo *Externo*, o *Interno* si todos los usuarios son de un mismo Workspace)
→ añadir el ámbito `https://mail.google.com/` → *Credenciales* → *ID de cliente OAuth* de tipo *Aplicación web*
con la URI de retorno de arriba. Ojo: `https://mail.google.com/` es un ámbito **restringido**. Mientras la app esté en
modo *Pruebas* solo funciona con las cuentas dadas de alta como *usuarios de prueba* (y el permiso caduca a los 7 días).
Para uso real con cuentas Gmail ajenas Google exige verificación de la aplicación y una evaluación de seguridad; con
Workspace *Interno* no hace falta.

**Microsoft** (portal.azure.com → *Microsoft Entra ID* → *Registros de aplicaciones* → *Nuevo registro*): plataforma
*Web* con la URI de retorno; *Certificados y secretos* → nuevo secreto de cliente (el **valor**, no el id);
*Permisos de API* → *Microsoft Graph*… no: **Office 365 Exchange Online** (delegados) `IMAP.AccessAsUser.All` y `SMTP.Send`,
más `offline_access`, `openid` y `email`. En el tenant de la organización el administrador puede tener que
conceder el consentimiento, y el buzón debe tener IMAP y *SMTP autenticado* habilitados en Exchange Online.

El token de refresco se guarda en el almacén de credenciales (como las contraseñas); el de acceso solo en memoria.
Si el proveedor revoca el permiso, la cuenta muestra «vuelve a conectarla» y se reconecta desde Correo → Cuentas.

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

## Dimensionar el servidor para el stack completo

La tabla de "Elegir proveedor" de arriba vale para la app sola. En cuanto
entras en el paso 8 y conectas herramientas de verdad, el dimensionado
cambia — y **conviene decidirlo antes de crear el servidor**, no después:
migrar de tamaño de máquina en Hetzner es sencillo (para/redimensiona/
arranca), pero perder tiempo con OOM-kills y swap constante mientras
pruebas la instancia no lo es.

**Recomendación: `CPX22` (2 vCPU dedicadas / 4GB RAM / 40GB, ~€11,49/mes)
como mínimo**, no la `CX22` de vCPU compartida de la tabla de arriba
(mismo nombre de tamaño, línea de producto distinta) — para un conjunto
de servicios así de variado (Ruby/OpenProject, Python/Synapse, Node/
Outline y Documenso, PHP/FacturaScripts y Nextcloud, Rust/Meilisearch y
Stalwart, más sus Postgres respectivos), los picos de CPU concurrentes
son reales y una vCPU compartida (`CX`) se nota mucho más que en el uso
ligero de la app sola.

Con `CPX22` cabe con margen razonable, para un primer tenant, el núcleo
imprescindible más las herramientas conectadas de mayor valor:

| Pieza | Por qué entra en el mínimo |
|---|---|
| `serve.py` + Caddy + Ory Kratos/Hydra | La columna vertebral (login, SSO, MCP remoto) — no se puede añadir más adelante sin fricción, el resto de herramientas SSO se registran contra Hydra desde el minuto uno. |
| Guía para desarrolladores (`/docs`) | Sin coste — páginas Flask servidas por el propio `serve.py`, sin contenedor ni servicio propio. |
| Meilisearch | Buscador unificado + base del RAG semántico — ligero (Rust), ver 8.30. |
| Stalwart | Correo propio — ligero (Rust), ver 8.27. |
| FacturaScripts | Facturación — una instancia por tenant, ver 8.21; esta cifra asume **un** tenant. |
| Documenso | Firma electrónica, ver 8.22. |
| Nextcloud | Drive con SSO, ver 8.20. |
| Paperless-ngx | Gestión documental + OCR, ver 8.23 — el paso de OCR en sí (Tesseract) es el único pico de CPU puntual de esta lista, no un consumo sostenido. |
| Outline | Wiki/documentación interna con SSO, ver 8.6. |
| OpenProject | Gestión de proyectos, ver 8.10. |
| Element + Synapse | Chat, con especial cuidado en el SSO (ver los avisos de la 8.8: es la integración con más fricción de arranque de todo el stack). |

**Aviso honesto, no medido en vivo como Meilisearch/Ollama (8.30/8.35)**:
de esta lista, **OpenProject y Synapse son los dos puntos calientes de
memoria** — ambos proyectos recomiendan en su propia documentación
oficial acercarse a los 2-4GB solo para ellos bajo uso real (Rails y
Postgres uno, Python/Twisted el otro), no en el sentido de "arrancan y
ya" sino de "van finos". En `CPX22` arrancan y funcionan para dar de
alta el primer tenant y probar el flujo completo, pero con poco margen —
vigila `free -h` y `docker stats` la primera semana con uso real
simultáneo de varias herramientas. Si el presupuesto lo permite, subir a
`CPX32` (4 vCPU / 8GB, ~€22,49/mes) da margen de verdad en vez de "cabe
justo" — normalmente compensa el diferencial de precio en menos tiempo
perdido depurando lentitud que no es un bug, sino falta de RAM.

Herramientas que **no** hace falta meter en este mínimo, quedan igual de
bien para cuando haya un tenant real pidiéndolas (ver también la nota de
autoalojamiento en `/docs/autoalojamiento`): Grafana+Loki+Promtail
(8.32, sustituible por `journalctl`/logs de Docker a pelo al principio),
Metabase, Baserow (8.24, se solapa con OpenProject para llevar
tareas/hojas de cálculo — con OpenProject ya en el mínimo, Baserow
aporta poco extra al principio), Portainer (8.33), Collabora (8.34),
Jitsi Meet (8.29) y n8n.

## 8. Desplegar el resto del stack (Metabase/MinIO/n8n/Kratos/Hydra/Outline/Element+Synapse)

Todo esto vive en `docker-compose.yml`, ya en el repo que clonaste en el
paso 2 — no hace falta clonar nada aparte. Los puertos que publica cada
contenedor están fijados a `127.0.0.1` a propósito (ver la cabecera del
propio `docker-compose.yml`): Docker manipula `iptables` directamente al
publicar puertos, así que un puerto publicado en `0.0.0.0` **salta por
encima de `ufw`** — con `127.0.0.1:` explícito, la única puerta de
entrada real desde internet es Caddy (que sí corre en el host y alcanza
`localhost`).

### Herramientas de mantenimiento (solo lectura)

- `scripts/probar.sh --carga` — prueba de carga: N usuarios a la vez (lecturas y escrituras) sobre una base sintética y temporal.
  `--usuarios 40 --segundos 40 --vencimientos 20000 --pausa 3` (pausa media entre clics) o `--pausa 0` para ver dónde se satura.
- `scripts/probar.sh --perfil` — tiempo, consultas y peso de cada pantalla con un año de datos.
- `scripts/auditar_contenedores.py` — memoria, contenedores parados, volúmenes huérfanos, imágenes sin uso y tráfico/errores 5xx por dominio
  (según Caddy). No borra nada: propone los comandos de limpieza.

### Versiones de las imágenes (fijadas por digest)

Las imágenes de `docker-compose.yml` que están en marcha van fijadas como `repo:etiqueta@sha256:…`: la etiqueta
se conserva para leer la versión, pero Docker usa el digest, así que ni un `docker compose pull` ni un reinicio
pueden traer otra versión sin que alguien lo decida. (Los tenants nuevos de FacturaScripts usan
`FACTURASCRIPTS_IMAGEN`, con el mismo criterio.) El panel de dependencias del backoffice solo avisa de las
que sigan con `latest` sin digest.

Para **subir de versión a propósito** (un `docker compose pull` no sirve: bajaría el digest fijado, es decir, lo mismo):

1. Haz un backup y, si puedes, prueba antes la versión nueva con una copia de los datos.
2. En `docker-compose.yml`, quita el `@sha256:…` de esa imagen (y, si quieres, cambia la etiqueta a la versión concreta).
3. `docker compose pull <servicio> && docker compose up -d <servicio>` y comprueba que responde.
4. `scripts/fijar_imagenes.py --aplicar` vuelve a fijar lo que quedó en marcha. Para volver atrás: `git revert` del cambio en el compose y `up -d`.

`scripts/fijar_imagenes.py` sin opciones solo muestra qué cambiaría.

### Stalwart: permitir la IP de la pasarela de Docker (importante)

Todo lo que llega a Stalwart por Caddy o desde el host entra desde la IP de la pasarela de la red de Docker (`172.18.0.1`
en esta instalación; compruébala con `docker network inspect guilda-work_default`). Si un escáner de internet dispara la
protección de Stalwart «portScanning», **Stalwart bloquea esa IP para siempre** y deja de responder al panel, a la API JMAP y a la
integración de Guilda Work (en producción pasó el 2026-08-10 y nadie lo notó hasta el 2026-10-08: respuestas 502 en
`correo-stalwart.<dominio>`). Evítalo dando de alta esa IP en las IP permitidas (WebUI de Stalwart → IP permitidas, o
`x:AllowedIp/set` por JMAP). Si ya está bloqueada: quitarla de IP bloqueadas **y reiniciar el contenedor** (`docker restart guilda-work-stalwart`),
porque la lista de bloqueo se carga en memoria.

### Stalwart: certificado válido en IMAP/SMTP

Por defecto Stalwart presenta un certificado **autofirmado** en los puertos de correo (993, 465, 25) y los clientes (Outlook, el móvil
o el propio Correo de Guilda Work) lo rechazan. El 443 va por Caddy, que sí tiene el de Let's Encrypt. Solución instalada:

1. `deploy/sincronizar-certificado-stalwart.sh` (copiado a `/usr/local/sbin/`) copia el certificado de `mail.guildawork.com` de Caddy a
   `/etc/guilda-work/stalwart-certs/` (Stalwart corre como uid 2000 y los ficheros de Caddy son privados), y reinicia Stalwart solo si ha cambiado.
2. `deploy/stalwart-cert.timer` (copiado a `/etc/systemd/system/`, `systemctl enable --now stalwart-cert.timer`) lo ejecuta a diario a las 04:30:
   Caddy renueva cada ~60 días y así Stalwart lo recoge sin intervención.
3. `docker-compose.yml` monta esa carpeta en `/certs` (solo lectura) y en Stalwart hay un objeto Certificate con `File` →
   `/certs/mail.guildawork.com.crt|key`, marcado como certificado predeterminado (`x:SystemSettings.defaultCertificateId`).

Puertos con TLS real: 993 (IMAP), 465 (SMTP de envío, TLS implícito), 995 (POP3), 25 (SMTP entre servidores, STARTTLS). **No existen los puertos
587, 143 ni 110** (Stalwart no tiene esos escuchadores aunque el compose los publique): al configurar un cliente, SMTP = 465 con TLS.

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

> **Panel retirado (2026-10-07):** esto vivía en `app.guildawork.com/backoffice`. Ahora las
> URLs `/backoffice/...` de la app solo redirigen a https://backoffice.guildawork.com (variable
> opcional `GUILDA_BACKOFFICE_URL`); el icono del rail para administradores abre el backoffice
> nuevo. Lo que sigue describe las funciones, que se mantienen en el backoffice independiente.

Página de backoffice para crear/renombrar/
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
los aproveche son solo una etiqueta.

**Nota — resuelto (2026-08-14)**: esto estuvo señalado aquí como deuda
pendiente porque `tareas`/`notas`/`categorías` no tienen columna
`tenant_id` — solo `usuario_id`. Investigado a fondo: cada consulta de
esas tablas YA filtra por `usuario_id` en todo lectura/escritura
(`app/db.py`: `obtener_tarea`, `editar_tarea`, `eliminar_tarea`,
equivalentes en notas/categorías), así que el aislamiento entre tenants
es real, no una etiqueta — verificado con
`tests/test_aislamiento_tenants.py` (2 tenants × 2 usuarios, capa BD y
capa ruta, incluyendo intentos con ID adivinado). **Se decidió NO
añadir una columna `tenant_id` duplicada** a esas 3 tablas: a
diferencia de `fichajes` (que sí la duplica, a propósito, como
snapshot inmutable con fin legal/auditoría — ver comentario en
`app/db.py` sobre esa tabla), `tareas`/`notas`/`categorías` son
registros editables y `asignar_tenant()`/`desasignar_tenant()`
(`app/db.py`) solo actualizan `usuarios.tenant_id` — un `tenant_id`
duplicado ahí se quedaría obsoleto en cuanto alguien cambiara de
tenant, sería un bug nuevo en vez de una mejora.

Cualquier funcionalidad futura que necesite agregar datos entre varios
usuarios de un mismo tenant (el calendario fiscal, por ejemplo, cuyas
tablas `clientes_fiscales`/`vencimientos_fiscales` sí llevan
`tenant_id` real desde el principio, al ser registros de la gestoría y
no de un usuario concreto) debe usar `db.usuarios_de_tenant(tenant_id)`
en vez de reinventar el JOIN a mano.

**Enlace opcional con el calendario fiscal** (`app/rutas_fiscal.py`): al
dar de alta un cliente fiscal, se intenta (best-effort, igual que el
resto de esta sección) enlazarlo con una Cuenta de EspoCRM del mismo
nombre — `espocrm.buscar_cuenta_por_nombre()` reutiliza si ya existe,
si no `espocrm.crear_cuenta()` crea una nueva, y el id se guarda en
`clientes_fiscales.espocrm_cuenta_id`. Sin `ESPOCRM_API_KEY`, o si
EspoCRM está caído, el alta del cliente fiscal no se entera ni falla —
mismo criterio que el resto del stack. **No** hay sincronización en
sentido inverso ni de más campos (NIF, dirección, facturación) —
`clientes_fiscales` solo guarda lo mínimo para identificar al cliente
en un vencimiento (ver comentario de cabecera de esa tabla en
`app/db.py`), el enlace es solo un atajo de navegación ("Ver en
EspoCRM" en la ficha del cliente). El enlace usa `ESPOCRM_PUBLIC_ORIGIN`
(la URL real, no la interna `HERRAMIENTA_ESPOCRM_URL` que solo
resuelve entre contenedores Docker) — sin ella configurada, cae de
vuelta a la interna, que no abrirá en el navegador del usuario.

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

> **Causa raíz de las «caídas» de FacturaScripts (resuelta 2026-10-11):** no era Docker ni la memoria: eran los TESTS. Con una base temporal el primer tenant es el 1, y los tests de «borrar tenant» ejecutaban el `facturascripts.desaprovisionar_tenant(1)` real (`docker stop` + `docker rm` del contenedor de producción y `rmtree` de `…/facturascripts-tenants/tenant-1`). Cada `scripts/probar.sh` tumbaba el FacturaScripts y vaciaba sus datos en el segundo disco; el vigilante lo reconstruía a los 5 minutos y avisaba por correo (de ahí las decenas de avisos y los «kill → stop → destroy» de `docker-events.log`). Arreglo: `tests/conftest.py::sin_tocar_contenedores_ni_datos_de_produccion` (nombres `guilda-test-…`, carpeta de datos temporal y guarda que aborta cualquier `docker stop/rm/kill/restart` sobre `guilda-work-*`). Si alguna vez vuelve a haber una caída sin pruebas en marcha, esto ya no es la explicación.

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

**Datos de cada tenant en el segundo disco**: `MyFiles`/`Plugins`/`Dinamic`
del contenedor se montan (bind mount, no volumen Docker) en
`/mnt/HC_Volume_106540289/facturascripts-tenants/tenant-<id>/` — ese disco
extra (73G, aparte de los 75G del disco raíz) está prácticamente vacío, así
que se reserva en exclusiva para esto. Antes de este cambio esos tres
directorios vivían solo en la capa escribible del contenedor: efímeros
(se perdían adjuntos de factura y plugins instalados en cualquier
`docker rm`/recreación) y contando contra el disco raíz. Configurable con
`FACTURASCRIPTS_DATOS_HOST` si el disco cambiara de punto de montaje.

**Qué pasa al crear un tenant nuevo** (automático, sin nada que hacer a
mano): `app/facturascripts.py:aprovisionar_tenant()` crea un rol y una
base de datos exclusivos en el Postgres compartido
(`REVOKE CONNECT ... FROM PUBLIC`, para que ni siquiera con las
credenciales de otro tenant se pueda entrar), levanta un contenedor
nuevo (`guilda-work-facturascripts-tenant-<id>`, puerto `8100 + id`) con
sus tres directorios de datos del disco extra ya montados, y lo instala.
**Nota técnica** (verificado en vivo, no solo leyendo
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
para y borra su contenedor, su base de datos y su directorio en el
segundo disco automáticamente — no hace falta limpieza manual.

**MCP**: a diferencia del resto de herramientas del catálogo (una
instancia compartida, sin necesidad de decir de cuál se habla), las
tools `facturas_listar_clientes`/`facturas_crear_cliente`/
`facturas_listar_facturas`/`facturas_crear_factura` llevan un primer
parámetro `tenant` (el nombre tal cual aparece en el backoffice) —
imprescindible aquí porque cada tenant es una instancia física distinta.

**Nota de alcance — Veri\*Factu/SII**: España exige progresivamente
desde 2026 que el software de facturación registre las facturas de
forma inalterable y pueda remitirlas a la AEAT (normativa Veri\*Factu).
Guilda Work **no genera ni registra facturas él mismo** — solo hace
peticiones HTTP a la API de FacturaScripts, que es quien realmente
emite, guarda y (si corresponde) declara las facturas de cada tenant.
El cumplimiento de Veri\*Factu recae por tanto sobre **la instancia de
FacturaScripts de cada tenant**, no sobre Guilda Work — no hay ni
debería haber código de cumplimiento fiscal en este repo. Dos motivos
prácticos para tenerlo anotado aquí de todos modos: (1) conviene
verificar periódicamente que la imagen desplegada
(`facturascripts/facturascripts:latest`) ya soporta Veri\*Factu antes
de que la obligatoriedad alcance a los tenants afectados — comprobarlo
entrando a cualquier instancia de tenant, Ajustes → apartado de
facturación electrónica; (2) como plataforma multi-tenant, es
razonable que llegue una consulta de soporte sobre esto aunque la
responsabilidad técnica sea de FacturaScripts, no de Guilda Work — la
respuesta correcta es señalar a la propia documentación de
FacturaScripts, no intentar resolverlo aquí.

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

### 8.28 ntfy (notificaciones push) — instancia compartida, aislamiento por usuario+ACL de topic

[ntfy](https://ntfy.sh) (`binwiederhier/ntfy`, Apache-2.0/GPLv2 dual) —
notificaciones push autoalojadas: un topic por tenant, sin depender de
Firebase/APNs de terceros. Pensado para enganchar con Uptime Kuma
(alertas de caída), n8n (automatizaciones) y el propio asistente de IA
(`notificaciones_enviar`).

**Aislamiento entre tenants — verificado en vivo**: por defecto ntfy es
público de lectura/escritura en cualquier topic (pensado para
`ntfy.sh`) — se fuerza `NTFY_AUTH_DEFAULT_ACCESS=deny-all` para que un
topic sin ACL explícita no sea accesible por nadie, y cada tenant tiene
su propio usuario con acceso `read-write` únicamente a su propio topic.
Confirmado con un token real: publicar de forma anónima en el topic de
un tenant devuelve `403 forbidden` del propio servidor.

**El punto que costó más resolver**: `ntfy access` (conceder el ACL de
topic a un usuario) es, según su propia ayuda de la CLI, *"a server-only
command"* que gestiona directamente el archivo `user.db` — no hay
ningún endpoint HTTP equivalente (se probó `POST /v1/users/.../access/...`
contra un contenedor real: `404`). La creación del usuario y la
generación de su token sí son HTTP puro (`POST /v1/users`,
`POST /v1/account/token`), así que solo ese paso de ACL se ejecuta por
`docker exec` (ver `app/ntfy.py:_conceder_acceso`, mismo patrón que
`app/facturascripts.py:_ejecutar_psql`) — no es un paso manual del
admin, es automático, solo que por un mecanismo distinto al resto.

**Arranque — un único paso manual, el alta del admin**:

```bash
docker compose up -d ntfy
docker exec -e NTFY_PASSWORD=elige-una-contrasena ntfy user add --role=admin admin
```

Añade a `.env`:
```bash
HERRAMIENTA_NTFY_URL=http://127.0.0.1:8027
NTFY_PUBLIC_ORIGIN=https://notificaciones.tu-hostname
NTFY_ADMIN_USER=admin
NTFY_ADMIN_PASSWORD=elige-una-contrasena
NTFY_CONTENEDOR=guilda-work-ntfy   # opcional, ya es el valor por defecto
```

**Qué pasa al crear un tenant nuevo** (100% automático una vez el admin
está dado de alta): usuario `tenant_<id>` + topic `guilda-<slug>-<id>` +
ACL `read-write` exclusiva + token, con el token ya guardado — nada que
pegar a mano. El token no se puede volver a leer una vez generado (mismo
criterio que `stalwart_api_key`): si el aprovisionamiento falla a mitad
y se reintenta, y el usuario de ntfy ya existe de un intento anterior,
hace falta borrarlo a mano (`docker exec ... ntfy user del tenant_<id>`)
antes de reintentar — caso raro, documentado en el propio
`app/ntfy.py:aprovisionar_tenant`.

**MCP**: `notificaciones_enviar` lleva un primer parámetro `tenant`,
octavo cliente del catálogo con este patrón.

### 8.29 Jitsi Meet (videollamadas) — instancia compartida, aislamiento por sala vía JWT

[Jitsi Meet](https://jitsi.org) (`ghcr.io/jitsi/{web,prosody,jicofo,jvb}`,
Apache-2.0) — videollamadas autoalojadas, integradas con Cal.diy (cada
cita reservada genera su propia sala automáticamente) y disponibles bajo
demanda desde el asistente de IA.

**Aislamiento entre tenants**: una videollamada no tiene datos
persistentes que aislar (la sala es efímera) — lo que de verdad aísla es
que cada JWT emitido por Guilda Work (`app/jitsi.py:generar_jwt_sala`)
solo es válido para **una sala concreta**, con el slug del tenant como
prefijo de su nombre. El secreto de firma (`JITSI_JWT_APP_SECRET`) es
compartido entre todos los tenants — no hace falta que sea distinto por
tenant, porque el JWT en sí ya lleva grabado a qué sala da acceso.

**Desplegado de verdad en producción (Linux real, 2026-08-19)**: los 4
servicios (`web`/`prosody`/`jicofo`/`jvb`) corren en el VPS con
`ENABLE_AUTH=1`/`AUTH_TYPE=jwt` activos — arranque limpio, Jicofo se
autentica contra Prosody y descubre el JVB con el módulo de
autenticación JWT cargado, sin errores propios del módulo. Se
encontró y corrigió un bug real en el propio `docker-compose.yml`: el
mapeo de puerto de `jitsi-web` estaba puesto a `80` (`127.0.0.1:8028:80`),
pero la imagen `ghcr.io/jitsi/web:unstable` escucha en `8000`/`8443`
internamente, no en `80` — confirmado con
`docker exec ... grep listen .../site-confs/default` y `docker port` —
sin esto, Docker aceptaba la conexión TCP pero nunca llegaba a nginx
("Connection reset by peer" en cada petición). Corregido a
`127.0.0.1:8028:8000`; confirmado con
`curl -H 'Host: meet.guildawork.com' http://127.0.0.1:8028/` → HTTP 200.
Bloque de Caddy añadido para `meet.guildawork.com` (reverse proxy a
`localhost:8028`, mismo patrón que el resto de subdominios) y
`app/jitsi.py:generar_jwt_sala()` confirmado generando un JWT
correctamente formado contra el secreto real.

**Verificación de punta a punta completada (2026-08-19, tras el alta del
DNS por parte del usuario)**: con el navegador real (Chrome, sesión ya
autenticada en `app.guildawork.com`) se creó una sala desde
`/videollamadas/`, redirigió a `https://meet.guildawork.com/<sala>?jwt=...`
con certificado HTTPS válido, la sala se creó sola sin aprovisionamiento
previo, y se entró como moderador (badge "M jorge@..." visible dentro de
la reunión, nombre y rol correctamente extraídos del JWT). Abrir la
misma URL de sala **sin** el parámetro `jwt` en una segunda pestaña
mostró el diálogo nativo de Jitsi "Se requiere autenticación" pidiendo
usuario/contraseña (que no existen por este mecanismo) — confirma que
el aislamiento por JWT-por-sala funciona de verdad, no solo en el papel.
**Hallazgo menor, no bloqueante**: la consola muestra errores
`service-unavailable` al pedir credenciales STUN/TURN (`extdisco:1`/`extdisco:2`
no configurado en Prosody) — no impide crear/entrar a la sala ni afecta
llamadas entre participantes en la misma red/NAT, pero podría dificultar
el establecimiento de medios entre dos participantes detrás de NATs
distintos en producción real; revisar si hace falta activar `mod_turncredentials`
en Prosody si se detectan problemas de conexión reales entre usuarios.

**Ruta web nueva**: hasta ahora solo el Asistente de IA podía generar
una sala (`videollamadas_crear_sala`, MCP) — un empleado que quisiera
iniciar una llamada sin pasar por un prompt no tenía forma de hacerlo.
`GET/POST /videollamadas` (`app/rutas_videollamadas.py`, enlazado desde
el rail de navegación) genera la sala y redirige directamente a la URL
de Jitsi con el JWT ya incluido.

**El punto que costó más resolver en este entorno concreto**: el propio
despliegue oficial de `docker-jitsi-meet` asume bind mounts con
`chown -R 1000:1000` hecho a mano en el host antes del primer arranque
— en Windows con Docker Desktop esto falla de forma no obvia
("`directory '/var/lib/prosody' is not writable`") incluso después de
`chmod 777`, por una traducción de permisos entre el host y la VM del
propio Docker Desktop. Se resolvió usando **volúmenes con nombre** en
vez de bind mounts (Docker gestiona los permisos internamente, sin
chown manual) — además de evitar el problema, es un paso menos que
documentar para quien despliegue esto.

**Arranque**:

```bash
docker compose up -d jitsi-prosody jitsi-jicofo jitsi-jvb jitsi-web
```

Añade a `.env`:
```bash
HERRAMIENTA_JITSI_URL=http://127.0.0.1:8028
JITSI_PUBLIC_ORIGIN=https://videollamadas.tu-hostname
JITSI_PUBLIC_HOSTNAME=videollamadas.tu-hostname
JITSI_JWT_APP_ID=guilda_work
JITSI_JWT_APP_SECRET=...        # openssl rand -base64 32
JITSI_JICOFO_COMPONENT_SECRET=... # openssl rand -base64 32
JITSI_JVB_AUTH_PASSWORD=...       # openssl rand -base64 32
JITSI_JICOFO_AUTH_PASSWORD=...    # openssl rand -base64 32
JITSI_JVB_ADVERTISE_IP=...        # IP pública real del VPS (JVB la anuncia para el tráfico de medios)
```

**Puerto UDP del videobridge — EXCEPCIÓN explícita a "todo detrás de
Caddy en 443"** (mismo criterio ya aceptado para SSH/OpenVPN/correo de
Stalwart): el puerto 10000/UDP (tráfico RTP/SRTP de medios) no es HTTP,
se publica directamente en el host.

**Qué pasa al reservar una cita con Cal.diy**: `citas_crear_reserva`
(MCP) genera automáticamente una sala y añade su URL (`video_url`) al
resultado de la reserva — sin pasos manuales. El asistente de IA también
puede generar una sala nueva en cualquier momento, sin que exista una
cita de por medio (`videollamadas_crear_sala`).

**MCP**: `videollamadas_crear_sala` lleva un primer parámetro `tenant`
(solo para prefijar el nombre de sala, no hay credencial que resolver),
noveno cliente del catálogo con este patrón — y `citas_crear_reserva`
(familia de Cal.diy) queda ampliada para generar la sala automáticamente.

### 8.30 Meilisearch (buscador unificado) — instancia compartida, aislamiento por tenant token

[Meilisearch](https://meilisearch.com) (`getmeili/meilisearch`, MIT,
Community Edition) — buscador unificado sobre notas, tareas con
duración y correo, con typo-tolerancia real (Ctrl/Cmd+K desde cualquier
pantalla de la app).

**Por qué Meilisearch y no Typesense** (ambos resuelven el mismo
problema, tenant tokens con filtro embebido): Meilisearch es MIT,
Typesense es GPL-3.0 — dado que el resto del stack de este proyecto es
mayoritariamente MIT/Apache-2.0 (Documenso, Baserow, Cal.diy, Listmonk,
Jitsi Meet, ntfy...), Meilisearch es la opción más consistente. GPL-3.0
no sería un problema real para uso puramente autoalojado, pero no hay
razón para asumir esa complejidad legal si la alternativa MIT cubre
exactamente lo mismo.

**Por qué `usuario_id` y no `tenant_id`**: el registro de actividad
propio de Guilda Work ya está delimitado por `usuario_id`, no por tenant
— un tenant puede tener varios usuarios, cada uno con su propio registro
privado (`db.py:historial`, siempre filtrado por `usuario_id`). El
buscador respeta ese mismo límite ya existente.

**Aislamiento — verificado en vivo, con un contenedor real y dos
usuarios de prueba**: se indexaron dos documentos, uno por usuario, y se
generó un tenant token real para cada uno (JWT con
`searchRules: {"registro_actividad": {"filter": "usuario_id = <n>"}}`,
firmado con una clave de búsqueda propia, nunca la clave maestra).
Confirmado que:
- El token del usuario A solo devuelve el documento del usuario A,
  incluso buscando por el texto exacto del documento del usuario B (0
  resultados, no un error).
- Intentar mandar un `filter` propio desde el cliente para ver los datos
  del usuario B no funciona — Meilisearch combina el filtro del cliente
  con el del tenant token siempre en **AND**, nunca lo sustituye
  (`(usuario_id = B) AND (usuario_id = A)` → imposible, 0 resultados).
- Sin cabecera `Authorization`, Meilisearch rechaza la petición
  directamente (401), no hay acceso anónimo por defecto.

**Arranque**:

```bash
docker compose up -d meilisearch
```

Añade a `.env`:
```bash
MEILISEARCH_URL=http://127.0.0.1:8029
MEILISEARCH_MASTER_KEY=...   # openssl rand -base64 32
```

**Sin pasos manuales**: la clave de búsqueda usada para firmar los
tenant tokens se crea sola la primera vez que hace falta (con la clave
maestra, ver `app/busqueda.py:_asegurar_clave_busqueda`) — nada que
generar ni pegar a mano en el backoffice.

**Qué se indexa (fase 1, ampliable)**: notas y tareas con duración (en
cada creación/edición/borrado, ver los `_reindexar_nota`/
`_reindexar_tarea`/`_quitar_*_del_indice` de `app/db.py`) y correo (tras
cada sincronización con mensajes nuevos, ver
`app/correo.py:_reindexar_mensajes_recientes`). Documentos de
Paperless-ngx/Outline quedan fuera de esta fase — cada uno ya tiene su
propio buscador razonable, indexarlos aquí sería duplicar sin necesidad
clara.

**Frontend**: el navegador llama a Meilisearch **directamente** con el
tenant token (`app/static/busqueda.js`), sin pasar por Flask para cada
tecla pulsada — solo pide un token nuevo a `/busqueda/token` (cookie de
sesión, no `/api/v1/*`, que es la API por Bearer token de la app móvil)
al abrir el buscador. Patrón estándar de tenant tokens: reduce carga en
el backend, y la clave maestra nunca sale del servidor.

**MCP**: ninguna tool nueva — `listar_notas`/`historial` ya cubren
búsqueda por texto vía SQL `LIKE` para un asistente de IA; Meilisearch
aquí es una mejora de experiencia humana (typo-tolerancia, ranking,
buscar en correo a la vez que en notas en una sola caja), no una
capacidad nueva para la IA.

### 8.31 Umami (analítica web) — instancia compartida, aislamiento por Team

[Umami](https://umami.is) (`docker.umami.is/umami-software/umami`,
MIT) — analítica web sin cookies para la web de cada tenant.

**Por qué Umami y no Plausible**: Plausible Community Edition es
AGPL-3.0; Umami es MIT. Ambos resuelven lo mismo (analítica sin
cookies) — Umami es la opción más consistente con el resto del stack
MIT/Apache-2.0 de este proyecto (mismo razonamiento que Meilisearch
sobre Typesense, ver 8.30).

**Aislamiento — verificado en vivo, con un contenedor real**: Umami
tiene un sistema de **Teams** en su propia edición self-hosted, sin
licencia de pago. Confirmado creando un Team, un sitio y un usuario de
verdad:
- Un sitio se crea ya asociado a un Team concreto (`teamId` en el
  cuerpo de `POST /api/websites`) — no existe un endpoint separado de
  "añadir sitio a un equipo ya creado".
- Un usuario `team-member` de ese Team ve exactamente los sitios de su
  Team (`GET /api/teams/{id}/websites`) y accede a sus estadísticas
  directamente por id.
- Ese mismo usuario, al pedir por id las estadísticas de un sitio de
  OTRO tenant (fuera de su Team), recibe **401** del propio servidor —
  no un filtro de cliente.
- `DELETE /api/teams/{id}` borra en cascada el/los sitio(s) de ese
  Team — un solo borrado basta para desaprovisionar un tenant entero.

**Arranque**:

```bash
docker compose up -d postgres-umami umami
```

Añade a `.env`:
```bash
UMAMI_DB_PASSWORD=...
UMAMI_APP_SECRET=...   # openssl rand -base64 32
UMAMI_ADMIN_PASSWORD=...
```

**Hallazgo real: la contraseña del admin inicial NO se puede fijar por
variable de entorno** (a diferencia de Listmonk/Cal.diy) — Umami crea
siempre `admin`/`umami` de fábrica en su primera migración. Paso de
despliegue único, tras el primer arranque:

```bash
.venv/bin/python -c "from app import umami; umami.bootstrap_admin()"
```

Cambia esa contraseña de fábrica por `UMAMI_ADMIN_PASSWORD` — verificado
en vivo que es idempotente (si ya se ejecutó antes, no hace nada).

**Otro hallazgo real, no obvio en la documentación**: actualizar un
usuario de Umami (incluida su contraseña) es `POST /api/users/{id}`,
NO `PUT` ni `PATCH` — ambos devuelven 405, confirmado en vivo. Mismo
tipo de sorpresa que el `PATCH` vs `PUT` de Meilisearch (ver 8.30).

**Sin pasos manuales de aprovisionamiento**: crear un tenant crea su
Team + sitio automáticamente (`app/umami.py:aprovisionar_tenant`); el
único dato que queda pendiente de ajustar a mano, cuando el tenant lo
sepa, es el dominio real de su web (Umami usa el campo `domain` solo
como etiqueta descriptiva, no restringe desde dónde se puede enviar
tracking — se deja un valor provisional al crear el sitio).

**Sin SSO**: Umami no tiene SSO/OIDC en su edición self-hosted
gratuita — cada usuario de un tenant entra con la cuenta que le crea
`app/umami.py:crear_usuario_tenant()` (contraseña temporal mostrada una
vez en el backoffice, mismo criterio que OpenProject/Chatwoot).

**MCP**: ninguna tool nueva — la analítica web es una métrica de
negocio para que el propio cliente la mire desde su panel, no una
acción que un asistente de IA necesite ejecutar (mismo criterio que
Metabase, ya conectado sin tools de MCP tampoco).

**Visibilidad por tenant**: a diferencia de Restic (infraestructura de
servidor, fuera del catálogo por completo), Umami SÍ respeta el flag de
visibilidad por tenant que el admin puede alternar por tenant desde el
backoffice (`tenants_herramientas_ocultas`, ver `app/db.py` y
`app/rutas_backoffice.py:alternar_herramienta_tenant`) y nace
**visible** por defecto — es una herramienta de negocio del propio
cliente, no de administración del servidor.

### 8.32 Grafana + Loki + Promtail (logs centralizados) — sin aislamiento por tenant

[Grafana](https://grafana.com) + [Loki](https://grafana.com/oss/loki/)
+ [Promtail](https://grafana.com/docs/loki/latest/send-data/promtail/)
— logs de TODOS los contenedores del stack en un único sitio, para no
depurar un fallo mirando `docker logs` uno a uno en ~20 servicios.

**Licencia — AGPL-3.0**: Grafana Labs relicenció Grafana/Loki/Promtail
desde Apache-2.0 en 2021. Esto no es un problema real en este
despliegue: el uso es interno (dashboards de la propia infraestructura
para quien la administra), sin modificar el código ni ofrecerlo como
servicio a terceros — la cláusula de red de la AGPL solo se activa si
se modifica el software Y se deja a OTROS interactuar con esa versión
modificada por red, no por usar la imagen oficial tal cual para mirar
tus propios logs. Mismo criterio de transparencia ya aplicado a
Stalwart (también AGPLv3, ver 8.27).

**SIN aislamiento por tenant, y hay que decirlo claro**: los logs son
de la infraestructura compartida COMPLETA (todos los contenedores de
todos los tenants mezclados) — no existe, ni tiene sentido que exista,
una vista de logs solo de un tenant concreto. Esta herramienta es de
uso exclusivo del administrador de la instancia. Por eso, a diferencia
de TODO el resto del catálogo (que nace visible), la entrada
`"observabilidad"` se oculta explícitamente para cada tenant nuevo
justo al crearlo (`app/rutas_backoffice.py:crear_tenant()` llama a
`db.ocultar_herramienta(tenant_id, "observabilidad")`) — el admin puede
mostrarla a mano desde el backoffice si de verdad quiere que un tenant
en concreto la vea.

**Mecanismo — verificado en vivo con contenedores reales**:
- Promtail descubre los contenedores en marcha vía **Docker Service
  Discovery** (`docker_sd_configs` contra el socket de Docker,
  `deploy/promtail-config.yml`) — NO lee archivos de log por bind
  mount, es Promtail quien pregunta a la API de Docker qué contenedores
  hay y se suscribe a sus logs. Confirmado que etiqueta cada stream con
  el nombre real del contenedor.
- Loki recibe y almacena esos streams — confirmado consultando
  `GET /loki/api/v1/label/container/values` tras arrancar Promtail
  junto a un par de contenedores de prueba: ambos nombres aparecen.
- Grafana provisiona el datasource de Loki **automáticamente** al
  arrancar (`deploy/grafana-datasource-loki.yml`, montado como
  provisioning) — confirmado con `GET /api/datasources` nada más
  arrancar, sin tocar la UI.

**Arranque**:

```bash
docker compose up -d loki promtail grafana
```

Añade a `.env`:
```bash
GRAFANA_ADMIN_PASSWORD=...
```

Entra en `http://<host>:8031` con usuario `admin` y la contraseña de
arriba. El datasource de Loki ya está — solo hace falta ir a
Explore → Loki y filtrar por `{container="guilda-work-..."}` para ver
los logs de un servicio concreto.

**Socket de Docker montado en Promtail (solo lectura)**: necesario para
el Service Discovery — a diferencia del montaje en LECTURA-ESCRITURA
que hace falta para Portainer (ver 8.33), aquí Promtail solo puede
leer, nunca actuar sobre un contenedor.

### 8.33 Portainer — gestión de los ~25 contenedores del stack, oculta por defecto

[Portainer](https://www.portainer.io) CE (zlib) — panel web para
inspeccionar/reiniciar/hacer `exec` en cualquier contenedor de este
`docker-compose.yml`, sin depender de SSH + `docker compose` a mano.

**Licencia — sin OAuth/OIDC/LDAP en Community Edition**: confirmado en
la comparativa oficial de licencias de Portainer que la autenticación
externa (OAuth, LDAP/Active Directory) es exclusiva de Business
Edition — CE entra con cuenta local propia, mismo criterio que
MinIO/Vaultwarden.

**Hallazgo real, verificado en vivo**: Portainer CE se autobloquea si
no se crea una cuenta admin en los primeros minutos tras el primer
arranque (para que nadie deje una instancia recién desplegada sin
proteger). Se evita del todo con `--admin-password-file`, que crea el
admin de forma no interactiva nada más arrancar — confirmado en vivo
que el login por API funciona al instante, sin tocar la UI
(`created admin user with the given password` en el log).

**La contraseña nunca toca un archivo del repo**: en vez de un archivo
de secreto a mano, se usa el mecanismo `secrets: environment:` de
Docker Compose (bloque `secrets:` al final de `docker-compose.yml`,
primer uso en este archivo) — Compose toma el valor de la variable de
entorno `PORTAINER_ADMIN_PASSWORD` y lo materializa como archivo en
`/run/secrets/portainer_admin_password` DENTRO del contenedor.
Confirmado en vivo que este mecanismo funciona de verdad en tiempo de
ejecución, no solo en `docker compose config`.

**`docker.sock` en LECTURA-ESCRITURA — el nivel de exposición más alto
de todo este catálogo**: es inevitable (Portainer necesita poder
actuar sobre contenedores, no solo leer logs como Promtail), y equivale
a control TOTAL sobre el host — puede tocar cualquier contenedor de
cualquier tenant. Por eso `"portainer"` nace **oculta por defecto**
para tenants nuevos (`app/rutas_backoffice.py:crear_tenant()`, mismo
mecanismo que `"observabilidad"`, ver 8.32).

**Arranque**:

```bash
docker compose up -d portainer
```

Añade a `.env`:
```bash
PORTAINER_ADMIN_PASSWORD=...
```

Entra en `http://<host>:8033` (o `portainer.HOSTNAME` detrás de Caddy)
con usuario `admin` y esa contraseña — el entorno Docker local ya
aparece solo (se detecta el propio `docker.sock` montado), sin tener
que darlo de alta a mano.

### 8.34 Collabora Online — edición de documentos dentro de Drive, sin aprovisionamiento por tenant

[Collabora Online](https://www.collaboraonline.com) (CODE, motor
LibreOffice, protocolo WOPI) — edita `.docx`/`.xlsx`/`.odt`... en el
navegador desde dentro de Drive (Nextcloud, ver 8.20), sin descargar el
archivo antes.

**Sin aislamiento ni aprovisionamiento propio — heredado al 100% de
Nextcloud**: Collabora es un motor de render sin estado. Nextcloud le
manda "edita este documento con este token de acceso firmado"
(protocolo WOPI), Collabora edita y llama de vuelta a Nextcloud para
guardar — no guarda nada propio por tenant. Los Group Folders y
permisos de usuario que ya existen en Nextcloud siguen siendo el único
límite de acceso real. Por eso no hay columnas nuevas en `tenants`, ni
entrada nueva en `app/herramientas.py` (solo se amplió la descripción
de `"drive"`), ni ganchos en `crear_tenant()`/`borrar_tenant()`.

**Verificado en vivo, de punta a punta, contra contenedores reales**:
un Nextcloud de prueba con la app `richdocuments` instalada y apuntada
al contenedor de Collabora — `occ richdocuments:activate-config`
confirma `Detected WOPI server: Collabora Online Development Edition`
con capacidades válidas, sin ningún paso manual en la UI.

**Bootstrap — CLI-only, sin equivalente HTTP**: instalar y activar
`richdocuments` solo se puede hacer con el propio `occ` de Nextcloud
(mismo tipo de limitación que `ntfy access`, ver 8.28) — se ejecuta por
`docker exec` contra el contenedor de Nextcloud
(`app/collabora.py:bootstrap_richdocuments()`, mismo patrón que
`app/ntfy.py:_conceder_acceso`). Paso de despliegue, se llama UNA VEZ:

```bash
docker compose up -d nextcloud collabora
.venv/bin/python -c "from app import collabora; collabora.bootstrap_richdocuments()"
```

Añade a `.env`:
```bash
NEXTCLOUD_PUBLIC_ORIGIN=https://drive.tu-dominio.com   # aliasgroup1 de Collabora
COLLABORA_ADMIN_PASSWORD=...   # consola admin propia de Collabora (opcional pero recomendado)
```

**`cap_add: MKNOD`**: requisito oficial documentado para el jail de
`coolwsd` (aislamiento de cada documento abierto) — se mantiene por ser
la recomendación oficial, no una suposición propia.

**El navegador carga el editor DIRECTAMENTE desde Collabora, no a
través de Nextcloud** (confirmado por la propia salida de
`occ richdocuments:activate-config`: "Collabora public URL (used in
the browser to open Collabora)") — de ahí el subdominio propio
`office.HOSTNAME` en el Caddyfile, aparte de `drive.HOSTNAME`.

### 8.35 Búsqueda semántica (RAG) — embeddings locales sobre Meilisearch

Amplía el buscador unificado (8.30) para responder por SIGNIFICADO, no
solo por palabra exacta — un asistente de IA puede preguntar "¿qué dijo
el cliente X sobre el IVA?" y encontrar la nota aunque no use esas
palabras literales.

**Verificado en vivo antes de escribir esto** (Ollama + Meilisearch
reales, no solo documentación): `POST /api/embed` de Ollama con
`nomic-embed-text` devuelve `{"embeddings": [[...]]}` (768
dimensiones); un embedder `{"source": "userProvided", "dimensions": 768}`
en `PATCH /indexes/{idx}/settings/embedders` de Meilisearch funciona
tal cual; y — el punto que de verdad importaba — **el filtro
`usuario_id` del tenant token se sigue aplicando en búsqueda híbrida
exactamente igual que en búsqueda por palabra clave**: probado con una
consulta semánticamente mucho más cercana al documento de OTRO
usuario, que con el tenant token propio sigue devolviendo solo lo del
usuario dueño del token.

**Diseño — vectores "userProvided", no un proveedor de embeddings de
Meilisearch**: `app/embeddings.py` calcula el vector con Ollama
(mismo servicio local ya usado para informes, ver 8.x "IA local") y lo
manda ya hecho en `_vectors.default` al indexar
(`app/busqueda.py:_indexar`) — evita depender de que Meilisearch
self-hosted soporte traer el embedding él mismo desde un proveedor
externo (terreno menos probado), y reutiliza el patrón `urllib` que ya
tiene `app/ai_local.py`.

**Arranque**:

```bash
# Ollama corriendo en el host (o en un contenedor propio, no forma
# parte de docker-compose.yml — mismo criterio que su uso ya existente
# para informes de IA local):
ollama pull nomic-embed-text
```

Sin variables nuevas obligatorias — `OLLAMA_EMBED_URL` (por defecto
`http://localhost:11434/api/embed`) y `OLLAMA_EMBED_MODEL` (por
defecto `nomic-embed-text`) solo hace falta tocarlas si usas otro
modelo o puerto.

**Degradación con gracia**: si Ollama no está disponible o el modelo
no está descargado, `app/embeddings.py:generar_embedding()` devuelve
`None` (nunca lanza) — el documento se indexa igual, solo que sin
vector: sigue siendo buscable por palabra clave exactamente como
antes de esta fase, la búsqueda semántica es una mejora encima, nunca
un requisito.

**Contenido indexado antes de esta fase no tiene vector todavía** —
para añadírselo:

```bash
python scripts/reindexar_embeddings.py
```

Idempotente (mismo `id` de siempre, Meilisearch sobrescribe), seguro
de repetir.

**Búsqueda híbrida — única excepción al patrón "todo directo desde el
navegador" de 8.30**: a diferencia de la búsqueda por palabra clave, el
navegador NO llama a Meilisearch directamente aquí — la pregunta
necesita embeberse con Ollama, solo alcanzable desde el servidor, así
que `GET /busqueda/hibrida?q=...` (cookie de sesión) hace la llamada
completa server-side y devuelve los resultados ya filtrados.

**MCP**: tool `buscar_semantico(texto, limite)` — cierra el círculo de
RAG: un asistente de IA puede recuperar el contexto relevante por
significado antes de responder, en vez de tener que adivinar las
palabras exactas que usó el usuario.

### 8.36 Webhooks salientes — Guilda Work avisa a una URL externa

Cuatro eventos de negocio (no cada escritura, sería ruido en el uso
diario): `tarea.finalizada`, `nota.creada`, `cita.reservada`,
`correo.mensaje_nuevo` — pensados para automatización real (facturación
por horas, disparar un flujo de n8n ya desplegado, avisar a un CRM
externo), ver `app/eventos.py`.

**Alta**: desde el Backoffice (sección "Webhooks") o por MCP
(`webhooks_crear(url, eventos_suscritos, tenant=None)`) — `tenant=None`
es un webhook de ámbito local/sin tenant (modo escritorio). El
`secreto` devuelto solo se enseña esa vez, igual que el resto de
credenciales generadas por este proyecto — apúntalo, hace falta para
verificar la firma de cada entrega.

**Formato del payload**:

```json
{"evento": "tarea.finalizada", "datos": {"tarea_id": 42, "nombre": "Reunión cliente", "duracion_segundos": 2460}}
```

**Verificar la firma — cabecera `X-Guilda-Signature`** (mismo esquema
que GitHub/Stripe, no uno propio): `sha256=<hmac-sha256 del cuerpo
crudo recibido, con el secreto del webhook>`. Ejemplo en Python:

```python
import hashlib
import hmac

def firma_valida(cuerpo_crudo: bytes, cabecera_recibida: str, secreto: str) -> bool:
    esperada = "sha256=" + hmac.new(secreto.encode(), cuerpo_crudo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(cabecera_recibida, esperada)
```

Recalcula siempre sobre el cuerpo crudo tal cual llega, no sobre un
JSON reserializado — un reserializado puede no ser byte a byte idéntico
(orden de claves, espacios) y la firma no coincidiría aunque el
contenido sea "el mismo".

**Reintentos**: 3 intentos con backoff (inmediato, +30s, +5min) antes
de darlo por fallido — cada intento queda registrado (visible desde el
Backoffice, con el código HTTP o el error de cada uno) para depurar un
webhook que no está respondiendo.

**Mecanismo — cola en memoria + un hilo, sin Redis/Celery**: no hace
falta a esta escala (mismo patrón que la sincronización periódica de
correo ya existente). Limitación conocida: al ser un único hilo, un
webhook lento con reintentos retrasa la entrega de los siguientes en la
cola — aceptable para el volumen de eventos de negocio de este
proyecto, no un sistema de mensajería de alto tráfico.

### 8.37 Explorador de API interactivo — `/docs/explorador-api`

Sin servicio nuevo, sin variable de entorno, sin paso de despliegue
propio — es una página más de la Guía para desarrolladores (`/docs`,
pública, sin login) servida por el propio `serve.py`. Genera su
contenido **en el navegador**, en cada carga, a partir de
`GET /api/v1/openapi.json` (el documento OpenAPI 3.0 real, generado por
introspección del código en cada petición — nunca un archivo aparte
que se pueda desincronizar, ver `app/openapi.py`), en vez de vendorizar
Redoc/Scalar/Swagger UI: lista de endpoints filtrable agrupada por
recurso, con parámetros, cuerpo esperado y un `curl` de ejemplo ya
generado (`app/static/api_explorer.js`).

Como `/api/v1/openapi.json` no requiere token, esta página funciona
igual detrás de Caddy que en local — no hace falta abrir ningún puerto
ni tocar el `Caddyfile` para que quede accesible junto al resto de
`/docs`.

## 9. Backups (recomendado)

Hay **tres mecanismos de backup distintos en este proyecto, cada uno con
un alcance diferente** — no son redundantes entre sí, cada uno cubre
algo que los otros dos no:

| Mecanismo | Qué cubre | Frecuencia | Destino |
|---|---|---|---|
| `db.hacer_backup_si_hace_falta()` | Solo `data/registro.db` | Diaria (cron), **una única copia** | Segundo disco del VPS (`GUILDA_BACKUPS_DIR`) |
| Litestream (`deploy/litestream.yml`) | Solo `data/registro.db` | Continua (streaming) | S3-compatible externo |
| **Restic (`scripts/backup_restic.sh`)** | **Todo lo demás**: los ~15 volúmenes Docker de las herramientas conectadas (Postgres de EspoCRM/Nextcloud/Documenso/Paperless-ngx/Baserow/Chatwoot/OpenProject/FacturaScripts/Listmonk/Cal.diy/Umami, más los archivos de Nextcloud/Paperless-ngx/Baserow/Stalwart/Listmonk) | Diaria (systemd timer) | S3-compatible externo |

`registro.db` ya está doblemente cubierto (copia local + réplica
continua). **Todo el resto del stack — facturas, contratos firmados,
CRM, correo real de los clientes — no tenía backup de ningún tipo hasta
Restic.** Si se pierde uno de esos volúmenes sin Restic, se pierde el
dato sin vuelta atrás.

### 9.1 Backup local simple de `registro.db`

Se conserva **una sola copia**: la última verificada. Cada ejecución crea
la copia en un `.tmp`, comprueba `PRAGMA integrity_check`, la sustituye de
forma atómica y solo entonces borra las demás; si algo falla, la copia
anterior queda intacta, el comando sale con código ≠ 0 y se envía un correo
de alerta (`ALERTAS_ADMIN_EMAIL`).

```bash
# crontab -e (usuario guilda)
0 4 * * * cd /home/guilda/guilda-work && GUILDA_BACKUPS_DIR=/mnt/HC_Volume_106540289/guilda-backups .venv/bin/python cli.py backup >> /var/log/guilda-work/backup.log 2>&1
```

**Importante**: el `cd` es imprescindible. Sin él Python no encuentra el
paquete `app` (`ModuleNotFoundError`) y el cron falla cada noche sin que
nadie lo vea (así se perdieron ~6 semanas de copias en 2026). Si el
destino está bajo `/mnt/` y el disco no está montado, `cli.py backup`
se niega a escribir en el disco raíz y avisa. El botón "Hacer copia ahora"
del backoffice (`/backoffice/backups`) refresca la copia única.

### 9.2 Backups completos del stack con Restic (MIT)

`scripts/backup_restic.sh` respalda con [Restic](https://restic.net/)
cada volumen Docker de la lista de arriba, uno a uno, vía
`docker run --rm -v <volumen>:/data:ro ... restic/restic backup /data`
(mismo patrón de contenedor de un solo uso que ya usa
`app/facturascripts.py:_ejecutar_psql`) — no es un servicio más de
`docker-compose.yml`, es un script de administración del servidor.

**El destino tiene que ser un backend S3-compatible EXTERNO de
verdad** (ej. Backblaze B2, o cualquier otro proveedor S3-compatible) —
**nunca el propio MinIO de este mismo VPS**. Si el VPS entero se pierde
(disco dañado, proveedor con un incidente, etc.), un backup guardado en
el mismo VPS no sirve de nada; el sentido de un backup es sobrevivir a
la pérdida de la máquina que respalda.

**Variables de entorno** (en `/etc/restic.env`, con permisos `600`,
nunca dentro del propio script ni del repo):

```bash
RESTIC_REPOSITORY=s3:https://s3.eu-central-003.backblazeb2.com/mi-bucket-backups
RESTIC_PASSWORD=una-contraseña-larga-y-aleatoria-solo-para-restic
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

La primera vez, inicializa el repositorio (una sola vez, antes del
primer backup):

```bash
docker run --rm --env-file /etc/restic.env restic/restic init
```

**Programación** — timer systemd diario con margen aleatorio, para no
golpear el backend siempre a la misma hora exacta si comparte proveedor
con otros clientes (`deploy/restic-backup.service` +
`deploy/restic-backup.timer`, mismo estilo que
`deploy/guilda-work-mcp.service`):

```bash
sudo cp deploy/restic-backup.service deploy/restic-backup.timer /etc/systemd/system/
sudo nano /etc/systemd/system/restic-backup.service   # ajustar USUARIO y rutas
sudo systemctl daemon-reload
sudo systemctl enable --now restic-backup.timer
```

### 9.3 Recurrencia automática del calendario fiscal

`scripts/generar_vencimientos_fiscales.py` genera solo los vencimientos
de los clientes fiscales que tengan la casilla "Generación automática"
activada en su ficha (`clientes_fiscales.generacion_automatica`, apagada
por defecto — opt-in por cliente, editable en `/fiscal/clientes/<id>/editar`)
y sanea el estado `fuera_plazo` de lo pendiente ya vencido
(`db.generar_vencimientos_automaticos()` /
`db.sanear_vencimientos_fuera_plazo()`). Es un timer systemd de verdad,
no un hilo más dentro de `serve.py` — mismo criterio que Restic (9.2):
esto es una tarea de administración periódica, no algo que dependa de
que el proceso web esté vivo.

**Idempotente** — se puede ejecutar cualquier número de veces sin
duplicar nada: por cada cliente en generación automática, calcula las
propuestas del año en curso y del anterior con la misma función pura
que usa "Generar vencimientos" a mano
(`vencimientos_fiscales.generar_vencimientos_propuestos()`) y solo
inserta lo que no exista ya para ese cliente+modelo+periodo. No hace
falta que sepa qué trimestre exacto toca hoy.

**No necesita variables nuevas** — reutiliza `/etc/guilda-work.env`, el
mismo fichero que ya usa `guilda-work.service` (a diferencia de Restic,
esta tarea no habla con ninguna API externa, solo con `data/registro.db`).

**Programación** — timer diario a las 04:00 (una hora después de
Restic, para no competir por CPU/IO), mismo patrón que 9.2:

```bash
sudo cp deploy/vencimientos-fiscales.service deploy/vencimientos-fiscales.timer /etc/systemd/system/
sudo nano /etc/systemd/system/vencimientos-fiscales.service   # ajustar USUARIO y rutas
sudo systemctl daemon-reload
sudo systemctl enable --now vencimientos-fiscales.timer
```

**Verificar que corrió**:

```bash
systemctl list-timers vencimientos-fiscales.timer
journalctl -u vencimientos-fiscales.service -n 20
```

**Retención**: el script termina con
`restic forget --prune --group-by host,tags --keep-last 1` — una única
copia por volumen. El `--group-by host,tags` es obligatorio: todos los
volúmenes se respaldan como `/data` en el mismo host, y con el agrupado
por defecto (`host,paths`) restic los fusionaría en un solo grupo y
borraría los snapshots de los demás volúmenes.

**Destino local**: `RESTIC_REPOSITORY` puede ser una ruta absoluta (p. ej.
`/mnt/HC_Volume_106540289/restic`, el segundo disco), sin cuenta S3. Protege
frente a un fallo del disco principal, no frente a perder el servidor entero;
un S3 externo sigue siendo lo único que cubre eso.

**Prefijo de los volúmenes**: el script asume que Docker Compose nombra
los volúmenes como `guilda-work_<nombre>` (el prefijo se deriva del
nombre de la carpeta del proyecto — `cd guilda-work` en el paso 2 de
esta misma guía). Si tu carpeta se llama distinto, ajusta
`DOCKER_COMPOSE_PROJECT_PREFIX` en `/etc/restic.env`. Si una herramienta
concreta no está desplegada en tu instancia, el script avisa y salta
ese volumen sin fallar — no hace falta editar la lista para
despliegues parciales.

**Un backup nunca restaurado no es un backup — prueba de
restauración real, obligatoria al menos una vez**:

```bash
# Listar snapshots disponibles
docker run --rm --env-file /etc/restic.env -v restic-cache:/cache \
  restic/restic snapshots

# Restaurar el último snapshot de un volumen concreto a un directorio limpio
docker run --rm --env-file /etc/restic.env -v restic-cache:/cache \
  -v /tmp/restore-test:/restore \
  restic/restic restore latest --target /restore --tag postgres-espocrm-data
```

**Ojo con la ruta de destino**: Restic reconstruye la ruta absoluta
ORIGINAL de backup bajo el `--target` indicado, no la aplana. Como el
script respalda cada volumen montado en `/data` dentro del contenedor
efímero, `restic restore ... --target /algo` recrea el contenido en
`/algo/data/...` (anidado), NO directamente en `/algo/...` — verificado
en vivo reproduciendo primero el error y confirmando después la ruta
correcta. Para una restauración real a un volumen Docker (no a un
directorio de prueba), monta el volumen destino en la raíz del
contenedor de restore y usa `--target /`:

```bash
docker run --rm --env-file /etc/restic.env -v restic-cache:/cache \
  -v guilda-work_postgres-espocrm-data:/data \
  restic/restic restore latest --target / --tag postgres-espocrm-data
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


## Backoffice independiente (backoffice.guildawork.com)

El backoffice es una aplicación aparte (`backoffice/`, proceso `serve_backoffice.py`
en `127.0.0.1:8001`, unidad `deploy/guilda-backoffice.service`): **no usa Kratos ni la
sesión de `app.guildawork.com`**. Tiene sus propios administradores
(`data/backoffice.db`, contraseñas con scrypt), sesión propia (cookie `bo_session`,
caduca a la hora de inactividad y a las 12 h), protección CSRF, bloqueo tras 5 intentos
fallidos en 15 minutos y registro de actividad. Comparte únicamente la base de datos de
la plataforma (`registro.db`) para administrar tenants y usuarios.

- Crear o cambiar un administrador (la contraseña generada se muestra una sola vez):
  `.venv/bin/python scripts/crear_admin_backoffice.py USUARIO [--nombre "Nombre"] [--cambiar]`
- Variables opcionales: `BACKOFFICE_PORT` (8001), `BACKOFFICE_DB`, `BACKOFFICE_SECRET_KEY`
  (si no, se genera `data/backoffice_secret.key`, permisos 0600).
- Caddy: bloque de `deploy/Caddyfile.backoffice`.
- Las rutas antiguas `/backoffice/...` de `app.guildawork.com` ya no existen como panel:
  redirigen (solo GET) a las pantallas equivalentes de este backoffice.
- Tareas periódicas del propio backoffice (hilo en `serve_backoffice.py`, cada 10 min, latido
  `backoffice_tareas` en Salud): foto diaria de la cartera (histórico de MRR, altas, bajas y
  cambios de plan en Ingresos), revisión de los cobros puntuales pendientes en Stripe y resumen
  semanal por correo (lunes 8:00, a `ALERTAS_ADMIN_EMAIL`, una vez por semana; también se puede
  enviar a mano desde Alertas). Salud de cada tenant: 0-100 según actividad, usuarios que
  entran, funciones en uso y estado del pago (≥70 sano, 40-69 atención, <40 en riesgo).
- **Correo IMAP en ambos sentidos**: leer, destacar y borrar aquí se refleja en el servidor (un borrado va a
  la papelera de la cuenta; sin papelera, se borra), y lo hecho desde el móvil u otro cliente se refleja aquí
  (estado de los 500 mensajes más recientes en cada pasada y de toda la carpeta cada hora, y los borrados en el
  servidor). Los cambios se encolan en `correo_operaciones` y se reintentan hasta 5 veces; si el servidor los
  rechaza se avisa en la barra superior. Descargar correo ya no lo marca como leído en el servidor (BODY.PEEK) y
  un buzón grande se baja por tandas (lo más reciente primero, máx. 60 s o 2.000 mensajes por carpeta y pasada).
  Cuentas POP3: sin cambios. La búsqueda usa un índice de texto completo (FTS5) que se crea y rellena solo al
  migrar; `db.reconstruir_indice_correo()` lo regenera si hiciera falta.
- **Proyectos compartidos** (`/proyecto/<id>`): un proyecto (categoría) puede compartirse con compañeros del MISMO despacho
  como «colabora» o «solo lectura»; el dueño ve y trabaja las tareas de los miembros y viceversa (vista
  `tareas_participantes_todos`, solo para permisos: las listas generales y «Mi día» no se llenan con lo del equipo). Quien
  sale del despacho pierde el acceso al instante; los supervisores ven (solo lectura) los proyectos compartidos del despacho.
  Los proyectos de siempre siguen privados hasta que su dueño los comparte. Columnas nuevas con prefijo `proy_` en
  `categorias`; tablas `proyecto_miembros` y `proyecto_secciones`. `/menu/<id>` redirige a la página nueva; el registro
  cronológico de notas y eventos sigue en `/menu/<id>?registro=1` (pestaña «Registro»).
- **Seguridad del acceso** (página «Mi cuenta»): verificación en dos pasos con app de autenticación
  (TOTP, 6 dígitos; el secreto se guarda cifrado y se dan 8 códigos de recuperación de un solo uso)
  y caducidad de contraseña (`BACKOFFICE_CADUCIDAD_DIAS`, 180 por defecto, 0 = nunca). Con
  `BACKOFFICE_2FA_OBLIGATORIO=1` nadie navega sin tenerlo activado. Si un administrador pierde el móvil
  y los códigos: `.venv/bin/python scripts/crear_admin_backoffice.py USUARIO --quitar-2fa`.
- **Vigilancia desde fuera**: el backoffice repasa los latidos de la app (aviso por correo, una vez al día
  por motivo) y comprueba que responde en `GUILDA_PORT`; tras 2 sondas seguidas fallidas (~20 min) avisa.
- **Auditoría de dependencias** (semanal; página Dependencias): envía a osv.dev SOLO nombre y versión de
  cada paquete de Python; desactivable con `BACKOFFICE_AUDITORIA_DEPENDENCIAS=0`. Avisa además de las
  imágenes de Docker sin versión fijada (`:latest`).
- **Pruebas y despliegue**: `scripts/probar.sh` ejecuta la suite en una copia aislada que borra al terminar
  (`--rapida`: sin Kratos ni Docker, ~1 min; completa ~5 min). `scripts/comprobar_migraciones.py` aplica las
  migraciones del código nuevo a una copia de la base real; `scripts/desplegar.sh` lo ejecuta ANTES de
  hacer `git pull` y cancela el despliegue si algo falla.
- Borrar un tenant elimina también sus clientes fiscales, vencimientos, documentos, webhooks y
  extras. Si tiene fichajes se rechaza (hay que conservarlos 4 años) salvo que se marque la
  casilla expresa; la comprobación se hace antes de retirar nada de las herramientas conectadas.
- El último acceso de cada usuario (`usuarios.ultimo_acceso`) lo anota la app como mucho
  una vez cada 10 minutos; el backoffice lo muestra si la columna ya existe.

## Comunicados y buscador del backoffice

- **Comunicados** (`/comunicados` en el backoffice): avisos que la app muestra como banner (informativo, aviso o crítico; para todos los despachos o uno; con fechas de inicio/fin). Los críticos no se pueden cerrar. Tablas `comunicados` y `comunicados_cerrados` en `registro.db` (se crean solas). La app y el backoffice son procesos distintos: un comunicado nuevo tarda hasta ~20 s en aparecer (caché de existencia en `app/comunicados.py`).
- **Buscador global**: `Ctrl+K` (o `/`) en el backoffice abre una paleta con páginas, tenants y usuarios (`/buscar?q=`).
- Para que se vea en producción hay que reiniciar guilda-work (banner, rutas) y el backoffice.

## Modo mantenimiento y «ver como»

- **Mantenimiento** (`/mantenimiento` en el backoffice): cierra toda la plataforma o un despacho con un mensaje y fecha de fin opcional. Los usuarios ven una página 503 y la API responde 503 JSON con `Retry-After`. Pasan los administradores globales, el login, el proxy de Kratos (`/.ory/`), los webhooks entrantes (`/webhooks/`) y las sesiones de «ver como». Tabla `mantenimiento`; la app lo consulta con caché de 10 s.
- **Ver como** (ficha de usuario del backoffice): pide un motivo (obligatorio, queda auditado), emite un enlace de un solo uso (2 min, solo se guarda su hash en `ver_como_tokens`) y abre la app como ese usuario en **solo lectura** durante 30 min (toda petición que no sea GET devuelve 403). Nunca se puede suplantar a un administrador. Inicio y fin quedan en `auditoria_backoffice` (app) y la emisión en la Actividad del backoffice.
- Variables: `GUILDA_APP_URL` (backoffice; por defecto https://app.guildawork.com) y `GUILDA_BACKOFFICE_URL` (app; adónde vuelve «Salir»; por defecto https://backoffice.guildawork.com). La sesión de la app necesita `GUILDA_SECRET_KEY` fija para sobrevivir a reinicios.
- Limitación: algunas pantallas marcan cosas como leídas al abrirlas (GET); «ver como» no lo evita del todo.

## Puesta en marcha guiada del despacho

- `app/onboarding_despacho.py`: 6 pasos que se calculan en caliente de los datos (primer cliente fiscal, vencimientos generados, correo conectado, recordatorios revisados, acceso al portal dado a un cliente, primer vencimiento presentado). No hay tabla de seguimiento: no puede desincronizarse.
- En la app: tarjeta «Primeros pasos» del inicio (con barra de progreso y enlace a cada pantalla) mientras el usuario no la oculte.
- En el backoffice: bloque «Puesta en marcha» en el resumen de cada tenant, columna en Customer Journey y botón «Avisar al despacho de lo que le falta», que publica un comunicado (banner) solo para ese despacho. No duplica avisos activos.

## Tope de consumo de IA por despacho

- Cada consulta al modelo (turno del chat o acción de IA del correo) cuenta 1 en `ia_consumo` (despacho y mes). El tope está en `tenants.ia_limite_mensual`: vacío = **ilimitado** (por defecto, nada cambia para los despachos existentes), 0 = IA desactivada, N = tope mensual. Se renueva el día 1.
- Al agotarlo, el chat y las acciones del correo devuelven un aviso claro y no llaman al modelo. Las confirmaciones de acciones ya iniciadas no cuentan. Usuarios sin despacho: sin tope.
- Backoffice: bloque «Consumo de IA» en el resumen del tenant (límite, ilimitado, histórico) y página `/consumo-ia` con el gasto de todos. En la app, Ajustes del Asistente IA muestra el uso y avisa al llegar al 80 %.
- El consumo es de **consultas**, no de coste: cada usuario usa su propia clave de OpenRouter.

## API ampliada y herramientas de IA/MCP por grupos

- **API** (`app/rutas_api_ampliada.py`, mismo blueprint `/api/v1`): listados `GET /notas` y `GET /tareas`; proyectos; detalle de tarea con checklist; asignación y compañeros; `/mi-dia`; conversaciones de correo y paso de correo a tarea/nota; envíos programados, seguimientos y plantillas; notificaciones; `/buscar`; `/ia/consumo`; `/comunicados`. Todo aditivo (la app móvil actual no cambia), con OpenAPI y docs de desarrolladores al día.
- **Chat de IA**: ya no manda las 95 herramientas en cada turno (~40 KB). Manda el núcleo (13, ~6 KB) y añade grupos (correo, fiscal, fichaje, tiquets, facturación, CRM, archivos, firmas, tareas_avanzadas) según las palabras del usuario, lo ya usado en la conversación o lo que el modelo pida con `activar_herramientas`. Ahorro típico: 60-85 % de fichas de herramientas por turno. Definido en `app/herramientas_grupos.py`.
- **MCP externo**: por defecto expone todo, como siempre. Perfiles opcionales por entorno: `GUILDA_MCP_GRUPOS=fiscal,correo` (el núcleo siempre entra) y `GUILDA_MCP_SOLO_LECTURA=1`. Se aplican en `mcp_tools.registrar_tools`.
- Herramientas nuevas: `resumen_del_dia`, `detalle_tarea`, `completar_tareas` (lote), `listar_notificaciones`.
- **MCP más útil** (`app/mcp_utilidad.py`): las respuestas se recortan con aviso (`GUILDA_MCP_MAX_TEXTO`, 12000 caracteres por texto; `GUILDA_MCP_MAX_CHARS`, 60000 por listado, que se corta con un marcador `_truncado`); `leer_correo` no repite el HTML salvo `incluir_html=true`; `tenant` es opcional (por defecto, tu propio despacho); 5 prompts (`resumen_del_dia_prompt`, `ficha_cliente`, `preparar_vencimiento`, `revisar_correo`, `cierre_de_trimestre`) y 5 recursos `guilda://…` que pasan por el mismo guardián (áreas, límites, auditoría). Herramientas nuevas: `consumo_ia`, `listar_comunicados`, `webhooks_entregas`. Requiere reiniciar `guilda-work-mcp`.

## API robusta para uso externo, sincronización y webhooks persistentes

- **Contrato** (compatible hacia atrás): errores `{"ok": false, "error", "codigo", ["campo"]}` (también 404/405 de enrutado y 500, siempre JSON); cabecera `X-API-Version` (1.3); `ETag`/`If-None-Match` → 304 en lecturas; `?campos=`; paginación de `/notas` hecha en SQL.
- **Límite por usuario**: `GUILDA_API_LIMITE_POR_MINUTO` (600 por defecto), ventana de 60 s en memoria del proceso, con `X-RateLimit-*` y `429 + Retry-After`.
- **Idempotencia**: `Idempotency-Key` en POST, 24 h (tabla `api_idempotencia`); los 5xx no se guardan.
- **Sincronización incremental** `GET /api/v1/sync`: triggers de SQLite (`trg_cambios_*`) llenan `api_cambios` en cualquier alta/edición/papelera/borrado de notas, tareas, tareas de lista y proyectos, venga de donde venga. Retención 30 días (`api_cambios_purgado` marca hasta dónde se purgó → `reiniciar: true`). Las migraciones son idempotentes y se ensayaron sobre una copia de `registro.db`.
- **Webhooks**: cola persistente `webhooks_cola` (sobrevive a reinicios), 4 hilos de entrega, 6 intentos (0 s, 30 s, 5 min, 30 min, 2 h, 12 h), entregas atascadas se recuperan a los 5 min, `X-Guilda-Delivery` para deduplicar, cuerpo con `id` y `fecha`. Eventos nuevos: `cliente.creado`, `correo.sin_respuesta`. Backoffice: «Enviar prueba» (ping) y «Reintentar» envíos fallidos. El hilo arranca en `serve.py` (y al emitir el primer evento en otros procesos); con varios procesos no hay duplicados (reclamo atómico por fila).
- Cambio de comportamiento: antes un 500 en la API devolvía HTTP 200 con un JSON de error; ahora devuelve 500.

## Tokens de API: áreas, caducidad y registro de uso

- `tokens_api` gana `areas` (JSON; vacío = todas), `caduca_en` y `ultima_ip`; tabla `tokens_api_uso` (llamadas y errores por token y día). Clasificación de rutas en `app/api_areas.py`: un token con áreas no usa las rutas transversales (`historial`, `dashboard`, `export`, `papelera`, `buscar`, `sync`) ni `/tokens`, de modo que no puede crear otro más amplio. Ruta nueva sin clasificar = transversal (cerrado por defecto).
- Errores nuevos: `token_caducado` (401), `token_area_no_permitida` (403, con `areas`). Los tokens existentes no cambian (sin áreas ni caducidad).
- La web (Mis dispositivos) crea tokens con permisos, áreas y caducidad, y muestra último uso y llamadas de 30 días. Backoffice: `/tokens-api` lista todos los tokens (alcance, uso, errores, IP) y permite revocar cualquiera.
- `GET /tareas-outlook` admite `desde`/`hasta`.

## Fase 0 de OAuth2 y primer paquete de mejoras de API/MCP

- **Consentimiento OAuth**: los clientes con `skip_consent` (propios) siguen sin pantalla; cualquier otro (p. ej. los del Registro Dinámico, como ChatGPT) muestra «Permitir/Denegar» en `/hydra/consent`, con auditoría (`oauth.consentimiento`). El challenge solo lo puede resolver la persona a la que pertenece.
- **MCP remoto**: ya no acepta cualquier token de Hydra. Valen los clientes que pasaron por consentimiento, los marcados `metadata.mcp = true` y los de `MCP_REMOTO_CLIENTES` (por defecto `claude-desktop`); un token de Outline/Element/Drive/MAS/Documentos se rechaza. También acepta **tokens personales de API** con sus áreas y su solo lectura (`app/mcp_acceso.py`). Cada herramienta lleva anotaciones MCP (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`).
- **Aislamiento de despachos en el MCP**: las herramientas con parámetro `tenant` (facturas, documentos, hojas, firmas, citas, newsletter, correo_stalwart, ntfy, webhooks...) solo operan sobre tu propio despacho (admins y usuario local, sobre cualquiera). Antes bastaba con escribir el nombre de otra gestoría. Los webhooks por MCP exigen supervisor del despacho y URL pública.
- **Hydra**: sigue arrancando con `--dev` y con el Registro Dinámico activo (`deploy/hydra/hydra.yml`); es decisión de operación, ver `scripts/auditar_hydra.py` (solo lectura) para revisar los clientes.
- **Webhooks**: firma con marca de tiempo `X-Guilda-Signature-V2` (`t=...,v1=...`) además de la antigua; webhooks creados por API/MCP: solo https hacia direcciones públicas, comprobado también en cada entrega, sin seguir redirecciones (columna `webhooks.origen`). API `/webhooks` para supervisores.
- **`X-Request-Id`** en toda respuesta (y `request_id` en errores de la API); se acepta el del cliente si es sano. Va a Sentry como etiqueta y a los registros de errores.
- **`referencia_externa`** (notas, tareas de lista, clientes fiscales) con índices únicos por dueño y upsert `.../por-referencia/{ref}`.
- Un valor que la base rechaza (estado inexistente...) ahora responde 400 `valor_invalido` en la API (antes 500).

## API de tareas completa

- `app/rutas_api_tareas.py`: estado (con dependencias), cronómetro, comentarios con menciones, dependencias, recordatorios, compartir, lote (máx. 200), tablero, plan de carga y mover, vistas guardadas, plantillas, recurrentes y reglas por vencimiento, papelera. Usa las mismas funciones de `db.py` y las mismas notificaciones que la web (`rutas_tareas._notificar_*`), así que API, web y MCP no pueden divergir.
- Correcciones de paridad: `POST /tareas-outlook/{id}/completar` ahora respeta las dependencias (409 `tarea_bloqueada`) y avisa a quien queda desbloqueado; asignar por API (y en lote) notifica al compañero.
- MCP/chat: `cambiar_estado_tarea`, `listar_comentarios_tarea`, `comentar_tarea`, `iniciar_cronometro_tarea` (área `tareas`, grupo `tareas_avanzadas`).

## API fiscal completa

- `app/rutas_api_fiscal.py`: expediente del cliente (documentos), alta/detalle/propuestas/generación masiva de vencimientos, documentos y mensajes por vencimiento, constancia y justificante, recordatorios del portal, accesos (RGPD), resumen y papelera.
- **Paridad con la web** (antes la API se saltaba cosas): `presentado` ahora genera la constancia, acepta el justificante y emite `vencimiento.presentado` (antes no emitía el evento, así que los webhooks nunca se enteraban); generar vencimientos usa el país del cliente y ya no duplica; pedir un documento avisa al cliente por correo; leer, editar o borrar un cliente por API queda en el registro de accesos («vía API»); el cliente admite `email`, `pais`, `idioma` y `recordatorios_portal` (sin `email` el portal y los recordatorios no funcionaban para clientes creados por API).
- Los listados de vencimientos paginan en SQL (`X-Total-Count`) y admiten `desde`, `hasta` y `pais`.
- Deliberadamente fuera: enviar a firma (Documenso) y cobrar (Stripe).

## API: adjuntos de notas, envío de correo, plantillas y administración del fichaje

- `app/rutas_api_extras.py`: adjuntos de notas (mismos límites que la web: 5 MB, 5 por nota, tipos permitidos), estado y cancelación de envíos, plantillas de correo (CRUD + render) y administración del fichaje (resumen, detalle, corrección auditable, exportaciones CSV/PDF/JSON y verificación de integridad). Permisos del fichaje idénticos a la web: gestor de fichajes (su despacho) o administrador global (con `tenant_id`); un trabajador de otro despacho se responde 404.
- `POST /correo/enviar`: acepta multipart, `programar_para` (202 + `envio_id`) y `seguimiento_dias`; base64 inválido da 400 (antes 500). **El tope de 25 MB de adjuntos ahora vale también para el envío directo** (`construir_y_enviar`); antes solo se comprobaba al encolar.
- `DELETE /correo/programados/{id}` ahora también borra los adjuntos retenidos en la cola.

## Hydra sin `--dev` (2026-10-10)

- `docker-compose.yml`: Hydra arranca con `serve ... all --sqa-opt-out` (antes `--dev`, que «desactiva comprobaciones críticas de seguridad»). `--sqa-opt-out` evita la telemetría anónima a Ory, que sin `--dev` estaría activa.
- **Ensayado antes** en un Hydra desechable (`DSN=memory`, puertos 14444/14445) con el flujo completo —login, consentimiento, PKCE S256, intercambio de código, `id_token`, refresh, `userinfo` e introspección— y repetido contra producción con un cliente temporal (borrado al terminar). Detrás de Caddy en HTTP plano funciona igual; Hydra solo avisa «HTTPS is disabled». Las cookies siguen saliendo `Secure; SameSite=None` por `SERVE_COOKIES_SECURE`.
- **Cómo recrear Hydra sin accidentes**: `docker compose` debe leer el `.env` DEL PROYECTO (`/home/guilda/guilda-work/.env`), que es donde están `HYDRA_SYSTEM_SECRET` y `HYDRA_DB_PASSWORD`. Con `--env-file /etc/guilda-work.env` el compose renderiza los valores de ejemplo y cambiaría el secreto del sistema (invalidaría tokens y datos cifrados). Antes de recrear, compara el entorno renderizado con el del contenedor (`docker inspect`) y usa `up -d --no-deps hydra`.
- **`prueba-dcr` NO es una prueba**: es el conector de Claude.ai (`redirect_uri` `https://claude.ai/api/mcp/auth_callback`), registrado solo por Registro Dinámico el 2026-08-06. No borrar. Claude.ai y ChatGPT dependen del Registro Dinámico, así que sigue activo (`oidc.dynamic_client_registration.enabled`).
- Riesgo conocido y aceptado: el Registro Dinámico de Hydra acepta cualquier `redirect_uri` (incluso `http://` no local) sin autenticación. Lo que protege es la pantalla de consentimiento de Guilda (`/hydra/consent`, que muestra a dónde vuelve la aplicación) y que el MCP solo acepta clientes que han pasado por ella. `scripts/auditar_hydra.py` lista los clientes para revisarlos.
- Copia de los clientes previos al cambio: `/root/hydra-clientes-antes-2026-10-10.json`. Reversión: restaurar `--dev` en el `command` y `up -d --no-deps hydra` (la base de datos no se toca).

## MCP: medido, limitado y auditado

- Cada herramienta pasa por `mcp_tools._con_guardian`: aplica el alcance del token personal, el **límite por persona** de las conexiones remotas (120 llamadas/min y 40 escrituras/min; `GUILDA_MCP_LIMITE_POR_MINUTO` y `GUILDA_MCP_LIMITE_ESCRITURAS_POR_MINUTO`; la llamada rechazada no gasta cupo) y **anota** la llamada. El stdio local (tu propia máquina) no se limita pero sí se anota.
- Tablas `mcp_auditoria` (90 días: persona, despacho, cliente, token, herramienta, lectura/escritura, resultado, duración y la FORMA de los argumentos) y `mcp_uso` (contador diario por persona y herramienta). **Privacidad**: de un texto solo se guarda su longitud; nunca contenidos de correos, notas ni documentos.
- Las llamadas por token personal suman a `tokens_api_uso` (se ven en `/tokens-api`). El `AccessToken` lleva `token:<id>` en sus scopes.
- Backoffice: **Actividad MCP** (`/actividad-mcp`): totales, errores, uso por herramienta y por persona, y el registro filtrable por despacho, persona, herramienta, resultado y «solo escrituras».
- No cubre las herramientas que el chat de IA integrado ejecuta directamente (esas ya quedan en el historial de la conversación).

## OpenAPI completo y contrato de la API

- `app/openapi.py` genera el documento **del código**: `openapi_analisis.py` lee cada vista con `ast` (campos del cuerpo JSON o multipart, parámetros de consulta, códigos de respuesta, ayudantes que añaden campos) y `openapi_catalogo.py` aporta lo que solo sabe una persona (tipos y descripciones de campos, qué entidad devuelve cada ruta, esquemas a medida, ejemplos). Los esquemas de las entidades salen de las columnas reales de las tablas: una columna nueva aparece sola. El análisis se hace una vez por ruta y proceso (el endpoint es público).
- Pasó de 9 a **81 operaciones con cuerpo documentado** (el resto no lleva cuerpo), 0 respuestas sin esquema, 236 operaciones con códigos de error, cabeceras (`X-Request-Id`, `X-RateLimit-Remaining`, `ETag`, `X-Total-Count`, `Idempotency-Key`), área de token (`x-area`) y ejemplos de las operaciones principales. El documento anterior tenía campos inventados (p. ej. `para` en vez de `destinatarios` en `/correo/enviar`).
- **`tests/test_openapi_contrato.py`**: válido (openapi-spec-validator), completo (todo campo que lee una vista está documentado; ninguna respuesta sin esquema), ejemplos que cumplen su esquema, **respuestas reales que cumplen el esquema** (~50 operaciones ejecutadas de verdad) y **compatibilidad**: `tests/openapi_baseline.json` guarda la huella publicada; falla si desaparece una ruta, un campo o un parámetro, si deja de responder un código de éxito o si un campo opcional pasa a obligatorio. Para aceptar un cambio incompatible a propósito (subiendo la versión mayor): `GUILDA_ACTUALIZAR_BASELINE_OPENAPI=1 GUILDA_BASELINE_OPENAPI_DESTINO=$PWD/tests/openapi_baseline.json scripts/probar.sh tests/test_openapi_contrato.py -k referencia`.
- Al construirlo, el propio test de respuestas reales destapó tres desajustes entre lo que se suponía y lo que devuelve la API (corregidos en la documentación, no en el comportamiento, para no romper a la app móvil): `modelos_fiscales` de un cliente es texto JSON salvo en `GET /fiscal/clientes/{id}`; `POST .../checklist` devuelve `{id, checklist}` y no la lista; y `generar-vencimientos` no exigía `modelos` (usa los del cliente).

## SDK de Python y TypeScript y colección de Postman

- `app/sdk_generador.py` los **genera del contrato OpenAPI vivo** y se descargan desde `/docs/sdk/guilda_work.py`, `/docs/sdk/guilda-work.ts` y `/docs/sdk/guilda-work.postman_collection.json` (página `/docs/sdk`); salen ya apuntando a la instancia que los sirve. No hay ficheros que mantener ni versionar: cada descarga refleja la API de ese momento.
- **Python**: un fichero, solo biblioteca estándar. Un método por operación (236) con firma tipada y docstring (argumentos, obligatorios, área de token); reintentos con retroceso en red/502-504 y `Retry-After` en 429; `Idempotency-Key` automática (y estable entre reintentos) en los POST; `ErrorGuilda` con `codigo`/`status`/`request_id`; `paginar`, `sincronizar_desde`, ETag opcional, multipart y descargas binarias, y `verificar_firma_webhook`.
- **TypeScript**: un fichero con `fetch`, tipos de todas las entidades, un método por operación (argumentos de camino, luego cuerpo, luego consulta) y lo mismo de reintentos, errores, paginación y firma. Comprobado con `scripts/comprobar_sdk_ts.sh` (compila en `--strict` y pasa una prueba de comportamiento con un contenedor `node:22-alpine` desechable).
- **Postman** v2.1: carpetas por tema, variables `base_url` y `token`, auth Bearer, ejemplos, scripts (guarda el token al hacer login; `Idempotency-Key` y `X-Request-Id` automáticos).
- Tests (`tests/test_sdk.py`): el cliente de Python se ejecuta de punta a punta contra la API real (registro, notas, upsert, paginación, multipart, binarios, sincronización, errores, reintentos con 429 y red caída, ETag, firma de webhooks); TypeScript y Postman se validan estructuralmente (y TS con `tsc` si está instalado).

## Ayuda contextual (enlaces al centro de ayuda)
- `app/ayuda.py` asocia cada pantalla (por prefijo de endpoint; gana el más largo) con su artículo de `help.guildawork.com` y lo inyecta como `ayuda_url`: un botón con el libro junto al «?» de atajos y el enlace «Ayuda sobre esta pantalla» del panel de ajustes. Sin artículo propio, enlaza a la portada de la ayuda. El enlace va en el idioma de la persona (`/ca/`, `/en/`, `/fr/`; el español está en la raíz): el centro de ayuda está traducido y se genera con `guilda-help/generar.py` (ver su README). La base se cambia con `GUILDA_AYUDA_URL`.
- Los artículos viven en el repo `guilda-help` (`contenido/<categoria>/<slug>.md`, ver su README para compilar y publicar). El test `tests/test_ayuda_contextual.py` comprueba que todo el mapa apunta a artículos que existen (se salta si el repo no está en la máquina; ruta en `GUILDA_AYUDA_CONTENIDO`). Al renombrar un artículo hay que actualizar `MAPA`.
- Las notas tienen su artículo (`trabajo-diario/notas`).

- `GUILDA_FIREBASE_CREDENTIALS_PATH`: ruta al JSON de cuenta de servicio de Firebase (Firebase Console → Project Settings → Service accounts → Generate new private key) para el push a la app móvil. Sin ella, `app/push.py` no envía nada y las notificaciones dentro de la app siguen funcionando.

## Estado del servicio, errores 5xx, límites por tipo y restricciones de token
- `GET /api/v1/health` (público): `200` si responde la app y la base de datos, `503` si no. Para Uptime Kuma (monitor HTTP cada minuto, esperado `200`) o un balanceador.
- Tabla `errores_servidor` (5xx con la plantilla de la ruta, sin identificadores ni consulta; 7 días). El panel Salud del backoffice añade «Errores del servidor (5xx)»: ámbar desde 3 en 15 min, rojo desde 10; el vigilante diario envía correo en rojo (una vez al día por motivo). Requiere reiniciar `guilda-work` (migra la tabla).
- Límites de la API por persona: 600/min en total, 200 de escritura y 20 «pesadas» (`GUILDA_API_LIMITE_POR_MINUTO`, `GUILDA_API_LIMITE_ESCRITURAS_POR_MINUTO`, `GUILDA_API_LIMITE_PESADAS_POR_MINUTO`). Las cabeceras informan del cupo más ajustado y `X-RateLimit-Scope` dice cuál es.
- Tokens: `ips_permitidas` y `origenes_cors` (columnas `tokens_api.ips_permitidas/origenes_cors`, migran al reiniciar). La IP real sale de `ProxyFix(x_for=1)` (Caddy). Un token con IPs se rechaza en el MCP.

## Copia de seguridad con Restic en el segundo disco
- **Qué hace** (`scripts/backup_restic.sh`, 26 objetivos): un volcado `pg_dumpall` de cada Postgres en marcha (Kratos, Hydra, Synapse, MAS, Nextcloud, Documenso, Outline, GlitchTip, FacturaScripts), los volúmenes de Docker con datos reales (Stalwart, Nextcloud, Vaultwarden, Synapse, n8n, VPN, MinIO, Grafana y los de servicios parados), las SQLite de la plataforma (`registro.db`, `backoffice.db`, copia consistente con la API de SQLite), los secretos y la configuración (`.env`, `/etc/guilda-work.env`, Caddyfile, claves del backoffice y del llavero de correo) y los datos de FacturaScripts de cada despacho. No copia lo regenerable (redis, meilisearch, logs de Loki, certificados de Caddy, configuración de Jitsi).
- **Dónde**: repositorio en `/mnt/HC_Volume_106540289/restic` (el segundo disco, `sdb`), configurado en `/etc/restic.env` (solo root, modo 600, con `RESTIC_REPOSITORY` y `RESTIC_PASSWORD`). El script se niega a escribir si ese destino cae en el disco principal (segundo disco sin montar). **La contraseña tiene que guardarse también fuera del servidor** (gestor de contraseñas): sin ella la copia no se abre y, si falla el disco principal, también se pierde `/etc/restic.env`.
- **Cuándo**: `restic-backup.timer` (03:00 + hasta 30 min de margen), que lanza `restic-backup.service` (root, `RequiresMountsFor` el segundo disco). Retención por objetivo: 7 diarias, 4 semanales y 6 mensuales; los domingos se comprueba una muestra del 3 % de los datos. Unidades y plantillas en `deploy/`; instalación: copiar a `/etc/systemd/system/`, `systemctl daemon-reload` y `systemctl enable --now restic-backup.timer`.
- **Vigilancia**: el script deja `data/backups/restic_estado.json` y el panel Salud muestra «Copia de seguridad en otro disco (Restic)»: verde hasta 36 h, ámbar hasta 3 días o con fallos en la última pasada, rojo después; el vigilante diario avisa por correo en rojo.
- **Prueba mensual de restauración** (`scripts/verificar_restauracion_restic.sh`, `restic-verificacion.timer`, día 1 a las 05:00): comprueba el 10 % de los datos del repositorio, restaura `registro.db` (integridad y usuarios), carga el volcado de Kratos en un Postgres desechable SIN red (identidades > 0) y restaura el volumen de Vaultwarden (no vacío); todo en `/var/tmp` y sin tocar producción. El panel Salud muestra «Prueba de restauración de la copia» (verde hasta 40 días, rojo si falló) y el vigilante avisa por correo. Se puede lanzar a mano: `systemctl start restic-verificacion.service`.
- **Avisos por correo**: el panel Salud del backoffice tiene «Avisos por correo» con dos botones: «Comprobar conexión» (se autentica en el SMTP sin enviar nada) y «Enviar aviso de prueba» (llega al destino de `ALERTAS_ADMIN_EMAIL`, mostrado enmascarado). Conviene pulsarlos tras cualquier cambio del correo saliente: todas las alertas dependen de él.
- **Restaurar** (ejemplos; `source /etc/restic.env` antes y sustituye `IMG` por la imagen del script):
  `docker run --rm -v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY" -e RESTIC_REPOSITORY -e RESTIC_PASSWORD IMG snapshots` lista las copias; `... restore latest --tag pg-kratos --target /ruta` recupera un volcado (cárgalo con `psql` en un Postgres limpio); `--tag vol-vaultwarden-data` un volumen; `--tag host` las SQLite, secretos y Caddyfile. Probado: restauración de un volcado de Kratos, del volumen de Vaultwarden (idéntico al vivo) y de `registro.db` (integridad correcta, 4 usuarios).
- **Límites que conviene tener claros**: el segundo disco es otro DISCO pero sigue siendo el MISMO servidor (protege de un fallo o borrado del disco principal, no de perder el VPS ni de un borrado de la cuenta del proveedor); los datos de FacturaScripts de cada despacho viven en ese mismo segundo disco, así que su copia comparte disco con ellos. Para sobrevivir a la pérdida del servidor hace falta además una copia fuera (un bucket S3-compatible o la copia de volúmenes del proveedor): Restic admite `RESTIC_REPOSITORY=s3:...` a mano, pero este script solo acepta rutas locales. Las SQLite crudas de Vaultwarden, n8n y Uptime Kuma se copian con el servicio en marcha (consistentes a nivel de fallo, no transaccional).

## Revisión de seguridad (2026-10-11) y limpieza de disco
- **Hallazgos corregidos**: (1) la app principal no enviaba ninguna cabecera de seguridad; ahora lleva `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Content-Security-Policy: frame-ancestors 'self'; object-src 'none'; base-uri 'self'`, `Referrer-Policy` y, tras HTTPS (`X-Forwarded-Proto`), `Strict-Transport-Security` sin `includeSubDomains`. Una CSP de scripts estricta queda pendiente (exige nonces: la app usa scripts en línea). El backoffice ya las llevaba. (2) El Kratos de los tests publicaba su API de administración en `0.0.0.0` con un puerto aleatorio mientras corría la suite (Docker salta ufw y `DOCKER-USER` está vacío): ahora `127.0.0.1` en `docker-compose.test.yml`. (3) Las 19 imágenes de `docker-compose.yml` que no estaban fijadas (servicios no desplegados) ya llevan digest; solo queda `openproject` (el tag es una variable).
- **Kratos sin `--dev` (aplicado el 2026-10-11)**: antes corría con `--dev` (comprobaciones de seguridad desactivadas, cookies CSRF/sesión sin `Secure`). Se recreó solo ese contenedor con `docker compose up -d --no-deps kratos` (mismo `.env` del proyecto, misma imagen y mismas variables; solo cambió el comando a `--sqa-opt-out --watch-courier`) tras una copia fresca de Restic. Comprobado: `/health/ready` 200, el flujo de login redirige bien y la cookie CSRF ya lleva `Secure`. Marcha atrás: `KRATOS_EXTRA_FLAGS=--dev docker compose up -d --no-deps kratos`. Para desarrollo en http://127.0.0.1 hay que poner `KRATOS_EXTRA_FLAGS=--dev` en el `.env` local (las cookies Secure no viajan por http).
- **Menor**: `DOCUMENSO_DB_PASSWORD` usa el valor por defecto del compose (la base de datos solo es alcanzable desde la red interna de Docker); conviene rotarla. Las de Baserow, Cal.com, Chatwoot, EspoCRM, Listmonk y Umami también están por defecto pero esos servicios no están desplegados.
- **Disco**: se borraron 3,2 GB de restos de tests en `/var/tmp` (`gwt`, `gwc`) y 38 volúmenes anónimos huérfanos de FacturaScripts (1,1 GB; los datos reales están en bind mounts). `docker rm` de los contenedores de FacturaScripts pasa a `docker rm -v` para no dejar uno por cada recreación. Quedan sin tocar los volúmenes con nombre de servicios parados (Baserow, OpenProject, Paperless, ~0,5 GB).
- **Tests**: `docker-compose.test.yml` usa bcrypt con coste mínimo y sin «Have I Been Pwned» (solo tests): cada inicio de sesión pasa de ~1,5 s a ~0,5 s. `scripts/probar.sh -n 3` los reparte en 3 procesos (necesita `pytest-xdist` en `.herramientas-test`, fuera del venv de producción).

## Política de contenido (CSP) estricta para scripts
- La app ya no tiene manejadores `on...=` ni `javascript:` en el HTML: `static/csp_compat.js` los sustituye con atributos `data-*` (`data-confirmar-envio`, `data-confirmar-clic`, `data-autoenviar`, `data-mostrar`, `data-accion`, `data-requerido-si-vacio`, `data-autoaltura`) y cada `<script>` en línea lleva `nonce="{{ csp_nonce }}"`, distinto en cada petición. Efecto secundario bueno: las confirmaciones ya no se rompen en catalán o francés con apóstrofos (antes iban dentro de una cadena JavaScript).
- Modo con `GUILDA_CSP` (`app/seguridad_csp.py`): **`reportar`** (por defecto) manda `Content-Security-Policy-Report-Only` y el navegador avisa a `POST /csp-report` (una línea `CSP: ...` en el registro de `guilda-work`, limitado a 30/min por IP) de lo que bloquearía, sin romper nada; **`forzar`** manda `Content-Security-Policy` y bloquea; **`no`** quita la parte de scripts. Siempre se hace cumplir `frame-ancestors 'self'; object-src 'none'; base-uri 'self'`.
- Política de scripts: `script-src 'self' 'nonce-...'`, `worker-src 'self' blob:` (la prueba de trabajo del captcha crea un Worker desde un Blob). Los estilos en línea (`style=`) siguen permitidos: es riesgo bajo y quitarlos es otro proyecto.
- **Para pasar a `forzar`**: despliega en `reportar`, usa la app unos días (todas las pantallas que uses de verdad) y mira `journalctl -u guilda-work | grep "CSP:"`. Si no hay avisos, pon `GUILDA_CSP=forzar` en `/etc/guilda-work.env` y reinicia. Si algo se rompe, `GUILDA_CSP=reportar` lo deshace sin tocar código.
- Pruebas: `tests/test_cabeceras_seguridad.py` (recorre todas las pantallas buscando manejadores en línea o scripts sin nonce) y `scripts/comprobar_csp_compat.sh` (jsdom en un contenedor Node desechable: confirma el comportamiento de cada `data-*`).

## Verificación en dos pasos (TOTP) para los usuarios de la app
- **Opcional por persona**: se activa en Ajustes → Contraseña y email (app de autenticación con QR + 12 códigos de recuperación de un solo uso). Kratos: métodos `totp` y `lookup_secret` y `session.whoami.required_aal: highest_available` en `deploy/kratos/kratos.yml` (el cambio de configuración exige recrear/reiniciar el contenedor de Kratos). Quien no la activa entra como siempre.
- **Web**: con la contraseña sola la sesión es AAL1 y Kratos responde 403 `session_aal2_required`; `kratos.requiere_aal2()` lo detecta y `/login` abre el flujo del segundo factor (`?aal=aal2`) con formulario de código y de recuperación. El puente de Hydra (`/hydra/login`) hace lo mismo para ChatGPT/Claude (sin eso entraba en un bucle).
- **API**: `POST /api/v1/auth/login` responde `401 requiere_2fa` si falta `codigo_2fa`; con un código correcto (6 dígitos o de recuperación) entrega el token. Sin esta comprobación la contraseña sola habría dado acceso (Kratos concede una sesión AAL1). Los tokens de API ya emitidos no cambian.
- **Salida si se pierde todo**: backoffice → usuario → «Quitar la verificación en dos pasos» (Admin API de Kratos: borra las credenciales `totp` y `lookup_secret`; queda auditado).
- **Pendiente**: la app móvil (Flutter) todavía no tiene campo para el código: quien active la verificación no podrá volver a iniciar sesión en el móvil hasta que se actualice (las sesiones ya abiertas siguen). La pantalla de ajustes lo avisa.
- **Pruebas**: `tests/test_dos_pasos.py` (Kratos real: API con app y con códigos de recuperación de un solo uso, web con aal2, puente de Hydra, ajustes con QR y salida desde el backoffice).

## Aspecto de la app: superficies de cristal

Todas las pantallas internas (las que extienden `base.html`) cargan `app/static/superficies.css` DESPUÉS de `style.css`. Es el mismo lenguaje que el inicio de sesión: fondo con luz ambiente suave (dos degradados radiales fijos, lima y azul), paneles translúcidos con desenfoque y filo de luz de 1 px en vez de cajas con borde sólido, una escala de radios (12/16/22 px), Manrope en todo (sin el monoespaciado en mayúsculas de «terminal») y controles redondeados con foco suave.

- **Cómo está hecho:** `style.css` ya pasaba casi todas las superficies por `--glass-bg/--glass-border/--glass-blur`; la capa redefine esos tokens (y `--border`, ahora un filo translúcido) y sustituye las cajas planas por la misma receta. No cambia HTML ni estructura: si la hoja no carga, la app sigue con el estilo anterior.
- **Qué NO la carga:** inicio de sesión (tiene su propio diseño con foto), registro, recuperar contraseña, verificar correo, portal de cliente (paleta de papel cálido propia) y el backoffice (hoja propia, `backoffice/static/backoffice.css`).
- **Para tocar el aspecto:** los tokens están arriba del fichero (`--glass-bg`, `--panel-2`, `--panel-2-hover`, `--linea`, `--ambiente`; uno por tema). Las listas de selectores de «panel de cristal» y de «etiqueta suave» están en el bloque «Paneles de cristal». Una pantalla nueva con `.dash-panel`/`.log-item`/`.btn` ya sale bien sin CSS propio.
- **Casillas y botones de opción** son propios (`appearance: none`); ojo con reglas que les pongan `width: auto` (por eso llevan `min-width`).
- **Sin soporte de `backdrop-filter`** los fondos pasan a casi opacos; los menús flotantes (`.busqueda-modal`, `.new-menu`, `.top-bar-menu`, `.toast`) son siempre casi opacos.
- **Contraste:** `tests/test_superficies.py` calcula cada color de texto sobre el peor caso (luz ambiente más intensa bajo el panel, y fila resaltada encima) en claro y oscuro (AA 4,5:1). Por eso `--text-muted` está redefinido en la capa (`#566070` claro, `#9ba2ac` oscuro).
- **Fechas legibles:** filtros Jinja `fecha_y_hora` («11 oct 2026, 20:43») y `fecha_dia` («11 oct 2026») en el idioma de la persona; sustituyen a `[:16].replace('T', ' ')` en las plantillas. Si el dato no es una fecha ISO se muestra tal cual.
- **Ver cómo queda sin tocar producción:** copia aislada del repo + datos sintéticos + sesión simulada de Kratos en 127.0.0.1 y capturas con un Chromium de Playwright instalado fuera del repo (`/tmp`); nada de esto vive en el repositorio.

### Móvil, landing y centro de ayuda (2026-10-11)

- **Menú lateral en móvil (≤ 640 px):** el rail pasa a ser un panel deslizante que se abre con el botón de la barra superior (`#menu-movil-abrir`, estado en `<html data-menu-movil>`, lógica en `sidebar.js`, estilos al final de `superficies.css`). Cerrado es `visibility: hidden` (no recibe foco); Esc, el fondo y cualquier enlace lo cierran. Antes era una columna fija de 64 px que dejaba ~270 px de contenido en un móvil de 360.
- **Auditoría de desbordes:** se recorrieron todas las pantallas internas a 320/360/414/768/1024/1280 px en claro y oscuro (Playwright sobre copia aislada con datos sintéticos; fuera del repo). Causa más repetida: en móvil `style.css` apila `.quick-row` en columna pero deja `flex: … 100%` en los campos, y en columna ese 100% pasa a ser ALTURA. Arreglos en `superficies.css` (bloques «Que nada ensanche la página» y los de ≤ 640 px).
- **Landing (`/var/www/landing`, repo propio):** `capa.css` se carga tras `estilo.css`/`blog.css` en las 29 páginas; Manrope en `/fonts/`. Cabecera sin solapes (hamburguesa hasta 1180 px; en móvil marca + Entrar + menú en una línea), cookies compactas en cristal, tarjetas y formulario de cristal.
- **Centro de ayuda (`/home/guilda/guilda-help`):** capa al final de `estaticos/style.css` (cabecera flotante, tarjetas con icono en baldosa, artículo en panel de cristal, tablas y bloques de código). Se despliega como siempre: `generar.py` + copiar `salida/` a `/var/www/help`.

### Portal de cliente, páginas de acceso y backoffice (2026-10-11)

- **`app/static/paginas_cristal.css`** (tras `style.css`) en el portal de cliente (5 páginas) y en registro, recuperar contraseña y verificar correo: papel cálido con luz ambiente, filas y paneles de cristal, Manrope, tarjeta de acceso redondeada. Mantiene la identidad del portal (tokens `--portal-*`); NO carga `superficies.css`. Redefine `--portal-muted` (`#625d4a` / `#b3ad96`) porque el anterior no llegaba a AA sobre blanco. Fechas del portal con el filtro `fecha_dia`.
- **`backoffice/static/capa.css`** (tras `backoffice.css`, también en `login.html` y `login_2fa.html`; fuente en `backoffice/static/ManropeVariable.woff2`): cristal turquesa, navegación en pastilla, controles y tablas más suaves. El backoffice sigue siendo un proceso y una hoja aparte; solo comparte el lenguaje visual.
- **`/ia/panel` es un fragmento HTML** (se inyecta en la página, sin CSS propio): abrirlo suelto en el navegador se ve roto y desborda; no es un fallo.
- Revisado con rastreo de enlaces a 320/360/820/1280 px en claro y oscuro (sin desbordes) y el menú móvil en ca/en/fr.

### Selector con buscador (2026-10-12)

`app/static/selector_buscable.js` (cargado en `base.html`, solo pantallas internas) convierte los `<select>` con **6 o más opciones** (proyectos, clientes fiscales, personas…) en un panel con campo de búsqueda: se escribe «vid» y quedan las opciones que contienen «vid», sin distinguir mayúsculas ni acentos y con varias palabras (todas deben aparecer). Teclado completo (↑↓ Enter Esc Tab; escribir sobre el selector lo abre con esa letra), cabeceras de `<optgroup>`, resaltado de lo escrito, y hoja inferior a todo el ancho en móvil. Con más de 300 coincidencias pinta las 300 primeras y avisa.

- **Mejora progresiva:** el `<select>` sigue siendo el control real (formulario, `required`, `value`, evento `change`, `data-autoenviar`, lectores de pantalla); solo se intercepta la apertura. Sin JavaScript o con pocas opciones se ve la lista nativa.
- **Control por atributos:** `data-buscable` fuerza la mejora, `data-sin-buscador` (en el select o en un contenedor) la evita; `multiple` y `size > 1` nunca se mejoran. También mejora selects añadidos después o a los que llegan opciones más tarde (MutationObserver).
- **Textos** (`Buscar…`, `Sin resultados`, `Mostrando %s de %s…`) viajan en atributos `data-t-*` de `<html>`; ojo: dentro de `_()` el `%` va escrito `%%` (flask-babel formatea siempre).
- **Pruebas:** `scripts/comprobar_selector_buscable.sh` (jsdom en un contenedor Node desechable, 27 comprobaciones) y `tests/test_superficies.py`. El flujo táctil y el teclado real se comprobaron con Chromium; **no con un móvil físico** (en iOS/Android el toque se intercepta con `touchend` para evitar el selector nativo).
- **Fuera de alcance de momento:** backoffice y portal (hojas aparte) mantienen sus selects nativos.

### Evaluación de la oferta de herramientas del asistente / MCP (2026-10-12)

`tests/datos/evaluacion_herramientas.py` reúne ~60 peticiones realistas (una persona en un despacho) con la herramienta que tiene que estar disponible YA en el primer turno; `tests/test_evaluacion_herramientas.py` comprueba que `ia_herramientas.herramientas_para()` la incluye y que la oferta media sigue siendo una fracción del catálogo (≤ 55 %). No usa modelo real: mide lo que depende de nosotros (las palabras clave de `herramientas_grupos.PALABRAS`). Para ampliarlo, añade una línea `(petición, herramienta)`; si falla, añade la palabra clave que falta al grupo. Lo que NO mide es si un modelo concreto elige bien entre las herramientas ofrecidas (eso exige una clave de API).

### Pasar la CSP de «informar» a «forzar»

`scripts/comprobar_csp_para_forzar.sh [DIAS]` (por defecto 5) cuenta los avisos `CSP:` del registro de `guilda-work` en ese periodo y comprueba que el registro lo cubre; sale con `LISTO` solo si hay cero avisos. No cambia nada. Si sale `LISTO`: `echo 'GUILDA_CSP=forzar' >> /etc/guilda-work.env && systemctl restart guilda-work`; para volver atrás, `GUILDA_CSP=reportar` y reinicio. Un aviso suelto con `blocked-uri='inline'` y `source-file` igual a la propia página puede ser una extensión del navegador (gestores de contraseñas, traductores) inyectando un `<script>`: antes de contarlo como fallo de la app, reprodúcelo con el navegador sin extensiones.

### Recuperar contraseña (fallo de 404 y textos en inglés, 2026-10-12)

- **Bug:** Kratos redirige a `…/ajustes-cuenta` (`SELFSERVICE_FLOWS_SETTINGS_UI_URL` y `…RECOVERY_AFTER_DEFAULT_BROWSER_RETURN_URL` en `docker-compose.yml`) al terminar de recuperar la contraseña con el código, y esa ruta no existía (la app usa `/ajustes/cuenta`): justo al elegir la contraseña nueva, 404. Ahora `/ajustes-cuenta` existe y sirve la misma pantalla. Si alguna vez se cambia la ruta, cambiar también esas dos variables.
- **Textos:** Kratos manda sus mensajes y etiquetas en inglés. `main._msg_kratos` (filtro `msg_kratos`) traduce los conocidos por el principio del texto inglés («Recovery code», «Continue», «An email containing a recovery code has been sent…»); lo desconocido se muestra tal cual. Los avisos informativos (`type != 'error'`) usan `.auth-info`, no el rojo de error, y los campos ocultos de Kratos (`method`) ya no salen como etiqueta suelta.
- Para añadir otro mensaje: una línea en `_msg_kratos` + sus traducciones en ca/en/fr.

### Cuentas sin dirección de recuperación (el correo de «olvidé mi contraseña» no llegaba)

Una cuenta cuya identidad de Kratos no tiene `recovery_addresses` es «desconocida» para la recuperación: la pantalla dice «te hemos mandado un código» pero Kratos no manda nada (no revela qué direcciones existen; en su registro aparece «recovery was requested for an unknown address»). Pasó con `gestio@guilda.cat` (creada el 7-ago, antes de que el esquema declarase `recovery.via`/`verification.via`). Diagnóstico: `select i.traits->>'email', (select count(*) from identity_recovery_addresses a where a.identity_id=i.id) from identities i;` en la base de Kratos. Arreglo: `scripts/reparar_direcciones_kratos.py` (sin argumentos solo lista; `--aplicar [--email X]` vuelve a guardar la identidad con sus mismos datos para que Kratos genere las direcciones; no toca la contraseña ni el segundo factor). Las cuentas creadas hoy por `kratos.crear_identidad` ya las llevan.

### Páginas de acceso con la misma foto que el inicio de sesión

Recuperar contraseña, registro, verificar correo y el acceso/solicitud del portal de cliente (`.auth-shell` en `app/static/paginas_cristal.css`) y el acceso al backoffice (`body.pagina-login` en `backoffice/static/capa.css`, con la foto copiada a `backoffice/static/fotos/` porque es otra aplicación) llevan la foto de montaña a pantalla completa y la tarjeta de cristal del login (oscura por defecto, clara en tema claro; el backoffice conserva su turquesa). Los valores (velo, tinte, desenfoque, colores de apoyo y de enlace) son los de `.auth-dividido` de `style.css`; `tests/test_superficies.py` comprueba que siguen iguales y mide el contraste AA de cada color con la tarjeta CENTRADA sobre la foto en 5 tamaños de pantalla. Si cambias la foto o su posición, copia `app/static/fotos/montana-login.*` a `backoffice/static/fotos/` (un test avisa si difieren). El portal de cliente ya con sesión (vencimientos, documentos) sigue en papel cálido: es una pantalla de trabajo, no de entrada.

### Correos con el diseño de Guilda Work

Todos los correos que manda la app (`app/notificaciones_email.py`: enlace de acceso al portal, solicitud de documento, enlace de pago, respuesta del equipo, recordatorios de vencimientos —con o sin el texto propio del despacho— y las alertas internas) salen **multipart/alternative**: texto plano + HTML con el diseño del inicio de sesión (foto de montaña de fondo, tarjeta oscura redondeada, botón lima, código destacado). Lo construye `app/correo_diseno.py` (`construir()` → `(plano, html)`): maquetado con tablas y estilos en línea, tarjeta OPACA (los clientes de correo no admiten `backdrop-filter`), foto solo de adorno (si no se carga queda un azul oscuro liso y se lee igual), todo texto de fuera escapado y colores con contraste AA medido en `tests/test_correo_diseno.py`. Las imágenes se sirven desde `{GUILDA_ORIGIN}/static/fotos/email-fondo.jpg` y `/static/email-logo.png` (ligeras: 62 KB y 12 KB; deben ser públicas, sin sesión). El texto plano de las alertas internas y el del texto propio del despacho se mantienen idénticos a antes.

**Correos de Kratos** (código de recuperación y de verificación): plantillas en `deploy/kratos/courier-templates/`, generadas con el mismo diseño por `scripts/generar_plantillas_kratos.py` (`kratos.yml` → `courier.template_override_path`). Kratos solo las lee al arrancar: `cd /home/guilda/guilda-work && docker compose up -d --force-recreate kratos` (unos segundos sin inicio de sesión). **Idioma:** Kratos no tiene plantillas por idioma, así que el proxy de la app (`rutas_kratos_proxy.py`) añade `transient_payload={"lang": "<idioma de la pantalla>"}` al pedir una recuperación o una verificación (es el idioma que ve la persona: el guardado en su cuenta o, si no hay sesión, el de su navegador entre es/ca/en/fr) y cada plantilla elige su variante con un `if` sobre `.TransientPayload`. Sin idioma o con uno desconocido sale la versión en castellano, con una línea de seguridad en los cuatro. **El asunto no lleva el código** (se ve en notificaciones de pantalla bloqueada y en listados): solo el cuerpo. Verificado de punta a punta con un Kratos desechable (10 casos: 4 idiomas × recuperación/verificación, sin idioma y desconocido). Verificadas de punta a punta con un Kratos desechable y un servidor SMTP de captura (asunto con el código, multipart, sin marcas sin resolver); si se cambia el diseño, regenerar y el test `test_las_plantillas_de_kratos_estan_al_dia_con_el_generador` avisa si se olvida.

## Foto de montaña en el inicio de sesión
- La foto ocupa **toda la pantalla** de `/login` (`.auth-dividido`, `app/static/fotos/montana-login.webp` y `.jpg`, 1920 px de ancho) con un velo liso (sin degradado direccional). Es **CC0 (dominio público)**: «Landscape-mountains-nature-lake» de www.Pixel.la Free Stock Photos, de Wikimedia Commons; datos en `app/static/fotos/CREDITOS.md`. Va de fondo por CSS (no es un `<img>`).
- Encima, dos **paneles de cristal** (tinte + `backdrop-filter: blur`): el del texto (`.auth-hero-panel`, siempre oscuro, con la marca, el titular, el párrafo y las ventajas) y la tarjeta del formulario (`.auth-dividido .auth-card`: oscura por defecto y **clara en el tema claro**; dentro de ella se reajustan el gris de apoyo y el color de los enlaces para mantener el contraste). Sin soporte de `backdrop-filter` los tintes suben a casi opacos (0,93-0,97).
- **Móvil** (< 820 px): se oculta el panel del texto y la tarjeta del formulario queda centrada sobre la misma foto (recolocada con `background-position: 40% 50%`), a pantalla completa (`100dvh`).
- **Legibilidad medida**: `tests/test_foto_login.py` recrea lo que dibuja el navegador (foto `cover` + velo + desenfoque + tinte de cada panel) y exige contraste AA (4,5:1) de cada color de texto contra el PEOR píxel de la zona del panel (el más claro para texto claro, el más oscuro para texto oscuro), en 1920×1080, 1366×768, 820×1180, 390×844 y 360×740. Hoy el peor caso es 6,0:1 (texto del hero), 5,9:1 (tarjeta oscura) y 5,2:1 (tarjeta clara). Si se cambia la foto o los valores y baja de ahí, el test falla.
- **Tema claro**: el logotipo es blanco; en la tarjeta clara va sobre una pastilla oscura (`.auth-logo`, también en registro, recuperar contraseña y portal, que no llevan foto).
- Para cambiar la foto: sustituye los dos ficheros (mismo nombre; mejor 3:2 y ≥ 1920 px de ancho), actualiza `CREDITOS.md` con su licencia y origen (solo fotos CC0 o con licencia que permita el uso sin atribución) y pasa el test.

## Exportar a PDF (informes y fichajes)
- **Fichajes**: el PDF de administración ya existía (`/fichaje/admin/exportar.pdf`). Nuevos botones «Descargar PDF» en **Mi historial** (`/fichaje/historial.pdf`: solo los fichajes propios, con el filtro de fechas) y en el **detalle de cada trabajador** (misma ruta de administración con `usuario_id`, con los mismos permisos de siempre).
- **Informes**: **Histórico** → botón PDF (`/export?formato=pdf`, `export.a_pdf`, mismos filtros que el CSV); bajo el **informe de IA** → «Descargar informe en PDF» (`POST /informe-ia/pdf`; el servidor no guarda el informe, llega en el formulario y se limita a 60 000 caracteres); **carga del equipo** del panel de inicio → «Exportar PDF» (`/tareas/carga.pdf`).
- Todo con reportlab (ya en `requirements.txt`, sin binarios de sistema). Los textos de usuario se escapan antes de pintarlos como párrafo (`generador_documentos.texto_a_pdf`, `tabla_a_pdf`, `fichaje_export.a_pdf`), para que un `<` en una nota no rompa el PDF. Tests en `tests/test_exportar_pdf.py`.
- Requiere reiniciar solo `guilda-work`.

## El asistente de IA como soporte de la plataforma
- **Qué hace** (`app/ia_soporte.py`): responde dudas de uso buscando en el centro de ayuda (`ayuda_buscar`: título, enlace en el idioma de la persona y un fragmento), lleva a la pantalla correcta (`abrir_pantalla`, lista cerrada `DESTINOS`, solo devuelve el enlace), lee y cambia **solo los ajustes de la propia cuenta** (`ver_mis_ajustes`, `cambiar_mis_ajustes`: idioma, nombre/cargo/teléfono, avisos, «no molestar»; con confirmación como cualquier escritura y bloqueado en modo solo lectura) y, si la ayuda no cubre algo o la persona cuenta un fallo o una idea, redacta el borrador de un **tiquet** (error o sugerencia, sin datos personales ni de clientes) y lo registra con `crear_tiquet` solo tras confirmar. No toca contraseña, email, 2FA, dispositivos, tema (vive en el navegador) ni administración: explica y enlaza.
- **Mismo chat**: no hay modo aparte. Un turno es «de soporte» si el último mensaje lo parece (`es_consulta_soporte`: «cómo…», «dónde…», «no funciona», «ayúdame a configurar…», «quiero sugerir…», en es/ca/en/fr, salvo que empiece como una orden de datos: «lista…», «crea…»). En ese turno solo se ofrecen las herramientas de soporte (`HERRAMIENTAS_SOPORTE`) y el modelo no tiene acceso a los datos de trabajo.
- **No cuenta en el límite de IA**: `ia_asistente._reservar_turno` no suma el turno de soporte al consumo del despacho ni lo bloquea cuando el límite está agotado. Excepciones: IA desactivada para el despacho (límite 0) → tampoco hay soporte; y un **cupo diario gratuito de 60 consultas por persona** (`TOPE_DIARIO_GRATIS`, tabla `ia_soporte_uso`, se limpia a 7 días) para que «cómo…» no sirva de chat gratuito: pasado el cupo la consulta cuenta como normal (nunca se rechaza).
- **Pantalla actual**: el navegador manda el `Referer` del chat; `rutas_ia._recordar_pantalla` guarda en memoria el endpoint (se pierde al reiniciar, no importa) y el prompt dice en qué pantalla está y su artículo, para entender «aquí» o «esto». El chat de página completa (`/ia`) no cuenta.
- **Origen de la ayuda**: lee `/home/guilda/guilda-help/salida/<idioma>/indice.json` (el que genera `generar.py`; se recarga solo al republicar la ayuda). Cambiar la carpeta con `GUILDA_AYUDA_INDICE_DIR`. Sin índice, el asistente dice que la ayuda no lo cubre y ofrece el tiquet. Búsqueda por palabras (raíces de 6 letras, título ×4); si se queda corta, el siguiente paso son los embeddings que ya tiene la app.
- **Preguntas sin respuesta**: no se registra nada en silencio; solo llega un tiquet cuando la persona acepta el borrador. Se ven en Tiquets como cualquier otro.
- **Atajos de serie nuevos**: «¿Cómo funciona esta pantalla?» y «Ayúdame a configurar mi cuenta» (traducidos).
- **Ayuda**: nueva sección «El asistente también es tu soporte» en `usar-el-asistente` (es/ca/en/fr, en `guilda-help`; comprobada con `generar.py` + `comprobar.py` en una copia). **Falta publicarla** (`generar.py` en `guilda-help`): hasta entonces el asistente no conoce esa sección.
- Tests en `tests/test_ia_soporte.py` (detección en 4 idiomas, búsqueda, destinos, ajustes propios y rechazos, herramientas ofrecidas, límite/cupo, prompt, tiquet con confirmación, de punta a punta con un modelo simulado).
- Requiere reiniciar solo `guilda-work` (crea una tabla nueva sola al arrancar).

## Sistema de diseño (componentes y candado)
- **Componentes** (Día 1 de `PLAN_MAESTRO.md`): estilos en `app/static/ds.css`, comportamiento en `app/static/ds.js` y macros en `app/templates/_ds/componentes.html` (`boton`, `interruptor`, `estado_vacio`, `campo`, `seccion`, `esqueleto`, `chip`, `sin_validar`, `icono`). Usan los mismos tokens que `superficies.css`, así que siguen el tema y la densidad solos.
- **Diálogos propios** (`window.GuildaDS.confirmar / pedirTexto / avisar`): sustituyen a `confirm()`, `prompt()` y `alert()` con un `<dialog>` accesible (foco atrapado, Esc, foco inicial en «Cancelar» si la acción es destructiva, texto siempre como texto). Sin `<dialog>` en el navegador caen a los nativos. `csp_compat.js` los usa para `data-confirmar-envio` y `data-confirmar-clic` (nuevo: `data-confirmar-excepto="nombre"` no pregunta si envía ese botón, `data-confirmar-peligro` usa el estilo destructivo).
- **Corrección importante**: el envío de «Redactar correo» llevaba un `onsubmit` en línea que la CSP forzada bloquea, así que el aviso «¿Enviar este correo? No se puede deshacer.» no salía. Ahora usa `data-confirmar-envio`.
- **Candado** (`tests/test_sistema_diseno.py`): cuenta por fichero los `<select>` nativos, `<button>` sin clase, `style="…"`, fechas nativas y diálogos del navegador, y falla si una pantalla **empeora**. La línea base está en `tests/datos/sistema_diseno_base.json` y, cuando una pantalla mejora, el test exige bajarla con `python3 scripts/sistema_diseno_base.py` (así la lista de excepciones se vacía de verdad). Los manejadores `on…=` en línea y las etiquetas obsoletas no tienen excepciones.
- Estado de la línea base al terminar el Día 1: 0 diálogos nativos, 114 `<select>`, 32 `<button>` sin clase, 130 `style=""`, 32 fechas nativas (se reducen el Día 2).
- Las casillas y botones de opción **ya** tenían estilo global en `superficies.css`; lo que faltaba era el interruptor (`interruptor()`).
- `scripts/csp_compat_prueba.mjs` (jsdom, vía `scripts/comprobar_csp_compat.sh`) cubre ahora la confirmación asíncrona y `data-confirmar-excepto`. Requiere Docker y descarga `jsdom`.
- Tests que caducaban solos y se arreglaron de paso: las marcas de fichaje fijas de `test_api_extras.py` (solo se aceptan de los últimos 7 días) y el resumen semanal de los lunes en `test_backoffice_salud_clientes.py`.
- Requiere reiniciar solo `guilda-work`.

### Sistema de diseño, Día 2: desplegables, fechas, apariencia y estilos
- **Desplegables**: `selector_buscable.js` mejora ahora **todos** los `<select>` (`MIN_OPCIONES = 1`): lista propia en cualquier navegador y tema, con campo de búsqueda solo desde 6 opciones (`MIN_BUSCADOR`). Se saltan los `multiple`, los de `size` y los `data-sin-buscador`.
- **Fechas**: `app/static/ds_fecha.js` sustituye el calendario nativo de `date`, `datetime-local` y `time` (el campo sigue siendo el control real: se puede teclear, `min`/`max`, `required`, eventos). Semana desde el lunes, teclado completo (flechas, Inicio/Fin, AvPág/RePág, Esc), hoja inferior en móvil y, con `name="desde"`/`name="hasta"` en el mismo formulario, atajos de periodo (esta semana, este mes, mes pasado, este trimestre, este año). `data-nativo` lo desactiva. Prueba de comportamiento: `scripts/comprobar_ds_fecha.sh` (jsdom, descarga).
- **Tema y densidad en la cuenta**: se guardan en `usuarios.tema` y `usuarios.densidad` (`POST /ajustes/apariencia`, desde `apariencia.js`); `base.html` los aplica antes de pintar y mandan sobre `localStorage`, así te siguen entre dispositivos. Viven en `usuarios` (no en `usuario_perfil`) porque esa fila ya se lee en cada petición: una consulta más por página rebasaba el presupuesto de `test_bloque_a_rendimiento`. El asistente también los cambia (`cambiar_mis_ajustes`).
- **Estilos en línea**: los 88 `style="…"` estáticos de las plantillas pasaron a utilidades `ds-*` de `ds.css` (con `!important`, para conservar la prioridad que tenía el atributo). Los que llevan `{{ … }}` (ancho de una barra, color de una categoría) pintan un dato y se quedan: el candado solo cuenta los estáticos.
- **Botones sin clase**: los 32 llevan ya una clase (`btn …` los sueltos; `correo-editor-boton`, `correo-bulkbar-boton`, `ds-segmento`, `ds-cerrar`… los que estilan sus contenedores).
- **Candado a cero**: la línea base de `tests/datos/sistema_diseno_base.json` es 0 en las cinco reglas; cualquier control de fábrica nuevo rompe `tests/test_sistema_diseno.py`.
- Requiere reiniciar solo `guilda-work` (añade dos columnas a `usuarios` al arrancar).

## Núcleo común y módulos de negocio (Día 3 del plan maestro)
- **Qué es**: una base común —**clientes** (con contactos, etiquetas, idioma y responsable), **expedientes** (con línea de tiempo, confidencialidad y miembros), **plazos**, **festivos** y **horas facturables**— sobre la que cuelgan los tres módulos de negocio: **Gestoría**, **Gabinete de abogados** e **Inmobiliaria**. Código en `app/nucleo.py` (datos y reglas), `app/rutas_nucleo.py` (pantallas `/clientes`, `/expedientes`, `/plazos`, `/tiempo`) y `app/calendario_plazos.py` (cálculo de fechas, funciones puras).
- **Aditivo**: `clientes_fiscales` sigue igual. Cada cliente fiscal tiene además su ficha en `clientes` (`clientes_fiscales.cliente_id`, rellenada al arrancar para los que ya existían) y nombre, NIF, email, idioma y papelera se sincronizan en los dos sentidos. Alta, edición, papelera y borrado del despacho (`borrar_tenant`) pasan por los dos.
- **Módulos de negocio** (`app/verticales.py`; «verticales» en el código porque el backoffice ya llama «módulos» a las herramientas conectadas): un despacho tiene activo un módulo si es de serie (hoy **Gestoría**), si tiene un **extra de pago vinculado** (backoffice → Planes y extras → «Módulo de negocio que activa») o si se activó **a mano** (backoffice → despacho → Módulos: interruptor, y «Volver a automático»). El ajuste manual puede incluso quitar Gestoría; los activos se guardan 30 s en memoria (un cambio tarda hasta 30 s en verse en la app). Hoy solo Gestoría está disponible; Abogados e Inmobiliaria llegan con sus pantallas (días 4 y 5). Sin Gestoría activo las pantallas `/fiscal/…` dan 404 y el menú no las muestra.
- **Cálculo de plazos** (`app/calendario_plazos.py`): días hábiles, vencimientos en días naturales/hábiles/meses con desplazamiento a hábil, fechas de aviso (7, 3 y 1 días antes por defecto, adelantadas al hábil anterior), estado (cumplido, vencido, hoy, próximo, en plazo) y Pascua/Viernes Santo. **Los festivos que trae son nacionales y de ejemplo, SIN VALIDAR**: los autonómicos, locales y del partido judicial los añade cada despacho en `/plazos/festivos` (solo responsables). Calendario «procesal» de ejemplo: agosto inhábil. Los plazos piden **segunda revisión** por otra persona y cambiar la fecha la vuelve a pedir.
- **Permisos**: todo va acotado por despacho. Un expediente **confidencial** solo lo ven su responsable, quien lo creó, las personas añadidas y los responsables del despacho (`supervisor_tenant`); sus plazos, horas y documentos siguen la misma regla y quien no puede verlo recibe 404.
- **Horas**: partes con tarifa por persona (`usuarios.tarifa_hora_centimos`), hoja de horas por cliente, expediente o persona (con redondeo opcional a bloques), exportación CSV (con las fórmulas neutralizadas) y PDF, y marca de «facturado» (solo responsables; un parte facturado no se borra). Aún no se enlaza con el cronómetro de tareas ni genera la factura.
- **Almacén único de documentos** (`app/almacen_documentos.py`): toda escritura y lectura del contenido de documentos de clientes y expedientes pasa por ahí; el cifrado con la clave del despacho se enchufa como un `Cifrador` sin tocar a quien guarda o lee (Día 7). Las funciones antiguas del expediente documental de la ficha fiscal (`archivar_documento_cliente`…) solo las llama el almacén; `tests/test_almacen_documentos.py` falla si alguien lo esquiva.
- **Menú**: nuevo grupo «Clientes» (Clientes, Expedientes, Plazos, Horas); Fiscal depende del módulo Gestoría; los módulos nuevos añaden sus entradas (`entradas_menu` de cada `Vertical`).
- **Pendiente de los siguientes días**: herramientas del asistente y del MCP y endpoints de la API para el núcleo (Día 6), «cliente desde el remitente de un correo», enlazar el cronómetro de tareas con las horas, y los tipos de expediente de Abogados e Inmobiliaria.
- Requiere reiniciar `guilda-work` **y** `guilda-backoffice` (tablas nuevas, columnas `clientes_fiscales.cliente_id`, `extras_guilda.vertical_id`, `usuarios.tarifa_hora_centimos` y relleno de clientes al arrancar).

## Módulo Gabinete de abogados (Día 4 del plan maestro)
- **Qué es** (`app/abogados.py`, pantallas en `app/rutas_abogados.py` y `app/templates/abogados*`): el módulo de negocio para despachos de abogados, sobre el núcleo común. Se activa por despacho (backoffice → despacho → Módulos, o con un extra de pago vinculado). Sin él, `/abogados/…` da 404 y el menú no lo ofrece. Todo lo normativo es **de ejemplo y está marcado «sin validar»** en pantalla (plazos típicos, calendario procesal con agosto inhábil, IVA 21 % y retención 15 %, texto de la hoja de encargo): son valores editables en **Gabinete → Ajustes**.
- **Asuntos**: dos tipos de expediente nuevos, *Procedimiento judicial* (estados desde «En preparación» hasta «Archivado»; usa el calendario procesal) y *Asunto extrajudicial*. Su ficha lleva un panel propio que el núcleo incluye sin saber nada del módulo (`Vertical.panel_expediente` + `contexto_expediente`): datos del procedimiento (número, juzgado, jurisdicción, procurador, cuantía, resumen para el cliente), partes, notificaciones y plazos, vistas, provisión de fondos, minutas, hoja de encargo y enlace del cliente.
- **Notificaciones → plazos**: «Registrar notificación» calcula la fecha límite con el calendario procesal del despacho (festivos propios incluidos; el día de la notificación no cuenta), la enseña **antes de guardar** y, al confirmar, crea el plazo (fatal por defecto, pendiente de segunda revisión por otra persona) y una tarea para el responsable. Los atajos de plazos típicos (contestación 20, apelación 20, reposición 5 días hábiles) son orientativos y sin validar.
- **Conflicto de intereses**: al añadir una parte se comprueba si quien es nuestro cliente fue contraparte (o su letrado o procurador) en otro asunto, y si una contraparte ya es cliente del despacho; coincide por NIF o por nombre. De un asunto **confidencial** que la persona no puede ver solo se avisa de que existe, sin título ni cliente. También hay una pantalla de consulta suelta (Gabinete → Conflictos de intereses).
- **Vistas**: agenda por despacho y calendario `.ics` descargable de los señalamientos previstos.
- **Provisión de fondos**: movimientos (provisión, suplido, cargo de honorarios, devolución) y saldo por asunto; aviso en el panel si baja de la provisión mínima configurada.
- **Minutas**: borrador desde las horas facturables sin facturar (con el redondeo a bloques del despacho) y los suplidos pendientes; se pueden añadir líneas y cambiar IVA y retención (la retención solo se propone si el cliente es empresa); al **emitir** recibe número correlativo `serie-año-nnn`, las horas y suplidos quedan facturados y, si se pide, el total se carga a la provisión; se puede marcar pagada o anular (libera lo facturado y quita el cargo). PDF descargable. El cálculo está en `calcular_minuta` (función pura con tests, redondeo al céntimo).
- **Hoja de encargo**: PDF con los datos del asunto desde la plantilla del despacho, guardado como documento del asunto; «Enviar a firma» la manda a **Documenso** (acción externa: pide confirmación y necesita el token de Documenso del despacho, como el resto de firmas).
- **Enlace para el cliente**: página pública de solo lectura (`/asunto/<token>`, sin cuenta) con el estado en lenguaje llano, el resumen escrito, las próximas vistas y los documentos que el despacho haya **compartido** uno a uno. No muestra horas, notas internas, plazos ni partes contrarias. El token (32 bytes aleatorios) se muestra una sola vez y en la base solo queda su huella SHA-256; caduca (30 días por defecto), se puede revocar, deja de funcionar si el despacho pierde el módulo o el asunto va a la papelera, y la página lleva `no-store`, `noindex` y `Referrer-Policy: no-referrer` y está limitada a 60 peticiones por minuto.
- **Pendiente**: mensajes seguros con el cliente, asistente de IA y herramientas MCP/API del módulo (Día 6), LexNET y el resto de «después del MVP».
- Requiere reiniciar `guilda-work` y `guilda-backoffice` (tablas `abogados_*` y columna `documentos.compartido_cliente`).

## Módulo Inmobiliaria (Día 5 del plan maestro)
- **Qué es** (`app/inmobiliaria.py`, pantallas en `app/rutas_inmobiliaria.py` y `app/templates/inmobiliaria*`): el módulo de negocio para agencias inmobiliarias, sobre el núcleo común. Se activa por agencia (backoffice → despacho → Módulos, o con un extra de pago vinculado); sin él `/inmobiliaria/…` da 404 y el menú no lo ofrece. Los porcentajes, el IVA y los textos de los contratos son **de ejemplo y están marcados «sin validar»**; se editan en **Inmobiliaria → Ajustes** (solo responsables).
- **Un inmueble es una operación**: al dar de alta un inmueble se crea un expediente de *venta* o *alquiler* para su propietario (que es un cliente del núcleo) y su ficha de inmueble. Las **fases** del embudo son los estados del expediente (Primer contacto → Valoración → Mandato firmado → Publicado → En visitas → Con oferta → Reservado/arras → Cerrada / Perdida), así que plazos, horas, documentos, línea de tiempo y confidencialidad son los de siempre. El estado comercial (en captación, en venta, reservado, vendido…) se **calcula** de la fase; no se guarda aparte.
- **Pantallas**: panel (cartera, visitas de hoy, ofertas por responder, inmuebles sin movimiento en 14 días), **tablero de captación** por columnas con un selector de fase en cada tarjeta, listado con filtros, demandas, agenda de visitas y ajustes. Las acciones sobre un inmueble están en el panel de su ficha de expediente (el núcleo lo incluye sin conocer el módulo).
- **Demandas y cruce explicable** (`puntuar`, función pura con tests): puntúa de 0 a 100 un inmueble frente a una demanda —tipo 20, zona 25, precio 30 (mitad si supera el máximo en menos de un 10 % o no llega al mínimo), superficie 10, habitaciones 10, baños 5; cada «imprescindible» que no tiene resta 8— y devuelve cada razón con sus puntos. Solo se cruzan inmuebles **en comercialización** (Publicado, En visitas, Con oferta) de la misma operación, y por debajo de 50 puntos no se sugiere. Se ve desde la demanda y desde el inmueble.
- **Visitas y ofertas**: se programan con o sin demanda (crean una tarea para el agente), se registra el resultado con valoración de 1 a 5, interés y comentario, y la agenda agrupa por día con enlace al mapa (OpenStreetMap). Las ofertas tienen estados (pendiente, contraoferta, aceptada, rechazada, retirada).
- **Contratos desde plantilla**: mandato de venta, arras, alquiler y reserva, con variables del inmueble y de las partes. Cada generación es una **versión nueva** (la anterior se conserva como documento de la operación), se puede enviar a firma con Documenso (acción externa con confirmación) y marcarse como firmada. Los modelos de ejemplo son cortos y sin validar: sustitúyelos por los de la agencia.
- **Comisiones**: propuesta con los ajustes de la agencia (venta: porcentaje del precio; alquiler: mensualidades de renta; mínimo e IVA), cálculo en puntos básicos y **reparto entre agentes que no pierde ni un céntimo** (el resto del redondeo va a quien más decimales tenía); estados prevista, facturada y cobrada.
- **Fotos**: se comprueba que son imágenes de verdad, se reducen a 1600 px, se guardan como JPEG y se les **eliminan todos los metadatos (EXIF, incluida la ubicación GPS)**. Hasta 30 por inmueble; se sirven solo a quien puede ver la operación.
- **Portal del propietario**: página pública de solo lectura (`/propietario/<token>`, sin cuenta) con la fase en lenguaje llano, el precio, un resumen de visitas y ofertas **sin los datos personales de los interesados**, el historial de precios, el informe del mes en PDF y los documentos que la agencia comparta uno a uno. No muestra comisiones, notas internas, horas ni otras demandas. Misma seguridad que el enlace del cliente de Abogados (`app/enlaces_publicos.py`): token aleatorio con huella SHA-256 en la base, mostrado una sola vez, caducidad, revocación, `no-store`/`noindex`/`no-referrer` y 60 peticiones por minuto.
- **Publicación en portales**: exportación autenticada en JSON (`/inmobiliaria/feed.json`) y CSV (`/inmobiliaria/feed.csv`) de lo que está en comercialización, **sin la calle exacta ni el propietario** (solo municipio y código postal). No hay envío automático a portales.
- **Importes a la española**: `nucleo.importe_a_centimos` lee «250.000» como doscientos cincuenta mil (el punto con grupos de tres cifras es separador de miles), «12.5» como doce con cincuenta y la coma siempre como decimal. Se usa también en Abogados y en la tarifa de horas; antes «1.000» se leía como uno.
- **Refactor de este día**: los enlaces públicos y el envío a firma, que ya tenía Abogados, pasan a módulos comunes (`app/enlaces_publicos.py`, `app/firma_documentos.py`) y Abogados los usa sin cambiar su comportamiento. Un test nuevo impide un «%» suelto en un texto traducible de una plantilla (rompía la página con un error 500).
- **Pendiente**: mensajes seguros con el propietario o el interesado, asistente de IA y herramientas MCP/API del módulo (Día 6: anuncio redactado por IA, resumen de visitas), publicación directa en portales, gestión de alquileres (recibos, fianzas, revisión de renta).
- Requiere reiniciar `guilda-work` y `guilda-backoffice` (tablas `inmobiliaria_*` y `inmobiliaria_enlaces`).

## Día 6 del plan maestro: gestoría, informes, asistente con contexto y móvil
- **Perfil fiscal del cliente** (`app/perfil_fiscal.py`, funciones puras con tests): en *Editar cliente fiscal* se indica el tipo (autónomo, sociedad, particular) y qué hace (presenta IVA, estimación directa, retenciones, alquiler de local). De ahí se **proponen los modelos** (303/390/130/111/115/200) con el motivo de cada uno; solo se aplican si se marca «sustituir los modelos…» al guardar, y al generar vencimientos sin modelos guardados se parte del perfil. Reglas **sin validar**: son un punto de partida.
- **Fechas en inhábil**: toda propuesta de vencimientos (pantallas, API REST, generación masiva y automática) pasa por `nucleo.propuestas_vencimientos_ajustadas`, que desplaza al siguiente día hábil con el calendario del despacho (festivos nacionales de ejemplo + los propios). La pantalla enseña «desplazada desde» y la fecha sigue siendo editable.
- **Semáforo por cliente** en la lista de clientes fiscales: atrasado / vence pronto (7 días) / al día / sin vencimientos, con filtro. Se calcula con una sola consulta (`db.vencimientos_por_cliente`).
- **Informe mensual al cliente** (`app/informe_cliente.py`): PDF con lo presentado en el mes, lo atrasado y lo que vence en 30 días, desde la ficha del cliente («Informe mensual (PDF)»); queda en el registro de accesos. El envío programado por correo **no está hecho** (envía correo real: se hará cuando se decida).
- **Capa común de informes** (`app/informes.py`): cabecera con el nombre del despacho, pie con fecha y «página X / Y», fuente DejaVu (catalán, francés y alfabetos latinos; si no está instalada, Helvetica) y celdas que ajustan el texto. `generador_documentos.tabla_a_pdf/texto_a_pdf` y el PDF de fichajes ya pasan por ella. La constancia de presentación conserva su diseño propio. Los textos de los PDF están en español.
- **Asistente y MCP con el núcleo**: cinco herramientas **de solo lectura** (`listar_clientes_despacho`, `resumen_cliente_despacho`, `listar_expedientes_despacho`, `resumen_expediente_despacho`, `listar_plazos_despacho`), grupo `despacho`, en el chat y en el MCP. Respetan el despacho y la confidencialidad: nunca ven más que la persona. Sirven igual a gestoría, abogados e inmobiliaria (asunto u operación = expediente).
- **Contexto de la ficha abierta**: si se escribe al asistente desde la ficha de un cliente, expediente o cliente fiscal, el prompt le dice cuál es (solo el id; las herramientas comprueban el acceso). No se añade en los turnos de soporte. Evaluación continua ampliada con 6 casos del núcleo (encontró que «ficha» no activaba el grupo).
- **Móvil** (`mobile/`): campo de **código 2FA** en el inicio de sesión (se pide solo si la API contesta `requiere_2fa`, que ahora llega como `ApiException.codigo`), **resumen semanal de fichaje** (horas frente a la jornada contratada y barras por día) y **tareas asignadas / compartidas** con selector de ámbito. Se ejecutó `flutter pub get`, `flutter analyze` (0 incidencias) y `flutter test` (12 pruebas). Flutter está en `/home/guilda/flutter` y necesita `safe.directory` de git: se usó por variables de entorno, sin tocar la configuración global.
- **No hecho**: ausencias y vacaciones en el móvil (no existe aún en el servidor: es el §7.4 del plan), cliente desde el remitente de un correo y enlace cronómetro→horas, módulos con herramientas propias de escritura (la IA solo lee el núcleo), y probar la app en un dispositivo.
- Requiere reiniciar `guilda-work` y `guilda-backoffice` (columna `clientes_fiscales.perfil_fiscal`).

## Día 7 del plan maestro: cifrado de documentos, privacidad, rendimiento y cierre
- **Cifrado de documentos con la clave del despacho** (`app/cifrado_despacho.py`, pantalla en *Seguridad del despacho* del panel de ajustes, solo responsables): cifrado de sobre. Cada despacho tiene un par de claves X25519; la **pública** cifra cada documento (con su propia clave AES-256-GCM) **sin necesitar desbloqueo**, y la **privada** solo existe cifrada con la **frase de paso** (Argon2id, 64 MiB) y con la **clave de recuperación** impresa (se enseña una sola vez, con `Cache-Control: no-store`). Desbloquear deja la privada **solo en memoria del proceso**, 4 horas renovables con el uso; reiniciar `guilda-work` bloquea todos los despachos. Con el despacho bloqueado se puede subir pero no leer: la web responde **423** con una explicación, la API `despacho_bloqueado` y el asistente lo cuenta en vez de devolver vacío.
- **Al activarlo** se cifran también los documentos que ya había (`almacen_documentos.sellar_pendientes`), con `secure_delete` y vaciado del WAL para no dejar restos en claro en el fichero de la base de datos (hay un test que busca el contenido en el fichero). **Las copias de seguridad hechas ANTES de activarlo siguen teniendo los documentos en claro**: cuando el cifrado esté estable, retira las anteriores de Restic.
- **Límites que hay que decir en la política de privacidad**: protege contenido **en reposo y en copias**; el servidor lo ve un instante al entrar y mientras el despacho está desbloqueado. El desbloqueo es **del despacho**, no de una sesión concreta: mientras esté desbloqueado leen las personas autorizadas, el asistente de IA interno y los enlaces de solo lectura. La huella SHA-256 del contenido se guarda en claro (para detectar duplicados). Perder frase y clave de recuperación hace los documentos irrecuperables. **El expediente documental de la ficha fiscal (`cliente_documentos`) y los adjuntos de correo todavía no se cifran.** Hay 5 intentos de frase cada 15 minutos.
- **Registro de accesos**: cada lectura de un documento cifrado (persona, enlace público o asistente) se anota y se ve en la pantalla de cifrado.
- **Asistente y MCP**: `listar_documentos_despacho` y `leer_documento_despacho` (solo texto, CSV y JSON; avisan si el despacho está bloqueado). Quedan en el grupo `despacho`.
- **Privacidad y retención** (`app/rgpd.py`, *Seguridad del despacho → Privacidad y retención*): exportación JSON de todo lo que el despacho guarda de un cliente (respeta la visibilidad de expedientes confidenciales) y **vaciado de la papelera** (documentos, plazos y horas) tras 0/30/90/365 días, con constancia en `registro_rgpd`. **No** borra clientes ni expedientes: arrastran datos de los módulos y plazos legales de conservación que decide cada despacho.
- **Rendimiento** (`scripts/probar.sh --perfil`, ahora con 5.000 clientes, 3.000 expedientes, 4.000 plazos y 6.000 partes de horas): se encontraron y corrigieron dos fallos reales. `/plazos/` pasó de **1.900 ms y 318 consultas a 140 ms y 19** (un `setdefault` recalculaba el calendario completo en cada fila) y `/tiempo/` de **1.090 a 90 ms** (la subconsulta del próximo plazo por expediente no tenía índice: `idx_plazos_expediente`, `idx_partes_expediente`). Tests de regresión en `tests/test_rendimiento_nucleo.py`.
- **Accesibilidad**: las pantallas nuevas entran solas en `tests/test_accesibilidad.py` (reglas WCAG comprobables sin navegador). No se ha hecho una pasada real con lector de pantalla.
- **Despliegue** (en este orden): `pip install -r requirements.txt` en el entorno de producción (nuevas dependencias `cryptography` y `argon2-cffi`), reiniciar `systemctl restart guilda-work guilda-backoffice`, activar los módulos en el backoffice si no lo estaban, y —solo cuando el despacho decida— activar el cifrado desde su pantalla. Nada del cifrado se activa solo.
- **Semana 2 (no hecho)**: correo cifrado, concesiones para MCP/API/Hydra (`guilda:documentos`) y tareas programadas, niveles Laxo/Medio/Estricto sobre metadatos y correo, test de paridad entre niveles, cifrado del expediente documental fiscal y de los adjuntos, rotación de la clave del despacho y partir `db.py`/`mcp_tools.py`.
- Requiere reiniciar `guilda-work` y `guilda-backoffice` (tablas `cifrado_despacho`, `accesos_contenido`, `registro_rgpd` e índices nuevos).

## Semana 2 del plan maestro: accesos de máquinas a lo cifrado, expediente fiscal y rotación de la clave
- **Concesiones** (`app/cifrado_despacho.py`, tabla `concesiones_clave`): la clave privada del despacho **envuelta con un secreto que solo tiene quien accede**; el servidor guarda la envoltura, no el secreto. Se crea con el despacho desbloqueado y sirve **aunque luego esté bloqueado**; revocar = borrar la fila (efecto inmediato). Solo un **responsable** puede darlas.
  - **Token de API / MCP personal**: casilla «Dar acceso a los documentos cifrados» al crear el token en *Mis dispositivos* (el secreto es el propio token). Si el token se revoca o caduca, su concesión deja de valer sola.
  - **Aplicaciones OAuth (Hydra)**: el alcance `guilda:documentos` en la pantalla de consentimiento. Al permitirlo, el despacho debe estar desbloqueado (la pantalla pide la frase) y el secreto de la concesión viaja **dentro del token de acceso** (`ext.guilda_cs`, sobrevive a la renovación). Sin ese alcance, o sin responsable, o con el despacho bloqueado, la aplicación se autoriza **sin** el permiso de documentos. Límite: ese secreto queda en la base de Hydra, en el mismo servidor.
  - **API REST** (área `documentos`): `GET /api/v1/documentos?cliente_id=|expediente_id=` y `GET /api/v1/documentos/{id}/contenido`. Sin clave disponible: **423 `despacho_bloqueado`**, nunca vacío. Un token limitado a otras áreas recibe 403.
  - **MCP**: las herramientas `listar_documentos_despacho` y `leer_documento_despacho` usan la concesión del token; una aplicación OAuth sin `guilda:documentos` no las usa. Cada lectura queda en el registro de accesos con su canal (`api`, `mcp`, `asistente`, `enlace`, `persona`).
  - Pantalla *Seguridad del despacho → Accesos de integraciones*: lista y revoca.
- **Expediente documental de la ficha fiscal** (`cliente_documentos`) cifrado con la misma clave (también al subirlo desde correo). Borrar un documento no necesita la clave. **Sigue sin cifrarse**: adjuntos de correo, documentos que sube el cliente por el portal y justificantes (`vencimientos_fiscales_documentos`).
- **Rotación de la clave del despacho**: *Cambiar la clave del despacho* genera un par nuevo, **re-cifra todo en una sola transacción** (si una fila está alterada no cambia nada), estrena clave de recuperación y **revoca todas las concesiones**. La frase de paso sigue siendo la misma. Cambiar solo la frase no re-cifra nada.
- Guardia en la suite: nada fuera de `app/almacen_documentos.py` y `app/db.py` lee el contenido de las tablas de documentos.
- **Lo que NO se ha hecho** (y por qué): **correo cifrado**. No se trata de cifrar una columna: el correo tiene un índice de texto completo (`correo_fts`), embeddings y reglas que guardan o leen el asunto y el cuerpo **en claro**, y más de una veintena de lecturas en `app/db.py` y `app/correo.py`; cifrar el cuerpo sin rehacer eso dejaría el contenido en claro en el índice. Requiere sustituir el índice por uno en memoria que se construye al desbloquear (como dice §8.1) y es un trabajo propio. Tampoco los **niveles Laxo/Medio/Estricto** (dependen del correo y de cifrar nombres de archivo, que también aparecen en la línea de tiempo del expediente), ni la **concesión de servicio** para tareas programadas (ninguna tarea programada lee hoy contenido de documentos), ni el test de paridad entre niveles, ni partir `db.py` y `mcp_tools.py`.
- Requiere reiniciar `guilda-work` y `guilda-backoffice` (tabla `concesiones_clave`, columnas `cliente_documentos.cifrado/sobre` y `accesos_contenido.tabla`).

## Revisión en el navegador de lo hecho desde el Día 3
Se revisaron en un Chromium sin pantalla (instancia temporal y aislada: base de datos de usar y tirar, Kratos simulado, sin tocar datos ni servicios reales) las pantallas del núcleo, gestoría, Gabinete de abogados, Inmobiliaria y seguridad, a 1280 y 390 px, sin errores de JavaScript ni de CSP. Corregido: casillas de los filtros colocadas encima de su texto (plazos, horas, generar vencimientos); celdas de tabla con `display: flex` que descuadraban la fila de plazos; botones de cabecera pegados al subtítulo; selector de archivos nativo sin estilo (todos los de la aplicación); tablas anchas en móvil sin indicio de que se desplazan; campos de los formularios de datos de los módulos **sin etiqueta visible** (superficie, habitaciones, baños...) y el **panel del módulo, que quedaba casi 900 px por debajo de los plazos y horas genéricos** (ahora va el primero). **No se pudo comprobar**: interacción (clics, selectores con búsqueda, calendario de fechas, arrastre), porque el Chrome conectado es el de tu PC y no llega al servidor; ni la pantalla 423, los enlaces públicos y el PDF en pantalla.

### Prueba de interacción en navegador (`scripts/comprobar_interaccion.sh`)
Recorrido con clics reales (Playwright + Chromium sin pantalla) sobre una **instancia temporal**: copia del repositorio, base de datos desechable con datos de demostración (`scripts/servidor_demo.py`), Kratos simulado y sin tocar datos ni servicios reales; cada ejecución arranca una nueva y la borra al terminar. Necesita Playwright (`PW_PYTHON`, por defecto `/tmp/pw-venv/bin/python`, y `PLAYWRIGHT_BROWSERS_PATH`, por defecto `/tmp/pw-browsers`); no instala nada. Comprueba, además de que no haya errores de JavaScript ni de CSP: selector con buscador (ratón y teclado), calendario propio, alta y cierre de un plazo, registro de horas, tablero de captación, diálogo de confirmación (cancelar y aceptar), notificación con cálculo de plazo procesal, enlace público del cliente y portal del propietario sin sesión (con el PDF), perfil fiscal, informe mensual, exportación RGPD, el ciclo completo del cifrado (activar, clave de recuperación, bloquear, 423, frase incorrecta, desbloquear) y el menú móvil. No sustituye a una revisión visual ni a probar con Kratos, Documenso o correo reales.

## Correo cifrado con niveles (semana 2 del plan maestro)
- **Opcional, por despacho** (`app/correo_cifrado.py`; *Seguridad del despacho → Correo cifrado*, solo responsables): hace falta tener ya activado el cifrado de documentos (misma clave del despacho). Se activa, se cambia de nivel y se desactiva desde esa pantalla; sin activarlo el correo funciona exactamente como siempre (hay un test que lo vigila).
- **Sellado al entrar sin desbloqueo**: el mensaje entra en estado «por sellar» (`cifrado = 2`), pasa por todo lo de siempre en claro (reglas, categorías, vínculo con el cliente fiscal, archivado de adjuntos) y como último paso se sella con la clave **pública** del despacho; por eso también se cifra el correo que llega de madrugada con el despacho bloqueado. Mientras está «por sellar» el índice de texto completo lo ignora (se comprobó que, si no, conservaba el cuerpo en minúsculas para siempre); al sellarse se indexa solo lo que el nivel deja en claro. Al terminar cada sincronización se vacía el WAL de SQLite.
- **Los tres niveles** (se guardan en `cifrado_despacho.nivel`, se eligen al activar y se cambian cuando se quiera; ninguno quita funciones):

  | dato | Laxo | Medio | Estricto |
  |---|---|---|---|
  | cuerpo, HTML y contenido de adjuntos | cifrado | cifrado | cifrado |
  | asunto y nombre de adjuntos | en claro | cifrado | cifrado |
  | remitente, destinatarios, copia | en claro | en claro | cifrado |
  | categoría y cliente fiscal vinculados | en claro | en claro | cifrado |
  | fecha, carpeta, leído, destacado, tamaños | en claro | en claro | en claro |

  El bloque cifrado lleva siempre una copia de todo, así que **subir de nivel solo vacía columnas (sin clave)** y **bajarlo necesita el despacho desbloqueado**. En Medio y Estricto la clave de conversación es un HMAC con la clave del servidor (`GUILDA_SECRET_KEY`), no con la del despacho, para que el hilo siga funcionando sin desbloqueo.
- **Leer**: sesión desbloqueada o concesión (token de API, MCP, aplicación OAuth: las mismas concesiones que los documentos). Sin clave, los campos protegidos salen vacíos con `protegido = true`: la bandeja dice «Protegido: desbloquea para leerlo» con enlace para los responsables, la API y el MCP devuelven `protegido` y un `aviso`, y descargar un adjunto da 423. Las lecturas quedan en el registro de accesos.
- **Buscar**: con correo cifrado la búsqueda por palabras, remitente, asunto, categoría y cliente se hace **en memoria** sobre los mensajes descifrados (caché ligera por despacho, solo mientras haya clave; se olvida al bloquear). Medido con 20.000 mensajes sellados: primera búsqueda ≈ 6 s (descifra), siguientes ≈ 0,4 s, ≈ 230 MB; el tope es de 100.000 mensajes por consulta. Es una búsqueda por palabras, no idéntica al índice de texto completo (sin prefijos).
- **IA y MCP**: `buscar_semantico` completa con una búsqueda por palabras en memoria porque el correo de estos despachos **ya no se manda a Meilisearch ni a los embeddings** (se retira lo que ya hubiera al activar). `leer_correo`, `listar_bandeja_entrada` y `listar_conversacion_correo` devuelven el aviso si está protegido.
- **Adjuntos**: contenido sellado en los tres niveles; el nombre, en Medio y Estricto. Rotar la clave del despacho re-cifra también el correo (en la misma transacción).
- **Test de paridad** (`tests/test_correo_cifrado.py`): el mismo guion —listar, abrir, buscar por cuerpo, asunto, remitente, categoría y cliente, conversaciones, adjuntos, ficha del cliente, herramientas de la IA— con los tres niveles y con sesión desbloqueada o concesión de token, y exige resultados idénticos. Otro test busca en el fichero de la base de datos (y su WAL) el contenido, el asunto, el remitente y los términos en minúsculas.
- **Límites**: el mensaje existe en claro un instante al entrar; lo que se copia fuera del correo (un asunto guardado en un expediente, `cliente_documentos.asunto_origen`), los borradores y los envíos programados no se cifran aquí; el `Message-ID` y las cabeceras de hilo quedan en claro; el buscador global del navegador deja de incluir el correo de estos despachos; cambiar categoría o cliente de un correo en Estricto exige el despacho desbloqueado; las copias de seguridad anteriores a activarlo conservan el correo en claro.
- **Sigue sin hacerse**: la concesión de servicio para tareas programadas (por defecto no existe: las que leen correo ven «protegido»), cifrar nombre y título de documentos y notas según el nivel, y partir `db.py` y `mcp_tools.py`.
- Requiere reiniciar `guilda-work` y `guilda-backoffice` (columnas `correo_mensajes.cifrado/cifrado_nivel/sobre/datos`, `correo_adjuntos.cifrado/sobre/nombre_cifrado`, `cifrado_despacho.correo_activo` y disparadores del índice de texto, que se recrean solos).

### Verificación de la migración del correo cifrado sobre datos reales (12 de octubre)
Sobre copias temporales (instantánea de solo lectura con la API de copia de SQLite, en un directorio `0700` de `/tmp`, **borradas al terminar**; solo se imprimieron recuentos) de la copia de seguridad de las 04:00 —esquema anterior a todo lo de esta semana, 98 tablas, 101 mensajes, 13 adjuntos— y comprobando que la base en producción ya había migrado al reiniciar el servicio:
- **Migración** (`init_db` del código nuevo): 0,4 s; 31 tablas nuevas, 0 filas perdidas, `integrity_check` y `foreign_key_check` limpios, índice de texto íntegro (101 de 101 indexados), los cuatro disparadores recreados.
- **Activar el correo cifrado en Estricto**: 101 mensajes y todos los adjuntos sellados en 0,1 s; con el despacho bloqueado ninguno es legible; desbloqueado se leen y la búsqueda de una palabra real da el mismo número de resultados que sin cifrar; **desactivarlo devuelve el correo idéntico bit a bit** (huella SHA-256 de todos los campos y adjuntos).
- **Búsqueda en bruto en el fichero** (400 palabras reales, en minúsculas, de cuerpos, asuntos y remitentes): antes de cifrar aparecían las 400; después, 24, todas explicadas: nombres del propio esquema y de carpetas, `message_id` (en claro por diseño) y vocabulario de ayuda en el historial del chat. **Esto destapó dos fugas reales que ya están corregidas**: el índice de texto conservaba el cuerpo de los mensajes que entran en claro (ahora «por sellar» no se indexa) y el historial del asistente guardaba en claro los resultados de `leer_correo` y similares (ahora se sellan, también al activar y al rotar la clave).
- **Límites vistos**: los mensajes de la persona y las respuestas del asistente en el historial siguen en claro; las páginas libres de borrados anteriores a activarlo pueden conservar restos hasta que se ejecute un `VACUUM` (la copia de seguridad de hoy tenía 387 páginas libres): si hace falta limpiarlas, `sqlite3 data/registro.db "VACUUM"` con el servicio parado.

## Pendientes de la semana 2 cerrados: concesión de servicio y nombres de documentos por nivel
- **Concesión de servicio** (`cifrado_despacho.activar_servicio`, *Seguridad del despacho → Tareas programadas*): por defecto **no existe** y una tarea que corre sola ve lo cifrado como «protegido». Un responsable, con el despacho desbloqueado, puede autorizar tareas concretas (hoy solo el **seguimiento de respuestas de correo**, que en el nivel Estricto necesita saber quién escribe) durante 1 a 90 días; se revoca al instante y cae sola al caducar o al rotar la clave del despacho. La clave del despacho queda envuelta con una clave derivada de `GUILDA_SECRET_KEY` (fuera de la base de datos): una copia de seguridad sola no la abre, pero quien controle el servidor sí podría; si ese secreto cambia, la concesión deja de abrir nada. El resumen semanal de IA no la necesita (usa la actividad, no correo ni documentos).
- **Nombres de archivo según el nivel** (`documentos` y `cliente_documentos`): en Laxo van en claro; en Medio y Estricto la columna queda vacía y el nombre va sellado (`nombre_cifrado`), y no se copia a la línea de tiempo del expediente («Documento añadido», sin nombre), al registro de accesos del cliente ni al `asunto_origen` de los adjuntos archivados desde el correo. Sin clave se ve «Documento protegido»; con clave, el nombre real. **El nivel es único por despacho** y se cambia en *Estado* (vale para documentos y correo): subir no necesita clave, bajar sí. Rotar la clave re-cifra también los nombres. Los enlaces públicos enseñan el nombre solo si hay clave disponible.
- **No se ha hecho**: cifrar el **título de las notas personales** (son de cada persona, no del despacho, y están en el buscador y en el MCP: es una decisión aparte), los nombres de lo que sube el cliente por el portal, y lo que quedó escrito en claro **antes** de activar (registros de accesos y eventos antiguos).

## `db.py` y `mcp_tools` divididos por dominios (sin cambiar su comportamiento)
- **`app/db.py`** (era de 13.600 líneas) queda con el esquema, las migraciones, la conexión y las constantes (≈ 3.200 líneas) y reexporta todo desde diez módulos de dominio: `db_plataforma` (usuarios, despachos, facturación, tokens, notificaciones, auditoría, webhooks, perfil, papelera), `db_tareas`, `db_historial`, `db_notas`, `db_fiscal` (calendario fiscal, portal, expediente documental), `db_correo`, `db_proyectos`, `db_ia`, `db_tiquets` y `db_fichaje`. **`mcp_tools.py` pasó a ser el paquete `mcp_tools/`**: en `__init__.py` quedan la infraestructura (`_uid`, `_fila`...), el catálogo `TOOLS`, el guardián y el registro; las 253 herramientas viven en `herramientas_*.py` por familia.
- **Cómo se hizo y por qué es seguro**: una herramienta mecánica movió cada función **idéntica** salvo que toda referencia a un nombre del módulo original (funciones, constantes, nombres importados) pasó a `_db.nombre` / `_mt.nombre`. Así el módulo original sigue siendo el único espacio de nombres: `db.nombre` y `mcp_tools.nombre` existen igual que antes y un `monkeypatch` sobre ellos llega a todo el código (los tests parchean `db.now_iso`, `db.datetime`, `mcp_tools._uid`...). Comprobado: los 710 nombres de `db` siguen existiendo; las 165 herramientas MCP tienen el mismo nombre, firma, descripción y orden; la suite completa (2.658) y las medidas de rendimiento son iguales.
- **Para añadir código**: una función nueva va en el módulo de su dominio y, para todo lo que no sea suyo (la conexión, constantes, otras funciones), usa `_db.nombre` / `_mt.nombre`. `tests/test_modulos_de_dominio.py` falla si se usa un nombre del módulo original «a pelo» (solo habría fallado al ejecutar esa función) o si algo movido no se reexporta. `app/db_fiscal.py` está en la lista de ficheros autorizados a tocar las tablas de documentos (`tests/test_almacen_documentos.py`).

## Resumen diario de pendientes (13 oct 2026)

Cada persona puede recibir, en **Ajustes › Perfil › Notificaciones**, un resumen de *sus* pendientes (no del cliente): visitas agendadas hoy, plazos y vencimientos fiscales a ≤ 3 días, tareas atrasadas y de hoy y correos recibidos sin contestar (últimos 14 días, sin respuesta tuya en el hilo; ni automáticos ni pospuestos).

- **Opt-in** (`usuario_perfil.resumen_diario`, apagado por defecto), a partir de la hora elegida (5–20 h, 8 por defecto), **solo de lunes a viernes**, **una vez al día** (`resumen_diario_ultimo`, se marca antes de enviar) y **solo si hay algo pendiente**.
- Llega a la campana y al móvil; por email si está marcado y `PORTAL_SMTP_*` está configurado (a la dirección de la propia cuenta).
- Código: `app/resumen_pendientes.py` (`reunir`, `redactar`, `entregar`, `bucle`); el hilo arranca en `serve.py`. Requiere reiniciar `guilda-work`; las 4 columnas nuevas se crean solas.
- `resumen_del_dia` (asistente/MCP) devuelve además `visitas_hoy`, `plazos` y `correos_sin_contestar` con la misma función.
- **Privacidad**: se arma solo con lo que está en claro; un correo con asunto/remitente sellados aparece como «(correo protegido)» (el hilo de fondo no tiene la clave del despacho). La visita no se cuenta dos veces (su tarea automática se omite).
- Limitación: el texto del resumen sale siempre en español (el hilo no tiene idioma de petición).
- Salud: `resumen_diario` en `/api/v1/health`/vigilante como el resto de hilos.

## Ausencias, vacaciones y permisos (13 oct 2026)

PLAN_MAESTRO §7.4. Código: `app/ausencias.py` (reglas), rutas en `app/rutas_fichaje.py` (`/fichaje/ausencias`, `/fichaje/ausencias/equipo`), API en `app/rutas_api_ampliada.py`, móvil en `mobile/lib/screens/ausencias_screen.dart`. Las 3 tablas nuevas (`ausencias`, `ausencias_saldos`, `ausencias_config`) se crean solas al reiniciar.

- **Pedir**: tipo (vacaciones, asuntos propios, permiso retribuido, baja médica, otro), fechas y motivo; un solo día puede ser medio día. Solo cuentan los **días laborables** (mismo calendario que los plazos: fines de semana, festivos nacionales de ejemplo y los del despacho). No se solapa con otra solicitud viva de la misma persona ni cruza de año.
- **Saldo**: solo las **vacaciones** gastan días. Por defecto 22 al año por despacho (editable) y ajustable por persona y año. Cuentan aprobadas + pendientes.
- **Aprobar**: quien tiene `gestor_fichajes` o es supervisor del despacho (no el superadmin global). Recibe un aviso por la campana/móvil de cada solicitud; la persona recibe el de la resolución. Esa misma gente puede **registrar** la ausencia de otra persona (queda aprobada) y cancelar cualquiera. Cada persona cancela las suyas mientras no hayan terminado.
- **Pantallas**: «Ausencias» en el menú de Fichaje (saldo, formulario, mis solicitudes) y «Ausencias del equipo» (quién falta hoy, cola de aprobación, próximas, saldos y registro).
- **API** (área `fichaje`): `GET/POST /fichaje/ausencias`, `GET /fichaje/ausencias/saldo`, `POST /fichaje/ausencias/{id}/cancelar`, `GET /fichaje/ausencias/equipo` y `POST /fichaje/ausencias/{id}/resolver` (estos dos, solo quien gestiona).
- **Resumen diario**: quien gestiona ve además «Ausencias por aprobar».
- Los mensajes de error del servidor (p. ej. «No te quedan días suficientes») salen en español.

## Turnos, bolsa de horas, herramientas de IA/MCP, backoffice y ayuda (13 oct 2026)

Cierra el §7.4 del plan junto con las ausencias de arriba.

- **Cuadrante de turnos** (`app/turnos.py`, `/fichaje/turnos`): tipos de turno por despacho (nombre, horario —puede cruzar la medianoche—, color; se archivan, no se borran), un turno por persona y día, edición por semana y persona, **copiar semana** (respeta lo asignado y salta ausentes) y aviso a la persona (uno solo por cambio). No se asigna turno a quien tiene una ausencia aprobada ese día, y al aprobar/registrar una ausencia se quitan los turnos que cubría. Lo ve todo el equipo; lo cambia quien gestiona el fichaje (gestor de fichajes o supervisor).
- **Bolsa de horas** (`app/bolsa_horas.py`, `/fichaje/bolsa`): `saldo = trabajado + ajustes − esperado`. Esperado = jornada semanal (Fichaje › Mis datos) / 5 por cada día laborable del calendario del despacho, menos las ausencias aprobadas (medio día = la mitad). Trabajado = misma medida que el resumen semanal (entrada→salida; no se toca el registro horario). Por defecto desde el 1 de enero (o el alta, o el primer fichaje si es posterior) hasta ayer. **Ajustes manuales** (`bolsa_horas_ajustes`) con motivo y aviso a la persona. Sin jornada contratada no hay saldo.
- **API** (área `fichaje`): `GET /fichaje/turnos`, `/fichaje/turnos/cuadrante`, `/fichaje/turnos/tipos` (GET/POST), `POST /fichaje/turnos/asignar`, `GET /fichaje/bolsa-horas`, `/fichaje/bolsa-horas/equipo`, `POST /fichaje/bolsa-horas/ajustes` (la gestión, solo para quien gestiona).
- **IA y MCP** (grupo `fichaje`, 11 herramientas): lectura `listar_mis_ausencias`, `saldo_vacaciones`, `listar_ausencias_equipo`, `ver_mis_turnos`, `ver_cuadrante`, `ver_bolsa_de_horas`; escritura (piden confirmación) `pedir_ausencia`, `cancelar_ausencia`, `resolver_ausencia`, `asignar_turno`, `ajustar_bolsa_de_horas`. Mismas reglas que las pantallas: la IA nunca puede más que la persona.
- **Backoffice**: sección **Personal** en la ficha del despacho (hoy fuera, ausencias pendientes, saldos, bolsa, turnos) y los días de vacaciones por defecto del despacho.
- **Ayuda pública** (`/home/guilda/guilda-help`): artículos nuevos «Ausencias y vacaciones», «Cuadrante de turnos», «Bolsa de horas» (Trabajo diario) y «Resumen diario de pendientes» (Mi cuenta), en es/ca/en/fr; enlazados desde «Fichaje» y «Notificaciones». `generar.py` y `comprobar.py` pasan (43 artículos por idioma). **Compilado en `salida/` pero NO desplegado** a `/var/www/help` (ver `guilda-help/README.md`, apartado «Desplegar»).
- **No hecho**: turnos y bolsa de horas en el móvil, que los turnos alimenten la bolsa de horas (hoy la jornada esperada sale de la jornada semanal, no del cuadrante), avisos automáticos de jornada excedida por turno.

## Certificados digitales (fase B de la especificación de control fiscal, 13 oct 2026)

Primer bloque de la «Especificación de control fiscal y certificados» (RF-07 a RF-12), construido **dentro de Guilda Work** (no como aplicación aparte). Código: `app/certificados.py` (reglas), `app/rutas_certificados.py` + plantillas `certificados*.html` / `certificado_detalle.html` (pantallas, menú Fiscal › Certificados), API `/api/v1/certificados*` (área `certificados`) y 2 herramientas IA/MCP de lectura. Las tablas (`certificados`, `certificados_evaluaciones`, `certificados_vinculos`, `certificados_renovaciones`, `certificados_implantaciones`, `certificados_eventos`, `certificados_avisos`) y la columna `usuarios.custodio_certificados` se crean solas al reiniciar. El hilo de avisos arranca en `serve.py`.

- **Es una capa de control, no custodia claves.** Solo se admite material **público** (PEM/DER). Cualquier archivo que lleve una clave privada (PEM de cualquier tipo, PKCS#8 DER, `.p12/.pfx` reconocido por contenido, no por extensión) se rechaza antes de guardar nada. La misma comprobación (`certificados.contiene_clave_privada`) protege los documentos del despacho, el expediente documental fiscal y los justificantes de vencimientos (nuevo resultado `clave_privada`). Límite de 256 KB y hasta 20 certificados por archivo; ASN.1 corrupto se rechaza sin error 500.
- **Importación**: huella SHA-256 del DER (única por asesoría: importar otra vez, en PEM o DER, no duplica), serie, emisor, sujeto, SAN, fechas en UTC, algoritmo, usos de clave, políticas y NIF **sugerido** (el custodio lo confirma). Si el archivo trae varios certificados identifica la hoja (el que no emite a otro del archivo); si hay varias hojas, hay que elegir (nunca se asume el primero). `Alta manual` guarda solo metadatos con evidencia obligatoria y queda «pendiente de comprobar».
- **Estado en dimensiones independientes**: temporal (calculada, RFC 5280, extremos incluidos, a precisión de instante; hora local de la asesoría + UTC), cadena, revocación y clave (anotadas a mano con fecha; sin comprobar = «no comprobada»), operativa (inventariado → autorizado ↔ suspendido; archivado; sustituido solo al cerrar una renovación) y renovación. El contador de días es informativo.
- **Dependencias** (certificado ↔ cliente ↔ servicio con su autorización) y **riesgos**: obligaciones pendientes a 90 días cuyo certificado caduca antes, está suspendido o no existe («cobertura desconocida», nunca «correcto»).
- **Renovación** (una activa por certificado, índice único parcial): sin_iniciar → en_gestion ⇄ pendiente_titular → obtenido (solo importando el nuevo, con diferencias de identidad y fechas) → validado → implantado (todos los servicios probados con éxito; si no hay servicios, confirmación expresa) → cerrado (el anterior pasa a «sustituido» conservando historial y los servicios se trasladan al nuevo). Una prueba fallida mantiene la renovación abierta. Se abre sola a ≤ 60 días.
- **Avisos** (cada 6 h, idempotentes): 90, 60, 30, 15, 7, 1 días y caducado. Custodio siempre; coordinación (gestores de fichajes + un supervisor) desde 15; dirección (supervisores) desde 7. Decisión: se escala también cuando el certificado no tiene servicios registrados (cobertura desconocida), no solo cuando afecta a servicios. Deduplicados por certificado, umbral, destinatario, canal y fecha de caducidad; si un certificado entra ya dentro de un umbral solo avisa el vigente y los anteriores quedan como «omitido». Canales: campana/móvil y correo (si `PORTAL_SMTP_*`), este último sin datos del certificado, solo un enlace; un envío fallido queda visible y se reintenta.
- **Permisos**: custodios (marca nueva por persona, la pone un supervisor) y supervisores del despacho; el resto no ve nada (403) y el módulo desaparece (404) si el despacho no tiene Gestoría. Cada despacho solo ve lo suyo (probado).
- **No hecho en esta fase**: comprobación automática de cadena y CRL/OCSP (P1), roles de auditor y revisor, oficinas, estados de entrega `planificado`/`encolado`, acuses de avisos y pausas, alerta por una vía independiente del propio servidor, aviso previo al guardar notas con posibles claves (solo se rechazan contraseñas y PIN en los campos de custodia), y migración a `If-Match`. Siguiente en el plan: fase A (cimientos: estados fiscales, unicidades, auditoría unificada, roles) y motor de avisos v2.

### Mejora UX de certificados: alta sin archivo y avisos al cliente (14 oct 2026)

Los certificados **no se suben**: lo principal es apuntarlos en diez segundos. Código: `app/certificados.py` (`alta_rapida`, `editar`, `renovado`, `caducidad_propuesta`, `config`/`guardar_config`, `avisar_clientes`, `pedir_ayuda`), `app/rutas_certificados.py`, `static/certificados.js`, plantillas `certificados.html`, `certificado_detalle.html`, `certificados_avisos.html`, `_certificados_macros.html`, y el portal (`rutas_portal_cliente.py`, tarjeta en `portal_dashboard.html`).

- **Alta rápida** (`POST /certificados/nuevo`, `POST /api/v1/certificados`, herramienta `registrar_certificado`): cliente, tipo (FNMT persona física/representante, DNIe, ACCV, Izenpe, Camerfirma, Firmaprofesional, otro) y caducidad; con la emisión se propone la caducidad habitual del tipo. Titular y NIF se heredan del cliente (un NIF mal escrito en su ficha no bloquea el alta). Apuntar dos veces el mismo no duplica. La importación del archivo público queda como «Avanzado».
- **«Ya está renovado»** (`renovado`, API `/<id>/renovado`, herramienta `renovar_certificado`): el nuevo hereda cliente, tipo, custodio y servicios; el anterior pasa a «sustituido»; si tenía servicios hay que confirmar que el nuevo funciona.
- **Avisos al cliente**, configurables solo por la dirección (`/certificados/avisos`, `GET/PUT /api/v1/certificados/avisos-cliente`): apagados por defecto; días antes (por defecto 60, 30, 15, 7) y después (3), instrucciones de renovación, texto propio con marcas `{cliente} {tipo} {caduca} {dias} {cuando} {despacho} {instrucciones} {enlace}`, vista previa y prueba a uno mismo. Cada aviso se manda una vez por certificado y fecha de caducidad (`certificados_avisos_cliente`); si se apunta ya dentro de un plazo solo se manda el que toca; se reintentan los fallidos; no se avisa sin correo, con ayuda ya pedida, excluido o ya renovado. Por certificado se puede forzar o silenciar. El hilo es el mismo de `certificados.bucle`.
- **Portal del cliente**: si el despacho lo activa, ve su certificado con un lenguaje llano (sin datos técnicos) y un botón «Necesito ayuda para renovarlo» que avisa al despacho.
- Tablas nuevas `certificados_config` y `certificados_avisos_cliente` y columnas `tipo_certificado`, `cliente_titular_id`, `avisar_cliente`, `ayuda_solicitada_en` se crean solas al reiniciar. 125 herramientas IA / 180 MCP.

## Control fiscal — fase E: traspasos y panel (14 oct 2026)

RF-14 y las pantallas «Hoy» y «Cartera» de la especificación, dentro de Guilda Work. Código: `app/traspasos.py` (traspasos y responsable del cliente), `app/panel_fiscal.py` (panel), rutas en `app/rutas_control_fiscal.py` (`/fiscal/panel`, `/fiscal/traspasos`, `/fiscal/clientes/<id>/responsable`), plantillas `fiscal_panel.html` y `fiscal_traspasos.html`, API `GET /api/v1/fiscal/panel`, `GET/POST /api/v1/fiscal/traspasos`, `POST /fiscal/traspasos/<id>/aceptar|rechazar|cancelar` y `PUT /fiscal/clientes/<id>/responsable` (área `fiscal`), y 4 herramientas IA/MCP (`panel_fiscal`, `listar_traspasos` de lectura; `proponer_traspaso`, `resolver_traspaso` de escritura). Tabla nueva `traspasos` y columna `clientes_fiscales.responsable_id` se crean solas al reiniciar. Hilo `traspasos.bucle` en `serve.py` (cada 3 h).

- **Traspaso con aceptación**: se propone (emisor, receptor, oficina de destino opcional, nota con el trabajo pendiente). **Hasta que se acepta no cambia nada**: el responsable anterior conserva el cliente y la visibilidad. Al aceptar (solo el receptor o la dirección), en una transacción, cambian responsable y oficina, el receptor recibe una concesión de gestión si no vería el cliente, y queda auditado. Rechazar exige motivo; cancelar, quien lo propuso, el responsable o la dirección. Un solo traspaso pendiente por cliente (índice único parcial; 409 en la API). Concurrencia con `version` (`If-Match` → 412).
- **Escalado**: si un traspaso sigue sin aceptar y hay una obligación activa que vence en menos de 7 días, se avisa una sola vez a la dirección, al emisor y al receptor (`escalado_en`).
- **Responsable del cliente** sin traspaso (alta o corrección): dirección o coordinación de la oficina del cliente; no se puede con un traspaso pendiente.
- **Panel** (todo el que tenga el vertical de gestoría; el ámbito es el de cada persona: con oficinas solo sus clientes y los compartidos): vencidas, próximas (7 días), bloqueadas, para revisar (quien puede autorizar), traspasos sin aceptar y riesgos de certificados (solo custodios y supervisores). Cada elemento trae su causa y un enlace de acción. Reparto por responsable y por oficina. Indicadores con **muestra y exclusiones**: obligaciones vencidas en 90 días presentadas en plazo (sin muestra → «Sin datos», nunca 100 %), clientes sin responsable, bloqueadas, presentadas sin evidencia, certificados con custodio. Un panel no promete ausencia de sanciones.
- **No hecho**: expedientes unificados (RF-13), acciones masivas con previsualización, claves de idempotencia, catálogo global de reglas (fase D), métricas de renovaciones implantadas a tiempo.

## Control fiscal — fase A: cimientos (13 oct 2026)

Segundo bloque de la «Especificación de control fiscal y certificados», dentro de Guilda Work. Sin cambiar lo que ya funcionaba: todo es aditivo y el comportamiento de siempre sigue siendo el predeterminado.

- **Migración** (`app/fiscal_base.py`, al reiniciar; idempotente; verificada sobre una copia de la base real: 0 filas perdidas, integridad y claves foráneas correctas). Nunca falla por datos antiguos: si hubiera duplicados, el más antiguo se queda y los demás se marcan (cliente: «duplicado autorizado por la migración»; vencimiento: vinculado como rectificación).
- **Identificación fiscal** (`app/fiscal_identidad.py`): NIF/NIE/CIF con dígito de control, normalizados, y **un cliente por asesoría y país**. Solo se impone cuando el NIF es válido (un valor de relleno como «B123» no cuenta). El duplicado se rechaza con el cliente existente en el mensaje (web, API 409 `cliente_duplicado`, MCP); una excepción documentada (`nif_duplicado_autorizado`) lo permite. Restaurar de la papelera no puede crear un duplicado.
- **Obligaciones** (`app/obligaciones.py`): un vencimiento por cliente + modelo + período (salvo rectificaciones, `rectifica_a`). Nueva **fase de trabajo** (`pendiente → en_preparacion → en_revision → aprobada → presentada → cerrada`; `no_aplica` y `anulada` con justificación, que sacan la obligación de las listas y se deshacen restaurándola de la papelera). El `estado` de siempre es la proyección de la fase (presentada y cerrada = «presentado»), así que pantallas, API, recordatorios y portal no cambian. `vencida`, `en_riesgo`, `bloqueada` y `presentada_tarde` son indicadores, no fases. **Flujo flexible por defecto** (se puede presentar desde cualquier fase); **estricto** por despacho (`/fiscal/flujo`, solo dirección): revisión y aprobación obligatorias, también para el botón «Presentado», el formulario de edición, la API y las herramientas de IA/MCP. «Exigir justificante» bloquea presentar y cerrar sin él. Una presentación a mano se anota como **declarada por el gestor** (`obligaciones_evidencias`), nunca como confirmada. Devolver a preparación exige motivo y avisa a quien la preparaba; poner una obligación en revisión avisa a quien revisa.
- **Concurrencia**: columna `version` en clientes y obligaciones (sube con cada cambio). Web: el formulario lleva la versión y rechaza guardar sobre una más nueva. API: `If-Match: "<version>"` (o `version` en el cuerpo) → **412 `version_obsoleta`** en `PUT /fiscal/clientes/{id}`, `PUT /fiscal/vencimientos/{id}` y `POST …/transiciones`; es opcional (quien no la manda funciona como antes).
- **Auditoría unificada** (`app/auditoria.py`, `/fiscal/auditoria`, `GET /api/v1/fiscal/auditoria`): una sola tabla de eventos que se escribe **en la misma transacción** que el cambio (obligaciones, certificados, oficinas, roles, concesiones, configuración). Solo de anexado: dos disparadores impiden `UPDATE` y `DELETE`; la única puerta es borrar el despacho entero. **No es inmutabilidad criptográfica**: quien administre la base de datos puede quitar los disparadores (para eso, las copias Restic aparte).
- **Oficinas y roles** (`app/acceso.py`, `/fiscal/oficinas`, API `/fiscal/oficinas|membresias|concesiones`): oficinas por despacho, oficina principal de cada cliente y roles con alcance (coordinador de oficina, gestor, revisor fiscal, auditor; la dirección son los supervisores). Sin oficinas, todo el equipo ve todo como siempre; con ellas, cada persona ve lo de sus oficinas, lo que se le comparta (con vigencia, a una persona o a una oficina) y, con rol de toda la organización, todo. **Los clientes sin oficina asignada los ve todo el equipo** hasta que se asignen. El auditor solo lee (web, API y herramientas). El filtro está en la **capa de datos**, no solo en las pantallas: listas, fichas, vencimientos, conteos, documentos, papelera, calendario, exportaciones, API, IA y MCP; el buscador global deja de incluir clientes y vencimientos fiscales a quien no ve todos. Las tareas del sistema (recordatorios, generación automática) no se filtran. Una oficina con clientes no se archiva.
- **No cubierto todavía**: los clientes y las tareas **del núcleo** (ficha de cliente, expedientes) no usan oficinas (solo el módulo fiscal); las notas y tareas personales que mencionan un cliente fiscal enseñan su nombre a su dueño; el aviso a quien coordina («oficinas y permisos») no está en el menú (se entra por la dirección o por URL); el filtro de oficinas se recuerda 30 s por proceso (el servidor MCP puede tardar ese tiempo en enterarse de un cambio); la auditoría no incluye aún lecturas sensibles ni exportaciones.
- **Decisiones del propietario** (13 oct): hay despachos con varias oficinas; **las reglas fiscales las valida el propietario desde su gestoría**, así que el catálogo de reglas (fase D) será **de la plataforma** y lo aprobará él, no cada despacho.

## Catálogo de reglas fiscales y laborales (backoffice)

Las fechas de los modelos fiscales (303, 130, 111, 115, 390, 200…) y las reglas laborales (TC, 190, plazos de alta, baja y contrato) son **datos de la plataforma** que escribe y aprueba el propietario en el backoffice (**Reglas fiscales** y **Reglas laborales**), con versiones y auditoría (`auditoria_eventos`, entidades `regla_fiscal` y `regla_laboral`). Código: `app/reglas_fiscales.py` y `app/reglas_laborales.py`.

- **Reglas fiscales**: al arrancar se siembra como versión 1 ya aprobada cada modelo que figure en `app/vencimientos_fiscales.py:MODELOS_POR_PAIS` y no tenga filas (idempotente; nunca pisa lo que haya cambiado el propietario). Por eso nada cambia hasta que se edita algo. Cada cambio crea una versión **sin aprobar**; la vigente es la última aprobada. «Modelo en uso» desmarcado y aprobado retira el modelo del catálogo. Un cambio solo afecta a los vencimientos que se generen después: los ya generados conservan su fecha. Si la base de datos falla, el calendario sigue con los valores del código.
- **Reglas laborales**: vacías al instalar; mientras no se aprueban, no se genera ningún vencimiento laboral. El botón «Cargar valores habituales como borrador» (`reglas_laborales.cargar_propuestas`) crea, solo para las reglas sin ninguna versión, un borrador con los plazos habituales y la regla escrita en la nota; nunca aprueba, así que no cambia nada hasta que el propietario revisa y aprueba cada una. Los vencimientos `NOMINAS`, `ALTA-SS`, `BAJA-SS` y `CONTRATO` son internos: no se muestran en el portal del cliente ni le generan recordatorios.

## Importar clientes desde Excel o CSV

En Clientes, la dirección y la coordinación del despacho ven «Importar desde Excel o CSV» (`/clientes/importar/`, `app/importador_clientes.py` y `app/rutas_importar_clientes.py`). Se sube un `.xlsx` o un CSV (UTF-8 o Windows-1252; separador coma, punto y coma o tabulador) de hasta 5 MB y 5.000 filas, con los nombres de las columnas en la primera fila: se reconocen por su nombre (nombre o razón social, NIF/CIF, email, teléfono, dirección, tipo, idioma, etiquetas, notas, origen y país) y se pueden reasignar a mano. Antes de crear nada se enseña qué hará con cada fila: nuevo, repetido (mismo NIF, correo o nombre que un cliente ya existente o que otra fila del archivo; se omite) o con error (p. ej. sin nombre). Cada fila se valida por separado, los clientes se crean con la misma ruta que el alta manual (`alta_cliente.crear_cliente_completo`, con gestión fiscal opcional, tipo de cliente fiscal y etiqueta común para encontrarlos juntos) y el resultado queda en la auditoría (`clientes.importados`).

El archivo leído se guarda en `data/importaciones/<id>.json` (modo 600, ligado al despacho y a la persona que lo subió) y caduca a las 2 horas; el paso de crear es de un solo uso, así que reenviar el formulario no duplica. Un `.xlsx` se rechaza si abierto ocuparía más de 60 MB. No hay variables de entorno nuevas.

## Hoy: la bandeja única de lo que necesita a cada persona

`/hoy/` (`app/bandeja_hoy.py`, `app/rutas_hoy.py`) junta en una pantalla lo que cada módulo ya calcula para la persona que entra: sus tareas vencidas y de hoy, los correos sin contestar, los plazos que vencen en la próxima semana, los vencimientos fiscales que lleva (los vencidos de cualquiera, si supervisa), los mensajes de clientes o propietarios sin leer (con las mismas reglas de visibilidad de los expedientes confidenciales), las visitas de hoy (inmobiliaria), los clientes que le quieren traspasar, las ausencias por aprobar y los certificados caducados o que caducan en 30 días (solo quien gestiona). Cada elemento se ordena por urgencia (vencido, hoy, esta semana) y lleva el enlace a donde se resuelve; las secciones vacías no aparecen. El inicio enseña los más urgentes que no son tareas (esas ya salen en «Mi día») en «Necesita tu atención», con enlace a la pantalla completa: el panel se pide después de cargar la página (`/hoy/destacados`, `static/hoy_inicio.js`) para no sumar consultas al inicio, y la barra lateral tiene su entrada «Hoy». Es de solo lectura y no guarda nada. Los avisos con acuse y escalado (`app/avisos.py`) todavía no forman parte de esta bandeja.

## Barra lateral a medida y fichas con una sola fila de pestañas

Cada persona puede personalizar su menú lateral en Ajustes › «Barra lateral y accesos directos» (`/ajustes/menu/`, `app/navegacion.py`, `app/rutas_menu.py`): ocultar lo que no usa (Notas, Tiquets, Fichaje, Videollamadas, Herramientas, Asistente IA, Histórico, Estadísticas, Papelera, Importar) y fijar hasta 6 accesos directos en un bloque «Accesos directos» bajo Inicio. Lo esencial (Hoy, Tareas, Correo, Clientes y la gestoría) no se puede ocultar, lo oculto sigue en el buscador (Ctrl K) y en esa pantalla, y «Restablecer» devuelve el menú de serie. Las preferencias son un JSON en `usuario_perfil.menu_prefs` (columna nueva, migración automática) que viaja con el perfil que ya se lee para pintar el menú, así que no suman consultas; son solo de esa persona. Un acceso fijado a algo que el despacho ya no lleva (p. ej. el panel fiscal sin gestoría) no se enseña, pero la preferencia se conserva. En la ficha de un cliente o de un expediente desaparece la fila de pestañas del núcleo (Clientes/Expedientes/Plazos/Horas, que repetía el submenú lateral) y queda un enlace «‹ Clientes» o «‹ Expedientes» sobre las pestañas propias de la ficha.

## Facturación conectada con los expedientes

La facturación sigue siendo FacturaScripts (un contenedor por despacho); `app/facturacion_despacho.py` y `app/rutas_cobros.py` la conectan con el trabajo del despacho sin duplicarla. En la ficha de un expediente, un panel «Facturación» (solo si el despacho tiene FacturaScripts configurado) permite emitir una factura de una línea (concepto e importe sin IVA; el IVA lo aplica FacturaScripts) para el cliente del expediente, con casilla de confirmación obligatoria. Pueden hacerlo la dirección y la coordinación, y quien lleva el expediente; el cliente necesita gestión fiscal activada y estar vinculado con FacturaScripts (si no, el panel lo explica y enlaza a su ficha). La factura se crea en FacturaScripts, la relación expediente → factura se guarda en `facturacion_expedientes` (se borra con el expediente o el despacho), el expediente anota el hecho y la auditoría registra `factura.creada`. El estado (cobrada, pendiente, vencida) no se copia: se lee siempre de FacturaScripts con una caché de 2 minutos para no llamarla en cada pantalla, y si FacturaScripts no responde esta parte se calla sin romper nada. La pestaña Fiscal de la ficha del cliente suma facturado, cobrado, pendiente y vencido, con el estado de cada factura, y «Hoy» incluye «Facturas vencidas sin cobrar» (todas para la dirección y la coordinación; para el resto, las de los expedientes que llevan). No se envían todavía avisos por correo ni notificaciones push de impagados.

## Facturas para contabilizar y fichero de enlace de a3 (SUENLACE.DAT)

**Es un módulo propio (`contabilizacion`, aparte de la Gestoría aunque se apoye en sus clientes fiscales) pensado como extra de pago, con cobro por uso según tier más adelante.** Se activa por despacho como cualquier módulo de negocio: extra de pago vinculado (`extras_guilda.vertical_id`) o a mano desde el backoffice (Tenant › Módulos); sin él, `/contabilidad/` y «Mis facturas» del portal dan 404. Tiene su propia entrada en la barra lateral y su ficha del cliente enlaza a él cuando está activo. El backoffice enseña el uso del mes de cada despacho (facturas anotadas, cuántas desde el portal y con archivo, y facturas y ficheros exportados): `facturas_contables.uso_del_mes`, la medida sobre la que se podrá cobrar.

Con el módulo «Contabilización de facturas», «Facturas para contabilizar» (`/contabilidad/`, `app/facturas_contables.py`, `app/rutas_contabilidad.py`) recoge los datos de las facturas de los clientes del despacho, emitidas y recibidas (fecha, número, proveedor o cliente con su NIF, una línea por tipo de IVA con recargo y retención, suplidos, abono) para evitar teclearlas en a3 a última hora de cada trimestre. Cada factura pasa por `pendiente` → `revisada` (no se puede marcar si hay problemas: falta el código de empresa de a3 o el NIF, un abono no indica la factura que rectifica, una cuota no cuadra con base × porcentaje o el total no cuadra) → `exportada`; `descartada` la saca del circuito. Cada cliente se configura con su código de empresa de a3 (hasta 5 dígitos), los dígitos de sus subcuentas y las cuentas por defecto (proveedores y clientes genéricos, gasto 62900000, ingreso 70000000, IVA soportado 47200000, repercutido 47700000, retenciones 47510000); la subcuenta de un proveedor o cliente escrita en una factura se recuerda por su NIF. «Generar SUENLACE.DAT» toma las facturas revisadas aún no exportadas (de un trimestre o de todas las fechas), las marca como exportadas y guarda el lote para volver a bajarlo en «Ficheros generados». En a3 se importa desde Utilidades › Importar/Exportar › Enlace contable.

`app/enlace_a3.py` escribe el fichero siguiendo el documento oficial de Wolters Kluwer «Enlace de entrada en a3asesor Eco y a3asesor Con para el SII» (descripción de registros 9.80): ASCII secuencial de registros de **512 bytes** (510 caracteres más CR LF, Latin-1) con constante `5` en la posición 1 y moneda `E` / indicador `N` en las 509-510. Por factura, un registro de cabecera tipo 1 (tipo 2 si es abono) con el tercero (NIF, nombre, país y tipo de documento si el NIF es español), un detalle tipo 9 por tipo de IVA (marca `M`/`U`, `C`/`A`, base, IVA, recargo y retención, cuenta de IVA soportado en las posiciones 192-203 o repercutido en las 228-239, cuenta de retención en las 216-227) y, en los abonos, el registro tipo 4 obligatorio con el número y la fecha de la factura rectificada. Los importes de los abonos van en positivo, como dice el documento. Un número de factura de más de 10 caracteres va completo (hasta 60) en el campo ampliado del SII (253-312) y resumido (sus 10 últimos caracteres) en las 10 posiciones clásicas. a3 da de alta las cuentas que no existan en el plan al importar. `tests/test_enlace_a3.py` fija cada campo en su posición oficial. **Antes de usarlo en una empresa real, importa un primer fichero en una empresa de pruebas de a3 y pásalo por el botón «Chequeo» del propio enlace**, que valida el fichero línea a línea. Los clientes pueden anotar sus facturas ellos mismos desde el portal («Mis facturas», `/portal/facturas`, `crear_desde_portal`): tipo, fecha, número, proveedor o cliente con NIF, **total con IVA** y tipo de IVA (la plataforma lo desglosa en base y cuota), con casilla para avisar de que lleva retención o varios tipos de IVA y foto o PDF opcional (hasta 8 MB, guardado en los documentos del cliente y sellado con la clave del despacho si la tiene). La factura queda `pendiente` con origen «portal» y una nota si hace falta completarla; se avisa a quien lleva al cliente (o, si nadie, a la dirección y la coordinación) y el cliente solo ve fecha, número, tercero, total y un estado sencillo. De momento no incluye registros de vencimientos (tipo V, cobros y pagos), de distribución analítica, de comentarios (tipos 3, 5 y 6) ni la subida de facturas por parte de los clientes desde el portal.
