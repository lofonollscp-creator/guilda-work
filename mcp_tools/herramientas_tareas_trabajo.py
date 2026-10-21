"""Herramientas MCP (y del asistente de IA) del trabajo con tareas: cambiar el estado con motivo, subtareas, clientes de una tarea, tareas de un cliente, archivos adjuntos (solo la lista),
revisiones, el informe y las reglas de automatización (solo consulta y simulación).

La lógica está en `app/tareas_trabajo.py`, `app/informes_tareas.py` y `app/automatizaciones.py`, la misma que usan la web y la API: mismos permisos, mismo aislamiento por despacho y mismas
reglas de cierre (una tarea con subtareas abiertas o con una revisión pendiente no se completa). Nada de aquí cambia lo que ve un cliente en su portal ni crea o borra reglas de
automatización: esas decisiones son de una persona. Un error de negocio llega como ValueError con un texto claro."""
from __future__ import annotations

import mcp_tools as _mt


def _tt():
    from app import tareas_trabajo
    return tareas_trabajo


def _como_error(e: Exception) -> ValueError:
    tt = _mt._tt()
    if isinstance(e, tt.ConflictoDeVersion):
        return ValueError(f"La tarea ha cambiado desde que la leíste (versión actual: {e.actual}). Vuelve a leerla y repite el cambio.")
    return ValueError(str(e))


def _tarea_visible(tarea_id: int):
    tarea = _mt.db.obtener_tarea_outlook_visible(_mt._uid(), tarea_id)
    if tarea is None:
        raise ValueError(f"No existe la tarea {tarea_id} (o no puedes verla).")
    return tarea


def cambiar_estado_tarea_con_motivo(tarea_id: int, estado: str, motivo: str | None = None, version: int | None = None) -> dict:
    """Cambia el estado de una tarea (no_iniciada, en_progreso, completada, esperando o aplazada). `esperando` (bloqueada) exige `motivo`. Con `version` (la que devuelve detalle_tarea) solo vale si
    nadie ha tocado la tarea antes. No completa una tarea con subtareas abiertas ni con una revisión pendiente."""
    _mt._tarea_visible(tarea_id)
    tt = _mt._tt()
    try:
        tt.transicionar(_mt._uid(), tarea_id, (estado or "").strip(), motivo, tt.version_pedida(version))
    except (tt.TransicionInvalida, tt.ConflictoDeVersion) as e:
        raise _mt._como_error(e) from e
    t = _mt.db.obtener_tarea_outlook_visible(_mt._uid(), tarea_id)
    return {"id": tarea_id, "estado": t["estado"], "motivo_bloqueo": t["motivo_bloqueo"], "version": t["version"]}


def listar_subtareas_tarea(tarea_id: int) -> dict:
    """Las subtareas de una tarea (un nivel) con su progreso. La tarea no se puede completar hasta que se completen."""
    _mt._tarea_visible(tarea_id)
    subtareas = _mt._tt().subtareas_de(tarea_id)
    return {"subtareas": subtareas, "progreso": _mt._tt().progreso_subtareas(subtareas)}


def crear_subtarea(tarea_id: int, asunto: str, fecha_vencimiento: str | None = None, asignada_a: int | None = None) -> dict:
    """Añade una subtarea a una tarea (hereda su cliente y proyecto). Solo un nivel; no sobre una tarea completada."""
    _mt._tarea_visible(tarea_id)
    tt = _mt._tt()
    try:
        nueva = tt.crear_subtarea(_mt._uid(), tarea_id, asunto, fecha_vencimiento, asignada_a)
    except tt.TransicionInvalida as e:
        raise _mt._como_error(e) from e
    return _mt._fila(_mt.db.obtener_tarea_outlook_visible(_mt._uid(), nueva))


def listar_clientes_de_tarea(tarea_id: int) -> dict:
    """Los clientes a los que está vinculada una tarea, con el principal marcado."""
    _mt._tarea_visible(tarea_id)
    return {"clientes": _mt._tt().clientes_de_tarea(tarea_id)}


def fijar_clientes_de_tarea(tarea_id: int, cliente_ids: list[int], principal_id: int | None = None, version: int | None = None) -> dict:
    """Sustituye los clientes de una tarea (lista vacía = tarea interna). Solo clientes de tu despacho; un único principal (`principal_id` o el primero)."""
    _mt._tarea_visible(tarea_id)
    tt = _mt._tt()
    try:
        clientes = tt.fijar_clientes(_mt._uid(), tarea_id, list(cliente_ids or []), principal_id, tt.version_pedida(version))
    except (tt.TransicionInvalida, tt.ConflictoDeVersion) as e:
        raise _mt._como_error(e) from e
    return {"clientes": clientes, "version": tt.version_de(tarea_id)}


def listar_tareas_de_cliente(cliente_fiscal_id: int, estado: str | None = None, solo_vencidas: bool = False) -> dict:
    """Las tareas de un cliente que puedes ver (principal o vinculado), con los contadores abiertas, vencidas y completadas calculados sobre toda la lista."""
    tenant = _mt._tenant_id_actual()
    if _mt.db.obtener_cliente_fiscal(tenant, cliente_fiscal_id) is None:
        raise ValueError(f"No existe el cliente fiscal {cliente_fiscal_id} en tu despacho.")
    tt = _mt._tt()
    todas = [dict(t) for t in _mt.db.listar_tareas_outlook(_mt._uid(), incluir_asignadas=True, cliente_fiscal_id=cliente_fiscal_id)]
    contadores = tt.contadores_de_cliente(todas)
    filas = []
    for t in todas:
        t["vencida"] = tt.esta_vencida(t["fecha_vencimiento"], t["estado"])
        if (estado and t["estado"] != estado) or (solo_vencidas and not t["vencida"]):
            continue
        filas.append({k: t[k] for k in ("id", "asunto", "estado", "prioridad", "fecha_vencimiento", "vencida", "motivo_bloqueo") if k in t})
    filas.sort(key=lambda t: (t["estado"] == "completada", t["fecha_vencimiento"] or "9999", t["id"]))
    return {"tareas": filas[:200], "contadores": contadores}


def listar_adjuntos_tarea(tarea_id: int) -> list[dict]:
    """Los archivos adjuntos de una tarea (nombre, tipo y tamaño). El contenido se descarga desde la web o la API."""
    _mt._tarea_visible(tarea_id)
    return _mt._tt().listar_adjuntos(tarea_id)


def listar_revisiones_tarea(tarea_id: int) -> dict:
    """La revisión pendiente de una tarea (quién la revisa) y las últimas resueltas."""
    _mt._tarea_visible(tarea_id)
    return {"pendiente": _mt._tt().revision_pendiente(tarea_id), "historial": _mt._tt().historial_de_revisiones(tarea_id)}


def pedir_revision_tarea(tarea_id: int, revisor_id: int | None = None, nota: str | None = None, revisor_ids: list[int] | None = None, modo: str = "todos") -> dict:
    """Pide que otra persona de tu despacho —o varias, hasta cinco, con `revisor_ids`— revise la tarea (se les avisa y se les comparte para que la vean). `modo`: «todos» (aprueban todos, por defecto)
    o «cualquiera» (basta uno); una petición de cambios, de quien sea, detiene la revisión. Mientras esté pendiente la tarea no se puede completar."""
    _mt._tarea_visible(tarea_id)
    tt = _mt._tt()
    try:
        tt.solicitar_revision(_mt._uid(), tarea_id, revisor_ids if revisor_ids else revisor_id, nota, modo or "todos")
    except tt.TransicionInvalida as e:
        raise _mt._como_error(e) from e
    return {"pendiente": tt.revision_pendiente(tarea_id)}


def resolver_revision_tarea(tarea_id: int, decision: str, nota: str | None = None) -> dict:
    """El voto de una persona designada para revisar (cada una vota una vez). `decision`: aprobar (no completa la tarea; con varios revisores en modo «todos» la revisión sigue pendiente hasta que aprueben todos)
    o cambios (exige `nota`, detiene la revisión y devuelve la tarea a en progreso)."""
    _mt._tarea_visible(tarea_id)
    tt = _mt._tt()
    try:
        r = tt.resolver_revision(_mt._uid(), tarea_id, (decision or "").strip(), nota)
    except tt.TransicionInvalida as e:
        raise _mt._como_error(e) from e
    return {"revision": r}


def informe_tareas(desde: str | None = None, hasta: str | None = None, dias_proximos: int = 14) -> dict:
    """Informe de tareas: abiertas, vencidas y completadas por persona y por cliente, cumplimiento en plazo, tiempo medio de cierre, bloqueos y lo que se acerca. Solo las tareas que puedes ver.
    `desde` y `hasta` (AAAA-MM-DD, por defecto los últimos 30 días, máximo 366) acotan lo histórico; lo de «ahora» es la foto de hoy."""
    from app import informes_tareas
    return informes_tareas.informe(_mt._tenant_id_actual(), _mt._uid(), desde, hasta, dias_proximos or 14)


def _direccion() -> int:
    from app import acceso
    if not acceso.es_directivo(_mt._uid()):
        raise ValueError("Solo la dirección del despacho consulta las automatizaciones.")
    return _mt._tenant_id_actual()


def listar_reglas_automatizacion() -> list[dict]:
    """Las reglas de automatización del despacho (disparador, condiciones, acciones y si están activas). Solo la dirección."""
    from app import automatizaciones
    return automatizaciones.listar_reglas(_mt._direccion())


def simular_regla_automatizacion(regla_id: int) -> dict:
    """Qué haría una regla ahora (cuántos casos cumplen y ejemplos), sin crear ni enviar nada. Solo la dirección."""
    from app import automatizaciones
    try:
        return automatizaciones.simular(_mt._direccion(), regla_id)
    except LookupError as e:
        raise ValueError(str(e)) from e


def listar_ejecuciones_automatizacion(estado: str | None = None, limite: int = 30) -> list[dict]:
    """Las últimas ejecuciones de las reglas, con su estado (ok, error, fallida o pendiente) y el error si lo hubo. Solo la dirección."""
    from app import automatizaciones
    return automatizaciones.ejecuciones(_mt._direccion(), estado=estado or None, limite=limite)
