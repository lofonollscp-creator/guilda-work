import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errores.dart';
import '../../api/fechas.dart';
import '../../api/generado/modelos.g.dart';
import '../../diseno/formatos.dart';
import '../../dominio/tarea.dart';
import '../../l10n/app_localizations.dart';
import 'tarea_detalle_screen.dart';
import 'tareas_repositorio.dart';
import 'textos.dart';

/// Los bloques de la ficha de una tarea que la web tiene aparte de lo básico: «Espera a», «Compartida con» y «Recordatorios». Cada uno pide sus datos
/// (y los guarda) por su cuenta; si el servidor rechaza algo (un ciclo, un permiso), enseña su mensaje tal cual.

void _aviso(BuildContext context, String texto) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(texto)));

Future<bool> _probar(BuildContext context, Future<void> Function() f) async {
  try {
    await f();
    return true;
  } on ApiException catch (e) {
    if (context.mounted) _aviso(context, e.mensaje);
    return false;
  }
}

class _Cabecera extends StatelessWidget {
  final String titulo;
  const _Cabecera(this.titulo);

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 20, bottom: 4),
        child: Text(titulo, style: Theme.of(context).textTheme.titleSmall),
      );
}

// ---------------------------------------------------------------- Espera a ----

/// Tareas de las que depende esta (no se puede empezar ni completar hasta que acaben). Solo quien puede editar la tarea añade o quita.
class BloqueEspera extends ConsumerStatefulWidget {
  final int tareaId;
  final bool puedeEditar;
  final VoidCallback? alCambiar;
  const BloqueEspera({super.key, required this.tareaId, required this.puedeEditar, this.alCambiar});

  @override
  ConsumerState<BloqueEspera> createState() => _BloqueEsperaState();
}

class _BloqueEsperaState extends ConsumerState<BloqueEspera> {
  List<DependenciaTarea> _lista = const [];
  bool _cargado = false;

  TareasRepositorio get _repo => ref.read(tareasRepositorioProvider);

  @override
  void initState() {
    super.initState();
    _cargar();
  }

  Future<void> _cargar() async {
    try {
      final r = await _repo.dependencias(widget.tareaId);
      if (mounted) setState(() => _lista = r.esperaA);
    } catch (_) {
      // sin red o sin permiso: el bloque queda vacío
    }
    if (mounted) setState(() => _cargado = true);
  }

  Future<void> _anadir() async {
    final elegida = await elegirTarea(context, ref, excluir: {widget.tareaId, ..._lista.map((d) => d.id)});
    if (elegida == null || !mounted) return;
    final t = AppLocalizations.of(context);
    try {
      await _repo.esperaA(widget.tareaId, elegida.id);
    } on ApiException catch (e) {
      if (mounted) _aviso(context, e.codigo == 'dependencia_invalida' ? t.tareaEsperaInvalida : e.mensaje);
      return;
    }
    await _cargar();
    widget.alCambiar?.call();
  }

  Future<void> _quitar(DependenciaTarea d) async {
    if (await _probar(context, () => _repo.quitarEspera(widget.tareaId, d.id))) {
      await _cargar();
      widget.alCambiar?.call();
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    if (_cargado && _lista.isEmpty && !widget.puedeEditar) return const SizedBox.shrink();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _Cabecera(t.tareaEsperaA),
      if (_cargado && _lista.isEmpty) Text(t.tareaEsperaVacio, style: Theme.of(context).textTheme.bodySmall),
      for (final d in _lista)
        ListTile(
          dense: true,
          contentPadding: EdgeInsets.zero,
          leading: Icon(d.estado.abierta ? Icons.hourglass_empty : Icons.check_circle_outline, size: 20),
          title: Text(d.asunto, maxLines: 2, overflow: TextOverflow.ellipsis),
          subtitle: Text(etiquetaEstado(t, d.estado)),
          trailing: widget.puedeEditar ? IconButton(icon: const Icon(Icons.close), tooltip: t.tareaQuitar, onPressed: () => _quitar(d)) : null,
          onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => TareaDetalleScreen(tareaId: d.id))),
        ),
      if (widget.puedeEditar) Align(alignment: Alignment.centerLeft, child: TextButton.icon(onPressed: _anadir, icon: const Icon(Icons.add), label: Text(t.tareaEsperaAnadir))),
    ]);
  }
}

/// Busca entre tus tareas abiertas (por texto) y devuelve la elegida.
Future<TareaOutlook?> elegirTarea(BuildContext context, WidgetRef ref, {Set<int> excluir = const {}}) =>
    showModalBottomSheet<TareaOutlook>(context: context, isScrollControlled: true, showDragHandle: true, builder: (_) => _HojaTareas(excluir: excluir));

class _HojaTareas extends ConsumerStatefulWidget {
  final Set<int> excluir;
  const _HojaTareas({required this.excluir});

  @override
  ConsumerState<_HojaTareas> createState() => _HojaTareasState();
}

class _HojaTareasState extends ConsumerState<_HojaTareas> {
  final _texto = TextEditingController();
  List<TareaOutlook> _resultados = const [];
  bool _buscando = false;
  int _generacion = 0;

  @override
  void initState() {
    super.initState();
    _buscar('');
  }

  @override
  void dispose() {
    _texto.dispose();
    super.dispose();
  }

  Future<void> _buscar(String q) async {
    final mia = ++_generacion;
    setState(() => _buscando = true);
    try {
      final r = await ref.read(tareasRepositorioProvider).listar(ambito: 'todas', q: q, limit: 20, soloAbiertas: true);
      if (mounted && mia == _generacion) setState(() => _resultados = [for (final t in r) if (!widget.excluir.contains(t.id)) t]);
    } catch (_) {
      if (mounted && mia == _generacion) setState(() => _resultados = const []);
    }
    if (mounted && mia == _generacion) setState(() => _buscando = false);
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: TextField(controller: _texto, autofocus: true, decoration: InputDecoration(hintText: t.tareaEsperaBuscar, prefixIcon: const Icon(Icons.search)), onChanged: _buscar),
          ),
          if (_buscando) const LinearProgressIndicator(minHeight: 2),
          Flexible(
            child: ListView(shrinkWrap: true, children: [
              for (final x in _resultados) ListTile(title: Text(x.asunto ?? '', maxLines: 2, overflow: TextOverflow.ellipsis), onTap: () => Navigator.pop(context, x)),
            ]),
          ),
        ]),
      ),
    );
  }
}

// ---------------------------------------------------------------- Compartida con ----

/// Con quién se comparte la tarea y con qué permiso (puede editarla / solo lectura). Solo la dueña comparte; cada participante puede salirse.
class BloqueCompartida extends ConsumerStatefulWidget {
  final int tareaId;
  final bool esDueno;
  final int? miId;
  const BloqueCompartida({super.key, required this.tareaId, required this.esDueno, this.miId});

  @override
  ConsumerState<BloqueCompartida> createState() => _BloqueCompartidaState();
}

class _BloqueCompartidaState extends ConsumerState<BloqueCompartida> {
  List<ParticipanteTarea> _lista = const [];
  bool _cargado = false;

  TareasRepositorio get _repo => ref.read(tareasRepositorioProvider);

  @override
  void initState() {
    super.initState();
    _cargar();
  }

  Future<void> _cargar() async {
    try {
      final r = await _repo.participantes(widget.tareaId);
      if (mounted) setState(() => _lista = r);
    } catch (_) {
      // sin red o sin permiso
    }
    if (mounted) setState(() => _cargado = true);
  }

  Future<void> _anadir() async {
    final t = AppLocalizations.of(context);
    List<Companero> companeros;
    try {
      companeros = await _repo.companeros();
    } on ApiException catch (e) {
      if (mounted) _aviso(context, e.mensaje);
      return;
    }
    final ya = _lista.map((p) => p.usuarioId).toSet();
    final libres = [for (final c in companeros) if (c.id != null && !ya.contains(c.id)) c];
    if (!mounted || libres.isEmpty) return;
    final elegido = await showModalBottomSheet<(Companero, String)>(
      context: context,
      showDragHandle: true,
      builder: (_) => SafeArea(
        child: ListView(shrinkWrap: true, children: [
          for (final c in libres)
            ListTile(
              title: Text(c.nombre ?? c.email ?? ''),
              trailing: PopupMenuButton<String>(
                tooltip: t.tareaCompartirAnadir,
                onSelected: (rol) => Navigator.pop(context, (c, rol)),
                itemBuilder: (_) => [PopupMenuItem(value: 'colabora', child: Text(t.tareaRolColabora)), PopupMenuItem(value: 'observa', child: Text(t.tareaRolObserva))],
              ),
            ),
        ]),
      ),
    );
    if (elegido == null || !mounted) return;
    if (await _probar(context, () => _repo.compartir(widget.tareaId, elegido.$1.id!, elegido.$2))) await _cargar();
  }

  Future<void> _quitar(ParticipanteTarea p) async {
    if (await _probar(context, () => _repo.dejarDeCompartir(widget.tareaId, p.usuarioId))) await _cargar();
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    if (_cargado && _lista.isEmpty && !widget.esDueno) return const SizedBox.shrink();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _Cabecera(t.tareaCompartidaCon),
      if (_cargado && _lista.isEmpty) Text(t.tareaCompartirVacio, style: Theme.of(context).textTheme.bodySmall),
      for (final p in _lista)
        ListTile(
          dense: true,
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.person_outline, size: 20),
          title: Text(p.nombre),
          subtitle: Text(p.colabora ? t.tareaRolColabora : t.tareaRolObserva),
          trailing: (widget.esDueno || p.usuarioId == widget.miId) ? IconButton(icon: const Icon(Icons.close), tooltip: t.tareaQuitar, onPressed: () => _quitar(p)) : null,
        ),
      if (widget.esDueno) Align(alignment: Alignment.centerLeft, child: TextButton.icon(onPressed: _anadir, icon: const Icon(Icons.person_add_alt), label: Text(t.tareaCompartirAnadir))),
    ]);
  }
}

// ---------------------------------------------------------------- Recordatorios ----

/// Tus recordatorios en la tarea: a una hora concreta o relativos al vencimiento, con canales, y posponer / quitar.
class BloqueRecordatorios extends ConsumerStatefulWidget {
  final TareaOutlook tarea;
  const BloqueRecordatorios({super.key, required this.tarea});

  @override
  ConsumerState<BloqueRecordatorios> createState() => _BloqueRecordatoriosState();
}

class _BloqueRecordatoriosState extends ConsumerState<BloqueRecordatorios> {
  List<RecordatorioTarea> _lista = const [];
  bool _cargado = false;

  TareasRepositorio get _repo => ref.read(tareasRepositorioProvider);

  @override
  void initState() {
    super.initState();
    _cargar();
  }

  Future<void> _cargar() async {
    try {
      final r = await _repo.recordatorios(widget.tarea.id);
      if (mounted) setState(() => _lista = r);
    } catch (_) {
      // sin red: queda vacío
    }
    if (mounted) setState(() => _cargado = true);
  }

  Future<void> _anadir() async {
    final nuevo = await showModalBottomSheet<_NuevoRecordatorio>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _HojaRecordatorio(conVencimiento: (widget.tarea.fechaVencimiento ?? '').isNotEmpty),
    );
    if (nuevo == null || !mounted) return;
    if (await _probar(context, () => _repo.anadirRecordatorio(widget.tarea.id, avisarEn: nuevo.avisarEn, atajo: nuevo.atajo, canales: nuevo.canales))) await _cargar();
  }

  Future<void> _posponer(RecordatorioTarea r, String opcion) async {
    if (await _probar(context, () => _repo.posponerRecordatorio(r.id, opcion))) await _cargar();
  }

  Future<void> _quitar(RecordatorioTarea r) async {
    if (await _probar(context, () => _repo.quitarRecordatorio(r.id))) await _cargar();
  }

  String _canales(AppLocalizations t, String? canales) =>
      (canales ?? '').split(',').where((c) => c.isNotEmpty).map((c) => switch (c) { 'app' => t.tareaCanalApp, 'correo' => t.tareaCanalCorreo, _ => c }).join(', ');

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final abierta = EstadoTarea.desde(widget.tarea.estado).abierta;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _Cabecera(t.tareaRecordatorios),
      if (_cargado && _lista.isEmpty) Text(t.tareaRecordatoriosVacio, style: Theme.of(context).textTheme.bodySmall),
      for (final r in _lista)
        ListTile(
          dense: true,
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.notifications_none, size: 20),
          title: Text(() {
            final m = MomentoLocal.intentar(r.avisarEn);
            return m == null ? (r.avisarEn ?? '') : context.formatos.momento(m);
          }()),
          subtitle: Text('${_canales(t, r.canales)} · ${(r.enviadoEn ?? '').isNotEmpty ? t.tareaRecordatorioEnviado : t.tareaRecordatorioPendiente}'),
          trailing: Row(mainAxisSize: MainAxisSize.min, children: [
            PopupMenuButton<String>(
              tooltip: t.tareaRecordatorioPosponer,
              icon: const Icon(Icons.snooze),
              onSelected: (o) => _posponer(r, o),
              itemBuilder: (_) => [
                PopupMenuItem(value: '1h', child: Text(t.tareaPospUnaHora)),
                PopupMenuItem(value: 'manana', child: Text(t.tareaPospManana)),
                PopupMenuItem(value: '1s', child: Text(t.tareaPospSemana)),
              ],
            ),
            IconButton(icon: const Icon(Icons.close), tooltip: t.tareaQuitar, onPressed: () => _quitar(r)),
          ]),
        ),
      if (abierta) Align(alignment: Alignment.centerLeft, child: TextButton.icon(onPressed: _anadir, icon: const Icon(Icons.add_alert_outlined), label: Text(t.tareaRecordatorioAnadir))),
    ]);
  }
}

class _NuevoRecordatorio {
  final String? avisarEn;
  final String? atajo;
  final List<String> canales;
  const _NuevoRecordatorio({this.avisarEn, this.atajo, required this.canales});
}

class _HojaRecordatorio extends StatefulWidget {
  final bool conVencimiento;
  const _HojaRecordatorio({required this.conVencimiento});

  @override
  State<_HojaRecordatorio> createState() => _HojaRecordatorioState();
}

class _HojaRecordatorioState extends State<_HojaRecordatorio> {
  String? _atajo; // null = a una hora concreta
  DateTime? _momento;
  bool _app = true, _correo = false;

  Future<void> _elegirMomento() async {
    final ahora = DateTime.now();
    final f = await showDatePicker(context: context, initialDate: _momento ?? ahora, firstDate: DateTime(ahora.year - 1), lastDate: DateTime(ahora.year + 5));
    if (f == null || !mounted) return;
    final h = await showTimePicker(context: context, initialTime: TimeOfDay.fromDateTime(_momento ?? ahora.add(const Duration(hours: 1))));
    if (h == null) return;
    setState(() => _momento = DateTime(f.year, f.month, f.day, h.hour, h.minute));
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    String dos(int n) => n.toString().padLeft(2, '0');
    final valido = _atajo != null || _momento != null;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Wrap(spacing: 8, children: [
            ChoiceChip(label: Text(t.tareaAtajoConcreta), selected: _atajo == null, onSelected: (_) => setState(() => _atajo = null)),
            if (widget.conVencimiento) ...[
              ChoiceChip(label: Text(t.tareaAtajoDia), selected: _atajo == '1d_antes', onSelected: (_) => setState(() => _atajo = '1d_antes')),
              ChoiceChip(label: Text(t.tareaAtajoHora), selected: _atajo == '1h_antes', onSelected: (_) => setState(() => _atajo = '1h_antes')),
              ChoiceChip(label: Text(t.tareaAtajoAlVencer), selected: _atajo == 'al_vencer', onSelected: (_) => setState(() => _atajo = 'al_vencer')),
            ],
          ]),
          if (_atajo == null)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.event_outlined),
              title: Text(_momento == null ? t.tareaHora : '${context.formatos.fecha(Fecha(_momento!.year, _momento!.month, _momento!.day))} ${dos(_momento!.hour)}:${dos(_momento!.minute)}'),
              onTap: _elegirMomento,
            ),
          CheckboxListTile(contentPadding: EdgeInsets.zero, title: Text(t.tareaCanalApp), value: _app, onChanged: (v) => setState(() => _app = v ?? false)),
          CheckboxListTile(contentPadding: EdgeInsets.zero, title: Text(t.tareaCanalCorreo), value: _correo, onChanged: (v) => setState(() => _correo = v ?? false)),
          Align(
            alignment: Alignment.centerRight,
            child: FilledButton(
              onPressed: !valido || (!_app && !_correo)
                  ? null
                  : () => Navigator.pop(
                        context,
                        _NuevoRecordatorio(
                          atajo: _atajo,
                          avisarEn: _atajo == null ? '${_momento!.year}-${dos(_momento!.month)}-${dos(_momento!.day)}T${dos(_momento!.hour)}:${dos(_momento!.minute)}' : null,
                          canales: [if (_app) 'app', if (_correo) 'correo'],
                        ),
                      ),
              child: Text(t.tareaRecordatorioAnadir),
            ),
          ),
        ]),
      ),
    );
  }
}

// ---------------------------------------------------------------- Tiempo dedicado ----

/// El tiempo de la tarea: lo que has registrado, el cronómetro (iniciar, pausar, reanudar, parar) y, si se trabaja en equipo, lo de cada persona. El
/// cronómetro cuenta con la hora del servidor al pedirlo y sigue con el reloj del móvil, así que un móvil con la hora mal puesta no lo desajusta.
class BloqueTiempo extends ConsumerStatefulWidget {
  final TareaOutlook tarea;
  final VoidCallback? alCambiar;
  const BloqueTiempo({super.key, required this.tarea, this.alCambiar});

  @override
  ConsumerState<BloqueTiempo> createState() => _BloqueTiempoState();
}

class _BloqueTiempoState extends ConsumerState<BloqueTiempo> {
  TiempoDeTarea? _tiempo;
  Timer? _reloj;

  TareasRepositorio get _repo => ref.read(tareasRepositorioProvider);

  @override
  void initState() {
    super.initState();
    _cargar();
    _reloj = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted && (_tiempo?.cronometro != null && !_tiempo!.cronometro!.pausado)) setState(() {});
    });
  }

  @override
  void dispose() {
    _reloj?.cancel();
    super.dispose();
  }

  Future<void> _cargar() async {
    try {
      final r = await _repo.tiempo(widget.tarea.id);
      if (mounted) setState(() => _tiempo = r);
    } catch (_) {
      // sin red: el bloque queda como estaba
    }
  }

  Future<void> _hacer(Future<void> Function() f) async {
    if (await _probar(context, f)) {
      await _cargar();
      widget.alCambiar?.call();
    }
  }

  Future<void> _iniciar() async {
    int? proyecto;
    if (widget.tarea.categoriaId == null) {
      // El tiempo se registra en un proyecto: si la tarea no tiene, se pregunta (como en la web).
      final t = AppLocalizations.of(context);
      List<Proyecto> proyectos;
      try {
        proyectos = await _repo.proyectos();
      } on ApiException catch (e) {
        if (mounted) _aviso(context, e.mensaje);
        return;
      }
      if (!mounted || proyectos.isEmpty) return;
      final elegido = await showModalBottomSheet<int>(
        context: context,
        showDragHandle: true,
        builder: (_) => SafeArea(
          child: ListView(shrinkWrap: true, children: [
            Padding(padding: const EdgeInsets.fromLTRB(16, 0, 16, 8), child: Text(t.tareaCronoProyecto, style: Theme.of(context).textTheme.titleMedium)),
            for (final p in proyectos) ListTile(title: Text(p.nombre ?? ''), onTap: () => Navigator.pop(context, p.id)),
          ]),
        ),
      );
      if (elegido == null) return;
      proyecto = elegido;
    }
    await _hacer(() => _repo.iniciarCronometro(widget.tarea.id, proyectoId: proyecto));
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final x = _tiempo;
    final abierta = EstadoTarea.desde(widget.tarea.estado).abierta;
    final crono = x?.cronometro;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _Cabecera(t.tareaTiempo),
      if (x != null && x.mioSegundos > 0)
        Text(t.tareaTiempoRegistrado(duracionCorta((x.mioSegundos / 60).round().clamp(1, 1 << 31))))
      else if (crono == null)
        Text(t.tareaTiempoNada, style: tema.textTheme.bodySmall),
      if (crono != null) ...[
        const SizedBox(height: 8),
        Row(children: [
          Icon(crono.pausado ? Icons.pause_circle_outline : Icons.timer_outlined, color: crono.pausado ? null : tema.colorScheme.primary),
          const SizedBox(width: 8),
          Text(reloj(crono.segundos()), style: tema.textTheme.titleLarge?.copyWith(fontFeatures: const [FontFeature.tabularFigures()])),
          const SizedBox(width: 8),
          Expanded(child: Text(crono.pausado ? t.tareaCronoPausado : t.tareaCronoEnMarcha, style: tema.textTheme.bodySmall)),
        ]),
        Wrap(spacing: 8, children: [
          if (crono.pausado)
            OutlinedButton.icon(onPressed: () => _hacer(() => _repo.reanudarCronometro(crono.id)), icon: const Icon(Icons.play_arrow), label: Text(t.tareaCronoReanudar))
          else
            OutlinedButton.icon(onPressed: () => _hacer(() => _repo.pausarCronometro(crono.id)), icon: const Icon(Icons.pause), label: Text(t.tareaCronoPausar)),
          FilledButton.icon(onPressed: () => _hacer(() => _repo.finalizarCronometro(crono.id)), icon: const Icon(Icons.stop), label: Text(t.tareaCronoFinalizar)),
        ]),
      ] else if (abierta && x != null)
        Align(alignment: Alignment.centerLeft, child: TextButton.icon(onPressed: _iniciar, icon: const Icon(Icons.play_arrow), label: Text(t.tareaCronoIniciar))),
      if (x != null && x.personas.length > 1) ...[
        const SizedBox(height: 8),
        Text(t.tareaTiempoEquipo, style: tema.textTheme.labelLarge),
        for (final p in x.personas)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: Row(children: [Expanded(child: Text(p.nombre)), Text(duracionCorta((p.segundos / 60).round().clamp(1, 1 << 31)))]),
          ),
      ],
    ]);
  }
}

// ---------------------------------------------------------------- Actividad ----

/// El historial de la tarea (quién hizo qué y cuándo), plegado: solo se pide al abrirlo.
class BloqueActividad extends ConsumerStatefulWidget {
  final int tareaId;
  const BloqueActividad({super.key, required this.tareaId});

  @override
  ConsumerState<BloqueActividad> createState() => _BloqueActividadState();
}

class _BloqueActividadState extends ConsumerState<BloqueActividad> {
  List<ActividadDeTarea>? _lista;

  Future<void> _cargar() async {
    if (_lista != null) return;
    try {
      final r = await ref.read(tareasRepositorioProvider).actividad(widget.tareaId);
      if (mounted) setState(() => _lista = r);
    } catch (_) {
      if (mounted) setState(() => _lista = const []);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final lista = _lista;
    return ExpansionTile(
      tilePadding: EdgeInsets.zero,
      title: Text(t.tareaActividad, style: Theme.of(context).textTheme.titleSmall),
      onExpansionChanged: (abierto) {
        if (abierto) _cargar();
      },
      children: [
        if (lista == null) const Padding(padding: EdgeInsets.all(12), child: Center(child: CircularProgressIndicator())),
        if (lista != null && lista.isEmpty) Align(alignment: Alignment.centerLeft, child: Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(t.tareaActividadVacia))),
        for (final a in lista ?? const <ActividadDeTarea>[])
          ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            title: Text(a.detalle),
            subtitle: Text([a.autor, if (MomentoLocal.intentar(a.cuando) != null) context.formatos.momento(MomentoLocal.intentar(a.cuando)!)].where((x) => x.isNotEmpty).join(' · ')),
          ),
      ],
    );
  }
}
