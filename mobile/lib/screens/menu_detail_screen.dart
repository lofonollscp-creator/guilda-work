import 'package:flutter/material.dart';

import '../diseno/componentes.dart';

import '../l10n/app_localizations.dart';

import '../models/models.dart';
import '../services/api_client.dart';
import '../theme/app_theme.dart';
import '../widgets/app_card.dart';
import '../widgets/status_badge.dart';

/// Detalle de un proyecto/categoría (equivalente móvil de
/// app/templates/menu.html): nota rápida, evento instantáneo, tarea con
/// duración, tareas activas de este proyecto con pausar/reanudar/finalizar, y
/// el histórico filtrado por este proyecto con buscador de texto.
class MenuDetailScreen extends StatefulWidget {
  final Categoria categoria;
  final ApiClient api;

  const MenuDetailScreen({super.key, required this.categoria, required this.api});

  @override
  State<MenuDetailScreen> createState() => _MenuDetailScreenState();
}

class _MenuDetailScreenState extends State<MenuDetailScreen> {
  late Future<void> _carga;
  List<TareaActiva> _activas = [];
  List<EntradaHistorial> _historial = [];
  final _notaController = TextEditingController();
  final _eventoController = TextEditingController();
  final _tareaController = TextEditingController();
  final _buscarController = TextEditingController();
  String? _error;

  @override
  void initState() {
    super.initState();
    _carga = _cargar();
  }

  Future<void> _cargar() async {
    final dashboard = await widget.api.dashboard();
    final historial = await widget.api.historial(
      categoriaId: widget.categoria.id,
      q: _buscarController.text.trim(),
    );
    setState(() {
      _activas = (dashboard['tareas_activas'] as List)
          .map((t) => TareaActiva.fromJson(t as Map<String, dynamic>))
          .where((t) => t.categoriaId == widget.categoria.id)
          .toList();
      _historial = historial;
    });
  }

  Future<void> _recargar() async {
    final futuro = _cargar();
    setState(() {
      _carga = futuro;
    });
    await futuro;
  }

  Future<void> _anotar() async {
    final texto = _notaController.text.trim();
    if (texto.isEmpty) return;
    try {
      await widget.api.crearNota(texto, categoriaId: widget.categoria.id);
      _notaController.clear();
      await _recargar();
    } catch (e) {
      if (mounted) setState(() => _error = mensajeDeError(AppLocalizations.of(context), e));
    }
  }

  Future<void> _registrarEvento() async {
    final nombre = _eventoController.text.trim();
    if (nombre.isEmpty) return;
    try {
      await widget.api.crearTarea(nombre, widget.categoria.id, 'instantanea');
      _eventoController.clear();
      await _recargar();
    } catch (e) {
      if (mounted) setState(() => _error = mensajeDeError(AppLocalizations.of(context), e));
    }
  }

  Future<void> _iniciarTarea() async {
    final nombre = _tareaController.text.trim();
    if (nombre.isEmpty) return;
    try {
      await widget.api.crearTarea(nombre, widget.categoria.id, 'duracion');
      _tareaController.clear();
      await _recargar();
    } catch (e) {
      if (mounted) setState(() => _error = mensajeDeError(AppLocalizations.of(context), e));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.categoria.nombre)),
      body: FutureBuilder<void>(
        future: _carga,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text(mensajeDeError(AppLocalizations.of(context), snapshot.error!)));
          }
          return RefreshIndicator(
            onRefresh: _recargar,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _cardAccionRapida(
                  etiqueta: AppLocalizations.of(context).dashboardNotaRapidaTitulo,
                  controlador: _notaController,
                  hint: AppLocalizations.of(context).menuNotaHint,
                  botonTexto: AppLocalizations.of(context).dashboardAnotarBoton,
                  onPressed: _anotar,
                ),
                const SizedBox(height: 8),
                _cardAccionRapida(
                  etiqueta: AppLocalizations.of(context).menuEvento,
                  controlador: _eventoController,
                  hint: AppLocalizations.of(context).menuEventoHint,
                  botonTexto: AppLocalizations.of(context).menuRegistrar,
                  onPressed: _registrarEvento,
                ),
                const SizedBox(height: 8),
                _cardAccionRapida(
                  etiqueta: AppLocalizations.of(context).menuTareaDuracion,
                  controlador: _tareaController,
                  hint: AppLocalizations.of(context).menuTareaDuracionHint,
                  botonTexto: AppLocalizations.of(context).menuIniciar,
                  onPressed: _iniciarTarea,
                ),
                if (_error != null) ...[
                  const SizedBox(height: 8),
                  Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
                if (_activas.isNotEmpty) ...[
                  const SizedBox(height: 24),
                  Text(AppLocalizations.of(context).menuEnCursoAhora, style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  ..._activas.map(_tarjetaTareaActiva),
                ],
                const SizedBox(height: 24),
                Text(AppLocalizations.of(context).menuRegistroDe(widget.categoria.nombre), style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                TextField(
                  controller: _buscarController,
                  decoration: InputDecoration(
                    hintText: AppLocalizations.of(context).menuBuscarEnProyecto,
                    prefixIcon: Icon(Icons.search),
                  ),
                  onSubmitted: (_) => _recargar(),
                ),
                const SizedBox(height: 8),
                if (_historial.isEmpty)
                  Padding(
                    padding: EdgeInsets.symmetric(vertical: 16),
                    child: Text(AppLocalizations.of(context).menuProyectoVacio),
                  )
                else
                  ..._historial.map(_tarjetaHistorial),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _cardAccionRapida({
    required String etiqueta,
    required TextEditingController controlador,
    required String hint,
    required String botonTexto,
    required VoidCallback onPressed,
  }) {
    return AppCard(
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(etiqueta),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: controlador,
                  decoration: InputDecoration(hintText: hint),
                  onSubmitted: (_) => onPressed(),
                ),
              ),
              const SizedBox(width: 8),
              FilledButton(onPressed: onPressed, child: Text(botonTexto)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _tarjetaTareaActiva(TareaActiva t) {
    final pausada = t.estado == 'pausada';
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        title: Text(t.nombre),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 4),
          child: StatusBadge(
            texto: pausada ? AppLocalizations.of(context).menuEnPausa : AppLocalizations.of(context).estadoEnProgreso,
            tono: pausada ? BadgeTono.aviso : BadgeTono.exito,
          ),
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            IconButton(
              icon: Icon(pausada ? Icons.play_arrow : Icons.pause),
              tooltip: pausada ? AppLocalizations.of(context).menuReanudar : AppLocalizations.of(context).menuPausar,
              onPressed: () async {
                if (pausada) {
                  await widget.api.reanudarTarea(t.id);
                } else {
                  await widget.api.pausarTarea(t.id);
                }
                await _recargar();
              },
            ),
            IconButton(
              icon: const Icon(Icons.stop),
              tooltip: AppLocalizations.of(context).menuFinalizar,
              onPressed: () async {
                await widget.api.finalizarTarea(t.id);
                await _recargar();
              },
            ),
          ],
        ),
      ),
    );
  }

  Widget _tarjetaHistorial(EntradaHistorial f) {
    final esNota = f.origen == 'nota';
    String etiqueta;
    if (esNota) {
      etiqueta = AppLocalizations.of(context).menuTipoNota;
    } else if (f.tipo == 'instantanea') {
      etiqueta = AppLocalizations.of(context).menuTipoEvento;
    } else if (f.estado == 'en_curso') {
      etiqueta = AppLocalizations.of(context).estadoEnProgreso;
    } else if (f.estado == 'pausada') {
      etiqueta = AppLocalizations.of(context).menuEnPausa;
    } else {
      etiqueta = AppLocalizations.of(context).busquedaTipoTarea;
    }
    String? duracion;
    if (f.duracionSegundos != null) {
      final h = f.duracionSegundos! ~/ 3600;
      final m = (f.duracionSegundos! % 3600) ~/ 60;
      duracion = '${h}h ${m}m';
    }
    final hora = f.timestamp != null && f.timestamp!.length >= 16 ? f.timestamp!.substring(11, 16) : '';
    return ListTile(
      dense: true,
      leading: Text(hora, style: AppTheme.cifra(fontSize: 13, fontWeight: FontWeight.w400)),
      title: Text(f.texto),
      subtitle: Text(etiqueta),
      trailing: duracion != null ? Text(duracion, style: AppTheme.cifra(fontSize: 13)) : null,
    );
  }
}
