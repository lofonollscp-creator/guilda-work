import 'package:flutter/material.dart';

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
  late Future<List<Herramienta>> _herramientas;

  @override
  void initState() {
    super.initState();
    _herramientas = widget.api.listarHerramientas();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Herramientas')),
      body: FutureBuilder<List<Herramienta>>(
        future: _herramientas,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text('${snapshot.error}'));
          }
          final herramientas = snapshot.data!;
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
              return Card(
                child: InkWell(
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => WebviewScreen(titulo: h.nombre, url: h.url),
                    ),
                  ),
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(h.icono, style: const TextStyle(fontSize: 28)),
                        const SizedBox(height: 8),
                        Text(h.nombre, style: Theme.of(context).textTheme.titleMedium),
                        const SizedBox(height: 4),
                        Expanded(
                          child: Text(
                            h.descripcion,
                            style: Theme.of(context).textTheme.bodySmall,
                            overflow: TextOverflow.fade,
                          ),
                        ),
                        Text(
                          h.sso ? 'Entra con tu sesión de Guilda Work' : 'Inicia sesión aparte',
                          style: Theme.of(context).textTheme.labelSmall,
                        ),
                      ],
                    ),
                  ),
                ),
              );
            },
          );
        },
      ),
    );
  }
}
