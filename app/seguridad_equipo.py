"""Acceso del equipo (W14): quién tiene la verificación en dos pasos y quién no, para que la dirección pueda exigirla donde más importa (quien dirige y quien ve todos los clientes).

La verificación en dos pasos (app de autenticación y códigos de recuperación) la da Kratos y es opcional para cada persona. Esta pantalla no cambia nada: **informa**, con el dato que ya tiene Kratos, y dice cómo activarla.
Las passkeys del equipo (huella o PIN en lugar de contraseña) requieren activar WebAuthn en Kratos y adaptar las pantallas de acceso: ver docs/passkeys-equipo.md; no se activan sin probarlas con un entorno aparte."""
from __future__ import annotations

from . import db, kratos


def informe(tenant_id: int) -> dict:
    """{personas: [{id, nombre, email, direccion, segundo_factor: True|False|None}], sin_segundo_factor, direccion_sin_segundo_factor, sin_comprobar}. `None` = no se pudo consultar a Kratos (o la cuenta aún no está vinculada)."""
    personas = []
    for uid in db.usuarios_de_tenant(tenant_id):
        u = db.obtener_usuario(uid)
        if u is None:
            continue
        creds = None
        try:
            creds = kratos.credenciales_de(u["kratos_identity_id"]) if u["kratos_identity_id"] else None
        except Exception:  # noqa: BLE001 -- una consulta que falla no rompe la pantalla: esa persona sale «sin comprobar»
            creds = None
        personas.append({"id": uid, "nombre": db.nombre_mostrado_usuario(uid) or u["email"], "email": u["email"], "direccion": bool(u["supervisor_tenant"]),
                         "segundo_factor": None if creds is None else "totp" in creds})
    personas.sort(key=lambda p: (not p["direccion"], p["segundo_factor"] is not False, p["nombre"].lower()))
    sin = [p for p in personas if p["segundo_factor"] is False]
    return {"personas": personas, "sin_segundo_factor": len(sin), "direccion_sin_segundo_factor": sum(1 for p in sin if p["direccion"]), "sin_comprobar": sum(1 for p in personas if p["segundo_factor"] is None)}
