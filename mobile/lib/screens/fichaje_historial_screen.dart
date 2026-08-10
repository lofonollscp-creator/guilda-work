import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
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

  String _fecha(DateTime? d, AppLocalizations t) => d == null ? t.fichajeHistorialCualquiera : d.toIso8601String().substring(0, 10);

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(t.fichajeHistorialTitulo)),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => _elegirFecha(esDesde: true),
                    child: Text(t.fichajeHistorialDesde(_fecha(_desde, t))),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => _elegirFecha(esDesde: false),
                    child: Text(t.fichajeHistorialHasta(_fecha(_hasta, t))),
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
                    return Center(child: Text(t.comunErrorCargar(snapshot.error.toString())));
                  }
                  final fichajes = snapshot.data ?? [];
                  if (fichajes.isEmpty) {
                    return ListView(
                      children: [
                        Padding(
                          padding: const EdgeInsets.all(24),
                          child: Text(t.fichajeHistorialSinFichajes),
                        ),
                      ],
                    );
                  }
                  final etiquetas = etiquetasFichaje(t);
                  return ListView.builder(
                    itemCount: fichajes.length,
                    itemBuilder: (context, i) {
                      final f = fichajes[i];
                      return ListTile(
                        leading: const Icon(Icons.access_time),
                        title: Text(etiquetas[f.tipo] ?? f.tipo),
                        subtitle: Text('${f.marcaTiempo.substring(0, 10)} · ${f.marcaTiempo.substring(11, 16)}'),
                        trailing: f.origen == 'correccion_admin' ? Tooltip(message: t.fichajeHistorialCorreccionAdmin, child: const Icon(Icons.info_outline)) : null,
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
