import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../widgets/app_button.dart';

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
    final nombre = _nombreController.text.trim();
    final dni = _dniController.text.trim();
    if (nombre.isEmpty || dni.isEmpty) {
      setState(() => _error = 'Nombre completo y DNI/NIE son obligatorios: la normativa exige poder identificarte.');
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
    return Scaffold(
      appBar: AppBar(title: const Text('Mis datos de fichaje')),
      body: _cargando
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                TextField(
                  controller: _nombreController,
                  decoration: const InputDecoration(labelText: 'Nombre completo *'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _dniController,
                  decoration: const InputDecoration(labelText: 'DNI/NIE *'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _numAfiliacionController,
                  decoration: const InputDecoration(labelText: 'Nº de afiliación a la Seguridad Social'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _categoriaController,
                  decoration: const InputDecoration(labelText: 'Categoría profesional'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _contratoController,
                  decoration: const InputDecoration(labelText: 'Tipo de contrato'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _fechaAltaController,
                  readOnly: true,
                  decoration: const InputDecoration(labelText: 'Fecha de alta'),
                  onTap: _elegirFecha,
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _jornadaController,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: const InputDecoration(labelText: 'Jornada semanal contratada (horas)'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _convenioController,
                  decoration: const InputDecoration(labelText: 'Convenio colectivo'),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
                const SizedBox(height: 24),
                AppButton(texto: 'Guardar', cargando: _guardando, onPressed: _guardar),
              ],
            ),
    );
  }
}
