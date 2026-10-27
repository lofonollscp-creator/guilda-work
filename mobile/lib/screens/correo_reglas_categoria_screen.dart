import 'package:flutter/material.dart';

import '../diseno/adaptable.dart';

import '../nucleo/abrir_asistente.dart';

import '../diseno/componentes.dart';

import '../l10n/app_localizations.dart';

import '../models/models.dart';
import '../services/api_client.dart';

/// Gestión de reglas de categorización automática por remitente (Fase 5d):
/// lista + alta (patrón + categoría) + borrado, mismo patrón que
/// tareas_outlook_screen.dart.
class CorreoReglasCategoriaScreen extends StatefulWidget {
  final ApiClient api;

  const CorreoReglasCategoriaScreen({super.key, required this.api});

  @override
  State<CorreoReglasCategoriaScreen> createState() => _CorreoReglasCategoriaScreenState();
}

class _CorreoReglasCategoriaScreenState extends State<CorreoReglasCategoriaScreen> {
  late Future<List<ReglaCategoria>> _reglas;
  List<CategoriaCorreo> _categorias = [];
  final _patronController = TextEditingController();
  int? _categoriaSeleccionada;
  String? _error;

  @override
  void initState() {
    super.initState();
    _reglas = _cargar();
  }

  Future<List<ReglaCategoria>> _cargar() async {
    final resultados = await Future.wait([
      widget.api.listarReglasCategoria(),
      widget.api.listarCategoriasCorreo(),
    ]);
    _categorias = resultados[1] as List<CategoriaCorreo>;
    if (_categoriaSeleccionada == null && _categorias.isNotEmpty) {
      _categoriaSeleccionada = _categorias.first.id;
    }
    return resultados[0] as List<ReglaCategoria>;
  }

  Future<void> _recargar() async {
    final futuro = _cargar();
    setState(() {
      _reglas = futuro;
    });
    await futuro;
  }

  Future<void> _anadir() async {
    final patron = _patronController.text.trim();
    if (patron.isEmpty || _categoriaSeleccionada == null) return;
    try {
      await widget.api.crearReglaCategoria(patron, _categoriaSeleccionada!);
      _patronController.clear();
      await _recargar();
    } catch (e) {
      if (mounted) setState(() => _error = mensajeDeError(AppLocalizations.of(context), e));
    }
  }

  Future<void> _eliminar(ReglaCategoria r) async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(AppLocalizations.of(context).correoReglaEliminarTitulo),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(AppLocalizations.of(context).comunCancelar)),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(AppLocalizations.of(context).comunEliminar)),
        ],
      ),
    );
    if (confirmar != true) return;
    await widget.api.eliminarReglaCategoria(r.id);
    await _recargar();
  }

  Color? _colorDesdeHex(String? hex) {
    if (hex == null || !hex.startsWith('#')) return null;
    final valor = int.tryParse(hex.substring(1), radix: 16);
    if (valor == null) return null;
    return Color(0xFF000000 | valor);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(AppLocalizations.of(context).correoReglasTitulo), actions: [AccionAsistente(contexto: AppLocalizations.of(context).correoReglasTitulo)]),
      body: AnchoMaximo(child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  AppLocalizations.of(context).correoReglasAyuda,
                  style: TextStyle(fontSize: 13),
                ),
                const SizedBox(height: 12),
                if (_categorias.isEmpty)
                  Text(AppLocalizations.of(context).correoReglasSinCategorias)
                else ...[
                  TextField(
                    controller: _patronController,
                    decoration: InputDecoration(hintText: AppLocalizations.of(context).correoReglasPatronHint),
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: DropdownButton<int>(
                          isExpanded: true,
                          value: _categoriaSeleccionada,
                          items: _categorias
                              .map((c) => DropdownMenuItem(value: c.id, child: Text(c.nombre)))
                              .toList(),
                          onChanged: (v) => setState(() => _categoriaSeleccionada = v),
                        ),
                      ),
                      const SizedBox(width: 8),
                      FilledButton(onPressed: _anadir, child: Text('+ ${AppLocalizations.of(context).comunAnadir}')),
                    ],
                  ),
                ],
                if (_error != null) ...[
                  const SizedBox(height: 8),
                  Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
              ],
            ),
          ),
          Expanded(
            child: FutureBuilder<List<ReglaCategoria>>(
              future: _reglas,
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snapshot.hasError) {
                  return Center(child: Text(mensajeDeError(AppLocalizations.of(context), snapshot.error!)));
                }
                final reglas = snapshot.data ?? [];
                if (reglas.isEmpty) {
                  return Center(child: Text(AppLocalizations.of(context).correoReglasVacio));
                }
                return ListView.builder(
                  itemCount: reglas.length,
                  itemBuilder: (context, i) {
                    final r = reglas[i];
                    return ListTile(
                      leading: CircleAvatar(
                        backgroundColor: _colorDesdeHex(r.categoriaColor) ?? Colors.blueGrey,
                        radius: 8,
                      ),
                      title: Text(r.remitentePatron),
                      subtitle: Text('→ ${r.categoriaNombre}'),
                      trailing: IconButton(
                        icon: const Icon(Icons.delete_outline),
                        tooltip: AppLocalizations.of(context).comunEliminar,
                        onPressed: () => _eliminar(r),
                      ),
                    );
                  },
                );
              },
            ),
          ),
        ],
      )),
    );
  }
}
