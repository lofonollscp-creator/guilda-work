import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../services/api_client.dart';
import '../services/locale_service.dart';
import '../services/push_service.dart';
import '../services/session_service.dart';
import '../services/sync_service.dart';
import '../services/theme_service.dart';
import 'ajustes_servidor_dialog.dart';
import 'correo_ajustes_screen.dart';
import 'ia_ajustes_screen.dart';
import 'login_screen.dart';
import 'selector_idioma_dialog.dart';

/// Ajustes generales de la app -- punto de entrada único a: tema
/// claro/oscuro/sistema, idioma, ajustes del asistente IA, URL del
/// servidor, ajustes de correo, y cerrar sesión. Reúne aquí todo lo que
/// antes eran iconos sueltos en la barra superior del dashboard (llegó a
/// haber 10 a la vez -- ver dashboard_screen.dart) para que esa barra se
/// quede solo con lo de uso diario.
class AjustesScreen extends StatelessWidget {
  final ApiClient api;
  final SessionService sesion;
  final SyncService sync;
  final PushService push;
  final ThemeService tema;
  final LocaleService locale;

  const AjustesScreen({
    super.key,
    required this.api,
    required this.sesion,
    required this.sync,
    required this.push,
    required this.tema,
    required this.locale,
  });

  Future<void> _cerrarSesion(BuildContext context) async {
    await push.alCerrarSesion();
    await api.logout();
    await sesion.borrarToken();
    if (!context.mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(
        builder: (_) => LoginScreen(api: api, sesion: sesion, sync: sync, push: push, tema: tema, locale: locale),
      ),
      (route) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(t.dashboardAjustesTooltip)),
      body: ListView(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
            child: Text(t.ajustesApariencia, style: const TextStyle(fontWeight: FontWeight.w600)),
          ),
          AnimatedBuilder(
            animation: tema,
            builder: (context, _) => Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: SegmentedButton<ThemeMode>(
                segments: [
                  ButtonSegment(value: ThemeMode.system, label: Text(t.ajustesTemaSistema), icon: const Icon(Icons.brightness_auto)),
                  ButtonSegment(value: ThemeMode.light, label: Text(t.ajustesTemaClaro), icon: const Icon(Icons.light_mode_outlined)),
                  ButtonSegment(value: ThemeMode.dark, label: Text(t.ajustesTemaOscuro), icon: const Icon(Icons.dark_mode_outlined)),
                ],
                selected: {tema.modo},
                onSelectionChanged: (seleccion) => tema.cambiar(seleccion.first),
              ),
            ),
          ),
          const SizedBox(height: 8),
          ListTile(
            leading: const Icon(Icons.language),
            title: Text(t.comunIdioma),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => mostrarSelectorIdioma(context, locale),
          ),
          const Divider(height: 32),
          ListTile(
            leading: const Icon(Icons.smart_toy_outlined),
            title: Text(t.dashboardAsistenteIaTooltip),
            subtitle: Text(t.ajustesAsistenteIaSubtitulo),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => IaAjustesScreen(api: api)),
            ),
          ),
          ListTile(
            leading: const Icon(Icons.mail_outline),
            title: Text(t.dashboardCorreoTooltip),
            subtitle: Text(t.ajustesCorreoSubtitulo),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => CorreoAjustesScreen(api: api)),
            ),
          ),
          const Divider(height: 32),
          ListTile(
            leading: const Icon(Icons.dns_outlined),
            title: Text(t.ajustesServidorTitulo),
            subtitle: Text(t.ajustesServidorSubtitulo),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => mostrarAjustesServidor(context, sesion),
          ),
          const Divider(height: 32),
          ListTile(
            leading: Icon(Icons.logout, color: Theme.of(context).colorScheme.error),
            title: Text(t.dashboardCerrarSesionTooltip, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            onTap: () => _cerrarSesion(context),
          ),
        ],
      ),
    );
  }
}
