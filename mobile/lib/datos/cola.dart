import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../nucleo/servicios.dart';
import '../nucleo/sesion.dart';
import 'cola_procesador.dart';
import 'local/cola_escritura.dart';

/// Se incrementa con cada cambio de la cola: lo que dependa de ella (contadores, la hoja de pendientes) se rehace.
class ColaCambios extends Notifier<int> {
  @override
  int build() => 0;
  void avisar() => state++;
}

final colaCambiosProvider = NotifierProvider<ColaCambios, int>(ColaCambios.new);

/// Se incrementa cuando una pasada envió algo al servidor: las listas se recargan para enseñar lo real.
class ColaEnviada extends Notifier<int> {
  @override
  int build() => 0;
  void avisar() => state++;
}

final colaEnviadaProvider = NotifierProvider<ColaEnviada, int>(ColaEnviada.new);

final colaEscrituraProvider = Provider<ColaEscritura>((ref) => ColaEscritura(alCambiar: () => ref.read(colaCambiosProvider.notifier).avisar()));

final procesadorColaProvider = Provider<ProcesadorCola>((ref) {
  final cliente = ref.read(clienteApiProvider);
  return ProcesadorCola(
    cola: ref.read(colaEscrituraProvider),
    usuarioActivo: () => ref.read(estadoSesionProvider).usuario?.id,
    despachoActivo: () => ref.read(estadoSesionProvider).despacho ?? _sinDespacho,
    enviar: (p) => cliente.enviarConClave(p.metodo, p.ruta, cuerpo: p.cuerpoMapa, claveIdempotencia: p.clave),
    alTerminar: (_) => ref.read(colaEnviadaProvider.notifier).avisar(),
  );
});

/// Quien tiene un solo despacho (o el servidor aún no informa de ellos) no manda `X-Despacho`: sus acciones se guardan con esta marca.
const _sinDespacho = '0';

String despachoDeLaCola(String? despachoActivo) => despachoActivo ?? _sinDespacho;

/// Las pendientes de la persona y el despacho activos (se rehace con cada cambio de la cola).
final pendientesProvider = FutureProvider<List<Pendiente>>((ref) async {
  ref.watch(colaCambiosProvider);
  final e = ref.watch(estadoSesionProvider);
  if (e.usuario == null) return const [];
  return ref.read(colaEscrituraProvider).de(e.usuario!.id, despachoDeLaCola(e.despacho));
});

/// Cuántas acciones sin enviar hay (0 mientras carga).
final numPendientesProvider = Provider<int>((ref) => ref.watch(pendientesProvider).value?.length ?? 0);

/// Cuántos fichajes hay sin enviar.
final numFichajesPendientesProvider = Provider<int>((ref) => ref.watch(pendientesProvider).value?.where((p) => p.tipo == 'fichaje.marca').length ?? 0);

/// Guarda una escritura en la cola con la persona y el despacho activos. Lanza [ColaLlena] si no cabe.
Future<Pendiente> encolarEscritura(
  Ref ref, {
  required String metodo,
  required String ruta,
  Map<String, dynamic>? cuerpo,
  required String clave,
  required String entidad,
  required String tipo,
  required String descripcion,
  String? localId,
}) {
  final e = ref.read(estadoSesionProvider);
  return ref.read(colaEscrituraProvider).encolar(
        metodo: metodo,
        ruta: ruta,
        cuerpo: cuerpo,
        clave: clave,
        usuarioId: e.usuario!.id,
        despachoId: despachoDeLaCola(e.despacho),
        entidad: entidad,
        tipo: tipo,
        descripcion: descripcion,
        localId: localId,
      );
}
