"""El asistente como soporte de la plataforma: busca en el centro de ayuda, lleva a la pantalla correcta y cambia los
ajustes de la propia cuenta. Las consultas de soporte (cómo se hace algo, dónde está, configurar mi cuenta, informar de
un error) NO cuentan en el límite mensual de IA del despacho: ver `es_consulta_soporte` y `ia_asistente._reservar_turno`."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import date
from pathlib import Path

from flask import url_for

from . import ayuda, db

IDIOMAS = ("es", "ca", "en", "fr")
# Tope diario de consultas de soporte gratuitas por persona: evita usar «cómo…» para charlar gratis con el modelo.
# Pasado el tope, la consulta cuenta como una normal (nunca se rechaza).
TOPE_DIARIO_GRATIS = 60

# Qué herramientas se ofrecen cuando el turno es de soporte: ninguna de las que leen o modifican datos de trabajo.
HERRAMIENTAS_SOPORTE = ("ayuda_buscar", "abrir_pantalla", "ver_mis_ajustes", "cambiar_mis_ajustes", "crear_tiquet",
                        "obtener_firma_correo", "configurar_firma_correo")


NOMBRES_EJECUTABLES = {"ayuda_buscar", "abrir_pantalla", "ver_mis_ajustes", "cambiar_mis_ajustes"}


def _plano(texto: str) -> str:
    sin = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in sin if unicodedata.category(c) != "Mn")


# --- ¿Es una consulta de soporte? ---------------------------------------------------------------------------------------------------------
_SOPORTE = re.compile(
    # castellano
    r"\b(como (puedo|hago|se |configuro|cambio|activo|desactivo|conecto|creo|uso|usar|anado|pongo|quito|exporto|importo|recupero|funciona|ficho|entro|instalo)"
    r"|donde (esta|estan|encuentro|puedo|se |cambio|configuro|veo|pongo)"
    r"|para que sirve|no funciona|no me deja|no puedo (entrar|acceder|iniciar|conectar|ver|cambiar|fichar|enviar|subir)"
    r"|no me (llega|aparece|sale)|necesito ayuda|ayuda con|ayudame a (configurar|cambiar|activar|conectar|entender)"
    r"|(quiero|quisiera|me gustaria) (configurar|cambiar|activar|desactivar|conectar|saber como)|configurar mi|configura mi|ajustes de mi"
    r"|centro de ayuda|tutorial|guia de|manual de|que (puedes|sabes) hacer"
    r"|(he )?(encontrado|visto|detectado) un (error|fallo|bug)|hay un (error|fallo|bug)|reportar|informar de un (error|fallo)"
    r"|(quiero|quisiera|me gustaria) (sugerir|proponer)|tengo una sugerencia|sugerencia para"
    # catalán
    r"|com (puc|faig|es |configuro|canvio|activo|desactivo|connecto|creo|uso|funciona|fitxo)|on (es troba|trobo|puc|es )|per a? ?que serveix|no funciona"
    r"|ajuda'?m a|vull (configurar|canviar|activar|desactivar|connectar)|he trobat un (error|bug)|tinc un suggeriment|necessito ajuda"
    # inglés
    r"|how (do|can|to|does) (i|it|this|you)|where (is|are|can i|do i)|what is .{0,30} for|not working|doesn't work|help me (set up|configure|change|enable|connect)"
    r"|i (want|would like) to (configure|change|set up|enable|disable|connect)|i need help|(found|there is) a (bug|error)|report (a )?(bug|problem)|i have a suggestion"
    # francés
    r"|comment (puis-je|faire|je |configurer|changer|activer|fonctionne)|ou (est|se trouve|puis-je|trouver)|ca ne marche pas|ne fonctionne pas|a quoi sert"
    r"|aide(z)?-?moi a|je veux (configurer|changer|activer|desactiver|connecter)|j'ai trouve un (bug|erreur)|j'ai une suggestion|j'ai besoin d'aide)\b"
)
_DATOS = re.compile(
    r"^\s*(lista|listame|muestra|muestrame|dame|resume|resumeme|crea|creame|envia|enviame|busca|marca|completa|elimina|borra|redacta|prepara|escribe|anade|apunta|recuerdame"
    r"|que (tareas|correos|notas|vencimientos|clientes)|llista|mostra|dona'?m|crea|cerca|resumeix|escriu|list|show|give me|create|send|find|summari[sz]e|write|liste|montre|donne|cree|envoie|cherche|resume|ecris)\b"
)


def es_consulta_soporte(texto: str | None) -> bool:
    plano = _plano(texto or "")
    if not plano.strip() or _DATOS.search(plano):
        return False
    return bool(_SOPORTE.search(plano))


def texto_ultimo_usuario(mensajes: list[dict] | None) -> str:
    for m in reversed(mensajes or []):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            return m["content"]
    return ""


# --- Tope diario de consultas gratuitas ---------------------------------------------------------------------------------------------------
def consumir_gratis(usuario_id: int, hoy: date | None = None) -> bool:
    """True si esta consulta de soporte entra en el cupo gratuito de hoy (y lo consume)."""
    dia = (hoy or date.today()).isoformat()
    conn = db.get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        fila = conn.execute("SELECT usadas FROM ia_soporte_uso WHERE usuario_id = ? AND dia = ?", (usuario_id, dia)).fetchone()
        if fila is not None and fila["usadas"] >= TOPE_DIARIO_GRATIS:
            conn.rollback()
            return False
        conn.execute(
            "INSERT INTO ia_soporte_uso (usuario_id, dia, usadas) VALUES (?, ?, 1) ON CONFLICT(usuario_id, dia) DO UPDATE SET usadas = usadas + 1",
            (usuario_id, dia),
        )
        conn.execute("DELETE FROM ia_soporte_uso WHERE dia < date(?, '-7 days')", (dia,))
        conn.commit()
        return True
    finally:
        conn.close()


# --- Pantalla en la que está la persona (la manda el navegador en la cabecera Referer) --------------------------------------------------------
_PANTALLA: dict[int, str] = {}


def recordar_pantalla(usuario_id: int, endpoint: str | None) -> None:
    """Endpoint de la pantalla desde la que se escribe (None si es el propio chat de página completa)."""
    if endpoint and not endpoint.startswith(("ia.", "static")):
        _PANTALLA[usuario_id] = endpoint
    else:
        _PANTALLA.pop(usuario_id, None)
    if len(_PANTALLA) > 5000:
        _PANTALLA.clear()


def pantalla_de(usuario_id: int) -> str | None:
    return _PANTALLA.get(usuario_id)


def endpoint_de_url(referer: str | None, app) -> str | None:
    """Endpoint de Flask al que corresponde una URL de la propia app (None si no es de aquí o no casa)."""
    from urllib.parse import urlparse

    if not referer:
        return None
    try:
        ruta = urlparse(referer).path
        with app.test_request_context(ruta):
            from flask import request

            return request.endpoint
    except Exception:  # noqa: BLE001 -- saber en qué pantalla está es un extra: nunca debe romper el chat
        return None


# --- Búsqueda en el centro de ayuda ---------------------------------------------------------------------------------------------------------
_CACHE: dict[str, tuple[float, list[dict]]] = {}
_VACIAS = {"de", "la", "el", "los", "las", "un", "una", "que", "como", "para", "por", "con", "en", "mi", "mis", "se", "es", "al", "del", "y", "o", "a", "lo", "me", "puedo", "hago",
           "the", "to", "how", "do", "i", "my", "of", "and", "is", "in", "comment", "je", "le", "les", "des", "du", "et", "pour", "mon", "ma", "com", "puc", "el", "els"}


def _ruta_indice(idioma: str) -> Path:
    raiz = Path(os.environ.get("GUILDA_AYUDA_INDICE_DIR") or "/home/guilda/guilda-help/salida")
    return (raiz / idioma / "indice.json") if idioma in ("ca", "en", "fr") else (raiz / "indice.json")


def _cargar_indice(idioma: str) -> list[dict]:
    ruta = _ruta_indice(idioma)
    try:
        mtime = ruta.stat().st_mtime
    except OSError:
        return []
    clave = str(ruta)
    if clave in _CACHE and _CACHE[clave][0] == mtime:
        return _CACHE[clave][1]
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    datos = [d for d in datos if isinstance(d, dict) and d.get("url") and d.get("titulo")]
    _CACHE[clave] = (mtime, datos)
    return datos


def _palabras(texto: str) -> list[str]:
    return [p for p in re.findall(r"[a-z0-9]{3,}", _plano(texto)) if p not in _VACIAS]


def _raiz(palabra: str) -> str:
    return palabra[:6]  # «configurar»/«configuro» -> «config»: tolera conjugaciones y plurales sin diccionario


def _fragmento(texto: str, palabras: list[str], largo: int = 450) -> str:
    plano = _plano(texto)
    mejor, pos = -1, 0
    ventana = 250
    for i in range(0, max(1, len(plano) - 1), 120):
        puntos = sum(1 for p in set(palabras) if _raiz(p) in plano[i:i + ventana])
        if puntos > mejor:
            mejor, pos = puntos, i
    ini = max(0, pos - 40)
    trozo = texto[ini:ini + largo].strip()
    return ("…" if ini else "") + trozo + ("…" if ini + largo < len(texto) else "")


def buscar_ayuda(consulta: str, idioma: str = "es", n: int = 3) -> list[dict]:
    """Los `n` artículos del centro de ayuda que mejor responden a la consulta: título, enlace completo y un fragmento."""
    idioma = idioma if idioma in IDIOMAS else "es"
    indice = _cargar_indice(idioma)
    palabras = _palabras(consulta)
    if not palabras or not indice:
        return []
    puntuados = []
    for art in indice:
        titulo, cat, texto = _plano(art["titulo"]), _plano(art.get("categoria", "")), art.get("texto") or ""
        puntos = 0.0
        for p in set(palabras):
            r = _raiz(p)
            puntos += 4 * (r in titulo) + 1.5 * (r in cat) + min(texto.count(r), 6) * 0.5
        if puntos > 0:
            puntuados.append((puntos, art))
    puntuados.sort(key=lambda x: -x[0])
    base = ayuda.base()
    prefijo = f"{base}/{idioma}" if idioma in ayuda.IDIOMAS else base
    return [{
        "titulo": art["titulo"], "categoria": art.get("categoria", ""), "enlace": prefijo + art["url"],
        "fragmento": _fragmento(art.get("texto") or art.get("extracto") or "", palabras),
    } for _, art in puntuados[:n]]


# --- Herramientas del chat -----------------------------------------------------------------------------------------------------------------
# destino -> (endpoint, ancla, qué es)
DESTINOS: dict[str, tuple[str, str, str]] = {
    "ajustes": ("ajustes", "", "Centro de ajustes: todo lo configurable, con buscador. Aquí también están el tema (claro/oscuro) y la densidad (normal/compacta)"),
    "perfil": ("ajustes_perfil", "", "Mi perfil: nombre, foto, cargo, teléfono"),
    "notificaciones": ("ajustes_perfil", "#notificaciones", "Notificaciones: qué avisos recibes y «no molestar»"),
    "seguridad": ("ajustes_cuenta", "", "Contraseña, email y verificación en dos pasos"),
    "dispositivos": ("mis_dispositivos", "", "Mis dispositivos con sesión iniciada"),
    "cuentas_correo": ("correo.cuentas", "", "Conectar o quitar cuentas de correo"),
    "ajustes_correo": ("correo.ajustes", "", "Firma, categorías, reglas y plantillas del correo"),
    "asistente_ia": ("ia.ajustes", "", "Ajustes del asistente de IA: modelo, claves, atajos, solo lectura"),
    "fichaje": ("fichaje.panel", "", "Fichar entrada y salida"),
    "fichaje_datos": ("fichaje.mis_datos", "", "Mis datos para el registro horario (nombre completo, DNI/NIE)"),
    "mi_historial_fichaje": ("fichaje.historial", "", "Mi historial de fichajes, con descarga en PDF"),
    "plantillas_tareas": ("tareas.plantillas", "", "Plantillas de tareas"),
    "tareas_recurrentes": ("tareas.recurrentes", "", "Tareas recurrentes"),
    "tiquets": ("tiquets.tarjetas", "", "Tiquets: errores y sugerencias"),
    "clientes_fiscales": ("fiscal.clientes", "", "Clientes fiscales y calendario de vencimientos"),
    "importar": ("importar", "", "Importar datos"),
    "exportar_historico": ("historial", "", "Histórico, con exportación a JSON, CSV, PDF y Markdown"),
    "papelera": ("papelera", "", "Papelera: recuperar lo borrado"),
    "herramientas": ("herramientas", "", "Catálogo de aplicaciones conectadas"),
}


def _origen() -> str:
    return (os.environ.get("GUILDA_ORIGIN") or "https://app.guildawork.com").rstrip("/")


def abrir_pantalla(usuario_id: int, destino: str) -> dict:
    """Enlace a una pantalla de la aplicación (no ejecuta nada)."""
    clave = (destino or "").strip().lower()
    if clave not in DESTINOS:
        return {"error": "Destino desconocido.", "destinos_validos": {k: v[2] for k, v in DESTINOS.items()}}
    endpoint, ancla, descripcion = DESTINOS[clave]
    try:
        ruta = url_for(endpoint, _external=False)
    except Exception:  # noqa: BLE001
        return {"error": "Esa pantalla no está disponible para esta cuenta."}
    return {"destino": clave, "descripcion": descripcion, "enlace": _origen() + ruta + ancla}


_CAMPOS_AVISOS = {
    "avisos_vencimientos": "notificar_push_vencimientos", "avisos_tiquets": "notificar_push_tiquets", "avisos_correo": "notificar_push_correo",
    "avisos_mensajes_portal": "notificar_push_portal_mensajes", "resumen_semanal": "notificar_resumen_semanal",
}


def ver_mis_ajustes(usuario_id: int) -> dict:
    perfil = db.obtener_perfil_usuario(usuario_id)
    return {
        "idioma": db.idioma_usuario(usuario_id) or "es (por defecto, según el navegador)",
        "nombre_mostrado": perfil["nombre_mostrado"], "cargo": perfil["cargo"], "telefono": perfil["telefono"],
        "avisos_vencimientos": bool(perfil["notificar_push_vencimientos"]), "avisos_tiquets": bool(perfil["notificar_push_tiquets"]),
        "avisos_correo": bool(perfil["notificar_push_correo"]), "avisos_mensajes_portal": bool(perfil["notificar_push_portal_mensajes"]),
        "resumen_semanal": bool(perfil["notificar_resumen_semanal"]),
        "no_molestar_desde": perfil["silencio_desde"], "no_molestar_hasta": perfil["silencio_hasta"],
        "tema": db.apariencia_usuario(usuario_id)["tema"] or "system (según el navegador)", "densidad": db.apariencia_usuario(usuario_id)["densidad"] or "normal",
        "no_se_cambia_desde_el_chat": "contraseña, email, verificación en dos pasos, dispositivos y administración: usa abrir_pantalla.",
    }


def cambiar_mis_ajustes(
    usuario_id: int, idioma: str | None = None, nombre_mostrado: str | None = None, cargo: str | None = None, telefono: str | None = None,
    avisos_vencimientos: bool | None = None, avisos_tiquets: bool | None = None, avisos_correo: bool | None = None,
    avisos_mensajes_portal: bool | None = None, resumen_semanal: bool | None = None,
    no_molestar_desde: str | None = None, no_molestar_hasta: str | None = None, quitar_no_molestar: bool = False,
    tema: str | None = None, densidad: str | None = None,
) -> dict:
    """Cambia SOLO ajustes de la cuenta de quien pregunta (nunca de otra persona, ni seguridad ni administración)."""
    hecho = []
    if idioma is not None:
        if idioma not in IDIOMAS:
            return {"error": f"Idioma no válido: usa uno de {', '.join(IDIOMAS)}."}
        db.cambiar_idioma_usuario(usuario_id, idioma)
        hecho.append("idioma")
    if tema is not None or densidad is not None:
        if (tema is not None and tema not in db.TEMAS_VALIDOS) or (densidad is not None and densidad not in db.DENSIDADES_VALIDAS):
            return {"error": "Tema: system, light o dark. Densidad: normal o compacta."}
        db.guardar_apariencia_usuario(usuario_id, tema, densidad)
        hecho.append("apariencia (se verá al recargar la página)")
    avisos = {
        "notificar_push_vencimientos": avisos_vencimientos, "notificar_push_tiquets": avisos_tiquets, "notificar_push_correo": avisos_correo,
        "notificar_push_portal_mensajes": avisos_mensajes_portal, "notificar_resumen_semanal": resumen_semanal,
    }
    avisos = {k: bool(v) for k, v in avisos.items() if v is not None}
    franja = {}
    if quitar_no_molestar:
        franja = {"silencio_desde": "", "silencio_hasta": ""}
        hecho.append("no molestar (desactivado)")
    elif no_molestar_desde is not None or no_molestar_hasta is not None:
        if not (db._hora_valida(no_molestar_desde) and db._hora_valida(no_molestar_hasta) and no_molestar_desde != no_molestar_hasta):
            return {"error": "«No molestar» necesita dos horas distintas en formato HH:MM (por ejemplo 22:00 y 08:00)."}
        franja = {"silencio_desde": no_molestar_desde, "silencio_hasta": no_molestar_hasta}
        hecho.append("no molestar")
    campos = {k: v for k, v in (("nombre_mostrado", nombre_mostrado), ("cargo", cargo), ("telefono", telefono)) if v is not None}
    if campos or avisos or franja:
        db.guardar_perfil_usuario(usuario_id, **campos, **avisos, **franja)
        hecho += [k.replace("_", " ") for k in campos] + [k.replace("notificar_push_", "avisos de ").replace("notificar_", "").replace("_", " ") for k in avisos]
    if not hecho:
        return {"error": "No se ha indicado ningún ajuste que cambiar."}
    return {"cambiado": hecho, "ajustes_ahora": ver_mis_ajustes(usuario_id)}


def ejecutar(usuario_id: int, nombre: str, argumentos: dict):
    idioma = db.idioma_usuario(usuario_id) or "es"
    if nombre == "ayuda_buscar":
        resultados = buscar_ayuda(str(argumentos.get("consulta") or ""), idioma)
        if not resultados:
            return {"resultados": [], "aviso": "La ayuda no cubre esto. Ofrece registrar un tiquet (error o sugerencia) y no inventes la respuesta."}
        return {"resultados": resultados}
    if nombre == "abrir_pantalla":
        return abrir_pantalla(usuario_id, str(argumentos.get("destino") or ""))
    if nombre == "ver_mis_ajustes":
        return ver_mis_ajustes(usuario_id)
    if nombre == "cambiar_mis_ajustes":
        return cambiar_mis_ajustes(usuario_id, **argumentos)
    raise ValueError(f"Herramienta de soporte desconocida: {nombre}")
