"""Catálogo de herramientas conectadas (Fase 7e) — lista en código, no en
base de datos: no hay todavía necesidad real de que un admin la edite sin
tocar código (si llega a hacer falta, se traslada a una tabla gestionada
desde el panel de administración de la Fase 7c, no antes).

Cada URL tiene un valor por defecto para desarrollo local (mismos
puertos que `docker-compose.yml`) y se sobreescribe por variable de
entorno en un despliegue real (ver HOSTING.md) apuntando a los
subdominios que sirve Caddy.

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
        "url": os.environ.get("HERRAMIENTA_OUTLINE_URL", "http://127.0.0.1:3001"),
        "sso": True,
    },
    {
        "id": "chat",
        "nombre": "Chat",
        "descripcion": "Mensajería del equipo (Element).",
        "icono": "💬",
        "url": os.environ.get("HERRAMIENTA_ELEMENT_URL", "http://127.0.0.1:8009"),
        "sso": True,
    },
    {
        "id": "metabase",
        "nombre": "Metabase",
        "descripcion": "Paneles de análisis sobre los datos de Guilda Work.",
        "icono": "📊",
        "url": os.environ.get("HERRAMIENTA_METABASE_URL", "http://127.0.0.1:3000"),
        "sso": False,
    },
    {
        "id": "n8n",
        "nombre": "n8n",
        "descripcion": "Automatizaciones y flujos de trabajo.",
        "icono": "🔀",
        "url": os.environ.get("HERRAMIENTA_N8N_URL", "http://127.0.0.1:5678"),
        "sso": False,
    },
    {
        "id": "minio",
        "nombre": "MinIO",
        "descripcion": "Almacenamiento de archivos (consola de administración).",
        "icono": "🗄",
        "url": os.environ.get("HERRAMIENTA_MINIO_URL", "http://127.0.0.1:9001"),
        "sso": False,
    },
    {
        "id": "openproject",
        "nombre": "OpenProject",
        "descripcion": "Gestión de proyectos y tareas de equipo (Kanban, Gantt).",
        "icono": "🗂",
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
        "url": os.environ.get("HERRAMIENTA_CHATWOOT_URL", "http://127.0.0.1:8011"),
        # Sin SSO: confirmado en su documentación oficial que SAML/SSO es
        # un plan Enterprise de pago, no está en la community edition
        # desplegada aquí (Fase 7g) — mismo criterio que OpenProject.
        "sso": False,
    },
]
