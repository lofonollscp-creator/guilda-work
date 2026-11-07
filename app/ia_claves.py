"""Claves de API de los proveedores de IA. NUNCA van a la base de datos: viven en el almacén de credenciales del sistema (keyring), como las contraseñas de correo.

Cada entrada es una lista de claves en orden de preferencia (si una falla por un motivo propio de esa clave, se prueba la siguiente). Hay de dos dueños:
* de una **persona** (`usuario`): van primero. Las de OpenRouter conservan el nombre de siempre, así que las que ya hay guardadas siguen valiendo.
* del **despacho** (`despacho`): las pone la dirección y las usa todo el equipo cuando la persona no tiene las suyas o las suyas fallan."""
from __future__ import annotations

import json

import keyring
import keyring.errors

SERVICIO = "guilda-work-ia"


def _nombre_usuario(proveedor: str, usuario_id: int) -> str:
    return f"openrouter-api-key-usuario-{usuario_id}" if proveedor == "openrouter" else f"{proveedor}-api-key-usuario-{usuario_id}"


def _nombre_despacho(proveedor: str, tenant_id: int) -> str:
    return f"{proveedor}-api-key-despacho-{tenant_id}"


def _leer(nombre: str) -> list[str]:
    valor = keyring.get_password(SERVICIO, nombre)
    if not valor:
        return []
    try:
        datos = json.loads(valor)
        if isinstance(datos, list):
            return [str(c) for c in datos if c]
    except (json.JSONDecodeError, TypeError):
        pass
    return [valor]                                   # guardada antes de admitir varias: una sola clave en texto plano


def _guardar(nombre: str, claves: list[str]) -> None:
    claves = [c.strip() for c in claves if c and c.strip()]
    if claves:
        keyring.set_password(SERVICIO, nombre, json.dumps(claves))
    else:
        _borrar(nombre)


def _borrar(nombre: str) -> None:
    try:
        keyring.delete_password(SERVICIO, nombre)
    except keyring.errors.PasswordDeleteError:
        pass


def de_usuario(proveedor: str, usuario_id: int) -> list[str]:
    return _leer(_nombre_usuario(proveedor, usuario_id))


def guardar_de_usuario(proveedor: str, usuario_id: int, claves: list[str]) -> None:
    _guardar(_nombre_usuario(proveedor, usuario_id), claves)


def borrar_de_usuario(proveedor: str, usuario_id: int) -> None:
    _borrar(_nombre_usuario(proveedor, usuario_id))


def de_despacho(proveedor: str, tenant_id: int) -> list[str]:
    return _leer(_nombre_despacho(proveedor, tenant_id))


def guardar_de_despacho(proveedor: str, tenant_id: int, claves: list[str]) -> None:
    _guardar(_nombre_despacho(proveedor, tenant_id), claves)


def borrar_de_despacho(proveedor: str, tenant_id: int) -> None:
    _borrar(_nombre_despacho(proveedor, tenant_id))
