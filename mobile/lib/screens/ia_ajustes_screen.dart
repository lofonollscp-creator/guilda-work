import 'package:flutter/material.dart';

import '../diseno/adaptable.dart';

import '../diseno/asistente.dart';

import '../l10n/app_localizations.dart';

import '../models/models.dart';
import '../services/api_client.dart';
import '../widgets/app_button.dart';

/// Ajustes del Asistente IA en el móvil -- SOLO modelo y modo autónomo
/// (comparten la misma fila `ia_preferencias` que la web, así que cambiarlos
/// aquí también afecta al chat en el navegador y viceversa). La clave de API
/// de OpenRouter NO se puede tocar desde aquí a propósito: se gestiona
/// exclusivamente en /ia/ajustes de la web (ver plan "eventual-herding-kitten",
/// Fase 2) -- aquí solo se muestra si hay una configurada o no.
class IaAjustesScreen extends StatefulWidget {
  final ApiClient api;

  const IaAjustesScreen({super.key, required this.api});

  @override
  State<IaAjustesScreen> createState() => _IaAjustesScreenState();
}

class _IaAjustesScreenState extends State<IaAjustesScreen> {
  bool _cargando = true;
  bool _guardando = false;
  String? _error;

  List<IaModelo> _modelos = [];
  String _modeloSeleccionado = '';
  bool _modoAutonomo = false;
  bool _apiKeyConfigurada = false;

  @override
  void initState() {
    super.initState();
    _cargar();
  }

  Future<void> _cargar() async {
    setState(() {
      _cargando = true;
      _error = null;
    });
    try {
      final resultados = await Future.wait([
        widget.api.obtenerAjustesIa(),
        widget.api.listarModelosIa(),
      ]);
      final ajustes = resultados[0] as IaAjustes;
      final modelos = resultados[1] as List<IaModelo>;
      setState(() {
        _modelos = modelos;
        _modeloSeleccionado = ajustes.modelo;
        _modoAutonomo = ajustes.modoAutonomo;
        _apiKeyConfigurada = ajustes.apiKeyConfigurada;
      });
    } on ApiException catch (e) {
      setState(() => _error = e.mensaje);
    } finally {
      if (mounted) setState(() => _cargando = false);
    }
  }

  Future<void> _guardar() async {
    setState(() => _guardando = true);
    try {
      await widget.api.guardarAjustesIa(modelo: _modeloSeleccionado, modoAutonomo: _modoAutonomo);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(AppLocalizations.of(context).iaAjustesGuardados)));
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.mensaje)));
    } finally {
      if (mounted) setState(() => _guardando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(AppLocalizations.of(context).iaAjustesTitulo)),
      body: AnchoMaximo(child: _cargando
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(_error!, textAlign: TextAlign.center),
                        const SizedBox(height: 12),
                        FilledButton(onPressed: _cargar, child: Text(AppLocalizations.of(context).estadoVacioReintentar)),
                      ],
                    ),
                  ),
                )
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    const Align(alignment: Alignment.centerLeft, child: InsigniaIa(tamano: 44)),
                    const SizedBox(height: 12),
                    AvisoIa(texto: AppLocalizations.of(context).iaAviso),
                    const SizedBox(height: 20),
                    Text(AppLocalizations.of(context).iaAjustesModelo, style: Theme.of(context).textTheme.titleSmall),
                    const SizedBox(height: 8),
                    _selectorModelo(),
                    const SizedBox(height: 24),
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text(AppLocalizations.of(context).iaAjustesAutonomo),
                      subtitle: Text(AppLocalizations.of(context).iaAjustesAutonomoAyuda),
                      value: _modoAutonomo,
                      onChanged: (v) => setState(() => _modoAutonomo = v),
                    ),
                    const Divider(height: 32),
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: Icon(
                        _apiKeyConfigurada ? Icons.check_circle_outline : Icons.error_outline,
                        color: _apiKeyConfigurada
                            ? Theme.of(context).colorScheme.primary
                            : Theme.of(context).colorScheme.error,
                      ),
                      title: Text(_apiKeyConfigurada
                          ? AppLocalizations.of(context).iaAjustesClaveSi
                          : AppLocalizations.of(context).iaAjustesClaveNo),
                      subtitle: Text(AppLocalizations.of(context).iaAjustesClaveAyuda),
                    ),
                    const SizedBox(height: 16),
                    SizedBox(
                      width: double.infinity,
                      child: AppButton(texto: AppLocalizations.of(context).comunGuardar, cargando: _guardando, onPressed: _guardar),
                    ),
                  ],
                )),
    );
  }

  Widget _selectorModelo() {
    // El modelo guardado puede no estar en la lista de gratuitos (elegido
    // como "modelo personalizado" desde la web, o de pago) -- se añade como
    // opción extra para no perder la selección actual al abrir esta pantalla.
    final idsConocidos = _modelos.map((m) => m.id).toSet();
    final opciones = [
      ..._modelos,
      if (_modeloSeleccionado.isNotEmpty && !idsConocidos.contains(_modeloSeleccionado))
        IaModelo(id: _modeloSeleccionado, nombre: AppLocalizations.of(context).iaAjustesModeloActual(_modeloSeleccionado)),
    ];
    if (opciones.isEmpty) {
      return Text(AppLocalizations.of(context).iaAjustesSinModelos);
    }
    return DropdownButtonFormField<String>(
      initialValue: _modeloSeleccionado.isEmpty ? null : _modeloSeleccionado,
      decoration: const InputDecoration(border: OutlineInputBorder(), isDense: true),
      hint: Text(AppLocalizations.of(context).iaAjustesElegirModelo),
      isExpanded: true,
      items: opciones
          .map((m) => DropdownMenuItem(value: m.id, child: Text(m.nombre, overflow: TextOverflow.ellipsis)))
          .toList(),
      onChanged: (v) => setState(() => _modeloSeleccionado = v ?? ''),
    );
  }
}
