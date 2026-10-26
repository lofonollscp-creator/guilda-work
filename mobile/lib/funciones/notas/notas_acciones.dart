import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../../api/errores.dart';
import '../../api/generado/modelos.g.dart';
import '../../datos/cola.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/servicios.dart';
import 'notas_lista_controlador.dart';
import 'notas_repositorio.dart';

/// La nota rápida que **no se pierde sin red**: se intenta al momento y, si falla la conexión, queda en la cola con su hora de creación y con la
/// misma clave del primer intento (no se duplica). Devuelve `true` si quedó en la cola.
class AccionesNotas {
  final Ref _ref;
  final Uuid _uuid = const Uuid();
  AccionesNotas(this._ref);

  Future<bool> crear(String texto, {int? categoriaId, DateTime? ahora}) async => (await crearNota(texto, categoriaId: categoriaId, ahora: ahora)).encolada;

  /// Como [crear], con título y devolviendo la nota creada (`encolada`: quedó en la cola y aún no existe en el servidor).
  Future<({Nota? nota, bool encolada})> crearNota(String texto, {String? titulo, int? categoriaId, DateTime? ahora}) async {
    final clave = _uuid.v4();
    final cuerpo = <String, dynamic>{'texto': texto.trim(), 'titulo': ?((titulo ?? '').trim().isEmpty ? null : titulo!.trim()), 'categoria_id': ?categoriaId, 'cliente_uuid': clave};
    try {
      final r = await _ref.read(clienteApiProvider).conClave(clave).enviar('POST', '/notas', cuerpo: cuerpo);
      return (nota: r is Map<String, dynamic> ? Nota.fromJson(r) : null, encolada: false);
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
        descripcion: (titulo ?? '').trim().isNotEmpty ? titulo!.trim() : texto.trim(),
      );
      return (nota: null, encolada: true);
    }
  }
}

final accionesNotasProvider = Provider<AccionesNotas>((ref) => AccionesNotas(ref));

/// Borra una nota (a la papelera) y avisa con «Deshacer» durante 6 s. Los avisos cuelgan del mensajero de la app, así que siguen aunque la pantalla se cierre.
/// Devuelve si se borró.
Future<bool> eliminarNotaConDeshacer(BuildContext context, WidgetRef ref, Nota nota) async {
  final t = AppLocalizations.of(context);
  final mensajero = ScaffoldMessenger.of(context);
  final repo = ref.read(notasRepositorioProvider);
  final lista = ref.read(notasListaProvider.notifier);
  try {
    await repo.eliminar(nota.id);
  } on ApiException catch (e) {
    mensajero.showSnackBar(SnackBar(content: Text(e.mensaje)));
    return false;
  }
  lista.quitar(nota.id);
  mensajero
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(
      content: Text(t.notasEliminada),
      duration: const Duration(seconds: 6),
      action: SnackBarAction(
        label: t.comunDeshacer,
        onPressed: () async {
          try {
            await repo.restaurar(nota.id);
            lista.recargar();
            mensajero
              ..hideCurrentSnackBar()
              ..showSnackBar(SnackBar(content: Text(t.notasRestaurada)));
          } on ApiException catch (e) {
            mensajero.showSnackBar(SnackBar(content: Text(e.mensaje)));
          }
        },
      ),
    ));
  return true;
}
