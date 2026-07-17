import 'package:flutter/material.dart';

import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'services/api_client.dart';
import 'services/session_service.dart';

void main() {
  runApp(const GuildaWorkApp());
}

class GuildaWorkApp extends StatelessWidget {
  const GuildaWorkApp({super.key});

  @override
  Widget build(BuildContext context) {
    final sesion = SessionService();
    final api = ApiClient(sesion);

    return MaterialApp(
      title: 'Guilda Work',
      theme: ThemeData(colorScheme: ColorScheme.fromSeed(seedColor: Colors.deepPurple)),
      home: _PantallaInicial(api: api, sesion: sesion),
    );
  }
}

/// Si ya hay un token guardado, intenta recuperar el usuario y salta
/// directo a HomeScreen; si no hay token o el token ya no es válido
/// (revocado, servidor reinstalado...), muestra el login.
class _PantallaInicial extends StatelessWidget {
  final ApiClient api;
  final SessionService sesion;

  const _PantallaInicial({required this.api, required this.sesion});

  Future<Widget> _resolverPantalla() async {
    final token = await sesion.obtenerToken();
    if (token == null) {
      return LoginScreen(api: api, sesion: sesion);
    }
    try {
      final usuario = await api.quienSoy();
      return HomeScreen(usuario: usuario, api: api, sesion: sesion);
    } catch (_) {
      await sesion.borrarToken();
      return LoginScreen(api: api, sesion: sesion);
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
