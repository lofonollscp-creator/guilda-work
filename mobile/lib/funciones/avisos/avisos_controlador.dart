import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/generado/modelos.g.dart';
import '../../nucleo/servicios.dart';
import '../../nucleo/sesion.dart';

/// La bandeja de avisos (`GET /notificaciones`): lo mismo que llega por push, pero
/// guardado en el servidor para verlo cuando se quiera. Se rehace al cambiar de despacho.
class AvisosControlador extends AsyncNotifier<NotificacionesRespuesta> {
  @override
  Future<NotificacionesRespuesta> build() {
    ref.watch(estadoSesionProvider.select((e) => e.despacho));
    return _pedir();
  }

  Future<NotificacionesRespuesta> _pedir() async {
    final crudo = await ref.read(clienteApiProvider).enviar('GET', '/notificaciones', consulta: {'limit': 50});
    return NotificacionesRespuesta.fromJson(crudo as Map<String, dynamic>);
  }

  Future<void> refrescar() async {
    final anterior = state.value;
    try {
      state = AsyncData(await _pedir());
    } catch (e, st) {
      if (anterior == null) state = AsyncError(e, st);
    }
  }

  /// Marca todos como leídos (el servidor solo ofrece «todos»); la lista se actualiza sin esperar.
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

  /// Quita un aviso de la lista y lo borra en el servidor; si falla, vuelve a pedir la lista.
  Future<void> eliminar(int id) async {
    final actual = state.value;
    if (actual != null) {
      final resto = [for (final n in actual.notificaciones ?? const <Notificacion>[]) if (n.id != id) n];
      final habia = (actual.notificaciones ?? const <Notificacion>[]).where((n) => n.id == id && n.leidoEn == null).length;
      state = AsyncData(NotificacionesRespuesta(noLeidas: ((actual.noLeidas ?? 0) - habia).clamp(0, 1 << 30), notificaciones: resto));
    }
    try {
      await ref.read(clienteApiProvider).enviar('DELETE', '/notificaciones/$id');
    } catch (_) {
      await refrescar();
    }
  }
}

final avisosProvider = AsyncNotifierProvider<AvisosControlador, NotificacionesRespuesta>(AvisosControlador.new);

/// Cuántos avisos sin leer hay (0 mientras carga o si falla): para la insignia de la campana.
final avisosNoLeidosProvider = Provider<int>((ref) => ref.watch(avisosProvider).value?.noLeidas ?? 0);
