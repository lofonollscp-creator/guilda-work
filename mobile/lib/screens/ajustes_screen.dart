import 'package:flutter/material.dart';

import '../nucleo/pantalla_bloqueo.dart';

import '../diseno/componentes.dart';
import '../l10n/app_localizations.dart';
import '../services/api_client.dart';
import '../services/locale_service.dart';
import '../services/push_service.dart';
import '../services/session_service.dart';
import '../services/sync_service.dart';
import '../services/theme_service.dart';
import '../theme/acento.dart';
import 'ajustes_servidor_dialog.dart';
import 'correo_ajustes_screen.dart';
import 'ia_ajustes_screen.dart';
import 'login_screen.dart';
import 'perfil_screen.dart';
import 'selector_idioma_dialog.dart';

/// Ajustes generales de la app -- punto de entrada único a: tema
/// claro/oscuro/sistema, idioma, ajustes del asistente IA, URL del
/// servidor, ajustes de correo, y cerrar sesión. Reúne aquí todo lo que
/// antes eran iconos sueltos en la barra superior del dashboard (llegó a
/// haber 10 a la vez -- ver dashboard_screen.dart) para que esa barra se
/// quede solo con lo de uso diario.
String _nombreAcento(AppLocalizations t, String clave) => switch (clave) {
      'azul' => t.acentoAzul,
      'turquesa' => t.acentoTurquesa,
      'violeta' => t.acentoVioleta,
      'rosa' => t.acentoRosa,
      'rojo' => t.acentoRojo,
      'naranja' => t.acentoNaranja,
      'ambar' => t.acentoAmbar,
      _ => t.acentoLima,
    };

class AjustesScreen extends StatelessWidget {
  final ApiClient api;
  final Usuario usuario;
  final SessionService sesion;
  final SyncService sync;
  final PushService push;
  final ThemeService tema;
  final LocaleService locale;

  /// Si lo da el enrutador, cerrar sesión le avisa a él (que lleva a la
  /// pantalla de login) en vez de abrir [LoginScreen] a mano.
  final Future<void> Function()? alCerrarSesion;

  /// Si lo da el enrutador, se le pregunta antes de cerrar (p. ej. por cambios sin enviar); `false` cancela.
  final Future<bool> Function()? confirmarCerrarSesion;

  const AjustesScreen({
    super.key,
    required this.api,
    required this.usuario,
    required this.sesion,
    required this.sync,
    required this.push,
    required this.tema,
    required this.locale,
    this.alCerrarSesion,
    this.confirmarCerrarSesion,
  });

  Future<void> _cerrarSesion(BuildContext context) async {
    if (confirmarCerrarSesion != null && !await confirmarCerrarSesion!()) return;
    await push.alCerrarSesion();
    await api.logout();
    await sesion.borrarToken();
    if (alCerrarSesion != null) {
      await alCerrarSesion!();
      return;
    }
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
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
        children: [
          GrupoAjustes(children: [
            FilaAjuste(
              icono: Icons.person_outline,
              titulo: t.perfilTitulo,
              subtitulo: t.ajustesPerfilSubtitulo,
              final_: const Icon(Icons.chevron_right),
              alPulsar: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => PerfilScreen(api: api, usuario: usuario))),
            ),
          ]),
          // Apariencia: tema, color de los botones e idioma, juntos.
          Padding(padding: const EdgeInsets.fromLTRB(4, 4, 4, 8), child: Text(t.ajustesApariencia, style: Theme.of(context).textTheme.titleSmall)),
          Card(
            margin: const EdgeInsets.only(bottom: 12),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                AnimatedBuilder(
                  animation: tema,
                  builder: (context, _) => SizedBox(
                    width: double.infinity,
                    child: SegmentedButton<ThemeMode>(
                      showSelectedIcon: false,
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
                const SizedBox(height: 20),
                Text(t.ajustesColorBotones, style: Theme.of(context).textTheme.titleSmall),
                const SizedBox(height: 8),
                AnimatedBuilder(
                  animation: tema,
                  builder: (context, _) => Wrap(spacing: 8, runSpacing: 8, children: [
                    for (final e in acentos.entries)
                      ChoiceChip(
                        showCheckmark: false,
                        avatar: CircleAvatar(
                          backgroundColor: Color(e.value),
                          radius: 10,
                          child: tema.acento == e.key ? Icon(Icons.check, size: 14, color: coloresDeAcento(e.key).onAccent) : null,
                        ),
                        label: Text(_nombreAcento(t, e.key)),
                        selected: tema.acento == e.key,
                        onSelected: (_) => tema.cambiarAcento(e.key),
                      ),
                  ]),
                ),
                const SizedBox(height: 8),
                Text(t.ajustesColorAyuda, style: Theme.of(context).textTheme.bodySmall),
              ]),
            ),
          ),
          GrupoAjustes(children: [
            FilaAjuste(icono: Icons.language, titulo: t.comunIdioma, final_: const Icon(Icons.chevron_right), alPulsar: () => mostrarSelectorIdioma(context, locale)),
            FilaAjuste(
              icono: Icons.smart_toy_outlined,
              titulo: t.dashboardAsistenteIaTooltip,
              subtitulo: t.ajustesAsistenteIaSubtitulo,
              final_: const Icon(Icons.chevron_right),
              alPulsar: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => IaAjustesScreen(api: api))),
            ),
            FilaAjuste(
              icono: Icons.mail_outline,
              titulo: t.dashboardCorreoTooltip,
              subtitulo: t.ajustesCorreoSubtitulo,
              final_: const Icon(Icons.chevron_right),
              alPulsar: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => CorreoAjustesScreen(api: api))),
            ),
          ]),
          GrupoAjustes(children: [
            FilaAjuste(
              icono: Icons.dns_outlined,
              titulo: t.ajustesServidorTitulo,
              subtitulo: t.ajustesServidorSubtitulo,
              final_: const Icon(Icons.chevron_right),
              alPulsar: () => mostrarAjustesServidor(context, sesion),
            ),
            const InterruptorBloqueo(),
          ]),
          GrupoAjustes(children: [
            FilaAjuste(icono: Icons.logout, titulo: t.dashboardCerrarSesionTooltip, peligro: true, alPulsar: () => _cerrarSesion(context)),
          ]),
        ],
      ),
    );
  }
}
