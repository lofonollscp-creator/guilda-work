import 'package:flutter/material.dart';

import '../models/models.dart';
import '../services/api_client.dart';
import '../services/session_service.dart';
import 'login_screen.dart';
import 'menu_detail_screen.dart';

/// Dashboard (equivalente móvil de app/templates/inicio.html): stats del
/// día, nota rápida, y las tarjetas de menú desde las que se entra al
/// detalle de cada uno (menu_detail_screen.dart).
class DashboardScreen extends StatefulWidget {
  final Usuario usuario;
  final ApiClient api;
  final SessionService sesion;

  const DashboardScreen({
    super.key,
    required this.usuario,
    required this.api,
    required this.sesion,
  });

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  late Future<void> _cargaInicial;
  Map<String, dynamic>? _dashboard;
  List<Categoria> _categorias = [];
  final _notaController = TextEditingController();
  int? _categoriaNotaSeleccionada;
  bool _guardandoNota = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _cargaInicial = _cargar();
  }

  Future<void> _cargar() async {
    final resultados = await Future.wait([
      widget.api.dashboard(),
      widget.api.listarCategorias(),
    ]);
    setState(() {
      _dashboard = resultados[0] as Map<String, dynamic>;
      _categorias = resultados[1] as List<Categoria>;
    });
  }

  Future<void> _recargar() async {
    final futuro = _cargar();
    setState(() {
      _cargaInicial = futuro;
    });
    await futuro;
  }

  Future<void> _anotar() async {
    final texto = _notaController.text.trim();
    if (texto.isEmpty) return;
    setState(() {
      _guardandoNota = true;
      _error = null;
    });
    try {
      await widget.api.crearNota(texto, categoriaId: _categoriaNotaSeleccionada);
      _notaController.clear();
      await _recargar();
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _guardandoNota = false);
    }
  }

  Future<void> _crearMenu() async {
    final controlador = TextEditingController();
    final nombre = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Nuevo menú'),
        content: TextField(
          controller: controlador,
          decoration: const InputDecoration(labelText: 'Nombre (ej. Lueira, Guilda...)'),
          autofocus: true,
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancelar')),
          FilledButton(
            onPressed: () => Navigator.pop(context, controlador.text.trim()),
            child: const Text('Crear'),
          ),
        ],
      ),
    );
    if (nombre == null || nombre.isEmpty) return;
    await widget.api.crearCategoria(nombre);
    await _recargar();
  }

  Future<void> _cerrarSesion() async {
    await widget.api.logout();
    await widget.sesion.borrarToken();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => LoginScreen(api: widget.api, sesion: widget.sesion)),
      (route) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Guilda Work'),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Cerrar sesión',
            onPressed: _cerrarSesion,
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: _crearMenu,
        tooltip: 'Nuevo menú',
        child: const Icon(Icons.add),
      ),
      body: FutureBuilder<void>(
        future: _cargaInicial,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text('Error al cargar: ${snapshot.error}'));
          }
          return RefreshIndicator(
            onRefresh: _recargar,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _tarjetaStats(),
                const SizedBox(height: 16),
                _tarjetaNotaRapida(),
                if (_error != null) ...[
                  const SizedBox(height: 8),
                  Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
                const SizedBox(height: 24),
                Text('Tus menús', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                if (_categorias.isEmpty)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 24),
                    child: Text('Todavía no tienes ningún menú. Crea el primero con el botón +.'),
                  )
                else
                  ..._categorias.map(_tarjetaMenu),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _tarjetaStats() {
    final tareasActivas = (_dashboard?['tareas_activas'] as List?)?.length ?? 0;
    final notasHoy = _dashboard?['notas_hoy'] ?? 0;
    final correosNoLeidos = _dashboard?['correos_no_leidos'] ?? 0;
    return Row(
      children: [
        Expanded(child: _stat('$tareasActivas', 'en curso')),
        Expanded(child: _stat('$notasHoy', 'notas hoy')),
        Expanded(child: _stat('$correosNoLeidos', 'correos sin leer')),
      ],
    );
  }

  Widget _stat(String valor, String etiqueta) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 16),
        child: Column(
          children: [
            Text(valor, style: Theme.of(context).textTheme.headlineSmall),
            Text(etiqueta, style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
      ),
    );
  }

  Widget _tarjetaNotaRapida() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('📝 Nota rápida'),
            const SizedBox(height: 8),
            if (_categorias.isNotEmpty)
              DropdownButton<int?>(
                isExpanded: true,
                value: _categoriaNotaSeleccionada,
                hint: const Text('Sin menú'),
                items: [
                  const DropdownMenuItem(value: null, child: Text('Sin menú')),
                  ..._categorias.map(
                    (c) => DropdownMenuItem(value: c.id, child: Text(c.nombre)),
                  ),
                ],
                onChanged: (v) => setState(() => _categoriaNotaSeleccionada = v),
              ),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _notaController,
                    decoration: const InputDecoration(hintText: '¿Qué ha pasado?'),
                    onSubmitted: (_) => _anotar(),
                  ),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: _guardandoNota ? null : _anotar,
                  child: const Text('Anotar'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _tarjetaMenu(Categoria c) {
    final tareasActivas = (_dashboard?['tareas_activas'] as List? ?? [])
        .where((t) => t['categoria_id'] == c.id)
        .length;
    final color = _colorDesdeHex(c.color) ?? Colors.blueGrey;
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        leading: CircleAvatar(backgroundColor: color, radius: 8),
        title: Text(c.nombre),
        subtitle: tareasActivas > 0 ? Text('$tareasActivas en curso') : null,
        trailing: const Icon(Icons.chevron_right),
        onTap: () async {
          await Navigator.of(context).push(
            MaterialPageRoute(
              builder: (_) => MenuDetailScreen(categoria: c, api: widget.api),
            ),
          );
          await _recargar();
        },
      ),
    );
  }

  Color? _colorDesdeHex(String? hex) {
    if (hex == null || !hex.startsWith('#')) return null;
    final valor = int.tryParse(hex.substring(1), radix: 16);
    if (valor == null) return null;
    return Color(0xFF000000 | valor);
  }
}
