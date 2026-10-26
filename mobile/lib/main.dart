import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'l10n/app_localizations.dart';
import 'datos/cola.dart';
import 'diseno/adaptable.dart';
import 'nucleo/abrir_destino.dart';
import 'nucleo/bloqueo.dart';
import 'nucleo/pantalla_bloqueo.dart';
import 'nucleo/rutas.dart';
import 'nucleo/servicios.dart';
import 'nucleo/sesion.dart';
import 'theme/app_theme.dart';

void main() {
  runApp(
    ProviderScope(
      overrides: [serviciosProvider.overrideWithValue(Servicios.reales())],
      child: const GuildaWorkApp(),
    ),
  );
}

class GuildaWorkApp extends ConsumerStatefulWidget {
  const GuildaWorkApp({super.key});

  @override
  ConsumerState<GuildaWorkApp> createState() => _GuildaWorkAppState();
}

/// Escucha conectividad y ciclo de vida de la app para vaciar la cola de
/// escrituras sin conexión al recuperar red o volver a primer plano (ver
/// datos/cola_procesador.dart). La navegación y la sesión viven en `nucleo/`
/// (go_router + Riverpod).
class _GuildaWorkAppState extends ConsumerState<GuildaWorkApp> with WidgetsBindingObserver {
  StreamSubscription<List<ConnectivityResult>>? _conexionSub;

  Servicios get _s => ref.read(serviciosProvider);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // Al tocar un aviso (push) se abre la pantalla de su `destino` (ver nucleo/avisos.dart): espera a
    // que haya sesión, avisa si es de otro despacho y cae en la web si aún no hay pantalla nativa.
    _s.push.onTap = (datos) => ref.read(navegadorDeAvisosProvider).abrirDesdePush(datos);
    ref.listenManual(estadoSesionProvider, (anterior, estado) {
      if (estado.fase == FaseSesion.conSesion && anterior?.fase != FaseSesion.conSesion) {
        // Abierta con la sesión ya guardada (venía de «arrancando»): hay que desbloquear. Si acaba de escribir la contraseña (venía de «sin sesión»), no.
        unawaited(ref.read(bloqueoProvider.notifier).alEntrarConSesion(arranqueEnFrio: anterior?.fase == FaseSesion.arrancando).then((_) => _ofrecerBloqueo()));
        _alIniciarSesion();
      } else if (estado.fase == FaseSesion.sinSesion && anterior?.fase == FaseSesion.conSesion) {
        unawaited(ref.read(bloqueoProvider.notifier).alCerrarSesion());
      }
    }, fireImmediately: true);
    _conexionSub = Connectivity().onConnectivityChanged.listen((estados) {
      if (!estados.contains(ConnectivityResult.none)) {
        _vaciarCola();
      }
    });
  }

  /// Tras la segunda entrada, ofrece proteger la app con la biometría del móvil (una sola vez).
  Future<void> _ofrecerBloqueo() async {
    final b = ref.read(bloqueoProvider);
    if (!b.debeOfrecer || b.bloqueada) return;
    await WidgetsBinding.instance.endOfFrame;
    final contexto = ref.read(routerProvider).routerDelegate.navigatorKey.currentContext;
    if (contexto != null && contexto.mounted) await ofrecerBloqueo(contexto, ref);
  }

  /// Envía lo que se hizo sin conexión (si aún no hay sesión, no hace nada).
  void _vaciarCola() => unawaited(ref.read(procesadorColaProvider).procesar());

  /// Lo que una versión anterior de la app dejó pendiente (fichajes y notas sin enviar) pasa a la cola nueva. Se hace sin ruido y es seguro repetirlo.
  Future<void> _migrarColaAntigua() async {
    final e = ref.read(estadoSesionProvider);
    if (e.usuario == null) return;
    try {
      await _s.sync.migrarA(ref.read(colaEscrituraProvider), usuarioId: e.usuario!.id, despachoId: despachoDeLaCola(e.despacho));
    } catch (_) {
      // se reintenta en el próximo inicio de sesión: la cola antigua no se borra hasta que pasa a la nueva
    }
  }

  /// Con sesión: prepara los avisos (Firebase, token del dispositivo, canales de Android) y abre el aviso que se tocó antes de entrar.
  Future<void> _alIniciarSesion() async {
    await WidgetsBinding.instance.endOfFrame; // que el enrutador ya haya pintado la pantalla de inicio
    await _migrarColaAntigua();
    try {
      await _s.push.inicializar();
      final t = await AppLocalizations.delegate.load(_s.locale.locale);
      await _s.push.crearCanales({
        'tareas': t.canalTareas,
        'correo': t.canalCorreo,
        'fiscal': t.canalFiscal,
        'equipo': t.canalEquipo,
        'resumenes': t.canalResumenes,
        'general': t.canalGeneral,
      });
    } catch (_) {
      // los avisos son opcionales: sin Firebase la app funciona igual
    }
    await ref.read(navegadorDeAvisosProvider).aplicarPendiente();
    _vaciarCola();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _conexionSub?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    ref.read(bloqueoProvider.notifier).alCambiarCiclo(state);
    if (state == AppLifecycleState.resumed) {
      _vaciarCola();
    }
  }

  @override
  Widget build(BuildContext context) {
    final router = ref.watch(routerProvider);
    return ListenableBuilder(
      listenable: Listenable.merge([_s.tema, _s.locale]),
      builder: (context, _) {
        return MaterialApp.router(
          routerConfig: router,
          builder: (context, hijo) => ColoredBox(
            color: Theme.of(context).scaffoldBackgroundColor,
            // En una pantalla muy ancha el contenido no se estira (el fondo sí llena).
            child: Center(child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: anchoMaximoApp), child: _ConBloqueo(hijo: hijo ?? const SizedBox()))),
          ),
          title: 'Guilda Work',
          theme: AppTheme.claro(_s.tema.acento),
          darkTheme: AppTheme.oscuro(_s.tema.acento),
          themeMode: _s.tema.modo,
          locale: _s.locale.locale,
          localizationsDelegates: const [
            AppLocalizations.delegate,
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          supportedLocales: AppLocalizations.supportedLocales,
        );
      },
    );
  }
}

/// Pone el bloqueo y la cubierta de privacidad encima de toda la app (por encima también de los diálogos y las rutas empujadas).
class _ConBloqueo extends ConsumerWidget {
  final Widget hijo;
  const _ConBloqueo({required this.hijo});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final conSesion = ref.watch(estadoSesionProvider.select((e) => e.fase == FaseSesion.conSesion));
    final b = ref.watch(bloqueoProvider);
    final bloqueada = conSesion && b.bloqueada;
    return Stack(children: [
      // Bloqueada, lo de debajo ni se toca ni se lee con un lector de pantalla.
      ExcludeSemantics(excluding: bloqueada, child: IgnorePointer(ignoring: bloqueada, child: hijo)),
      if (bloqueada) const Positioned.fill(child: PantallaBloqueo()) else if (conSesion && b.activo && b.cubierta) const Positioned.fill(child: CubiertaPrivacidad()),
    ]);
  }
}
