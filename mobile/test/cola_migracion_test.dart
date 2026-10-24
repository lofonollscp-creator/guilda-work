import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/api/cliente.dart';
import 'package:guilda_work_mobile/api/errores.dart';
import 'package:guilda_work_mobile/api/generado/operaciones.g.dart' show Transporte;
import 'package:guilda_work_mobile/datos/cola.dart';
import 'package:guilda_work_mobile/datos/cola_procesador.dart';
import 'package:guilda_work_mobile/datos/local/cola_escritura.dart';
import 'package:guilda_work_mobile/funciones/fichaje/fichaje_acciones.dart';
import 'package:guilda_work_mobile/funciones/notas/notas_acciones.dart';
import 'package:guilda_work_mobile/nucleo/servicios.dart' show clienteApiProvider;
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:guilda_work_mobile/services/api_client.dart' show Usuario;
import 'package:guilda_work_mobile/services/sync_service.dart';
import 'package:sqflite/sqflite.dart' show Sqflite;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

int _ahora = 5000000;
ColaEscritura _cola() => ColaEscritura(
      abrir: () => databaseFactoryFfi.openDatabase(inMemoryDatabasePath, options: OpenDatabaseOptions(version: 1, onCreate: ColaEscritura.crearEsquema, singleInstance: false)),
      ahoraMs: () => _ahora,
    );

/// Crea un fichero con el esquema de la cola ANTIGUA de una versión anterior de la app.
Future<String> _antigua({List<Map<String, Object?>> fichajes = const [], List<Map<String, Object?>> notas = const []}) async {
  final dir = await Directory.systemTemp.createTemp('cola-antigua');
  addTearDown(() => dir.delete(recursive: true));
  final ruta = '${dir.path}/guilda_work_cola.db';
  final db = await databaseFactoryFfi.openDatabase(ruta, options: OpenDatabaseOptions(version: 1, onCreate: (db, v) async {
    await db.execute('CREATE TABLE cola_fichajes (id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, marca_tiempo TEXT NOT NULL, cliente_uuid TEXT NOT NULL UNIQUE)');
    await db.execute('CREATE TABLE cola_notas (id INTEGER PRIMARY KEY AUTOINCREMENT, texto TEXT NOT NULL, categoria_id INTEGER, creada_en TEXT NOT NULL, cliente_uuid TEXT NOT NULL UNIQUE)');
  }));
  for (final f in fichajes) {
    await db.insert('cola_fichajes', f);
  }
  for (final n in notas) {
    await db.insert('cola_notas', n);
  }
  await db.close();
  return ruta;
}

Future<int> _filas(String ruta, String tabla) async {
  final db = await databaseFactoryFfi.openDatabase(ruta);
  final n = Sqflite.firstIntValue(await db.rawQuery('SELECT COUNT(*) FROM $tabla')) ?? 0;
  await db.close();
  return n;
}

// ---------- cliente falso para las acciones ----------

class _Ctx implements ContextoApi {
  @override
  Future<String> servidor() async => 'https://s.test';
  @override
  Future<String?> token() async => 't';
  @override
  String? get despacho => null;
  @override
  String get idioma => 'es';
  @override
  String get versionApp => '1.0.0';
  @override
  String get plataforma => 'android';
  @override
  Future<void> alSesionExpirada() async {}
  @override
  Future<void> alRequerirActualizacion({String? urlTienda}) async {}
}

class _Llamada {
  final String clave, metodo, ruta;
  final Object? cuerpo;
  _Llamada(this.clave, this.metodo, this.ruta, this.cuerpo);
}

class _ClienteFalso extends ClienteApi {
  final llamadas = <_Llamada>[];
  Object? Function(_Llamada)? respuesta; // devuelve datos o lanza
  _ClienteFalso() : super(_Ctx());
  @override
  Transporte conClave(String clave) => _Conectado(this, clave);
}

class _Conectado implements Transporte {
  final _ClienteFalso _c;
  final String _clave;
  _Conectado(this._c, this._clave);
  @override
  Future<dynamic> enviar(String metodo, String ruta, {Map<String, dynamic>? consulta, Object? cuerpo, bool multipart = false, bool binario = false}) async {
    final l = _Llamada(_clave, metodo, ruta, cuerpo);
    _c.llamadas.add(l);
    return _c.respuesta?.call(l);
  }
}

class _Sesion extends SesionControl {
  @override
  EstadoSesion build() => EstadoSesion(fase: FaseSesion.conSesion, usuario: Usuario(id: 1, email: 'a@b.c'), despacho: '3');
}

void main() {
  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi; // el código de producción usa la API global de sqflite; aquí habla con SQLite por FFI
  });
  setUp(() => _ahora = 5000000);

  group('migración de la cola antigua', () {
    test('pasa fichajes (en su orden) y notas a la cola nueva con su cliente_uuid como clave, y vacía la antigua', () async {
      final ruta = await _antigua(
        fichajes: [
          {'tipo': 'entrada', 'marca_tiempo': '2026-10-24T08:01:00.000', 'cliente_uuid': 'f1'},
          {'tipo': 'pausa_inicio', 'marca_tiempo': '2026-10-24T11:00:00.000', 'cliente_uuid': 'f2'},
        ],
        notas: [
          {'texto': 'Llamar al gestor', 'categoria_id': 4, 'creada_en': '2026-10-24T09:00:00.000', 'cliente_uuid': 'n1'},
          {'texto': 'Sin categoría', 'categoria_id': null, 'creada_en': '2026-10-24T09:30:00.000', 'cliente_uuid': 'n2'},
        ],
      );
      final cola = _cola();
      expect(await SyncService(ruta: () async => ruta).migrarA(cola, usuarioId: 1, despachoId: '3'), 4);
      final p = await cola.de(1, '3');
      expect(p.map((x) => x.clave), ['f1', 'f2', 'n1', 'n2']);
      expect(p[0].ruta, '/fichaje/marcar');
      expect(p[0].cuerpoMapa, {'tipo': 'entrada', 'marca_tiempo': '2026-10-24T08:01:00.000', 'cliente_uuid': 'f1'});
      expect((p[0].entidad, p[1].entidad), (ProcesadorCola.entidadFichaje, ProcesadorCola.entidadFichaje)); // estricto: misma entidad, mismo orden
      expect(p[0].descripcion, 'entrada 08:01');
      expect(p[2].ruta, '/notas');
      expect(p[2].cuerpoMapa, {'texto': 'Llamar al gestor', 'categoria_id': 4, 'creada_en': '2026-10-24T09:00:00.000', 'cliente_uuid': 'n1'});
      expect(p[3].cuerpoMapa!.containsKey('categoria_id'), false);
      expect(p[2].entidad, isNot(p[3].entidad)); // las notas no esperan unas a otras
      expect(await _filas(ruta, 'cola_fichajes'), 0);
      expect(await _filas(ruta, 'cola_notas'), 0);
    });

    test('es repetible: la segunda vez no hay nada, y si se interrumpió no se duplica', () async {
      final ruta = await _antigua(fichajes: [
        {'tipo': 'entrada', 'marca_tiempo': '2026-10-24T08:01:00.000', 'cliente_uuid': 'f1'},
        {'tipo': 'salida', 'marca_tiempo': '2026-10-24T17:00:00.000', 'cliente_uuid': 'f2'},
      ]);
      final cola = _cola();
      // simula un corte: f1 ya estaba en la cola nueva pero seguía en la antigua
      await cola.encolar(metodo: 'POST', ruta: '/fichaje/marcar', clave: 'f1', usuarioId: 1, despachoId: '3', entidad: 'fichaje', tipo: 'fichaje.marca', descripcion: 'entrada');
      final s = SyncService(ruta: () async => ruta);
      expect(await s.migrarA(cola, usuarioId: 1, despachoId: '3'), 2);
      expect((await cola.de(1, '3')).map((x) => x.clave), ['f1', 'f2']); // sin duplicar f1
      expect(await s.migrarA(cola, usuarioId: 1, despachoId: '3'), 0);
    });

    test('instalación nueva: no hace nada y no crea el fichero', () async {
      final dir = await Directory.systemTemp.createTemp('sin-cola');
      addTearDown(() => dir.delete(recursive: true));
      final ruta = '${dir.path}/guilda_work_cola.db';
      expect(await SyncService(ruta: () async => ruta).migrarA(_cola(), usuarioId: 1, despachoId: '3'), 0);
      expect(File(ruta).existsSync(), false);
    });

    test('si la cola nueva está llena, lo que no cabe se queda en la antigua (no se pierde)', () async {
      final ruta = await _antigua(notas: [
        {'texto': 'una', 'categoria_id': null, 'creada_en': 'x', 'cliente_uuid': 'n1'},
        {'texto': 'dos', 'categoria_id': null, 'creada_en': 'x', 'cliente_uuid': 'n2'},
      ]);
      final cola = _cola();
      for (var i = 0; i < 199; i++) {
        await cola.encolar(metodo: 'POST', ruta: '/x', clave: 'k$i', usuarioId: 1, despachoId: '3', entidad: 'e$i', tipo: 't', descripcion: 'd');
      }
      expect(await SyncService(ruta: () async => ruta).migrarA(cola, usuarioId: 1, despachoId: '3'), 1);
      expect(await _filas(ruta, 'cola_notas'), 1);
    });
  });

  group('fichar sin conexión', () {
    late ColaEscritura cola;
    late _ClienteFalso cliente;
    late ProviderContainer c;

    setUp(() {
      cola = _cola();
      cliente = _ClienteFalso();
      c = ProviderContainer(overrides: [
        colaEscrituraProvider.overrideWithValue(cola),
        clienteApiProvider.overrideWithValue(cliente),
        estadoSesionProvider.overrideWith(_Sesion.new),
      ]);
      addTearDown(c.dispose);
    });

    test('con red: manda el cliente_uuid como clave y devuelve el estado', () async {
      cliente.respuesta = (l) => {'estado': 'dentro'};
      final r = await c.read(accionesFichajeProvider).marcar('entrada', latitud: 41.3, longitud: 2.1);
      expect((r.encolada, r.valor), (false, 'dentro'));
      final l = cliente.llamadas.single;
      expect(l.ruta, '/fichaje/marcar');
      expect((l.cuerpo as Map)['cliente_uuid'], l.clave);
      expect((l.cuerpo as Map)['latitud'], 41.3);
      expect(await cola.contar(1, '3'), 0);
    });

    test('sin red: se guarda con la hora REAL de la pulsación, la ubicación y la misma clave del primer intento', () async {
      cliente.respuesta = (l) => throw ApiException('sin red', esDeConexion: true);
      final r = await c.read(accionesFichajeProvider).marcar('salida', latitud: 41.3, longitud: 2.1, ahora: DateTime(2026, 10, 24, 17, 5, 9));
      expect(r.encolada, true);
      final p = (await cola.de(1, '3')).single;
      expect((p.ruta, p.entidad, p.tipo), ('/fichaje/marcar', ProcesadorCola.entidadFichaje, 'fichaje.marca'));
      expect(p.clave, cliente.llamadas.single.clave); // si el primer intento sí llegó, el servidor lo reconoce y no ficha dos veces
      expect(p.cuerpoMapa, {'tipo': 'salida', 'cliente_uuid': p.clave, 'latitud': 41.3, 'longitud': 2.1, 'marca_tiempo': DateTime(2026, 10, 24, 17, 5, 9).toIso8601String()});
      expect(p.descripcion, 'salida 17:05');
    });

    test('un error de negocio (secuencia inválida) no se encola: se enseña', () async {
      cliente.respuesta = (l) => throw ApiException('No se puede fichar «entrada» viniendo de «entrada»', status: 400);
      await expectLater(c.read(accionesFichajeProvider).marcar('entrada'), throwsA(isA<ApiException>()));
      expect(await cola.contar(1, '3'), 0);
    });

    test('la nota rápida sin red: queda con su hora, su categoría y la clave del primer intento', () async {
      cliente.respuesta = (l) => throw ApiException('sin red', esDeConexion: true);
      expect(await c.read(accionesNotasProvider).crear('  Llamar al gestor ', categoriaId: 4, ahora: DateTime(2026, 10, 24, 9)), true);
      final p = (await cola.de(1, '3')).single;
      expect((p.ruta, p.tipo), ('/notas', 'nota.crear'));
      expect(p.clave, cliente.llamadas.single.clave);
      expect(p.cuerpoMapa, {'texto': 'Llamar al gestor', 'categoria_id': 4, 'cliente_uuid': p.clave, 'creada_en': DateTime(2026, 10, 24, 9).toIso8601String()});
      cliente.respuesta = (l) => null; // con red
      expect(await c.read(accionesNotasProvider).crear('Otra'), false);
    });
  });

  group('el orden de los fichajes', () {
    late ColaEscritura cola;
    late List<String> enviadas;
    late Map<String, ApiException> falla;
    late ProcesadorCola proc;

    setUp(() async {
      cola = _cola();
      enviadas = [];
      falla = {};
      proc = ProcesadorCola(
        cola: cola, usuarioActivo: () => 1, despachoActivo: () => '3', ahoraMs: () => _ahora,
        enviar: (p) async {
          enviadas.add(p.clave);
          if (falla[p.clave] != null) throw falla[p.clave]!;
          return null;
        },
      );
      for (final k in ['entrada', 'pausa', 'salida']) {
        await cola.encolar(metodo: 'POST', ruta: '/fichaje/marcar', clave: k, usuarioId: 1, despachoId: '3', entidad: ProcesadorCola.entidadFichaje, tipo: 'fichaje.marca', descripcion: k);
      }
    });

    test('salen estrictamente en el orden en que se pulsaron', () async {
      await proc.procesar();
      expect(enviadas, ['entrada', 'pausa', 'salida']);
    });

    test('si uno no puede salir por la red, los siguientes esperan (no se adelantan)', () async {
      falla['entrada'] = ApiException('sin red', esDeConexion: true);
      await proc.procesar();
      expect(enviadas, ['entrada']);
      falla.clear();
      _ahora += 5000;
      await proc.procesar();
      expect(enviadas, ['entrada', 'entrada', 'pausa', 'salida']);
    });

    test('un fichaje que el servidor rechaza NO bloquea los siguientes y se queda a la vista, rechazado', () async {
      falla['pausa'] = ApiException('No se puede fichar «pausa_inicio» viniendo de «fuera»', status: 400);
      final r = await proc.procesar();
      expect(enviadas, ['entrada', 'pausa', 'salida']); // la salida sí llegó
      expect(r.rechazadas, 1);
      final resto = await cola.de(1, '3');
      expect(resto.map((p) => (p.clave, p.estado)), [('pausa', EstadoPendiente.rechazada)]);
      expect(resto.single.error, contains('viniendo de'));
      enviadas.clear();
      await proc.procesar(); // no se reintenta lo rechazado
      expect(enviadas, isEmpty);
    });
  });
}
