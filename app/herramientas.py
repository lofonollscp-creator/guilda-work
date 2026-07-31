"""Catálogo de herramientas conectadas (Fase 7e) — lista en código, no en
base de datos: no hay todavía necesidad real de que un admin la edite sin
tocar código (si llega a hacer falta, se traslada a una tabla gestionada
desde el panel de administración de la Fase 7c, no antes).

Cada URL tiene un valor por defecto para desarrollo local (mismos
puertos que `docker-compose.yml`) y se sobreescribe por variable de
entorno en un despliegue real (ver HOSTING.md) apuntando a los
subdominios que sirve Caddy.

`icono`: emoji — lo consume `app/rutas_api.py` (API de la app móvil,
que lo pinta tal cual) y `app/ia_asistente.py`, así que se mantiene por
compatibilidad. `icono_logo`: nombre de archivo dentro de
`app/static/logos/` con el logotipo oficial real de cada herramienta
(descargado una vez de la fuente oficial de cada proyecto — Simple
Icons para las que están publicadas ahí, repositorio/CDN propio del
proyecto para las que no — y servido como asset local, sin depender de
ningún CDN externo en tiempo de ejecución), usado solo por
`herramientas.html`. `color`: acento por herramienta para el borde y el
resplandor de la tarjeta en la web (hex) — decorativo, no tiene que
coincidir con el color de marca del logotipo (que ya se ve con sus
colores reales en el logotipo mismo). `categoria`: agrupación visual en
la web.

`sso`: si es `True`, la propia herramienta sabe autenticar contra Ory
Hydra usando la sesión de Kratos ya activa (mismo patrón que Outline,
Fase 7b) — el enlace entra sin pedir nada más. Si es `False`, la
herramienta no soporta SSO en su edición gratuita (Metabase/n8n,
confirmado en su documentación oficial — ver Fase 7e del plan) o
simplemente no está conectada todavía (MinIO sí soporta OIDC pero no se
ha conectado en esta fase, para no ampliar el alcance sin necesidad) —
el enlace lleva a su pantalla de login propia.
"""
import os

HERRAMIENTAS = [
    {
        "id": "outline",
        "nombre": "Outline",
        "descripcion": "Guías y documentación interna del equipo.",
        "icono": "📚",
        "icono_logo": "outline.svg",
        "color": "#8b5cf6",
        "categoria": "Conocimiento",
        "url": os.environ.get("HERRAMIENTA_OUTLINE_URL", "http://127.0.0.1:3001"),
        "sso": True,
    },
    {
        "id": "chat",
        "nombre": "Chat",
        "descripcion": "Mensajería del equipo (Element).",
        "icono": "💬",
        "icono_logo": "chat.svg",
        "color": "#22c55e",
        "categoria": "Conocimiento",
        "url": os.environ.get("HERRAMIENTA_ELEMENT_URL", "http://127.0.0.1:8009"),
        "sso": True,
    },
    {
        "id": "crm",
        "nombre": "CRM",
        "descripcion": "Gestión de clientes y oportunidades (EspoCRM).",
        "icono": "🧾",
        "icono_logo": "crm.svg",
        "color": "#3b82f6",
        "categoria": "Productividad",
        "url": os.environ.get("HERRAMIENTA_ESPOCRM_URL", "http://127.0.0.1:8015"),
        # Con SSO de verdad — a diferencia de OpenProject/Chatwoot/Metabase/
        # Vaultwarden, EspoCRM sí tiene OIDC nativo en su core gratuito
        # (desde v7.3), mismo patrón que Outline/Element (Fase CRM, ver
        # HOSTING.md 8.19).
        "sso": True,
    },
    {
        "id": "openproject",
        "nombre": "OpenProject",
        "descripcion": "Gestión de proyectos y tareas de equipo (Kanban, Gantt).",
        "icono": "🗂",
        "icono_logo": "openproject.svg",
        "color": "#f59e0b",
        "categoria": "Productividad",
        "url": os.environ.get("HERRAMIENTA_OPENPROJECT_URL", "http://127.0.0.1:8010"),
        # Sin SSO: confirmado en la documentación oficial de OpenProject
        # que el login OIDC/SAML es un Enterprise add-on de pago, no está
        # en la edición community desplegada aquí (Fase 7f).
        "sso": False,
    },
    {
        "id": "chatwoot",
        "nombre": "Chatwoot",
        "descripcion": "Bandeja de soporte omnicanal para incidencias de clientes.",
        "icono": "🎧",
        "icono_logo": "chatwoot.svg",
        "color": "#06b6d4",
        "categoria": "Productividad",
        "url": os.environ.get("HERRAMIENTA_CHATWOOT_URL", "http://127.0.0.1:8011"),
        # Sin SSO: confirmado en su documentación oficial que SAML/SSO es
        # un plan Enterprise de pago, no está en la community edition
        # desplegada aquí (Fase 7g) — mismo criterio que OpenProject.
        "sso": False,
    },
    {
        "id": "n8n",
        "nombre": "n8n",
        "descripcion": "Automatizaciones y flujos de trabajo.",
        "icono": "🔀",
        "icono_logo": "n8n.svg",
        "color": "#ec4899",
        "categoria": "Productividad",
        "url": os.environ.get("HERRAMIENTA_N8N_URL", "http://127.0.0.1:5678"),
        "sso": False,
    },
    {
        "id": "citas",
        "nombre": "Citas",
        "descripcion": "Reserva de citas online para tus clientes (Cal.diy).",
        "icono": "📅",
        "icono_logo": "citas.svg",
        "color": "#292929",
        "categoria": "Productividad",
        "url": os.environ.get("HERRAMIENTA_CALCOM_URL", "http://127.0.0.1:8021"),
        # Sin SSO: Cal.diy (la continuación libre de Cal.com tras su paso
        # a código cerrado en julio 2026) no tiene SSO/SAML en su edición
        # gratuita — mismo criterio que Documenso/FacturaScripts/Baserow.
        "sso": False,
    },
    {
        "id": "newsletter",
        "nombre": "Newsletter",
        "descripcion": "Envíos masivos y newsletters a tus clientes (Listmonk).",
        "icono": "📧",
        "icono_logo": "newsletter.svg",
        "color": "#0ea5e9",
        "categoria": "Productividad",
        "url": os.environ.get("HERRAMIENTA_LISTMONK_URL", "http://127.0.0.1:8023"),
        # Con SSO real — Listmonk tiene OIDC nativo gratis (sin edición
        # de pago, a diferencia de OpenProject/Chatwoot/Documenso/
        # Baserow), verificado en vivo contra un contenedor real (Fase
        # newsletter, ver HOSTING.md 8.26).
        "sso": True,
    },
    {
        "id": "correo-stalwart",
        "nombre": "Correo (Stalwart)",
        "descripcion": "Servidor de correo propio con API moderna para MCP (Stalwart).",
        "icono": "📮",
        "icono_logo": "correo-stalwart.svg",
        "color": "#DB2D54",
        "categoria": "Productividad",
        "url": os.environ.get("HERRAMIENTA_STALWART_URL", "http://127.0.0.1:8025"),
        # Nombre "correo-stalwart" (no "correo" a secas) para no chocar
        # con la sección "Correo" ya existente de Guilda Work (cliente
        # IMAP genérico, ver app/correo.py) — Stalwart es un backend
        # alternativo, no un reemplazo forzoso. Sin SSO por ahora:
        # Stalwart admite un directorio OIDC como backend de
        # autenticación (visto en su propio asistente de instalación),
        # pero mapear eso a Hydra es una fase aparte, no bloqueante para
        # este MVP — cada tenant entra con la cuenta que le crea
        # app/stalwart.py:aprovisionar_tenant().
        "sso": False,
    },
    {
        "id": "drive",
        "nombre": "Drive",
        "descripcion": "Almacenamiento de archivos en la nube, tipo Drive (Nextcloud).",
        "icono": "☁️",
        "icono_logo": "drive.svg",
        "color": "#38bdf8",
        "categoria": "Documentos y datos",
        "url": os.environ.get("HERRAMIENTA_NEXTCLOUD_URL", "http://127.0.0.1:8016"),
        # Con SSO — app oficial `user_oidc` (Fase Drive, ver HOSTING.md
        # 8.20), mismo patrón que Outline/Element/EspoCRM.
        "sso": True,
    },
    {
        "id": "documentos",
        "nombre": "Documentos",
        "descripcion": "Gestión documental y OCR de escaneos/PDFs (Paperless-ngx).",
        "icono": "📄",
        "icono_logo": "documentos.svg",
        "color": "#eab308",
        "categoria": "Documentos y datos",
        "url": os.environ.get("HERRAMIENTA_PAPERLESS_URL", "http://127.0.0.1:8019"),
        # Con SSO — OIDC vía django-allauth desde Paperless-ngx 2.5.0,
        # con sincronización de grupos (Fase documentos, ver HOSTING.md),
        # mismo patrón que Drive/CRM.
        "sso": True,
    },
    {
        "id": "firmas",
        "nombre": "Firmas",
        "descripcion": "Firma electrónica de documentos (Documenso).",
        "icono": "✍️",
        "icono_logo": "firmas.png",
        "color": "#10b981",
        "categoria": "Documentos y datos",
        "url": os.environ.get("HERRAMIENTA_DOCUMENSO_URL", "http://127.0.0.1:8018"),
        # Sin SSO: confirmado en la documentación oficial de Documenso
        # que el SSO Portal es una función de pago (Enterprise) — mismo
        # criterio que OpenProject/Chatwoot/Metabase/Vaultwarden.
        "sso": False,
    },
    {
        "id": "hojas",
        "nombre": "Hojas",
        "descripcion": "Hojas de cálculo tipo base de datos, listados estructurados (Baserow).",
        "icono": "🗂️",
        "icono_logo": "hojas.svg",
        "color": "#84cc16",
        "categoria": "Documentos y datos",
        "url": os.environ.get("HERRAMIENTA_BASEROW_URL", "http://127.0.0.1:8020"),
        # Sin SSO: confirmado en la documentación oficial que está solo
        # en el plan Advanced Enterprise, también en self-hosted — mismo
        # criterio que Documenso/FacturaScripts.
        "sso": False,
    },
    {
        "id": "metabase",
        "nombre": "Metabase",
        "descripcion": "Paneles de análisis sobre los datos de Guilda Work.",
        "icono": "📊",
        "icono_logo": "metabase.svg",
        "color": "#6366f1",
        "categoria": "Documentos y datos",
        "url": os.environ.get("HERRAMIENTA_METABASE_URL", "http://127.0.0.1:3000"),
        "sso": False,
    },
    {
        "id": "minio",
        "nombre": "MinIO",
        "descripcion": "Almacenamiento de archivos (consola de administración).",
        "icono": "🗄",
        "icono_logo": "minio.svg",
        "color": "#64748b",
        "categoria": "Infraestructura",
        "url": os.environ.get("HERRAMIENTA_MINIO_URL", "http://127.0.0.1:9001"),
        "sso": False,
    },
    {
        "id": "vaultwarden",
        "nombre": "Vaultwarden",
        "descripcion": "Gestor de contraseñas y tokens (compatible con Bitwarden).",
        "icono": "🔐",
        "icono_logo": "vaultwarden.svg",
        "color": "#ef4444",
        "categoria": "Infraestructura",
        "url": os.environ.get("HERRAMIENTA_VAULTWARDEN_URL", "http://127.0.0.1:8013"),
        # Sin SSO: la edición gratuita/código abierto no ofrece OIDC/SAML
        # (eso es un add-on de pago de Bitwarden), mismo criterio que
        # OpenProject/Chatwoot/Metabase/n8n.
        "sso": False,
    },
    {
        "id": "uptime-kuma",
        "nombre": "Uptime Kuma",
        "descripcion": "Monitorización del stack: avisa si algún servicio se cae.",
        "icono": "📈",
        "icono_logo": "uptime-kuma.svg",
        "color": "#14b8a6",
        "categoria": "Infraestructura",
        "url": os.environ.get("HERRAMIENTA_UPTIME_KUMA_URL", "http://127.0.0.1:8014"),
        "sso": False,
    },
]

# URL del homeserver de Synapse (Fase 9, chat nativo en la app móvil) —
# distinta de HERRAMIENTA_ELEMENT_URL (Element-web, la interfaz web de
# chat.*): el cliente Matrix nativo (paquete `matrix` en Flutter) habla
# directo con el homeserver (matrix.*), no con Element-web.
MATRIX_HOMESERVER_URL = os.environ.get("HERRAMIENTA_MATRIX_HOMESERVER_URL", "http://127.0.0.1:8008")
