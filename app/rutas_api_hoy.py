"""API: `GET /hoy`, la bandeja única de lo que necesita a la persona (app móvil, Ola 1 del plan: S-01).

Es la misma bandeja que la web (`app/bandeja_hoy.py`), con el despacho activo de la petición (`X-Despacho`) y, en cada elemento, un `destino`
tipado (`{tipo, id, ...}`) en lugar de depender de la URL de la web: la app navega por él. Una sola llamada para la pantalla inicial.

Se registra importándola desde `rutas_api_extras.py` (que `main.py` ya carga)."""
from datetime import datetime

from flask import g

from . import bandeja_hoy
from .auth import token_required
from .rutas_api import _ok, api_bp


@api_bp.route("/hoy", methods=["GET"])
@token_required
def hoy():
    """Lo que necesita tu atención hoy, de todos los módulos del despacho activo, por urgencia (`vencido`, `hoy`, `proximo`, `info`). Las secciones de módulos
    no activos o sin nada pendiente no aparecen. Cada elemento lleva `destino` (`{tipo, id}`: `tarea`, `correo`, `vencimiento`, `plazo`, `expediente`, `visita`,
    `traspaso`, `ausencia`, `factura`, `contabilizacion` —id del cliente fiscal— o `certificado`) y las `acciones` que la app puede ofrecer sin abrirlo."""
    supervisor = bool(g.get("supervisor_tenant") or g.get("es_admin"))
    datos = bandeja_hoy.reunir(g.usuario_id, supervisor, tenant_id=g.tenant_id)
    return _ok({**datos, "despacho_id": g.tenant_id, "generado_en": datetime.now().isoformat(timespec="seconds")})
