"""El portal «nuevo» (U1-U12): una navegación de 5 secciones fijas (Inicio, Facturas, Documentos, Mensajes, Impuestos), pestañas dentro de cada una, la marca del despacho en la cabecera y un
menú de perfil con Mi cuenta, el idioma, la ayuda y salir.

Está **encendido por defecto** para todos los despachos (`portal_nuevo`, 1); cada despacho puede apagarlo y entonces el portal se ve exactamente como siempre. Las URL no
cambian: lo único que cambia es cómo se agrupan las pantallas, y por eso cada endpoint declara aquí a qué sección y pestaña pertenece."""
from __future__ import annotations

from . import db, marca

GRUPOS = ("inicio", "facturas", "documentos", "mensajes", "impuestos")

# endpoint (sin el prefijo «portal_cliente.») -> sección. Lo que no está aquí (Mi cuenta, Glosario, Buscar, las pantallas de entrada) no pertenece a ninguna sección de la barra.
_GRUPO_DE = {
    "dashboard": "inicio", "actividad": "inicio",
    "facturas": "facturas", "factura": "facturas", "justificantes_cliente": "facturas", "extracto": "facturas", "ventas": "facturas", "informe_trimestre": "facturas", "subida_rapida": "facturas",
    "mis_documentos": "documentos", "carpeta": "documentos", "dossier": "documentos", "peticiones": "documentos", "peticion": "documentos", "cuestionarios": "documentos", "cuestionario": "documentos",
    "documentos_vencimiento": "documentos", "enlace_compartido": "documentos",
    "mensajes": "mensajes", "conversacion": "mensajes", "conversacion_nueva": "mensajes", "mensajes_vencimiento": "mensajes", "avisos": "mensajes", "gestiones": "mensajes", "gestion": "mensajes",
    "propuestas": "mensajes", "propuesta": "mensajes", "asistente": "mensajes", "citas": "mensajes",
    "impuestos": "impuestos", "declaracion": "impuestos", "firmas": "impuestos", "firma_vencimiento": "impuestos", "honorarios_cliente": "impuestos", "trabajadores": "impuestos",
}
_SECCION_A_GRUPO = {"inicio": "inicio", "facturas": "facturas", "documentos": "documentos", "carpeta": "documentos", "mensajes": "mensajes", "avisos": "mensajes", "impuestos": "impuestos"}


def activo(tenant_id: int | None) -> bool:
    if tenant_id is None:
        return False
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT portal_nuevo FROM portal_recordatorios_config WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    return True if f is None else bool(f["portal_nuevo"])                      # sin configuración guardada, el despacho usa el valor por defecto: encendido


def fijar(tenant_id: int, activar: bool) -> None:
    conn = db.get_connection()
    try:
        if not conn.execute("SELECT 1 FROM portal_recordatorios_config WHERE tenant_id = ?", (tenant_id,)).fetchone():
            cfg = db.CONFIG_RECORDATORIOS_DEFECTO
            conn.execute("INSERT INTO portal_recordatorios_config (tenant_id, dias_antes, dias_despues, avisar_equipo, asunto, cuerpo, actualizado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (tenant_id, ",".join(str(x) for x in cfg["dias_antes"]), "", int(cfg["avisar_equipo"]), "", "", db.now_iso()))
        conn.execute("UPDATE portal_recordatorios_config SET portal_nuevo = ? WHERE tenant_id = ?", (1 if activar else 0, tenant_id))
        conn.commit()
    finally:
        conn.close()


def grupo_de(endpoint: str | None, seccion: str | None = None) -> str | None:
    """La sección de la barra a la que pertenece esta pantalla (None si es de Mi cuenta, Glosario, Buscar o la entrada)."""
    nombre = (endpoint or "").split(".", 1)[-1]
    return _GRUPO_DE.get(nombre) or _SECCION_A_GRUPO.get(seccion or "")


def marca_del_portal(tenant_id: int | None) -> dict:
    """{nombre, tiene_logo, color, version}: lo que el despacho ha elegido en «Marca del despacho» para enseñarlo en el portal (todo vacío si no ha personalizado nada)."""
    m = marca.obtener(tenant_id) or {}
    return {"nombre": m.get("nombre") or "", "tiene_logo": bool(m.get("tiene_logo")), "color": m.get("color") or "", "version": m.get("version") or ""}


def css_de_marca(color: str) -> str:
    """Las variables de color del portal nuevo a partir del acento del despacho, con el contraste calculado (relleno, texto sobre el relleno, acento como texto en claro y en oscuro y su fondo suave)."""
    if not color:
        return "/* sin marca */\n"
    d = marca.colores_derivados(color)
    suave_claro, suave_oscuro = marca._mezclar(d["primary"], "#ffffff", 0.88), marca._mezclar(d["primary"], "#000000", 0.78)
    fuera = marca.css({"color": color})                                          # --primary y compañía: los botones y enlaces de siempre toman también el color del despacho
    return (fuera + f":root {{ --portal-accent: {d['texto_claro']}; --portal-accent-bg: {suave_claro}; }}\n"
            f':root[data-theme="dark"] {{ --portal-accent: {d["texto_oscuro"]}; --portal-accent-bg: {suave_oscuro}; }}\n'
            f":root {{ --pv-accent: {d['primary']}; --pv-on-accent: {d['on_accent']}; --pv-accent-text: {d['texto_claro']}; --pv-accent-soft: {suave_claro}; }}\n"
            f':root[data-theme="dark"] {{ --pv-accent-text: {d["texto_oscuro"]}; --pv-accent-soft: {suave_oscuro}; }}\n'
            f"@media (prefers-color-scheme: dark) {{ :root:not([data-theme=\"light\"]) {{ --pv-accent-text: {d['texto_oscuro']}; --pv-accent-soft: {suave_oscuro}; }} }}\n")
