"""Lo que el código no dice por sí solo y hay que saber para documentar bien la API: tipos y descripciones de campos, qué esquema
devuelve cada ruta, esquemas «a medida» y ejemplos. El generador (`openapi.py`) deriva de las vistas todo lo demás; aquí solo hay lo
que aporta una persona. Los esquemas de las entidades (Nota, TareaOutlook, ClienteFiscal...) se construyen leyendo las columnas de
las tablas reales, así que cuando se añade una columna aparece sola en el contrato."""
from __future__ import annotations

# --- Entidades: componente -> (tabla, columnas que NUNCA se exponen, propiedades extra) ----------------------------------------
TABLAS: dict[str, tuple[str, tuple[str, ...], dict]] = {
    "Nota": ("notas", (), {"categoria_nombre": {"type": "string", "nullable": True}, "dueno_nombre": {"type": "string", "nullable": True}}),
    "TareaConDuracion": ("tareas", (), {}),
    "TareaOutlook": ("tareas_outlook", (), {"categoria_nombre": {"type": "string", "nullable": True}, "categoria_color": {"type": "string", "nullable": True}, "vencida": {"type": "boolean", "description": "Derivada: tiene fecha, ya pasó el día y no está completada (solo en las respuestas de transiciones y tareas de un cliente)."}, "clientes": {"type": "array", "items": {"$ref": "#/components/schemas/ClienteDeTarea"}}}),
    "Proyecto": ("categorias", (), {}),
    "ClienteFiscal": ("clientes_fiscales", (), {"modelos_fiscales": {"type": "string", "nullable": True, "description": "Modelos que se le generan, **serializados como JSON** (p. ej. `[\"303\",\"130\"]`). Solo `GET /fiscal/clientes/{id}` los devuelve ya como lista (`ClienteFiscalDetalle`); al enviarlos siempre es una lista."}}),
    "Vencimiento": ("vencimientos_fiscales", (), {"cliente_nombre": {"type": "string"}}),
    "DocumentoVencimiento": ("vencimientos_fiscales_documentos", ("contenido", "nextcloud_ruta", "nextcloud_path"), {}),
    "MensajeVencimiento": ("vencimientos_fiscales_mensajes", (), {}),
    "DocumentoCliente": ("cliente_documentos", ("contenido", "huella", "sobre"), {}),
    "DocumentoDespacho": ("documentos", ("contenido", "sobre", "hash_sha256", "papelera_en", "tenant_id", "subido_por", "mensaje_correo_id", "compartido_cliente"),
                          {"contenido_disponible": {"type": "boolean", "description": "`false` si está cifrado y este token no tiene la clave disponible (la descarga daría 423 `despacho_bloqueado`)."}}),
    "Webhook": ("webhooks", ("secreto",), {"eventos": {"type": "array", "items": {"type": "string"}}}),
    "Notificacion": ("notificaciones", (), {}),
    "Fichaje": ("fichajes", (), {}),
    "Traspaso": ("traspasos", ("tenant_id",), {"cliente": {"type": "string"}, "de_nombre": {"type": "string", "nullable": True}, "a_nombre": {"type": "string"}, "de_oficina": {"type": "string", "nullable": True},
                                              "a_oficina": {"type": "string", "nullable": True}, "proximo_vencimiento": {"type": "string", "nullable": True}, "dias_al_vencimiento": {"type": "integer", "nullable": True}}),
    "Oficina": ("oficinas", ("tenant_id",), {"clientes": {"type": "integer", "description": "Clientes con esta oficina como principal."}, "personas": {"type": "integer", "description": "Personas con un rol en la oficina."}}),
    "EventoAuditoria": ("auditoria_eventos", ("tenant_id",), {"actor": {"type": "string", "nullable": True}, "detalle": {"description": "Objeto con el detalle del evento, o texto."}}),
    "Membresia": ("membresias", ("tenant_id",), {"persona": {"type": "string"}, "oficina": {"type": "string", "nullable": True}, "cliente": {"type": "string", "nullable": True}}),
    "Concesion": ("concesiones_cliente", ("tenant_id",), {"oficina": {"type": "string", "nullable": True}, "persona": {"type": "string", "nullable": True}}),
    "Certificado": ("certificados", ("tenant_id", "der"), {
        "san": {"type": "array", "items": {"type": "string"}}, "usos_clave": {"type": "array", "items": {"type": "string"}}, "politicas": {"type": "array", "items": {"type": "string"}},
        "ruta_cadena": {"type": "array", "items": {"type": "object", "properties": {"huella": {"type": "string"}, "sujeto": {"type": "string"}, "es_ca": {"type": "boolean"}}}},
        "temporal": {"type": "string", "enum": ["todavia_no_vigente", "vigente", "caducado", "desconocido"], "description": "Estado temporal (RFC 5280, extremos incluidos, a precisión de instante)."},
        "dias_restantes": {"type": "integer", "nullable": True, "description": "Días completos hasta `not_after` (negativo si ya caducó). Informativo: no determina la validez."},
        "cadena": {"type": "object", "properties": {"resultado": {"type": "string", "enum": ["no_comprobada", "valida", "invalida", "indeterminada"]}, "comprobado_en": {"type": "string", "nullable": True}, "metodo": {"type": "string", "nullable": True}, "detalle": {"type": "string", "nullable": True}}},
        "revocacion": {"type": "object", "properties": {"resultado": {"type": "string", "enum": ["no_comprobada", "no_revocado_en_comprobacion", "revocado", "indeterminada"]}, "comprobado_en": {"type": "string", "nullable": True}, "metodo": {"type": "string", "nullable": True}, "detalle": {"type": "string", "nullable": True}}},
        "clave": {"type": "object", "properties": {"resultado": {"type": "string", "enum": ["no_declarada", "declarada_en_medio_autorizado", "no_disponible"]}, "comprobado_en": {"type": "string", "nullable": True}, "metodo": {"type": "string", "nullable": True}, "detalle": {"type": "string", "nullable": True}}},
        "renovacion": {"type": "string", "enum": ["sin_iniciar", "en_gestion", "pendiente_titular", "obtenido", "validado", "implantado", "cerrado", "cancelada"]},
        "vinculos_activos": {"type": "integer", "description": "Servicios activos que usan el certificado (0 = cobertura desconocida)."}, "custodio_nombre": {"type": "string", "nullable": True},
        "pendiente_de_comprobar": {"type": "boolean", "description": "Apuntado a mano (sin el archivo público): los datos los ha introducido el despacho."},
        "caduca_el": {"type": "string", "nullable": True, "description": "Fecha de caducidad en la zona horaria del despacho (AAAA-MM-DD)."}, "emitido_el": {"type": "string", "nullable": True},
        "cliente_nombre": {"type": "string", "nullable": True, "description": "Cliente al que pertenece el certificado."}}),
    "TurnoTipo": ("turnos_tipos", ("tenant_id",), {"horas": {"type": "number", "description": "Duración del turno en horas."}}),
    "Ausencia": ("ausencias", ("tenant_id", "creada_por", "resuelta_por"), {"persona": {"type": "string", "description": "Nombre de la persona (solo en la vista del equipo)."}}),
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
                "idempotencia_en_curso", "tarea_bloqueada", "limite_excedido", "requiere_2fa", "credenciales_o_codigo_incorrectos", "ip_no_permitida", "servicio_no_disponible", "valor_invalido", "adjunto_invalido", "error_interno"]},
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
    "ResultadoSubida": {"type": "array", "items": {"type": "object", "properties": {"archivo": {"type": "string"}, "resultado": {"type": "string", "enum": ["ok", "duplicado", "grande", "vacio", "limite", "clave_privada"]}, "id": {"type": "integer", "nullable": True}}}},
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
    "TurnoAsignado": {"type": "object", "properties": {"fecha": {"type": "string"}, "turno_id": {"type": "integer"}, "nombre": {"type": "string"}, "inicio": {"type": "string"}, "fin": {"type": "string"},
                      "color": {"type": "string"}, "horas": {"type": "number"}}},
    "Cuadrante": {"type": "object", "properties": {"dias": {"type": "array", "items": {"type": "string"}, "description": "Las fechas del rango."},
                  "personas": {"type": "array", "items": {"type": "object", "properties": {"usuario_id": {"type": "integer"}, "nombre": {"type": "string"},
                               "dias": {"type": "object", "additionalProperties": {"type": "object"}, "description": "Por fecha: un turno (`turno_id`, `nombre`, `inicio`, `fin`, `color`) o `{\"ausencia\": tipo}`."}}}}}},
    "BolsaHoras": {"type": "object", "properties": {"usuario_id": {"type": "integer"}, "desde": {"type": "string"}, "hasta": {"type": "string"}, "jornada_semanal_horas": {"type": "number", "nullable": True},
                   "sin_jornada": {"type": "boolean", "description": "Sin jornada semanal contratada **y** sin turnos en el periodo: no hay bolsa que calcular."}, "dias_con_turno": {"type": "integer", "description": "Días del periodo cuyo «tocaba» sale de un turno del cuadrante (en las semanas con cuadrante manda el turno; en las demás, la jornada semanal)."}, "dias_laborables": {"type": "integer"}, "dias_justificados": {"type": "number", "description": "Días laborables cubiertos por una ausencia aprobada (0,5 = medio día)."},
                   "esperado_seg": {"type": "number"}, "trabajado_seg": {"type": "number"}, "ajustes_seg": {"type": "number"},
                   "saldo_seg": {"type": "number", "nullable": True, "description": "Trabajado + ajustes − esperado. `null` sin jornada contratada."},
                   "por_mes": {"type": "array", "items": {"type": "object", "properties": {"mes": {"type": "string"}, "esperado_seg": {"type": "number"}, "trabajado_seg": {"type": "number"},
                               "ajustes_seg": {"type": "number"}, "saldo_seg": {"type": "number", "nullable": True}}}}}},
    "BolsaEquipo": {"type": "object", "properties": {"usuario_id": {"type": "integer"}, "nombre": {"type": "string"}, "sin_jornada": {"type": "boolean"}, "jornada_semanal_horas": {"type": "number", "nullable": True},
                    "esperado_seg": {"type": "number"}, "trabajado_seg": {"type": "number"}, "ajustes_seg": {"type": "number"}, "saldo_seg": {"type": "number", "nullable": True}}},
    "ResultadoCambio": {"type": "object", "properties": {"cambiado": {"type": "boolean"}}},
    "FlujoObligacion": {"type": "object", "properties": {"fase": {"type": "string", "enum": ["pendiente", "en_preparacion", "en_revision", "aprobada", "presentada", "cerrada", "no_aplica", "anulada"]},
                        "version": {"type": "integer", "description": "Valor para `If-Match` al modificar."},
                        "indicadores": {"type": "object", "properties": {"vencida": {"type": "boolean"}, "en_riesgo": {"type": "boolean"}, "bloqueada": {"type": "boolean"}, "presentada_tarde": {"type": "boolean"}, "dias_restantes": {"type": "integer", "nullable": True}}},
                        "destinos": {"type": "array", "items": {"type": "string"}, "description": "Fases a las que TÚ puedes mover la obligación ahora."},
                        "evidencias": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "presentado_en": {"type": "string"}, "organismo": {"type": "string", "nullable": True}, "referencia": {"type": "string", "nullable": True},
                                       "documento_id": {"type": "integer", "nullable": True}, "procedencia": {"type": "string", "enum": ["declarada_por_gestor", "integracion"]}, "actor": {"type": "string", "nullable": True}}}},
                        "config": {"$ref": "#/components/schemas/ConfigFlujo"}, "motivo": {"type": "string", "nullable": True}, "bloqueo_motivo": {"type": "string", "nullable": True}}},
    "ResultadoTransicion": {"type": "object", "properties": {"fase": {"type": "string"}, "estado": {"type": "string", "description": "El estado de siempre (pendiente, presentado, fuera_plazo): proyección de la fase."}, "version": {"type": "integer"}}},
    "ConfigFlujo": {"type": "object", "properties": {"flujo_estricto": {"type": "boolean"}, "exigir_justificante": {"type": "boolean"}}},
    "Revocada": {"type": "object", "properties": {"revocada": {"type": "boolean"}}},
    "Archivada": {"type": "object", "properties": {"archivada": {"type": "boolean"}}},
    "ConfigAvisosCertificados": {"type": "object", "properties": {"avisar_cliente": {"type": "boolean"}, "mostrar_en_portal": {"type": "boolean"}, "dias_antes": {"type": "array", "items": {"type": "integer"}},
                                 "dias_despues": {"type": "array", "items": {"type": "integer"}}, "asunto": {"type": "string"}, "cuerpo": {"type": "string"}, "instrucciones": {"type": "string"}}},
    "CertificadoRenovado": {"type": "object", "properties": {"id": {"type": "integer", "description": "El certificado nuevo."}, "anterior_id": {"type": "integer"}}},
    "ResultadoImportacion": {"type": "object", "properties": {"id": {"type": "integer"}, "nuevo": {"type": "boolean", "description": "`false` si ese certificado ya estaba en el inventario."}, "huella": {"type": "string"}}},
    "RiesgoCertificado": {"type": "object", "properties": {"vencimiento_id": {"type": "integer"}, "cliente": {"type": "string"}, "modelo": {"type": "string"}, "periodo": {"type": "string"}, "fecha_limite": {"type": "string"},
                          "tipo": {"type": "string", "enum": ["cobertura_desconocida", "caduca_antes", "sin_alternativa"]}, "motivo": {"type": "string"}, "certificado_id": {"type": "integer", "nullable": True}}},
    "SaldoAusencias": {"type": "object", "properties": {"anio": {"type": "integer"}, "total": {"type": "number", "description": "Días de vacaciones que te corresponden ese año."},
                       "aprobadas": {"type": "number"}, "pendientes": {"type": "number"}, "disponibles": {"type": "number"}}},
    "ResultadoAdjuntos": {"type": "array", "items": {"type": "object", "properties": {"archivo": {"type": "string"}, "ok": {"type": "boolean"}, "id": {"type": "integer"}, "error": {"type": "string"}}}},
    "Identificador": {"type": "object", "properties": {"id": {"type": "integer"}}},
    "TiempoTarea": {"type": "object", "additionalProperties": True},
    "PanelFiscal": {"type": "object", "description": "Ver la descripción de la operación.", "properties": {
        "generado_en": {"type": "string"}, "hoy": {"type": "string"}, "ambito": {"type": "string", "enum": ["todo", "parcial"]}, "totales": {"type": "object", "additionalProperties": {"type": "integer"}},
        "hoy_lista": {"type": "object"}, "bloqueadas": {"type": "array", "items": {"type": "object"}}, "traspasos": {"type": "array", "items": {"$ref": "#/components/schemas/Traspaso"}},
        "riesgos_certificados": {"type": "array", "items": {"$ref": "#/components/schemas/RiesgoCertificado"}}, "certificados": {"type": "object", "nullable": True},
        "carga_por_responsable": {"type": "array", "items": {"type": "object"}}, "carga_por_oficina": {"type": "array", "items": {"type": "object"}}, "indicadores": {"type": "object"}}},
    "ResponsableAsignado": {"type": "object", "properties": {"cliente_id": {"type": "integer"}, "responsable_id": {"type": "integer", "nullable": True}}},
    "MensajeCorreoDetalle": {"allOf": [{"$ref": "#/components/schemas/MensajeCorreo"}, {"type": "object", "properties": {"cuerpo_html": {"type": "string"}, "adjuntos": {"type": "array", "items": {"type": "object"}}}}]},
}

# Operación -> (esquema de `data`, es_lista). Sobrescribe lo inferido por GETTERS.
RESPUESTAS: dict[str, tuple[str, bool]] = {
    "login": ("Sesion", False), "registro": ("Sesion", False), "me": ("Usuario", False), "sincronizar": ("Sincronizacion", False),
    "mi_dia": ("MiDia", False), "tablero": ("Tablero", False), "accion_en_lote": ("ResultadoLote", False), "accion_en_lote_correo": ("ResultadoLote", False),
    "flujo_vencimiento": ("FlujoObligacion", False), "transicionar_vencimiento": ("ResultadoTransicion", False), "bloquear_vencimiento": ("FlujoObligacion", False),
    "configuracion_flujo": ("ConfigFlujo", False), "guardar_configuracion_flujo": ("ConfigFlujo", False), "eventos_de_auditoria": ("EventoAuditoria", True),
    "panel_fiscal_api": ("PanelFiscal", False), "listar_traspasos_api": ("Traspaso", True), "proponer_traspaso_api": ("Traspaso", False), "aceptar_traspaso_api": ("Traspaso", False),
    "rechazar_traspaso_api": ("Traspaso", False), "cancelar_traspaso_api": ("Traspaso", False), "asignar_responsable_api": ("ResponsableAsignado", False),
    "listar_oficinas_api": ("Oficina", True), "crear_oficina_api": ("Identificador", False), "archivar_oficina_api": ("Archivada", False), "asignar_oficina_api": ("ClienteFiscal", False),
    "listar_concesiones_api": ("Concesion", True), "conceder_cliente_api": ("Identificador", False), "revocar_concesion_api": ("Revocada", False),
    "listar_membresias_api": ("Membresia", True), "dar_membresia_api": ("Identificador", False), "revocar_membresia_api": ("Revocada", False),
    "apuntar_certificado_api": ("ResultadoImportacion", False), "editar_certificado_api": ("Certificado", False), "renovado_certificado_api": ("CertificadoRenovado", False),
    "configuracion_avisos_cliente_api": ("ConfigAvisosCertificados", False), "guardar_avisos_cliente_api": ("ConfigAvisosCertificados", False),
    "listar_certificados_api": ("Certificado", True), "obtener_certificado_api": ("Certificado", False), "importar_certificado_api": ("ResultadoImportacion", False),
    "abrir_renovacion_api": ("Identificador", False), "riesgos_certificados_api": ("RiesgoCertificado", True),
    "mis_turnos_api": ("TurnoAsignado", True), "cuadrante_api": ("Cuadrante", False), "tipos_de_turno_api": ("TurnoTipo", True), "crear_tipo_de_turno_api": ("TurnoTipo", False),
    "asignar_turno_api": ("ResultadoCambio", False), "bolsa_de_horas_api": ("BolsaHoras", False), "bolsa_de_horas_equipo_api": ("BolsaEquipo", True), "ajustar_bolsa_api": ("Identificador", False),
    "listar_ausencias": ("Ausencia", True), "pedir_ausencia": ("Ausencia", False), "cancelar_ausencia_api": ("Ausencia", False), "ausencias_del_equipo": ("Ausencia", True),
    "resolver_ausencia_api": ("Ausencia", False), "saldo_ausencias": ("SaldoAusencias", False),
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
    "listar_documentos_cliente": ("DocumentoCliente", True), "listar_documentos": ("DocumentoDespacho", True), "papelera_fiscal": ("Papelera", True), "listar_clientes_fiscales": ("ClienteFiscal", True),
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
    "avatar_api": "image/*", "descargar_adjunto_correo": "application/octet-stream", "descargar_documento_cliente": "application/octet-stream", "descargar_documento": "application/octet-stream",
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
    "cambiar_estado_tarea": ("estado",), "transicionar_tarea": ("estado",), "fijar_clientes_de_la_tarea": ("cliente_ids",), "crear_subtarea_de_la_tarea": ("asunto",), "resolver_revision_de_la_tarea": ("decision",), "fijar_visible_cliente_de_la_tarea": ("visible",), "comentar_tarea": ("texto",), "agregar_item_checklist": ("texto",), "anadir_dependencia": ("depende_de_id",),
    "compartir_tarea": ("usuario_id",), "crear_recurrente": ("asunto", "periodicidad"), "crear_regla_vencimiento": ("modelo", "asunto"), "crear_plantilla": ("nombre", "cuerpo"),
    "crear_plantilla_tareas": ("nombre", "items"), "guardar_vista": ("nombre", "filtros"), "responder_mensaje_vencimiento": ("texto",), "marcar_fichaje": ("tipo",), "pedir_ausencia": ("tipo", "desde"), "importar_certificado_api": ("contenido_base64",), "proponer_traspaso_api": ("cliente_id", "a_usuario_id"), "rechazar_traspaso_api": ("motivo",), "renovado_certificado_api": ("nueva_caducidad",), "transicionar_vencimiento": ("destino",), "crear_oficina_api": ("nombre",), "dar_membresia_api": ("usuario_id", "rol", "alcance"), "crear_tipo_de_turno_api": ("nombre", "inicio", "fin"), "asignar_turno_api": ("usuario_id", "fecha"), "ajustar_bolsa_api": ("usuario_id", "minutos", "motivo"), "resolver_ausencia_api": ("decision",),
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
    "a_usuario_id": "Persona del despacho que recibe el cliente.", "a_oficina_id": "Oficina a la que pasa el cliente (opcional; sin ella sigue en la misma).", "responsable_id": "Persona que lleva el cliente (`null` la quita).",
    "caduca": "Fecha de caducidad del certificado (AAAA-MM-DD).", "emitido": "Fecha de emisión (AAAA-MM-DD).", "nueva_caducidad": "Caducidad del certificado renovado (AAAA-MM-DD).",
    "titular": "Nombre del titular (por defecto, el del cliente).", "serie": "Número de serie.", "funciona": "Confirma que el certificado nuevo funciona en los servicios donde se usa el anterior.",
    "nif": "NIF/CIF/NIE del titular.", "avisar_cliente": "`true` siempre se informa al cliente de su caducidad, `false` nunca, omitido: según el ajuste del despacho.",
    "mostrar_en_portal": "El cliente ve su certificado en su portal.", "dias_antes": "Días antes de la caducidad en que se avisa (0 a 365).", "dias_despues": "Días después de caducar en que se vuelve a avisar (1 a 90).",
    "instrucciones": "Cómo se renueva: texto para los clientes.", "asunto": "Asunto propio del correo (con las {marcas}).", "cuerpo": "Mensaje propio del correo (con las {marcas}).",
    "destino": "Fase a la que pasa la obligación.", "presentacion": "Evidencia de la presentación: `presentado_en`, `organismo`, `referencia`, `documento_id` (todo opcional salvo la fecha, que por defecto es ahora).",
    "version": "Versión que se ha leído; si ya cambió, 412.", "bloqueada": "`true` marca la obligación como bloqueada (esperando algo); `false` quita el bloqueo.",
    "flujo_estricto": "Revisión y aprobación obligatorias antes de presentar.", "exigir_justificante": "Sin justificante subido no se presenta ni se cierra.",
    "oficina_id": "Id de la oficina (`null` la quita).", "rol": "`coordinador`, `gestor`, `revisor_fiscal` o `auditor`.", "alcance": "`organizacion`, `oficina` o `cliente`.", "alcance_id": "Id de la oficina o del cliente, según el alcance.",
    "nivel": "`gestion` (por defecto) o `lectura`.", "entidad": "Tipo de objeto: obligacion, certificado, cliente_fiscal, oficina, usuario, despacho.", "entidad_id": "Id del objeto.", "accion": "Acción, p. ej. `obligacion.transicion`.",
    "antes_de_id": "Cursor: pide los eventos anteriores a este id.", "limite": "Máximo de resultados.", "revocada_en": "Cuándo se retiró.", "vigente_hasta": "Hasta cuándo vale (opcional).",
    "contenido_base64": "El certificado público (PEM o DER) en base64. Nunca una clave privada ni un .p12/.pfx: se rechazan.", "huella": "Huella SHA-256 del certificado elegido cuando el archivo trae varios.",
    "ubicacion": "Dónde está custodiado el certificado (sin contraseñas).", "titular": "Persona que debe actuar en la renovación.",
    "inicio": "Hora de inicio (HH:MM).", "fin": "Hora de fin (HH:MM); si es anterior al inicio, el turno cruza la medianoche.", "color": "Color hexadecimal (#rrggbb).",
    "turno_id": "Id del turno (`null` quita el turno de ese día).", "usuario_id": "Id de la persona.", "fecha": "Fecha (AAAA-MM-DD).", "minutos": "Minutos a sumar (positivo) o restar (negativo).",
    "horas": "Horas.", "archivado": "El turno ya no se puede asignar.",
    "desde": "Primer día (AAAA-MM-DD).", "hasta": "Último día (AAAA-MM-DD); si se omite, es un solo día.", "medio_dia": "Medio día (solo para un único día laborable).",
    "motivo": "Motivo (opcional, hasta 500 caracteres).", "decision": "`aprobar` o `rechazar`.", "comentario": "Comentario para la persona (opcional).",
    "dias": "Días laborables que cuenta (0,5 si es medio día).", "estado": "Estado.", "persona": "Nombre de la persona.", "creada_en": "Cuándo se creó (ISO).", "resuelta_en": "Cuándo se resolvió (ISO).",
    "texto": "Contenido en texto.", "nombre": "Nombre.", "asunto": "Asunto.", "cuerpo": "Cuerpo (admite HTML en correo).", "email": "Correo electrónico.", "contrasena": "Contraseña.",
    "nombre_dispositivo": "Nombre para reconocer este dispositivo o integración.", "categoria_id": "Id del proyecto.", "proyecto_id": "Id del proyecto.", "cliente_id": "Id del cliente fiscal.",
    "cuenta_id": "Id de la cuenta de correo.", "referencia_externa": "Tu propio identificador (hasta 120 caracteres, único por usuario o despacho): sirve para sincronizar con otro sistema sin duplicar.",
    "areas": "Áreas a las que se limita el token: notas, tareas, correo, fiscal, fichaje, tiquets, ia, avisos, webhooks. Vacío = todas.", "permisos": "`solo_lectura` solo puede hacer GET.",
    "codigo_2fa": "Código de la app de autenticación (6 dígitos) o uno de recuperación, solo si la cuenta tiene la verificación en dos pasos. Sin él, el login responde `401 requiere_2fa`.",
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

# --- Gabinete de abogados e Inmobiliaria (app/rutas_api_verticales.py) ---------------------------------------------------------------------------------
_S, _I, _B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
_SN = {"type": "string", "nullable": True}
ESQUEMAS.update({
    "ProvisionAsunto": {"type": "object", "properties": {
        "expediente": _S, "provisiones": _SN, "suplidos": _SN, "honorarios": _SN, "devoluciones": _SN, "saldo": {**_SN, "description": "Saldo con formato («1.234,56 €»); negativo = el despacho ha adelantado dinero."},
        "saldo_centimos": _I, "provision_minima": _SN, "por_debajo_de_la_minima": _B,
        "ultimos_movimientos": {"type": "array", "items": {"type": "object", "properties": {"fecha": _S, "tipo": _S, "importe": _SN, "concepto": _S}}}}},
    "ParteAsunto": {"type": "object", "properties": {"id": _I, "rol": _S, "nombre": _S, "nif": _SN, "notas": _SN}},
    "VistaAgenda": {"type": "object", "properties": {"id": _I, "expediente_id": _I, "fecha_hora": _S, "tipo": _S, "lugar": _SN, "notas": _SN, "asunto": _SN}},
    "ResultadoConflicto": {"type": "object", "properties": {"hay_conflicto": _B, "hallazgos": {"type": "array", "items": {"type": "object"}}}},
    "InmuebleResumen": {"type": "object", "properties": {"id": _I, "expediente_id": _I, "direccion": _S, "municipio": _SN, "referencia": _SN, "tipo": _SN, "estado": _S, "superficie_m2": {"type": "number", "nullable": True},
                                                      "habitaciones": {"type": "integer", "nullable": True}, "propietario_nombre": _SN, "visitas_realizadas": _I, "precio": _SN}},
    "CruceDemanda": {"type": "object", "properties": {"puntos": {"type": "integer", "description": "De 0 a 100."}, "motivos": {"type": "array", "items": _S}, "faltan": {"type": "array", "items": {}},
                                                    "inmueble": {"type": "object", "properties": {"id": _I, "direccion": _S, "municipio": _SN, "tipo": _SN, "estado": _S, "precio": _SN}}}},
    "VisitaAgenda": {"type": "object", "properties": {"id": _I, "inmueble_id": _I, "fecha_hora": _S, "direccion": _S, "municipio": _SN, "visitante_nombre": _SN, "agente_nombre": _SN}},
    "ResumenAgencia": {"type": "object", "properties": {"inmuebles_activos": _I, "por_fase": {"type": "object", "additionalProperties": _I}, "demandas_activas": _I, "visitas_hoy": {"type": "array", "items": {"type": "object"}},
                                                      "visitas_semana": _I, "ofertas_abiertas": {"type": "array", "items": {"type": "object"}}, "sin_movimiento_14_dias": {"type": "array", "items": {"type": "object"}}}},
    "HiloMensajes": {"type": "object", "properties": {"expediente": _S, "admite_respuesta": {**_B, "description": "Hay un enlace vivo que admite mensajes."}, "sin_leer": _I,
                                                    "mensajes": {"type": "array", "items": {"type": "object", "properties": {"id": _I, "autor": {"type": "string", "enum": ["externo", "despacho"]}, "nombre": _SN, "texto": _S, "creado_en": _S, "leido_en": _SN}}}}},
})
RESPUESTAS.update({
    "provision_asunto_api": ("ProvisionAsunto", False), "partes_asunto_api": ("ParteAsunto", True), "agenda_vistas_api": ("VistaAgenda", True), "comprobar_conflicto_api": ("ResultadoConflicto", False),
    "listar_inmuebles_api": ("InmuebleResumen", True), "cruces_demanda_api": ("CruceDemanda", True), "agenda_visitas_api": ("VisitaAgenda", True), "resumen_agencia_api": ("ResumenAgencia", False),
    "mensajes_asunto_api": ("HiloMensajes", False), "mensajes_inmueble_api": ("HiloMensajes", False), "responder_asunto_api": ("Identificador", False), "responder_inmueble_api": ("Identificador", False),
    "comprobar_certificado_api": ("Certificado", False),
})


# --- Facturas para contabilizar (app/rutas_api_contabilidad.py) ---------------------------------------------------------------------------------------
ETIQUETAS["contabilidad"] = "Facturas para contabilizar: anotar, revisar, leer con IA, comprobar y exportar el SUENLACE.DAT para a3."
_TIPOS["lineas"] = {"type": "array", "items": {"type": "object", "properties": {"base": {"type": "string", "description": "Base imponible («1.234,56»)."}, "pct_iva": {"type": "string"},
                    "cuota_iva": {"type": "string"}, "pct_recargo": {"type": "string"}, "pct_retencion": {"type": "string"}, "cuenta": {"type": "string"}, "subtipo": {"type": "string"}}}}
_BOOLEANOS |= {"abono", "criterio_caja"}
REQUERIDOS.update({"anotar_factura_contable_api": ("cliente_fiscal_id", "tipo", "fecha", "numero", "tercero_nombre", "lineas"), "estado_factura_contable_api": ("estado",)})
_S, _I, _B, _SN = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}, {"type": "string", "nullable": True}
_N = {"type": "number", "nullable": True}
ESQUEMAS.update({
    "FacturaContable": {"type": "object", "properties": {"id": _I, "cliente_fiscal_id": _I, "cliente": _SN, "tipo": {"type": "string", "enum": ["emitida", "recibida"]}, "abono": _B, "fecha": _S, "trimestre": _S,
                                                       "numero": _S, "tercero": _S, "nif": _SN, "total": _N, "estado": {"type": "string", "enum": ["pendiente", "revisada", "exportada", "descartada"]},
                                                       "origen": _S, "lectura": _SN, "tiene_archivo": _B}},
    "FacturaContableDetalle": {"type": "object", "properties": {"id": _I, "cliente_fiscal_id": _I, "cliente": _SN, "tipo": _S, "abono": _B, "fecha": _S, "trimestre": _S, "numero": _S, "tercero": _S, "nif": _SN,
                                                               "total": _N, "estado": _S, "origen": _S, "lectura": _SN, "tiene_archivo": _B, "fecha_operacion": _S, "concepto": _SN, "referencia": _SN,
                                                               "subcuenta_tercero": _SN, "rectifica_numero": _SN, "rectifica_fecha": _SN, "criterio_caja": _B, "suplidos": _N, "notas": _SN,
                                                               "lectura_error": _SN, "problemas": {"type": "array", "items": _S}, "periodo_cerrado": _SN,
                                                               "lineas": {"type": "array", "items": {"type": "object", "properties": {"base": _N, "pct_iva": {"type": "number"}, "cuota_iva": _N,
                                                                          "pct_recargo": {"type": "number"}, "cuota_recargo": _N, "pct_retencion": {"type": "number"}, "cuota_retencion": _N,
                                                                          "cuenta": _SN, "tipo_operacion": _S}}},
                                                               "avisos_de_la_lectura": {"type": "array", "items": _S}}},
    "ResumenContabilidad": {"type": "object", "properties": {"plan": {"type": "object", "nullable": True, "description": "Uso del mes frente a las facturas incluidas en el plan; null si el despacho no tiene tarifa.", "properties": {"mes": _S, "unidad": {"type": "string", "enum": ["anotadas", "exportadas"]}, "usadas": _I, "incluidas": {"type": "integer", "nullable": True}, "de_mas": _I, "precio_por_factura_de_mas": _N, "limite": {"type": "integer", "nullable": True}, "restantes": {"type": "integer", "nullable": True}}}, "por_revisar": _I, "por_leer": _I, "para_exportar": _I, "clientes": {"type": "array", "items": {"type": "object", "properties": {
        "cliente_fiscal_id": _I, "cliente": _S, "por_revisar": _I, "por_leer": _I, "para_exportar": _I, "del_portal": _I, "mas_antigua": _SN}}}}},
    "ChequeoExportacion": {"type": "object", "properties": {"cliente": _S, "ok": _B, "facturas": _I, "registros": _I, "total": _N,
                                                           "errores": {"type": "array", "items": {"type": "object", "properties": {"registro": {"type": "integer", "nullable": True}, "mensaje": _S}}},
                                                           "avisos": {"type": "array", "items": {"type": "object", "properties": {"registro": {"type": "integer", "nullable": True}, "mensaje": _S}}},
                                                           "periodos_cerrados": {"type": "array", "items": {"type": "object", "properties": {"trimestre": _S, "motivo": _S, "detalle": _S}}},
                                                           "subcuentas_nuevas": {"type": "array", "items": {"type": "object", "properties": {"tipo": _S, "nif": _S, "cuenta": _S, "nombre": _SN}}}}},
    "ExportacionContable": {"type": "object", "properties": {"lote": {**_I, "description": "Descárgalo con GET /contabilidad/lotes/{id}/fichero."}, "cliente": _S, "facturas": _I, "registros": _I,
                                                            "avisos": {"type": "array", "items": _S}}},
})
RESPUESTAS.update({"listar_facturas_contables_api": ("FacturaContable", True), "ver_factura_contable_api": ("FacturaContableDetalle", False), "anotar_factura_contable_api": ("FacturaContableDetalle", False),
                   "estado_factura_contable_api": ("FacturaContableDetalle", False), "leer_factura_contable_api": ("FacturaContableDetalle", False), "resumen_contabilidad_api": ("ResumenContabilidad", False),
                   "comprobar_exportacion_api": ("ChequeoExportacion", False), "exportar_contabilidad_api": ("ExportacionContable", False)})
BINARIAS["fichero_del_lote_api"] = "application/octet-stream"


# --- Trabajo con tareas: transiciones con versión, clientes vinculados, tareas de un cliente (app/rutas_api_tareas_trabajo.py) ---
ESQUEMAS["ClienteDeTarea"] = {"type": "object", "properties": {"id": {"type": "integer"}, "nombre": {"type": "string"}, "nif": {"type": "string", "nullable": True}, "principal": {"type": "boolean"}}}
ESQUEMAS["ClientesDeTarea"] = {"type": "object", "properties": {"clientes": {"type": "array", "items": {"$ref": "#/components/schemas/ClienteDeTarea"}}, "version": {"type": "integer", "description": "Versión de la tarea tras el cambio."}}}
RESPUESTAS.update({"transicionar_tarea": ("TareaOutlook", False), "clientes_de_la_tarea": ("ClientesDeTarea", False), "fijar_clientes_de_la_tarea": ("ClientesDeTarea", False), "tareas_del_cliente": ("TareaOutlook", True)})
ESQUEMAS["SubtareasDeTarea"] = {"type": "object", "properties": {"subtareas": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "asunto": {"type": "string"}, "estado": {"type": "string"},
                                "fecha_vencimiento": {"type": "string", "nullable": True}, "asignada_a": {"type": "integer", "nullable": True}}}},
                                "progreso": {"type": "object", "properties": {"total": {"type": "integer"}, "hechas": {"type": "integer"}, "abiertas": {"type": "integer"}}}}}
ESQUEMAS["AdjuntoTarea"] = {"type": "object", "properties": {"id": {"type": "integer"}, "nombre_archivo": {"type": "string"}, "tipo_mime": {"type": "string"}, "tamano_bytes": {"type": "integer"},
                            "subido_por": {"type": "integer", "nullable": True}, "creado_en": {"type": "string"}}}
ESQUEMAS["ResultadoAdjuntosTarea"] = {"type": "array", "items": {"type": "object", "properties": {"archivo": {"type": "string"}, "ok": {"type": "boolean"}, "id": {"type": "integer"},
                                      "codigo": {"type": "string", "description": "tipo_no_admitido, archivo_vacio, archivo_grande, clave_privada, duplicado, limite o sin_permiso."}, "error": {"type": "string"}}}}
RESPUESTAS.update({"subtareas_de_la_tarea": ("SubtareasDeTarea", False), "crear_subtarea_de_la_tarea": ("TareaOutlook", False), "adjuntos_de_la_tarea": ("AdjuntoTarea", True),
                   "subir_adjuntos_de_la_tarea": ("ResultadoAdjuntosTarea", False)})
BINARIAS["descargar_adjunto_de_tarea"] = "application/octet-stream"
SIN_DATOS_ESPERADOS.add("eliminar_adjunto_de_tarea")
ESQUEMAS["RevisionTarea"] = {"type": "object", "properties": {"id": {"type": "integer"}, "tarea_id": {"type": "integer"}, "solicitada_por": {"type": "integer"}, "revisor_id": {"type": "integer"},
                             "estado": {"type": "string", "enum": ["pendiente", "aprobada", "cambios", "cancelada"]}, "nota_solicitud": {"type": "string", "nullable": True},
                             "nota_resolucion": {"type": "string", "nullable": True}, "solicitada_en": {"type": "string"}, "resuelta_en": {"type": "string", "nullable": True},
                             "modo": {"type": "string", "enum": ["todos", "cualquiera"], "description": "`todos`: tienen que aprobar todos los revisores; `cualquiera`: basta uno. Pedir cambios detiene la revisión en ambos."},
                             "revisores": {"type": "array", "items": {"type": "integer"}}, "pendientes": {"type": "array", "items": {"type": "integer"}, "description": "Revisores que aún no han votado."},
                             "aprobados": {"type": "integer"},
                             "votos": {"type": "array", "items": {"type": "object", "properties": {"revisor_id": {"type": "integer"}, "estado": {"type": "string", "enum": ["pendiente", "aprobado", "cambios"]},
                                       "nota": {"type": "string", "nullable": True}, "votado_en": {"type": "string", "nullable": True}}}}}}
ESQUEMAS["RevisionesDeTarea"] = {"type": "object", "properties": {"pendiente": {"allOf": [{"$ref": "#/components/schemas/RevisionTarea"}], "nullable": True},
                                 "historial": {"type": "array", "items": {"$ref": "#/components/schemas/RevisionTarea"}}}}
ESQUEMAS["VisibleCliente"] = {"type": "object", "properties": {"visible_cliente": {"type": "boolean"}, "comentarios_cliente": {"type": "boolean", "description": "El cliente puede escribir comentarios en la tarea mientras esté abierta."}}}
ESQUEMAS["InformeTareas"] = {"type": "object", "description": "Cifras de tareas por persona y por cliente. Lo «histórico» se mide en la ventana; lo de «ahora» es la foto de hoy.", "properties": {
    "ventana": {"type": "object", "properties": {"desde": {"type": "string"}, "hasta": {"type": "string"}, "dias": {"type": "integer"}}}, "hoy": {"type": "string"}, "alcance": {"type": "string"},
    "creadas_en_ventana": {"type": "integer"}, "ahora": {"type": "object", "properties": {"abiertas": {"type": "integer"}, "vencidas": {"type": "integer"}, "bloqueadas": {"type": "integer"}}},
    "en_ventana": {"type": "object", "properties": {"completadas": {"type": "integer"}, "con_fecha": {"type": "integer"}, "en_plazo": {"type": "integer"},
                   "tasa_en_plazo": {"type": "number", "nullable": True, "description": "en_plazo / con_fecha, en %; null si no hay ninguna completada con fecha límite."},
                   "tiempo_medio_cierre_dias": {"type": "number", "nullable": True}, "tiempo_medio_n": {"type": "integer"}}},
    "por_responsable": {"type": "array", "items": {"type": "object"}}, "por_cliente": {"type": "array", "items": {"type": "object"}}, "bloqueadas": {"type": "array", "items": {"type": "object"}},
    "proximas": {"type": "object", "properties": {"dias": {"type": "integer"}, "tareas": {"type": "array", "items": {"type": "object"}}, "vencimientos_fiscales": {"type": "array", "items": {"type": "object"}},
                 "certificados": {"type": "array", "items": {"type": "object"}}}}}}
RESPUESTAS.update({"informe_de_tareas": ("InformeTareas", False), "revision_de_la_tarea": ("RevisionesDeTarea", False), "pedir_revision_de_la_tarea": ("RevisionesDeTarea", False),
                   "resolver_revision_de_la_tarea": ("RevisionesDeTarea", False), "cancelar_revision_de_la_tarea": ("RevisionesDeTarea", False), "fijar_visible_cliente_de_la_tarea": ("VisibleCliente", False)})
