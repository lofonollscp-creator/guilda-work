import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../services/api_client.dart';
import '../services/locale_service.dart';
import '../services/push_service.dart';
import '../services/session_service.dart';
import '../services/sync_service.dart';
import '../services/theme_service.dart';
import '../widgets/app_button.dart';
import 'ajustes_servidor_dialog.dart';
import 'dashboard_screen.dart';
import 'registro_screen.dart';
import 'selector_idioma_dialog.dart';

class LoginScreen extends StatefulWidget {
  final ApiClient api;
  final SessionService sesion;
  final SyncService sync;
  final PushService push;
  final ThemeService tema;
  final LocaleService locale;
  /// Si lo da quien monta la pantalla (el enrutador), se llama con el usuario
  /// al iniciar sesión en vez de abrir [DashboardScreen] directamente.
  final void Function(Usuario usuario)? alIniciarSesion;

  const LoginScreen({
    super.key,
    required this.api,
    required this.sesion,
    required this.sync,
    required this.push,
    required this.tema,
    required this.locale,
    this.alIniciarSesion,
  });

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _contrasena = TextEditingController();
  final _codigo2fa = TextEditingController();
  String? _error;
  bool _cargando = false;

  /// La API ha contestado que la cuenta tiene verificación en dos pasos: se pide el código y se reenvía.
  bool _pide2fa = false;

  Future<void> _iniciarSesion() async {
    setState(() {
      _cargando = true;
      _error = null;
    });
    try {
      final (token, usuario) = await widget.api.login(
        _email.text.trim(),
        _contrasena.text,
        codigo2fa: _pide2fa ? _codigo2fa.text.trim() : null,
      );
      await widget.sesion.guardarToken(token);
      if (!mounted) return;
      if (widget.alIniciarSesion != null) {
        widget.alIniciarSesion!(usuario);
        return;
      }
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(
          builder: (_) => DashboardScreen(
            usuario: usuario,
            api: widget.api,
            sesion: widget.sesion,
            sync: widget.sync,
            push: widget.push,
            tema: widget.tema,
            locale: widget.locale,
          ),
        ),
        (route) => false,
      );
    } on ApiException catch (e) {
      // Primera vez: solo falta el código. Si ya se envió uno, el error es de verdad (código incorrecto) y se muestra.
      setState(() {
        if (e.requiere2fa) {
          _pide2fa = true;
          _error = null;
        } else {
          _error = e.toString();
        }
      });
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
        automaticallyImplyLeading: false,
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
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 400),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Image.asset('assets/branding/logo.png', height: 96),
                  const SizedBox(height: 12),
                  Text('Guilda Work', style: Theme.of(context).textTheme.headlineSmall),
                  const SizedBox(height: 32),
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
                    onSubmitted: (_) => _iniciarSesion(),
                  ),
                  if (_pide2fa) ...[
                    const SizedBox(height: 12),
                    TextField(
                      controller: _codigo2fa,
                      decoration: InputDecoration(labelText: t.login2faLabel, helperText: t.login2faAyuda, helperMaxLines: 3),
                      keyboardType: TextInputType.number,
                      autofocus: true,
                      autocorrect: false,
                      onSubmitted: (_) => _iniciarSesion(),
                    ),
                  ],
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                  ],
                  const SizedBox(height: 24),
                  SizedBox(
                    width: double.infinity,
                    child: AppButton(texto: t.loginEntrarBoton, cargando: _cargando, onPressed: _iniciarSesion),
                  ),
                  TextButton(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => RegistroScreen(
                          api: widget.api,
                          sesion: widget.sesion,
                          sync: widget.sync,
                          push: widget.push,
                          tema: widget.tema,
                          locale: widget.locale,
                          alIniciarSesion: widget.alIniciarSesion,
                        ),
                      ),
                    ),
                    child: Text(t.loginRegistrateLink),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
