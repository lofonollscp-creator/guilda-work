import 'package:flutter/material.dart';

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
      setState(() => _error = e.toString());
    }
  }

  Future<void> _eliminar(ReglaCategoria r) async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('¿Eliminar esta regla?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Eliminar')),
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
      appBar: AppBar(title: const Text('Reglas de categorización')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Los correos nuevos de un remitente o dominio que coincida se categorizan solos.',
                  style: TextStyle(fontSize: 13),
                ),
                const SizedBox(height: 12),
                if (_categorias.isEmpty)
                  const Text('Crea al menos una categoría desde el detalle de un mensaje primero.')
                else ...[
                  TextField(
                    controller: _patronController,
                    decoration: const InputDecoration(hintText: 'email@ejemplo.com o @dominio.com'),
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
                      FilledButton(onPressed: _anadir, child: const Text('+ Añadir')),
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
                  return Center(child: Text('Error al cargar: ${snapshot.error}'));
                }
                final reglas = snapshot.data ?? [];
                if (reglas.isEmpty) {
                  return const Center(child: Text('Todavía no tienes ninguna regla.'));
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
                        tooltip: 'Eliminar',
                        onPressed: () => _eliminar(r),
                      ),
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
