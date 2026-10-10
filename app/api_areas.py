"""Áreas de la API para limitar un token a una parte de la plataforma (p. ej. una integración que solo toca el
calendario fiscal no debería poder leer el correo). Un token sin áreas (`areas` vacío) llega a todo, como siempre.

Las rutas transversales (`historial`, `dashboard`, `export`, `papelera`, `buscar`, `sync`) mezclan datos de varias
áreas, así que solo las puede usar un token SIN restricción de áreas. Gestionar tokens (`/tokens`) también:
un token restringido no puede crear otro más amplio."""
from __future__ import annotations

AREAS: dict[str, tuple[str, tuple[str, ...]]] = {
    # área: (descripción para personas, primer segmento de ruta bajo /api/v1)
    "notas": ("Notas", ("notas",)),
    "tareas": ("Tareas, proyectos y «mi día»", ("tareas", "tareas-outlook", "checklist", "mi-dia", "companeros", "categorias", "proyectos")),
    "correo": ("Correo", ("correo",)),
    "fiscal": ("Calendario fiscal y clientes", ("fiscal",)),
    "fichaje": ("Fichaje", ("fichaje",)),
    "tiquets": ("Tiquets", ("tiquets",)),
    "ia": ("Asistente de IA", ("ia", "chat")),
    "avisos": ("Notificaciones y comunicados", ("notificaciones", "comunicados")),
    "webhooks": ("Webhooks del despacho", ("webhooks",)),
}

# Siempre permitido (no expone datos de negocio): documentación, identidad propia y cierre de sesión.
_LIBRES = ("openapi.json", "auth", "perfil", "avatar", "herramientas", "dispositivos-push", "onboarding")

_AREA_DE_SEGMENTO = {segmento: area for area, (_d, segmentos) in AREAS.items() for segmento in segmentos}


def area_de_ruta(path: str) -> str | None:
    """Área a la que pertenece una ruta de `/api/v1/...`. `None` = libre (siempre permitida); `"transversal"` o
    `"tokens"` = solo para tokens sin restricción de áreas."""
    resto = path.split("/api/v1/", 1)[-1].strip("/")
    segmento = resto.split("/", 1)[0]
    if segmento in _LIBRES:
        return None
    if segmento == "tokens":
        return "tokens"
    return _AREA_DE_SEGMENTO.get(segmento, "transversal")


def validar_areas(areas) -> list[str]:
    """Lista limpia de áreas válidas (sin duplicados, ordenadas). ValueError si alguna no existe."""
    if areas in (None, "", []):
        return []
    if isinstance(areas, str):
        areas = [a for a in areas.split(",")]
    limpias = sorted({str(a).strip() for a in areas if str(a).strip()})
    desconocidas = [a for a in limpias if a not in AREAS]
    if desconocidas:
        raise ValueError(f"Áreas no válidas: {', '.join(desconocidas)}. Válidas: {', '.join(AREAS)}.")
    return limpias


def permite(areas: list[str], path: str) -> bool:
    if not areas:
        return True
    area = area_de_ruta(path)
    return area is None or area in areas
