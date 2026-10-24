import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../screens/ajustes_screen.dart';
import '../screens/correo_bandeja_screen.dart';
import '../screens/dashboard_screen.dart';
import '../screens/fichaje_screen.dart';
import '../screens/fiscal_screen.dart';
import '../screens/herramientas_screen.dart';
import '../screens/ia_chat_screen.dart';
import '../screens/login_screen.dart';
import '../screens/tareas_outlook_screen.dart';
import '../screens/tiquets_screen.dart';
import '../services/api_client.dart';
import '../services/element_launcher.dart';
import 'servicios.dart';
import 'sesion.dart';

/// Las pantallas que el enrutador monta. Es el **adaptador de las pantallas
/// antiguas** (ADR M2/§4.3 del plan): cada una recibe `api`, `sync`, `usuario`...
/// por constructor como siempre, sacado ahora de Riverpod. Las pruebas lo
/// sobrescriben con pantallas de mentira (las reales hacen red).
class PaginasApp {
  final Widget Function(WidgetRef ref) login;
  final Widget Function(WidgetRef ref, Usuario usuario) inicio;
  final Widget Function(WidgetRef ref) tareas;
  final Widget Function(WidgetRef ref) correo;
  final Widget Function(WidgetRef ref, Usuario usuario) fichaje;

  /// Las pantallas que cuelgan de «Más»: (icono, clave de etiqueta, construir).
  final List<AccesoMas> Function(WidgetRef ref, Usuario usuario) accesosMas;

  const PaginasApp({
    required this.login,
    required this.inicio,
    required this.tareas,
    required this.correo,
    required this.fichaje,
    required this.accesosMas,
  });

  factory PaginasApp.reales() => PaginasApp(
        login: (ref) {
          final s = ref.read(serviciosProvider);
          return LoginScreen(
            api: s.api,
            sesion: s.sesion,
            sync: s.sync,
            push: s.push,
            tema: s.tema,
            locale: s.locale,
            alIniciarSesion: (u) => ref.read(estadoSesionProvider.notifier).iniciada(u),
          );
        },
        inicio: (ref, usuario) {
          final s = ref.read(serviciosProvider);
          return DashboardScreen(
            usuario: usuario,
            api: s.api,
            sesion: s.sesion,
            sync: s.sync,
            push: s.push,
            tema: s.tema,
            locale: s.locale,
            alCerrarSesion: () => ref.read(estadoSesionProvider.notifier).cerrar(),
          );
        },
        tareas: (ref) => TareasOutlookScreen(api: ref.read(serviciosProvider).api),
        correo: (ref) => CorreoBandejaScreen(api: ref.read(serviciosProvider).api),
        fichaje: (ref, usuario) {
          final s = ref.read(serviciosProvider);
          return FichajeScreen(api: s.api, sync: s.sync, usuario: usuario);
        },
        accesosMas: (ref, usuario) {
          final s = ref.read(serviciosProvider);
          return [
            AccesoMas(Icons.apps, ClaveEtiqueta.herramientas, (_) => HerramientasScreen(api: s.api)),
            AccesoMas(Icons.confirmation_number_outlined, ClaveEtiqueta.tiquets, (_) => TiquetsScreen(api: s.api, usuario: usuario)),
            AccesoMas(Icons.smart_toy_outlined, ClaveEtiqueta.asistenteIa, (_) => IaChatScreen(api: s.api, locale: s.locale)),
            AccesoMas(Icons.chat_bubble_outline, ClaveEtiqueta.chat, null, alPulsar: abrirElementX),
            if (usuario.tenantId != null) AccesoMas(Icons.calendar_month_outlined, ClaveEtiqueta.fiscal, (_) => FiscalScreen(api: s.api)),
            AccesoMas(
              Icons.settings_outlined,
              ClaveEtiqueta.ajustes,
              (_) => AjustesScreen(
                api: s.api,
                usuario: usuario,
                sesion: s.sesion,
                sync: s.sync,
                push: s.push,
                tema: s.tema,
                locale: s.locale,
                alCerrarSesion: () => ref.read(estadoSesionProvider.notifier).cerrar(),
              ),
            ),
          ];
        },
      );
}

enum ClaveEtiqueta { herramientas, tiquets, asistenteIa, chat, fiscal, ajustes }

class AccesoMas {
  final IconData icono;
  final ClaveEtiqueta etiqueta;

  /// Pantalla a abrir (empujada sobre la actual)...
  final Widget Function(BuildContext)? construir;

  /// ...o una acción propia (p. ej. lanzar otra app).
  final VoidCallback? alPulsar;
  const AccesoMas(this.icono, this.etiqueta, this.construir, {this.alPulsar});
}

final paginasProvider = Provider<PaginasApp>((ref) => PaginasApp.reales());
