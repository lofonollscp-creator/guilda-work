"""Conjunto de evaluación de la oferta de herramientas del asistente (y del MCP por grupos): para cada petición realista de una persona
en un despacho, qué herramienta tiene que estar disponible YA en el primer turno (sin que el modelo tenga que pedir `activar_herramientas`).
Se mide en tests/test_evaluacion_herramientas.py. Para ampliarlo: añade una línea (petición, herramienta esperada)."""

CASOS: list[tuple[str, str]] = [
    # núcleo: notas, tareas, calendario, resumen
    ("apunta una nota: llamar al cliente de Vidal mañana", "crear_nota"),
    ("qué notas tengo sobre la reforma", "listar_notas"),
    ("crea una tarea para revisar el modelo 303 el viernes", "crear_tarea"),
    ("qué tareas tengo pendientes", "listar_tareas"),
    ("marca como hecha la tarea de las facturas", "completar_tarea"),
    ("qué tengo hoy", "listar_tareas_hoy"),
    ("qué hay en mi calendario esta semana", "consultar_calendario"),
    ("hazme un resumen de mi día", "resumen_del_dia"),
    ("busca todo lo que tengo sobre el cliente Soler", "buscar_semantico"),
    ("cambia el título de esa nota", "editar_nota"),
    ("lista mis proyectos", "listar_proyectos"),
    # tareas avanzadas
    ("añade un paso a la checklist de esa tarea", "agregar_item_checklist"),
    ("asigna la tarea a Marta", "asignar_tarea"),
    ("quiero una tarea recurrente cada mes para el IVA", "crear_tarea_recurrente"),
    ("restaura la tarea que borré de la papelera", "restaurar_de_papelera"),
    ("inicia el cronómetro de la tarea de la auditoría", "iniciar_cronometro_tarea"),
    ("comenta en la tarea que ya está lista la documentación", "comentar_tarea"),
    ("elimina esa nota", "eliminar_nota"),
    ("fija la nota de las claves arriba", "fijar_nota"),
    ("cuántas horas he dedicado a cada proyecto este mes (estadísticas)", "estadisticas_por_categoria"),
    ("exporta mi histórico", "exportar_historial"),
    ("crea un proyecto nuevo para la declaración de la renta", "crear_proyecto"),
    # correo
    ("qué correos tengo sin leer en la bandeja", "listar_bandeja_entrada"),
    ("lee el último correo de Hacienda", "leer_correo"),
    ("prepara un borrador de respuesta al correo del cliente", "preparar_borrador_correo"),
    ("mueve ese email a la carpeta de facturas", "mover_correo"),
    ("destaca el correo del banco", "destacar_correo"),
    ("pospón ese mail hasta el lunes", "posponer_correo"),
    ("crea una regla para que los correos de Endesa se marquen con una categoría", "crear_regla_correo"),
    ("convierte ese correo en una tarea", "crear_tarea_desde_correo"),
    ("guarda ese correo como nota", "guardar_nota_desde_correo"),
    ("sincroniza mi correo", "sincronizar_correo"),
    ("cuál es mi firma de correo", "obtener_firma_correo"),
    ("muéstrame la conversación completa con el proveedor por email", "listar_conversacion_correo"),
    # fiscal
    ("qué vencimientos fiscales tengo esta semana", "listar_vencimientos_fiscales"),
    ("marca el modelo 303 de Construcciones Vidal como presentado", "marcar_presentado_vencimiento_fiscal"),
    ("da de alta un cliente fiscal nuevo", "crear_cliente_fiscal"),
    ("genera los vencimientos del IVA del año", "generar_vencimientos_fiscales"),
    ("resumen fiscal del cliente Puig", "resumen_cliente_fiscal"),
    ("lista mis clientes", "listar_clientes_fiscales"),
    ("cambia la fecha límite del modelo 111", "editar_vencimiento_fiscal"),
    # fichaje
    ("ficha mi entrada", "fichar"),
    ("cuántas horas trabajé esta semana, mis fichajes", "listar_mis_fichajes"),
    ("registra mi salida de la jornada", "fichar"),
    # tiquets
    ("crea un tiquet por el error al subir documentos", "crear_tiquet"),
    ("qué tiquets hay abiertos", "listar_tiquets"),
    ("cierra el tiquet 12", "cambiar_estado_tiquet"),
    # facturación
    ("hazle una factura de 300 euros a Soler por la gestión trimestral", "crear_factura_cliente"),
    ("qué facturas tiene emitidas el cliente Ferrer", "listar_facturas_cliente"),
    # crm
    ("crea un lead para la panadería nueva", "crm_crear_lead"),
    ("qué leads tengo en el CRM", "crm_listar_leads"),
    ("añade un contacto al CRM", "crm_crear_contacto"),
    # archivos
    ("busca el pdf de la escritura en el drive", "drive_buscar_archivos"),
    ("sube este archivo al Drive", "drive_subir_archivo"),
    ("muéstrame las hojas de cálculo disponibles", "listar_tablas_hojas"),
    ("qué contiene el documento adjunto del chat", "leer_adjunto_chat"),
    # soporte de la plataforma y ajustes de la propia cuenta
    ("cómo conecto mi correo", "ayuda_buscar"),
    ("dónde está la configuración del perfil", "abrir_pantalla"),
    ("pon mi idioma en catalán", "cambiar_mis_ajustes"),
    ("qué ajustes de notificaciones tengo", "ver_mis_ajustes"),
    # firmas
    ("envía el contrato a firma electrónica", "enviar_documento_a_firma"),
    ("qué documentos están pendientes de firma", "listar_documentos_firma"),
    ("crea un documento para firmar", "crear_documento_firma"),
]
