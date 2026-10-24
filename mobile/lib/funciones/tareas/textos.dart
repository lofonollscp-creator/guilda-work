import '../../api/fechas.dart';
import '../../dominio/tarea.dart';
import '../../l10n/app_localizations.dart';

String etiquetaEstado(AppLocalizations t, EstadoTarea e) => switch (e) {
      EstadoTarea.noIniciada => t.estadoNoIniciada,
      EstadoTarea.enProgreso => t.estadoEnProgreso,
      EstadoTarea.esperando => t.estadoEsperando,
      EstadoTarea.aplazada => t.estadoAplazada,
      EstadoTarea.enRevision => t.estadoEnRevision,
      EstadoTarea.completada => t.estadoCompletada,
      EstadoTarea.desconocido => '',
    };

String etiquetaPrioridad(AppLocalizations t, PrioridadTarea p) => switch (p) {
      PrioridadTarea.baja => t.prioridadBaja,
      PrioridadTarea.normal => t.prioridadNormal,
      PrioridadTarea.alta => t.prioridadAlta,
    };

/// «24/10» (o «24/10/2027» si no es de este año): sin zonas horarias, que el servidor manda fechas locales.
String formatoFechaCorta(Fecha f, {int? anioActual}) {
  final dd = f.dia.toString().padLeft(2, '0'), mm = f.mes.toString().padLeft(2, '0');
  return f.anio == (anioActual ?? DateTime.now().year) ? '$dd/$mm' : '$dd/$mm/${f.anio}';
}
