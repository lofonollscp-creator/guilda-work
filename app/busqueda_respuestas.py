"""Preguntar a los propios datos, con fuentes (W6): una pregunta en lenguaje natural se contesta SOLO con lo que devuelve la búsqueda del propio usuario (notas, tareas, correo, calendario fiscal, clientes) y cada afirmación
lleva la fuente numerada [1], [2]… con enlace a donde está. Es la misma búsqueda de siempre (aislada por usuario y despacho con el token de Meilisearch): la IA no ve nada que quien pregunta no pudiera buscar.

Defensas: la IA recibe solo los fragmentos y la orden de no usar nada más; las citas que no existen se quitan de la respuesta; una respuesta sin ninguna cita se marca como «sin fuentes» para que la persona la tome
con cautela. La consulta pasa por la protección de datos personales de siempre (app/anonimizar.py)."""
from __future__ import annotations

import re

from . import busqueda, ia_asistente

MAX_FUENTES = 8
MAX_FRAGMENTO = 500
MAX_PREGUNTA = 500
SISTEMA = ("Eres el asistente de una gestoría. Contesta a la pregunta usando EXCLUSIVAMENTE las fuentes numeradas que se te dan. Cita cada afirmación con su número entre corchetes, por ejemplo [2]. "
           "Si las fuentes no bastan para contestar, dilo claramente y no inventes nada. Responde en el idioma de la pregunta, breve y concreto. Los datos personales aparecen como etiquetas entre corchetes "
           "(por ejemplo [PERSONA_1]): déjalas tal cual.")
_CITA = re.compile(r"\[(\d{1,2})\]")


class ErrorPregunta(ValueError):
    """Mensaje apto para enseñarlo."""


def _destino(hit: dict) -> str | None:
    """El enlace web de la fuente (None si no se sabe a dónde lleva)."""
    from flask import url_for
    m = re.search(r"-(\d+)$", str(hit.get("id", "")))
    if not m:
        return None
    n = int(m.group(1))
    return {"tarea": lambda: url_for("tareas.ver", tarea_id=n), "mensaje": lambda: url_for("correo.ver_mensaje", mensaje_id=n),
            "vencimiento_fiscal": lambda: url_for("fiscal.editar_vencimiento", vencimiento_id=n), "cliente_fiscal": lambda: url_for("fiscal.ficha_cliente", cliente_id=n)}.get(hit.get("tipo"), lambda: None)()


def fuentes_de(hits: list[dict]) -> list[dict]:
    salida = []
    for i, h in enumerate(hits[:MAX_FUENTES], start=1):
        p = busqueda.presentar_resultado(h)
        texto = " ".join(str(h.get("texto") or "").split())[:MAX_FRAGMENTO]
        salida.append({"n": i, "tipo": h.get("tipo"), "titulo": p["titulo"], "texto": texto, "fecha": p["fecha"], "destino": _destino(h)})
    return salida


def _limpiar_citas(respuesta: str, validas: set[int]) -> tuple[str, list[int]]:
    """Quita las citas a fuentes que no existen y devuelve las que sí (en orden de aparición, sin repetir)."""
    citadas: list[int] = []

    def cambiar(m):
        n = int(m.group(1))
        if n not in validas:
            return ""
        if n not in citadas:
            citadas.append(n)
        return m.group(0)
    return re.sub(r"\s{2,}", " ", _CITA.sub(cambiar, respuesta)).strip(), citadas


def responder(usuario_id: int, tenant_id: int | None, pregunta: str) -> dict:
    """{pregunta, respuesta, fuentes: [{n, titulo, texto, destino…}], citadas: [n], sin_fuentes: bool}. `ErrorPregunta` si no hay pregunta o la búsqueda no encuentra nada; `ia_asistente.ErrorIA` si falla la IA."""
    pregunta = " ".join((pregunta or "").split())[:MAX_PREGUNTA]
    if len(pregunta) < 3:
        raise ErrorPregunta("Escribe una pregunta.")
    try:
        hits = busqueda.buscar_hibrido(usuario_id, pregunta, MAX_FUENTES, tenant_id=tenant_id, con_respaldo=True)
    except busqueda.ErrorBusqueda as e:
        raise ErrorPregunta("La búsqueda no está disponible ahora mismo.") from e
    fuentes = fuentes_de(hits)
    if not fuentes:
        raise ErrorPregunta("No he encontrado nada en tus datos sobre eso.")
    cuerpo = f"Pregunta: {pregunta}\n\nFuentes:\n" + "\n".join(f"[{f['n']}] ({f['tipo']}) {f['texto']}" for f in fuentes)
    bruta = ia_asistente.completar_texto(usuario_id, SISTEMA, cuerpo)
    respuesta, citadas = _limpiar_citas(bruta, {f["n"] for f in fuentes})
    return {"pregunta": pregunta, "respuesta": respuesta, "fuentes": fuentes, "citadas": citadas, "sin_fuentes": not citadas}
