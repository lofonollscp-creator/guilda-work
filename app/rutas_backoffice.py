"""El backoffice vive ahora en su propia aplicación (paquete `backoffice/`,
https://backoffice.guildawork.com). Este módulo solo conserva las URLs
antiguas `/backoffice/...` de esta app para que los marcadores sigan
funcionando: redirigen (solo GET) a la pantalla equivalente del nuevo."""
import os

from flask import Blueprint, abort, redirect

BACKOFFICE_URL = os.environ.get("GUILDA_BACKOFFICE_URL", "https://backoffice.guildawork.com").rstrip("/")

backoffice_bp = Blueprint("backoffice", __name__, url_prefix="/backoffice")

# Rutas de la pantalla antigua cuyo nombre cambió en el backoffice nuevo.
_EQUIVALENCIAS = {
    "": "/", "resumen": "/", "auditoria": "/actividad", "backups": "/copias",
    "monitorizacion": "/estado", "catalogo-herramientas": "/herramientas",
}


@backoffice_bp.app_context_processor
def _inyectar_url_backoffice():
    return {"backoffice_url": BACKOFFICE_URL}


@backoffice_bp.route("/", defaults={"resto": ""})
@backoffice_bp.route("/<path:resto>")
def redirigir(resto: str):
    resto = resto.strip("/")
    if resto in _EQUIVALENCIAS:
        destino = _EQUIVALENCIAS[resto]
    elif resto.startswith(("tenants", "usuarios", "planes", "leads", "solicitudes-portal", "webhooks", "ingresos", "salud", "diagnostico", "mapa")):
        destino = "/" + resto
    else:
        abort(404)
    return redirect(BACKOFFICE_URL + destino, code=302)
