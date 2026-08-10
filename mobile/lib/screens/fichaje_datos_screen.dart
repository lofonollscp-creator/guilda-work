import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../services/api_client.dart';

/// Datos personales del trabajador para el fichaje (equivalente móvil de
/// app/templates/fichaje_datos.html) -- nombreCompleto+dniNie son
/// obligatorios antes de poder fichar por primera vez.
class FichajeDatosScreen extends StatefulWidget {
  final ApiClient api;

  const FichajeDatosScreen({super.key, required this.api});

  @override
  State<FichajeDatosScreen> createState() => _FichajeDatosScreenState();
}

class _FichajeDatosScreenState extends State<FichajeDatosScreen> {
  final _nombreController = TextEditingController();
  final _dniController = TextEditingController();
  final _numAfiliacionController = TextEditingController();
  final _categoriaController = TextEditingController();
  final _contratoController = TextEditingController();
  final _fechaAltaController = TextEditingController();
  final _jornadaController = TextEditingController();
  final _convenioController = TextEditingController();
  bool _cargando = true;
  bool _guardando = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _cargar();
  }

  Future<void> _cargar() async {
    try {
      final datos = await widget.api.obtenerFichajeDatos();
      _nombreController.text = datos.nombreCompleto ?? '';
      _dniController.text = datos.dniNie ?? '';
      _numAfiliacionController.text = datos.numeroAfiliacionSs ?? '';
      _categoriaController.text = datos.categoriaProfesional ?? '';
      _contratoController.text = datos.tipoContrato ?? '';
      _fechaAltaController.text = datos.fechaAlta != null ? datos.fechaAlta!.substring(0, 10) : '';
      _jornadaController.text = datos.jornadaSemanalHoras?.toString() ?? '';
      _convenioController.text = datos.convenioColectivo ?? '';
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _cargando = false);
    }
  }

  Future<void> _elegirFecha() async {
    final actual = DateTime.tryParse(_fechaAltaController.text);
    final elegida = await showDatePicker(
      context: context,
      initialDate: actual ?? DateTime.now(),
      firstDate: DateTime(2000),
      lastDate: DateTime(2100),
    );
    if (elegida != null) {
      _fechaAltaController.text = elegida.toIso8601String().substring(0, 10);
    }
  }

  Future<void> _guardar() async {
    final t = AppLocalizations.of(context);
    final nombre = _nombreController.text.trim();
    final dni = _dniController.text.trim();
    if (nombre.isEmpty || dni.isEmpty) {
      setState(() => _error = t.fichajeDatosObligatorios);
      return;
    }
    setState(() {
      _guardando = true;
      _error = null;
    });
    try {
      final jornada = _jornadaController.text.trim();
      await widget.api.guardarFichajeDatos(
        nombreCompleto: nombre,
        dniNie: dni,
        numeroAfiliacionSs: _numAfiliacionController.text.trim(),
        categoriaProfesional: _categoriaController.text.trim(),
        tipoContrato: _contratoController.text.trim(),
        fechaAlta: _fechaAltaController.text.isEmpty ? null : _fechaAltaController.text,
        jornadaSemanalHoras: jornada.isEmpty ? null : double.tryParse(jornada),
        convenioColectivo: _convenioController.text.trim(),
      );
      if (!mounted) return;
      Navigator.of(context).pop();
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _guardando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(t.fichajeDatosTitulo)),
      body: _cargando
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                TextField(
                  controller: _nombreController,
                  decoration: InputDecoration(labelText: t.fichajeDatosNombreLabel),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _dniController,
                  decoration: InputDecoration(labelText: t.fichajeDatosDniLabel),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _numAfiliacionController,
                  decoration: InputDecoration(labelText: t.fichajeDatosAfiliacionLabel),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _categoriaController,
                  decoration: InputDecoration(labelText: t.fichajeDatosCategoriaLabel),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _contratoController,
                  decoration: InputDecoration(labelText: t.fichajeDatosContratoLabel),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _fechaAltaController,
                  readOnly: true,
                  decoration: InputDecoration(labelText: t.fichajeDatosFechaAltaLabel),
                  onTap: _elegirFecha,
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _jornadaController,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: InputDecoration(labelText: t.fichajeDatosJornadaLabel),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _convenioController,
                  decoration: InputDecoration(labelText: t.fichajeDatosConvenioLabel),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
                const SizedBox(height: 24),
                FilledButton(onPressed: _guardando ? null : _guardar, child: Text(t.comunGuardar)),
              ],
            ),
    );
  }
}
