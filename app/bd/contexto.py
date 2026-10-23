"""Despacho (tenant) con el que se abren las conexiones a PostgreSQL.

La aplicación no pasa el despacho a cada función: lo fija UNA vez por petición (o por trabajo en segundo plano) y `db.get_connection()` lo lee.

  * ``en_despacho(t)``        las conexiones se abren como la aplicación (rol sujeto a RLS) y con ese despacho: solo ven y escriben lo suyo.
  * ``como_plataforma()``     rol que se salta la RLS: trabajos que recorren despachos, inicio de sesión, enlaces públicos por token, backoffice.
  * sin contexto              igual que ``como_plataforma()`` (lo que hacían los scripts y trabajos antes de existir los despachos activos).

Las peticiones autenticadas SIEMPRE fijan un despacho (el 0, «Plataforma», si la persona no tiene ninguno), de modo que un olvido en una ruta no abre la puerta a otros despachos.
En SQLite no tiene ningún efecto.
"""
from __future__ import annotations

import contextlib
import contextvars

_despacho: contextvars.ContextVar = contextvars.ContextVar("guilda_despacho", default=None)
_plataforma: contextvars.ContextVar = contextvars.ContextVar("guilda_plataforma", default=False)
_usuario: contextvars.ContextVar = contextvars.ContextVar("guilda_usuario", default=None)        # la persona que hace la petición: siempre ve su propia ficha de `usuarios`


def despacho_actual() -> int | None:
    return _despacho.get()


def es_plataforma() -> bool:
    return _plataforma.get()


def usuario_actual() -> int | None:
    return _usuario.get()


@contextlib.contextmanager
def en_despacho(tenant_id: int | None):
    """Dentro del bloque, las conexiones de la aplicación usan ese despacho."""
    t1, t2 = _despacho.set(None if tenant_id is None else int(tenant_id)), _plataforma.set(False)
    try:
        yield
    finally:
        _plataforma.reset(t2)
        _despacho.reset(t1)


@contextlib.contextmanager
def como_plataforma():
    """Dentro del bloque, las conexiones usan el rol que se salta la RLS y no fijan despacho."""
    t1, t2 = _despacho.set(None), _plataforma.set(True)
    try:
        yield
    finally:
        _plataforma.reset(t2)
        _despacho.reset(t1)


def fijar_para_la_peticion(tenant_id: int | None, usuario_id: int | None = None):
    """Para Flask: fija el despacho (y la persona) de la petición y devuelve los testigos con los que `restaurar()` lo deja como estaba."""
    return (_despacho.set(None if tenant_id is None else int(tenant_id)), _plataforma.set(False), _usuario.set(None if usuario_id is None else int(usuario_id)))


def restaurar(testigos) -> None:
    if testigos:
        _usuario.reset(testigos[2])
        _plataforma.reset(testigos[1])
        _despacho.reset(testigos[0])
