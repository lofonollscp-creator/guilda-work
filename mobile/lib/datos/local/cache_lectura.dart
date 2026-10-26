import 'dart:convert';

import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

/// Lo que el cliente HTTP necesita de una caché de lecturas: guardar la última respuesta buena de una consulta y devolverla cuando no hay red.
abstract class AlmacenLectura {
  Future<void> guardar({required String clave, required int usuarioId, required String despachoId, required Object? datos});
  Future<LecturaGuardada?> leer(String clave, int usuarioId);
}

class LecturaGuardada {
  final dynamic datos;
  final DateTime guardadaEn;
  const LecturaGuardada(this.datos, this.guardadaEn);
}

/// Caché de **lectura** sin conexión: la última respuesta correcta de «Hoy» y de las tareas (listas y fichas), en un SQLite propio
/// (`guilda_work_lectura.db`). Va ligada a la persona y al despacho (nunca se enseña lo de otra cuenta), caduca a los 30 días, guarda
/// como mucho [maximo] consultas (se borran las más antiguas) y se vacía al cerrar sesión.
class CacheLectura implements AlmacenLectura {
  static const maximo = 300;
  static const caducidad = Duration(days: 30);

  final Future<Database> Function()? _abrirPersonalizado;
  final int Function() _ahoraMs;
  Database? _db;

  CacheLectura({Future<Database> Function()? abrir, int Function()? ahoraMs})
      : _abrirPersonalizado = abrir,
        _ahoraMs = ahoraMs ?? (() => DateTime.now().millisecondsSinceEpoch);

  Future<Database> _abrir() async {
    if (_db != null) return _db!;
    if (_abrirPersonalizado != null) return _db = await _abrirPersonalizado();
    final ruta = p.join(await getDatabasesPath(), 'guilda_work_lectura.db');
    return _db = await openDatabase(ruta, version: 1, onCreate: crearEsquema);
  }

  static Future<void> crearEsquema(Database db, int version) => db.execute('''
        CREATE TABLE lectura (
          clave TEXT NOT NULL,
          usuario_id INTEGER NOT NULL,
          despacho_id TEXT NOT NULL,
          datos TEXT NOT NULL,
          guardada_en INTEGER NOT NULL,
          PRIMARY KEY (clave, usuario_id)
        )''');

  @override
  Future<void> guardar({required String clave, required int usuarioId, required String despachoId, required Object? datos}) async {
    final db = await _abrir();
    final ahora = _ahoraMs();
    await db.insert(
      'lectura',
      {'clave': clave, 'usuario_id': usuarioId, 'despacho_id': despachoId, 'datos': jsonEncode(datos), 'guardada_en': ahora},
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
    await db.delete('lectura', where: 'guardada_en < ?', whereArgs: [ahora - caducidad.inMilliseconds]);
    await db.rawDelete(
      'DELETE FROM lectura WHERE rowid IN (SELECT rowid FROM lectura ORDER BY guardada_en DESC LIMIT -1 OFFSET ?)',
      [maximo],
    );
  }

  @override
  Future<LecturaGuardada?> leer(String clave, int usuarioId) async {
    final filas = await (await _abrir()).query('lectura', where: 'clave = ? AND usuario_id = ?', whereArgs: [clave, usuarioId]);
    if (filas.isEmpty) return null;
    final f = filas.single;
    final cuando = f['guardada_en'] as int;
    if (_ahoraMs() - cuando > caducidad.inMilliseconds) return null;
    return LecturaGuardada(jsonDecode(f['datos'] as String), DateTime.fromMillisecondsSinceEpoch(cuando));
  }

  /// Borra todo (cerrar sesión): lo guardado de una persona no debe quedar en un móvil que ya no es suyo.
  Future<void> vaciar() async => (await _abrir()).delete('lectura');

  Future<int> contar() async => Sqflite.firstIntValue(await (await _abrir()).rawQuery('SELECT COUNT(*) FROM lectura')) ?? 0;
}
