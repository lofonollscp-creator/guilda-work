import 'package:flutter/material.dart';
import '../../diseno/adaptable.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errores.dart';
import '../../api/fechas.dart';
import '../../api/generado/modelos.g.dart';
import '../../diseno/formatos.dart';
import '../../dominio/tarea.dart';
import '../../l10n/app_localizations.dart';
import 'tareas_repositorio.dart';
import 'textos.dart';

/// El formulario de edición de la web, completo: asunto, descripción, prioridad, estimación, inicio y vencimiento (con hora), categoría, proyecto,
/// cliente y a quién se asigna. Lo que cambia se manda donde corresponde (la edición, la asignación, el proyecto y el cliente tienen cada uno su
/// operación en la API); si algo no se puede (un permiso), se guarda lo demás y se dice qué no. Devuelve la tarea ya actualizada.
class TareaEditorScreen extends ConsumerStatefulWidget {
  final TareaOutlook tarea;

  /// Solo quien creó la tarea la asigna y la cambia de proyecto (como en la web).
  final bool esDueno;
  const TareaEditorScreen({super.key, required this.tarea, required this.esDueno});

  @override
  ConsumerState<TareaEditorScreen> createState() => _TareaEditorScreenState();
}

class _TareaEditorScreenState extends ConsumerState<TareaEditorScreen> {
  late final TextEditingController _asunto, _notas, _estimacion, _categoria;
  late PrioridadTarea _prioridad;
  String? _inicio, _vencimiento; // `AAAA-MM-DD` o `AAAA-MM-DDTHH:MM`
  int? _proyectoId, _clienteId, _asignadaA;
  late Set<int> _otrosClientes;
  late bool _visible, _comentariosCliente;
  late int _porcentaje;
  late final int _porcentajeInicial; // el del control (de 10 en 10): solo se manda si la persona lo mueve
  List<Proyecto> _proyectos = const [];
  List<ClienteFiscal> _clientes = const [];
  List<Companero> _companeros = const [];
  bool _guardando = false;

  TareaOutlook get _t0 => widget.tarea;

  @override
  void initState() {
    super.initState();
    _asunto = TextEditingController(text: _t0.asunto ?? '');
    _notas = TextEditingController(text: _t0.cuerpo ?? '');
    _estimacion = TextEditingController(text: _t0.estimacionMin == null ? '' : duracionCorta(_t0.estimacionMin!));
    _categoria = TextEditingController(text: _t0.categoriaOutlook ?? '');
    _prioridad = PrioridadTarea.desde(_t0.prioridad);
    _inicio = _t0.fechaInicio;
    _vencimiento = _t0.fechaVencimiento;
    _proyectoId = _t0.categoriaId;
    _clienteId = _t0.clienteFiscalId;
    _asignadaA = _t0.asignadaA;
    _otrosClientes = {for (final c in _t0.clientes ?? const <ClienteDeTarea>[]) if (c.id != null && c.principal != true) c.id!};
    _porcentaje = _porcentajeInicial = ((_t0.porcentajeCompletado ?? 0) ~/ 10) * 10;
    _visible = (_t0.visibleCliente ?? 0) == 1;
    _comentariosCliente = (_t0.comentariosCliente ?? 0) == 1;
    _cargarListas();
  }

  @override
  void dispose() {
    for (final c in [_asunto, _notas, _estimacion, _categoria]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _cargarListas() async {
    final repo = ref.read(tareasRepositorioProvider);
    final r = await Future.wait<Object?>([
      repo.proyectos().then<Object?>((x) => x).catchError((_) => <Proyecto>[]),
      repo.clientesFiscales().then<Object?>((x) => x).catchError((_) => <ClienteFiscal>[]),
      repo.companeros().then<Object?>((x) => x).catchError((_) => <Companero>[]),
    ]);
    if (!mounted) return;
    setState(() {
      _proyectos = r[0] as List<Proyecto>;
      _clientes = r[1] as List<ClienteFiscal>;
      _companeros = r[2] as List<Companero>;
    });
  }

  // ---- fecha y hora ----

  String _dos(int n) => n.toString().padLeft(2, '0');

  Future<String?> _elegirFecha(String? actual, {required String ayuda}) async {
    final ahora = DateTime.now();
    final previa = Fecha.intentar(actual);
    final f = await showDatePicker(
      context: context,
      helpText: ayuda,
      initialDate: previa == null ? ahora : DateTime(previa.anio, previa.mes, previa.dia),
      firstDate: DateTime(ahora.year - 2),
      lastDate: DateTime(ahora.year + 6),
    );
    if (f == null) return actual;
    final hora = MomentoLocal.intentar(actual);
    final dia = '${f.year}-${_dos(f.month)}-${_dos(f.day)}';
    return hora == null ? dia : '${dia}T${_dos(hora.hora)}:${_dos(hora.minuto)}';
  }

  Future<String?> _elegirHora(String? actual) async {
    final dia = Fecha.intentar(actual);
    if (dia == null) return actual;
    final m = MomentoLocal.intentar(actual);
    final h = await showTimePicker(context: context, initialTime: TimeOfDay(hour: m?.hora ?? 9, minute: m?.minuto ?? 0));
    return h == null ? actual : '${dia.toJson()}T${_dos(h.hour)}:${_dos(h.minute)}';
  }

  Widget _filaFecha(String etiqueta, String? valor, void Function(String?) alCambiar) {
    final t = AppLocalizations.of(context);
    final m = MomentoLocal.intentar(valor);
    final f = Fecha.intentar(valor);
    return Row(children: [
      Expanded(
        child: ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.event_outlined),
          title: Text(f == null ? '—' : context.formatos.fecha(f)),
          subtitle: Text(etiqueta),
          onTap: () async => alCambiar(await _elegirFecha(valor, ayuda: etiqueta)),
        ),
      ),
      if (f != null) ...[
        ActionChip(avatar: const Icon(Icons.schedule, size: 16), label: Text(m == null ? t.tareaHora : context.formatos.hora(m.hora, m.minuto)), onPressed: () async => alCambiar(await _elegirHora(valor))),
        IconButton(icon: const Icon(Icons.close), tooltip: t.tareaQuitarFecha, onPressed: () => alCambiar(null)),
      ],
    ]);
  }

  // ---- selectores ----

  /// Devuelve `(valor,)` al elegir (también «ninguno») y null si se cierra sin elegir: así cerrar el panel no borra lo que había.
  Future<(T?,)?> _elegirDeLista<T>(String titulo, List<(T?, String)> opciones, T? actual) => showModalBottomSheet<(T?,)>(
        context: context,
        showDragHandle: true,
        isScrollControlled: true,
        builder: (_) => SafeArea(
          child: ListView(shrinkWrap: true, children: [
            Padding(padding: const EdgeInsets.fromLTRB(16, 0, 16, 8), child: Text(titulo, style: Theme.of(context).textTheme.titleMedium)),
            for (final (valor, etiqueta) in opciones)
              ListTile(
                title: Text(etiqueta),
                trailing: valor == actual ? const Icon(Icons.check) : null,
                onTap: () => Navigator.pop(context, (valor,)),
              ),
          ]),
        ),
      );

  Widget _campoSelector({required IconData icono, required String etiqueta, required String valor, required VoidCallback alPulsar}) => ListTile(
        contentPadding: EdgeInsets.zero,
        leading: Icon(icono),
        title: Text(valor),
        subtitle: Text(etiqueta),
        trailing: const Icon(Icons.arrow_drop_down),
        onTap: alPulsar,
      );

  // ---- guardar ----

  Future<void> _guardar() async {
    final t = AppLocalizations.of(context);
    final asunto = _asunto.text.trim();
    if (asunto.isEmpty) return;
    setState(() => _guardando = true);
    final repo = ref.read(tareasRepositorioProvider);
    final mensajero = ScaffoldMessenger.of(context);
    final navegador = Navigator.of(context);
    TareaOutlook resultado = _t0;
    final fallos = <String>[];
    try {
      // 1) Los campos de la edición, solo lo que ha cambiado (menos pisar lo que otra persona toque a la vez).
      final estimacionAntes = _t0.estimacionMin == null ? '' : duracionCorta(_t0.estimacionMin!);
      final cambioEdicion = asunto != (_t0.asunto ?? '') ||
          _notas.text != (_t0.cuerpo ?? '') ||
          _prioridad != PrioridadTarea.desde(_t0.prioridad) ||
          _estimacion.text.trim() != estimacionAntes ||
          _categoria.text.trim() != (_t0.categoriaOutlook ?? '') ||
          _porcentaje != _porcentajeInicial ||
          _inicio != _t0.fechaInicio ||
          _vencimiento != _t0.fechaVencimiento;
      if (cambioEdicion) {
        resultado = await repo.editarFicha(
          _t0.id,
          asunto: asunto != (_t0.asunto ?? '') ? asunto : null,
          cuerpo: _notas.text != (_t0.cuerpo ?? '') ? _notas.text : null,
          prioridad: _prioridad != PrioridadTarea.desde(_t0.prioridad) ? _prioridad : null,
          estimacion: _estimacion.text.trim() != estimacionAntes ? _estimacion.text.trim() : null,
          categoriaOutlook: _categoria.text.trim() != (_t0.categoriaOutlook ?? '') ? _categoria.text.trim() : null,
          porcentaje: _porcentaje != _porcentajeInicial ? _porcentaje : null,
          fechaInicio: _inicio != _t0.fechaInicio ? _inicio : null,
          quitarInicio: _inicio == null && _t0.fechaInicio != null,
          fechaVencimiento: _vencimiento != _t0.fechaVencimiento ? _vencimiento : null,
          quitarVencimiento: _vencimiento == null && _t0.fechaVencimiento != null,
        );
      }
    } on ApiException catch (e) {
      // Sin la edición no se sigue: lo demás depende de que la tarea esté como se espera.
      mensajero.showSnackBar(SnackBar(content: Text(e.mensaje)));
      if (mounted) setState(() => _guardando = false);
      return;
    }
    Future<void> aparte(String campo, Future<void> Function() f) async {
      try {
        await f();
      } on ApiException catch (e) {
        fallos.add('$campo: ${e.mensaje}');
      }
    }

    if (widget.esDueno && _asignadaA != _t0.asignadaA) await aparte(t.tareaAsignarA, () => repo.asignar(_t0.id, _asignadaA));
    if (widget.esDueno && _proyectoId != _t0.categoriaId) {
      await aparte(t.tareaProyecto, () async {
        final r = await repo.moverAProyecto(_t0.id, _proyectoId);
        if (r.ok == 0) fallos.add(t.tareaProyecto);
      });
    }
    final otrosAntes = {for (final c in _t0.clientes ?? const <ClienteDeTarea>[]) if (c.id != null && c.principal != true) c.id!};
    final otros = _clienteId == null ? <int>{} : _otrosClientes.where((c) => c != _clienteId).toSet();
    if (_clienteId != _t0.clienteFiscalId || otros.length != otrosAntes.length || !otros.containsAll(otrosAntes)) {
      await aparte(t.tareaCliente, () => repo.fijarCliente(_t0.id, _clienteId, otros: otros.toList()));
    }
    final conCliente = _clienteId != null || otros.isNotEmpty;
    final visible = conCliente && _visible, comentarios = visible && _comentariosCliente;
    if (visible != ((_t0.visibleCliente ?? 0) == 1) || comentarios != ((_t0.comentariosCliente ?? 0) == 1)) {
      await aparte(t.tareaVisiblePortal, () => repo.visibleParaCliente(_t0.id, visible: visible, comentarios: comentarios));
    }
    // La tarea como queda ahora (asignación, proyecto y cliente cambian filas aparte).
    try {
      resultado = await repo.obtener(_t0.id);
    } catch (_) {
      // se queda lo que devolvió la edición
    }
    if (fallos.isNotEmpty) mensajero.showSnackBar(SnackBar(content: Text(t.tareaGuardadoParcial(fallos.join(' · ')))));
    navegador.pop(resultado);
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final proyecto = _proyectos.where((p) => p.id == _proyectoId).firstOrNull;
    final cliente = _clientes.where((c) => c.id == _clienteId).firstOrNull;
    final persona = _companeros.where((c) => c.id == _asignadaA).firstOrNull;
    return Scaffold(
      appBar: AppBar(
        title: Text(t.tareaEditar),
        actions: [TextButton(onPressed: _guardando ? null : _guardar, child: Text(t.tareaGuardar))],
      ),
      body: AnchoMaximo(child: ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 32), children: [
        TextField(controller: _asunto, decoration: InputDecoration(labelText: t.tareaAsunto), textCapitalization: TextCapitalization.sentences),
        const SizedBox(height: 8),
        TextField(controller: _notas, decoration: InputDecoration(labelText: t.tareaNotas), minLines: 2, maxLines: 8),
        const SizedBox(height: 16),
        Text(t.tareaPrioridad, style: Theme.of(context).textTheme.labelLarge),
        const SizedBox(height: 4),
        SegmentedButton<PrioridadTarea>(
          segments: [for (final p in PrioridadTarea.values) ButtonSegment(value: p, label: Text(etiquetaPrioridad(t, p)))],
          selected: {_prioridad},
          onSelectionChanged: (s) => setState(() => _prioridad = s.first),
        ),
        Padding(padding: const EdgeInsets.only(top: 8), child: Text('${t.tareaPorcentaje}: $_porcentaje', style: Theme.of(context).textTheme.labelLarge)),
        Slider(value: _porcentaje.toDouble(), min: 0, max: 100, divisions: 10, label: '$_porcentaje', onChanged: (v) => setState(() => _porcentaje = v.round())),
        _filaFecha(t.tareaInicio, _inicio, (v) => setState(() => _inicio = v)),
        _filaFecha(t.tareaVencimiento, _vencimiento, (v) => setState(() => _vencimiento = v)),
        TextField(
          controller: _estimacion,
          decoration: InputDecoration(labelText: t.tareaEstimacion, hintText: t.tareaEstimacionHint, prefixIcon: const Icon(Icons.timer_outlined)),
        ),
        const SizedBox(height: 8),
        TextField(controller: _categoria, decoration: InputDecoration(labelText: t.tareaCategoriaOutlook, prefixIcon: const Icon(Icons.label_outline))),
        if (widget.esDueno && _proyectos.isNotEmpty)
          _campoSelector(
            icono: Icons.folder_outlined,
            etiqueta: t.tareaProyecto,
            valor: proyecto?.nombre ?? t.tareaSinProyecto,
            alPulsar: () async {
              final r = await _elegirDeLista<int>(t.tareaProyecto, [(null, t.tareaSinProyecto), for (final p in _proyectos) (p.id, p.nombre ?? '')], _proyectoId);
              if (mounted && r != null) setState(() => _proyectoId = r.$1);
            },
          ),
        if (_clientes.isNotEmpty)
          _campoSelector(
            icono: Icons.business_outlined,
            etiqueta: t.tareaCliente,
            valor: cliente?.nombre ?? t.tareaSinCliente,
            alPulsar: () async {
              final r = await _elegirDeLista<int>(t.tareaCliente, [(null, t.tareaSinCliente), for (final c in _clientes) (c.id, c.nombre ?? '')], _clienteId);
              if (mounted && r != null) setState(() => _clienteId = r.$1);
            },
          ),
        if (_clientes.length > 1 && _clienteId != null) ...[
          Padding(padding: const EdgeInsets.only(top: 8), child: Text(t.tareaOtrosClientes, style: Theme.of(context).textTheme.labelLarge)),
          Wrap(spacing: 8, children: [
            for (final c in _clientes)
              if (c.id != _clienteId)
                FilterChip(
                  label: Text(c.nombre ?? ''),
                  selected: _otrosClientes.contains(c.id),
                  onSelected: (v) => setState(() => v ? _otrosClientes.add(c.id) : _otrosClientes.remove(c.id)),
                ),
          ]),
          Text(t.tareaOtrosClientesAyuda, style: Theme.of(context).textTheme.bodySmall),
        ],
        if (_clienteId != null || _otrosClientes.isNotEmpty) ...[
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(t.tareaVisiblePortal),
            subtitle: Text(t.tareaVisiblePortalAyuda),
            value: _visible,
            onChanged: (v) => setState(() => _visible = v),
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(t.tareaComentariosCliente),
            subtitle: Text(t.tareaComentariosClienteAyuda),
            value: _visible && _comentariosCliente,
            onChanged: _visible ? (v) => setState(() => _comentariosCliente = v) : null,
          ),
        ],
        if (widget.esDueno && _companeros.isNotEmpty)
          _campoSelector(
            icono: Icons.person_outline,
            etiqueta: t.tareaAsignarA,
            valor: persona?.nombre ?? persona?.email ?? t.tareaSinAsignar,
            alPulsar: () async {
              final r = await _elegirDeLista<int>(t.tareaAsignarA, [(null, t.tareaSinAsignar), for (final c in _companeros) if (c.id != null) (c.id, c.nombre ?? c.email ?? '')], _asignadaA);
              if (mounted && r != null) setState(() => _asignadaA = r.$1);
            },
          ),
      ])),
    );
  }
}
