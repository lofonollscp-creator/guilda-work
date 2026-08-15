import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import 'fiscal_cliente_edit_screen.dart';

/// Lista de clientes fiscales de la gestoría -- calco de tiquets_screen.dart
/// (alta inline + búsqueda + lista, edición en pantalla aparte). A
/// diferencia de la web, no hay "ficha de cliente" separada de la edición:
/// tocar un cliente va directo a FiscalClienteEditScreen (que ya incluye
/// "Generar vencimientos"), sin una pantalla intermedia de solo-lectura.
class FiscalClientesScreen extends StatefulWidget {
  final ApiClient api;

  const FiscalClientesScreen({super.key, required this.api});

  @override
  State<FiscalClientesScreen> createState() => _FiscalClientesScreenState();
}

class _FiscalClientesScreenState extends State<FiscalClientesScreen> {
  late Future<List<ClienteFiscal>> _clientes;
  final _buscarController = TextEditingController();
  String? _error;

  @override
  void initState() {
    super.initState();
    _clientes = _cargar();
  }

  Future<List<ClienteFiscal>> _cargar() {
    return widget.api.listarClientesFiscales(q: _buscarController.text.trim());
  }

  Future<void> _recargar() async {
    final futuro = _cargar();
    setState(() => _clientes = futuro);
    await futuro;
  }

  Future<void> _abrirAlta() async {
    final creado = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => FiscalClienteEditScreen(api: widget.api),
      ),
    );
    if (creado == true) await _recargar();
  }

  Future<void> _abrirEdicion(ClienteFiscal resumen) async {
    final t = AppLocalizations.of(context);
    try {
      // El listado no trae modelos_fiscales/generacion_automatica (los
      // manda solo el detalle) -- se pide el detalle real antes de abrir
      // la edición para no perder esos campos al guardar.
      final detalle = await widget.api.obtenerClienteFiscal(resumen.id);
      if (!mounted) return;
      final cambiado = await Navigator.of(context).push<bool>(
        MaterialPageRoute(
          builder: (_) =>
              FiscalClienteEditScreen(api: widget.api, cliente: detalle),
        ),
      );
      if (cambiado == true) await _recargar();
    } catch (e) {
      setState(() => _error = t.comunErrorCargar(e.toString()));
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return Scaffold(
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _buscarController,
                    decoration: InputDecoration(
                      hintText: t.fiscalClientesBuscarHint,
                      prefixIcon: const Icon(Icons.search),
                    ),
                    onSubmitted: (_) => _recargar(),
                  ),
                ),
                const SizedBox(width: 8),
                FilledButton.icon(
                  onPressed: _abrirAlta,
                  icon: const Icon(Icons.add),
                  label: Text(t.fiscalClientesNuevoBoton),
                ),
              ],
            ),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: _recargar,
              child: FutureBuilder<List<ClienteFiscal>>(
                future: _clientes,
                builder: (context, snapshot) {
                  if (snapshot.connectionState != ConnectionState.done) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (snapshot.hasError) {
                    return Center(
                      child: Text(
                        t.comunErrorCargar(snapshot.error.toString()),
                      ),
                    );
                  }
                  final clientes = snapshot.data ?? [];
                  if (clientes.isEmpty) {
                    return ListView(
                      children: [
                        Padding(
                          padding: const EdgeInsets.all(24),
                          child: Text(t.fiscalClientesSinResultados),
                        ),
                      ],
                    );
                  }
                  return ListView.builder(
                    itemCount: clientes.length,
                    itemBuilder: (context, i) {
                      final c = clientes[i];
                      return ListTile(
                        leading: const Icon(Icons.business_outlined),
                        title: Text(c.nombre),
                        subtitle: c.nif != null ? Text(c.nif!) : null,
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => _abrirEdicion(c),
                      );
                    },
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }
}
