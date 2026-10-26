import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/api/cliente.dart';
import 'package:guilda_work_mobile/api/errores.dart';
import 'package:guilda_work_mobile/datos/local/cache_lectura.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

int _ahora = 1000000;

CacheLectura _cache() => CacheLectura(
      abrir: () => databaseFactoryFfi.openDatabase(inMemoryDatabasePath, options: OpenDatabaseOptions(version: 1, onCreate: CacheLectura.crearEsquema, singleInstance: false)),
      ahoraMs: () => _ahora,
    );

class _Contexto implements ContextoApi {
  @override
  int? usuarioId = 7;
  @override
  String? despacho = '3';
  @override
  Future<String> servidor() async => 'https://s.test';
  @override
  Future<String?> token() async => 'tok';
  @override
  String get idioma => 'es';
  @override
  String get versionApp => '1.0.0';
  @override
  String get plataforma => 'ios';
  @override
  Future<void> alSesionExpirada() async {}
  @override
  Future<void> alRequerirActualizacion({String? urlTienda}) async {}
}

/// Servidor falso: `datos` null = sin red.
class _Servidor implements HttpClientAdapter {
  Object? datos;
  int status = 200;
  _Servidor(this.datos);
  @override
  Future<ResponseBody> fetch(RequestOptions o, Stream<Uint8List>? cuerpo, Future<void>? cancelar) async {
    if (datos == null) throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
    return ResponseBody.fromBytes(utf8.encode(jsonEncode(status == 200 ? {'ok': true, 'data': datos} : {'ok': false, 'error': 'no'})), status, headers: {
      'content-type': ['application/json'],
    });
  }

  @override
  void close({bool force = false}) {}
}

(ClienteApi, _Servidor, _Contexto, CacheLectura, List<(String, DateTime?)>) _montar(Object? datos) {
  final s = _Servidor(datos);
  final ctx = _Contexto();
  final cache = _cache();
  final avisos = <(String, DateTime?)>[];
  final c = ClienteApi(ctx, dio: Dio()..httpClientAdapter = s, maxIntentos: 1, almacen: cache, alLeer: (r, d) => avisos.add((r, d)));
  return (c, s, ctx, cache, avisos);
}

void main() {
  sqfliteFfiInit();

  group('CacheLectura', () {
    setUp(() => _ahora = 1000000);

    test('guarda y devuelve lo último, ligado a la persona', () async {
      final c = _cache();
      await c.guardar(clave: 'a', usuarioId: 1, despachoId: '3', datos: {'x': 1});
      await c.guardar(clave: 'a', usuarioId: 1, despachoId: '3', datos: {'x': 2});
      expect((await c.leer('a', 1))!.datos, {'x': 2});
      expect(await c.leer('a', 2), isNull, reason: 'otra persona no ve lo guardado');
      expect(await c.contar(), 1);
    });

    test('caduca a los 30 días y vaciar lo borra todo', () async {
      final c = _cache();
      await c.guardar(clave: 'a', usuarioId: 1, despachoId: '3', datos: [1]);
      _ahora += CacheLectura.caducidad.inMilliseconds + 1;
      expect(await c.leer('a', 1), isNull);
      _ahora = 1000000;
      await c.guardar(clave: 'b', usuarioId: 1, despachoId: '3', datos: [2]);
      await c.vaciar();
      expect(await c.contar(), 0);
    });

    test('solo conserva las más recientes', () async {
      final c = _cache();
      for (var i = 0; i < CacheLectura.maximo + 5; i++) {
        _ahora += 1;
        await c.guardar(clave: 'k$i', usuarioId: 1, despachoId: '3', datos: i);
      }
      expect(await c.contar(), CacheLectura.maximo);
      expect(await c.leer('k0', 1), isNull);
      expect((await c.leer('k${CacheLectura.maximo + 4}', 1))!.datos, CacheLectura.maximo + 4);
    });
  });

  group('ClienteApi con caché de lectura', () {
    test('sin red devuelve lo último bueno y avisa con su hora; con red vuelve a avisar de que es en vivo', () async {
      final (c, s, _, _, avisos) = _montar({'total': 2});
      expect(await c.enviar('GET', '/hoy'), {'total': 2});
      expect(avisos.last, ('/hoy', null));
      s.datos = null; // se va la red
      expect(await c.enviar('GET', '/hoy'), {'total': 2});
      expect(avisos.last.$1, '/hoy');
      expect(avisos.last.$2, isNotNull);
      s.datos = {'total': 3};
      expect(await c.enviar('GET', '/hoy'), {'total': 3});
      expect(avisos.last, ('/hoy', null));
    });

    test('la caché distingue consulta y despacho', () async {
      final (c, s, ctx, _, _) = _montar([1]);
      await c.enviar('GET', '/tareas-outlook', consulta: {'ambito': 'propias'});
      s.datos = null;
      expect(await c.enviar('GET', '/tareas-outlook', consulta: {'ambito': 'propias'}), [1]);
      expect(await _falla(c.enviar('GET', '/tareas-outlook', consulta: {'ambito': 'asignadas'})), isNotNull);
      ctx.despacho = '9';
      expect(await _falla(c.enviar('GET', '/tareas-outlook', consulta: {'ambito': 'propias'})), isNotNull, reason: 'otro despacho no ve lo del anterior');
    });

    test('sin nada guardado, el error de red sigue siendo error de red', () async {
      final (c, _, _, _, _) = _montar(null);
      final e = await _falla(c.enviar('GET', '/hoy'));
      expect(e!.esDeConexion, isTrue);
    });

    test('un error del servidor no se tapa con lo guardado', () async {
      final (c, s, _, _, _) = _montar({'ok': 1});
      await c.enviar('GET', '/hoy');
      s.status = 403;
      final e = await _falla(c.enviar('GET', '/hoy'));
      expect(e!.status, 403);
    });

    test('no guarda lo que no está en la lista, ni las escrituras, ni adjuntos, ni sin sesión', () async {
      final (c, s, ctx, cache, _) = _montar({'a': 1});
      await c.enviar('GET', '/correo/bandeja');
      await c.enviar('POST', '/tareas-outlook', cuerpo: {'asunto': 'x'});
      await c.enviar('GET', '/tareas-outlook/5/adjuntos');
      ctx.usuarioId = null;
      await c.enviar('GET', '/hoy');
      expect(await cache.contar(), 0);
      ctx.usuarioId = 7;
      s.datos = null;
      expect(await _falla(c.enviar('GET', '/correo/bandeja')), isNotNull);
    });
  });
}

Future<ApiException?> _falla(Future<dynamic> f) async {
  try {
    await f;
    return null;
  } on ApiException catch (e) {
    return e;
  }
}
