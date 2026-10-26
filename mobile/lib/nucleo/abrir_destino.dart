import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/errores.dart';
import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../screens/ausencias_screen.dart';
import '../screens/correo_mensaje_screen.dart';
import '../screens/fiscal_vencimiento_edit_screen.dart';
import '../screens/ia_chat_screen.dart';
import '../funciones/notas/nota_screen.dart';
import '../funciones/notas/notas_screen.dart';
import '../funciones/tareas/tarea_detalle_screen.dart';
import '../screens/tiquets_screen.dart';
import 'avisos.dart';
import 'destinos.dart';
import 'rutas.dart';
import 'servicios.dart';
import 'sesion.dart';

/// Abre la pantalla de un destino (elemento de «Hoy», aviso o push). Usa el
/// navegador raíz del enrutador, así que sirve también sin un `BuildContext`
/// de pantalla (al tocar una notificación).
Future<void> abrirDestino(Ref ref, Destino destino, {String? urlWeb}) async {
  final router = ref.read(routerProvider);
  final contexto = router.routerDelegate.navigatorKey.currentContext;
  if (contexto == null || !contexto.mounted) return;
  final s = ref.read(serviciosProvider);
  final cliente = ref.read(clienteApiProvider);
  final t = AppLocalizations.of(contexto);
  final mensajero = ScaffoldMessenger.maybeOf(contexto);

  void aviso(String texto) => mensajero?.showSnackBar(SnackBar(content: Text(texto)));

  Future<T?> traer<T>(String ruta, T Function(Map<String, dynamic>) leer) async {
    try {
      return leer(await cliente.enviar('GET', ruta) as Map<String, dynamic>);
    } on ApiException catch (e) {
      aviso(e.categoria == CategoriaError.noEncontrado || e.categoria == CategoriaError.prohibido ? t.destinoNoDisponible : e.mensaje);
      return null;
    }
  }

  final ap = resolverDestino(destino);
  switch (ap) {
    case IrAPestana(:final ruta):
      router.go(ruta);
    case AbrirTarea(:final id):
      await Navigator.of(contexto).push(MaterialPageRoute(builder: (_) => TareaDetalleScreen(tareaId: id)));
    case AbrirNota(:final id):
      await Navigator.of(contexto).push(MaterialPageRoute(builder: (_) => NotaScreen(notaId: id)));
    case AbrirCorreo(:final id):
      if (id == null) {
        router.go(rutaCorreo);
      } else {
        await Navigator.of(contexto).push(MaterialPageRoute(builder: (_) => CorreoMensajeScreen(api: s.api, mensajeId: id, carpetas: const [])));
      }
    case AbrirVencimiento(:final id):
      final v = await traer('/fiscal/vencimientos/$id', VencimientoFiscal.fromJson);
      if (v != null && contexto.mounted) {
        await Navigator.of(contexto).push(MaterialPageRoute(builder: (_) => FiscalVencimientoEditScreen(api: s.api, vencimiento: v)));
      }
    case AbrirPantalla(:final clave):
      final usuario = ref.read(estadoSesionProvider).usuario;
      final pantalla = switch (clave) {
        'ausencias' => AusenciasScreen(api: s.api),
        'ia' => IaChatScreen(api: s.api, locale: s.locale),
        'notas' => const NotasScreen(),
        'tiquets' when usuario != null => TiquetsScreen(api: s.api, usuario: usuario),
        _ => null,
      };
      if (pantalla != null) await Navigator.of(contexto).push(MaterialPageRoute(builder: (_) => pantalla));
    case SoloWeb():
      await _ofrecerWeb(contexto, ref, urlWeb);
  }
}

Future<void> _ofrecerWeb(BuildContext contexto, Ref ref, String? urlWeb) async {
  final t = AppLocalizations.of(contexto);
  final abrir = await showDialog<bool>(
    context: contexto,
    builder: (c) => AlertDialog(
      title: Text(t.destinoSoloWebTitulo),
      content: Text(t.destinoSoloWebCuerpo),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: Text(t.comunCancelar)),
        FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(t.destinoAbrirWeb)),
      ],
    ),
  );
  if (abrir != true) return;
  final servidor = await ref.read(serviciosProvider).sesion.obtenerServidor();
  final ruta = urlWeb != null && urlWeb.startsWith('/') ? urlWeb : '';
  await launchUrl(Uri.parse('$servidor$ruta'), mode: LaunchMode.externalApplication);
}

/// El navegador de avisos con sus dependencias reales. Vive mientras vive la app
/// (guarda el aviso tocado antes de iniciar sesión).
final navegadorDeAvisosProvider = Provider<NavegadorDeAvisos>((ref) {
  EstadoSesion estado() => ref.read(estadoSesionProvider);
  return NavegadorDeAvisos(
    haySesion: () => estado().fase == FaseSesion.conSesion && !estado().actualizar,
    despachoActivo: () => estado().despacho,
    despachosPropios: () => estado().capacidades.despachos.map((d) => d.id).toSet(),
    confirmarCambio: (id) async {
      final contexto = ref.read(routerProvider).routerDelegate.navigatorKey.currentContext;
      if (contexto == null || !contexto.mounted) return false;
      final t = AppLocalizations.of(contexto);
      final nombre = estado().capacidades.despachoPorId(id)?.nombre ?? id;
      return await showDialog<bool>(
            context: contexto,
            builder: (c) => AlertDialog(
              content: Text(t.despachoAvisoCambiar(nombre)),
              actions: [
                TextButton(onPressed: () => Navigator.pop(c, false), child: Text(t.comunCancelar)),
                FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(t.despachoCambiarAccion)),
              ],
            ),
          ) ??
          false;
    },
    cambiarDespacho: (id) async {
      await ref.read(estadoSesionProvider.notifier).cambiarDespacho(id);
      await WidgetsBinding.instance.endOfFrame; // el enrutador se rehace con el despacho nuevo
    },
    abrir: (destino, {urlWeb}) => abrirDestino(ref, destino, urlWeb: urlWeb),
  );
});
