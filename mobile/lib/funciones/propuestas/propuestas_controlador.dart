import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/generado/modelos.g.dart';
import '../../nucleo/servicios.dart';
import '../../nucleo/sesion.dart';

/// Algo que el asistente (o una regla del sistema) **propone** y una persona aprueba o rechaza: nada se ejecuta solo.
/// `tipo` dice qué haría al aprobar: `tarea` crea una tarea; `peticion_portal`, `mensaje_portal` y `cuenta_tercero` actúan hacia un cliente.
class PropuestaIa {
  final int id;
  final String tipo;
  final String origen;
  final String titulo;
  final String detalle;
  final String prioridad;
  const PropuestaIa({required this.id, required this.tipo, required this.origen, required this.titulo, required this.detalle, required this.prioridad});

  factory PropuestaIa.desdeJson(Map<String, dynamic> j) => PropuestaIa(
        id: (j['id'] as num).toInt(),
        tipo: '${j['tipo'] ?? ''}',
        origen: '${j['origen'] ?? ''}',
        titulo: '${j['titulo'] ?? ''}',
        detalle: '${j['detalle'] ?? ''}',
        prioridad: '${j['prioridad'] ?? 'normal'}',
      );

  bool get urgente => prioridad == 'alta';

  /// Solo crear una tarea se queda dentro del despacho; lo demás sale hacia un cliente y se confirma antes de aprobar.
  bool get actuaFuera => tipo != 'tarea';
}

/// La bandeja de propuestas pendientes del despacho activo (`GET /propuestas`), las urgentes primero. Se rehace al cambiar de despacho.
/// Aprobar y rechazar van al servidor y, si salen bien, la propuesta desaparece de la lista; si fallan, el error sube a la pantalla y la lista queda igual.
class PropuestasControlador extends AsyncNotifier<List<PropuestaIa>> {
  @override
  Future<List<PropuestaIa>> build() {
    ref.watch(estadoSesionProvider.select((e) => e.despacho));
    return _pedir();
  }

  Future<List<PropuestaIa>> _pedir() async {
    final crudo = await ref.read(clienteApiProvider).enviar('GET', '/propuestas');
    final lista = ListaPropuestas.fromJson(crudo as Map<String, dynamic>).propuestas ?? const [];
    return [for (final p in lista) PropuestaIa.desdeJson(p)];
  }

  Future<void> refrescar() async {
    try {
      state = AsyncData(await _pedir());
    } catch (e, st) {
      state = state.value == null ? AsyncError(e, st) : state;
    }
  }

  /// Aprueba: el servidor la ejecuta como tú (p. ej. crea la tarea). Devuelve lo que hizo (`tarea:12`).
  Future<String?> aprobar(PropuestaIa p) => _resolver(p, 'aprobar');

  /// Rechaza: no vuelve a salir en 30 días.
  Future<void> rechazar(PropuestaIa p) => _resolver(p, 'rechazar');

  Future<String?> _resolver(PropuestaIa p, String accion) async {
    final crudo = await ref.read(clienteApiProvider).enviar('POST', '/propuestas/${p.id}/$accion');
    state = AsyncData([for (final x in state.value ?? const <PropuestaIa>[]) if (x.id != p.id) x]);
    return ResultadoPropuesta.fromJson(crudo as Map<String, dynamic>).resultado;
  }
}

final propuestasProvider = AsyncNotifierProvider<PropuestasControlador, List<PropuestaIa>>(PropuestasControlador.new);

/// Cuántas propuestas esperan (0 mientras carga o si no se pudo leer): para la insignia del ✦ y la tarjeta de Hoy.
final propuestasPendientesProvider = Provider<int>((ref) => ref.watch(propuestasProvider).value?.length ?? 0);
