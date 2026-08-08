import 'package:flutter/material.dart';

import '../models/models.dart';
import '../services/api_client.dart';

/// Edición de un tiquet propio (equivalente móvil de
/// app/templates/tiquet_editar.html) -- solo alcanzable mientras siga
/// "sin_revisar" y sea del usuario actual (TiquetsScreen ya filtra el
/// onTap con ese mismo criterio, esta pantalla no repite el chequeo).
class TiquetEditScreen extends StatefulWidget {
  final Tiquet tiquet;
  final ApiClient api;

  const TiquetEditScreen({super.key, required this.tiquet, required this.api});

  @override
  State<TiquetEditScreen> createState() => _TiquetEditScreenState();
}

class _TiquetEditScreenState extends State<TiquetEditScreen> {
  late final TextEditingController _tituloController;
  late final TextEditingController _descripcionController;
  late String _tipo;
  bool _guardando = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _tituloController = TextEditingController(text: widget.tiquet.titulo);
    _descripcionController = TextEditingController(text: widget.tiquet.descripcion ?? '');
    _tipo = widget.tiquet.tipo;
  }

  Future<void> _guardar() async {
    final titulo = _tituloController.text.trim();
    if (titulo.isEmpty) {
      setState(() => _error = 'El título no puede estar vacío.');
      return;
    }
    setState(() {
      _guardando = true;
      _error = null;
    });
    try {
      await widget.api.editarTiquet(
        widget.tiquet.id,
        titulo: titulo,
        descripcion: _descripcionController.text.trim(),
        tipo: _tipo,
      );
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
        title: const Text('¿Eliminar este tiquet?'),
        content: const Text('No se puede deshacer.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Eliminar')),
        ],
      ),
    );
    if (confirmar != true) return;
    await widget.api.eliminarTiquet(widget.tiquet.id);
    if (!mounted) return;
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Editar tiquet #${widget.tiquet.id}')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          DropdownButtonFormField<String>(
            initialValue: _tipo,
            decoration: const InputDecoration(labelText: 'Tipo'),
            items: tiposTiquet.map((t) => DropdownMenuItem(value: t.$1, child: Text(t.$2))).toList(),
            onChanged: (v) => setState(() => _tipo = v ?? _tipo),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _tituloController,
            decoration: const InputDecoration(labelText: 'Título'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _descripcionController,
            decoration: const InputDecoration(labelText: 'Descripción'),
            maxLines: 5,
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
          OutlinedButton(onPressed: _eliminar, child: const Text('🗑 Eliminar tiquet')),
        ],
      ),
    );
  }
}
