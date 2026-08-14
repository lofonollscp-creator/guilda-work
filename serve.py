"""Punto de entrada alternativo a run.py para servir Guilda Work con un
servidor de producción (waitress) en vez del servidor de desarrollo de
Flask — pensado para un futuro despliegue accesible desde internet (Fase 3
de la app móvil). No se despliega todavía; esto solo prepara el arranque.

A diferencia de run.py (app de escritorio, pywebview), aquí MODO_ESCRITORIO
se queda en False: cada visitante necesita iniciar sesión de verdad en
/login o /registro.

Variables de entorno:
    GUILDA_SECRET_KEY   Obligatoria para que las sesiones no se invaliden
                        cada vez que se reinicie el proceso.
    GUILDA_HOST         Dirección de escucha (por defecto 0.0.0.0).
    GUILDA_PORT         Puerto de escucha (por defecto 8000).

Uso:
    python serve.py
"""
import os

if __name__ == "__main__" and not os.environ.get("GUILDA_SECRET_KEY"):
    # Comprobado ANTES de importar app.main a propósito: ese import ya
    # ejecuta app/captcha.py y app/correo.py, que sin GUILDA_SECRET_KEY caen
    # a una clave fija de desarrollo (ver sus docstrings) -- pensada para la
    # app de escritorio de un único usuario local, nunca para un servidor
    # expuesto a internet. Cortando aquí, el proceso nunca llega a construir
    # la app con esa clave débil en memoria.
    raise SystemExit(
        "Falta la variable de entorno GUILDA_SECRET_KEY. Genera una con "
        "`python -c \"import secrets; print(secrets.token_hex(32))\"` y "
        "fíjala antes de arrancar este servidor."
    )

from waitress import serve

from app import db
from app.main import app

if __name__ == "__main__":
    db.init_db()
    host = os.environ.get("GUILDA_HOST", "0.0.0.0")
    port = int(os.environ.get("GUILDA_PORT", "8000"))
    # Caddy reenvía aquí por localhost (ver deploy/Caddyfile) mandando
    # X-Forwarded-For/-Proto con la IP/protocolo real del visitante — pero
    # Waitress, por defecto (desde la 3.0), DESCARTA esas cabeceras salvo
    # que se le diga explícitamente en qué proxy confiar (si no, cualquiera
    # que hable directo con este puerto podría falsificar su propia IP).
    # trusted_proxy="127.0.0.1" es justo eso: solo se fía de lo que diga
    # Caddy, nunca de una conexión directa. Sin esto, request.remote_addr
    # (usado por el rate-limit de app/auth.py y por el contador de fallos
    # de login de app/rutas_kratos_proxy.py) veía siempre 127.0.0.1.
    serve(
        app, host=host, port=port,
        trusted_proxy="127.0.0.1",
        trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto"},
        clear_untrusted_proxy_headers=True,
    )
