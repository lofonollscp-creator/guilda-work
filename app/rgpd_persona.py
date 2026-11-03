"""Derechos de la PERSONA USUARIA sobre sus propios datos (RGPD arts. 15 acceso, 17 supresión, 20 portabilidad): descargar todo lo que la plataforma guarda de ella, borrar su historial de IA y sus
dispositivos de avisos, y pedir la baja de su cuenta.

Distinto de app/rgpd.py (derechos de los CLIENTES del despacho, que gestionan los responsables): esto lo hace cada persona sobre sí misma.

La baja de la cuenta NO es instantánea: hay datos que la ley obliga a conservar (el registro horario, 4 años) y datos que pertenecen al despacho (tareas, notas, expedientes). Se REGISTRA la solicitud, se avisa a los
responsables del despacho y a la plataforma, y se atiende en el plazo legal (un mes). Cada solicitud y cada descarga quedan anotadas en `registro_rgpd` (quién y cuándo, sin copiar el contenido)."""
from __future__ import annotations

import json

from . import db, nucleo  # noqa: F401  (nucleo: mismo orden de importación que app/rgpd.py)
from .rgpd import _anotar

LIMITE_FILAS = 20000


def _filas(conn, sql: str, params: tuple) -> list[dict]:
    return [dict(f) for f in conn.execute(sql, params).fetchall()]


def exportar_mis_datos(usuario_id: int) -> dict:
    """Todo lo que la plataforma guarda DE la persona (no el contenido de trabajo del despacho): cuenta, perfil, ajustes, fichajes, ausencias, avisos, historial de IA y dispositivos. Sin secretos
    (ni hash de contraseña ni claves de API ni los tokens de los dispositivos)."""
    u = db.obtener_usuario(usuario_id)
    if u is None:
        return {}
    perfil = db.obtener_perfil_usuario(usuario_id)
    tenant = db.tenant_de_usuario(usuario_id)
    datos = {
        "generado_en": db.now_iso(),
        "cuenta": {"id": u["id"], "email": u["email"], "rol": u["rol"], "creado_en": u["creado_en"], "despacho": tenant["nombre"] if tenant else None},
        "perfil": {k: perfil[k] for k in perfil.keys() if k not in ("usuario_id",)},
        "fichaje_datos": (lambda f: {k: f[k] for k in f.keys() if k != "usuario_id"})(db.obtener_fichaje_datos(usuario_id)),
        "fichajes": [dict(f) for f in db.listar_fichajes(usuario_id)][:LIMITE_FILAS],
        "asistente_ia": {
            "preferencias": {k: v for k, v in dict(db.obtener_preferencias_ia(usuario_id)).items() if "clave" not in k and k != "usuario_id"},
            "conversaciones": [
                {"id": c["id"], "titulo": c["titulo"], "mensajes": [{"rol": m["rol"], "contenido": m["contenido"], "creado_en": m["creado_en"]} for m in db.listar_mensajes_ia(usuario_id, c["id"]) if m["rol"] in ("user", "assistant") and m["contenido"]]}
                for c in db.listar_conversaciones_ia(usuario_id)
            ],
        },
        "nota": "No incluye el contenido de trabajo del despacho (clientes, expedientes, tareas y notas compartidas), que pertenece al despacho: pídelo a sus responsables. Los fichajes se conservan por obligación legal.",
    }
    conn = db.get_connection()
    try:
        datos["ausencias"] = _filas(conn, "SELECT * FROM ausencias WHERE usuario_id = ? ORDER BY id DESC LIMIT ?", (usuario_id, LIMITE_FILAS))
        datos["avisos"] = _filas(conn, "SELECT tipo, titulo, cuerpo, url, creado_en, leido_en FROM notificaciones WHERE usuario_id = ? ORDER BY id DESC LIMIT ?", (usuario_id, LIMITE_FILAS))
        datos["dispositivos_avisos"] = _filas(conn, "SELECT plataforma, creado_en, actualizado_en FROM dispositivos_push WHERE usuario_id = ?", (usuario_id,))
        if tenant:
            _anotar(conn, tenant["id"], usuario_id, "exportacion_propia", "descarga de sus propios datos")
            conn.commit()
    finally:
        conn.close()
    return datos


def olvidar_dispositivos(usuario_id: int) -> int:
    """Borra los dispositivos con avisos push (móvil y navegadores) de la persona. Devuelve cuántos."""
    conn = db.get_connection()
    try:
        n = conn.execute("DELETE FROM dispositivos_push WHERE usuario_id = ?", (usuario_id,)).rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def borrar_historial_ia(usuario_id: int) -> None:
    for c in db.listar_conversaciones_ia(usuario_id):
        db.eliminar_conversacion_ia(usuario_id, c["id"])
    db.vaciar_mensajes_ia(usuario_id)


def solicitar_baja(usuario_id: int) -> bool:
    """Registra la solicitud de baja de la cuenta y avisa a los responsables del despacho. False si ya había una abierta (no se duplica)."""
    from . import notificaciones
    tenant = db.tenant_de_usuario(usuario_id)
    if tenant is None:
        return False
    conn = db.get_connection()
    try:
        previa = conn.execute("SELECT 1 FROM registro_rgpd WHERE tenant_id = ? AND usuario_id = ? AND tipo = 'solicitud_baja' LIMIT 1", (tenant["id"], usuario_id)).fetchone()
        if previa:
            return False
        _anotar(conn, tenant["id"], usuario_id, "solicitud_baja", "pide la baja de su cuenta y la supresión de sus datos")
        conn.commit()
    finally:
        conn.close()
    from . import acceso
    persona = db.nombre_mostrado_usuario(usuario_id) or (db.obtener_usuario(usuario_id) or {})["email"]
    for otro in db.usuarios_de_tenant(tenant["id"]):
        if otro != usuario_id and acceso.es_directivo(otro):
            notificaciones.crear_y_enviar(otro, "rgpd", "Solicitud de baja de una cuenta", f"{persona} ha pedido la baja de su cuenta y la supresión de sus datos. Hay un mes para atenderla (RGPD art. 12.3).", url="/seguridad/privacidad")
    return True


def solicitud_abierta(usuario_id: int) -> bool:
    tenant = db.tenant_de_usuario(usuario_id)
    if tenant is None:
        return False
    conn = db.get_connection()
    try:
        return conn.execute("SELECT 1 FROM registro_rgpd WHERE tenant_id = ? AND usuario_id = ? AND tipo = 'solicitud_baja' LIMIT 1", (tenant["id"], usuario_id)).fetchone() is not None
    finally:
        conn.close()


def como_json(datos: dict) -> str:
    return json.dumps(datos, ensure_ascii=False, indent=2, default=str)
