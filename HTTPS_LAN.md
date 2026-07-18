# HTTPS en la red local ("opción 1": servidor casero, sin exponerlo a internet)

Guía para dejar todo el stack (Guilda Work + Kratos/Hydra + Outline +
Element/Synapse) accesible con HTTPS real desde cualquier dispositivo de
tu propia red local (wifi de casa), sin abrir nada a internet — a
diferencia de [`CASERO.md`](CASERO.md) (Tailscale Funnel, acceso desde
fuera de casa) y de [`HTTPS_LOCAL.md`](HTTPS_LOCAL.md) (mock con
`*.localhost`, solo sirve dentro de la propia máquina de desarrollo, ni
siquiera otro dispositivo de la misma wifi lo alcanza — es un TLD
especial que cualquier resolutor trata como loopback).

Identifica el servidor por su **IP en la red local** (no un hostname) —
más simple de montar que mDNS/Bonjour, con la contrapartida de que si el
router reasigna la IP por DHCP hay que actualizar `GUILDA_LAN_IP` (se
recomienda reservar la IP en el router cuando se pase a producción
casera de verdad).

## 1. Averiguar la IP de la máquina en la LAN

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch 'Loopback|vEthernet|WSL' -and $_.IPAddress -notlike '169.254.*' }
```

Usa la de tu interfaz real (Wi-Fi/Ethernet), no las de adaptadores
virtuales (VMware/Hyper-V/WSL).

## 2. Levantar Caddy LAN

```bash
export SQLITE_WEB_PASSWORD=...   # requerido por docker-compose.yml aunque no uses sqlite-web
export GUILDA_LAN_IP=192.168.1.181   # la IP del paso 1
docker compose --profile lan up -d caddy-lan
```

`deploy/Caddyfile.lan` define un puerto por servicio en esa misma IP (no
se puede distinguir por nombre de host al no haber DNS): **8443** Guilda
Work, **8444** Hydra, **8445** Outline, **8446** Synapse (homeserver),
**8447** Element-web.

**Importante**: si `caddy-local` (el mock de `*.localhost`) está
corriendo a la vez, para lo primero — comparten el puerto 8443 y
compiten (síntoma: nada carga, ni por IP ni por `*.localhost`):

```bash
docker compose --profile https-local stop caddy-local
```

## 3. Confiar la CA de `caddy-lan` (una sola vez, en cada dispositivo)

```bash
docker cp guilda-work-caddy-lan:/data/caddy/pki/authorities/local/root.crt ./caddy-lan-root.crt
```

En Windows:
```powershell
certutil -addstore -user Root .\caddy-lan-root.crt
```
Bórralo después (`rm caddy-lan-root.crt`) — se puede volver a extraer
cuando haga falta. En otros dispositivos de la wifi (móvil, otro
portátil) hace falta repetir este paso ahí también para que no salga el
aviso de certificado no confiable — o simplemente aceptar el aviso cada
vez, si es solo para probar.

## 4. Recrear Kratos/Hydra apuntando a la IP

```bash
export GUILDA_ORIGIN="https://192.168.1.181:8443"
export HYDRA_PUBLIC_ORIGIN="https://192.168.1.181:8444"
docker compose up -d --force-recreate kratos hydra
```

## 5. Arrancar `serve.py` con las mismas variables

**No olvides `HERRAMIENTA_OUTLINE_URL`/`HERRAMIENTA_ELEMENT_URL`** — sin
ellas, el enlace de la página de Herramientas sigue apuntando a
`127.0.0.1:puerto` (su valor por defecto para desarrollo), aunque todo
lo demás esté bien configurado (encontrado depurando esta misma guía: el
login del núcleo funcionaba perfecto, pero el botón de Outline seguía
roto por este motivo exacto).

```powershell
$env:GUILDA_SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
$env:GUILDA_ORIGIN = "https://192.168.1.181:8443"
$env:HYDRA_PUBLIC_ORIGIN = "https://192.168.1.181:8444"
$env:HERRAMIENTA_OUTLINE_URL = "https://192.168.1.181:8445"
$env:HERRAMIENTA_ELEMENT_URL = "https://192.168.1.181:8447"
python serve.py
```

Verifica: `https://192.168.1.181:8443/login` — login de Guilda Work.

## 6. Outline en la LAN

```bash
.venv/Scripts/python scripts/registrar_cliente_hydra.py --nombre outline-lan \
  --redirect-uri https://192.168.1.181:8445/auth/oidc.callback
```

```bash
export OUTLINE_PUBLIC_ORIGIN="https://192.168.1.181:8445"
export OUTLINE_FORCE_HTTPS="true"
export OUTLINE_OIDC_CLIENT_ID="..."       # del comando de arriba
export OUTLINE_OIDC_CLIENT_SECRET="..."   # del comando de arriba
docker compose up -d --force-recreate outline
```

## 7. Element/Synapse en la LAN

```bash
cp deploy/synapse/guilda-overrides.lan.yaml.example deploy/synapse/guilda-overrides.lan.yaml
.venv/Scripts/python scripts/registrar_cliente_hydra.py --nombre element-lan \
  --redirect-uri https://192.168.1.181:8446/_synapse/client/oidc/callback
```

Rellena `client_id`/`client_secret` en `guilda-overrides.lan.yaml` y
sustituye las apariciones de `192.168.1.181` por tu IP real. Igual con
`deploy/synapse/element-config.lan.json` (`base_url`).

```bash
docker compose -f docker-compose.yml -f docker-compose.synapse-lan.yml \
  up -d --force-recreate synapse element-web
```

## 8. Volver a la normalidad

```bash
docker compose up -d --force-recreate kratos hydra outline synapse element-web   # sin las variables de arriba exportadas
docker compose --profile lan stop caddy-lan
```

## Verificación — ✅ verificado de principio a fin en dispositivos reales

Probado en la propia máquina y **confirmado desde otro dispositivo de la
misma wifi** (el objetivo real de "opción 1"): login de Guilda Work,
Element (chat nativo, incluida la sala) y Outline, los tres funcionando
sobre HTTPS real con la IP de la LAN.

### Problemas reales encontrados y corregidos en esta sesión

- **Caddy rechazaba conexiones sin SNI** (`internal_error` en el
  handshake) — los navegadores no mandan SNI cuando el destino es una IP
  literal (RFC 6066 solo define SNI para hostnames), y Caddy no sabía
  qué certificado servir aunque solo hubiera uno posible. Arreglado con
  la opción global `default_sni {$GUILDA_LAN_IP}` en
  `deploy/Caddyfile.lan`.
- **Proceso `wslrelay.exe` obsoleto** ocupando el puerto 8443/8444 en
  `127.0.0.1` tras parar `caddy-local` sin limpiar — síntoma:
  `TLSV1_ALERT_INTERNAL_ERROR` incluso después de arreglar el SNI. Se
  soluciona parando el proceso a mano (`Stop-Process`) y recreando el
  contenedor de Caddy — no se ha automatizado, es un efecto secundario
  conocido de Docker Desktop + WSL2 al cambiar mapeos de puertos.
- **`HERRAMIENTA_OUTLINE_URL`/`HERRAMIENTA_ELEMENT_URL` sin exportar**:
  el enlace de la página de Herramientas sigue usando su valor por
  defecto (`127.0.0.1:puerto`) si no se exportan explícitamente al
  arrancar `serve.py` — mismo tipo de olvido ya documentado en
  `HTTPS_LOCAL.md` para el mock de `*.localhost`.
