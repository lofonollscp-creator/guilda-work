"""Servidor del backoffice (proceso independiente de serve.py). Escucha solo en
127.0.0.1:8001; Caddy lo publica como backoffice.guildawork.com."""
import os

from waitress import serve

from app import db
from backoffice import cartera
from backoffice.main import create_app

if __name__ == "__main__":
    db.init_db()  # idempotente: asegura el esquema de la plataforma que este panel administra
    app = create_app()
    cartera.iniciar_hilo()  # histórico de ingresos, cobros pendientes y resumen semanal
    serve(
        app, host=os.environ.get("BACKOFFICE_HOST", "127.0.0.1"), port=int(os.environ.get("BACKOFFICE_PORT", "8001")),
        trusted_proxy="127.0.0.1", trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto"},
        clear_untrusted_proxy_headers=True, threads=int(os.environ.get("BACKOFFICE_THREADS", "4")),
    )
