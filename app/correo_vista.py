"""Vistas personalizables del correo: tamaño de letra, disposición de los paneles, ancho de la lista y vista previa. Preferencias por persona (tabla `correo_preferencias`).

Funciones puras: validan lo que llega del formulario y traducen las preferencias a lo que usa la plantilla (atributos y estilos del contenedor)."""
from __future__ import annotations

TAMANOS_LETRA = {"normal": 1.0, "grande": 1.15, "muy_grande": 1.3}
DISPOSICIONES = ("tres", "inferior", "lista")      # tres paneles · lista arriba y lectura debajo · solo lista (la lectura ocupa la pantalla)
ANCHO_MIN, ANCHO_MAX = 280, 720


def limpiar(*, tam_letra=None, disposicion=None, ancho_lista=None, vista_previa=None) -> dict:
    """Solo los campos que llegan y son válidos: un valor desconocido se ignora (conserva el que hay) y el ancho se acota."""
    res: dict = {}
    if tam_letra in TAMANOS_LETRA:
        res["tam_letra"] = tam_letra
    if disposicion in DISPOSICIONES:
        res["disposicion"] = disposicion
    if ancho_lista is not None:
        try:
            ancho = int(ancho_lista)
        except (TypeError, ValueError):
            ancho = None
        if ancho is not None:
            res["ancho_lista"] = 0 if ancho <= 0 else max(ANCHO_MIN, min(ancho, ANCHO_MAX))      # 0 = automático
    if vista_previa is not None:
        res["vista_previa"] = int(bool(vista_previa))
    return res


def para_plantilla(preferencias) -> dict:
    """Lo que la plantilla necesita: clase de letra, disposición, ancho en px (o None), vista previa y la escala del cuerpo del correo."""
    claves = preferencias.keys() if hasattr(preferencias, "keys") else ()
    letra = preferencias["tam_letra"] if "tam_letra" in claves and preferencias["tam_letra"] in TAMANOS_LETRA else "normal"
    disp = preferencias["disposicion"] if "disposicion" in claves and preferencias["disposicion"] in DISPOSICIONES else "tres"
    ancho = preferencias["ancho_lista"] if "ancho_lista" in claves else 0
    return {"letra": letra, "disposicion": disp, "ancho_lista": ancho or None, "escala": TAMANOS_LETRA[letra],
            "vista_previa": bool(preferencias["vista_previa"]) if "vista_previa" in claves else True}


def con_escala(html: str | None, escala: float) -> str | None:
    """El HTML del correo con el zoom de lectura aplicado (el iframe va aislado, así que el tamaño de letra de la página no le llega)."""
    if not html or escala == 1.0:
        return html
    return f"<style>html{{zoom:{escala}}}</style>{html}"
