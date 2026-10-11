"""Lo que el código no dice por sí solo y hay que saber para documentar bien la API: tipos y descripciones de campos, qué esquema
devuelve cada ruta, esquemas «a medida» y ejemplos. El generador (`openapi.py`) deriva de las vistas todo lo demás; aquí solo hay lo
que aporta una persona. Los esquemas de las entidades (Nota, TareaOutlook, ClienteFiscal...) se construyen leyendo las columnas de
las tablas reales, así que cuando se añade una columna aparece sola en el contrato."""
from __future__ import annotations

# --- Entidades: componente -> (tabla, columnas que NUNCA se exponen, propiedades extra) ----------------------------------------
TABLAS: dict[str, tuple[str, tuple[str, ...], dict]] = {
    "Nota": ("notas", (), {"categoria_nombre": {"type": "string", "nullable": True}, "dueno_nombre": {"type": "string", "nullable": True}}),
    "TareaConDuracion": ("tareas", (), {}),
    "TareaOutlook": ("tareas_outlook", (), {"categoria_nombre": {"type": "string", "nullable": True}, "categoria_color": {"type": "string", "nullable": True}}),
    "Proyecto": ("categorias", (), {}),
    "ClienteFiscal": ("clientes_fiscales", (), {"modelos_fiscales": {"type": "string", "nullable": True, "description": "Modelos que se le generan, **serializados como JSON** (p. ej. `[\"303\",\"130\"]`). Solo `GET /fiscal/clientes/{id}` los devuelve ya como lista (`ClienteFiscalDetalle`); al enviarlos siempre es una lista."}}),
    "Vencimiento": ("vencimientos_fiscales", (), {"cliente_nombre": {"type": "string"}}),
    "DocumentoVencimiento": ("vencimientos_fiscales_documentos", ("contenido", "nextcloud_ruta", "nextcloud_path"), {}),
    "MensajeVencimiento": ("vencimientos_fiscales_mensajes", (), {}),
    "DocumentoCliente": ("cliente_documentos", ("contenido", "huella"), {}),
    "Webhook": ("webhooks", ("secreto",), {"eventos": {"type": "array", "items": {"type": "string"}}}),
    "Notificacion": ("notificaciones", (), {}),
    "Fichaje": ("fichajes", (), {}),
    "Tiquet": ("tiquets", (), {}),
    "PlantillaCorreo": ("correo_plantillas", (), {}),
    "CuentaCorreo": ("correo_cuentas", ("contrasena", "token_oauth", "refresh_token"), {}),
    "MensajeCorreo": ("correo_mensajes", ("cuerpo_html",), {}),
    "EnvioCorreo": ("correo_envios", ("cuerpo_html",), {}),
    "AdjuntoNota": ("notas_adjuntos", ("contenido",), {}),
    "ChecklistItem": ("tarea_checklist", (), {}),
    "ComentarioTarea": ("tarea_comentarios", (), {}),
    "RecordatorioTarea": ("tarea_recordatorios", (), {}),
    "ReglaRecurrente": ("tareas_recurrentes", (), {}),
    "ReglaVencimiento": ("tareas_por_vencimiento", (), {"generadas": {"type": "integer"}}),
    "SeguimientoCorreo": ("correo_seguimientos", (), {}),
    "ConversacionIA": ("ia_conversaciones", (), {}),
    "MensajeIA": ("ia_mensajes", (), {}),
    "AtajoIA": ("ia_atajos", (), {}),
    "PreferenciasCorreo": ("correo_preferencias", (), {}),
    "CategoriaCorreo": ("correo_categorias", (), {}),
    "ReglaCategoriaCorreo": ("correo_reglas_categoria", (), {}),
    "RemitenteConfiable": ("correo_remitentes_confiables", (), {}),
    "PreferenciasIA": ("ia_preferencias", (), {"api_keys_configuradas": {"type": "integer", "description": "Cuántas claves de OpenRouter hay guardadas (nunca se devuelven)."}}),
    "FichajeDatos": ("fichaje_datos", (), {}),
    "PlantillaTareas": ("plantillas_tareas", (), {"items": {"type": "array", "items": {"type": "object"}}}),
    "AccesoCliente": ("cliente_accesos", (), {"usuario": {"type": "string"}}),
}
_AFINIDAD = {"INTEGER": "integer", "INT": "integer", "REAL": "number", "FLOAT": "number", "NUMERIC": "number", "TEXT": "string", "BLOB": "string"}

# --- Qué entidad devuelve cada función de datos: la primera que aparezca en la vista decide el esquema de `data` -------------
GETTERS: dict[str, tuple[str, bool]] = {   # función de db -> (componente, es_lista)
    "obtener_nota": ("Nota", False), "listar_notas": ("Nota", True),
    "obtener_tarea": ("TareaConDuracion", False), "obtener_categoria": ("Proyecto", False), "listar_categorias": ("Proyecto", True),
    "obtener_tarea_outlook": ("TareaOutlook", False), "obtener_tarea_outlook_visible": ("TareaOutlook", False), "listar_tareas_outlook": ("TareaOutlook", True),
    "obtener_cliente_fiscal": ("ClienteFiscalDetalle", False), "listar_clientes_fiscales": ("ClienteFiscal", True),
    "obtener_vencimiento_fiscal": ("Vencimiento", False), "listar_vencimientos_fiscales": ("Vencimiento", True),
    "listar_documentos_vencimiento": ("DocumentoVencimiento", True), "listar_mensajes_vencimiento": ("MensajeVencimiento", True),
    "listar_documentos_cliente": ("DocumentoCliente", True), "listar_notificaciones": ("Notificacion", True),
    "listar_fichajes": ("Fichaje", True), "obtener_tiquet": ("Tiquet", False), "listar_tiquets": ("Tiquet", True),
    "listar_plantillas_correo": ("PlantillaCorreo", True), "obtener_plantilla": ("PlantillaCorreo", False), "listar_cuentas_correo": ("CuentaCorreo", True),
    "listar_mensajes": ("MensajeCorreo", True), "mensajes_del_hilo_correo": ("MensajeCorreo", True), "listar_envios_programados": ("EnvioCorreo", True),
    "obtener_envio_correo": ("EnvioCorreo", False), "listar_adjuntos_nota": ("AdjuntoNota", True), "listar_checklist": ("ChecklistItem", True),
    "listar_comentarios_tarea": ("ComentarioTarea", True), "listar_recordatorios_tarea": ("RecordatorioTarea", True),
    "listar_tareas_recurrentes": ("ReglaRecurrente", True), "listar_reglas_por_vencimiento": ("ReglaVencimiento", True),
    "listar_seguimientos_correo": ("SeguimientoCorreo", True), "listar_conversaciones_ia": ("ConversacionIA", True), "listar_mensajes_ia": ("MensajeIA", True),
    "listar_webhooks": ("Webhook", True), "obtener_webhook": ("Webhook", False),
}

# --- Esquemas a medida ------------------------------------------------------------------------------------------------------
ESQUEMAS: dict[str, dict] = {
    "Error": {
        "type": "object", "required": ["ok", "error", "codigo"],
        "properties": {
            "ok": {"type": "boolean", "enum": [False]},
            "error": {"type": "string", "description": "Texto para personas. Puede cambiar o traducirse: no programes contra él."},
            "codigo": {"type": "string", "description": "Clave estable para programas.", "enum": [
                "peticion_invalida", "token_invalido", "token_caducado", "token_solo_lectura", "token_area_no_permitida", "no_autenticado", "prohibido", "sin_permiso",
                "no_encontrado", "metodo_no_permitido", "conflicto", "referencia_duplicada", "referencia_invalida", "vencimiento_duplicado", "idempotencia_conflicto",
                "idempotencia_en_curso", "tarea_bloqueada", "limite_excedido", "valor_invalido", "adjunto_invalido", "error_interno"]},
            "campo": {"type": "string", "description": "Campo que causó el error, si aplica."},
            "request_id": {"type": "string", "description": "Identificador de la petición (igual que la cabecera `X-Request-Id`); dilo al pedir soporte."},
        },
        "example": {"ok": False, "error": "Nota no encontrada.", "codigo": "no_encontrado", "request_id": "9f3c2a1b7d8e4f6a8b0c1d2e3f4a5b6c"},
    },
    "Usuario": {"type": "object", "properties": {"id": {"type": "integer"}, "email": {"type": "string", "format": "email"}, "tenant_id": {"type": "integer", "nullable": True}, "tenant": {"type": "string", "nullable": True}}},
    "Sesion": {"type": "object", "required": ["token", "usuario"], "properties": {
        "token": {"type": "string", "description": "Token de API: guárdalo, no se vuelve a mostrar."}, "usuario": {"$ref": "#/components/schemas/Usuario"}}},
    "TokenCreado": {"type": "object", "properties": {"token": {"type": "string", "description": "Solo se muestra esta vez."}, "id": {"type": "integer"}, "permisos": {"type": "string", "enum": ["completo", "solo_lectura"]},
                    "nombre": {"type": "string", "nullable": True}, "areas": {"type": "array", "items": {"type": "string"}}, "caduca_en": {"type": "string", "nullable": True}}},
    "Token": {"type": "object", "properties": {"id": {"type": "integer"}, "nombre_dispositivo": {"type": "string", "nullable": True}, "permisos": {"type": "string"}, "areas": {"type": "array", "items": {"type": "string"}},
              "caduca_en": {"type": "string", "nullable": True}, "creado_en": {"type": "string"}, "ultimo_uso_en": {"type": "string", "nullable": True}, "ultima_ip": {"type": "string", "nullable": True}, "llamadas_30d": {"type": "integer"}}},
    "WebhookCreado": {"allOf": [{"$ref": "#/components/schemas/Webhook"}, {"type": "object", "properties": {"secreto": {"type": "string", "description": "Con él se firman las entregas. Solo se muestra al crear y al rotarlo."}}}]},
    "ResultadoLote": {"type": "object", "properties": {"ok": {"type": "integer", "description": "Cuántas se aplicaron."}, "fallos": {"type": "integer"}}},
    "Sincronizacion": {"type": "object", "required": ["cursor", "hay_mas", "reiniciar"], "properties": {
        "cursor": {"type": "integer", "description": "Guárdalo y pásalo en la próxima llamada."}, "hay_mas": {"type": "boolean", "description": "Si es true, vuelve a llamar ya con el nuevo cursor."},
        "reiniciar": {"type": "boolean", "description": "El cursor es demasiado antiguo (30 días): descarga todo de nuevo."},
        "cambios": {"type": "object", "description": "Filas nuevas o modificadas por entidad.", "properties": {
            "notas": {"type": "array", "items": {"$ref": "#/components/schemas/Nota"}}, "tareas_outlook": {"type": "array", "items": {"$ref": "#/components/schemas/TareaOutlook"}},
            "proyectos": {"type": "array", "items": {"$ref": "#/components/schemas/Proyecto"}}, "tareas": {"type": "array", "items": {"$ref": "#/components/schemas/TareaConDuracion"}}}},
        "eliminados": {"type": "object", "description": "Ids que ya no existen (o están en la papelera), por entidad.", "additionalProperties": {"type": "array", "items": {"type": "integer"}}}}},
    "MiDia": {"type": "object", "description": "Secciones de «mi día».", "additionalProperties": {"type": "array", "items": {"$ref": "#/components/schemas/TareaOutlook"}}},
    "Tablero": {"type": "object", "description": "Tareas agrupadas por estado.", "additionalProperties": {"type": "array", "items": {"$ref": "#/components/schemas/TareaOutlook"}}},
    "Presentacion": {"type": "object", "properties": {"id": {"type": "integer"}, "estado": {"type": "string", "enum": ["pendiente", "presentado", "fuera_plazo"]}}},
    "ResultadoSubida": {"type": "array", "items": {"type": "object", "properties": {"archivo": {"type": "string"}, "resultado": {"type": "string", "enum": ["ok", "duplicado", "grande", "vacio", "limite"]}, "id": {"type": "integer", "nullable": True}}}},
    "EnvioResultado": {"type": "object", "properties": {"enviado": {"type": "boolean"}, "message_id": {"type": "string"}, "programado": {"type": "boolean"}, "envio_id": {"type": "integer"}, "enviar_en": {"type": "string"}}},
    "ConsumoIA": {"type": "object", "properties": {"mes": {"type": "string"}, "usadas": {"type": "integer"}, "limite": {"type": "integer", "nullable": True}, "ilimitado": {"type": "boolean"}, "restantes": {"type": "integer", "nullable": True}, "pct": {"type": "integer", "nullable": True}}},
    "Comunicado": {"type": "object", "properties": {"id": {"type": "integer"}, "titulo": {"type": "string"}, "texto": {"type": "string"}, "nivel": {"type": "string", "enum": ["info", "aviso", "critico"]}}},
    "NotificacionesRespuesta": {"type": "object", "properties": {"no_leidas": {"type": "integer"}, "notificaciones": {"type": "array", "items": {"$ref": "#/components/schemas/Notificacion"}}}},
    "ResultadoBusqueda": {"type": "array", "items": {"type": "object", "properties": {"tipo": {"type": "string"}, "id": {"type": "integer"}, "texto": {"type": "string"}, "url": {"type": "string"}}}},
    "Documento": {"type": "string", "format": "binary"},
    "Companero": {"type": "object", "properties": {"id": {"type": "integer"}, "nombre": {"type": "string"}, "email": {"type": "string"}}},
    "Vista": {"type": "object", "properties": {"id": {"type": "integer"}, "nombre": {"type": "string"}, "filtros": {"type": "object", "additionalProperties": {"type": "string"}},
              "compartida": {"type": "boolean"}, "mia": {"type": "boolean"}, "autor": {"type": "string"}}},
    "Perfil": {"type": "object", "properties": {"nombre_mostrado": {"type": "string", "nullable": True}, "tiene_avatar": {"type": "boolean"}, "avatar_url": {"type": "string", "nullable": True}}},
    "RespuestaIA": {"type": "object", "properties": {"mensajes_nuevos": {"type": "array", "items": {"$ref": "#/components/schemas/MensajeIA"}},
                    "pendiente": {"type": "object", "nullable": True, "description": "Acción que espera tu confirmación (`POST /ia/confirmar`)."}}},
    "ModeloIA": {"type": "object", "properties": {"id": {"type": "string"}, "nombre": {"type": "string"}}},
    "Historial": {"type": "object", "description": "Nota o tarea con duración, en orden cronológico.", "properties": {"origen": {"type": "string", "enum": ["nota", "tarea"]}, "id": {"type": "integer"}, "texto": {"type": "string"}, "fecha": {"type": "string"}}},
    "Integridad": {"type": "object", "properties": {"integra": {"type": "boolean"}, "total": {"type": "integer"}, "fila_rota": {"type": "integer", "nullable": True}}},
    "UsoToken": {"type": "array", "items": {"type": "object", "properties": {"dia": {"type": "string", "format": "date"}, "llamadas": {"type": "integer"}, "errores": {"type": "integer"}}}},
    "ResultadoAdjuntos": {"type": "array", "items": {"type": "object", "properties": {"archivo": {"type": "string"}, "ok": {"type": "boolean"}, "id": {"type": "integer"}, "error": {"type": "string"}}}},
    "Identificador": {"type": "object", "properties": {"id": {"type": "integer"}}},
    "TiempoTarea": {"type": "object", "additionalProperties": True},
    "MensajeCorreoDetalle": {"allOf": [{"$ref": "#/components/schemas/MensajeCorreo"}, {"type": "object", "properties": {"cuerpo_html": {"type": "string"}, "adjuntos": {"type": "array", "items": {"type": "object"}}}}]},
}

# Operación -> (esquema de `data`, es_lista). Sobrescribe lo inferido por GETTERS.
RESPUESTAS: dict[str, tuple[str, bool]] = {
    "login": ("Sesion", False), "registro": ("Sesion", False), "me": ("Usuario", False), "sincronizar": ("Sincronizacion", False),
    "mi_dia": ("MiDia", False), "tablero": ("Tablero", False), "accion_en_lote": ("ResultadoLote", False), "accion_en_lote_correo": ("ResultadoLote", False),
    "crear_token": ("TokenCreado", False), "listar_tokens": ("Token", True), "crear_webhook": ("WebhookCreado", False),
    "marcar_presentado_vencimiento_fiscal": ("Vencimiento", False), "subir_documentos_cliente": ("ResultadoSubida", False),
    "enviar_correo": ("EnvioResultado", False), "consumo_ia": ("ConsumoIA", False), "listar_comunicados": ("Comunicado", True),
    "listar_notificaciones": ("NotificacionesRespuesta", False), "buscar": ("ResultadoBusqueda", False),
    "listar_proyectos": ("Proyecto", True), "crear_proyecto": ("Proyecto", False), "renombrar_proyecto": ("Proyecto", False),
    "crear_categoria": ("Proyecto", False), "crear_tarea": ("TareaConDuracion", False), "crear_nota": ("Nota", False),
    "listar_tareas_cronometro": ("TareaConDuracion", True), "obtener_vencimiento": ("Vencimiento", False), "crear_vencimiento": ("Vencimiento", False),
    "estado_envio": ("EnvioCorreo", False), "listar_programados": ("EnvioCorreo", True), "listar_checklist": ("ChecklistItem", True),
    "listar_comentarios": ("ComentarioTarea", True), "listar_recordatorios": ("RecordatorioTarea", True), "listar_recurrentes": ("ReglaRecurrente", True),
    "listar_reglas_vencimiento": ("ReglaVencimiento", True), "listar_plantillas": ("PlantillaCorreo", True), "listar_seguimientos": ("SeguimientoCorreo", True),
    "listar_adjuntos_nota": ("AdjuntoNota", True), "listar_conversaciones_ia": ("ConversacionIA", True), "listar_mensajes_ia": ("MensajeIA", True),
    "listar_atajos_ia": ("AtajoIA", True), "historial_fichaje": ("Fichaje", True), "listar_webhooks": ("Webhook", True), "obtener_webhook": ("Webhook", False),
    "editar_webhook": ("Webhook", False), "crear_plantilla": ("PlantillaCorreo", False), "editar_plantilla": ("PlantillaCorreo", False),
    "editar_tarea_outlook": ("TareaOutlook", False), "completar_tarea_outlook": ("TareaOutlook", False), "cambiar_estado_tarea": ("TareaOutlook", False),
    "asignar_tarea_outlook": ("TareaOutlook", False), "mover_tarea": ("TareaOutlook", False), "tarea_desde_correo": ("TareaOutlook", False),
    "restaurar_tarea_outlook": ("TareaOutlook", False), "nota_desde_correo": ("Nota", False), "fijar_nota": ("Nota", False), "editar_nota": ("Nota", False),
    "upsert_nota": ("Nota", False), "nota_por_referencia": ("Nota", False), "upsert_tarea_outlook": ("TareaOutlook", False), "tarea_por_referencia": ("TareaOutlook", False),
    "upsert_cliente_fiscal": ("ClienteFiscal", False), "cliente_fiscal_por_referencia": ("ClienteFiscal", False), "editar_cliente_fiscal": ("ClienteFiscal", False),
    "crear_cliente_fiscal": ("ClienteFiscal", False), "obtener_cliente_fiscal": ("ClienteFiscalDetalle", False), "editar_vencimiento_fiscal": ("Vencimiento", False),
    "listar_tiquets": ("Tiquet", True), "crear_tiquet": ("Tiquet", False), "editar_tiquet": ("Tiquet", False), "cambiar_estado_tiquet": ("Tiquet", False),
    "listar_documentos_vencimiento": ("DocumentoVencimiento", True), "listar_mensajes_vencimiento": ("MensajeVencimiento", True),
    "listar_documentos_cliente": ("DocumentoCliente", True), "papelera_fiscal": ("Papelera", True), "listar_clientes_fiscales": ("ClienteFiscal", True),
    "listar_vencimientos_fiscales": ("Vencimiento", True), "listar_cuentas_correo": ("CuentaCorreo", True), "listar_mensajes_correo": ("MensajeCorreo", True),
    "conversacion_correo": ("MensajeCorreo", True), "listar_tareas_outlook": ("TareaOutlook", True), "listar_notas": ("Nota", True), "listar_categorias": ("Proyecto", True),
    "obtener_nota": ("Nota", False), "obtener_tarea_outlook": ("TareaOutlook", False), "crear_tarea_outlook": ("TareaOutlook", False),
    "listar_companeros": ("Companero", True), "obtener_ajustes_correo": ("PreferenciasCorreo", False), "guardar_ajustes_correo": ("PreferenciasCorreo", False),
    "listar_categorias_correo": ("CategoriaCorreo", True), "crear_cuenta_correo": ("CuentaCorreo", False), "obtener_mensaje_correo": ("MensajeCorreoDetalle", False),
    "obtener_plantilla": ("PlantillaCorreo", False), "listar_reglas_categoria": ("ReglaCategoriaCorreo", True), "listar_remitentes_confiables": ("RemitenteConfiable", True),
    "fichaje_admin_integridad": ("Integridad", False), "obtener_mis_datos_fichaje": ("FichajeDatos", False), "guardar_mis_datos_fichaje": ("FichajeDatos", False),
    "accesos_cliente": ("AccesoCliente", True), "historial": ("Historial", True), "obtener_ajustes_ia": ("PreferenciasIA", False), "guardar_ajustes_ia": ("PreferenciasIA", False),
    "confirmar_ia": ("RespuestaIA", False), "enviar_mensaje_ia": ("RespuestaIA", False), "listar_modelos_ia": ("ModeloIA", True), "subir_adjuntos_nota": ("ResultadoAdjuntos", False),
    "papelera": ("Papelera", True), "obtener_perfil": ("Perfil", False), "editar_perfil": ("Perfil", False), "subir_avatar_api": ("Perfil", False),
    "listar_vistas": ("Vista", True), "guardar_vista": ("Vista", False), "listar_participantes": ("Companero", True), "compartir_tarea": ("Companero", True),
    "tiempo_de_tarea": ("TiempoTarea", False), "listar_plantillas_tareas": ("PlantillaTareas", True), "crear_plantilla_tareas": ("PlantillaTareas", False),
    "editar_plantilla_tareas": ("PlantillaTareas", False), "uso_de_token": ("UsoToken", False), "listar_conversaciones_ia": ("ConversacionIA", True),
    "crear_categoria_correo": ("Identificador", False), "crear_regla_categoria": ("Identificador", False), "crear_remitente_confiable": ("Identificador", False),
    "crear_atajo_ia": ("Identificador", False), "crear_conversacion_ia": ("Identificador", False),
}
ESQUEMAS["Papelera"] = {"type": "object", "properties": {"origen": {"type": "string"}, "id": {"type": "integer"}, "texto": {"type": "string"}, "papelera_en": {"type": "string"}}}

# Operaciones que devuelven un fichero (no el sobre JSON): operación -> tipo MIME.
BINARIAS: dict[str, str] = {
    "avatar_api": "image/*", "descargar_adjunto_correo": "application/octet-stream", "descargar_documento_cliente": "application/octet-stream",
    "descargar_documento_vencimiento": "application/octet-stream", "descargar_adjunto_nota": "application/octet-stream",
    "fichaje_admin_csv": "text/csv", "fichaje_admin_pdf": "application/pdf", "fichaje_admin_json": "application/json",
}
STREAMS = {"enviar_mensaje_ia_stream", "confirmar_ia_stream"}
PUBLICAS = {"login", "registro", "openapi_json", "estado_servicio"}
BINARIAS["exportar"] = "application/octet-stream"
JSON_SIN_SOBRE = {"openapi_json"}           # devuelven el documento tal cual, sin `{"ok": ..., "data": ...}`
RESPUESTAS.update({
    "comentar_tarea": ("ComentarioTarea", False), "guardar_config_recordatorios": ("ConfigRecordatorios", False), "catalogo_eventos": ("NombreEvento", True),
    "listar_herramientas": ("Herramienta", True), "buscar_destinatarios_recientes": ("DestinatarioReciente", True), "listar_carpetas_correo": ("Carpeta", True),
    "actividad_de_tarea": ("ActividadTarea", True),
})
ESQUEMAS["EstadoServicio"] = {"type": "object", "properties": {"estado": {"type": "string", "enum": ["ok"], "description": "`ok` si el servicio atiende peticiones."}, "version_api": {"type": "string", "description": "Versión del contrato (`X-API-Version`)."}, "base_de_datos": {"type": "string", "enum": ["ok"], "description": "La base de datos responde."}}}
RESPUESTAS["estado_servicio"] = ("EstadoServicio", False)
ESQUEMAS.update({
    "ConfigRecordatorios": {"type": "object", "properties": {"dias_antes": {"type": "array", "items": {"type": "integer"}}, "dias_despues": {"type": "array", "items": {"type": "integer"}},
                            "avisar_equipo": {"type": "boolean"}, "asunto": {"type": "string"}, "cuerpo": {"type": "string"}}},
    "NombreEvento": {"type": "string", "example": "vencimiento.presentado"},
    "Herramienta": {"type": "object", "description": "Herramienta del stack conectada para tu despacho.", "properties": {"id": {"type": "string"}, "nombre": {"type": "string"}, "url": {"type": "string"}, "activa": {"type": "boolean"}}},
    "DestinatarioReciente": {"type": "object", "properties": {"email": {"type": "string"}, "nombre": {"type": "string", "nullable": True}}},
    "Carpeta": {"type": "object", "properties": {"nombre": {"type": "string"}, "no_leidos": {"type": "integer"}}},
    "ActividadTarea": {"type": "object", "properties": {"creado_en": {"type": "string"}, "usuario": {"type": "string"}, "accion": {"type": "string"}, "detalle": {"type": "string", "nullable": True}}},
})

# Operaciones que no devuelven datos útiles (solo `{"ok": true}`).
SIN_DATOS_ESPERADOS = {
    "logout", "eliminar_categoria", "eliminar_nota", "eliminar_tarea", "eliminar_tarea_outlook", "eliminar_proyecto", "eliminar_item_checklist", "alternar_item_checklist",
    "eliminar_comentario", "dejar_de_compartir", "quitar_dependencia", "eliminar_recordatorio", "posponer_recordatorio", "eliminar_vista", "eliminar_plantilla",
    "eliminar_plantilla_tareas", "eliminar_recurrente", "eliminar_regla_vencimiento", "borrar_webhook", "revocar_token", "eliminar_adjunto_nota", "eliminar_documento_cliente",
    "eliminar_notificacion", "marcar_notificaciones_leidas", "cerrar_comunicado", "eliminar_vencimiento_fiscal", "eliminar_cliente_fiscal", "restaurar_papelera_fiscal",
    "eliminar_definitivamente_de_papelera", "restaurar_de_papelera", "reintentar_entrega", "cancelar_programado", "cancelar_seguimiento", "ocultar_onboarding",
    "eliminar_dispositivo_push", "registrar_dispositivo_push", "eliminar_cuenta_correo", "eliminar_mensaje_correo", "eliminar_categoria_correo", "eliminar_regla_categoria",
    "eliminar_remitente_confiable", "eliminar_atajo_ia", "eliminar_conversacion_ia", "activar_conversacion_ia", "renombrar_conversacion_ia", "vaciar_ia", "eliminar_avatar_api",
    "destacar_mensaje_correo", "marcar_leido_correo", "mover_mensaje_correo", "posponer_mensaje_correo", "asignar_categoria_correo", "sincronizar_cuenta_correo",
    "guardar_firma_correo", "reordenar_categorias", "alternar_favorito_categoria", "regenerar_constancia", "subir_justificante", "probar_webhook", "eliminar_adjunto_nota",
}

# Las operaciones «upsert» reutilizan los controladores de crear y editar: heredan sus campos.
HEREDA: dict[str, tuple[str, str]] = {
    "upsert_nota": ("crear_nota", "editar_nota"), "upsert_tarea_outlook": ("crear_tarea_outlook", "editar_tarea_outlook"),
    "upsert_cliente_fiscal": ("crear_cliente_fiscal", "editar_cliente_fiscal"),
}
# Campos obligatorios que el código no delata por sí solo.
REQUERIDOS: dict[str, tuple[str, ...]] = {
    "login": ("email", "contrasena"), "registro": ("email", "contrasena"), "crear_nota": ("texto",), "editar_nota": ("texto",), "crear_proyecto": ("nombre",),
    "crear_categoria": ("nombre",), "crear_tarea": ("nombre", "categoria_id"), "crear_tarea_outlook": ("asunto",), "crear_cliente_fiscal": ("nombre",),
    "crear_vencimiento": ("cliente_id", "modelo", "periodo", "fecha_limite"), "enviar_correo": ("cuenta_id", "destinatarios", "asunto", "cuerpo_html"),
    "fichaje_admin_corregir": ("tipo", "marca_tiempo"), "accion_en_lote": ("ids", "accion"), "crear_webhook": ("url", "eventos"), "estado": ("estado",),
    "cambiar_estado_tarea": ("estado",), "comentar_tarea": ("texto",), "agregar_item_checklist": ("texto",), "anadir_dependencia": ("depende_de_id",),
    "compartir_tarea": ("usuario_id",), "crear_recurrente": ("asunto", "periodicidad"), "crear_regla_vencimiento": ("modelo", "asunto"), "crear_plantilla": ("nombre", "cuerpo"),
    "crear_plantilla_tareas": ("nombre", "items"), "guardar_vista": ("nombre", "filtros"), "responder_mensaje_vencimiento": ("texto",), "marcar_fichaje": ("tipo",),
    "crear_tiquet": ("titulo",), "enviar_mensaje_ia": ("texto",), "crear_atajo_ia": ("etiqueta", "texto"),
}
# Consultas que no se ven en el código (paginación hecha por ayudantes, formato de salida...).
CONSULTAS_EXTRA: dict[str, dict] = {}
PAGINADAS_EXTRA = {"listar_notas", "listar_vencimientos_fiscales"}   # paginan en SQL y devuelven X-Total-Count

# --- Tipos y descripciones de los campos por nombre -----------------------------------------------------------------------------
_TIPOS = {
    "ids": {"type": "array", "items": {"type": "integer"}}, "eventos": {"type": "array", "items": {"type": "string"}}, "areas": {"type": "array", "items": {"type": "string"}},
    "canales": {"type": "array", "items": {"type": "string"}}, "items": {"type": "array", "items": {"type": "string"}}, "modelos": {"type": "array", "items": {"type": "string"}},
    "modelos_fiscales": {"type": "array", "items": {"type": "string"}}, "dias_antes": {"type": "array", "items": {"type": "integer"}}, "dias_despues": {"type": "array", "items": {"type": "integer"}},
    "orden": {"type": "array", "items": {"type": "integer"}}, "filtros": {"type": "object", "additionalProperties": {"type": "string"}},
    "adjuntos": {"type": "array", "items": {"type": "object", "properties": {"nombre": {"type": "string"}, "tipo": {"type": "string"}, "contenido_base64": {"type": "string", "format": "byte"}}}},
    "porcentaje_completado": {"type": "integer", "minimum": 0, "maximum": 100}, "estimacion_min": {"type": "integer", "minimum": 1}, "anio": {"type": "integer"},
    "limit": {"type": "integer", "minimum": 1}, "offset": {"type": "integer", "minimum": 0}, "caduca_dias": {"type": "integer", "minimum": 1, "maximum": 3650},
    "origenes_cors": {"type": "array", "items": {"type": "string"}, "maxItems": 10}, "ips_permitidas": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
    "seguimiento_dias": {"type": "integer", "minimum": 1, "maximum": 30}, "crear_dias_antes": {"type": "integer"}, "vence_dias_antes": {"type": "integer"},
    "permisos": {"type": "string", "enum": ["completo", "solo_lectura"]}, "nivel": {"type": "string", "enum": ["info", "aviso", "critico"]},
    "prioridad": {"type": "string", "enum": ["baja", "normal", "alta"]}, "idioma": {"type": "string", "enum": ["es", "ca", "en", "fr"]},
    "estado": {"type": "string"}, "tipo": {"type": "string"}, "rol": {"type": "string", "enum": ["colabora", "observa"]},
    "periodicidad": {"type": "string", "enum": ["diaria", "laborables", "semanal", "mensual", "trimestral", "anual"]},
    "fecha_limite": {"type": "string", "format": "date"}, "fecha_inicio": {"type": "string", "format": "date"}, "fecha_vencimiento": {"type": "string", "format": "date"},
    "desde": {"type": "string", "format": "date"}, "hasta": {"type": "string", "format": "date"}, "fecha": {"type": "string", "format": "date"},
    "marca_tiempo": {"type": "string", "description": "Fecha y hora, `YYYY-MM-DDTHH:MM[:SS]`."}, "programar_para": {"type": "string", "description": "`YYYY-MM-DDTHH:MM`, hora del servidor."},
    "creada_en": {"type": "string", "format": "date-time"}, "avisar_en": {"type": "string", "format": "date-time"}, "email": {"type": "string", "format": "email"},
    "url": {"type": "string", "format": "uri"}, "cuerpo_html": {"type": "string", "description": "HTML del mensaje."},
}
_BOOLEANOS = {"activo", "compartida", "encadenar", "fijada", "ilimitado", "como_borrador", "avisar_equipo", "recordatorios_portal", "generacion_automatica", "asignar_responsable",
              "modo_autonomo", "solo_lectura", "borrar_api_key", "completadas", "todos", "leido", "destacado"}
_SUFIJOS_ENTERO = ("_id", "_ids_unico")
DESCRIPCIONES: dict[str, str] = {
    "texto": "Contenido en texto.", "nombre": "Nombre.", "asunto": "Asunto.", "cuerpo": "Cuerpo (admite HTML en correo).", "email": "Correo electrónico.", "contrasena": "Contraseña.",
    "nombre_dispositivo": "Nombre para reconocer este dispositivo o integración.", "categoria_id": "Id del proyecto.", "proyecto_id": "Id del proyecto.", "cliente_id": "Id del cliente fiscal.",
    "cuenta_id": "Id de la cuenta de correo.", "referencia_externa": "Tu propio identificador (hasta 120 caracteres, único por usuario o despacho): sirve para sincronizar con otro sistema sin duplicar.",
    "areas": "Áreas a las que se limita el token: notas, tareas, correo, fiscal, fichaje, tiquets, ia, avisos, webhooks. Vacío = todas.", "permisos": "`solo_lectura` solo puede hacer GET.",
    "origenes_cors": "Orígenes web exactos (`https://panel.ejemplo.com`) que pueden usar este token desde un navegador. Sin comodines; vacío = ninguno.",
    "ips_permitidas": "IP o redes CIDR desde las que se puede usar el token (`203.0.113.7`, `10.0.0.0/24`). Vacío = cualquiera. Un token con IPs no sirve por MCP.",
    "caduca_dias": "El token caduca a los N días.", "caduca_en": "Fecha y hora de caducidad (ISO).", "q": "Texto a buscar.", "limit": "Máximo de filas (hasta 1000).", "offset": "Filas a saltar.",
    "campos": "Lista de campos separados por comas: devuelve solo esos.", "desde": "Desde esta fecha (inclusive).", "hasta": "Hasta esta fecha (exclusive).", "estado": "Estado.",
    "ids": "Ids sobre los que actuar (máximo 200).", "accion": "Acción a aplicar.", "valor": "Valor de la acción (según la acción).", "modelo": "Modelo fiscal (p. ej. 303).",
    "periodo": "Periodo (p. ej. `3T 2026`).", "fecha_limite": "Fecha límite `YYYY-MM-DD`.", "pais": "País de tributación (ISO de 2 letras, p. ej. ES).", "idioma": "Idioma de las comunicaciones al cliente.",
    "destinatarios": "Direcciones separadas por comas.", "cc": "Con copia.", "bcc": "Con copia oculta (nunca aparece en el mensaje).", "en_respuesta_a": "Message-ID del correo que se responde.",
    "seguimiento_dias": "«Avísame si no responde» a los N días.", "programar_para": "Programa el envío (queda en cola).", "adjuntos": "Archivos adjuntos.", "evento": "Nombre del evento.",
    "eventos": "Eventos a los que se suscribe.", "url": "Dirección https pública que recibirá los eventos.", "estimacion_min": "Estimación en minutos.", "prioridad": "Prioridad.",
    "companero_id": "Id del compañero del despacho; vacío para desasignar.", "usuario_id": "Id de la persona.", "referencia": "Referencia externa.", "semana": "Cualquier fecha de la semana (YYYY-MM-DD).",
    "tenant_id": "Despacho (solo para administradores globales).", "cursor": "Cursor devuelto por la llamada anterior.", "ambito": "propias, asignadas, compartidas o todas.", "todos": "Incluye también los cerrados.",
    "depende_de_id": "Id de la tarea de la que depende.", "avisar_en": "Fecha y hora del aviso.", "atajo": "Aviso relativo al vencimiento.", "opcion": "Opción de aplazamiento.",
    "titulo": "Título.", "color": "Color hexadecimal (#rrggbb).", "marca_tiempo": "Fecha y hora real del fichaje.", "nota": "Nota.", "corrige_a": "Id del fichaje que se corrige.",
    "justificante": "Justificante oficial (imagen o PDF, hasta 8 MB).", "archivo": "Archivo.", "adjunto": "Archivo (imagen, PDF, texto o CSV; 5 MB).", "categoria": "Categoría.",
}


def tipo_de_campo(nombre: str, contexto_formulario: bool = False) -> dict:
    """Esquema OpenAPI de un campo, por su nombre."""
    if nombre in _TIPOS:
        esquema = dict(_TIPOS[nombre])
    elif nombre in _BOOLEANOS:
        esquema = {"type": "boolean"}
    elif nombre.endswith(_SUFIJOS_ENTERO) or nombre.endswith("_id") or nombre in ("id", "cursor", "dias"):
        esquema = {"type": "integer"}
    else:
        esquema = {"type": "string"}
    if nombre in DESCRIPCIONES and "description" not in esquema:
        esquema["description"] = DESCRIPCIONES[nombre]
    return esquema


# --- Etiquetas (grupos de operaciones) ----------------------------------------------------------------------------------------------
ETIQUETAS: dict[str, str] = {
    "auth": "Cuenta y sesión: registro, login, token propio.", "tokens": "Tokens de API: crearlos con áreas y caducidad, ver su uso, revocarlos.",
    "notas": "Notas, fijadas, adjuntos y referencias externas.", "tareas": "Tareas con cronómetro (duración).", "tareas-outlook": "Tareas de lista: estado, comentarios, dependencias, recordatorios, compartir, lote, carga.",
    "tareas-plantillas": "Plantillas de tareas.", "tareas-recurrentes": "Tareas que se repiten.", "tareas-reglas-vencimiento": "Una tarea por cada vencimiento fiscal de un modelo.",
    "proyectos": "Proyectos.", "categorias": "Proyectos (ruta antigua, igual que `/proyectos`).", "checklist": "Subtareas.", "mi-dia": "Lo de hoy.", "companeros": "Compañeros del despacho.",
    "correo": "Cuentas, mensajes, envío (incluido programado y con adjuntos), plantillas, reglas y seguimientos.", "fiscal": "Calendario fiscal: clientes, vencimientos, expediente, mensajes con el cliente, recordatorios.",
    "fichaje": "Registro horario: fichar y administración (correcciones auditables, exportaciones, integridad).", "tiquets": "Tiquets de soporte.", "ia": "Asistente de IA.",
    "webhooks": "Webhooks del despacho: crear, rotar secreto, probar, entregas.", "sync": "Sincronización incremental por cursor.", "notificaciones": "Notificaciones.", "comunicados": "Avisos de Guilda.",
    "buscar": "Búsqueda.", "dashboard": "Resumen del día.", "historial": "Notas y tareas en orden cronológico.", "export": "Exportación.", "papelera": "Papelera.", "perfil": "Perfil.",
}

# --- Ejemplos: operación -> {"peticion": ..., "respuesta": ...} ---------------------------------------------------------------------------
EJEMPLOS: dict[str, dict] = {
    "login": {"peticion": {"email": "ana@despacho.com", "contrasena": "una-clave-larga", "nombre_dispositivo": "Panel de Grafana"},
              "respuesta": {"token": "kQ3x...largo...Zp9", "usuario": {"id": 12, "email": "ana@despacho.com", "tenant_id": 3}}},
    "crear_nota": {"peticion": {"texto": "Llamar al cliente por el IVA del 3T", "categoria_id": 4, "referencia_externa": "CRM-NOTA-881"},
                   "respuesta": {"id": 210, "texto": "Llamar al cliente por el IVA del 3T", "categoria_id": 4, "referencia_externa": "CRM-NOTA-881", "fijada": 0, "creada_en": "2026-10-10T09:30:00"}},
    "crear_tarea_outlook": {"peticion": {"asunto": "Preparar el modelo 303", "fecha_vencimiento": "2026-10-20", "prioridad": "alta", "estimacion_min": 90},
                            "respuesta": {"id": 57, "asunto": "Preparar el modelo 303", "estado": "no_iniciada", "prioridad": "alta", "fecha_vencimiento": "2026-10-20", "porcentaje_completado": 0}},
    "cambiar_estado_tarea": {"peticion": {"estado": "en_progreso"}, "respuesta": {"id": 57, "estado": "en_progreso"}},
    "accion_en_lote": {"peticion": {"ids": [57, 58, 59], "accion": "prioridad", "valor": "alta"}, "respuesta": {"ok": 3, "fallos": 0}},
    "crear_cliente_fiscal": {"peticion": {"nombre": "Panadería López SL", "nif": "B12345678", "email": "info@panaderialopez.com", "pais": "ES", "modelos_fiscales": ["303", "130"], "referencia_externa": "ERP-C-1042"},
                             "respuesta": {"id": 31, "nombre": "Panadería López SL", "nif": "B12345678", "pais": "ES", "referencia_externa": "ERP-C-1042"}},
    "crear_vencimiento": {"peticion": {"cliente_id": 31, "modelo": "303", "periodo": "3T 2026", "fecha_limite": "2026-10-20"},
                          "respuesta": {"id": 904, "cliente_fiscal_id": 31, "modelo": "303", "periodo": "3T 2026", "fecha_limite": "2026-10-20", "estado": "pendiente"}},
    "generar_vencimientos_fiscales": {"peticion": {"anio": 2027}, "respuesta": {"creados": 8, "ids": [905, 906], "omitidos": 0}},
    "marcar_presentado_vencimiento_fiscal": {"respuesta": {"id": 904, "estado": "presentado", "modelo": "303"}},
    "enviar_correo": {"peticion": {"cuenta_id": 2, "destinatarios": "cliente@acme.com", "asunto": "Documentación del 3T", "cuerpo_html": "<p>Hola, os adjunto el resumen.</p>",
                                   "adjuntos": [{"nombre": "resumen.pdf", "tipo": "application/pdf", "contenido_base64": "JVBERi0xLjQK..."}], "seguimiento_dias": 3},
                      "respuesta": {"enviado": True, "message_id": "<a1b2c3@despacho.com>"}},
    "crear_webhook": {"peticion": {"url": "https://hooks.tuapp.com/guilda", "eventos": ["vencimiento.presentado", "tarea.completada"]},
                      "respuesta": {"id": 7, "url": "https://hooks.tuapp.com/guilda", "eventos": ["vencimiento.presentado", "tarea.completada"], "activo": 1, "origen": "api", "secreto": "p4x...solo-se-muestra-una-vez"}},
    "crear_token": {"peticion": {"nombre": "Panel fiscal de solo lectura", "permisos": "solo_lectura", "areas": ["fiscal"], "caduca_dias": 90},
                    "respuesta": {"token": "kQ3x...largo...Zp9", "id": 14, "permisos": "solo_lectura", "areas": ["fiscal"], "caduca_en": "2027-01-08T09:30:00"}},
    "sincronizar": {"respuesta": {"cursor": 4812, "hay_mas": False, "reiniciar": False, "cambios": {"notas": [{"id": 210, "texto": "Llamar al cliente…"}]}, "eliminados": {"tareas_outlook": [44]}}},
    "fichaje_admin_corregir": {"peticion": {"tipo": "salida", "marca_tiempo": "2026-10-05T16:30", "nota": "Olvidó fichar la salida"}, "respuesta": {"corregido": True, "fichaje_id": 5321}},
    "upsert_cliente_fiscal": {"peticion": {"nombre": "Panadería López S.L.", "email": "info@panaderialopez.com"}, "respuesta": {"id": 31, "nombre": "Panadería López S.L.", "referencia_externa": "ERP-C-1042"}},
    "crear_regla_vencimiento": {"peticion": {"modelo": "303", "asunto": "Preparar {modelo} de {cliente}", "crear_dias_antes": 14, "vence_dias_antes": 2, "estimacion": "2h"}, "respuesta": {"id": 3, "modelo": "303", "activa": 1}},
    "guardar_config_recordatorios": {"peticion": {"dias_antes": [10, 3, 1], "dias_despues": [2], "avisar_equipo": True}, "respuesta": {"dias_antes": [10, 3, 1], "dias_despues": [2], "avisar_equipo": True, "asunto": "", "cuerpo": ""}},
}


# Funciones de datos que devuelven algo que no es una entidad conocida: su tipo a mano.
TIPOS_FUNCION: dict[str, dict] = {
    "modelos_fiscales_de_cliente": {"type": "array", "items": {"type": "string"}},
    "tiempo_equipo_tarea": {"type": "object", "additionalProperties": True},
    "estado_actual_fichaje": {"type": "string", "enum": ["fuera", "dentro", "en_pausa", "salida"]},
    "dependencias_de_tarea": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "asunto": {"type": "string"}, "estado": {"type": "string"}}}},
    "obtener_config_recordatorios": {"$ref": "#/components/schemas/ConfigRecordatorios"},
}
