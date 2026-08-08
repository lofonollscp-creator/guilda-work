import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'package:guilda_work_mobile/services/api_client.dart';
import 'package:guilda_work_mobile/services/sync_service.dart';

class MockApiClient extends Mock implements ApiClient {}

void main() {
  // sqflite habla por platform channel en un dispositivo real; en el
  // entorno de `flutter test` no hay ninguno, así que se sustituye por el
  // backend FFI (SQLite de verdad, sin plugin nativo) -- SyncService no se
  // entera de la diferencia, usa la misma API `sqflite` en ambos casos.
  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  late MockApiClient api;
  late SyncService sync;

  setUp(() async {
    // SyncService abre siempre el mismo fichero físico
    // (getDatabasesPath()/guilda_work_cola.db) -- sin borrarlo entre tests,
    // filas de un test se colarían en el siguiente.
    final ruta = p.join(await getDatabasesPath(), 'guilda_work_cola.db');
    await databaseFactory.deleteDatabase(ruta);
    api = MockApiClient();
    sync = SyncService();
  });

  group('cola de fichajes', () {
    test('encolarFichaje guarda una pulsación pendiente', () async {
      await sync.encolarFichaje('entrada', DateTime(2026, 1, 1, 9, 0));
      expect(await sync.contarPendientes(), 1);
    });

    test('sincronizar() envía lo pendiente y vacía la cola si el servidor confirma', () async {
      when(() => api.fichar(any(), marcaTiempo: any(named: 'marcaTiempo'), clienteUuid: any(named: 'clienteUuid')))
          .thenAnswer((_) async => 'dentro');

      await sync.encolarFichaje('entrada', DateTime(2026, 1, 1, 9, 0));
      await sync.sincronizar(api);

      expect(await sync.contarPendientes(), 0);
      verify(() => api.fichar('entrada', marcaTiempo: any(named: 'marcaTiempo'), clienteUuid: any(named: 'clienteUuid')))
          .called(1);
    });

    test('sincronizar() deja la cola intacta si sigue sin haber red', () async {
      when(() => api.fichar(any(), marcaTiempo: any(named: 'marcaTiempo'), clienteUuid: any(named: 'clienteUuid')))
          .thenThrow(ApiException('sin conexión', esDeConexion: true));

      await sync.encolarFichaje('entrada', DateTime(2026, 1, 1, 9, 0));
      await sync.sincronizar(api);

      expect(await sync.contarPendientes(), 1);
    });

    test('sincronizar() descarta un fichaje si el servidor lo rechaza por negocio (no reintentable)', () async {
      when(() => api.fichar(any(), marcaTiempo: any(named: 'marcaTiempo'), clienteUuid: any(named: 'clienteUuid')))
          .thenThrow(ApiException('secuencia inválida', esDeConexion: false));

      await sync.encolarFichaje('entrada', DateTime(2026, 1, 1, 9, 0));
      await sync.sincronizar(api);

      expect(await sync.contarPendientes(), 0);
    });
  });

  group('cola de notas', () {
    test('sincronizar() envía las notas pendientes con su hora original', () async {
      DateTime? creadaEnviada;
      when(() => api.crearNota(any(),
              categoriaId: any(named: 'categoriaId'),
              creadaEn: any(named: 'creadaEn'),
              clienteUuid: any(named: 'clienteUuid')))
          .thenAnswer((invocacion) async {
        creadaEnviada = DateTime.parse(invocacion.namedArguments[#creadaEn] as String);
      });

      final hora = DateTime(2026, 1, 1, 8, 30);
      await sync.encolarNota('nota de prueba', null, hora);
      await sync.sincronizar(api);

      expect(await sync.contarPendientes(), 0);
      expect(creadaEnviada, hora);
    });
  });
}
