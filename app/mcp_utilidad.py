"""Piezas que hacen el MCP más útil para un modelo: respuestas que no se comen el contexto (recorte con aviso), `tenant` opcional (por
defecto, tu propio despacho), y prompts y recursos MCP además de herramientas. Lo usa `mcp_tools.registrar_tools`."""
from __future__ import annotations

import inspect
import json
import os
from typing import Optional


def _entero_env(nombre: str, defecto: int) -> int:
    try:
        return max(200, int(os.environ.get(nombre, defecto)))
    except ValueError:
        return defecto


def limites_de_respuesta() -> tuple[int, int]:
    """(caracteres máximos por texto, caracteres máximos por respuesta). `GUILDA_MCP_MAX_TEXTO` y `GUILDA_MCP_MAX_CHARS`."""
    return _entero_env("GUILDA_MCP_MAX_TEXTO", 12000), _entero_env("GUILDA_MCP_MAX_CHARS", 60000)


def _recortar_textos(valor, max_texto: int, cuenta: dict):
    if isinstance(valor, str):
        if len(valor) > max_texto:
            cuenta["textos"] += 1
            return valor[:max_texto] + f"\n… [recortado: {len(valor)} caracteres en total; se muestran {max_texto}]"
        return valor
    if isinstance(valor, list):
        return [_recortar_textos(v, max_texto, cuenta) for v in valor]
    if isinstance(valor, dict):
        return {k: _recortar_textos(v, max_texto, cuenta) for k, v in valor.items()}
    return valor


def recortar_resultado(valor, max_texto: int | None = None, max_total: int | None = None):
    """Evita que una herramienta devuelva un correo larguísimo o un listado enorme y llene el contexto del modelo. Los textos largos se
    cortan con un aviso que dice cuánto había; un listado que no cabe se corta y termina con un elemento `{"_truncado": true, ...}` que
    dice cuántos había y cómo pedir menos (filtros o `limite`). Lo que cabe se devuelve tal cual."""
    por_defecto_texto, por_defecto_total = limites_de_respuesta()
    max_texto, max_total = max_texto or por_defecto_texto, max_total or por_defecto_total
    cuenta = {"textos": 0}
    valor = _recortar_textos(valor, max_texto, cuenta)
    try:
        tamano = len(json.dumps(valor, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return valor
    if tamano <= max_total or not isinstance(valor, list) or not valor or not all(isinstance(x, dict) for x in valor):
        return valor
    mostrados, usado = [], 0
    for elemento in valor:
        usado += len(json.dumps(elemento, ensure_ascii=False, default=str))
        if usado > max_total * 0.9 and mostrados:
            break
        mostrados.append(elemento)
    n = len(mostrados)
    mostrados.append({"_truncado": True, "total": len(valor), "mostrados": n,
                      "aviso": f"Respuesta recortada: había {len(valor)} elementos y se muestran {n}. Pide menos con un filtro, un rango de fechas o `limite`."})
    return mostrados


def firma_con_tenant_opcional(firma: inspect.Signature) -> inspect.Signature | None:
    """Si la herramienta pide `tenant` obligatorio, la firma pública lo deja como opcional (por defecto, tu despacho) y al final, solo por
    nombre. `None` si no hace falta tocar nada."""
    p = firma.parameters.get("tenant")
    if p is None or p.default is not inspect.Parameter.empty:
        return None
    resto = [q for n, q in firma.parameters.items() if n != "tenant"]
    nuevo = inspect.Parameter("tenant", inspect.Parameter.KEYWORD_ONLY, default=None, annotation=Optional[str])
    return firma.replace(parameters=resto + [nuevo])


NOTA_TENANT = "\n\n`tenant` es opcional: si no lo indicas se usa tu propio despacho (solo un administrador necesita nombrarlo)."


# --- Prompts: tareas habituales listas para usar en el cliente MCP ---------------------------------------------------------------------
def prompt_resumen_del_dia() -> str:
    """Qué tengo hoy: tareas, vencimientos de la semana, correo y avisos, ordenado por urgencia."""
    return ("Prepárame el resumen de mi día en Guilda Work. Usa la herramienta `resumen_del_dia` y, con lo que devuelva, dime: 1) lo urgente de hoy "
            "(tareas vencidas y de hoy), 2) los vencimientos fiscales de los próximos 7 días con su cliente, 3) cuántos correos sin leer tengo y si "
            "alguno parece importante (puedes mirar la bandeja con `listar_bandeja_entrada`), 4) cualquier aviso nuevo. Termina con las 3 cosas que "
            "yo haría primero. Sé breve y concreto, con listas.")


def prompt_ficha_cliente(cliente: str) -> str:
    """Ficha completa de un cliente fiscal: datos, vencimientos, tareas y correos recientes."""
    return (f"Hazme una ficha del cliente fiscal «{cliente}». Búscalo con `listar_clientes_fiscales` (texto: {cliente!r}); si hay varios parecidos, "
            "pregúntame cuál. Con su id usa `resumen_cliente_fiscal`, `listar_vencimientos_fiscales` (cliente_id) y `buscar_semantico` para notas "
            "y correos relacionados. Resume: quién es y qué modelos presenta, qué tiene pendiente y para cuándo, qué se ha hablado últimamente y "
            "qué falta pedirle. No inventes nada que no salga de las herramientas.")


def prompt_preparar_vencimiento(cliente: str, modelo: str) -> str:
    """Prepara la presentación de un modelo (p. ej. 303) para un cliente: qué falta y qué tareas crear."""
    return (f"Prepara la presentación del modelo {modelo} de «{cliente}». Localiza al cliente con `listar_clientes_fiscales`, mira su vencimiento "
            f"pendiente del modelo {modelo} con `listar_vencimientos_fiscales` y revisa si hay documentación pedida o mensajes suyos. Dime qué falta "
            "y propón (sin crearlas todavía) las tareas necesarias con fecha. Si te digo que sí, créalas con `crear_tarea` y, si el vencimiento ya "
            "está hecho, márcalo con `marcar_presentado_vencimiento_fiscal` — pidiéndome confirmación antes de marcar nada.")


def prompt_revisar_correo() -> str:
    """Revisa el correo pendiente, clasifica lo importante y propone respuestas."""
    return ("Revisa mi correo pendiente. Lista la bandeja con `listar_bandeja_entrada` (solo lo no leído), lee los que parezcan importantes con "
            "`leer_correo` y clasifícalos en: urgente, responder esta semana, informativo y ruido. Para los urgentes, propón una respuesta corta con "
            "`preparar_borrador_correo` — sin enviar nada. Si algún correo pide un documento o fecha, sugiere crear una tarea con "
            "`crear_tarea_desde_correo`.")


def prompt_cierre_de_trimestre(modelo: str, periodo: str) -> str:
    """Qué clientes tienen pendiente un modelo en un periodo, para organizar el cierre."""
    return (f"Quiero organizar el cierre del modelo {modelo} del periodo {periodo}. Con `listar_vencimientos_fiscales` (estado pendiente) saca los "
            f"vencimientos del modelo {modelo} de ese periodo, agrúpalos por semana de fecha límite y dime cuántos hay por responsable. Señala los que "
            "ya tienen documentación pedida y no se ha recibido. Propón un reparto del trabajo por días.")


PROMPTS = (
    ("resumen_del_dia_prompt", prompt_resumen_del_dia), ("ficha_cliente", prompt_ficha_cliente), ("preparar_vencimiento", prompt_preparar_vencimiento),
    ("revisar_correo", prompt_revisar_correo), ("cierre_de_trimestre", prompt_cierre_de_trimestre),
)

# --- Recursos: datos que el cliente puede adjuntar a la conversación sin llamar a una herramienta ------------------------------------------
# (uri, nombre, descripción, herramienta que los produce)
RECURSOS = (
    ("guilda://resumen-del-dia", "Resumen del día", "Tareas de hoy, vencimientos de 7 días, correo y avisos sin leer.", "resumen_del_dia"),
    ("guilda://proyectos", "Mis proyectos", "Los proyectos propios (donde se agrupan notas y tareas).", "listar_proyectos"),
    ("guilda://tareas/hoy", "Mi día", "Tareas vencidas, de hoy, en curso y asignadas.", "listar_tareas_hoy"),
    ("guilda://fiscal/clientes", "Clientes fiscales", "Los clientes fiscales del despacho.", "listar_clientes_fiscales"),
    ("guilda://consumo-ia", "Consumo de IA", "Consultas de IA del mes del despacho y su tope.", "consumo_ia"),
)
