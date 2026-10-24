import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:dio/dio.dart';
import 'package:uuid/uuid.dart';

import 'errores.dart';
import 'generado/operaciones.g.dart' show Transporte;

/// Lo que el cliente necesita saber de la sesión y de la app en cada petición.
/// Lo implementa el núcleo de la app (sesión, despacho activo, idioma); así el
/// cliente no depende de `SessionService` y se puede probar sin almacén seguro.
abstract class ContextoApi {
  /// URL base del servidor, sin barra final ni `/api/v1`.
  Future<String> servidor();
  Future<String?> token();

  /// Despacho activo (`X-Despacho`); null si la persona tiene uno solo o aún no se sabe.
  String? get despacho;

  /// Código de idioma de la app (`es`, `ca`, `en`, `fr`) para `Accept-Language`.
  String get idioma;
  String get versionApp;

  /// `android` / `ios`.
  String get plataforma;

  /// Una petición con token volvió con 401: la sesión ya no vale.
  Future<void> alSesionExpirada();

  /// El servidor contestó 426: esta versión de la app ya no se admite.
  Future<void> alRequerirActualizacion({String? urlTienda}) async {}
}

class _Cacheado {
  final String etag;
  final dynamic datos;
  _Cacheado(this.etag, this.datos);
}

/// Cliente HTTP v2 de la API (`/api/v1`): implementa el [Transporte] del SDK
/// generado. Se ocupa de lo transversal para que las pantallas no lo repitan:
///
///  - sobre `{ok, data}` / `{ok: false, error, codigo, request_id}` → datos o [ApiException];
///  - cabeceras `Authorization`, `X-Despacho`, `Accept-Language`, `X-App-Version`, `X-App-Platform`;
///  - `Idempotency-Key` en cada escritura, **la misma en los reintentos**;
///  - reintentos con espera exponencial ante red, `429` (respeta `Retry-After`) y 502/503/504;
///  - `ETag` / `If-None-Match` en lecturas (memoria, ligada al despacho);
///  - 401 con token → [ContextoApi.alSesionExpirada].
class ClienteApi implements Transporte {
  final ContextoApi contexto;
  final int maxIntentos;

  /// `Retry-After` mayor que esto no se espera: se devuelve el error con [ApiException.retryAfter].
  final Duration esperaMaxima;
  final Future<void> Function(Duration) _espera;
  final Dio _dio;
  final Uuid _uuid = const Uuid();
  final Random _azar = Random();
  final Map<String, _Cacheado> _cache = {};
  static const _maxCache = 200;
  CancelToken _cancelar = CancelToken();

  /// Peticiones hechas (incluidos reintentos), para vigilar el límite de 600/min.
  int peticiones = 0;

  ClienteApi(
    this.contexto, {
    Dio? dio,
    this.maxIntentos = 3,
    this.esperaMaxima = const Duration(seconds: 30),
    Future<void> Function(Duration)? espera,
  })  : _dio = dio ?? Dio(),
        _espera = espera ?? Future<void>.delayed {
    _dio.options
      ..connectTimeout = const Duration(seconds: 15)
      ..receiveTimeout = const Duration(seconds: 60)
      ..sendTimeout = const Duration(seconds: 60)
      ..validateStatus = (_) => true; // el estado lo interpretamos nosotros
  }

  /// Rutas sin token: un 401 ahí es «credenciales incorrectas», no sesión caducada.
  static const _sinSesion = ['/auth/login', '/auth/registro'];

  /// Un transporte que manda siempre esa `Idempotency-Key`: para una acción que, si falla por falta de red, se guarda en la
  /// cola sin conexión con la **misma** clave (así, si la primera petición sí llegó al servidor, el reenvío no duplica nada).
  Transporte conClave(String clave) => _ConClave(this, clave);

  /// Olvida lo cacheado (cerrar sesión, cambiar de despacho).
  void vaciarCache() => _cache.clear();

  /// Cancela las peticiones en vuelo (cambio de despacho).
  void cancelarPendientes() {
    _cancelar.cancel('cancelada');
    _cancelar = CancelToken();
  }

  @override
  Future<dynamic> enviar(String metodo, String ruta,
          {Map<String, dynamic>? consulta, Object? cuerpo, bool multipart = false, bool binario = false}) =>
      enviarConClave(metodo, ruta, consulta: consulta, cuerpo: cuerpo, multipart: multipart, binario: binario);

  /// Igual que [enviar] pero con una clave de idempotencia dada: la cola sin
  /// conexión guarda la suya para que el reenvío tras horas no duplique nada.
  Future<dynamic> enviarConClave(String metodo, String ruta,
      {Map<String, dynamic>? consulta,
      Object? cuerpo,
      bool multipart = false,
      bool binario = false,
      String? claveIdempotencia}) async {
    metodo = metodo.toUpperCase();
    final lectura = metodo == 'GET';
    final clave = lectura ? null : (claveIdempotencia ?? _uuid.v4());
    final url = '${await contexto.servidor()}/api/v1$ruta';
    final token = await contexto.token();
    final despacho = contexto.despacho;
    final claveCache = lectura && !binario ? _claveCache(despacho, url, consulta) : null;

    ApiException? ultimo;
    for (var intento = 1; intento <= maxIntentos; intento++) {
      final cacheado = claveCache == null ? null : _cache[claveCache];
      final cabeceras = <String, dynamic>{
        'Accept': binario ? '*/*' : 'application/json',
        'Accept-Language': contexto.idioma,
        'X-App-Version': contexto.versionApp,
        'X-App-Platform': contexto.plataforma,
        if (token != null) 'Authorization': 'Bearer $token',
        'X-Despacho': ?despacho,
        'Idempotency-Key': ?clave,
        if (cacheado != null) 'If-None-Match': cacheado.etag,
      };
      peticiones++;
      Response<dynamic> r;
      try {
        r = await _dio.request<dynamic>(
          url,
          data: multipart && cuerpo is Map<String, dynamic> ? FormData.fromMap(cuerpo) : cuerpo,
          queryParameters: consulta,
          cancelToken: _cancelar,
          options: Options(
            method: metodo,
            headers: cabeceras,
            responseType: binario ? ResponseType.bytes : ResponseType.json,
          ),
        );
      } on DioException catch (e) {
        ultimo = _deRed(e);
        if (e.type == DioExceptionType.cancel || intento == maxIntentos) throw ultimo;
        await _espera(_pausa(intento));
        continue;
      }

      final s = r.statusCode ?? 0;
      if (s == 304 && cacheado != null) return cacheado.datos;
      if (s >= 200 && s < 300) {
        final datos = binario ? r.data : _desempaquetar(r.data, s);
        final etag = r.headers.value('etag');
        if (claveCache != null && etag != null) _guardar(claveCache, _Cacheado(etag, datos));
        return datos;
      }

      final e = _deRespuesta(r, s);
      if (s == 401 && token != null && !_sinSesion.contains(ruta)) await contexto.alSesionExpirada();
      if (s == 426) await contexto.alRequerirActualizacion(urlTienda: e.urlTienda);
      final espera = e.retryAfter;
      final reintento = intento < maxIntentos &&
          (s == 429 || s == 502 || s == 503 || s == 504) &&
          (espera == null || espera <= esperaMaxima);
      if (!reintento) throw e;
      ultimo = e;
      await _espera(espera ?? _pausa(intento));
    }
    throw ultimo ?? ApiException('Error desconocido');
  }

  // --- internos ---

  Duration _pausa(int intento) =>
      Duration(milliseconds: 500 * (1 << (intento - 1)) + _azar.nextInt(250));

  String _claveCache(String? despacho, String url, Map<String, dynamic>? consulta) {
    final q = (consulta?.entries.toList() ?? [])..sort((a, b) => a.key.compareTo(b.key));
    return '${despacho ?? ''}|$url?${q.map((e) => '${e.key}=${e.value}').join('&')}';
  }

  void _guardar(String clave, _Cacheado c) {
    _cache.remove(clave);
    _cache[clave] = c;
    if (_cache.length > _maxCache) _cache.remove(_cache.keys.first);
  }

  dynamic _desempaquetar(dynamic cuerpo, int status) {
    if (cuerpo is Map && cuerpo['ok'] == true) return cuerpo['data'];
    if (cuerpo is Map && cuerpo['ok'] == false) throw _deCuerpo(cuerpo, status, null);
    if (cuerpo == null || cuerpo == '') return null; // 204
    throw ApiException('Respuesta inesperada del servidor.', status: status);
  }

  ApiException _deRespuesta(Response<dynamic> r, int status) {
    dynamic cuerpo = r.data;
    if (cuerpo is List<int>) {
      try {
        cuerpo = jsonDecode(utf8.decode(cuerpo));
      } catch (_) {
        cuerpo = null;
      }
    }
    final ra = int.tryParse(r.headers.value('retry-after') ?? '');
    return _deCuerpo(cuerpo is Map ? cuerpo : const {}, status, ra == null ? null : Duration(seconds: ra));
  }

  ApiException _deCuerpo(Map cuerpo, int status, Duration? retryAfter) => ApiException(
        cuerpo['error']?.toString() ?? 'Error $status',
        codigo: cuerpo['codigo']?.toString(),
        status: status,
        requestId: cuerpo['request_id']?.toString(),
        campo: cuerpo['campo']?.toString(),
        versionActual: (cuerpo['version_actual'] as num?)?.toInt(),
        urlTienda: cuerpo['url_tienda']?.toString(),
        retryAfter: retryAfter,
      );

  ApiException _deRed(DioException e) {
    if (e.type == DioExceptionType.cancel) return ApiException('Petición cancelada.', codigo: 'cancelada');
    if (e.type == DioExceptionType.connectionTimeout || e.type == DioExceptionType.connectionError) {
      return ApiException('No se ha podido conectar con el servidor. Comprueba la URL en Ajustes.', esDeConexion: true);
    }
    return ApiException('Error de red: ${e.message}', esDeConexion: true);
  }
}

class _ConClave implements Transporte {
  final ClienteApi _c;
  final String _clave;
  _ConClave(this._c, this._clave);

  @override
  Future<dynamic> enviar(String metodo, String ruta, {Map<String, dynamic>? consulta, Object? cuerpo, bool multipart = false, bool binario = false}) =>
      _c.enviarConClave(metodo, ruta, consulta: consulta, cuerpo: cuerpo, multipart: multipart, binario: binario, claveIdempotencia: _clave);
}
