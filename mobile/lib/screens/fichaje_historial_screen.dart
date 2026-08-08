import 'package:flutter/material.dart';

import '../models/models.dart';
import '../services/api_client.dart';

/// Historial propio de fichajes (equivalente móvil de
/// app/templates/fichaje_historial.html), filtrable por fecha.
class FichajeHistorialScreen extends StatefulWidget {
  final ApiClient api;

  const FichajeHistorialScreen({super.key, required this.api});

  @override
  State<FichajeHistorialScreen> createState() => _FichajeHistorialScreenState();
}

class _FichajeHistorialScreenState extends State<FichajeHistorialScreen> {
  late Future<List<FichajeEvento>> _fichajes;
  DateTime? _desde;
  DateTime? _hasta;

  @override
  void initState() {
    super.initState();
    _fichajes = _cargar();
  }

  Future<List<FichajeEvento>> _cargar() {
    return widget.api.listarMisFichajes(
      desde: _desde?.toIso8601String().substring(0, 10),
      hasta: _hasta?.toIso8601String().substring(0, 10),
    );
  }

  Future<void> _recargar() async {
    final futuro = _cargar();
    setState(() => _fichajes = futuro);
    await futuro;
  }

  Future<void> _elegirFecha({required bool esDesde}) async {
    final elegida = await showDatePicker(
      context: context,
      initialDate: (esDesde ? _desde : _hasta) ?? DateTime.now(),
      firstDate: DateTime(2000),
      lastDate: DateTime(2100),
    );
    if (elegida == null) return;
    setState(() {
      if (esDesde) {
        _desde = elegida;
      } else {
        _hasta = elegida;
      }
    });
    await _recargar();
  }

  String _fecha(DateTime? d) => d == null ? 'Cualquiera' : d.toIso8601String().substring(0, 10);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Mi historial de fichaje')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => _elegirFecha(esDesde: true),
                    child: Text('Desde: ${_fecha(_desde)}'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => _elegirFecha(esDesde: false),
                    child: Text('Hasta: ${_fecha(_hasta)}'),
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: _recargar,
              child: FutureBuilder<List<FichajeEvento>>(
                future: _fichajes,
                builder: (context, snapshot) {
                  if (snapshot.connectionState != ConnectionState.done) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (snapshot.hasError) {
                    return Center(child: Text('Error al cargar: ${snapshot.error}'));
                  }
                  final fichajes = snapshot.data ?? [];
                  if (fichajes.isEmpty) {
                    return ListView(
                      children: const [
                        Padding(
                          padding: EdgeInsets.all(24),
                          child: Text('Sin fichajes en este periodo.'),
                        ),
                      ],
                    );
                  }
                  return ListView.builder(
                    itemCount: fichajes.length,
                    itemBuilder: (context, i) {
                      final f = fichajes[i];
                      return ListTile(
                        leading: const Icon(Icons.access_time),
                        title: Text(etiquetasFichaje[f.tipo] ?? f.tipo),
                        subtitle: Text('${f.marcaTiempo.substring(0, 10)} · ${f.marcaTiempo.substring(11, 16)}'),
                        trailing: f.origen == 'correccion_admin' ? const Tooltip(message: 'Corrección de un administrador', child: Icon(Icons.info_outline)) : null,
                      );
                    },
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }
}
