import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/material.dart';

import 'screens/correo_bandeja_screen.dart';
import 'screens/dashboard_screen.dart';
import 'screens/login_screen.dart';
import 'services/api_client.dart';
import 'services/push_service.dart';
import 'services/session_service.dart';
import 'services/sync_service.dart';

final navigatorKey = GlobalKey<NavigatorState>();

void main() {
  runApp(const GuildaWorkApp());
}

class GuildaWorkApp extends StatefulWidget {
  const GuildaWorkApp({super.key});

  @override
  State<GuildaWorkApp> createState() => _GuildaWorkAppState();
}

/// StatefulWidget (en vez del StatelessWidget original) para poder
/// escuchar conectividad y ciclo de vida de la app y disparar
/// SyncService.sincronizar() al recuperar red o volver a primer plano --
/// ver sync_service.dart para la cola offline de fichaje/notas.
class _GuildaWorkAppState extends State<GuildaWorkApp> with WidgetsBindingObserver {
  late final SessionService _sesion;
  late final ApiClient _api;
  late final SyncService _sync;
  late final PushService _push;
  StreamSubscription<List<ConnectivityResult>>? _conexionSub;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _sesion = SessionService();
    _api = ApiClient(_sesion);
    _sync = SyncService();
    _push = PushService(_api);
    // Al tocar una notificación de correo nuevo, abrir la bandeja de
    // entrada directamente -- únicos datos que manda app/push.py hoy (ver
    // app/correo.py:_emitir_evento_correo_nuevo).
    _push.onTap = (datos) {
      if (datos['tipo'] == 'correo_nuevo') {
        navigatorKey.currentState?.push(
          MaterialPageRoute(builder: (_) => CorreoBandejaScreen(api: _api)),
        );
      }
    };
    _api.onSesionExpirada = () {
      navigatorKey.currentState?.pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => LoginScreen(api: _api, sesion: _sesion, sync: _sync, push: _push)),
        (route) => false,
      );
    };
    _conexionSub = Connectivity().onConnectivityChanged.listen((estados) {
      if (!estados.contains(ConnectivityResult.none)) {
        _sync.sincronizar(_api);
      }
    });
    _sync.sincronizar(_api);
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
      _sync.sincronizar(_api);
    }
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      navigatorKey: navigatorKey,
      title: 'Guilda Work',
      theme: ThemeData(colorScheme: ColorScheme.fromSeed(seedColor: Colors.deepPurple)),
      home: _PantallaInicial(api: _api, sesion: _sesion, sync: _sync, push: _push),
    );
  }
}

/// Si ya hay un token guardado, intenta recuperar el usuario y salta
/// directo al Dashboard; si no hay token o el token ya no es válido
/// (revocado, servidor reinstalado...), muestra el login.
class _PantallaInicial extends StatelessWidget {
  final ApiClient api;
  final SessionService sesion;
  final SyncService sync;
  final PushService push;

  const _PantallaInicial({required this.api, required this.sesion, required this.sync, required this.push});

  Future<Widget> _resolverPantalla() async {
    final token = await sesion.obtenerToken();
    if (token == null) {
      return LoginScreen(api: api, sesion: sesion, sync: sync, push: push);
    }
    try {
      final usuario = await api.quienSoy();
      return DashboardScreen(usuario: usuario, api: api, sesion: sesion, sync: sync, push: push);
    } catch (_) {
      await sesion.borrarToken();
      return LoginScreen(api: api, sesion: sesion, sync: sync, push: push);
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Widget>(
      future: _resolverPantalla(),
      builder: (context, snapshot) {
        if (!snapshot.hasData) {
          return const Scaffold(body: Center(child: CircularProgressIndicator()));
        }
        return snapshot.data!;
      },
    );
  }
}
