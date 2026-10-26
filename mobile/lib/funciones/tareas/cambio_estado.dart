import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errores.dart';
import '../../api/generado/modelos.g.dart';
import '../../datos/local/cola_escritura.dart' show ColaLlena;
import '../../dominio/tarea.dart';
import '../../l10n/app_localizations.dart';
import 'tareas_acciones.dart';
import 'textos.dart';

/// Cambia el estado de una tarea desde «Mi día» o el tablero, con el aviso «… · Deshacer» de siempre. Sin conexión se guarda en la cola.
/// [alCambiar] recibe la tarea ya cambiada (o, al deshacer, la de antes) para que la pantalla la ponga donde toca.
/// Devuelve si se pudo (los errores de negocio —tarea bloqueada, sin permiso…— se enseñan tal cual y devuelven false).
Future<bool> cambiarEstadoConAviso(
  BuildContext context,
  WidgetRef ref,
  TareaOutlook tarea,
  EstadoTarea nuevo, {
  required void Function(TareaOutlook) alCambiar,
  String? motivo,
}) async {
  final t = AppLocalizations.of(context);
  final mensajero = ScaffoldMessenger.of(context);
  final anterior = EstadoTarea.desde(tarea.estado);
  try {
    final r = await ref.read(accionesTareasProvider).transicionar(tarea, nuevo, motivo: motivo);
    alCambiar(r.valor!);
    mensajero.hideCurrentSnackBar();
    mensajero.showSnackBar(SnackBar(
      content: Text(r.encolada ? t.colaGuardada : (nuevo == EstadoTarea.completada ? t.tareaCompletadaAviso : t.tareaMovidaA(etiquetaEstado(t, nuevo)))),
      duration: const Duration(seconds: 6),
      // Volver a un estado que pedía motivo (esperando) no se ofrece: hace falta el motivo.
      action: anterior.pideMotivo || anterior == EstadoTarea.desconocido
          ? null
          : SnackBarAction(
              label: t.comunDeshacer,
              onPressed: () async {
                try {
                  final v = await ref.read(accionesTareasProvider).transicionar(r.valor!, anterior);
                  alCambiar(v.valor!);
                  mensajero.hideCurrentSnackBar();
                  mensajero.showSnackBar(SnackBar(content: Text(t.tareaDeshechaAviso)));
                } on ApiException catch (e) {
                  mensajero.showSnackBar(SnackBar(content: Text(e.categoria == CategoriaError.conflicto ? t.tareaNoSePudoDeshacer : e.mensaje)));
                } on ColaLlena {
                  mensajero.showSnackBar(SnackBar(content: Text(t.colaLlena)));
                }
              },
            ),
    ));
    return true;
  } on ColaLlena {
    mensajero.showSnackBar(SnackBar(content: Text(t.colaLlena)));
  } on ApiException catch (e) {
    mensajero.showSnackBar(SnackBar(content: Text(e.mensaje)));
  }
  return false;
}
