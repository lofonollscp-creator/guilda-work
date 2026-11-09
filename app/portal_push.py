"""Avisos en el móvil o el navegador de quien usa el portal (Web Push). Cada persona los activa por su cuenta desde «Mi cuenta» y solo se usan para lo que espera una respuesta suya:
una factura devuelta, un documento pedido, un modelo por revisar, algo por firmar o un mensaje de la gestoría. Reutiliza las claves VAPID y el service worker de la aplicación (app/push.py).

Una suscripción es de una persona en un dispositivo: si a esa persona le quitan el acceso, sus suscripciones se borran (`portal_personas.quitar`)."""
from __future__ import annotations

import json
from datetime import datetime

from . import db, portal_personas, push

MAX_SUSCRIPCIONES_POR_PERSONA = 5
MAX_BYTES = 4000


def disponible() -> bool:
    return push.web_configurado()


def suscribir(cliente, email: str | None, suscripcion: dict) -> None:
    """Guarda la suscripción del navegador de esta persona. Lanza ValueError si no es una suscripción de Web Push o si ya tiene demasiados dispositivos."""
    endpoint = str((suscripcion or {}).get("endpoint") or "")
    claves = (suscripcion or {}).get("keys") or {}
    if not endpoint.startswith("https://") or len(endpoint) > 1000 or not claves.get("p256dh") or not claves.get("auth"):
        raise ValueError("Suscripción no válida.")
    texto = json.dumps({"endpoint": endpoint, "keys": {"p256dh": str(claves["p256dh"]), "auth": str(claves["auth"])}}, separators=(",", ":"))
    if len(texto) > MAX_BYTES:
        raise ValueError("Suscripción no válida.")
    e = portal_personas.limpio(email) or portal_personas.limpio(cliente["email"])
    conn = db.get_connection()
    try:
        ya = conn.execute("SELECT id FROM portal_suscripciones_push WHERE tenant_id = ? AND cliente_fiscal_id = ? AND endpoint = ?", (cliente["tenant_id"], cliente["id"], endpoint)).fetchone()
        if ya is not None:
            conn.execute("UPDATE portal_suscripciones_push SET email = ?, suscripcion = ? WHERE id = ?", (e, texto, ya["id"]))
        else:
            n = conn.execute("SELECT COUNT(*) FROM portal_suscripciones_push WHERE cliente_fiscal_id = ? AND email = ?", (cliente["id"], e)).fetchone()[0]
            if n >= MAX_SUSCRIPCIONES_POR_PERSONA:
                raise ValueError("Ya tienes avisos en varios dispositivos: desactiva alguno antes de añadir otro.")
            conn.execute("INSERT INTO portal_suscripciones_push (tenant_id, cliente_fiscal_id, email, endpoint, suscripcion, creado_en) VALUES (?, ?, ?, ?, ?, ?)",
                         (cliente["tenant_id"], cliente["id"], e, endpoint, texto, datetime.now().isoformat(timespec="seconds")))
        conn.commit()
    finally:
        conn.close()


def dar_de_baja(cliente, endpoint: str) -> None:
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM portal_suscripciones_push WHERE cliente_fiscal_id = ? AND endpoint = ?", (cliente["id"], endpoint))
        conn.commit()
    finally:
        conn.close()


def tiene(cliente, email: str | None) -> int:
    """Cuántos dispositivos tiene activados esta persona."""
    e = portal_personas.limpio(email) or portal_personas.limpio(cliente["email"])
    conn = db.get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM portal_suscripciones_push WHERE cliente_fiscal_id = ? AND email = ?", (cliente["id"], e)).fetchone()[0]
    finally:
        conn.close()


def enviar(cliente, titulo: str, cuerpo: str, destino: str, accion: str | None = None, urgente: bool = False) -> int:
    """Manda el aviso a los dispositivos de las personas de esta ficha que pueden actuar sobre él (`accion`, como en `portal_personas.destinatarios`). Devuelve a cuántos llegó.
    Nunca lanza: un aviso que no sale no debe romper lo que lo provoca."""
    try:
        from . import portal_novedades
        portal_novedades.anotar(cliente, titulo, cuerpo, destino)          # el aviso queda también en el centro de avisos del portal, haya o no notificaciones en el móvil
    except Exception:  # noqa: BLE001
        pass
    if not disponible():
        return 0
    from . import portal_silencio
    # Quien eligió solo el resumen semanal no recibe notificaciones; quien eligió solo lo urgente, solo las urgentes; y nadie las recibe dentro de su franja de «no molestar» (el aviso queda en Avisos).
    permitidos = {p["email"] for p in portal_personas.listar(cliente) if p["rol"] in portal_personas.PERFILES_QUE_PUEDEN[accion] and (p["avisos"] == "todo" or (urgente and p["avisos"] == "urgente"))
                  and not portal_silencio.en_silencio(cliente, p["email"])}
    ruta = destino if destino.startswith("/portal/") else "/portal/"
    carga = {"titulo": titulo[:120], "cuerpo": (cuerpo or "")[:push.MAX_CUERPO_WEB], "url": ruta, "tag": "portal"}
    enviados = 0
    try:
        conn = db.get_connection()
        try:
            filas = conn.execute("SELECT id, email, endpoint, suscripcion FROM portal_suscripciones_push WHERE cliente_fiscal_id = ?", (cliente["id"],)).fetchall()
        finally:
            conn.close()
        muertas = []
        for f in filas:
            if f["email"] not in permitidos:
                continue
            if push._enviar_web(f["suscripcion"], carga):
                enviados += 1
            else:
                muertas.append(f["id"])
        if muertas:
            conn = db.get_connection()
            try:
                for i in muertas:
                    conn.execute("DELETE FROM portal_suscripciones_push WHERE id = ?", (i,))
                conn.commit()
            finally:
                conn.close()
    except Exception:  # noqa: BLE001
        return enviados
    return enviados
