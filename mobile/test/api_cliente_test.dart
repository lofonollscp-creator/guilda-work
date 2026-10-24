import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/api/cliente.dart';
import 'package:guilda_work_mobile/api/errores.dart';
import 'package:guilda_work_mobile/api/fechas.dart';

class _Contexto implements ContextoApi {
  String? tokenActual = 'tok';
  @override
  String? despacho = '3';
  int caducadas = 0;
  int actualizaciones = 0;
  String? ultimaUrl;
  @override
  Future<String> servidor() async => 'https://s.test';
  @override
  Future<String?> token() async => tokenActual;
  @override
  String get idioma => 'ca';
  @override
  String get versionApp => '1.2.3';
  @override
  String get plataforma => 'android';
  @override
  Future<void> alSesionExpirada() async => caducadas++;
  @override
  Future<void> alRequerirActualizacion({String? urlTienda}) async {
    actualizaciones++;
    ultimaUrl = urlTienda;
  }
}

class _Respuesta {
  final int status;
  final Object? cuerpo;
  final Map<String, String> cabeceras;
  final DioExceptionType? fallo;
  _Respuesta(this.status, this.cuerpo, {this.cabeceras = const {}}) : fallo = null;
  _Respuesta.red() : status = 0, cuerpo = null, cabeceras = const {}, fallo = DioExceptionType.connectionError;
}

/// Servidor falso: contesta con la cola de respuestas y guarda lo que recibió.
class _Falso implements HttpClientAdapter {
  final List<_Respuesta> cola;
  final List<RequestOptions> vistas = [];
  _Falso(this.cola);

  @override
  Future<ResponseBody> fetch(RequestOptions o, Stream<Uint8List>? body, Future<void>? cancel) async {
    vistas.add(o);
    final r = cola.length > 1 ? cola.removeAt(0) : cola.first;
    if (r.fallo != null) throw DioException(requestOptions: o, type: r.fallo!);
    final bytes = r.cuerpo is List<int> ? r.cuerpo as List<int> : utf8.encode(r.cuerpo == null ? '' : jsonEncode(r.cuerpo));
    return ResponseBody.fromBytes(bytes, r.status, headers: {
      'content-type': [r.cuerpo is List<int> ? 'application/octet-stream' : 'application/json'],
      ...r.cabeceras.map((k, v) => MapEntry(k, [v])),
    });
  }

  @override
  void close({bool force = false}) {}
}

Map<String, Object?> _ok(Object? datos) => {'ok': true, 'data': datos};
Map<String, Object?> _ko(String error, {String? codigo, Map<String, Object?> extra = const {}}) =>
    {'ok': false, 'error': error, 'codigo': ?codigo, ...extra};

/// El error que lanza la llamada (o null si no falla).
Future<ApiException?> _falla(Future<dynamic> f) async {
  try {
    await f;
    return null;
  } on ApiException catch (e) {
    return e;
  }
}

(ClienteApi, _Falso, _Contexto, List<Duration>) _montar(List<_Respuesta> cola) {
  final falso = _Falso(cola);
  final dio = Dio()..httpClientAdapter = falso;
  final ctx = _Contexto();
  final esperas = <Duration>[];
  final c = ClienteApi(ctx, dio: dio, espera: (d) async => esperas.add(d));
  return (c, falso, ctx, esperas);
}

void main() {
  group('ClienteApi', () {
    test('desempaqueta {ok,data} y manda las cabeceras de contexto', () async {
      final (c, f, _, _) = _montar([_Respuesta(200, _ok({'id': 7}))]);
      final r = await c.enviar('GET', '/tareas-outlook/7', consulta: {'campos': 'id'});
      expect(r, {'id': 7});
      final h = f.vistas.single.headers;
      expect(f.vistas.single.uri.toString(), 'https://s.test/api/v1/tareas-outlook/7?campos=id');
      expect(h['Authorization'], 'Bearer tok');
      expect(h['X-Despacho'], '3');
      expect(h['Accept-Language'], 'ca');
      expect(h['X-App-Version'], '1.2.3');
      expect(h['X-App-Platform'], 'android');
      expect(h.containsKey('Idempotency-Key'), false); // las lecturas no llevan clave
    });

    test('sin token ni despacho no manda esas cabeceras', () async {
      final (c, f, ctx, _) = _montar([_Respuesta(200, _ok(null))]);
      ctx.tokenActual = null;
      ctx.despacho = null;
      await c.enviar('GET', '/health');
      expect(f.vistas.single.headers.containsKey('Authorization'), false);
      expect(f.vistas.single.headers.containsKey('X-Despacho'), false);
    });

    test('toda escritura lleva Idempotency-Key y los reintentos reutilizan la misma', () async {
      final (c, f, _, esperas) = _montar([_Respuesta.red(), _Respuesta(503, _ko('caído')), _Respuesta(200, _ok({'id': 1}))]);
      final r = await c.enviar('POST', '/notas', cuerpo: {'texto': 'hola'});
      expect(r, {'id': 1});
      expect(f.vistas.length, 3);
      final claves = f.vistas.map((o) => o.headers['Idempotency-Key']).toSet();
      expect(claves.length, 1);
      expect(claves.single, isNotNull);
      expect(esperas.length, 2); // espera exponencial entre intentos
      expect(esperas[1] > esperas[0], true);
    });

    test('enviarConClave usa la clave de la cola sin conexión', () async {
      final (c, f, _, _) = _montar([_Respuesta(200, _ok(null))]);
      await c.enviarConClave('POST', '/fichaje', claveIdempotencia: 'abc-123');
      expect(f.vistas.single.headers['Idempotency-Key'], 'abc-123');
    });

    test('429 respeta Retry-After y reintenta', () async {
      final (c, f, _, esperas) = _montar([
        _Respuesta(429, _ko('demasiadas'), cabeceras: {'retry-after': '2'}),
        _Respuesta(200, _ok('ok')),
      ]);
      expect(await c.enviar('GET', '/hoy'), 'ok');
      expect(f.vistas.length, 2);
      expect(esperas.single, const Duration(seconds: 2));
    });

    test('429 con Retry-After muy largo no espera: error con retryAfter', () async {
      final (c, f, _, esperas) = _montar([_Respuesta(429, _ko('demasiadas'), cabeceras: {'retry-after': '120'})]);
      final e = await _falla(c.enviar('GET', '/hoy'));
      expect(e!.categoria, CategoriaError.limite);
      expect(e.retryAfter, const Duration(seconds: 120));
      expect(f.vistas.length, 1);
      expect(esperas, isEmpty);
    });

    test('se rinde tras maxIntentos y devuelve error de conexión', () async {
      final (c, f, _, _) = _montar([_Respuesta.red()]);
      final e = await _falla(c.enviar('GET', '/hoy'));
      expect(f.vistas.length, 3);
      expect(e!.esDeConexion, true);
      expect(e.categoria, CategoriaError.red);
    });

    test('un 4xx de negocio no se reintenta y conserva codigo, request_id y campo', () async {
      final (c, f, _, _) = _montar([
        _Respuesta(400, _ko('NIF no válido', codigo: 'nif_invalido', extra: {'request_id': 'r-9', 'campo': 'nif'})),
      ]);
      final e = await _falla(c.enviar('POST', '/fiscal/clientes', cuerpo: {}));
      expect(f.vistas.length, 1);
      expect(e!.mensaje, 'NIF no válido');
      expect(e.codigo, 'nif_invalido');
      expect(e.requestId, 'r-9');
      expect(e.campo, 'nif');
      expect(e.categoria, CategoriaError.validacion);
    });

    test('409 y 412 son el mismo conflicto y traen version_actual', () async {
      for (final s in [409, 412]) {
        final (c, _, _, _) = _montar([_Respuesta(s, _ko('versión', codigo: 'version_obsoleta', extra: {'version_actual': 5}))]);
        final e = await _falla(c.enviar('POST', '/tareas-outlook/1/transiciones'));
        expect(e!.categoria, CategoriaError.conflicto);
        expect(e.versionActual, 5);
      }
    });

    test('423 despacho_bloqueado, 426 y 5xx se categorizan', () async {
      Future<CategoriaError> cat(int s, [String? codigo]) async {
        final (c, _, _, _) = _montar([_Respuesta(s, _ko('x', codigo: codigo))]);
        final e = await _falla(c.enviar('GET', '/x', consulta: null));
        return e!.categoria;
      }

      expect(await cat(423, 'despacho_bloqueado'), CategoriaError.bloqueado);
      expect(await cat(426), CategoriaError.actualizar);
      expect(await cat(500), CategoriaError.servidor);
      expect(await cat(403), CategoriaError.prohibido);
      expect(await cat(404), CategoriaError.noEncontrado);
    });

    test('401 con token avisa de sesión caducada; en /auth/login no', () async {
      final (c, _, ctx, _) = _montar([_Respuesta(401, _ko('no autorizado'))]);
      await _falla(c.enviar('GET', '/hoy'));
      expect(ctx.caducadas, 1);
      await _falla(c.enviar('POST', '/auth/login', cuerpo: {}));
      expect(ctx.caducadas, 1);
    });

    test('426 avisa de que hay que actualizar la app', () async {
      final (c, _, ctx, _) = _montar([_Respuesta(426, _ko('actualiza', codigo: 'actualiza_app', extra: {'url_tienda': 'https://tienda'}))]);
      final e = await _falla(c.enviar('GET', '/hoy'));
      expect(e!.categoria, CategoriaError.actualizar);
      expect(ctx.actualizaciones, 1);
      expect(ctx.ultimaUrl, 'https://tienda');
    });

    test('ETag: reenvía If-None-Match y sirve la copia en un 304', () async {
      final (c, f, ctx, _) = _montar([
        _Respuesta(200, _ok({'v': 1}), cabeceras: {'etag': '"a1"'}),
        _Respuesta(304, null),
      ]);
      expect(await c.enviar('GET', '/tareas-outlook/1'), {'v': 1});
      expect(f.vistas[0].headers.containsKey('If-None-Match'), false);
      expect(await c.enviar('GET', '/tareas-outlook/1'), {'v': 1});
      expect(f.vistas[1].headers['If-None-Match'], '"a1"');
      // otro despacho: no se reutiliza la caché del anterior
      ctx.despacho = '4';
      await _falla(c.enviar('GET', '/tareas-outlook/1'));
      expect(f.vistas[2].headers.containsKey('If-None-Match'), false);
    });

    test('vaciarCache olvida los ETag', () async {
      final (c, f, _, _) = _montar([_Respuesta(200, _ok(1), cabeceras: {'etag': '"x"'})]);
      await c.enviar('GET', '/a');
      c.vaciarCache();
      await c.enviar('GET', '/a');
      expect(f.vistas[1].headers.containsKey('If-None-Match'), false);
    });

    test('binario devuelve los bytes', () async {
      final (c, _, _, _) = _montar([_Respuesta(200, [1, 2, 3])]);
      expect(await c.enviar('GET', '/doc', binario: true), [1, 2, 3]);
    });

    test('204 sin cuerpo devuelve null', () async {
      final (c, _, _, _) = _montar([_Respuesta(204, null)]);
      expect(await c.enviar('DELETE', '/x/1'), null);
    });
  });

  group('ApiException compatible con el código anterior', () {
    test('constructor, esDeConexion, requiere2fa y toString', () {
      final e = ApiException('hola', codigo: 'requiere_2fa');
      expect(e.requiere2fa, true);
      expect(e.esDeConexion, false);
      expect('$e', 'hola');
    });
  });

  group('Fecha y MomentoLocal', () {
    test('leen lo que emite el servidor sin pasar por zonas', () {
      expect(Fecha.parse('2026-10-25').toJson(), '2026-10-25');
      expect(MomentoLocal.parse('2026-10-25T02:30').toJson(), '2026-10-25T02:30'); // hora repetida del cambio de hora
      expect(MomentoLocal.parse('2026-03-29T02:30:15').toJson(), '2026-03-29T02:30:15'); // hora inexistente: se conserva
      expect(Fecha.intentar('2026-02-30'), null);
      expect(Fecha.intentar('mañana'), null);
      expect(MomentoLocal.intentar('2026-10-25T24:00'), null);
    });

    test('aritmética de días no se altera con el cambio de hora', () {
      expect(const Fecha(2026, 10, 24).diasHasta(const Fecha(2026, 10, 26)), 2);
      expect(const Fecha(2026, 3, 28).diasHasta(const Fecha(2026, 3, 30)), 2);
      expect(const Fecha(2026, 12, 31).masDias(1), const Fecha(2027, 1, 1));
      expect(const Fecha(2026, 10, 24).diaSemana, DateTime.saturday);
    });

    test('orden', () {
      expect(MomentoLocal.parse('2026-10-24T09:00').compareTo(MomentoLocal.parse('2026-10-24T10:00')) < 0, true);
      expect(Fecha.parse('2026-10-24') == Fecha.parse('2026-10-24T08:00'), true);
    });
  });
}
