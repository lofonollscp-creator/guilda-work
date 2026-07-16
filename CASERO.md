# Hosting casero con Tailscale Funnel

Guía para dejar `serve.py` (la API REST de la Fase 2) accesible desde
internet **sin pagar nada, sin abrir puertos en el router y sin necesitar
un dominio propio** — usando tu propio PC como servidor. Es el punto de
partida recomendado antes de plantearte un VPS de pago (ver
[`HOSTING.md`](HOSTING.md)): además de ser gratis, corre sobre el mismo
`data/registro.db` que ya usa la app de escritorio (`GuildaWork.exe`), así
que la futura app móvil vería exactamente los mismos datos sin tener que
sincronizar nada.

Por qué Tailscale Funnel y no "abrir el puerto 443 en el router" +
DNS dinámico de toda la vida: muchos ISP residenciales en España (fibra de
Movistar, Vodafone, O2...) usan **CGNAT** (tu router no tiene una IP
pública propia, la comparte con otros clientes del ISP), lo que hace
imposible el port-forwarding tradicional sin ni siquiera darte cuenta de
por qué no funciona. Tailscale Funnel abre siempre una conexión *saliente*
desde tu PC hacia la red de Tailscale, así que funciona igual haya o no
CGNAT — y de regalo te da HTTPS automático y una URL estable, sin
gestionar certificados a mano.

## Antes de empezar

Este cambio hace que `serve.py` sea accesible desde fuera de tu casa. Es
la misma API que ya probamos con `curl` en local, con las mismas
protecciones (autenticación por token, límite de intentos en login) — pero
merece la pena que lo sepas antes de activarlo: a partir de este punto,
cualquiera con la URL podría intentar registrarse o iniciar sesión.

## 1. Comprobar si tienes CGNAT (opcional, informativo)

No bloquea nada de lo de abajo, pero si tienes curiosidad: entra en
`https://www.whatismyipaddress.com` desde el PC y compara la IP que ves
ahí con la IP de tu router (normalmente visible en `192.168.1.1` o el
panel de tu operador). Si son distintas, tienes CGNAT — con Tailscale
Funnel da igual.

## 2. Instalar Tailscale

**Este paso lo tienes que hacer tú**: es un instalador con ventana gráfica
y un inicio de sesión con tu cuenta (Google/Microsoft/GitHub), y no es
algo que deba hacer en tu nombre.

1. Descarga el instalador oficial desde <https://tailscale.com/download/windows>.
2. Ejecútalo e inicia sesión con la cuenta que prefieras (la versión
   gratuita permite hasta 3 usuarios / 100 dispositivos, de sobra para
   esto).
3. Verás el icono de Tailscale en la bandeja del sistema cuando esté
   conectado.

## 3. Activar HTTPS y Funnel en el panel de administración

1. Entra en <https://login.tailscale.com/admin/dns> y activa **"MagicDNS"**
   si no está ya activado.
2. En <https://login.tailscale.com/admin/settings/general>, activa
   **"HTTPS Certificates"** — es lo que permite a Tailscale emitir
   certificados TLS automáticos para tu dispositivo.
3. En <https://login.tailscale.com/admin/acls>, comprueba que Funnel no
   esté bloqueado por la política ACL por defecto (en una cuenta nueva no
   lo está; solo hace falta tocar algo aquí si ya tenías una red Tailscale
   configurada de antes con restricciones).

## 4. Fijar `GUILDA_SECRET_KEY` de forma permanente

Sin esto, cada reinicio de `serve.py` invalidaría todas las sesiones de
cookie activas (no los tokens de la API, que no dependen de esto, pero sí
el login web si alguna vez lo usas remotamente). Genera un valor aleatorio
tú mismo y NO lo compartas ni lo subas a git:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Copia el resultado y fíjalo como variable de entorno de usuario permanente:

```powershell
setx GUILDA_SECRET_KEY "pega-aqui-el-valor-generado"
```

Cierra y vuelve a abrir la terminal para que `setx` tenga efecto.

## 5. Arrancar `serve.py` y publicarlo con Funnel

Desde una terminal en la carpeta del proyecto:

```powershell
python serve.py
```

Por defecto escucha en el puerto 8000 (`GUILDA_PORT`). En **otra**
terminal, publica ese puerto con Funnel:

```powershell
tailscale funnel --bg 8000
```

Te devolverá la URL pública, algo como
`https://tu-pc.tu-tailnet.ts.net` — apunta esa URL, es la que usará la
futura app móvil.

## 6. Dejar `serve.py` corriendo siempre (no solo mientras tengas la terminal abierta)

Opción sencilla, sin instalar nada nuevo — Programador de tareas de Windows:

1. Abre "Programador de tareas" → "Crear tarea básica".
2. Desencadenador: "Al iniciar sesión".
3. Acción: "Iniciar un programa" →
   `C:\Users\Jorge Velasco Sanche\Desktop\ELEGANZA\.venv\Scripts\pythonw.exe`
   con argumento `serve.py` y "Iniciar en"
   `C:\Users\Jorge Velasco Sanche\Desktop\ELEGANZA`.
   (`pythonw.exe`, no `python.exe`, para que no abra ninguna ventana de consola.)
4. En "Condiciones", desmarca "Iniciar la tarea solo si el equipo funciona
   con corriente alterna" si es un portátil.

Con esto, `serve.py` arranca solo cada vez que inicias sesión en Windows.
Si más adelante quieres que se reinicie automáticamente si el proceso
muere (no solo al iniciar sesión), la mejora es instalar
[NSSM](https://nssm.cc/) y registrar `serve.py` como un servicio de
Windows de verdad — no hace falta para empezar.

`tailscale funnel --bg 8000` ya queda persistente por sí solo (Tailscale
lo recuerda entre reinicios de la app), no hace falta repetirlo cada vez.

## 7. Verificar que de verdad es accesible desde fuera de casa

Desde el móvil, **con datos móviles, no con el wifi de casa** (para
probar que de verdad sale a internet y no solo a la red local):

```
https://tu-pc.tu-tailnet.ts.net/api/v1/categorias
```

Debería responder `401` con el JSON `{"ok": false, "error": "Token
inválido o ausente."}` — confirma que el túnel llega hasta la API, aunque
sin token no te deje ver nada (correcto).

## Migrar a un dominio propio más adelante

Cuando tengas un dominio, puedes seguir usando Tailscale Funnel apuntando
un `CNAME` de tu dominio a la URL `.ts.net` (Tailscale lo soporta como
"custom domain" en la documentación oficial), o migrar a la vía VPS de
[`HOSTING.md`](HOSTING.md), donde el dominio se apunta directamente a la
IP del servidor.
