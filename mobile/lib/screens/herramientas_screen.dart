import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../models/models.dart';
import '../services/api_client.dart';
import 'webview_screen.dart';

/// Catálogo de herramientas externas conectadas (equivalente móvil de
/// app/templates/herramientas.html), Fase 9 — cada tarjeta abre su
/// WebView. No incluye "chat" (Element): la API ya lo excluye, ver
/// app/rutas_api.py `listar_herramientas`.
class HerramientasScreen extends StatefulWidget {
  final ApiClient api;

  const HerramientasScreen({super.key, required this.api});

  @override
  State<HerramientasScreen> createState() => _HerramientasScreenState();
}

class _HerramientasScreenState extends State<HerramientasScreen> {
  late Future<(List<Herramienta>, String)> _carga;

  @override
  void initState() {
    super.initState();
    // Se resuelve la URL del servidor una sola vez aquí (en vez de en cada
    // tarjeta) para construir las URLs de los logos -- ver
    // ApiClient.urlLogoHerramienta.
    _carga = Future.wait([
      widget.api.listarHerramientas(),
      widget.api.sesion.obtenerServidor(),
    ]).then((r) => (r[0] as List<Herramienta>, r[1] as String));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Herramientas')),
      body: FutureBuilder<(List<Herramienta>, String)>(
        future: _carga,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text('${snapshot.error}'));
          }
          final (herramientas, baseUrl) = snapshot.data!;
          if (herramientas.isEmpty) {
            return const Center(child: Text('Todavía no hay herramientas conectadas.'));
          }
          return GridView.builder(
            padding: const EdgeInsets.all(16),
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 2,
              mainAxisSpacing: 12,
              crossAxisSpacing: 12,
              childAspectRatio: 1.1,
            ),
            itemCount: herramientas.length,
            itemBuilder: (context, i) {
              final h = herramientas[i];
              final contenido = Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _logoHerramienta(h, baseUrl),
                    const SizedBox(height: 8),
                    Text(
                      h.nombre,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            color: h.disponible ? null : Theme.of(context).disabledColor,
                          ),
                    ),
                    const SizedBox(height: 4),
                    Expanded(
                      child: Text(
                        h.descripcion,
                        style: Theme.of(context).textTheme.bodySmall,
                        overflow: TextOverflow.fade,
                      ),
                    ),
                    Text(
                      !h.disponible
                          ? 'Aún no disponible'
                          // El WebView de la app no comparte la cookie de sesión de
                          // Kratos que usa el navegador: incluso las herramientas con
                          // SSO piden iniciar sesión la primera vez aquí dentro.
                          : h.sso
                              ? 'Con tu cuenta de Guilda Work'
                              : 'Inicia sesión aparte',
                      style: Theme.of(context).textTheme.labelSmall,
                    ),
                  ],
                ),
              );
              if (!h.disponible) {
                return Opacity(opacity: 0.6, child: Card(child: contenido));
              }
              return Card(
                child: InkWell(
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => WebviewScreen(titulo: h.nombre, url: h.url),
                    ),
                  ),
                  child: contenido,
                ),
              );
            },
          );
        },
      ),
    );
  }

  /// Logotipo oficial real (mismo criterio que herramientas.html en la
  /// web: SVG/PNG servido desde app/static/logos/) -- si la herramienta
  /// todavía no tiene `icono_logo` o falla la carga, se cae al emoji de
  /// `icono` para no dejar la tarjeta sin icono.
  Widget _logoHerramienta(Herramienta h, String baseUrl) {
    const tamano = 32.0;
    final respaldo = Text(
      h.icono,
      style: TextStyle(fontSize: 28, color: h.disponible ? null : Theme.of(context).disabledColor),
    );
    if (h.iconoLogo == null) return respaldo;

    final url = '$baseUrl/static/logos/${h.iconoLogo}';
    if (h.iconoLogo!.endsWith('.svg')) {
      return SvgPicture.network(
        url,
        width: tamano,
        height: tamano,
        placeholderBuilder: (_) => const SizedBox(width: tamano, height: tamano),
      );
    }
    return Image.network(
      url,
      width: tamano,
      height: tamano,
      errorBuilder: (_, _, _) => respaldo,
    );
  }
}
