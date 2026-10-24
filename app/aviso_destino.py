"""A dónde lleva cada aviso en la app móvil (S-05 del plan de la app móvil, Apéndice B) y en qué canal de Android se muestra.

Los avisos se emiten desde ~38 sitios con `datos` irregulares (a veces solo el `tipo`, a veces un id suelto) y casi siempre con la `url` de la web. Aquí se
unifica en un **destino** `{tipo, id, ...}` (los mismos tipos que `GET /hoy`), deducido, por este orden, de los ids de `datos`, de la `url` y del `tipo` del aviso.
Nada de esto cambia a quien emite: lo aplica `notificaciones.crear_y_enviar`, el único punto de entrada.

El destino viaja en el push (`data.destino`, JSON) y se calcula también al listar `GET /notificaciones`, para que tocar un aviso (o abrir uno de la bandeja)
lleve siempre a la pantalla exacta."""
from __future__ import annotations

import re

# Ids sueltos que algunos emisores ponen en `datos`: clave → tipo de destino.
_IDS_DE_DATOS = (
    ("tarea_id", "tarea"), ("vencimiento_id", "vencimiento"), ("expediente_id", "expediente"), ("certificado_id", "certificado"),
    ("mensaje_id", "correo"), ("alerta_id", "aviso_fiscal"), ("tiquet_id", "tiquet"), ("nota_id", "nota"), ("factura_contable_id", "factura_contable"),
)

# Rutas de la web con un id: (patrón, tipo de destino). Se usan cuando el emisor no puso el id en `datos`.
_URLS = (
    (re.compile(r"/tareas/(\d+)"), "tarea"),
    (re.compile(r"/fiscal/vencimientos/(\d+)"), "vencimiento"),
    (re.compile(r"/expedientes/(\d+)"), "expediente"),
    (re.compile(r"/certificados/(\d+)"), "certificado"),
    (re.compile(r"/contabilidad/(\d+)"), "factura_contable"),
    (re.compile(r"/correo/(?:mensaje|equipo)/(\d+)"), "correo"),
)

# Avisos sin id: llevan a una pantalla (no a un elemento).
_PANTALLAS = {
    "ausencia": "ausencias", "turno": "turnos", "bolsa_horas": "bolsa_horas", "fichaje_salida_olvidada": "fichaje", "traspaso": "traspasos",
    "resumen_diario": "hoy", "resumen_ia_semanal": "ia", "correo_nuevo": "correo", "correo_envio_fallido": "correo", "correo_sin_respuesta": "correo",
}

# Familias de avisos = canales de notificación de Android (la persona silencia cada familia por separado).
CANALES = ("tareas", "correo", "fiscal", "equipo", "resumenes", "general")
_CANAL_DE_TIPO = {
    "tarea_asignada": "tareas", "tarea_compartida": "tareas", "tarea_comentario": "tareas", "tarea_desbloqueada": "tareas", "tarea_recordatorio": "tareas",
    "revision_tarea": "tareas", "nota_compartida": "tareas", "tiquet_asignado": "tareas", "automatizacion": "tareas", "automatizacion_fallo": "tareas",
    "correo_nuevo": "correo", "correo_equipo": "correo", "correo_sin_respuesta": "correo", "correo_envio_fallido": "correo",
    "vencimiento_fiscal": "fiscal", "obligacion": "fiscal", "aviso_fiscal": "fiscal", "traspaso": "fiscal", "expediente": "fiscal", "mencion": "fiscal",
    "certificado": "fiscal", "portal_mensaje_nuevo": "fiscal", "portal_sin_documentos": "fiscal", "portal_comentario_tarea": "fiscal", "antivirus": "fiscal",
    "ausencia": "equipo", "turno": "equipo", "bolsa_horas": "equipo", "fichaje_salida_olvidada": "equipo",
    "resumen_diario": "resumenes", "resumen_ia_semanal": "resumenes",
}


# Resultados de la búsqueda global (`GET /buscar`): tipo del documento indexado → tipo de destino.
_DESTINO_DE_RESULTADO = {"nota": "nota", "tarea": "tarea", "mensaje": "correo", "vencimiento_fiscal": "vencimiento", "cliente_fiscal": "cliente_fiscal"}


def destino_de_resultado(resultado: dict) -> dict:
    """Destino de un resultado de búsqueda. El índice guarda `id` como «tipo-N» (p. ej. `tarea-12`); aquí se saca el N."""
    m = re.search(r"-(\d+)$", str(resultado.get("id", "")))
    tipo = _DESTINO_DE_RESULTADO.get(resultado.get("tipo"))
    return {"tipo": tipo, "id": int(m.group(1))} if tipo and m else {"tipo": "aviso"}


def canal_de(tipo: str | None) -> str:
    return _CANAL_DE_TIPO.get(tipo or "", "general")


def destino_de(tipo: str | None, datos: dict | None = None, url: str | None = None) -> dict:
    """`{tipo, id?, ...}`. `tipo` es el del aviso (el de `datos["tipo"]` si lo hay, que es el más específico). Sin nada más concreto: `{"tipo": "aviso"}` (abre la bandeja de avisos)."""
    datos = datos or {}
    especifico = datos.get("tipo") or tipo
    extra = {k: datos[k] for k in ("cuenta_id", "mensaje_id", "expediente_id", "vencimiento_id") if datos.get(k) is not None}
    for clave, destino in _IDS_DE_DATOS:
        if datos.get(clave) is not None:
            return {"tipo": destino, "id": int(datos[clave]), **{k: v for k, v in extra.items() if k != clave}}
    for patron, destino in _URLS:
        m = patron.search(url or "")
        if m:
            return {"tipo": destino, "id": int(m.group(1))}
    if especifico in _PANTALLAS:
        return {"tipo": _PANTALLAS[especifico], **({"cuenta_id": datos["cuenta_id"]} if datos.get("cuenta_id") is not None else {})}
    if (url or "").startswith("/fiscal/avisos"):
        return {"tipo": "aviso_fiscal"}
    return {"tipo": "aviso"}
