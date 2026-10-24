import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../../api/errores.dart';
import '../../datos/cola.dart';
import '../../nucleo/servicios.dart';

/// La nota rápida que **no se pierde sin red**: se intenta al momento y, si falla la conexión, queda en la cola con su hora de creación y con la
/// misma clave del primer intento (no se duplica). Devuelve `true` si quedó en la cola.
class AccionesNotas {
  final Ref _ref;
  final Uuid _uuid = const Uuid();
  AccionesNotas(this._ref);

  Future<bool> crear(String texto, {int? categoriaId, DateTime? ahora}) async {
    final clave = _uuid.v4();
    final cuerpo = <String, dynamic>{'texto': texto.trim(), 'categoria_id': ?categoriaId, 'cliente_uuid': clave};
    try {
      await _ref.read(clienteApiProvider).conClave(clave).enviar('POST', '/notas', cuerpo: cuerpo);
      return false;
    } on ApiException catch (e) {
      if (!e.esDeConexion) rethrow;
      final cuando = ahora ?? DateTime.now();
      await encolarEscritura(
        _ref,
        metodo: 'POST',
        ruta: '/notas',
        cuerpo: {...cuerpo, 'creada_en': cuando.toIso8601String()},
        clave: clave,
        entidad: 'nota-nueva:$clave', // cada nota es independiente: no esperan unas a otras
        tipo: 'nota.crear',
        descripcion: texto.trim(),
      );
      return true;
    }
  }
}

final accionesNotasProvider = Provider<AccionesNotas>((ref) => AccionesNotas(ref));
