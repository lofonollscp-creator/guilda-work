import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../widgets/app_button.dart';

/// Edición de un vencimiento fiscal ya creado -- estado, notas y fecha
/// límite (modelo/periodo se ven pero no se editan, calcularlos mal
/// rompería el nombre "modelo del trimestre X"; si hace falta corregirlo
/// de verdad se borra y se genera otro). Calco de tiquet_edit_screen.dart.
class FiscalVencimientoEditScreen extends StatefulWidget {
  final ApiClient api;
  final VencimientoFiscal vencimiento;

  const FiscalVencimientoEditScreen({
    super.key,
    required this.api,
    required this.vencimiento,
  });

  @override
  State<FiscalVencimientoEditScreen> createState() =>
      _FiscalVencimientoEditScreenState();
}

class _FiscalVencimientoEditScreenState
    extends State<FiscalVencimientoEditScreen> {
  late String _estado;
  late final TextEditingController _notasController;
  late DateTime _fechaLimite;
  bool _guardando = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _estado = widget.vencimiento.estado;
    _notasController = TextEditingController(
      text: widget.vencimiento.notas ?? '',
    );
    _fechaLimite = DateTime.parse(
      widget.vencimiento.fechaLimite.substring(0, 10),
    );
  }

  Future<void> _elegirFecha() async {
    final elegida = await showDatePicker(
      context: context,
      initialDate: _fechaLimite,
      firstDate: DateTime(2000),
      lastDate: DateTime(2100),
    );
    if (elegida != null) setState(() => _fechaLimite = elegida);
  }

  Future<void> _guardar() async {
    setState(() {
      _guardando = true;
      _error = null;
    });
    try {
      await widget.api.editarVencimientoFiscal(
        widget.vencimiento.id,
        estado: _estado,
        notas: _notasController.text.trim(),
        fechaLimite:
            '${_fechaLimite.year.toString().padLeft(4, '0')}-${_fechaLimite.month.toString().padLeft(2, '0')}-${_fechaLimite.day.toString().padLeft(2, '0')}',
      );
      if (!mounted) return;
      Navigator.of(context).pop(true);
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
        title: Text(t.fiscalVencimientoEliminarTitulo),
        content: Text(t.fiscalVencimientoEliminarContenido),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(t.comunCancelar),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text(t.comunEliminar),
          ),
        ],
      ),
    );
    if (confirmar != true) return;
    await widget.api.eliminarVencimientoFiscal(widget.vencimiento.id);
    if (!mounted) return;
    Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final v = widget.vencimiento;
    return Scaffold(
      appBar: AppBar(title: Text('${v.modelo} — ${v.clienteNombre}')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            t.fiscalVencimientoPeriodoLabel(v.periodo),
            style: Theme.of(context).textTheme.titleSmall,
          ),
          const SizedBox(height: 16),
          OutlinedButton.icon(
            icon: const Icon(Icons.event_outlined),
            onPressed: _elegirFecha,
            label: Text(
              t.fiscalVencimientoFechaLimiteLabel(
                '${_fechaLimite.year.toString().padLeft(4, '0')}-${_fechaLimite.month.toString().padLeft(2, '0')}-${_fechaLimite.day.toString().padLeft(2, '0')}',
              ),
            ),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _estado,
            decoration: InputDecoration(
              labelText: t.fiscalVencimientoEstadoLabel,
            ),
            items: estadosVencimientoFiscal(t)
                .map((e) => DropdownMenuItem(value: e.$1, child: Text(e.$2)))
                .toList(),
            onChanged: (v) => setState(() => _estado = v ?? _estado),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _notasController,
            decoration: InputDecoration(
              labelText: t.fiscalVencimientoNotasLabel,
            ),
            maxLines: 4,
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
          const SizedBox(height: 24),
          Row(
            children: [
              AppButton(
                texto: t.comunGuardar,
                cargando: _guardando,
                onPressed: _guardar,
              ),
              const SizedBox(width: 12),
              TextButton(
                onPressed: () => Navigator.pop(context),
                child: Text(t.comunCancelar),
              ),
            ],
          ),
          const SizedBox(height: 24),
          OutlinedButton(
            onPressed: _eliminar,
            child: Text(t.fiscalVencimientoEliminarBoton),
          ),
        ],
      ),
    );
  }
}
