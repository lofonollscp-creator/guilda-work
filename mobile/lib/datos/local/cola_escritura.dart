import 'dart:convert';

import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

enum EstadoPendiente {
  /// Esperando su turno o a que vuelva la red.
  pendiente,

  /// Se está enviando ahora mismo.
  enviando,

  /// El servidor dice que alguien cambió el recurso (409/412): la intención se conserva y la persona decide.
  conflicto,

  /// El servidor la rechazó por una regla de negocio: reintentar igual no sirve.
  rechazada,
}

/// Una escritura hecha sin conexión, a la espera de enviarse.
class Pendiente {
  final int id;
  final String metodo;
  final String ruta;
  final String? cuerpo; // JSON
  final String clave; // Idempotency-Key: la misma en cada reintento
  final int usuarioId;
  final String despachoId;
  final String entidad; // p. ej. «tarea:12»: FIFO dentro de una entidad
  final String tipo; // p. ej. «tarea.estado»
  final String descripcion; // lo que ve la persona
  final int creadaEnMs;
  final int intentos;
  final EstadoPendiente estado;
  final String? error;
  final int proximoIntentoMs;
  final int? versionActual; // en un conflicto: la versión que hay ahora en el servidor
  final String? localId; // «local:<uuid>» si crea algo que otras acciones pendientes referencian

  const Pendiente({
    required this.id,
    required this.metodo,
    required this.ruta,
    required this.cuerpo,
    required this.clave,
    required this.usuarioId,
    required this.despachoId,
    required this.entidad,
    required this.tipo,
    required this.descripcion,
    required this.creadaEnMs,
    required this.intentos,
    required this.estado,
    required this.error,
    required this.proximoIntentoMs,
    required this.versionActual,
    required this.localId,
  });

  Map<String, dynamic>? get cuerpoMapa => cuerpo == null ? null : jsonDecode(cuerpo!) as Map<String, dynamic>;

  factory Pendiente.desdeFila(Map<String, Object?> f) => Pendiente(
        id: f['id'] as int,
        metodo: f['metodo'] as String,
        ruta: f['ruta'] as String,
        cuerpo: f['cuerpo'] as String?,
        clave: f['clave'] as String,
        usuarioId: f['usuario_id'] as int,
        despachoId: f['despacho_id'] as String,
        entidad: f['entidad'] as String,
        tipo: f['tipo'] as String,
        descripcion: f['descripcion'] as String,
        creadaEnMs: f['creada_en'] as int,
        intentos: f['intentos'] as int,
        estado: EstadoPendiente.values.firstWhere((e) => e.name == f['estado'], orElse: () => EstadoPendiente.pendiente),
        error: f['error'] as String?,
        proximoIntentoMs: f['proximo_intento'] as int,
        versionActual: f['version_actual'] as int?,
        localId: f['local_id'] as String?,
      );
}

/// La cola está llena: no se admiten más cambios sin conexión hasta que se envíen o descarten.
class ColaLlena implements Exception {
  final int maximo;
  ColaLlena(this.maximo);
  @override
  String toString() => 'La cola sin conexión está llena ($maximo cambios pendientes).';
}

/// Cola local de **escrituras** hechas sin conexión (crear/cambiar/comentar una tarea...). Es una sola tabla en un SQLite propio
/// (`guilda_work_escrituras.db`, aparte de la cola antigua de fichajes y notas). Cada acción lleva su `Idempotency-Key`, el usuario y
/// el despacho con los que se hizo: solo se envía con ese usuario y ese despacho activos, nunca mezclados.
///
/// Reglas del plan (§13.1): máximo 200 (aviso a 150), caducidad de 14 días, FIFO dentro de una entidad.
class ColaEscritura {
  static const maximo = 200;
  static const avisoEn = 150;
  static const caducidad = Duration(days: 14);

  final Future<Database> Function()? _abrirPersonalizado;
  final int Function() _ahoraMs;

  /// Se llama tras cualquier cambio (para refrescar contadores en pantalla).
  void Function()? alCambiar;

  Database? _db;

  ColaEscritura({Future<Database> Function()? abrir, int Function()? ahoraMs, this.alCambiar})
      : _abrirPersonalizado = abrir,
        _ahoraMs = ahoraMs ?? (() => DateTime.now().millisecondsSinceEpoch);

  Future<Database> _abrir() async {
    if (_db != null) return _db!;
    if (_abrirPersonalizado != null) return _db = await _abrirPersonalizado();
    final ruta = p.join(await getDatabasesPath(), 'guilda_work_escrituras.db');
    return _db = await openDatabase(ruta, version: 1, onCreate: crearEsquema);
  }

  static Future<void> crearEsquema(Database db, int version) => db.execute('''
        CREATE TABLE cola_escritura (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          metodo TEXT NOT NULL,
          ruta TEXT NOT NULL,
          cuerpo TEXT,
          clave TEXT NOT NULL UNIQUE,
          usuario_id INTEGER NOT NULL,
          despacho_id TEXT NOT NULL,
          entidad TEXT NOT NULL,
          tipo TEXT NOT NULL,
          descripcion TEXT NOT NULL,
          creada_en INTEGER NOT NULL,
          intentos INTEGER NOT NULL DEFAULT 0,
          estado TEXT NOT NULL DEFAULT 'pendiente',
          error TEXT,
          proximo_intento INTEGER NOT NULL DEFAULT 0,
          version_actual INTEGER,
          local_id TEXT
        )''');

  void _avisar() => alCambiar?.call();

  /// Guarda una escritura. Lanza [ColaLlena] si ya hay [maximo].
  Future<Pendiente> encolar({
    required String metodo,
    required String ruta,
    Map<String, dynamic>? cuerpo,
    required String clave,
    required int usuarioId,
    required String despachoId,
    required String entidad,
    required String tipo,
    required String descripcion,
    String? localId,
  }) async {
    final db = await _abrir();
    final hay = Sqflite.firstIntValue(await db.rawQuery('SELECT COUNT(*) FROM cola_escritura')) ?? 0;
    if (hay >= maximo) throw ColaLlena(maximo);
    final id = await db.insert('cola_escritura', {
      'metodo': metodo,
      'ruta': ruta,
      'cuerpo': cuerpo == null ? null : jsonEncode(cuerpo),
      'clave': clave,
      'usuario_id': usuarioId,
      'despacho_id': despachoId,
      'entidad': entidad,
      'tipo': tipo,
      'descripcion': descripcion,
      'creada_en': _ahoraMs(),
      'local_id': localId,
    });
    _avisar();
    return (await uno(id))!;
  }

  Future<Pendiente?> uno(int id) async {
    final filas = await (await _abrir()).query('cola_escritura', where: 'id = ?', whereArgs: [id]);
    return filas.isEmpty ? null : Pendiente.desdeFila(filas.single);
  }

  /// ¿Ya hay una acción con esa clave? (la migración de la cola antigua no repite lo que ya pasó)
  Future<bool> existeClave(String clave) async =>
      (Sqflite.firstIntValue(await (await _abrir()).rawQuery('SELECT COUNT(*) FROM cola_escritura WHERE clave = ?', [clave])) ?? 0) > 0;

  /// Las de esa persona en ese despacho, en orden de creación.
  Future<List<Pendiente>> de(int usuarioId, String despachoId) async {
    final filas = await (await _abrir()).query('cola_escritura', where: 'usuario_id = ? AND despacho_id = ?', whereArgs: [usuarioId, despachoId], orderBy: 'id ASC');
    return [for (final f in filas) Pendiente.desdeFila(f)];
  }

  Future<int> contar(int usuarioId, String despachoId) async =>
      Sqflite.firstIntValue(await (await _abrir()).rawQuery('SELECT COUNT(*) FROM cola_escritura WHERE usuario_id = ? AND despacho_id = ?', [usuarioId, despachoId])) ?? 0;

  /// ¿Hay tantas que conviene avisar de que se llena?
  Future<bool> casiLlena() async => (Sqflite.firstIntValue(await (await _abrir()).rawQuery('SELECT COUNT(*) FROM cola_escritura')) ?? 0) >= avisoEn;

  Future<void> marcar(int id, {EstadoPendiente? estado, int? intentos, String? error, bool borrarError = false, int? proximoIntentoMs, int? versionActual}) async {
    final cambios = <String, Object?>{
      if (estado != null) 'estado': estado.name,
      'intentos': ?intentos,
      'proximo_intento': ?proximoIntentoMs,
      'version_actual': ?versionActual,
    };
    if (borrarError) {
      cambios['error'] = null;
    } else if (error != null) {
      cambios['error'] = error;
    }
    if (cambios.isEmpty) return;
    await (await _abrir()).update('cola_escritura', cambios, where: 'id = ?', whereArgs: [id]);
    _avisar();
  }

  /// Un conflicto que la persona decide aplicar igualmente: se reintenta con la versión que hay ahora.
  Future<void> reintentarConVersion(int id, int version) async {
    final p = await uno(id);
    if (p == null) return;
    final cuerpo = p.cuerpoMapa;
    if (cuerpo != null && cuerpo.containsKey('version')) cuerpo['version'] = version;
    await (await _abrir()).update(
      'cola_escritura',
      {'cuerpo': cuerpo == null ? null : jsonEncode(cuerpo), 'estado': 'pendiente', 'error': null, 'version_actual': null, 'proximo_intento': 0},
      where: 'id = ?',
      whereArgs: [id],
    );
    _avisar();
  }

  /// Si la app se cerró en mitad de un envío, esa acción quedó «enviando»: vuelve a pendiente (su `Idempotency-Key` evita que se duplique).
  Future<void> reiniciarEnviando() async {
    await (await _abrir()).update('cola_escritura', {'estado': 'pendiente'}, where: "estado = 'enviando'");
  }

  /// Vuelve a ponerla en la fila de salida ya (reintento manual).
  Future<void> reintentarAhora(int id) => marcar(id, estado: EstadoPendiente.pendiente, proximoIntentoMs: 0, borrarError: true);

  Future<void> eliminar(int id) async {
    await (await _abrir()).delete('cola_escritura', where: 'id = ?', whereArgs: [id]);
    _avisar();
  }

  /// Cuando algo creado sin conexión (`local:<uuid>`) por fin existe, las acciones pendientes que lo nombran pasan a usar su id real.
  Future<void> sustituirIdLocal(String localId, Object idReal) async {
    final db = await _abrir();
    await db.rawUpdate(
      "UPDATE cola_escritura SET ruta = REPLACE(ruta, ?, ?), cuerpo = REPLACE(cuerpo, ?, ?), entidad = REPLACE(entidad, ?, ?) WHERE ruta LIKE ? OR cuerpo LIKE ? OR entidad LIKE ?",
      [localId, '$idReal', localId, '$idReal', localId, '$idReal', '%$localId%', '%$localId%', '%$localId%'],
    );
    _avisar();
  }

  /// Quita lo que lleva más de 14 días. Devuelve cuántas.
  Future<int> purgarCaducadas() async {
    final n = await (await _abrir()).delete('cola_escritura', where: 'creada_en < ?', whereArgs: [_ahoraMs() - caducidad.inMilliseconds]);
    if (n > 0) _avisar();
    return n;
  }

  /// Descarta todo lo de esa persona (al cerrar sesión, tras avisarle).
  Future<void> vaciar(int usuarioId) async {
    await (await _abrir()).delete('cola_escritura', where: 'usuario_id = ?', whereArgs: [usuarioId]);
    _avisar();
  }
}
