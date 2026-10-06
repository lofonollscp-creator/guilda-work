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
    GUILDA_THREADS      Hilos de waitress (por defecto 16; waitress trae 4).
    GUILDA_CORREO_SYNC_MINUTOS  Cada cuántos minutos se sincroniza el correo de
                        todas las cuentas (por defecto 5; 0 lo desactiva).

Uso:
    python serve.py
"""
import os
import threading

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
from app.main import (
    _avisos_fichaje_servidor, _envios_correo_servidor, _recordatorio_vencimientos_fiscales, _recordatorios_portal_servidor,
    _resumen_ia_semanal,
    _sincronizacion_correo_servidor, _vigilante_salud_servidor, app,
)

if __name__ == "__main__":
    db.init_db()
    # A diferencia de _sincronizacion_correo_periodica/_recordatorio_periodico
    # (solo pensados para la app de escritorio de un único usuario, nunca
    # arrancados aquí), el recordatorio de vencimientos fiscales y el
    # resumen semanal de IA SÍ son multi-tenant/multi-usuario y tienen que
    # correr en el servidor real -- si no, nunca se ejecutarían en ningún
    # despliegue hospedado.
    threading.Thread(target=_recordatorio_vencimientos_fiscales, daemon=True).start()
    threading.Thread(target=_resumen_ia_semanal, daemon=True).start()
    # Auto-sync del correo de todas las cuentas (GUILDA_CORREO_SYNC_MINUTOS,
    # 5 por defecto, 0 lo desactiva). _sincronizacion_correo_periodica sigue
    # siendo solo de escritorio; esta es su versión multi-usuario.
    threading.Thread(target=_sincronizacion_correo_servidor, daemon=True).start()
    # Cola de envío de correo: "deshacer envío" y envíos programados.
    threading.Thread(target=_envios_correo_servidor, daemon=True).start()
    # Aviso de "salida olvidada" del fichaje (GUILDA_FICHAJE_AVISO_HORAS, 10 por defecto).
    threading.Thread(target=_avisos_fichaje_servidor, daemon=True).start()
    # Recordatorios por correo a los clientes del portal (7 y 2 días antes de cada vencimiento).
    threading.Thread(target=_recordatorios_portal_servidor, daemon=True).start()
    # Vigilante de salud: avisa por correo de lo que esté en rojo en /backoffice/salud.
    threading.Thread(target=_vigilante_salud_servidor, daemon=True).start()
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
        # waitress usa 4 hilos por defecto: con llamadas lentas a Kratos o al
        # correo, 4 usuarios simultáneos bloquean al resto.
        threads=int(os.environ.get("GUILDA_THREADS", "16")),
    )
