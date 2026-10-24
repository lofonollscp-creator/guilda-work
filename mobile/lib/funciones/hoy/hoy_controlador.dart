import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/generado/modelos.g.dart';
import '../../nucleo/servicios.dart';
import '../../nucleo/sesion.dart';

/// Lo que enseña «Hoy»: la bandeja, cuándo se obtuvo (hora local del móvil) y si el
/// último refresco falló (entonces son datos de antes y la pantalla lo avisa).
class EstadoHoy {
  final BandejaHoy bandeja;
  final DateTime obtenidoEn;
  final bool desactualizado;
  const EstadoHoy(this.bandeja, this.obtenidoEn, {this.desactualizado = false});
}

/// La bandeja de «Hoy»: `GET /hoy` en **una** llamada (las pantallas con muchas
/// peticiones al abrirse rozan el límite de la API). Se rehace sola al cambiar
/// de despacho. Si un refresco falla y ya había datos, se conservan; solo se
/// muestra el error si no hay nada que enseñar.
class HoyControlador extends AsyncNotifier<EstadoHoy> {
  @override
  Future<EstadoHoy> build() {
    ref.watch(estadoSesionProvider.select((e) => e.despacho));
    return _pedir();
  }

  Future<EstadoHoy> _pedir() async {
    final crudo = await ref.read(clienteApiProvider).enviar('GET', '/hoy');
    return EstadoHoy(BandejaHoy.fromJson(crudo as Map<String, dynamic>), DateTime.now());
  }

  /// Pull-to-refresh o reintento.
  Future<void> refrescar() async {
    final anterior = state.value;
    try {
      state = AsyncData(await _pedir());
    } catch (e, st) {
      state = anterior == null ? AsyncError(e, st) : AsyncData(EstadoHoy(anterior.bandeja, anterior.obtenidoEn, desactualizado: true));
    }
  }
}

final hoyProvider = AsyncNotifierProvider<HoyControlador, EstadoHoy>(HoyControlador.new);
