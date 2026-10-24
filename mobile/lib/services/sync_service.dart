import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import '../datos/local/cola_escritura.dart';

/// La cola ANTIGUA de acciones pulsadas sin conexión (fichajes y notas rápidas, `guilda_work_cola.db`). Ya no se escribe en ella: todo va a la cola
/// de escritura genérica (`datos/local/cola_escritura.dart`). Esta clase solo existe para **migrar** lo que una versión anterior de la app dejó pendiente.
class SyncService {
  /// Ruta del fichero antiguo; en las pruebas se sustituye.
  final Future<String> Function() _ruta;

  SyncService({Future<String> Function()? ruta}) : _ruta = ruta ?? (() async => p.join(await getDatabasesPath(), 'guilda_work_cola.db'));

  /// Pasa a la cola nueva lo que quedó pendiente en la antigua y lo borra de ella. Cada acción conserva su `cliente_uuid` como clave de idempotencia:
  /// si ya había llegado al servidor, el reenvío no la duplica. Las filas antiguas no guardaban de quién eran: se asignan a la persona y el despacho
  /// con los que se abre la app por primera vez tras actualizar. Devuelve cuántas se migraron. Es seguro llamarlo cada vez (sin fichero, no hace nada).
  Future<int> migrarA(ColaEscritura cola, {required int usuarioId, required String despachoId}) async {
    final ruta = await _ruta();
    if (!await databaseExists(ruta)) return 0; // instalación nueva: nada que migrar (y no se crea el fichero)
    final db = await openDatabase(ruta);
    var migradas = 0;
    try {
      final tablas = {for (final t in await db.rawQuery("SELECT name FROM sqlite_master WHERE type = 'table'")) t['name'] as String};

      if (tablas.contains('cola_fichajes')) {
        // En el orden en que se pulsaron: el servidor valida la secuencia por orden de llegada.
        for (final f in await db.query('cola_fichajes', orderBy: 'id ASC')) {
          final uuid = f['cliente_uuid'] as String;
          if (!await cola.existeClave(uuid)) {
            try {
              await cola.encolar(
                metodo: 'POST',
                ruta: '/fichaje/marcar',
                cuerpo: {'tipo': f['tipo'], 'marca_tiempo': f['marca_tiempo'], 'cliente_uuid': uuid},
                clave: uuid,
                usuarioId: usuarioId,
                despachoId: despachoId,
                entidad: 'fichaje',
                tipo: 'fichaje.marca',
                descripcion: '${f['tipo']} ${_hora(f['marca_tiempo'] as String)}',
              );
            } on ColaLlena {
              return migradas; // el resto se queda en la antigua hasta que haya sitio
            }
          }
          await db.delete('cola_fichajes', where: 'id = ?', whereArgs: [f['id']]);
          migradas++;
        }
      }

      if (tablas.contains('cola_notas')) {
        for (final n in await db.query('cola_notas', orderBy: 'id ASC')) {
          final uuid = n['cliente_uuid'] as String;
          if (!await cola.existeClave(uuid)) {
            try {
              await cola.encolar(
                metodo: 'POST',
                ruta: '/notas',
                cuerpo: {'texto': n['texto'], 'categoria_id': n['categoria_id'], 'creada_en': n['creada_en'], 'cliente_uuid': uuid}..removeWhere((_, v) => v == null),
                clave: uuid,
                usuarioId: usuarioId,
                despachoId: despachoId,
                entidad: 'nota-nueva:$uuid',
                tipo: 'nota.crear',
                descripcion: n['texto'] as String,
              );
            } on ColaLlena {
              return migradas;
            }
          }
          await db.delete('cola_notas', where: 'id = ?', whereArgs: [n['id']]);
          migradas++;
        }
      }
    } finally {
      await db.close();
    }
    return migradas;
  }

  /// «2026-10-24T09:05:00.000» → «09:05».
  String _hora(String iso) => iso.length >= 16 ? iso.substring(11, 16) : iso;
}
