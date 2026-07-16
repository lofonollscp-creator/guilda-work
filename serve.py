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

from waitress import serve

from app import db
from app.main import app

if __name__ == "__main__":
    if not os.environ.get("GUILDA_SECRET_KEY"):
        raise SystemExit(
            "Falta la variable de entorno GUILDA_SECRET_KEY. Genera una con "
            "`python -c \"import secrets; print(secrets.token_hex(32))\"` y "
            "fíjala antes de arrancar este servidor."
        )
    db.init_db()
    host = os.environ.get("GUILDA_HOST", "0.0.0.0")
    port = int(os.environ.get("GUILDA_PORT", "8000"))
    serve(app, host=host, port=port)
