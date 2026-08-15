import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../widgets/status_badge.dart';
import 'fiscal_vencimiento_edit_screen.dart';

/// Lista de vencimientos fiscales de todos los clientes -- calco de
/// tiquets_screen.dart, con ChoiceChip de estado en vez de tipo.
class FiscalVencimientosScreen extends StatefulWidget {
  final ApiClient api;

  const FiscalVencimientosScreen({super.key, required this.api});

  @override
  State<FiscalVencimientosScreen> createState() =>
      _FiscalVencimientosScreenState();
}

class _FiscalVencimientosScreenState extends State<FiscalVencimientosScreen> {
  late Future<List<VencimientoFiscal>> _vencimientos;
  String? _filtroEstado;

  @override
  void initState() {
    super.initState();
    _vencimientos = _cargar();
  }

  Future<List<VencimientoFiscal>> _cargar() {
    return widget.api.listarVencimientosFiscales(estado: _filtroEstado);
  }

  Future<void> _recargar() async {
    final futuro = _cargar();
    setState(() => _vencimientos = futuro);
    await futuro;
  }

  Future<void> _marcarPresentado(VencimientoFiscal v) async {
    await widget.api.marcarPresentadoVencimientoFiscal(v.id);
    await _recargar();
  }

  Future<void> _abrirEdicion(VencimientoFiscal v) async {
    final cambiado = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) =>
            FiscalVencimientoEditScreen(api: widget.api, vencimiento: v),
      ),
    );
    if (cambiado == true) await _recargar();
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final estados = estadosVencimientoFiscal(t);
    return Scaffold(
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Wrap(
              spacing: 8,
              children: [
                ChoiceChip(
                  label: Text(t.fiscalTodos),
                  selected: _filtroEstado == null,
                  onSelected: (_) {
                    setState(() => _filtroEstado = null);
                    _recargar();
                  },
                ),
                for (final estado in estados)
                  ChoiceChip(
                    label: Text(estado.$2),
                    selected: _filtroEstado == estado.$1,
                    onSelected: (_) {
                      setState(() => _filtroEstado = estado.$1);
                      _recargar();
                    },
                  ),
              ],
            ),
          ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: _recargar,
              child: FutureBuilder<List<VencimientoFiscal>>(
                future: _vencimientos,
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
                  final vencimientos = snapshot.data ?? [];
                  if (vencimientos.isEmpty) {
                    return ListView(
                      children: [
                        Padding(
                          padding: const EdgeInsets.all(24),
                          child: Text(t.fiscalVencimientosSinResultados),
                        ),
                      ],
                    );
                  }
                  return ListView.builder(
                    itemCount: vencimientos.length,
                    itemBuilder: (context, i) =>
                        _tarjeta(vencimientos[i], t, estados),
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _tarjeta(
    VencimientoFiscal v,
    AppLocalizations loc,
    List<(String, String)> estados,
  ) {
    final etiquetaEstado = estados
        .firstWhere((e) => e.$1 == v.estado, orElse: () => (v.estado, v.estado))
        .$2;
    final tono = switch (v.estado) {
      'presentado' => BadgeTono.exito,
      'fuera_plazo' => BadgeTono.peligro,
      _ => BadgeTono.aviso,
    };
    return ListTile(
      leading: IconButton(
        icon: Icon(
          v.estado == 'presentado'
              ? Icons.check_circle
              : Icons.radio_button_unchecked,
        ),
        tooltip: loc.fiscalMarcarPresentadoTooltip,
        onPressed: v.estado == 'presentado' ? null : () => _marcarPresentado(v),
      ),
      title: Text('${v.modelo} — ${v.clienteNombre}'),
      subtitle: Wrap(
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: 8,
        runSpacing: 4,
        children: [
          Text(loc.fiscalVenceEl(v.fechaLimite.substring(0, 10))),
          Text(v.periodo),
          StatusBadge(texto: etiquetaEstado, tono: tono),
        ],
      ),
      trailing: const Icon(Icons.chevron_right),
      onTap: () => _abrirEdicion(v),
    );
  }
}
