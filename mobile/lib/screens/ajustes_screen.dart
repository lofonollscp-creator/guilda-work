import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../services/session_service.dart';
import '../services/theme_service.dart';
import 'ajustes_servidor_dialog.dart';
import 'correo_ajustes_screen.dart';
import 'ia_ajustes_screen.dart';

/// Ajustes generales de la app (no existía ninguna pantalla equivalente
/// antes de la Fase 3 del plan "eventual-herding-kitten") -- punto de
/// entrada único a: tema claro/oscuro/sistema, ajustes del asistente IA,
/// URL del servidor, y ajustes de correo.
class AjustesScreen extends StatelessWidget {
  final ApiClient api;
  final SessionService sesion;
  final ThemeService tema;

  const AjustesScreen({super.key, required this.api, required this.sesion, required this.tema});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Ajustes')),
      body: ListView(
        children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 16, 16, 8),
            child: Text('Apariencia', style: TextStyle(fontWeight: FontWeight.w600)),
          ),
          AnimatedBuilder(
            animation: tema,
            builder: (context, _) => Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: SegmentedButton<ThemeMode>(
                segments: const [
                  ButtonSegment(value: ThemeMode.system, label: Text('Sistema'), icon: Icon(Icons.brightness_auto)),
                  ButtonSegment(value: ThemeMode.light, label: Text('Claro'), icon: Icon(Icons.light_mode_outlined)),
                  ButtonSegment(value: ThemeMode.dark, label: Text('Oscuro'), icon: Icon(Icons.dark_mode_outlined)),
                ],
                selected: {tema.modo},
                onSelectionChanged: (seleccion) => tema.cambiar(seleccion.first),
              ),
            ),
          ),
          const Divider(height: 32),
          ListTile(
            leading: const Icon(Icons.smart_toy_outlined),
            title: const Text('Asistente IA'),
            subtitle: const Text('Modelo y modo autónomo'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => IaAjustesScreen(api: api)),
            ),
          ),
          ListTile(
            leading: const Icon(Icons.mail_outline),
            title: const Text('Correo'),
            subtitle: const Text('Densidad, marcar leído automático, firma…'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => CorreoAjustesScreen(api: api)),
            ),
          ),
          const Divider(height: 32),
          ListTile(
            leading: const Icon(Icons.dns_outlined),
            title: const Text('Servidor'),
            subtitle: const Text('URL del backend al que se conecta la app'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => mostrarAjustesServidor(context, sesion),
          ),
        ],
      ),
    );
  }
}
