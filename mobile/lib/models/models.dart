import '../l10n/app_localizations.dart';

/// Modelos de datos para el Dashboard y Notas/Tareas con duración (Fase 4c).
/// Reflejan los campos que ya devuelve la API de la Fase 2
/// (app/rutas_api.py), que a su vez son los mismos que usa la web
/// (app/db.py) — ver plan de la app móvil para el mapeo exacto.
class Categoria {
  final int id;
  final String nombre;
  final String? color;
  final bool favorito;

  Categoria({
    required this.id,
    required this.nombre,
    this.color,
    required this.favorito,
  });

  factory Categoria.fromJson(Map<String, dynamic> json) => Categoria(
        id: json['id'] as int,
        nombre: json['nombre'] as String,
        color: json['color'] as String?,
        favorito: (json['favorito'] as int? ?? 0) != 0,
      );
}

/// Tarea con duración en curso o en pausa (db.tareas_activas). No incluye
/// los campos de cronómetro (segundos_pausados, segundos_trabajados_congelado)
/// porque esta fase no muestra un reloj en vivo, solo el estado.
class TareaActiva {
  final int id;
  final String nombre;
  final int categoriaId;
  final String estado;

  TareaActiva({
    required this.id,
    required this.nombre,
    required this.categoriaId,
    required this.estado,
  });

  factory TareaActiva.fromJson(Map<String, dynamic> json) => TareaActiva(
        id: json['id'] as int,
        nombre: json['nombre'] as String,
        categoriaId: json['categoria_id'] as int,
        estado: json['estado'] as String,
      );
}

/// Una fila del histórico combinado de notas y tareas (db.historial).
class EntradaHistorial {
  final String origen; // 'nota' o 'tarea'
  final int id;
  final String texto;
  final String? tipo; // solo si origen == 'tarea': 'duracion' o 'instantanea'
  final String? estado;
  final String? timestamp;
  final int? duracionSegundos;
  final String? categoriaNombre;
  final String? categoriaColor;

  EntradaHistorial({
    required this.origen,
    required this.id,
    required this.texto,
    this.tipo,
    this.estado,
    this.timestamp,
    this.duracionSegundos,
    this.categoriaNombre,
    this.categoriaColor,
  });

  factory EntradaHistorial.fromJson(Map<String, dynamic> json) => EntradaHistorial(
        origen: json['origen'] as String,
        id: json['id'] as int,
        texto: json['texto'] as String,
        tipo: json['tipo'] as String?,
        estado: json['estado'] as String?,
        timestamp: json['timestamp'] as String?,
        duracionSegundos: json['duracion_segundos'] as int?,
        categoriaNombre: json['categoria_nombre'] as String?,
        categoriaColor: json['categoria_color'] as String?,
      );
}

/// Tarea "estilo Outlook" (independiente de los menús), Fase 4d — mismos
/// campos que app/templates/tarea_outlook_editar.html.
class TareaOutlook {
  final int id;
  final String asunto;
  final String? cuerpo;
  final String estado;
  final String prioridad;
  final int porcentajeCompletado;
  final String? fechaInicio;
  final String? fechaVencimiento;
  final String? categoriaOutlook;

  TareaOutlook({
    required this.id,
    required this.asunto,
    this.cuerpo,
    required this.estado,
    required this.prioridad,
    required this.porcentajeCompletado,
    this.fechaInicio,
    this.fechaVencimiento,
    this.categoriaOutlook,
  });

  factory TareaOutlook.fromJson(Map<String, dynamic> json) => TareaOutlook(
        id: json['id'] as int,
        asunto: json['asunto'] as String,
        cuerpo: json['cuerpo'] as String?,
        estado: json['estado'] as String,
        prioridad: json['prioridad'] as String,
        porcentajeCompletado: json['porcentaje_completado'] as int? ?? 0,
        fechaInicio: json['fecha_inicio'] as String?,
        fechaVencimiento: json['fecha_vencimiento'] as String?,
        categoriaOutlook: json['categoria_outlook'] as String?,
      );
}

const estadosTareaOutlook = [
  ('no_iniciada', 'No iniciada'),
  ('en_progreso', 'En progreso'),
  ('completada', 'Completada'),
  ('esperando', 'Esperando a otros'),
  ('aplazada', 'Aplazada'),
];

const prioridadesTareaOutlook = [
  ('baja', 'Baja'),
  ('normal', 'Normal'),
  ('alta', 'Alta'),
];

/// Cuenta de correo IMAP/POP3+SMTP (db.listar_cuentas_correo), Fase 4e —
/// solo se lee desde el móvil, no se crean/editan cuentas en esta fase.
class CuentaCorreo {
  final int id;
  final String nombre;
  final String protocolo;
  final String host;
  final int puerto;
  final String usuario;
  final String? smtpHost;
  final int? smtpPuerto;
  final String? ultimaSincronizacion;

  CuentaCorreo({
    required this.id,
    required this.nombre,
    required this.protocolo,
    required this.host,
    required this.puerto,
    required this.usuario,
    this.smtpHost,
    this.smtpPuerto,
    this.ultimaSincronizacion,
  });

  factory CuentaCorreo.fromJson(Map<String, dynamic> json) => CuentaCorreo(
        id: json['id'] as int,
        nombre: json['nombre'] as String,
        protocolo: json['protocolo'] as String,
        host: json['host'] as String,
        puerto: json['puerto'] as int,
        usuario: json['usuario'] as String,
        smtpHost: json['smtp_host'] as String?,
        smtpPuerto: json['smtp_puerto'] as int?,
        ultimaSincronizacion: json['ultima_sincronizacion'] as String?,
      );
}

/// Carpeta IMAP de una cuenta (db.correo_carpetas / correo.listar_carpetas).
class Carpeta {
  final String nombre;
  final String nombreVisible;

  Carpeta({required this.nombre, required this.nombreVisible});

  factory Carpeta.fromJson(Map<String, dynamic> json) => Carpeta(
        nombre: json['nombre'] as String,
        nombreVisible: json['nombre_visible'] as String,
      );
}

/// Adjunto de un mensaje (db.correo_adjuntos) — solo metadatos, sin
/// contenido: en esta fase no se descargan adjuntos desde el móvil.
class Adjunto {
  final int id;
  final String nombreArchivo;
  final String tipoMime;
  final int tamanoBytes;

  Adjunto({
    required this.id,
    required this.nombreArchivo,
    required this.tipoMime,
    required this.tamanoBytes,
  });

  factory Adjunto.fromJson(Map<String, dynamic> json) => Adjunto(
        id: json['id'] as int,
        nombreArchivo: json['nombre_archivo'] as String,
        tipoMime: json['tipo_mime'] as String,
        tamanoBytes: json['tamano_bytes'] as int,
      );
}

/// Categoría de correo (db.listar_categorias_correo) — distinta de las
/// categorías/menús de Notas y Tareas.
class CategoriaCorreo {
  final int id;
  final String nombre;
  final String color;

  CategoriaCorreo({required this.id, required this.nombre, required this.color});

  factory CategoriaCorreo.fromJson(Map<String, dynamic> json) => CategoriaCorreo(
        id: json['id'] as int,
        nombre: json['nombre'] as String,
        color: json['color'] as String,
      );
}

/// Mensaje de correo (db.correo_mensajes) — se usa tanto en la lista de la
/// bandeja (sin `adjuntos`) como en el detalle (con `adjuntos` rellenado).
class Mensaje {
  final int id;
  final int cuentaId;
  final String carpeta;
  final String asunto;
  final String remitente;
  final String destinatarios;
  final String? cc;
  final String? fecha;
  final String? cuerpoTexto;
  final String? cuerpoHtml;
  final bool leido;
  final int? categoriaId;
  final bool destacado;
  final String? messageId;
  final bool remitenteConfiable;
  final List<Adjunto> adjuntos;

  Mensaje({
    required this.id,
    required this.cuentaId,
    required this.carpeta,
    required this.asunto,
    required this.remitente,
    required this.destinatarios,
    this.cc,
    this.fecha,
    this.cuerpoTexto,
    this.cuerpoHtml,
    required this.leido,
    this.categoriaId,
    required this.destacado,
    this.messageId,
    this.remitenteConfiable = false,
    this.adjuntos = const [],
  });

  factory Mensaje.fromJson(Map<String, dynamic> json) => Mensaje(
        id: json['id'] as int,
        cuentaId: json['cuenta_id'] as int,
        carpeta: json['carpeta'] as String,
        asunto: json['asunto'] as String,
        remitente: json['remitente'] as String,
        destinatarios: json['destinatarios'] as String,
        cc: json['cc'] as String?,
        fecha: json['fecha'] as String?,
        cuerpoTexto: json['cuerpo_texto'] as String?,
        cuerpoHtml: json['cuerpo_html'] as String?,
        leido: (json['leido'] as int? ?? 0) != 0,
        categoriaId: json['categoria_id'] as int?,
        destacado: (json['destacado'] as int? ?? 0) != 0,
        messageId: json['message_id'] as String?,
        remitenteConfiable: json['remitente_confiable'] as bool? ?? false,
        adjuntos: json['adjuntos'] == null
            ? const []
            : (json['adjuntos'] as List)
                .map((a) => Adjunto.fromJson(a as Map<String, dynamic>))
                .toList(),
      );
}

/// Remitente marcado como de confianza (db.correo_remitentes_confiables),
/// Fase 5 — sus imágenes remotas y adjuntos no se bloquean/avisan.
class RemitenteConfiable {
  final int id;
  final String direccion;

  RemitenteConfiable({required this.id, required this.direccion});

  factory RemitenteConfiable.fromJson(Map<String, dynamic> json) => RemitenteConfiable(
        id: json['id'] as int,
        direccion: json['direccion'] as String,
      );
}

/// Regla de categorización automática por remitente (db.correo_reglas_categoria),
/// Fase 5 — remitentePatron es un email exacto o "@dominio.com".
class ReglaCategoria {
  final int id;
  final String remitentePatron;
  final int categoriaId;
  final String categoriaNombre;
  final String categoriaColor;

  ReglaCategoria({
    required this.id,
    required this.remitentePatron,
    required this.categoriaId,
    required this.categoriaNombre,
    required this.categoriaColor,
  });

  factory ReglaCategoria.fromJson(Map<String, dynamic> json) => ReglaCategoria(
        id: json['id'] as int,
        remitentePatron: json['remitente_patron'] as String,
        categoriaId: json['categoria_id'] as int,
        categoriaNombre: json['categoria_nombre'] as String,
        categoriaColor: json['categoria_color'] as String,
      );
}

/// Destinatario al que ya se ha enviado correo antes (db.correo_destinatarios_recientes),
/// Fase 5 — usado para autocompletar Para/Cc/Cco al redactar.
class DestinatarioReciente {
  final String direccion;
  final String? nombreMostrado;

  DestinatarioReciente({required this.direccion, this.nombreMostrado});

  factory DestinatarioReciente.fromJson(Map<String, dynamic> json) => DestinatarioReciente(
        direccion: json['direccion'] as String,
        nombreMostrado: json['nombre_mostrado'] as String?,
      );

  String get etiqueta => nombreMostrado != null && nombreMostrado!.isNotEmpty
      ? '$nombreMostrado <$direccion>'
      : direccion;
}

/// Un adjunto nuevo elegido en el móvil para enviar (aún no subido) —
/// se codifica a base64 justo antes de mandarlo a la API.
class ArchivoAdjuntoNuevo {
  final String nombre;
  final String tipo;
  final List<int> bytes;

  ArchivoAdjuntoNuevo({required this.nombre, required this.tipo, required this.bytes});
}

/// Herramienta externa conectada (app/herramientas.py), Fase 9 — se abre en
/// un WebView. No incluye "chat" (Element): eso se consume como cliente
/// Matrix nativo, ver ChatConfig más abajo.
class Herramienta {
  final String id;
  final String nombre;
  final String descripcion;
  final String icono;
  /// Nombre de archivo en app/static/logos/ con el logotipo oficial real
  /// (mismo campo que ya usa herramientas.html en la web) -- null en
  /// entradas antiguas que todavía no lo tengan, se cae al emoji de
  /// `icono` en ese caso (ver herramientas_screen.dart).
  final String? iconoLogo;
  final String url;
  final bool sso;
  final bool disponible;

  Herramienta({
    required this.id,
    required this.nombre,
    required this.descripcion,
    required this.icono,
    this.iconoLogo,
    required this.url,
    required this.sso,
    this.disponible = true,
  });

  factory Herramienta.fromJson(Map<String, dynamic> json) => Herramienta(
        id: json['id'] as String,
        nombre: json['nombre'] as String,
        descripcion: json['descripcion'] as String,
        icono: json['icono'] as String,
        iconoLogo: json['icono_logo'] as String?,
        url: json['url'] as String,
        sso: json['sso'] as bool,
        disponible: json['disponible'] as bool? ?? true,
      );
}

/// Configuración del chat nativo (Matrix/Synapse), Fase 9.
class ChatConfig {
  final String homeserverUrl;

  ChatConfig({required this.homeserverUrl});

  factory ChatConfig.fromJson(Map<String, dynamic> json) =>
      ChatConfig(homeserverUrl: json['homeserver_url'] as String);
}

/// Tiquet de soporte interno (errores/sugerencias sobre la propia Guilda
/// Work) -- tablero COMPARTIDO entre todos los usuarios, a diferencia del
/// resto de modelos de este archivo (que son siempre datos propios).
class Tiquet {
  final int id;
  final String tipo;
  final String titulo;
  final String? descripcion;
  final String estado;
  final int usuarioId;
  final String? autorEmail;
  final String creadoEn;

  Tiquet({
    required this.id,
    required this.tipo,
    required this.titulo,
    this.descripcion,
    required this.estado,
    required this.usuarioId,
    this.autorEmail,
    required this.creadoEn,
  });

  factory Tiquet.fromJson(Map<String, dynamic> json) => Tiquet(
        id: json['id'] as int,
        tipo: json['tipo'] as String,
        titulo: json['titulo'] as String,
        descripcion: json['descripcion'] as String?,
        estado: json['estado'] as String,
        usuarioId: json['usuario_id'] as int,
        autorEmail: json['autor_email'] as String?,
        creadoEn: json['creado_en'] as String,
      );
}

/// Función (no const) porque las etiquetas dependen del idioma elegido
/// -- ver AppLocalizations.of(context)! en cada pantalla que las usa.
List<(String, String)> tiposTiquet(AppLocalizations t) => [
      ('error', t.tiquetTipoError),
      ('sugerencia', t.tiquetTipoSugerencia),
    ];

List<(String, String)> estadosTiquet(AppLocalizations t) => [
      ('sin_revisar', t.tiquetEstadoSinRevisar),
      ('en_revision', t.tiquetEstadoEnRevision),
      ('finalizado', t.tiquetEstadoFinalizado),
    ];

/// Datos personales del trabajador para el registro de fichaje (art. 34.9
/// ET) -- hace falta rellenar nombreCompleto+dniNie antes de poder fichar.
class FichajeDatos {
  final String? nombreCompleto;
  final String? dniNie;
  final String? numeroAfiliacionSs;
  final String? categoriaProfesional;
  final String? tipoContrato;
  final String? fechaAlta;
  final double? jornadaSemanalHoras;
  final String? convenioColectivo;

  FichajeDatos({
    this.nombreCompleto,
    this.dniNie,
    this.numeroAfiliacionSs,
    this.categoriaProfesional,
    this.tipoContrato,
    this.fechaAlta,
    this.jornadaSemanalHoras,
    this.convenioColectivo,
  });

  factory FichajeDatos.fromJson(Map<String, dynamic> json) => FichajeDatos(
        nombreCompleto: json['nombre_completo'] as String?,
        dniNie: json['dni_nie'] as String?,
        numeroAfiliacionSs: json['numero_afiliacion_ss'] as String?,
        categoriaProfesional: json['categoria_profesional'] as String?,
        tipoContrato: json['tipo_contrato'] as String?,
        fechaAlta: json['fecha_alta'] as String?,
        jornadaSemanalHoras: (json['jornada_semanal_horas'] as num?)?.toDouble(),
        convenioColectivo: json['convenio_colectivo'] as String?,
      );
}

/// Un evento de fichaje (entrada/pausa_inicio/pausa_fin/salida).
class FichajeEvento {
  final int id;
  final String tipo;
  final String marcaTiempo;
  final String origen;
  final String? nota;

  FichajeEvento({
    required this.id,
    required this.tipo,
    required this.marcaTiempo,
    required this.origen,
    this.nota,
  });

  factory FichajeEvento.fromJson(Map<String, dynamic> json) => FichajeEvento(
        id: json['id'] as int,
        tipo: json['tipo'] as String,
        marcaTiempo: json['marca_tiempo'] as String,
        origen: json['origen'] as String,
        nota: json['nota'] as String?,
      );
}

Map<String, String> etiquetasFichaje(AppLocalizations t) => {
      'entrada': t.fichajeTipoEntrada,
      'pausa_inicio': t.fichajeTipoPausaInicio,
      'pausa_fin': t.fichajeTipoPausaFin,
      'salida': t.fichajeTipoSalida,
    };

// --- Asistente IA (Fase 2 de paridad app/web, ver app/ia_asistente.py) -----

/// Una fila de app/db.py:ia_mensajes (rol user/assistant/tool). Refleja
/// exactamente lo que devuelven GET /ia/mensajes y los "mensajes_nuevos" de
/// POST /ia/mensaje y /ia/confirmar.
class IaMensaje {
  final int id;
  final String rol; // 'user' | 'assistant' | 'tool'
  final String? contenido;
  /// Solo relleno en filas "assistant" que pidieron herramientas -- JSON en
  /// crudo (lista de tool_calls) tal cual lo guardó ia_asistente.py. Se usa
  /// para reconstruir si hay una confirmación pendiente al reabrir el chat
  /// (ver _pendienteDesdeHistorial en ia_chat_screen.dart).
  final String? toolCallsJson;
  final String? toolCallId;
  final String? nombreHerramienta;
  final String creadoEn;

  IaMensaje({
    required this.id,
    required this.rol,
    this.contenido,
    this.toolCallsJson,
    this.toolCallId,
    this.nombreHerramienta,
    required this.creadoEn,
  });

  factory IaMensaje.fromJson(Map<String, dynamic> json) => IaMensaje(
        id: json['id'] as int,
        rol: json['rol'] as String,
        contenido: json['contenido'] as String?,
        toolCallsJson: json['tool_calls_json'] as String?,
        toolCallId: json['tool_call_id'] as String?,
        nombreHerramienta: json['nombre_herramienta'] as String?,
        creadoEn: json['creado_en'] as String,
      );
}

/// Una acción esperando confirmación explícita (ver
/// ia_asistente._pendiente_dict) antes de que el asistente pueda seguir.
class IaPendiente {
  final String toolCallId;
  final String herramienta;
  final Map<String, dynamic> argumentos;

  IaPendiente({required this.toolCallId, required this.herramienta, required this.argumentos});

  factory IaPendiente.fromJson(Map<String, dynamic> json) => IaPendiente(
        toolCallId: json['tool_call_id'] as String,
        herramienta: json['herramienta'] as String,
        argumentos: (json['argumentos'] as Map?)?.cast<String, dynamic>() ?? {},
      );
}

/// Resultado de un turno (POST /ia/mensaje o /ia/confirmar): los mensajes
/// nuevos generados en ese turno, y si hay algo esperando confirmación.
class IaTurnoResultado {
  final List<IaMensaje> mensajesNuevos;
  final IaPendiente? pendiente;

  IaTurnoResultado({required this.mensajesNuevos, this.pendiente});

  factory IaTurnoResultado.fromJson(Map<String, dynamic> json) => IaTurnoResultado(
        mensajesNuevos: (json['mensajes_nuevos'] as List? ?? [])
            .map((m) => IaMensaje.fromJson(m as Map<String, dynamic>))
            .toList(),
        pendiente: json['pendiente'] != null
            ? IaPendiente.fromJson(json['pendiente'] as Map<String, dynamic>)
            : null,
      );
}

/// Preferencias del asistente (modelo + modo autónomo, tabla
/// ia_preferencias) más si hay clave de OpenRouter configurada. La clave en
/// sí NUNCA viaja aquí -- solo se puede gestionar desde la web (ver
/// ia_ajustes_screen.dart).
class IaAjustes {
  final String modelo;
  final bool modoAutonomo;
  final bool apiKeyConfigurada;

  IaAjustes({required this.modelo, required this.modoAutonomo, required this.apiKeyConfigurada});

  factory IaAjustes.fromJson(Map<String, dynamic> json) => IaAjustes(
        modelo: json['modelo'] as String? ?? '',
        modoAutonomo: (json['modo_autonomo'] is bool)
            ? json['modo_autonomo'] as bool
            : (json['modo_autonomo'] as int? ?? 0) != 0,
        apiKeyConfigurada: json['api_key_configurada'] as bool? ?? false,
      );
}

/// Un modelo gratuito de OpenRouter (ver ia_asistente.listar_modelos_gratuitos).
class IaModelo {
  final String id;
  final String nombre;

  IaModelo({required this.id, required this.nombre});

  factory IaModelo.fromJson(Map<String, dynamic> json) =>
      IaModelo(id: json['id'] as String, nombre: json['nombre'] as String);
}

/// Un evento de /ia/mensaje/stream o /ia/confirmar/stream (Fase V del plan
/// "eventual-herding-kitten", asistente de voz) -- mismo formato SSE que ya
/// consume ia_asistente.js en la web, ver ia_asistente.procesar_turno_stream
/// en el backend para los 5 tipos posibles. OJO: para tipo="error" el campo
/// crudo del backend se llama igual que para tipo="mensaje" ("mensaje"),
/// pero con un string en vez de un dict -- por eso fromJson mira `tipo`
/// ANTES de decidir cómo interpretar ese campo, no puede ir por presencia.
class IaEventoStream {
  final String tipo; // 'delta' | 'mensaje' | 'pendiente' | 'error' | 'fin'
  final String? texto;
  final IaMensaje? mensaje;
  final IaPendiente? pendiente;
  final String? error;

  IaEventoStream({required this.tipo, this.texto, this.mensaje, this.pendiente, this.error});

  factory IaEventoStream.fromJson(Map<String, dynamic> json) {
    final tipo = json['tipo'] as String;
    return IaEventoStream(
      tipo: tipo,
      texto: tipo == 'delta' ? json['texto'] as String? : null,
      mensaje: tipo == 'mensaje' && json['mensaje'] != null
          ? IaMensaje.fromJson(json['mensaje'] as Map<String, dynamic>)
          : null,
      pendiente: tipo == 'pendiente' && json['pendiente'] != null
          ? IaPendiente.fromJson(json['pendiente'] as Map<String, dynamic>)
          : null,
      error: tipo == 'error' ? json['mensaje'] as String? : null,
    );
  }
}
