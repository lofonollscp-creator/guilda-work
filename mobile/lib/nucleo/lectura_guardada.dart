import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../datos/local/cache_lectura.dart';
import '../diseno/componentes.dart';
import '../diseno/formatos.dart';
import '../l10n/app_localizations.dart';

/// La caché de lectura sin conexión (SQLite). Se sobrescribe en las pruebas.
final cacheLecturaProvider = Provider<CacheLectura>((ref) => CacheLectura());

/// Qué consultas se están enseñando desde la caché (ruta → cuándo se guardaron) porque no hay red. Se quita cada una en cuanto
/// vuelve a llegar de verdad desde el servidor.
class LecturasGuardadas extends Notifier<Map<String, DateTime>> {
  @override
  Map<String, DateTime> build() => const {};

  void fijar(String ruta, DateTime? guardadaEn) {
    if (guardadaEn == null) {
      if (!state.containsKey(ruta)) return;
      state = {...state}..remove(ruta);
    } else {
      state = {...state, ruta: guardadaEn};
    }
  }

  void limpiar() => state = const {};
}

final lecturasGuardadasProvider = NotifierProvider<LecturasGuardadas, Map<String, DateTime>>(LecturasGuardadas.new);

/// Aviso «Sin conexión · datos de las 10:32» para las pantallas que enseñan lo guardado. No ocupa nada si todo viene del servidor.
/// `prefijo`: solo mira las consultas de esa parte de la API (p. ej. `/tareas-outlook`).
class AvisoDatosGuardados extends ConsumerWidget {
  final String prefijo;
  const AvisoDatosGuardados({super.key, required this.prefijo});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final desde = ref.watch(lecturasGuardadasProvider.select((m) {
      final fechas = [for (final e in m.entries) if (e.key.startsWith(prefijo)) e.value];
      if (fechas.isEmpty) return null;
      fechas.sort();
      return fechas.first; // la más antigua: lo que más puede haber cambiado
    }));
    if (desde == null) return const SizedBox.shrink();
    final t = AppLocalizations.of(context);
    return BannerEstado(tipo: TipoBanner.sinConexion, texto: t.hoySinConexionDatosDe(context.formatos.hora(desde.hour, desde.minute)));
  }
}
