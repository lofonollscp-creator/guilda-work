"""Centro de notificaciones unificado: además del push FCM (efímero, solo
llega si el móvil está a mano y con cobertura, ver app/push.py), cada
aviso se registra en la tabla `notificaciones` para que el usuario lo vea
dentro de la propia app -- correo nuevo, vencimiento fiscal próximo,
mensaje del portal de cliente, resumen IA semanal.

Un único punto de entrada, `crear_y_enviar()`, sustituye las llamadas
directas a `push.enviar_a_usuario()` que había en los 4 puntos de emisión
existentes (app/correo.py, app/rutas_portal_cliente.py, app/main.py x2)
-- misma llamada, no dos sistemas paralelos que puedan desincronizarse."""
import json

from . import aviso_destino, db, push


def _despacho_del_aviso(usuario_id: int) -> int | None:
    """El despacho al que pertenece el aviso: el de la petición en curso si es uno de la persona (quien lo emite suele ser de su mismo despacho); si no, el principal."""
    try:
        propios = [d["id"] for d in db.tenants_de_usuario(usuario_id)]
        from flask import g, has_request_context
        if has_request_context() and g.get("tenant_id") in propios:
            return g.tenant_id
        return propios[0] if propios else None
    except Exception:  # noqa: BLE001 -- el despacho es informativo: nunca debe impedir el aviso
        return None


def crear_y_enviar(
    usuario_id: int, tipo: str, titulo: str, cuerpo: str, url: str | None = None, datos: dict | None = None,
    ignorar_silencio: bool = False, despacho_id: int | None = None,
) -> None:
    """Registra la notificación (visible en la propia app) y manda el
    push FCM (visible en el móvil) -- el registro en BD nunca falla en
    silencio como el push (si algo va mal aquí, se quiere saber), pero
    tampoco debe impedir que el push se intente si el registro fallara
    por algún motivo.

    El push lleva siempre el mismo contrato (S-05 del plan de la app móvil): `tipo`, `destino` (JSON `{tipo, id, ...}`, más `destino_tipo`/`destino_id`
    sueltos), `despacho_id`, `notificacion_id` y `canal`; además de lo que ya mandara quien emite."""
    notificacion_id = None
    try:
        notificacion_id = db.crear_notificacion(usuario_id, tipo, titulo, cuerpo, url)
    except Exception:
        pass
    datos = dict(datos or {})
    destino = aviso_destino.destino_de(tipo, datos, url)
    canal = aviso_destino.canal_de(datos.get("tipo") or tipo)
    datos.setdefault("tipo", tipo)
    datos.update({"destino": json.dumps(destino, separators=(",", ":")), "destino_tipo": destino["tipo"], "canal": canal})
    if destino.get("id") is not None:
        datos["destino_id"] = destino["id"]
    if url:
        datos.setdefault("url", url)          # ruta de la web: respaldo de la app cuando el destino aún no tiene pantalla nativa
    despacho = despacho_id if despacho_id is not None else _despacho_del_aviso(usuario_id)
    if despacho is not None:
        datos["despacho_id"] = despacho
    if notificacion_id is not None:
        datos["notificacion_id"] = notificacion_id
    push.enviar_a_usuario(usuario_id, titulo, cuerpo, datos, ignorar_silencio=ignorar_silencio, canal=canal)
