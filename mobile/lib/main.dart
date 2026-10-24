import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'l10n/app_localizations.dart';
import 'datos/cola.dart';
import 'nucleo/abrir_destino.dart';
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
      if (estado.fase == FaseSesion.conSesion && anterior?.fase != FaseSesion.conSesion) _alIniciarSesion();
    }, fireImmediately: true);
    _conexionSub = Connectivity().onConnectivityChanged.listen((estados) {
      if (!estados.contains(ConnectivityResult.none)) {
        _vaciarCola();
      }
    });
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
          title: 'Guilda Work',
          theme: AppTheme.light,
          darkTheme: AppTheme.dark,
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
