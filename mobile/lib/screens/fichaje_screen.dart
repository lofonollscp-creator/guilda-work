import 'package:flutter/material.dart';

import '../models/models.dart';
import '../services/api_client.dart';
import 'fichaje_datos_screen.dart';
import 'fichaje_historial_screen.dart';

/// Panel de fichaje del trabajador (equivalente móvil de
/// app/templates/fichaje_panel.html): estado actual + botones grandes de
/// Entrada/Pausa/Fin de pausa/Salida, y los fichajes de hoy. Sin las
/// vistas de administración (revisar horas de un tenant no es una tarea
/// de móvil, se queda en web/escritorio -- ver app/rutas_fichaje.py).
class FichajeScreen extends StatefulWidget {
  final ApiClient api;

  const FichajeScreen({super.key, required this.api});

  @override
  State<FichajeScreen> createState() => _FichajeScreenState();
}

class _FichajeScreenState extends State<FichajeScreen> {
  late Future<(String, bool)> _estado;
  Future<List<FichajeEvento>>? _hoy;
  String? _error;
  bool _marcando = false;

  @override
  void initState() {
    super.initState();
    _estado = _cargar();
  }

  Future<(String, bool)> _cargar() async {
    final estado = await widget.api.obtenerEstadoFichaje();
    if (estado.$2) {
      final hoy = DateTime.now().toIso8601String().substring(0, 10);
      setState(() => _hoy = widget.api.listarMisFichajes(desde: hoy, hasta: hoy));
    }
    return estado;
  }

  Future<void> _recargar() async {
    final futuro = _cargar();
    setState(() {
      _estado = futuro;
      _error = null;
    });
    await futuro;
  }

  Future<void> _marcar(String tipo) async {
    setState(() {
      _marcando = true;
      _error = null;
    });
    try {
      await widget.api.fichar(tipo);
      await _recargar();
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _marcando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Fichaje'),
        actions: [
          IconButton(
            icon: const Icon(Icons.history),
            tooltip: 'Mi historial',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => FichajeHistorialScreen(api: widget.api)),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.badge_outlined),
            tooltip: 'Mis datos',
            onPressed: () async {
              await Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => FichajeDatosScreen(api: widget.api)),
              );
              await _recargar();
            },
          ),
        ],
      ),
      body: FutureBuilder<(String, bool)>(
        future: _estado,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text('Error al cargar: ${snapshot.error}'));
          }
          final (estado, datosCompletos) = snapshot.data!;
          if (!datosCompletos) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Text(
                      'Antes de fichar, la normativa exige poder identificarte: rellena tu nombre completo y DNI/NIE.',
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 16),
                    FilledButton(
                      onPressed: () async {
                        await Navigator.of(context).push(
                          MaterialPageRoute(builder: (_) => FichajeDatosScreen(api: widget.api)),
                        );
                        await _recargar();
                      },
                      child: const Text('Rellenar mis datos'),
                    ),
                  ],
                ),
              ),
            );
          }
          return RefreshIndicator(
            onRefresh: _recargar,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Center(child: _pillEstado(estado)),
                const SizedBox(height: 20),
                if (_error != null) ...[
                  Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                  const SizedBox(height: 12),
                ],
                Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  alignment: WrapAlignment.center,
                  children: [
                    _botonFichar('Entrada', Colors.green, estado == 'fuera', () => _marcar('entrada')),
                    _botonFichar('Iniciar pausa', Colors.amber.shade800, estado == 'dentro', () => _marcar('pausa_inicio')),
                    _botonFichar('Fin de pausa', Colors.amber.shade800, estado == 'en_pausa', () => _marcar('pausa_fin')),
                    _botonFichar('Salida', Colors.red, estado != 'fuera', () => _marcar('salida')),
                  ],
                ),
                const SizedBox(height: 32),
                Text('Hoy', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                if (_hoy != null)
                  FutureBuilder<List<FichajeEvento>>(
                    future: _hoy,
                    builder: (context, snap) {
                      if (snap.connectionState != ConnectionState.done) {
                        return const Padding(
                          padding: EdgeInsets.all(16),
                          child: Center(child: CircularProgressIndicator()),
                        );
                      }
                      final eventos = snap.data ?? [];
                      if (eventos.isEmpty) {
                        return const Padding(
                          padding: EdgeInsets.all(8),
                          child: Text('Todavía no has fichado nada hoy.'),
                        );
                      }
                      return Column(
                        children: eventos
                            .map((f) => ListTile(
                                  dense: true,
                                  leading: const Icon(Icons.access_time),
                                  title: Text(etiquetasFichaje[f.tipo] ?? f.tipo),
                                  trailing: Text(f.marcaTiempo.substring(11, 16)),
                                ))
                            .toList(),
                      );
                    },
                  ),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _pillEstado(String estado) {
    final (texto, color) = switch (estado) {
      'dentro' => ('Dentro de jornada', Colors.green),
      'en_pausa' => ('En pausa', Colors.amber.shade800),
      _ => ('Fuera de jornada', Colors.grey),
    };
    return Chip(
      label: Text(texto, style: const TextStyle(color: Colors.white)),
      backgroundColor: color,
    );
  }

  Widget _botonFichar(String texto, Color color, bool habilitado, VoidCallback onPressed) {
    return SizedBox(
      width: 150,
      height: 56,
      child: FilledButton(
        style: FilledButton.styleFrom(backgroundColor: habilitado ? color : null),
        onPressed: (habilitado && !_marcando) ? onPressed : null,
        child: Text(texto),
      ),
    );
  }
}
