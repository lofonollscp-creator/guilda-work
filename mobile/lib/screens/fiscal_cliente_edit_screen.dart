import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../widgets/app_button.dart';

/// Alta/edición de un cliente fiscal -- calco de tiquet_edit_screen.dart,
/// con los modelos que presenta (checkboxes) y la casilla de generación
/// automática (Fase F4) añadidos. `cliente == null` es alta.
class FiscalClienteEditScreen extends StatefulWidget {
  final ApiClient api;
  final ClienteFiscal? cliente;

  const FiscalClienteEditScreen({super.key, required this.api, this.cliente});

  @override
  State<FiscalClienteEditScreen> createState() =>
      _FiscalClienteEditScreenState();
}

class _FiscalClienteEditScreenState extends State<FiscalClienteEditScreen> {
  late final TextEditingController _nombreController;
  late final TextEditingController _nifController;
  late final TextEditingController _notasController;
  late Set<String> _modelosSeleccionados;
  bool _generacionAutomatica = false;
  bool _guardando = false;
  bool _generandoVencimientos = false;
  String? _error;

  bool get _esAlta => widget.cliente == null;

  @override
  void initState() {
    super.initState();
    final c = widget.cliente;
    _nombreController = TextEditingController(text: c?.nombre ?? '');
    _nifController = TextEditingController(text: c?.nif ?? '');
    _notasController = TextEditingController(text: c?.notas ?? '');
    _modelosSeleccionados = {...(c?.modelosFiscales ?? const [])};
    _generacionAutomatica = c?.generacionAutomatica ?? false;
  }

  Future<void> _guardar() async {
    final t = AppLocalizations.of(context);
    final nombre = _nombreController.text.trim();
    if (nombre.isEmpty) {
      setState(() => _error = t.fiscalClienteNombreVacio);
      return;
    }
    setState(() {
      _guardando = true;
      _error = null;
    });
    try {
      if (_esAlta) {
        await widget.api.crearClienteFiscal(
          nombre: nombre,
          nif: _nifController.text.trim(),
          notas: _notasController.text.trim(),
          modelosFiscales: _modelosSeleccionados.toList(),
        );
      } else {
        await widget.api.editarClienteFiscal(
          widget.cliente!.id,
          nombre: nombre,
          nif: _nifController.text.trim(),
          notas: _notasController.text.trim(),
          modelosFiscales: _modelosSeleccionados.toList(),
          generacionAutomatica: _generacionAutomatica,
        );
      }
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
        title: Text(t.fiscalClienteEliminarTitulo),
        content: Text(t.fiscalClienteEliminarContenido),
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
    await widget.api.eliminarClienteFiscal(widget.cliente!.id);
    if (!mounted) return;
    Navigator.of(context).pop(true);
  }

  /// Genera e inserta directamente los vencimientos del año en curso para
  /// los modelos marcados -- solo disponible al editar (necesita el id
  /// del cliente ya creado). A diferencia de la web, no hay paso de
  /// revisar/editar cada fecha propuesta antes de guardar (ver
  /// ApiClient.generarVencimientosFiscales).
  Future<void> _generarVencimientos() async {
    final t = AppLocalizations.of(context);
    if (_modelosSeleccionados.isEmpty) {
      setState(() => _error = t.fiscalGenerarSinModelos);
      return;
    }
    setState(() => _generandoVencimientos = true);
    try {
      final anio = DateTime.now().year;
      final creados = await widget.api.generarVencimientosFiscales(
        widget.cliente!.id,
        _modelosSeleccionados.toList(),
        anio,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(t.fiscalGenerarResultado(creados))),
      );
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _generandoVencimientos = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(
          _esAlta ? t.fiscalClienteNuevoTitulo : t.fiscalClienteEditarTitulo,
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _nombreController,
            decoration: InputDecoration(labelText: t.fiscalClienteNombreLabel),
            autofocus: _esAlta,
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _nifController,
            decoration: InputDecoration(labelText: t.fiscalClienteNifLabel),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _notasController,
            decoration: InputDecoration(labelText: t.fiscalClienteNotasLabel),
            maxLines: 3,
          ),
          const SizedBox(height: 20),
          Text(
            t.fiscalModelosLabel,
            style: Theme.of(context).textTheme.titleSmall,
          ),
          const SizedBox(height: 4),
          Text(
            t.fiscalModelosSubtitulo,
            style: Theme.of(context).textTheme.bodySmall,
          ),
          for (final entry in modelosFiscalesDisponibles.entries)
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              dense: true,
              value: _modelosSeleccionados.contains(entry.key),
              title: Text('${entry.key} — ${entry.value}'),
              onChanged: (marcado) => setState(() {
                if (marcado ?? false) {
                  _modelosSeleccionados.add(entry.key);
                } else {
                  _modelosSeleccionados.remove(entry.key);
                }
              }),
            ),
          if (!_esAlta) ...[
            const SizedBox(height: 8),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              value: _generacionAutomatica,
              title: Text(t.fiscalGeneracionAutomaticaLabel),
              subtitle: Text(t.fiscalGeneracionAutomaticaSubtitulo),
              onChanged: (v) => setState(() => _generacionAutomatica = v),
            ),
          ],
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
          if (!_esAlta) ...[
            const SizedBox(height: 16),
            AppButton(
              texto: t.fiscalGenerarVencimientosBoton,
              secundario: true,
              cargando: _generandoVencimientos,
              onPressed: _generarVencimientos,
            ),
            const SizedBox(height: 24),
            OutlinedButton(
              onPressed: _eliminar,
              child: Text(t.fiscalClienteEliminarBoton),
            ),
          ],
        ],
      ),
    );
  }
}
