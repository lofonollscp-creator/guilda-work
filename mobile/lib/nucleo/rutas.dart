import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../services/api_client.dart' show Usuario;
import 'actualizar_screen.dart';
import 'arranque_screen.dart';
import 'paginas.dart';
import 'sesion.dart';
import 'shell.dart';

const rutaArranque = '/arranque';
const rutaLogin = '/login';
const rutaActualizar = '/actualizar';
const rutaInicio = '/inicio';
const rutaTareas = '/tareas';
const rutaCorreo = '/correo';
const rutaFichaje = '/fichaje';
const rutaMas = '/mas';

/// A dónde debe estar la app según la sesión (null = donde está). Es una
/// función pura para poder probarla sin widgets.
///
/// Una versión no admitida (`actualizar`) gana a todo: no tiene sentido pedir
/// login a una app que el servidor ya no acepta.
String? redirigir(EstadoSesion e, String ubicacion) {
  if (e.actualizar) return ubicacion == rutaActualizar ? null : rutaActualizar;
  switch (e.fase) {
    case FaseSesion.arrancando:
      return ubicacion == rutaArranque ? null : rutaArranque;
    case FaseSesion.sinSesion:
      return ubicacion == rutaLogin ? null : rutaLogin;
    case FaseSesion.conSesion:
      const deSalida = {rutaArranque, rutaLogin, rutaActualizar};
      return deSalida.contains(ubicacion) ? rutaInicio : null;
  }
}

/// El enrutador. Se **rehace al cambiar de despacho**: así todas las pantallas
/// (también las empujadas con `Navigator.push`) se descartan y vuelven a
/// cargar desde cero, sin datos del despacho anterior (riesgo R11 del plan).
final routerProvider = Provider<GoRouter>((ref) {
  ref.watch(estadoSesionProvider.select((e) => e.despacho));
  final refresco = ValueNotifier<int>(0);
  ref.listen(estadoSesionProvider, (_, _) => refresco.value++);
  final paginas = ref.read(paginasProvider);

  Usuario usuario() => ref.read(estadoSesionProvider).usuario!;

  return GoRouter(
    initialLocation: rutaInicio,
    refreshListenable: refresco,
    redirect: (context, state) => redirigir(ref.read(estadoSesionProvider), state.matchedLocation),
    routes: [
      GoRoute(path: rutaArranque, builder: (_, _) => const ArranqueScreen()),
      GoRoute(path: rutaLogin, builder: (_, _) => Consumer(builder: (_, ref, _) => paginas.login(ref))),
      GoRoute(path: rutaActualizar, builder: (_, _) => const ActualizarScreen()),
      StatefulShellRoute.indexedStack(
        builder: (_, _, shell) => ShellApp(shell: shell),
        branches: [
          StatefulShellBranch(routes: [
            GoRoute(path: rutaInicio, builder: (_, _) => Consumer(builder: (_, ref, _) => paginas.inicio(ref, usuario()))),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: rutaTareas, builder: (_, _) => Consumer(builder: (_, ref, _) => paginas.tareas(ref))),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: rutaCorreo, builder: (_, _) => Consumer(builder: (_, ref, _) => paginas.correo(ref))),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: rutaFichaje, builder: (_, _) => Consumer(builder: (_, ref, _) => paginas.fichaje(ref, usuario()))),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: rutaMas, builder: (_, _) => const MasScreen()),
          ]),
        ],
      ),
    ],
  );
});
