import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:uuid/uuid.dart';

import '../../api/errores.dart';
import '../../datos/cola.dart';
import '../../datos/cola_procesador.dart';
import '../../nucleo/servicios.dart';
import '../tareas/tareas_acciones.dart' show ResultadoAccion;

/// Fichar que **no se pierde sin red**. Se intenta al momento; si falla la conexión se guarda en la cola con la hora real de la pulsación
/// (el servidor registra esa, no la de cuando llegue) y con la misma clave del primer intento, para que no se duplique si aquel sí llegó.
/// Los fichajes salen estrictamente en el orden en que se pulsaron: el servidor valida la secuencia entrada → pausa → salida por orden de llegada.
class AccionesFichaje {
  final Ref _ref;
  final Uuid _uuid = const Uuid();
  AccionesFichaje(this._ref);

  /// `tipo`: `entrada`, `pausa_inicio`, `pausa_fin` o `salida`. Devuelve el estado resultante si se envió; si quedó en la cola, [ResultadoAccion.encolada].
  Future<ResultadoAccion<String>> marcar(String tipo, {double? latitud, double? longitud, DateTime? ahora}) async {
    final clave = _uuid.v4();
    final cuerpo = <String, dynamic>{'tipo': tipo, 'cliente_uuid': clave, 'latitud': ?latitud, 'longitud': ?longitud};
    try {
      final r = await _ref.read(clienteApiProvider).conClave(clave).enviar('POST', '/fichaje/marcar', cuerpo: cuerpo);
      return ResultadoAccion.enviada((r as Map<String, dynamic>)['estado'] as String);
    } on ApiException catch (e) {
      if (!e.esDeConexion) rethrow;
      final cuando = ahora ?? DateTime.now();
      await encolarEscritura(
        _ref,
        metodo: 'POST',
        ruta: '/fichaje/marcar',
        cuerpo: {...cuerpo, 'marca_tiempo': cuando.toIso8601String()},
        clave: clave,
        entidad: ProcesadorCola.entidadFichaje,
        tipo: 'fichaje.marca',
        descripcion: '$tipo ${cuando.hour.toString().padLeft(2, '0')}:${cuando.minute.toString().padLeft(2, '0')}',
      );
      return const ResultadoAccion.encolada();
    }
  }
}

final accionesFichajeProvider = Provider<AccionesFichaje>((ref) => AccionesFichaje(ref));

/// Ubicación opcional (Fase G3): solo se pide si el despacho la tiene activada [activa]; nunca bloquea fichar. Si el permiso se deniega, tarda
/// o falla por lo que sea, se sigue sin coordenadas (mismo criterio que la web). Es la misma para la pantalla de Fichaje y la tarjeta de Hoy.
Future<(double?, double?)> ubicacionOpcionalFichaje({required bool activa}) async {
  if (!activa) return (null, null);
  try {
    if (!await Geolocator.isLocationServiceEnabled()) return (null, null);
    var permiso = await Geolocator.checkPermission();
    if (permiso == LocationPermission.denied) permiso = await Geolocator.requestPermission();
    if (permiso == LocationPermission.denied || permiso == LocationPermission.deniedForever) return (null, null);
    final posicion = await Geolocator.getCurrentPosition(locationSettings: const LocationSettings(accuracy: LocationAccuracy.medium)).timeout(const Duration(seconds: 3));
    return (posicion.latitude, posicion.longitude);
  } catch (_) {
    return (null, null);
  }
}
