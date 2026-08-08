import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';
import 'package:uuid/uuid.dart';

import 'api_client.dart';

/// Cola local de acciones pulsadas sin conexión (fichaje y notas rápidas) --
/// ver ApiException.esDeConexion en api_client.dart para cuándo se encola
/// algo aquí en vez de mostrar el error tal cual. Se sincroniza sola al
/// recuperar conexión o volver la app a primer plano (ver main.dart).
class SyncService {
  static const _version = 1;
  Database? _db;
  final _uuid = const Uuid();
  bool _sincronizando = false;

  Future<Database> _abrir() async {
    if (_db != null) return _db!;
    final ruta = p.join(await getDatabasesPath(), 'guilda_work_cola.db');
    _db = await openDatabase(
      ruta,
      version: _version,
      onCreate: (db, version) async {
        await db.execute('''
          CREATE TABLE cola_fichajes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            marca_tiempo TEXT NOT NULL,
            cliente_uuid TEXT NOT NULL UNIQUE
          )
        ''');
        await db.execute('''
          CREATE TABLE cola_notas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            texto TEXT NOT NULL,
            categoria_id INTEGER,
            creada_en TEXT NOT NULL,
            cliente_uuid TEXT NOT NULL UNIQUE
          )
        ''');
      },
    );
    return _db!;
  }

  Future<void> encolarFichaje(String tipo, DateTime marcaTiempo) async {
    final db = await _abrir();
    await db.insert('cola_fichajes', {
      'tipo': tipo,
      'marca_tiempo': marcaTiempo.toIso8601String(),
      'cliente_uuid': _uuid.v4(),
    });
  }

  Future<void> encolarNota(String texto, int? categoriaId, DateTime creadaEn) async {
    final db = await _abrir();
    await db.insert('cola_notas', {
      'texto': texto,
      'categoria_id': categoriaId,
      'creada_en': creadaEn.toIso8601String(),
      'cliente_uuid': _uuid.v4(),
    });
  }

  Future<int> contarPendientes() async {
    final db = await _abrir();
    final f = Sqflite.firstIntValue(await db.rawQuery('SELECT COUNT(*) FROM cola_fichajes')) ?? 0;
    final n = Sqflite.firstIntValue(await db.rawQuery('SELECT COUNT(*) FROM cola_notas')) ?? 0;
    return f + n;
  }

  /// Recorre la cola y sube cada pendiente; borra localmente lo que el
  /// servidor confirma. Los fichajes se mandan en orden de pulsación (por
  /// id de inserción local) -- importante porque el servidor valida la
  /// secuencia por orden de llegada, no por marca_tiempo (ver comentario de
  /// db.fichar() en el backend).
  Future<void> sincronizar(ApiClient api) async {
    if (_sincronizando) return;
    _sincronizando = true;
    try {
      final db = await _abrir();

      final fichajes = await db.query('cola_fichajes', orderBy: 'id ASC');
      for (final f in fichajes) {
        try {
          await api.fichar(
            f['tipo'] as String,
            marcaTiempo: f['marca_tiempo'] as String,
            clienteUuid: f['cliente_uuid'] as String,
          );
          await db.delete('cola_fichajes', where: 'id = ?', whereArgs: [f['id']]);
        } on ApiException catch (e) {
          if (e.esDeConexion) return; // sigue sin red: se reintenta en la siguiente pasada
          // Error de negocio (ej. secuencia inválida porque ya se fichó algo
          // más reciente desde otro sitio mientras estaba offline): no se
          // puede resolver reintentando igual, se descarta para no bloquear
          // el resto de la cola.
          await db.delete('cola_fichajes', where: 'id = ?', whereArgs: [f['id']]);
        }
      }

      final notas = await db.query('cola_notas', orderBy: 'id ASC');
      for (final n in notas) {
        try {
          await api.crearNota(
            n['texto'] as String,
            categoriaId: n['categoria_id'] as int?,
            creadaEn: n['creada_en'] as String,
            clienteUuid: n['cliente_uuid'] as String,
          );
          await db.delete('cola_notas', where: 'id = ?', whereArgs: [n['id']]);
        } on ApiException catch (e) {
          if (e.esDeConexion) return;
          await db.delete('cola_notas', where: 'id = ?', whereArgs: [n['id']]);
        }
      }
    } finally {
      _sincronizando = false;
    }
  }
}
