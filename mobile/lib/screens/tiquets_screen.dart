import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../widgets/status_badge.dart';
import 'tiquet_edit_screen.dart';

/// Tablero de tiquets de soporte interno (equivalente móvil de
/// app/templates/tiquets_tarjetas.html): errores y sugerencias, tablero
/// COMPARTIDO entre todos los usuarios -- cualquiera ve todos los
/// tiquets, pero solo puede editar/borrar los suyos (o cualquiera, si es
/// admin), y solo un admin puede cambiar el estado. Sin vista Kanban en
/// móvil (no hace falta duplicar arrastrar/soltar en una pantalla
/// pequeña): cambiar de estado se hace desde un menú en la propia fila.
class TiquetsScreen extends StatefulWidget {
  final ApiClient api;
  final Usuario usuario;

  const TiquetsScreen({super.key, required this.api, required this.usuario});

  @override
  State<TiquetsScreen> createState() => _TiquetsScreenState();
}

class _TiquetsScreenState extends State<TiquetsScreen> {
  late Future<List<Tiquet>> _tiquets;
  final _tituloController = TextEditingController();
  String _tipoNuevo = 'error';
  String? _filtroTipo;
  String? _error;

  @override
  void initState() {
    super.initState();
    _tiquets = _cargar();
  }

  Future<List<Tiquet>> _cargar() {
    return widget.api.listarTiquets(tipo: _filtroTipo);
  }

  Future<void> _recargar() async {
    final futuro = _cargar();
    setState(() => _tiquets = futuro);
    await futuro;
  }

  bool _puedeEditar(Tiquet t) => t.usuarioId == widget.usuario.id && t.estado == 'sin_revisar';
  bool _puedeBorrar(Tiquet t) => t.usuarioId == widget.usuario.id || widget.usuario.esAdmin;

  Future<void> _crear() async {
    final titulo = _tituloController.text.trim();
    if (titulo.isEmpty) return;
    try {
      await widget.api.crearTiquet(tipo: _tipoNuevo, titulo: titulo);
      _tituloController.clear();
      await _recargar();
    } catch (e) {
      setState(() => _error = e.toString());
    }
  }

  Future<void> _eliminar(Tiquet t) async {
    final loc = AppLocalizations.of(context);
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(loc.tiquetsEliminarTitulo),
        content: Text(loc.tiquetsEliminarContenido(t.titulo)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(loc.comunCancelar)),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(loc.comunEliminar)),
        ],
      ),
    );
    if (confirmar != true) return;
    await widget.api.eliminarTiquet(t.id);
    await _recargar();
  }

  Future<void> _cambiarEstado(Tiquet t, String estado) async {
    await widget.api.cambiarEstadoTiquet(t.id, estado);
    await _recargar();
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tipos = tiposTiquet(t);
    final estados = estadosTiquet(t);
    return Scaffold(
      appBar: AppBar(title: Text(t.tiquetsTitulo)),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _tituloController,
                        decoration: InputDecoration(hintText: t.tiquetsTituloHint),
                        onSubmitted: (_) => _crear(),
                      ),
                    ),
                    const SizedBox(width: 8),
                    DropdownButton<String>(
                      value: _tipoNuevo,
                      items: tipos.map((e) => DropdownMenuItem(value: e.$1, child: Text(e.$2))).toList(),
                      onChanged: (v) => setState(() => _tipoNuevo = v ?? 'error'),
                    ),
                    const SizedBox(width: 8),
                    FilledButton(onPressed: _crear, child: Text(t.tiquetsCrearBoton)),
                  ],
                ),
                if (_error != null) ...[
                  const SizedBox(height: 8),
                  Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  children: [
                    ChoiceChip(
                      label: Text(t.tiquetsTodos),
                      selected: _filtroTipo == null,
                      onSelected: (_) {
                        setState(() => _filtroTipo = null);
                        _recargar();
                      },
                    ),
                    for (final tipo in tipos)
                      ChoiceChip(
                        label: Text(tipo.$2),
                        selected: _filtroTipo == tipo.$1,
                        onSelected: (_) {
                          setState(() => _filtroTipo = tipo.$1);
                          _recargar();
                        },
                      ),
                  ],
                ),
              ],
            ),
          ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: _recargar,
              child: FutureBuilder<List<Tiquet>>(
                future: _tiquets,
                builder: (context, snapshot) {
                  if (snapshot.connectionState != ConnectionState.done) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (snapshot.hasError) {
                    return Center(child: Text(t.comunErrorCargar(snapshot.error.toString())));
                  }
                  final tiquets = snapshot.data ?? [];
                  if (tiquets.isEmpty) {
                    return ListView(
                      children: [
                        Padding(
                          padding: const EdgeInsets.all(24),
                          child: Text(t.tiquetsSinResultados),
                        ),
                      ],
                    );
                  }
                  return ListView.builder(
                    itemCount: tiquets.length,
                    itemBuilder: (context, i) => _tarjetaTiquet(tiquets[i], t, estados),
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _tarjetaTiquet(Tiquet t, AppLocalizations loc, List<(String, String)> estados) {
    final etiquetaEstado = estados.firstWhere((e) => e.$1 == t.estado, orElse: () => (t.estado, t.estado)).$2;
    final tonoEstado = switch (t.estado) {
      'finalizado' => BadgeTono.exito,
      'en_revision' => BadgeTono.aviso,
      _ => BadgeTono.neutro,
    };
    return ListTile(
      leading: Icon(t.tipo == 'error' ? Icons.bug_report_outlined : Icons.lightbulb_outline),
      title: Text('#${t.id} · ${t.titulo}'),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Wrap(
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: 8,
          runSpacing: 4,
          children: [
            if (t.autorEmail != null) Text(t.autorEmail!),
            StatusBadge(texto: etiquetaEstado, tono: tonoEstado),
          ],
        ),
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (widget.usuario.esAdmin)
            PopupMenuButton<String>(
              tooltip: loc.tiquetsCambiarEstadoTooltip,
              icon: const Icon(Icons.swap_horiz),
              onSelected: (estado) => _cambiarEstado(t, estado),
              itemBuilder: (context) => estados
                  .map((e) => PopupMenuItem(value: e.$1, child: Text(e.$2)))
                  .toList(),
            ),
          if (_puedeBorrar(t))
            IconButton(
              icon: const Icon(Icons.delete_outline),
              tooltip: loc.tiquetsEliminarTooltip,
              onPressed: () => _eliminar(t),
            ),
        ],
      ),
      onTap: _puedeEditar(t)
          ? () async {
              await Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => TiquetEditScreen(tiquet: t, api: widget.api)),
              );
              await _recargar();
            }
          : null,
    );
  }
}
