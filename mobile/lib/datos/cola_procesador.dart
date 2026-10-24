import '../api/errores.dart';
import 'local/cola_escritura.dart';

/// Manda una escritura pendiente al servidor (con su misma `Idempotency-Key`) y devuelve la respuesta ya desempaquetada.
typedef EnviarPendiente = Future<dynamic> Function(Pendiente p);

class ResultadoProceso {
  final int enviadas;
  final int rechazadas;
  final int conflictos;

  /// Se cortó porque no hay red, la sesión caducó o la app necesita actualizarse.
  final String? motivoDeParada;
  const ResultadoProceso({this.enviadas = 0, this.rechazadas = 0, this.conflictos = 0, this.motivoDeParada});
}

/// Vacía la cola de escrituras: envía en orden lo que toca, con las reglas del plan (§13.1).
///
///  - Solo envía lo de la persona y el despacho activos; lo demás espera.
///  - FIFO dentro de una misma entidad (una tarea no recibe su comentario antes que su estado); entre entidades distintas no se espera.
///  - Red, `429` y `5xx`: se reintenta con espera exponencial (1 s → 5 min). Sin red se corta la pasada.
///  - Conflicto (`409`/`412`): se conserva la intención y espera la decisión de la persona.
///  - Regla de negocio (`4xx`): rechazada, no se reintenta.
///  - `401`, `423` o `426`: se corta (hay que volver a entrar, desbloquear o actualizar).
class ProcesadorCola {
  final ColaEscritura cola;
  final EnviarPendiente enviar;
  final int? Function() usuarioActivo;
  final String? Function() despachoActivo;
  final int Function() _ahoraMs;

  /// Tras una pasada que envió algo (para recargar listas).
  void Function(ResultadoProceso)? alTerminar;

  bool _corriendo = false;

  ProcesadorCola({required this.cola, required this.enviar, required this.usuarioActivo, required this.despachoActivo, int Function()? ahoraMs, this.alTerminar})
      : _ahoraMs = ahoraMs ?? (() => DateTime.now().millisecondsSinceEpoch);

  /// Espera antes del intento número [intentos]: 1 s, 2 s, 4 s... hasta 5 minutos.
  static Duration espera(int intentos) {
    final seg = 1 << (intentos.clamp(0, 9));
    return Duration(seconds: seg > 300 ? 300 : seg);
  }

  Future<ResultadoProceso> procesar() async {
    if (_corriendo) return const ResultadoProceso();
    final usuario = usuarioActivo(), despacho = despachoActivo();
    if (usuario == null || despacho == null) return const ResultadoProceso();
    _corriendo = true;
    var enviadas = 0, rechazadas = 0, conflictos = 0;
    String? parada;
    try {
      await cola.purgarCaducadas();
      await cola.reiniciarEnviando();
      final bloqueadas = <String>{};
      for (final previa in await cola.de(usuario, despacho)) {
        // Se vuelve a leer: lo anterior pudo cambiarla (un id local sustituido por el real) o la persona descartarla mientras tanto.
        final p = await cola.uno(previa.id);
        if (p == null) continue;
        if (bloqueadas.contains(p.entidad)) continue; // lo anterior de esa entidad aún no ha salido
        if (p.estado == EstadoPendiente.conflicto || p.estado == EstadoPendiente.rechazada) {
          bloqueadas.add(p.entidad);
          continue;
        }
        if (p.proximoIntentoMs > _ahoraMs()) {
          bloqueadas.add(p.entidad);
          continue;
        }
        await cola.marcar(p.id, estado: EstadoPendiente.enviando);
        try {
          final respuesta = await enviar(p);
          if (p.localId != null && respuesta is Map && respuesta['id'] != null) await cola.sustituirIdLocal(p.localId!, respuesta['id'] as Object);
          await cola.eliminar(p.id);
          enviadas++;
        } on ApiException catch (e) {
          final intentos = p.intentos + 1;
          switch (e.categoria) {
            case CategoriaError.red:
              await cola.marcar(p.id, estado: EstadoPendiente.pendiente, intentos: intentos, proximoIntentoMs: _ahoraMs() + espera(intentos).inMilliseconds);
              parada = 'sin_red';
            case CategoriaError.limite || CategoriaError.servidor:
              final pausa = e.retryAfter ?? espera(intentos);
              await cola.marcar(p.id, estado: EstadoPendiente.pendiente, intentos: intentos, proximoIntentoMs: _ahoraMs() + pausa.inMilliseconds, error: e.mensaje);
              bloqueadas.add(p.entidad);
            case CategoriaError.conflicto:
              await cola.marcar(p.id, estado: EstadoPendiente.conflicto, intentos: intentos, error: e.mensaje, versionActual: e.versionActual);
              bloqueadas.add(p.entidad);
              conflictos++;
            case CategoriaError.autenticacion:
              await cola.marcar(p.id, estado: EstadoPendiente.pendiente);
              parada = 'sesion';
            case CategoriaError.actualizar:
              await cola.marcar(p.id, estado: EstadoPendiente.pendiente);
              parada = 'actualizar';
            case CategoriaError.bloqueado:
              await cola.marcar(p.id, estado: EstadoPendiente.pendiente, intentos: intentos, proximoIntentoMs: _ahoraMs() + espera(9).inMilliseconds, error: e.mensaje);
              bloqueadas.add(p.entidad);
            default:
              await cola.marcar(p.id, estado: EstadoPendiente.rechazada, intentos: intentos, error: e.mensaje);
              bloqueadas.add(p.entidad);
              rechazadas++;
          }
          if (parada != null) break;
        } catch (e) {
          // Un fallo inesperado (no de la API) no puede dejar la acción en «enviando» para siempre.
          await cola.marcar(p.id, estado: EstadoPendiente.pendiente, intentos: p.intentos + 1, proximoIntentoMs: _ahoraMs() + espera(p.intentos + 1).inMilliseconds, error: '$e');
          bloqueadas.add(p.entidad);
        }
      }
    } finally {
      _corriendo = false;
    }
    final r = ResultadoProceso(enviadas: enviadas, rechazadas: rechazadas, conflictos: conflictos, motivoDeParada: parada);
    if (enviadas > 0) alTerminar?.call(r);
    return r;
  }
}
