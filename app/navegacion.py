"""Menú lateral a medida de cada persona: ocultar lo que no usa y fijar arriba sus accesos directos. Se guarda en su perfil (`usuario_perfil.menu_prefs`, JSON), que ya se lee para pintar el menú,
así que no suma consultas. Nada se pierde: lo oculto sigue en el buscador (Ctrl K) y en Ajustes › Menú, y «Restablecer» deja el menú como viene de serie. Lo esencial (Inicio, Hoy, Tareas, Correo,
Clientes y la gestoría) no se puede ocultar."""
from __future__ import annotations

import json

from flask import url_for
from flask_babel import lazy_gettext as _l

from . import db

MAX_FIJADOS = 6

# clave: (etiqueta, endpoint, icono, requiere, ocultable). `requiere`: None, «tenant» (la persona pertenece a un despacho) o «gestoria» (el despacho lleva la gestoría).
CATALOGO: dict[str, tuple] = {
    "hoy": (_l("Hoy"), "hoy.bandeja", "sun", None, False),
    "tareas": (_l("Tareas"), "tareas.listar", "list-checks", None, False),
    "notas": (_l("Notas"), "lista_notas", "notebook-pen", None, True),
    "correo": (_l("Correo"), "correo.bandeja", "mail", None, False),
    "correo_equipo": (_l("Correo del equipo"), "correo.equipo", "mail", None, False),
    "contactos": (_l("Contactos"), "contactos.lista", "users", "tenant", False),
    "tiquets": (_l("Tiquets"), "tiquets.tarjetas", "ticket", None, True),
    "fichaje": (_l("Fichaje"), "fichaje.panel", "clock", None, True),
    "clientes": (_l("Clientes"), "clientes.lista", "users", "tenant", False),
    "expedientes": (_l("Expedientes"), "expedientes.lista", "users", "tenant", False),
    "plazos": (_l("Plazos"), "plazos.lista", "calendar-days", "tenant", False),
    "horas": (_l("Horas"), "tiempo.lista", "clock", "tenant", False),
    "panel_fiscal": (_l("Panel fiscal"), "control_fiscal.panel", "calendar-days", "gestoria", False),
    "calendario_fiscal": (_l("Calendario fiscal"), "fiscal.vencimientos", "calendar-days", "gestoria", False),
    "agenda": (_l("Agenda"), "citas.agenda", "calendar-days", "gestoria", False),
    "videollamadas": (_l("Videollamadas"), "videollamadas.nueva", "video", "tenant", True),
    "herramientas": (_l("Herramientas"), "herramientas", "wrench", None, True),
    "asistente": (_l("Asistente IA"), "ia.asistente_vista", "bot", None, True),
    "historial": (_l("Histórico"), "historial", "history", None, True),
    "estadisticas": (_l("Estadísticas"), "estadisticas", "bar-chart-3", None, True),
    "papelera": (_l("Papelera"), "papelera", "trash-2", None, True),
    "importar": (_l("Importar"), "importar", "upload", None, True),
}
OCULTABLES = tuple(k for k, v in CATALOGO.items() if v[4])


def _limpias(datos) -> dict[str, list[str]]:
    if not isinstance(datos, dict):
        datos = {}
    ocultos = [k for k in dict.fromkeys(datos.get("ocultos") or []) if k in OCULTABLES]
    fijados = [k for k in dict.fromkeys(datos.get("fijados") or []) if k in CATALOGO][:MAX_FIJADOS]
    return {"ocultos": ocultos, "fijados": fijados}


def leer(perfil) -> dict[str, list[str]]:
    """Las preferencias de menú de una fila de `usuario_perfil` (o vacías si no hay o están mal)."""
    try:
        bruto = perfil["menu_prefs"] if perfil is not None else None
    except (IndexError, KeyError):
        bruto = None
    try:
        return _limpias(json.loads(bruto)) if bruto else {"ocultos": [], "fijados": []}
    except (ValueError, TypeError):
        return {"ocultos": [], "fijados": []}


def guardar(usuario_id: int, ocultos, fijados) -> dict[str, list[str]]:
    """Valida y guarda: solo claves del catálogo, solo ocultables como ocultas, hasta MAX_FIJADOS fijados. Un mismo elemento no puede estar oculto y fijado."""
    limpias = _limpias({"ocultos": list(ocultos or []), "fijados": list(fijados or [])})
    limpias["ocultos"] = [k for k in limpias["ocultos"] if k not in limpias["fijados"]]
    db.obtener_perfil_usuario(usuario_id)                     # asegura la fila
    conn = db.get_connection()
    try:
        conn.execute("UPDATE usuario_perfil SET menu_prefs = ? WHERE usuario_id = ?", (json.dumps(limpias) if (limpias["ocultos"] or limpias["fijados"]) else None, usuario_id))
        conn.commit()
    finally:
        conn.close()
    return limpias


class Menu:
    """Lo que ve la plantilla del menú: `nav.visible('notas')` y `nav.accesos(...)`."""

    def __init__(self, prefs: dict[str, list[str]]):
        self.prefs = prefs

    def visible(self, clave: str) -> bool:
        return clave not in self.prefs["ocultos"]

    def accesos(self, hay_despacho: bool, gestoria: bool) -> list[dict]:
        """Los accesos directos fijados que esta persona puede usar ahora, en el orden elegido."""
        res = []
        for clave in self.prefs["fijados"]:
            etiqueta, endpoint, icono, requiere, _oculta = CATALOGO[clave]
            if (requiere == "tenant" and not hay_despacho) or (requiere == "gestoria" and not (hay_despacho and gestoria)):
                continue
            res.append({"clave": clave, "etiqueta": str(etiqueta), "url": url_for(endpoint), "icono": icono, "endpoint": endpoint})
        return res


def disponibles(hay_despacho: bool, gestoria: bool) -> list[dict]:
    """Para la pantalla de ajustes: todo lo que esta persona puede ocultar o fijar."""
    res = []
    for clave, (etiqueta, endpoint, icono, requiere, ocultable) in CATALOGO.items():
        if (requiere == "tenant" and not hay_despacho) or (requiere == "gestoria" and not (hay_despacho and gestoria)):
            continue
        res.append({"clave": clave, "etiqueta": str(etiqueta), "ocultable": ocultable, "icono": icono})
    return res
