import 'package:flutter/material.dart';

import '../models/models.dart';
import '../services/api_client.dart';
import 'tarea_outlook_edit_screen.dart';

/// Lista de tareas "estilo Outlook" (equivalente móvil de
/// app/templates/tareas_lista.html): independiente de los menús, con
/// asunto, prioridad, vencimiento y estado.
class TareasOutlookScreen extends StatefulWidget {
  final ApiClient api;

  const TareasOutlookScreen({super.key, required this.api});

  @override
  State<TareasOutlookScreen> createState() => _TareasOutlookScreenState();
}

class _TareasOutlookScreenState extends State<TareasOutlookScreen> {
  late Future<List<TareaOutlook>> _tareas;
  final _asuntoController = TextEditingController();
  final _buscarController = TextEditingController();
  String _prioridadNueva = 'normal';
  bool _verCompletadas = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _tareas = _cargar();
  }

  Future<List<TareaOutlook>> _cargar() {
    return widget.api.listarTareasOutlook(
      q: _buscarController.text.trim().isEmpty ? null : _buscarController.text.trim(),
    ).then((tareas) => _verCompletadas ? tareas : tareas.where((t) => t.estado != 'completada').toList());
  }

  Future<void> _recargar() async {
    final futuro = _cargar();
    setState(() {
      _tareas = futuro;
    });
    await futuro;
  }

  Future<void> _crear() async {
    final asunto = _asuntoController.text.trim();
    if (asunto.isEmpty) return;
    try {
      await widget.api.crearTareaOutlook(asunto: asunto, prioridad: _prioridadNueva);
      _asuntoController.clear();
      await _recargar();
    } catch (e) {
      setState(() => _error = e.toString());
    }
  }

  Future<void> _completar(TareaOutlook t) async {
    await widget.api.completarTareaOutlook(t.id);
    await _recargar();
  }

  Future<void> _eliminar(TareaOutlook t) async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('¿Eliminar esta tarea?'),
        content: Text('Se moverá a la papelera: "${t.asunto}".'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Eliminar')),
        ],
      ),
    );
    if (confirmar != true) return;
    await widget.api.eliminarTareaOutlook(t.id);
    await _recargar();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Tareas')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _asuntoController,
                        decoration: const InputDecoration(hintText: 'Nueva tarea...'),
                        onSubmitted: (_) => _crear(),
                      ),
                    ),
                    const SizedBox(width: 8),
                    DropdownButton<String>(
                      value: _prioridadNueva,
                      items: prioridadesTareaOutlook
                          .map((p) => DropdownMenuItem(value: p.$1, child: Text(p.$2)))
                          .toList(),
                      onChanged: (v) => setState(() => _prioridadNueva = v ?? 'normal'),
                    ),
                    const SizedBox(width: 8),
                    FilledButton(onPressed: _crear, child: const Text('+ Añadir')),
                  ],
                ),
                if (_error != null) ...[
                  const SizedBox(height: 8),
                  Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
                const SizedBox(height: 12),
                TextField(
                  controller: _buscarController,
                  decoration: const InputDecoration(
                    hintText: 'Buscar...',
                    prefixIcon: Icon(Icons.search),
                  ),
                  onSubmitted: (_) => _recargar(),
                ),
                Row(
                  children: [
                    Checkbox(
                      value: _verCompletadas,
                      onChanged: (v) {
                        setState(() => _verCompletadas = v ?? false);
                        _recargar();
                      },
                    ),
                    const Text('Ver también completadas'),
                  ],
                ),
              ],
            ),
          ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: _recargar,
              child: FutureBuilder<List<TareaOutlook>>(
                future: _tareas,
                builder: (context, snapshot) {
                  if (snapshot.connectionState != ConnectionState.done) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (snapshot.hasError) {
                    return Center(child: Text('Error al cargar: ${snapshot.error}'));
                  }
                  final tareas = snapshot.data ?? [];
                  if (tareas.isEmpty) {
                    return ListView(
                      children: const [
                        Padding(
                          padding: EdgeInsets.all(24),
                          child: Text('No hay tareas para este filtro.'),
                        ),
                      ],
                    );
                  }
                  return ListView.builder(
                    itemCount: tareas.length,
                    itemBuilder: (context, i) => _tarjetaTarea(tareas[i]),
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _tarjetaTarea(TareaOutlook t) {
    final completada = t.estado == 'completada';
    return ListTile(
      leading: IconButton(
        icon: Icon(completada ? Icons.check_circle : Icons.radio_button_unchecked),
        tooltip: 'Marcar como completada',
        onPressed: completada ? null : () => _completar(t),
      ),
      title: Text(
        t.asunto,
        style: completada ? const TextStyle(decoration: TextDecoration.lineThrough) : null,
      ),
      subtitle: Row(
        children: [
          Text(t.prioridad),
          if (t.categoriaOutlook != null) ...[
            const SizedBox(width: 8),
            Text('· ${t.categoriaOutlook}'),
          ],
          if (t.fechaVencimiento != null) ...[
            const SizedBox(width: 8),
            Text('· Vence ${t.fechaVencimiento!.substring(0, 10)}'),
          ],
        ],
      ),
      trailing: IconButton(
        icon: const Icon(Icons.delete_outline),
        tooltip: 'Eliminar',
        onPressed: () => _eliminar(t),
      ),
      onTap: () async {
        await Navigator.of(context).push(
          MaterialPageRoute(builder: (_) => TareaOutlookEditScreen(tarea: t, api: widget.api)),
        );
        await _recargar();
      },
    );
  }
}
