import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../services/push_service.dart';
import '../services/session_service.dart';
import '../services/sync_service.dart';
import '../services/theme_service.dart';
import '../widgets/app_button.dart';
import 'ajustes_servidor_dialog.dart';
import 'dashboard_screen.dart';

class RegistroScreen extends StatefulWidget {
  final ApiClient api;
  final SessionService sesion;
  final SyncService sync;
  final PushService push;
  final ThemeService tema;

  const RegistroScreen({
    super.key,
    required this.api,
    required this.sesion,
    required this.sync,
    required this.push,
    required this.tema,
  });

  @override
  State<RegistroScreen> createState() => _RegistroScreenState();
}

class _RegistroScreenState extends State<RegistroScreen> {
  final _email = TextEditingController();
  final _contrasena = TextEditingController();
  final _confirmar = TextEditingController();
  String? _error;
  bool _cargando = false;

  Future<void> _registrar() async {
    if (_contrasena.text.length < 8) {
      setState(() => _error = 'La contraseña debe tener al menos 8 caracteres.');
      return;
    }
    if (_contrasena.text != _confirmar.text) {
      setState(() => _error = 'Las contraseñas no coinciden.');
      return;
    }
    setState(() {
      _cargando = true;
      _error = null;
    });
    try {
      final (token, usuario) = await widget.api.registrar(
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
            tema: widget.tema,
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
    return Scaffold(
      appBar: AppBar(
        title: const Text('Crear cuenta'),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_ethernet),
            tooltip: 'Servidor',
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
                  Image.asset('assets/branding/logo.png', height: 80),
                  const SizedBox(height: 24),
                  TextField(
                    controller: _email,
                    decoration: const InputDecoration(labelText: 'Email'),
                    keyboardType: TextInputType.emailAddress,
                    autocorrect: false,
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _contrasena,
                    decoration: const InputDecoration(
                      labelText: 'Contraseña (mínimo 8 caracteres)',
                    ),
                    obscureText: true,
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _confirmar,
                    decoration: const InputDecoration(labelText: 'Repite la contraseña'),
                    obscureText: true,
                    onSubmitted: (_) => _registrar(),
                  ),
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                  ],
                  const SizedBox(height: 24),
                  SizedBox(
                    width: double.infinity,
                    child: AppButton(texto: 'Crear cuenta', cargando: _cargando, onPressed: _registrar),
                  ),
                  TextButton(
                    onPressed: () => Navigator.of(context).pop(),
                    child: const Text('¿Ya tienes cuenta? Inicia sesión'),
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
