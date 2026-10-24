"""Contexto de la sesión para la app móvil (`GET /auth/me` ampliado, API 1.5) y versión mínima de la app.

Ver `docs/plan-app-movil.md` §4.4 (S-02) y S-10. Todo es aditivo: un cliente anterior ignora lo nuevo.

La versión mínima y la recomendada de la app se fijan por entorno (sin tocar código ni base de datos):
    GUILDA_APP_VERSION_MINIMA      p. ej. «1.1.0»; una app con `X-App-Version` menor recibe `426 actualiza_app`
    GUILDA_APP_VERSION_RECOMENDADA p. ej. «1.3.0»; solo se informa (la app puede sugerir actualizar)
    GUILDA_APP_URL_TIENDA          enlace a la ficha de la app para el botón «Ir a la tienda»"""
from __future__ import annotations

import os

from . import cifrado_despacho, db, db_plataforma, verticales

IDIOMAS = ("es", "ca", "en", "fr")


def version_a_tupla(version: str) -> tuple[int, ...]:
    """`1.2.3+45` → (1, 2, 3); lo que no es número cuenta como 0."""
    principal = (version or "").strip().split("+")[0].split("-")[0]
    return tuple(int(x) if x.isdigit() else 0 for x in principal.split(".")) if principal else ()


def comparar_versiones(a: str, b: str) -> int:
    x, y = list(version_a_tupla(a)), list(version_a_tupla(b))
    n = max(len(x), len(y))
    x, y = x + [0] * (n - len(x)), y + [0] * (n - len(y))
    return (x > y) - (x < y)


def config_app() -> dict:
    """Lo que el servidor dice de la app móvil: {version_minima, version_recomendada, url_tienda} (None si no se ha fijado)."""
    def leer(nombre: str):
        return (os.environ.get(nombre) or "").strip() or None
    return {"version_minima": leer("GUILDA_APP_VERSION_MINIMA"), "version_recomendada": leer("GUILDA_APP_VERSION_RECOMENDADA"),
            "url_tienda": leer("GUILDA_APP_URL_TIENDA")}


def app_obsoleta(version_cliente: str | None) -> bool:
    """¿Es esta versión de la app menor que la mínima admitida? Sin versión mínima fijada o sin versión del cliente, no."""
    minima = config_app()["version_minima"]
    return bool(minima and version_cliente and comparar_versiones(version_cliente, minima) < 0)


def modulos_de(tenant_id: int | None) -> dict[str, bool]:
    """Módulos de negocio disponibles y si el despacho los tiene activos."""
    activos = verticales.activos_de(tenant_id)
    return {v.id: v.id in activos for v in verticales.VERTICALES.values() if v.disponible}


def despachos_de(usuario_id: int) -> list[dict]:
    """Despachos de la persona (el principal primero) con lo que es en cada uno."""
    salida = []
    for d in db_plataforma.tenants_de_usuario(usuario_id):
        a = db_plataforma.atributos_en_despacho(usuario_id, d["id"])
        salida.append({"id": d["id"], "nombre": d["nombre"], "principal": bool(d["principal"]),
                       "gestor_fichajes": bool(a["gestor_fichajes"]), "supervisor": bool(a["supervisor_tenant"])})
    return salida


def apariencia_de(usuario_id: int) -> dict:
    a = db_plataforma.apariencia_usuario(usuario_id)
    return {"tema": a["tema"], "densidad": a["densidad"], "idioma": db_plataforma.idioma_usuario(usuario_id)}


def contexto(usuario_id: int, tenant_id: int | None, *, es_admin: bool, gestor_fichajes: bool, supervisor: bool) -> dict:
    """Los campos nuevos de `/auth/me`. `tenant_id` es el despacho activo de la petición (ya resuelto con `X-Despacho`)."""
    cifrado = cifrado_despacho.estado(tenant_id) if tenant_id is not None else {"activo": False, "nivel": None}
    return {
        "despacho_activo": tenant_id,
        "despachos": despachos_de(usuario_id),
        "modulos": modulos_de(tenant_id),
        "permisos": {"fichaje_admin": bool(gestor_fichajes), "supervisor_fiscal": bool(supervisor), "admin": bool(es_admin)},
        "cifrado": {"activo": bool(cifrado["activo"]), "nivel": cifrado["nivel"]},
        "apariencia": apariencia_de(usuario_id),
        "app": config_app(),
    }
