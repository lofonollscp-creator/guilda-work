"""Estado de configuración (¿está puesta la variable de entorno del servidor?)
de cada integración externa a nivel de PLATAFORMA."""
from app import baserow, calcom, chatwoot, espocrm, facturascripts, listmonk, metabase, nextcloud, notificaciones_email, ntfy
from app import openproject, paperless, push, stalwart, stripe_pagos, umami, uptime_kuma


def integraciones() -> list[dict]:
    return [
        {"nombre": "Email del portal de cliente (SMTP)", "configurado": notificaciones_email.configurado()},
        {"nombre": "Alertas internas (ALERTAS_ADMIN_EMAIL)", "configurado": bool(notificaciones_email.ALERTAS_ADMIN_EMAIL)},
        {"nombre": "Notificaciones push (FCM)", "configurado": push.configurado()},
        {"nombre": "Stripe (plataforma)", "configurado": stripe_pagos.configurado()},
        {"nombre": "Baserow", "configurado": bool(baserow.BASEROW_ADMIN_PASSWORD)},
        {"nombre": "Cal.diy", "configurado": bool(calcom.CALCOM_ADMIN_PASSWORD)},
        {"nombre": "Chatwoot", "configurado": bool(chatwoot.CHATWOOT_AGENT_API_TOKEN)},
        {"nombre": "EspoCRM", "configurado": bool(espocrm.ESPOCRM_API_KEY)},
        {"nombre": "FacturaScripts (aprovisionamiento)", "configurado": bool(facturascripts.FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD)},
        {"nombre": "Listmonk", "configurado": bool(listmonk.LISTMONK_ADMIN_USER and listmonk.LISTMONK_ADMIN_PASSWORD)},
        {"nombre": "Metabase", "configurado": bool(metabase.METABASE_API_KEY)},
        {"nombre": "Nextcloud", "configurado": bool(nextcloud.NEXTCLOUD_ADMIN_USER and nextcloud.NEXTCLOUD_ADMIN_PASSWORD)},
        {"nombre": "ntfy", "configurado": bool(ntfy.NTFY_ADMIN_USER and ntfy.NTFY_ADMIN_PASSWORD)},
        {"nombre": "OpenProject", "configurado": bool(openproject.OPENPROJECT_API_TOKEN)},
        {"nombre": "Paperless-ngx", "configurado": bool(paperless.PAPERLESS_ADMIN_USER and paperless.PAPERLESS_ADMIN_PASSWORD)},
        {"nombre": "Stalwart (correo por tenant)", "configurado": bool(stalwart.STALWART_ADMIN_USER and stalwart.STALWART_ADMIN_PASSWORD)},
        {"nombre": "Umami", "configurado": bool(umami.UMAMI_ADMIN_PASSWORD)},
        {"nombre": "Uptime Kuma", "configurado": bool(uptime_kuma.UPTIME_KUMA_API_KEY)},
    ]
