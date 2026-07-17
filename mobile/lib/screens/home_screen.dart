import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../services/session_service.dart';
import 'login_screen.dart';

/// Placeholder tras iniciar sesión — el resto de módulos (Dashboard,
/// Notas/Tareas, Correo, Asistente IA) son las sub-fases siguientes de la
/// Fase 4 (ver plan de "app móvil"), esta pantalla solo confirma que el
/// login/registro y la persistencia de sesión funcionan de verdad.
class HomeScreen extends StatelessWidget {
  final Usuario usuario;
  final ApiClient api;
  final SessionService sesion;

  const HomeScreen({
    super.key,
    required this.usuario,
    required this.api,
    required this.sesion,
  });

  Future<void> _cerrarSesion(BuildContext context) async {
    await api.logout();
    await sesion.borrarToken();
    if (!context.mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => LoginScreen(api: api, sesion: sesion)),
      (route) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Guilda Work')),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text('Sesión iniciada como ${usuario.email}'),
            const SizedBox(height: 24),
            OutlinedButton(
              onPressed: () => _cerrarSesion(context),
              child: const Text('Cerrar sesión'),
            ),
          ],
        ),
      ),
    );
  }
}
