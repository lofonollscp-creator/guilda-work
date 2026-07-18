import 'dart:async';

import 'package:app_links/app_links.dart';
import 'package:flutter/material.dart';

import '../services/matrix_service.dart';
import 'salas_chat_screen.dart';

/// Pantalla de entrada al chat nativo (Element/Synapse), Fase 9. Si ya
/// había una sesión de Matrix persistida, entra directa a
/// [SalasChatScreen]; si no, muestra el botón de login SSO (único método
/// que admite el homeserver) y espera el callback por deep link.
class ChatLoginScreen extends StatefulWidget {
  final MatrixService matrix;

  const ChatLoginScreen({super.key, required this.matrix});

  @override
  State<ChatLoginScreen> createState() => _ChatLoginScreenState();
}

class _ChatLoginScreenState extends State<ChatLoginScreen> {
  final _appLinks = AppLinks();
  StreamSubscription<Uri>? _suscripcion;
  bool _conectando = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _comprobarSesionExistente();
    _escucharCallback();
  }

  @override
  void dispose() {
    _suscripcion?.cancel();
    super.dispose();
  }

  Future<void> _comprobarSesionExistente() async {
    final cliente = await widget.matrix.clienteConectado();
    if (cliente.isLogged() && mounted) {
      _irASalas();
    }
  }

  void _escucharCallback() {
    _suscripcion = _appLinks.uriLinkStream.listen(_procesarUri, onError: (_) {});
    _appLinks.getInitialLink().then((uri) {
      if (uri != null) _procesarUri(uri);
    });
  }

  Future<void> _procesarUri(Uri uri) async {
    if (uri.scheme != 'guildawork' || uri.host != 'matrix-callback') return;
    final loginToken = uri.queryParameters['loginToken'];
    if (loginToken == null) return;
    setState(() {
      _conectando = true;
      _error = null;
    });
    try {
      await widget.matrix.completarLoginConToken(loginToken);
      if (mounted) _irASalas();
    } catch (e) {
      setState(() {
        _conectando = false;
        _error = 'No se ha podido completar el login: $e';
      });
    }
  }

  Future<void> _iniciarLogin() async {
    setState(() {
      _conectando = true;
      _error = null;
    });
    try {
      await widget.matrix.iniciarLoginSso();
    } catch (e) {
      setState(() {
        _conectando = false;
        _error = 'No se ha podido iniciar el login: $e';
      });
    }
  }

  void _irASalas() {
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => SalasChatScreen(matrix: widget.matrix)),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Chat')),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.chat_bubble_outline, size: 48),
              const SizedBox(height: 16),
              const Text(
                'El chat de equipo (Element) entra con tu misma sesión de Guilda Work.',
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),
              if (_conectando)
                const CircularProgressIndicator()
              else
                FilledButton(
                  onPressed: _iniciarLogin,
                  child: const Text('Entrar con tu sesión de Guilda Work'),
                ),
              if (_error != null) ...[
                const SizedBox(height: 16),
                Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
