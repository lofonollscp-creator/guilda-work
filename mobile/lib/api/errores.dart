/// Familia del fallo: lo que decide qué hace la pantalla (reintentar, pedir
/// login, avisar de conflicto...) sin mirar números de estado sueltos.
enum CategoriaError {
  /// No se llega al servidor (sin red, tiempo agotado).
  red,

  /// 401: falta sesión o ha caducado.
  autenticacion,

  /// 403: la persona no puede hacer esto (rol, módulo, alcance).
  prohibido,

  /// 404: ya no existe o el módulo no está activo en el despacho.
  noEncontrado,

  /// 423: el despacho tiene cifrado y falta desbloquearlo.
  bloqueado,

  /// 409/412: alguien cambió el recurso (versión obsoleta) o regla de negocio.
  conflicto,

  /// 400/422: datos no válidos; [ApiException.campo] dice cuál si se sabe.
  validacion,

  /// 429: demasiadas peticiones; [ApiException.retryAfter] dice cuándo.
  limite,

  /// 426: esta versión de la app ya no se admite.
  actualizar,

  /// 5xx.
  servidor,

  /// Cualquier otra cosa.
  desconocido,
}

/// Error legible para mostrar en la UI cuando falla una llamada a la API.
///
/// Es la misma clase que usaban las pantallas (`mensaje`, `esDeConexion`,
/// `codigo`, `requiere2fa`), ampliada con lo que manda el servidor
/// (`request_id`, `campo`, `version_actual`) y con una [categoria] tipada.
class ApiException implements Exception {
  final String mensaje;

  /// true si el fallo es "no hay red/no se llega al servidor" -- lo usan
  /// fichaje_screen.dart y dashboard_screen.dart para decidir si encolar la
  /// acción offline en vez de mostrar el error tal cual (un error de
  /// negocio, ej. secuencia de fichaje inválida, sigue mostrándose normal).
  final bool esDeConexion;

  /// Clave estable que manda la API en `codigo` (p. ej. `requiere_2fa`): es lo
  /// que debe leer el programa; `mensaje` es solo para mostrar a la persona.
  final String? codigo;

  /// Estado HTTP, o null si no hubo respuesta.
  final int? status;

  /// Identificador de la petición en el servidor, para soporte y diagnóstico.
  final String? requestId;

  /// Campo del formulario al que se refiere el error, si el servidor lo dice.
  final String? campo;

  /// Cuánto esperar antes de reintentar (`Retry-After` en un 429/503).
  final Duration? retryAfter;

  /// Versión actual del recurso en un conflicto (`version_actual`), para
  /// ofrecer "ver cambios / sobrescribir" sin otra petición.
  final int? versionActual;

  /// Enlace de la tienda que manda el servidor en un 426 (`url_tienda`).
  final String? urlTienda;

  ApiException(
    this.mensaje, {
    this.esDeConexion = false,
    this.codigo,
    this.status,
    this.requestId,
    this.campo,
    this.retryAfter,
    this.versionActual,
    this.urlTienda,
  });

  /// La cuenta tiene verificación en dos pasos y falta el código.
  bool get requiere2fa => codigo == 'requiere_2fa';

  /// Se decide por el estado, salvo los `codigo` que el servidor usa para
  /// conflictos con otro número (tareas 409, fiscal 412: mismo concepto).
  CategoriaError get categoria {
    if (esDeConexion) return CategoriaError.red;
    if (codigo == 'version_obsoleta' || codigo == 'despacho_bloqueado') {
      return codigo == 'despacho_bloqueado' ? CategoriaError.bloqueado : CategoriaError.conflicto;
    }
    final s = status;
    if (s == null) return CategoriaError.desconocido;
    if (s == 401) return CategoriaError.autenticacion;
    if (s == 403) return CategoriaError.prohibido;
    if (s == 404) return CategoriaError.noEncontrado;
    if (s == 409 || s == 412) return CategoriaError.conflicto;
    if (s == 423) return CategoriaError.bloqueado;
    if (s == 426) return CategoriaError.actualizar;
    if (s == 429) return CategoriaError.limite;
    if (s == 400 || s == 422) return CategoriaError.validacion;
    if (s >= 500) return CategoriaError.servidor;
    return CategoriaError.desconocido;
  }

  /// Tiene sentido volver a intentarlo tal cual (red, límite, caída del servidor).
  bool get reintentable {
    final c = categoria;
    return c == CategoriaError.red || c == CategoriaError.limite || c == CategoriaError.servidor;
  }

  @override
  String toString() => mensaje;
}
