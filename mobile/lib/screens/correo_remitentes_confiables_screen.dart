import 'package:flutter/material.dart';

import '../models/models.dart';
import '../services/api_client.dart';

/// Gestión de remitentes de confianza (Fase 5b): lista + alta por email +
/// borrado, mismo patrón que tareas_outlook_screen.dart.
class CorreoRemitentesConfiablesScreen extends StatefulWidget {
  final ApiClient api;

  const CorreoRemitentesConfiablesScreen({super.key, required this.api});

  @override
  State<CorreoRemitentesConfiablesScreen> createState() => _CorreoRemitentesConfiablesScreenState();
}

class _CorreoRemitentesConfiablesScreenState extends State<CorreoRemitentesConfiablesScreen> {
  late Future<List<RemitenteConfiable>> _remitentes;
  final _direccionController = TextEditingController();
  String? _error;

  @override
  void initState() {
    super.initState();
    _remitentes = widget.api.listarRemitentesConfiables();
  }

  Future<void> _recargar() async {
    final futuro = widget.api.listarRemitentesConfiables();
    setState(() {
      _remitentes = futuro;
    });
    await futuro;
  }

  Future<void> _anadir() async {
    final direccion = _direccionController.text.trim();
    if (direccion.isEmpty) return;
    try {
      await widget.api.confiarEnRemitente(direccion);
      _direccionController.clear();
      await _recargar();
    } catch (e) {
      setState(() => _error = e.toString());
    }
  }

  Future<void> _eliminar(RemitenteConfiable r) async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('¿Quitar de la lista de confianza?'),
        content: Text('"${r.direccion}" volverá a bloquear sus imágenes y avisar antes de abrir adjuntos.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Quitar')),
        ],
      ),
    );
    if (confirmar != true) return;
    await widget.api.eliminarRemitenteConfiable(r.id);
    await _recargar();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Remitentes de confianza')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Sus imágenes remotas y adjuntos se muestran/abren sin avisar.',
                  style: TextStyle(fontSize: 13),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _direccionController,
                        decoration: const InputDecoration(hintText: 'correo@ejemplo.com'),
                        keyboardType: TextInputType.emailAddress,
                        onSubmitted: (_) => _anadir(),
                      ),
                    ),
                    const SizedBox(width: 8),
                    FilledButton(onPressed: _anadir, child: const Text('+ Añadir')),
                  ],
                ),
                if (_error != null) ...[
                  const SizedBox(height: 8),
                  Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
              ],
            ),
          ),
          Expanded(
            child: FutureBuilder<List<RemitenteConfiable>>(
              future: _remitentes,
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snapshot.hasError) {
                  return Center(child: Text('Error al cargar: ${snapshot.error}'));
                }
                final remitentes = snapshot.data ?? [];
                if (remitentes.isEmpty) {
                  return const Center(child: Text('Todavía no tienes ningún remitente de confianza.'));
                }
                return ListView.builder(
                  itemCount: remitentes.length,
                  itemBuilder: (context, i) {
                    final r = remitentes[i];
                    return ListTile(
                      leading: const Icon(Icons.shield_outlined),
                      title: Text(r.direccion),
                      trailing: IconButton(
                        icon: const Icon(Icons.delete_outline),
                        tooltip: 'Eliminar',
                        onPressed: () => _eliminar(r),
                      ),
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
