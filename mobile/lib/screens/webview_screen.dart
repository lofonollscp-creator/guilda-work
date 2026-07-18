import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

/// WebView a pantalla completa para una herramienta externa (Fase 9) —
/// Outline, Metabase, n8n, OpenProject, Chatwoot. Las que tienen SSO
/// (Outline) piden login aparte la primera vez dentro del propio WebView
/// (la app móvil usa un token Bearer propio, no comparte la cookie de
/// sesión de Kratos que usa el navegador) — la cookie queda guardada en el
/// WebView entre usos, igual que ya pasa hoy en escritorio con
/// Metabase/n8n.
class WebviewScreen extends StatefulWidget {
  final String titulo;
  final String url;

  const WebviewScreen({super.key, required this.titulo, required this.url});

  @override
  State<WebviewScreen> createState() => _WebviewScreenState();
}

class _WebviewScreenState extends State<WebviewScreen> {
  late final WebViewController _controller;
  bool _cargando = true;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageStarted: (_) => setState(() => _cargando = true),
          onPageFinished: (_) => setState(() => _cargando = false),
        ),
      )
      ..loadRequest(Uri.parse(widget.url));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.titulo)),
      body: Stack(
        children: [
          WebViewWidget(controller: _controller),
          if (_cargando) const LinearProgressIndicator(),
        ],
      ),
    );
  }
}
