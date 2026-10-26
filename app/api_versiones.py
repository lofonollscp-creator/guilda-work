"""Historial de versiones del contrato de `/api/v1` (cabecera `X-API-Version`, `mayor.menor`). El menor sube con cada ampliación
compatible (campos nuevos siempre opcionales); el mayor solo si algo se rompe. Alimenta la página «Registro de cambios» de /docs.

Al subir `rutas_api.API_VERSION` hay que añadir aquí su entrada: un test lo exige. La primera entrada es la más reciente."""

# (versión | None, fecha, [(tipo, texto)]). Antes de la 1.3 la API no enviaba la cabecera: esas entradas llevan solo la fecha.
HISTORIAL = [
    ("1.7", "2026-10-26", [
        ("Mejora", "`GET /mi-dia` y `GET /tareas-outlook/tablero` traen en cada tarea los mismos indicadores que la lista (`vencida`, `n_comentarios`, `checklist_hechas`, `checklist_total`, "
                   "`bloqueos`, `rol`, `asignada_nombre`, `creador_nombre`). `/mi-dia` documenta sus cinco secciones (`vencidas`, `hoy`, `en_progreso`, `asignadas`, `compartidas`)."),
        ("Nuevo", "`GET /tareas-outlook/tablero?recientes=15`: de las completadas, solo las N más recientes, como el tablero de la web. Sin el parámetro, todo como siempre."),
        ("Compatibilidad", "Todo aditivo: ningún campo ni ruta existente cambia."),
    ]),
    ("1.6", "2026-10-26", [
        ("Nuevo", "`GET /tareas-outlook` admite `completadas` (`0` oculta las completadas salvo que se pida un `estado`, `1` las incluye; sin él, todo como siempre) y trae en cada fila "
                  "`n_comentarios`, `checklist_hechas`, `checklist_total` y `bloqueos`, para pintar la lista como la web sin más llamadas."),
        ("Nuevo", "`POST /tareas-outlook` admite `texto_libre` (el asunto se interpreta como en el cuadro de alta de la web: «viernes 10h pedir extractos @luis !alta #IVA»; la respuesta "
                  "trae `sin_resolver` con lo que no se pudo entender) y los campos explícitos `categoria_id` (proyecto), `asignada_a` y `cliente_fiscal_id`."),
        ("Nuevo", "`GET /tareas-outlook/categorias-outlook`: las categorías (estilo Outlook) que usan tus tareas, para el filtro `categoria`."),
        ("Compatibilidad", "Todo aditivo: ningún campo ni ruta existente cambia."),
    ]),
    ("1.5", "2026-10-24", [
        ("Nuevo", "`GET /auth/me` amplía su respuesta para la app móvil: `despachos` (los de la persona, con el principal y lo que es en cada uno), "
                  "`despacho_activo`, `modulos` (qué módulos de negocio tiene activos el despacho), `permisos`, `cifrado`, `apariencia` y `app` "
                  "(versión mínima y recomendada, enlace de la tienda). La cabecera `X-Despacho` ya elegía el despacho; ahora la app puede listarlos."),
        ("Nuevo", "`426 actualiza_app`: una app que manda `X-App-Version` menor que la mínima admitida recibe este error, con `version_minima` y `url_tienda`. "
                  "Quien no manda la cabecera (web, integraciones, MCP) no se ve afectado."),
        ("Nuevo", "`GET /perfil` incluye `apariencia` (`tema`, `densidad`, `idioma`) y `PUT /perfil` los acepta: el tema y el idioma de la cuenta son los mismos en la web y en la app."),
        ("Mejora", "`GET /tareas-outlook` incluye `vencida` en cada fila (derivada de la fecha y el estado, igual que en el detalle)."),
        ("Nuevo", "`GET /buscar` devuelve en cada resultado su `destino` (`{tipo, id}`), no incluye los vectores internos, y su `id` se documenta como lo que es: «tipo-N» (`tarea-12`)."),
        ("Mejora", "Los `412 version_obsoleta` de clientes fiscales y vencimientos incluyen `version_actual` (como ya hacían los `409` de las tareas), "
                   "para ofrecer «ver cambios / sobrescribir» sin otra petición."),
        ("Mejora", "El contrato describe con exactitud `GET /ia/conversaciones` (`{activa, conversaciones}`) y admite `id: null` en los atajos de serie de `GET /ia/atajos`."),
        ("Nuevo", "`GET /hoy`: la bandeja única de lo que necesita tu atención (tareas, correo, plazos, vencimientos, visitas, traspasos, ausencias, facturas, certificados...) del "
                  "despacho activo, por urgencia, en una sola llamada. Cada elemento lleva `destino` (`{tipo, id}`) y las `acciones` posibles; los módulos no activos no aparecen."),
        ("Nuevo", "`GET /notificaciones` devuelve en cada aviso su `destino` (`{tipo, id}`) y `canal`, y admite los filtros `tipo`, `desde` y `no_leidas`. Los push llevan el mismo "
                  "contrato: `data.destino` (JSON), `destino_tipo`, `destino_id`, `despacho_id`, `notificacion_id` y `canal` (canal de Android por familia de aviso)."),
        ("Compatibilidad", "Todo aditivo: ningún campo ni ruta existente cambia."),
    ]),
    ("1.4", "2026-10-11", [
        ("Nuevo", "`GET /health`: comprobación de vida pública (sin token) para monitores externos; 200 si responde la base de datos, 503 si no."),
        ("Nuevo", "Restricciones de red por token: `ips_permitidas` (IP o redes CIDR; `403 ip_no_permitida` desde otra dirección) y `origenes_cors` "
                  "(orígenes web exactos que pueden usar el token desde un navegador). Un token con IPs no sirve por MCP."),
        ("Nuevo", "Límites por tipo de petición: además de 600/min en total, 200 escrituras y 20 operaciones pesadas (IA, exportaciones, importaciones, "
                  "sincronizar un buzón, enviar correo) por minuto. Cabecera `X-RateLimit-Scope` y campo `cupo` en el 429."),
        ("Mejora", "OpenAPI completo (cuerpos, parámetros, respuestas, errores y ejemplos) con clientes de Python y TypeScript y colección de Postman "
                   "generados de él, y explorador interactivo con «Probar»."),
        ("Compatibilidad", "Todo aditivo: ningún campo ni ruta existente cambia."),
    ]),
    ("1.3", "2026-10-10", [
        ("Nuevo", "Errores con `codigo` estable y `request_id` (cabecera `X-Request-Id`)."),
        ("Nuevo", "Límite de 600 peticiones por minuto y persona, `Idempotency-Key` en POST, `ETag`/`304` en lecturas y `?campos=` para devolver solo algunos campos."),
        ("Nuevo", "`GET /sync` incremental con cursor, `X-Total-Count` y `limit`/`offset` uniformes."),
        ("Nuevo", "Tokens con permisos (completo o solo lectura), áreas (`notas`, `tareas`, `correo`, `fiscal`, `fichaje`, `tiquets`, `ia`, `avisos`, "
                  "`webhooks`), caducidad y registro de uso (`GET /tokens/{id}/uso`)."),
        ("Nuevo", "`referencia_externa` en notas, tareas y clientes fiscales, con alta o actualización por `PUT .../por-referencia/{ref}`."),
        ("Nuevo", "Webhooks con cola persistente, reintentos (6) y firma `X-Guilda-Signature-V2` con marca de tiempo; eventos `cliente.creado` y `correo.sin_respuesta`."),
        ("Nuevo", "Paridad con la web y el MCP: tareas completas (estado con dependencias, comentarios, recordatorios, compartir, lotes, plantillas, recurrentes), "
                  "calendario fiscal completo, adjuntos de notas, envío de correo con adjuntos y programado, y administración del fichaje."),
    ]),
    (None, "2026-10-06", [
        ("Nuevo", "Tokens de solo lectura, paginación y webhooks salientes por despacho; 22 herramientas más en el MCP."),
    ]),
    (None, "2026-08-19", [("Nuevo", "Eventos de negocio reales para webhooks y automatizaciones.")]),
    (None, "2026-08-15", [("Nuevo", "API del calendario fiscal para la app móvil.")]),
    (None, "2026-08-04", [("Nuevo", "Documento OpenAPI (`/api/v1/openapi.json`), explorador de la API y búsqueda semántica.")]),
    (None, "2026-07-16", [("Nuevo", "Primera API REST con tokens por dispositivo para la app móvil.")]),
]
