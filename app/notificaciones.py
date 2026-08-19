"""Centro de notificaciones unificado: además del push FCM (efímero, solo
llega si el móvil está a mano y con cobertura, ver app/push.py), cada
aviso se registra en la tabla `notificaciones` para que el usuario lo vea
dentro de la propia app -- correo nuevo, vencimiento fiscal próximo,
mensaje del portal de cliente, resumen IA semanal.

Un único punto de entrada, `crear_y_enviar()`, sustituye las llamadas
directas a `push.enviar_a_usuario()` que había en los 4 puntos de emisión
existentes (app/correo.py, app/rutas_portal_cliente.py, app/main.py x2)
-- misma llamada, no dos sistemas paralelos que puedan desincronizarse."""
from . import db, push


def crear_y_enviar(
    usuario_id: int, tipo: str, titulo: str, cuerpo: str, url: str | None = None, datos: dict | None = None,
) -> None:
    """Registra la notificación (visible en la propia app) y manda el
    push FCM (visible en el móvil) -- el registro en BD nunca falla en
    silencio como el push (si algo va mal aquí, se quiere saber), pero
    tampoco debe impedir que el push se intente si el registro fallara
    por algún motivo."""
    try:
        db.crear_notificacion(usuario_id, tipo, titulo, cuerpo, url)
    except Exception:
        pass
    push.enviar_a_usuario(usuario_id, titulo, cuerpo, datos)
