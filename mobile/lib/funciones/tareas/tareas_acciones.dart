import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../../api/errores.dart';
import '../../api/generado/modelos.g.dart';
import '../../datos/cola.dart';
import '../../datos/local/cola_escritura.dart' show Pendiente;
import '../../dominio/tarea.dart';
import 'tareas_repositorio.dart';

/// Resultado de una acción que puede hacerse sin conexión: o se envió, o quedó guardada para enviarla al volver la red.
class ResultadoAccion<T> {
  final T? valor;
  final bool encolada;
  const ResultadoAccion._(this.valor, this.encolada);
  const ResultadoAccion.enviada(T valor) : this._(valor, false);
  const ResultadoAccion.encolada([T? provisional]) : this._(provisional, true);
}

/// Las escrituras de tareas que **no se pierden sin red**: crear, cambiar de estado y comentar. Se intentan al momento; si falla la conexión se
/// guardan en la cola con la misma `Idempotency-Key` (si la primera petición sí llegó, el reenvío no duplica) y se devuelve un valor provisional
/// para que la pantalla lo enseñe como «pendiente». Un error de negocio (tarea bloqueada, conflicto...) NO se encola: se relanza.
class AccionesTareas {
  final Ref _ref;
  final Uuid _uuid = const Uuid();
  AccionesTareas(this._ref);

  TareasRepositorio get _repo => _ref.read(tareasRepositorioProvider);

  /// Id provisional (negativo) de una tarea creada sin conexión: nunca coincide con uno del servidor.
  static int idProvisional(Pendiente p) => -p.id;

  Future<ResultadoAccion<TareaOutlook>> crear(String asunto, {String? fechaVencimiento}) async {
    final clave = _uuid.v4();
    try {
      return ResultadoAccion.enviada(await _repo.crear(asunto: asunto, fechaVencimiento: fechaVencimiento, clave: clave));
    } on ApiException catch (e) {
      if (!e.esDeConexion) rethrow;
      final p = await encolarEscritura(
        _ref,
        metodo: 'POST',
        ruta: '/tareas-outlook',
        cuerpo: {'asunto': asunto.trim(), 'fecha_vencimiento': ?fechaVencimiento},
        clave: clave,
        entidad: 'tarea-nueva:$clave',
        tipo: 'tarea.crear',
        descripcion: asunto.trim(),
        localId: 'local:$clave',
      );
      return ResultadoAccion.encolada(TareaOutlook.fromJson({
        'id': idProvisional(p), 'asunto': asunto.trim(), 'estado': 'no_iniciada', 'prioridad': 'normal', 'fecha_vencimiento': fechaVencimiento, 'version': 0,
      }));
    }
  }

  Future<ResultadoAccion<TareaOutlook>> transicionar(TareaOutlook t, EstadoTarea estado, {String? motivo}) async {
    final clave = _uuid.v4();
    try {
      return ResultadoAccion.enviada(await _repo.transicionar(t.id, estado, motivo: motivo, version: t.version, clave: clave));
    } on ApiException catch (e) {
      if (!e.esDeConexion) rethrow;
      await encolarEscritura(
        _ref,
        metodo: 'POST',
        ruta: '/tareas-outlook/${t.id}/transiciones',
        cuerpo: {'estado': estado.valor, 'motivo': ?motivo, 'version': ?t.version},
        clave: clave,
        entidad: 'tarea:${t.id}',
        tipo: 'tarea.estado',
        descripcion: '${estado == EstadoTarea.completada ? '✓ ' : ''}${t.asunto ?? ''}',
      );
      return ResultadoAccion.encolada(t.copyWith(estado: estado.valor, motivoBloqueo: motivo));
    }
  }

  /// `true` si quedó en la cola.
  Future<bool> comentar(int tareaId, String asuntoTarea, String texto) async {
    final clave = _uuid.v4();
    try {
      await _repo.comentar(tareaId, texto, clave: clave);
      return false;
    } on ApiException catch (e) {
      if (!e.esDeConexion) rethrow;
      await encolarEscritura(
        _ref,
        metodo: 'POST',
        ruta: '/tareas-outlook/$tareaId/comentarios',
        cuerpo: {'texto': texto.trim()},
        clave: clave,
        entidad: 'tarea:$tareaId',
        tipo: 'tarea.comentario',
        descripcion: '$asuntoTarea: ${texto.trim()}',
      );
      return true;
    }
  }
}

final accionesTareasProvider = Provider<AccionesTareas>((ref) => AccionesTareas(ref));
