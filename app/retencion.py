"""Conservación limitada de datos personales (RGPD art. 5.1.e): lo que ya no hace falta se borra solo, cada día.

| Qué | Cuánto se conserva |
|---|---|
| Conversaciones con el asistente de IA (y sus mensajes) | 365 días desde la última actividad (`GUILDA_RETENCION_IA_DIAS`) |
| Avisos de la campana ya leídos | 180 días; los no leídos, 365 |
| Accesos de clientes a su portal (registro técnico) | `RETENCION_ACCESOS_DIAS` (ver app/db.py) |
| Errores del servidor | `ERRORES_SERVIDOR_RETENCION_DIAS` (ver app/db.py; se limpia al registrar) |

Lo que la ley obliga a conservar (fichajes 4 años, facturas y libros fiscales 4-6 años, documentos del despacho) NO se toca aquí: lo gobierna cada despacho (app/rgpd.py, papelera) y las obligaciones de su sector."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta

from . import db
from .bd import contexto

log = logging.getLogger(__name__)
IA_DIAS = int(os.environ.get("GUILDA_RETENCION_IA_DIAS", "365"))
AVISOS_LEIDOS_DIAS = 180
AVISOS_DIAS = 365
INTERVALO_SEGUNDOS = 24 * 3600


def _antes_de(dias: int, ahora: datetime | None = None) -> str:
    return ((ahora or datetime.now()) - timedelta(days=dias)).isoformat(timespec="seconds")


def purgar(ahora: datetime | None = None) -> dict:
    """Borra lo caducado y devuelve cuántas filas de cada tipo. Idempotente."""
    corte_ia, corte_leidos, corte_avisos = _antes_de(IA_DIAS, ahora), _antes_de(AVISOS_LEIDOS_DIAS, ahora), _antes_de(AVISOS_DIAS, ahora)
    resultado = {"ia_conversaciones": 0, "ia_mensajes": 0, "avisos": 0, "accesos_portal": 0}
    with contexto.como_plataforma():
        conn = db.get_connection()
        try:
            viejas = [f[0] for f in conn.execute("SELECT id FROM ia_conversaciones WHERE actualizada_en < ?", (corte_ia,)).fetchall()]
            for i in viejas:
                resultado["ia_mensajes"] += conn.execute("DELETE FROM ia_mensajes WHERE conversacion_id = ?", (i,)).rowcount
                conn.execute("DELETE FROM ia_conversaciones WHERE id = ?", (i,))
            resultado["ia_conversaciones"] = len(viejas)
            resultado["avisos"] = conn.execute("DELETE FROM notificaciones WHERE (leido_en IS NOT NULL AND creado_en < ?) OR creado_en < ?", (corte_leidos, corte_avisos)).rowcount
            conn.commit()
        finally:
            conn.close()
        try:
            resultado["accesos_portal"] = db.purgar_accesos_antiguos()
        except Exception:  # noqa: BLE001 -- la tabla puede no existir en instalaciones sin ese módulo
            log.exception("No se pudo purgar el registro de accesos del portal")
        try:
            from . import ia_salidas
            resultado["ia_salidas"] = ia_salidas.purgar(ahora)                      # el contador de datos enviados a la IA no se guarda para siempre
        except Exception:  # noqa: BLE001
            log.exception("No se pudo purgar el contador de salidas de datos a la IA")
    return resultado


def bucle() -> None:
    from . import salud
    salud.registrar_ok("retencion_rgpd", INTERVALO_SEGUNDOS * 2, "arrancado")
    time.sleep(300)
    while True:
        try:
            r = purgar()
            salud.registrar_ok("retencion_rgpd", INTERVALO_SEGUNDOS * 2, ", ".join(f"{v} {k}" for k, v in r.items()))
        except Exception as e:  # noqa: BLE001
            log.exception("Fallo en la purga de retención")
            salud.registrar_error("retencion_rgpd", INTERVALO_SEGUNDOS * 2, f"{type(e).__name__}: {e}")
        time.sleep(INTERVALO_SEGUNDOS)
