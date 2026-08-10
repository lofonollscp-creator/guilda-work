import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../services/api_client.dart';
import '../services/locale_service.dart';
import '../services/push_service.dart';
import '../services/session_service.dart';
import '../services/sync_service.dart';
import 'ajustes_servidor_dialog.dart';
import 'dashboard_screen.dart';
import 'registro_screen.dart';
import 'selector_idioma_dialog.dart';

class LoginScreen extends StatefulWidget {
  final ApiClient api;
  final SessionService sesion;
  final SyncService sync;
  final PushService push;
  final LocaleService locale;

  const LoginScreen({super.key, required this.api, required this.sesion, required this.sync, required this.push, required this.locale});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _contrasena = TextEditingController();
  String? _error;
  bool _cargando = false;

  Future<void> _iniciarSesion() async {
    setState(() {
      _cargando = true;
      _error = null;
    });
    try {
      final (token, usuario) = await widget.api.login(
        _email.text.trim(),
        _contrasena.text,
      );
      await widget.sesion.guardarToken(token);
      if (!mounted) return;
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(
          builder: (_) => DashboardScreen(
            usuario: usuario,
            api: widget.api,
            sesion: widget.sesion,
            sync: widget.sync,
            push: widget.push,
            locale: widget.locale,
          ),
        ),
        (route) => false,
      );
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _cargando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Guilda Work'),
        actions: [
          IconButton(
            icon: const Icon(Icons.language),
            tooltip: t.comunIdioma,
            onPressed: () => mostrarSelectorIdioma(context, widget.locale),
          ),
          IconButton(
            icon: const Icon(Icons.settings_ethernet),
            tooltip: t.loginServidorTooltip,
            onPressed: () => mostrarAjustesServidor(context, widget.sesion),
          ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            TextField(
              controller: _email,
              decoration: InputDecoration(labelText: t.loginEmailLabel),
              keyboardType: TextInputType.emailAddress,
              autocorrect: false,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _contrasena,
              decoration: InputDecoration(labelText: t.loginContrasenaLabel),
              obscureText: true,
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ],
            const SizedBox(height: 24),
            FilledButton(
              onPressed: _cargando ? null : _iniciarSesion,
              child: _cargando
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : Text(t.loginEntrarBoton),
            ),
            TextButton(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => RegistroScreen(api: widget.api, sesion: widget.sesion, sync: widget.sync, push: widget.push, locale: widget.locale),
                ),
              ),
              child: Text(t.loginRegistrateLink),
            ),
          ],
        ),
      ),
    );
  }
}
