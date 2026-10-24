import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'l10n/app_localizations.dart';
import 'nucleo/rutas.dart';
import 'nucleo/servicios.dart';
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

/// Escucha conectividad y ciclo de vida de la app para disparar
/// SyncService.sincronizar() al recuperar red o volver a primer plano --
/// ver sync_service.dart para la cola offline de fichaje/notas. La navegación
/// y la sesión viven en `nucleo/` (go_router + Riverpod).
class _GuildaWorkAppState extends ConsumerState<GuildaWorkApp> with WidgetsBindingObserver {
  StreamSubscription<List<ConnectivityResult>>? _conexionSub;

  Servicios get _s => ref.read(serviciosProvider);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // Al tocar una notificación de correo nuevo, abrir la bandeja de
    // entrada -- únicos datos que manda app/push.py hoy (ver
    // app/correo.py:_emitir_evento_correo_nuevo).
    _s.push.onTap = (datos) {
      if (datos['tipo'] == 'correo_nuevo') ref.read(routerProvider).go(rutaCorreo);
    };
    _conexionSub = Connectivity().onConnectivityChanged.listen((estados) {
      if (!estados.contains(ConnectivityResult.none)) {
        _s.sync.sincronizar(_s.api);
      }
    });
    _s.sync.sincronizar(_s.api);
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
      _s.sync.sincronizar(_s.api);
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
