import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
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
    final t = AppLocalizations.of(context);
    final titulo = _tituloController.text.trim();
    if (titulo.isEmpty) {
      setState(() => _error = t.tiquetTituloVacio);
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
    final t = AppLocalizations.of(context);
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(t.tiquetsEliminarTitulo),
        content: Text(t.tiquetEliminarContenidoSimple),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(t.comunCancelar)),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(t.comunEliminar)),
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
    final t = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(t.tiquetEditarTitulo(widget.tiquet.id))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          DropdownButtonFormField<String>(
            initialValue: _tipo,
            decoration: InputDecoration(labelText: t.tiquetTipoLabel),
            items: tiposTiquet(t).map((e) => DropdownMenuItem(value: e.$1, child: Text(e.$2))).toList(),
            onChanged: (v) => setState(() => _tipo = v ?? _tipo),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _tituloController,
            decoration: InputDecoration(labelText: t.tiquetTituloLabel),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _descripcionController,
            decoration: InputDecoration(labelText: t.tiquetDescripcionLabel),
            maxLines: 5,
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 24),
          Row(
            children: [
              FilledButton(onPressed: _guardando ? null : _guardar, child: Text(t.comunGuardar)),
              const SizedBox(width: 12),
              TextButton(onPressed: () => Navigator.pop(context), child: Text(t.comunCancelar)),
            ],
          ),
          const SizedBox(height: 24),
          OutlinedButton(onPressed: _eliminar, child: Text(t.tiquetEliminarBoton)),
        ],
      ),
    );
  }
}
