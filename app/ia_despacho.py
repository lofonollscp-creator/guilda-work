"""Configuración de IA del despacho: qué proveedores tiene (con clave compartida por todo el equipo), qué modelo usa cada uno para el asistente y para leer facturas, en qué orden se prueban,
y las normas que fija la dirección (solo proveedores de la UE, si las personas pueden poner claves propias, si la IA decide sola al leer facturas…).

En la base de datos solo va lo que no es secreto: de las claves se guarda un resumen enmascarado («sk-…a1b2») para que la pantalla enseñe cuántas hay sin poder leerlas (app/ia_claves.py).
Cualquier persona del despacho puede ver qué proveedores hay activos; solo la dirección (supervisores) cambia nada."""
from __future__ import annotations

import json
from datetime import datetime

from . import db, ia_claves, ia_proveedores as pv

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ia_proveedores_despacho (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    proveedor TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 0,
    orden INTEGER NOT NULL DEFAULT 0,
    modelo_asistente TEXT NOT NULL DEFAULT '',
    modelo_facturas TEXT NOT NULL DEFAULT '',
    url_base TEXT NOT NULL DEFAULT '',
    claves_resumen TEXT NOT NULL DEFAULT '[]',
    actualizado_por INTEGER,
    actualizado_en TEXT NOT NULL,
    PRIMARY KEY (tenant_id, proveedor)
);

CREATE TABLE IF NOT EXISTS ia_config_despacho (
    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    solo_ue INTEGER NOT NULL DEFAULT 0,
    claves_personales INTEGER NOT NULL DEFAULT 1,
    facturas_modo TEXT NOT NULL DEFAULT 'compartida' CHECK (facturas_modo IN ('compartida', 'auto')),
    umbral_confianza INTEGER NOT NULL DEFAULT 90,
    lectura_texto INTEGER NOT NULL DEFAULT 1,
    separar_pdf INTEGER NOT NULL DEFAULT 1,
    actualizado_por INTEGER,
    actualizado_en TEXT NOT NULL
);
"""

TAREAS = ("asistente", "facturas")
MODOS_FACTURAS = ("compartida", "auto")
UMBRAL_MIN, UMBRAL_MAX = 50, 100
MAX_MODELO = 120


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def es_direccion(usuario_id: int) -> bool:
    return bool(db.es_admin(usuario_id) or db.es_supervisor_tenant(usuario_id))


# --- Normas del despacho ------------------------------------------------------------------------------------------------------------------------------------

def config(tenant_id: int) -> dict:
    """Las normas del despacho (con sus valores por defecto si la dirección aún no ha tocado nada)."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT solo_ue, claves_personales, facturas_modo, umbral_confianza, lectura_texto, separar_pdf FROM ia_config_despacho WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    return {"solo_ue": bool(f["solo_ue"]), "claves_personales": bool(f["claves_personales"]), "facturas_modo": f["facturas_modo"], "umbral_confianza": f["umbral_confianza"],
            "lectura_texto": bool(f["lectura_texto"]), "separar_pdf": bool(f["separar_pdf"])} if f else {"solo_ue": False, "claves_personales": True, "facturas_modo": "compartida", "umbral_confianza": 90,
                                                                                                                  "lectura_texto": True, "separar_pdf": True}


def guardar_config(tenant_id: int, *, solo_ue: bool, claves_personales: bool, facturas_modo: str, umbral_confianza: int, lectura_texto: bool = True, separar_pdf: bool = True, por: int | None = None) -> None:
    if facturas_modo not in MODOS_FACTURAS:
        raise ValueError("El modo de lectura de facturas no es válido.")
    try:
        umbral = int(umbral_confianza)
    except (TypeError, ValueError):
        raise ValueError("El umbral de confianza debe ser un número.") from None
    if not UMBRAL_MIN <= umbral <= UMBRAL_MAX:
        raise ValueError("El umbral de confianza debe estar entre 50 y 100.")
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO ia_config_despacho (tenant_id, solo_ue, claves_personales, facturas_modo, umbral_confianza, lectura_texto, separar_pdf, actualizado_por, actualizado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                     "ON CONFLICT (tenant_id) DO UPDATE SET solo_ue = excluded.solo_ue, claves_personales = excluded.claves_personales, facturas_modo = excluded.facturas_modo, "
                     "umbral_confianza = excluded.umbral_confianza, lectura_texto = excluded.lectura_texto, separar_pdf = excluded.separar_pdf, actualizado_por = excluded.actualizado_por, actualizado_en = excluded.actualizado_en",
                     (tenant_id, int(solo_ue), int(claves_personales), facturas_modo, umbral, int(lectura_texto), int(separar_pdf), por, _ahora()))
        conn.commit()
    finally:
        conn.close()


def permitido(tenant_id: int | None, proveedor_id: str) -> bool:
    """¿Admite el despacho este proveedor? Con «solo UE» quedan fuera los que mandan los datos fuera de la UE (los de tu propia red, como Ollama, sí valen)."""
    if tenant_id is None:
        return True
    return not (config(tenant_id)["solo_ue"] and pv.obtener(proveedor_id).region == "global")


# --- Proveedores del despacho -------------------------------------------------------------------------------------------------------------------------------

def _filas(tenant_id: int) -> dict[str, dict]:
    conn = db.get_connection()
    try:
        return {f["proveedor"]: dict(f) for f in conn.execute("SELECT * FROM ia_proveedores_despacho WHERE tenant_id = ?", (tenant_id,)).fetchall()}
    finally:
        conn.close()


def listar(tenant_id: int) -> list[dict]:
    """Todos los proveedores conocidos con la configuración del despacho (en el orden en que se prueban; los no configurados, al final y apagados). Nunca lleva claves, solo su resumen."""
    filas = _filas(tenant_id)
    salida = []
    for pid in pv.ORDEN:
        p = pv.obtener(pid)
        f = filas.get(pid)
        resumen = json.loads(f["claves_resumen"]) if f else []
        salida.append({"id": pid, "nombre": p.nombre, "region": p.region, "pide_clave": p.pide_clave, "ejemplo_clave": p.ejemplo_clave, "ayuda": str(p.ayuda), "modelos_sugeridos": list(p.modelos_sugeridos),
                       "activo": bool(f and f["activo"]), "orden": f["orden"] if f else 999, "modelo_asistente": f["modelo_asistente"] if f else "", "modelo_facturas": f["modelo_facturas"] if f else "",
                       "url_base": (f["url_base"] if f else "") or "", "url_por_defecto": p.url_base, "claves": resumen, "tiene_claves": bool(resumen) or not p.pide_clave,
                       "permitido": permitido(tenant_id, pid)})
    return sorted(salida, key=lambda x: (not x["activo"], x["orden"], pv.ORDEN.index(x["id"])))


def _modelo(texto: str | None) -> str:
    m = (texto or "").strip()
    if len(m) > MAX_MODELO or any(c.isspace() for c in m):
        raise ValueError("El nombre del modelo no es válido (sin espacios, máximo 120 caracteres).")
    return m


def guardar(tenant_id: int, proveedor_id: str, *, activo: bool, modelo_asistente: str = "", modelo_facturas: str = "", url_base: str = "", orden: int | None = None,
            claves_nuevas: list[str] | None = None, borrar_claves: bool = False, por: int | None = None) -> None:
    """Configura un proveedor del despacho. `claves_nuevas` sustituye a las que hubiera; `borrar_claves` las quita. `ValueError` con un mensaje legible si algo no vale."""
    p = pv.obtener(proveedor_id)
    modelo_a, modelo_f = _modelo(modelo_asistente), _modelo(modelo_facturas)
    url = pv.url_valida(url_base) if (url_base or "").strip() else ""
    if url and proveedor_id not in ("ollama", "openai", "mistral", "gemini"):
        raise ValueError("Solo se puede cambiar la dirección en Ollama y en los proveedores compatibles con OpenAI.")
    if activo and not permitido(tenant_id, proveedor_id):
        raise ValueError("El despacho solo admite proveedores de la UE o de tu propia red: este manda los datos fuera.")
    nuevas = [c.strip() for c in (claves_nuevas or []) if c and c.strip()]
    if borrar_claves:
        ia_claves.borrar_de_despacho(proveedor_id, tenant_id)
    if nuevas:
        if any(len(c) < 8 or any(ch.isspace() for ch in c) for c in nuevas):
            raise ValueError("Una de las claves no parece válida (muy corta o con espacios).")
        ia_claves.guardar_de_despacho(proveedor_id, tenant_id, nuevas)
    claves = ia_claves.de_despacho(proveedor_id, tenant_id)
    if activo and p.pide_clave and not claves:
        raise ValueError("Para activar este proveedor añade antes su clave de API.")
    if activo and not (modelo_a or modelo_f):
        raise ValueError("Indica al menos un modelo (para el asistente o para las facturas).")
    resumen = json.dumps([pv.enmascarar(c) for c in claves], ensure_ascii=False)
    conn = db.get_connection()
    try:
        previo = conn.execute("SELECT orden FROM ia_proveedores_despacho WHERE tenant_id = ? AND proveedor = ?", (tenant_id, proveedor_id)).fetchone()
        if orden is None:
            orden = previo["orden"] if previo else (conn.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM ia_proveedores_despacho WHERE tenant_id = ?", (tenant_id,)).fetchone()[0])
        conn.execute("INSERT INTO ia_proveedores_despacho (tenant_id, proveedor, activo, orden, modelo_asistente, modelo_facturas, url_base, claves_resumen, actualizado_por, actualizado_en) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (tenant_id, proveedor) DO UPDATE SET activo = excluded.activo, orden = excluded.orden, modelo_asistente = excluded.modelo_asistente, "
                     "modelo_facturas = excluded.modelo_facturas, url_base = excluded.url_base, claves_resumen = excluded.claves_resumen, actualizado_por = excluded.actualizado_por, "
                     "actualizado_en = excluded.actualizado_en",
                     (tenant_id, proveedor_id, int(activo), int(orden), modelo_a, modelo_f, url, resumen, por, _ahora()))
        conn.commit()
    finally:
        conn.close()


def mover(tenant_id: int, proveedor_id: str, arriba: bool) -> None:
    """Sube o baja un proveedor en el orden en que se prueban (cambia su sitio con el vecino activo)."""
    activos = [p for p in listar(tenant_id) if p["activo"]]
    ids = [p["id"] for p in activos]
    if proveedor_id not in ids:
        return
    i = ids.index(proveedor_id)
    j = i - 1 if arriba else i + 1
    if not 0 <= j < len(ids):
        return
    ids[i], ids[j] = ids[j], ids[i]
    conn = db.get_connection()
    try:
        for orden, pid in enumerate(ids, start=1):
            conn.execute("UPDATE ia_proveedores_despacho SET orden = ? WHERE tenant_id = ? AND proveedor = ?", (orden, tenant_id, pid))
        conn.commit()
    finally:
        conn.close()


def candidatos(tenant_id: int | None, tarea: str) -> list[dict]:
    """Los proveedores del despacho listos para usar en esa tarea, en orden: {proveedor, modelo, claves, url_base, origen}. Sin modelo para esa tarea (ni el del asistente como respaldo), no entra."""
    if tenant_id is None or tarea not in TAREAS:
        return []
    salida = []
    for p in listar(tenant_id):
        if not p["activo"] or not p["permitido"]:
            continue
        modelo = p["modelo_facturas"] or p["modelo_asistente"] if tarea == "facturas" else p["modelo_asistente"] or p["modelo_facturas"]
        claves = ia_claves.de_despacho(p["id"], tenant_id)
        if not modelo or (pv.obtener(p["id"]).pide_clave and not claves):
            continue
        salida.append({"proveedor": p["id"], "modelo": modelo, "claves": claves or [""], "url_base": p["url_base"] or None, "origen": "despacho"})
    return salida


def quitar_todo(tenant_id: int) -> None:
    """Borra las claves del despacho (al darlo de baja)."""
    for pid in pv.ORDEN:
        ia_claves.borrar_de_despacho(pid, tenant_id)
