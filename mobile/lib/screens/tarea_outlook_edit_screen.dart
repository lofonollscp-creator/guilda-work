import 'package:flutter/material.dart';

import '../models/models.dart';
import '../services/api_client.dart';

/// Edición de una tarea Outlook (equivalente móvil de
/// app/templates/tarea_outlook_editar.html): todos los campos editables.
class TareaOutlookEditScreen extends StatefulWidget {
  final TareaOutlook tarea;
  final ApiClient api;

  const TareaOutlookEditScreen({super.key, required this.tarea, required this.api});

  @override
  State<TareaOutlookEditScreen> createState() => _TareaOutlookEditScreenState();
}

class _TareaOutlookEditScreenState extends State<TareaOutlookEditScreen> {
  late final TextEditingController _asuntoController;
  late final TextEditingController _cuerpoController;
  late final TextEditingController _categoriaController;
  late String _estado;
  late String _prioridad;
  late int _porcentaje;
  late final TextEditingController _fechaInicioController;
  late final TextEditingController _fechaVencimientoController;
  bool _guardando = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final t = widget.tarea;
    _asuntoController = TextEditingController(text: t.asunto);
    _cuerpoController = TextEditingController(text: t.cuerpo ?? '');
    _categoriaController = TextEditingController(text: t.categoriaOutlook ?? '');
    _estado = t.estado;
    _prioridad = t.prioridad;
    _porcentaje = t.porcentajeCompletado;
    _fechaInicioController = TextEditingController(
      text: t.fechaInicio != null ? t.fechaInicio!.substring(0, 10) : '',
    );
    _fechaVencimientoController = TextEditingController(
      text: t.fechaVencimiento != null ? t.fechaVencimiento!.substring(0, 10) : '',
    );
  }

  Future<void> _elegirFecha(TextEditingController controlador) async {
    final actual = DateTime.tryParse(controlador.text);
    final elegida = await showDatePicker(
      context: context,
      initialDate: actual ?? DateTime.now(),
      firstDate: DateTime(2000),
      lastDate: DateTime(2100),
    );
    if (elegida != null) {
      controlador.text = elegida.toIso8601String().substring(0, 10);
    }
  }

  Future<void> _guardar() async {
    final asunto = _asuntoController.text.trim();
    if (asunto.isEmpty) {
      setState(() => _error = 'El asunto no puede estar vacío.');
      return;
    }
    setState(() {
      _guardando = true;
      _error = null;
    });
    try {
      await widget.api.editarTareaOutlook(widget.tarea.id, {
        'asunto': asunto,
        'cuerpo': _cuerpoController.text.trim(),
        'estado': _estado,
        'prioridad': _prioridad,
        'porcentaje_completado': _porcentaje,
        'fecha_inicio': _fechaInicioController.text.isEmpty ? null : _fechaInicioController.text,
        'fecha_vencimiento': _fechaVencimientoController.text.isEmpty ? null : _fechaVencimientoController.text,
        'categoria_outlook': _categoriaController.text.trim(),
      });
      if (!mounted) return;
      Navigator.of(context).pop();
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _guardando = false);
    }
  }

  Future<void> _eliminar() async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('¿Eliminar esta tarea?'),
        content: const Text('Se moverá a la papelera.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Eliminar')),
        ],
      ),
    );
    if (confirmar != true) return;
    await widget.api.eliminarTareaOutlook(widget.tarea.id);
    if (!mounted) return;
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Editar tarea')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _asuntoController,
            decoration: const InputDecoration(labelText: 'Asunto'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _cuerpoController,
            decoration: const InputDecoration(labelText: 'Descripción'),
            maxLines: 4,
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _estado,
            decoration: const InputDecoration(labelText: 'Estado'),
            items: estadosTareaOutlook.map((e) => DropdownMenuItem(value: e.$1, child: Text(e.$2))).toList(),
            onChanged: (v) => setState(() => _estado = v ?? _estado),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _prioridad,
            decoration: const InputDecoration(labelText: 'Prioridad'),
            items: prioridadesTareaOutlook.map((p) => DropdownMenuItem(value: p.$1, child: Text(p.$2))).toList(),
            onChanged: (v) => setState(() => _prioridad = v ?? _prioridad),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              const Text('% completado: '),
              Expanded(
                child: Slider(
                  value: _porcentaje.toDouble(),
                  min: 0,
                  max: 100,
                  divisions: 10,
                  label: '$_porcentaje%',
                  onChanged: (v) => setState(() => _porcentaje = v.round()),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _fechaInicioController,
            readOnly: true,
            decoration: const InputDecoration(labelText: 'Fecha de inicio'),
            onTap: () => _elegirFecha(_fechaInicioController),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _fechaVencimientoController,
            readOnly: true,
            decoration: const InputDecoration(labelText: 'Fecha de vencimiento'),
            onTap: () => _elegirFecha(_fechaVencimientoController),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _categoriaController,
            decoration: const InputDecoration(labelText: 'Categoría (ej. Trabajo, Personal...)'),
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 24),
          Row(
            children: [
              FilledButton(onPressed: _guardando ? null : _guardar, child: const Text('Guardar')),
              const SizedBox(width: 12),
              TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancelar')),
            ],
          ),
          const SizedBox(height: 24),
          OutlinedButton(onPressed: _eliminar, child: const Text('🗑 Eliminar tarea')),
        ],
      ),
    );
  }
}
