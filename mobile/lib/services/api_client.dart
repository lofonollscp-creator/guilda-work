import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';

import '../models/models.dart';
import 'session_service.dart';

/// Error legible para mostrar en la UI cuando falla una llamada a la API.
class ApiException implements Exception {
  final String mensaje;
  ApiException(this.mensaje);

  @override
  String toString() => mensaje;
}

class Usuario {
  final int id;
  final String email;
  Usuario({required this.id, required this.email});

  factory Usuario.fromJson(Map<String, dynamic> json) =>
      Usuario(id: json['id'] as int, email: json['email'] as String);
}

/// Cliente HTTP para app/rutas_api.py (Fase 2). Todas las respuestas de la
/// API usan el mismo sobre `{"ok": true, "data": ...}` / `{"ok": false,
/// "error": "..."}` — este cliente lo desempaqueta una sola vez aquí, para
/// que el resto de la app solo trate con los datos o con ApiException.
class ApiClient {
  final SessionService sesion;
  late final Dio _dio;

  ApiClient(this.sesion) {
    _dio = Dio();
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          final baseUrl = await sesion.obtenerServidor();
          options.baseUrl = '$baseUrl/api/v1';
          final token = await sesion.obtenerToken();
          if (token != null) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          handler.next(options);
        },
      ),
    );
  }

  /// Convierte cualquier fallo (red, timeout, o `{"ok": false, "error": ...}`
  /// devuelto por la API) en un ApiException con un mensaje legible.
  Object _errorLegible(DioException e) {
    final datos = e.response?.data;
    if (datos is Map && datos['error'] != null) {
      return ApiException(datos['error'].toString());
    }
    if (e.type == DioExceptionType.connectionTimeout ||
        e.type == DioExceptionType.connectionError) {
      return ApiException(
        'No se ha podido conectar con el servidor. Comprueba la URL en Ajustes.',
      );
    }
    return ApiException('Error de red: ${e.message}');
  }

  Future<(String token, Usuario usuario)> login(
    String email,
    String contrasena,
  ) async {
    try {
      final resp = await _dio.post(
        '/auth/login',
        data: {'email': email, 'contrasena': contrasena},
      );
      final datos = resp.data['data'] as Map<String, dynamic>;
      return (
        datos['token'] as String,
        Usuario.fromJson(datos['usuario'] as Map<String, dynamic>),
      );
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<(String token, Usuario usuario)> registrar(
    String email,
    String contrasena,
  ) async {
    try {
      final resp = await _dio.post(
        '/auth/registro',
        data: {'email': email, 'contrasena': contrasena},
      );
      final datos = resp.data['data'] as Map<String, dynamic>;
      return (
        datos['token'] as String,
        Usuario.fromJson(datos['usuario'] as Map<String, dynamic>),
      );
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  /// Recupera quién es el usuario a partir del token ya guardado — hace
  /// falta al reabrir la app con una sesión persistida, donde no tenemos
  /// cacheado el email en ningún sitio.
  Future<Usuario> quienSoy() async {
    try {
      final resp = await _dio.get('/auth/me');
      return Usuario.fromJson(resp.data['data'] as Map<String, dynamic>);
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<void> logout() async {
    try {
      await _dio.post('/auth/logout');
    } on DioException {
      // Si el servidor no responde, no bloquea el cierre de sesión local.
    }
  }

  // --- Dashboard / menús / notas / tareas con duración (Fase 4c) -----------

  Future<Map<String, dynamic>> dashboard() async {
    try {
      final resp = await _dio.get('/dashboard');
      return resp.data['data'] as Map<String, dynamic>;
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<List<Categoria>> listarCategorias() async {
    try {
      final resp = await _dio.get('/categorias');
      return (resp.data['data'] as List)
          .map((c) => Categoria.fromJson(c as Map<String, dynamic>))
          .toList();
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<Categoria> crearCategoria(String nombre, {String? color}) async {
    try {
      final resp = await _dio.post(
        '/categorias',
        data: {'nombre': nombre, 'color': ?color},
      );
      return Categoria.fromJson(resp.data['data'] as Map<String, dynamic>);
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<void> eliminarCategoria(int id) async {
    try {
      await _dio.delete('/categorias/$id');
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<void> crearNota(String texto, {int? categoriaId}) async {
    try {
      await _dio.post(
        '/notas',
        data: {'texto': texto, 'categoria_id': ?categoriaId},
      );
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<void> crearTarea(String nombre, int categoriaId, String tipo) async {
    try {
      await _dio.post(
        '/tareas',
        data: {'nombre': nombre, 'categoria_id': categoriaId, 'tipo': tipo},
      );
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<void> pausarTarea(int id) => _accionTarea(id, 'pausar');
  Future<void> reanudarTarea(int id) => _accionTarea(id, 'reanudar');
  Future<void> finalizarTarea(int id) => _accionTarea(id, 'finalizar');

  Future<void> _accionTarea(int id, String accion) async {
    try {
      await _dio.post('/tareas/$id/$accion');
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<List<EntradaHistorial>> historial({int? categoriaId, String? q}) async {
    final qEfectivo = (q != null && q.isNotEmpty) ? q : null;
    try {
      final resp = await _dio.get(
        '/historial',
        queryParameters: {
          'categoria_id': ?categoriaId,
          'q': ?qEfectivo,
        },
      );
      return (resp.data['data'] as List)
          .map((f) => EntradaHistorial.fromJson(f as Map<String, dynamic>))
          .toList();
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  // --- Tareas Outlook (Fase 4d) ----------------------------------------------

  Future<List<TareaOutlook>> listarTareasOutlook({
    String? estado,
    String? prioridad,
    String? categoria,
    String? q,
  }) async {
    try {
      final resp = await _dio.get(
        '/tareas-outlook',
        queryParameters: {
          'estado': ?estado,
          'prioridad': ?prioridad,
          'categoria': ?categoria,
          'q': ?q,
        },
      );
      return (resp.data['data'] as List)
          .map((t) => TareaOutlook.fromJson(t as Map<String, dynamic>))
          .toList();
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<TareaOutlook> crearTareaOutlook({
    required String asunto,
    String? prioridad,
    String? fechaVencimiento,
    String? categoriaOutlook,
  }) async {
    try {
      final resp = await _dio.post(
        '/tareas-outlook',
        data: {
          'asunto': asunto,
          'prioridad': ?prioridad,
          'fecha_vencimiento': ?fechaVencimiento,
          'categoria_outlook': ?categoriaOutlook,
        },
      );
      return TareaOutlook.fromJson(resp.data['data'] as Map<String, dynamic>);
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<TareaOutlook> editarTareaOutlook(int id, Map<String, dynamic> campos) async {
    try {
      final resp = await _dio.put('/tareas-outlook/$id', data: campos);
      return TareaOutlook.fromJson(resp.data['data'] as Map<String, dynamic>);
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<void> eliminarTareaOutlook(int id) async {
    try {
      await _dio.delete('/tareas-outlook/$id');
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<TareaOutlook> completarTareaOutlook(int id) async {
    try {
      final resp = await _dio.post('/tareas-outlook/$id/completar');
      return TareaOutlook.fromJson(resp.data['data'] as Map<String, dynamic>);
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  // --- Correo (Fase 4e) -------------------------------------------------

  Future<List<CuentaCorreo>> listarCuentasCorreo() async {
    try {
      final resp = await _dio.get('/correo/cuentas');
      return (resp.data['data'] as List)
          .map((c) => CuentaCorreo.fromJson(c as Map<String, dynamic>))
          .toList();
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<List<Carpeta>> listarCarpetas(int cuentaId) async {
    try {
      final resp = await _dio.get(
        '/correo/carpetas',
        queryParameters: {'cuenta_id': cuentaId},
      );
      return (resp.data['data'] as List)
          .map((c) => Carpeta.fromJson(c as Map<String, dynamic>))
          .toList();
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<List<Mensaje>> listarMensajes({
    required int cuentaId,
    String carpeta = 'INBOX',
    bool? noLeidos,
    String? q,
  }) async {
    final qEfectivo = (q != null && q.isNotEmpty) ? q : null;
    try {
      final resp = await _dio.get(
        '/correo/mensajes',
        queryParameters: {
          'cuenta_id': cuentaId,
          'carpeta': carpeta,
          'no_leidos': ?(noLeidos == true ? 1 : null),
          'q': ?qEfectivo,
        },
      );
      return (resp.data['data'] as List)
          .map((m) => Mensaje.fromJson(m as Map<String, dynamic>))
          .toList();
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<Mensaje> obtenerMensaje(int id) async {
    try {
      final resp = await _dio.get('/correo/mensajes/$id');
      return Mensaje.fromJson(resp.data['data'] as Map<String, dynamic>);
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<void> eliminarMensaje(int id) async {
    try {
      await _dio.delete('/correo/mensajes/$id');
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<void> marcarLeido(int id, bool leido) async {
    try {
      await _dio.post('/correo/mensajes/$id/leido', data: {'leido': leido});
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<void> destacarMensaje(int id, bool destacado) async {
    try {
      await _dio.post(
        '/correo/mensajes/$id/destacar',
        data: {'destacado': destacado},
      );
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<void> asignarCategoria(int id, int? categoriaId) async {
    try {
      await _dio.post(
        '/correo/mensajes/$id/categoria',
        data: {'categoria_id': categoriaId},
      );
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<void> moverMensaje(int id, String carpetaDestino) async {
    try {
      await _dio.post(
        '/correo/mensajes/$id/mover',
        data: {'carpeta_destino': carpetaDestino},
      );
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<List<CategoriaCorreo>> listarCategoriasCorreo() async {
    try {
      final resp = await _dio.get('/correo/categorias');
      return (resp.data['data'] as List)
          .map((c) => CategoriaCorreo.fromJson(c as Map<String, dynamic>))
          .toList();
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<void> enviarCorreo({
    required int cuentaId,
    required String destinatarios,
    String? cc,
    String? bcc,
    required String asunto,
    required String cuerpoHtml,
    String? enRespuestaA,
    List<ArchivoAdjuntoNuevo> adjuntos = const [],
  }) async {
    try {
      await _dio.post(
        '/correo/enviar',
        data: {
          'cuenta_id': cuentaId,
          'destinatarios': destinatarios,
          'cc': ?cc,
          'bcc': ?bcc,
          'asunto': asunto,
          'cuerpo_html': cuerpoHtml,
          'en_respuesta_a': ?enRespuestaA,
          if (adjuntos.isNotEmpty)
            'adjuntos': adjuntos
                .map((a) => {
                      'nombre': a.nombre,
                      'tipo': a.tipo,
                      'contenido_base64': base64Encode(a.bytes),
                    })
                .toList(),
        },
      );
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<Uint8List> descargarAdjunto(int mensajeId, int adjuntoId) async {
    try {
      final resp = await _dio.get(
        '/correo/mensajes/$mensajeId/adjuntos/$adjuntoId',
        options: Options(responseType: ResponseType.bytes),
      );
      return Uint8List.fromList(resp.data as List<int>);
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  // --- Remitentes de confianza (Fase 5) ----------------------------------

  Future<List<RemitenteConfiable>> listarRemitentesConfiables() async {
    try {
      final resp = await _dio.get('/correo/remitentes-confiables');
      return (resp.data['data'] as List)
          .map((r) => RemitenteConfiable.fromJson(r as Map<String, dynamic>))
          .toList();
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<void> confiarEnRemitente(String direccion) async {
    try {
      await _dio.post('/correo/remitentes-confiables', data: {'direccion': direccion});
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<void> eliminarRemitenteConfiable(int id) async {
    try {
      await _dio.delete('/correo/remitentes-confiables/$id');
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  // --- Reglas de categorización automática (Fase 5) ----------------------

  Future<List<ReglaCategoria>> listarReglasCategoria() async {
    try {
      final resp = await _dio.get('/correo/reglas-categoria');
      return (resp.data['data'] as List)
          .map((r) => ReglaCategoria.fromJson(r as Map<String, dynamic>))
          .toList();
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<void> crearReglaCategoria(String remitentePatron, int categoriaId) async {
    try {
      await _dio.post(
        '/correo/reglas-categoria',
        data: {'remitente_patron': remitentePatron, 'categoria_id': categoriaId},
      );
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  Future<void> eliminarReglaCategoria(int id) async {
    try {
      await _dio.delete('/correo/reglas-categoria/$id');
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }

  // --- Destinatarios recientes (Fase 5) -----------------------------------

  Future<List<DestinatarioReciente>> buscarDestinatariosRecientes(String q) async {
    try {
      final resp = await _dio.get('/correo/destinatarios-recientes', queryParameters: {'q': q});
      return (resp.data['data'] as List)
          .map((d) => DestinatarioReciente.fromJson(d as Map<String, dynamic>))
          .toList();
    } on DioException catch (e) {
      throw _errorLegible(e);
    }
  }
}
