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
