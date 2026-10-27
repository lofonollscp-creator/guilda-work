import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/generado/modelos.g.dart';
import '../../nucleo/servicios.dart';
import '../../nucleo/sesion.dart';

/// La bandeja de avisos (`GET /notificaciones`): lo mismo que llega por push, pero
/// guardado en el servidor para verlo cuando se quiera. Se rehace al cambiar de despacho.
class AvisosControlador extends AsyncNotifier<NotificacionesRespuesta> {
  /// Avisos que se acaban de quitar con «Deshacer» a la vista: el borrado en el servidor espera a que se acabe el plazo.
  final Map<int, Timer> _borrados = {};
  static const plazoDeshacer = Duration(seconds: 6);

  @override
  Future<NotificacionesRespuesta> build() {
    ref.watch(estadoSesionProvider.select((e) => e.despacho));
    ref.onDispose(() {
      // Al salir de la bandeja no se pierde lo que se quitó: se borra ya.
      for (final id in _borrados.keys.toList()) {
        _confirmarBorrado(id);
      }
    });
    return _pedir();
  }

  Future<NotificacionesRespuesta> _pedir() async {
    final crudo = await ref.read(clienteApiProvider).enviar('GET', '/notificaciones', consulta: {'limit': 50});
    final r = NotificacionesRespuesta.fromJson(crudo as Map<String, dynamic>);
    if (_borrados.isEmpty) return r;
    return _sin(r, _borrados.keys.toSet());
  }

  NotificacionesRespuesta _sin(NotificacionesRespuesta r, Set<int> ids) {
    final lista = r.notificaciones ?? const <Notificacion>[];
    final quitadasSinLeer = lista.where((n) => ids.contains(n.id) && n.leidoEn == null).length;
    return NotificacionesRespuesta(noLeidas: ((r.noLeidas ?? 0) - quitadasSinLeer).clamp(0, 1 << 30), notificaciones: [for (final n in lista) if (!ids.contains(n.id)) n]);
  }

  Future<void> refrescar() async {
    final anterior = state.value;
    try {
      state = AsyncData(await _pedir());
    } catch (e, st) {
      if (anterior == null) state = AsyncError(e, st);
    }
  }

  /// Marca todos como leídos; la lista se actualiza sin esperar.
  Future<void> marcarTodosLeidos() async {
    final actual = state.value;
    if (actual != null) {
      state = AsyncData(NotificacionesRespuesta(
        noLeidas: 0,
        notificaciones: [for (final n in actual.notificaciones ?? const <Notificacion>[]) n.leidoEn == null ? n.copyWith(leidoEn: DateTime.now().toIso8601String()) : n],
      ));
    }
    try {
      await ref.read(clienteApiProvider).enviar('POST', '/notificaciones/leidas');
    } catch (_) {
      await refrescar();
    }
  }

  /// Marca uno como leído (al abrirlo); sin esperar al servidor.
  Future<void> marcarLeido(int id) async {
    final actual = state.value;
    if (actual == null) return;
    final lista = actual.notificaciones ?? const <Notificacion>[];
    if (!lista.any((n) => n.id == id && n.leidoEn == null)) return;
    state = AsyncData(NotificacionesRespuesta(
      noLeidas: ((actual.noLeidas ?? 0) - 1).clamp(0, 1 << 30),
      notificaciones: [for (final n in lista) n.id == id ? n.copyWith(leidoEn: DateTime.now().toIso8601String()) : n],
    ));
    try {
      await ref.read(clienteApiProvider).enviar('POST', '/notificaciones/$id/leida');
    } catch (_) {
      // sin red se queda como leído aquí y se rehace al volver a pedir la lista
    }
  }

  /// Quita un aviso de la lista. Se borra en el servidor al pasar el plazo de «Deshacer» (o al salir de la bandeja).
  void eliminar(int id) {
    final actual = state.value;
    if (actual != null) state = AsyncData(_sin(actual, {id}));
    _borrados[id]?.cancel();
    _borrados[id] = Timer(plazoDeshacer, () => _confirmarBorrado(id));
  }

  /// «Deshacer»: si aún no se había borrado en el servidor, el aviso vuelve a su sitio.
  Future<void> deshacerEliminar(int id) async {
    final t = _borrados.remove(id);
    if (t == null) return;
    t.cancel();
    await refrescar();
  }

  void _confirmarBorrado(int id) {
    final t = _borrados.remove(id);
    if (t == null) return;
    t.cancel();
    unawaited(() async {
      try {
        await ref.read(clienteApiProvider).enviar('DELETE', '/notificaciones/$id');
      } catch (_) {
        await refrescar();
      }
    }());
  }
}

final avisosProvider = AsyncNotifierProvider<AvisosControlador, NotificacionesRespuesta>(AvisosControlador.new);

/// Cuántos avisos sin leer hay (0 mientras carga o si falla): para la insignia de la campana.
final avisosNoLeidosProvider = Provider<int>((ref) => ref.watch(avisosProvider).value?.noLeidas ?? 0);
