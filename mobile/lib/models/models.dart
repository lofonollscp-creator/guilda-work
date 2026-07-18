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
  final String url;
  final bool sso;

  Herramienta({
    required this.id,
    required this.nombre,
    required this.descripcion,
    required this.icono,
    required this.url,
    required this.sso,
  });

  factory Herramienta.fromJson(Map<String, dynamic> json) => Herramienta(
        id: json['id'] as String,
        nombre: json['nombre'] as String,
        descripcion: json['descripcion'] as String,
        icono: json['icono'] as String,
        url: json['url'] as String,
        sso: json['sso'] as bool,
      );
}

/// Configuración del chat nativo (Matrix/Synapse), Fase 9.
class ChatConfig {
  final String homeserverUrl;

  ChatConfig({required this.homeserverUrl});

  factory ChatConfig.fromJson(Map<String, dynamic> json) =>
      ChatConfig(homeserverUrl: json['homeserver_url'] as String);
}
