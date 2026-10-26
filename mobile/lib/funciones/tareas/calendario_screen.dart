import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../api/errores.dart';
import '../../api/fechas.dart';
import '../../datos/cola.dart';
import '../../diseno/componentes.dart';
import '../../dominio/tarea.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/destinos.dart';
import '../../nucleo/abrir_destino.dart';
import '../../nucleo/lectura_guardada.dart';
import '../../nucleo/sesion.dart';
import '../pendientes/pendientes_sheet.dart';
import 'cambio_estado.dart';
import 'fila_tarea.dart';
import 'tareas_acciones.dart';
import 'tareas_repositorio.dart';
import 'tareas_vistas.dart';

/// Las vistas del calendario, como en la web.
enum VistaCalendario {
  dia('dia'),
  semanaLaboral('semana_laboral'),
  semana('semana'),
  mes('mes');

  final String valor;
  const VistaCalendario(this.valor);
}

Fecha _hoy() {
  final d = DateTime.now();
  return Fecha(d.year, d.month, d.day);
}

/// El calendario de tareas: la misma información que el de la web (`GET /tareas-outlook/calendario`): tareas (por vencimiento o inicio), vencimientos
/// fiscales, citas y horas fichadas. Se rehace al cambiar de despacho y cuando la cola sin conexión envía algo.
class CalendarioControlador extends AsyncNotifier<CalendarioDeTareas> {
  VistaCalendario vista = VistaCalendario.mes;
  Fecha ancla = _hoy();

  @override
  Future<CalendarioDeTareas> build() {
    ref.watch(estadoSesionProvider.select((e) => e.despacho));
    ref.listen(colaEnviadaProvider, (_, _) => refrescar());
    return ref.read(tareasRepositorioProvider).calendario(vista.valor, ancla);
  }

  Future<void> _pedir() async {
    final anterior = state.value;
    state = const AsyncLoading();
    try {
      state = AsyncData(await ref.read(tareasRepositorioProvider).calendario(vista.valor, ancla));
    } catch (e, st) {
      state = anterior == null ? AsyncError(e, st) : AsyncData(anterior);
    }
  }

  Future<void> refrescar() => _pedir();

  Future<void> cambiarVista(VistaCalendario v) {
    vista = v;
    return _pedir();
  }

  Future<void> irA(Fecha f) {
    ancla = f;
    return _pedir();
  }

  /// Un paso adelante (+1) o atrás (-1): un día, una semana o un mes, según la vista.
  Future<void> paso(int direccion) {
    switch (vista) {
      case VistaCalendario.dia:
        ancla = ancla.masDias(direccion);
      case VistaCalendario.semana || VistaCalendario.semanaLaboral:
        ancla = ancla.masDias(7 * direccion);
      case VistaCalendario.mes:
        final m = ancla.mes - 1 + direccion;
        final anio = ancla.anio + (m / 12).floor();
        final mes = m % 12 + 1;
        final ultimo = DateTime.utc(anio, mes + 1, 0).day;
        ancla = Fecha(anio, mes, ancla.dia > ultimo ? ultimo : ancla.dia);
    }
    return _pedir();
  }
}

final calendarioProvider = AsyncNotifierProvider<CalendarioControlador, CalendarioDeTareas>(CalendarioControlador.new);

/// Qué capas se enseñan (tareas, vencimientos fiscales, citas, fichajes): una elección de la persona, solo en este móvil.
class CapasCalendario extends Notifier<Set<String>> {
  @override
  Set<String> build() => const {'tareas', 'fiscal', 'citas', 'fichaje'};

  void alternar(String capa) => state = state.contains(capa) ? ({...state}..remove(capa)) : {...state, capa};
}

final capasCalendarioProvider = NotifierProvider<CapasCalendario, Set<String>>(CapasCalendario.new);

class CalendarioScreen extends ConsumerStatefulWidget {
  const CalendarioScreen({super.key});

  @override
  ConsumerState<CalendarioScreen> createState() => _CalendarioScreenState();
}

class _CalendarioScreenState extends ConsumerState<CalendarioScreen> {
  String? _diaElegido; // AAAA-MM-DD, en la vista de mes

  String _titulo(BuildContext context, CalendarioControlador c) {
    final idioma = Localizations.localeOf(context).languageCode;
    final d = DateTime(c.ancla.anio, c.ancla.mes, c.ancla.dia);
    switch (c.vista) {
      case VistaCalendario.dia:
        return DateFormat.yMMMMEEEEd(idioma).format(d);
      case VistaCalendario.mes:
        return toBeginningOfSentenceCase(DateFormat.yMMMM(idioma).format(d)) ?? '';
      default:
        final lunes = c.ancla.masDias(1 - c.ancla.diaSemana);
        final fin = lunes.masDias(c.vista == VistaCalendario.semana ? 6 : 4);
        final a = DateTime(lunes.anio, lunes.mes, lunes.dia), b = DateTime(fin.anio, fin.mes, fin.dia);
        return '${DateFormat.MMMd(idioma).format(a)} – ${DateFormat.yMMMd(idioma).format(b)}';
    }
  }

  Future<void> _nuevaTarea(String fecha) async {
    final t = AppLocalizations.of(context);
    final texto = TextEditingController();
    final asunto = await showDialog<String>(
      context: context,
      builder: (d) => AlertDialog(
        title: Text(t.calNuevaTarea),
        content: TextField(controller: texto, autofocus: true, decoration: InputDecoration(hintText: t.calAsuntoNueva), textCapitalization: TextCapitalization.sentences),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d), child: Text(t.comunCancelar)),
          FilledButton(onPressed: () => Navigator.pop(d, texto.text.trim()), child: Text(t.tareaGuardar)),
        ],
      ),
    );
    if (asunto == null || asunto.isEmpty || !mounted) return;
    final mensajero = ScaffoldMessenger.of(context);
    try {
      final r = await ref.read(accionesTareasProvider).crear(asunto, fechaVencimiento: fecha);
      if (r.encolada) mensajero.showSnackBar(SnackBar(content: Text(t.colaGuardada)));
      await ref.read(calendarioProvider.notifier).refrescar();
    } on ApiException catch (e) {
      mensajero.showSnackBar(SnackBar(content: Text(e.mensaje)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final calendario = ref.watch(calendarioProvider);
    final c = ref.read(calendarioProvider.notifier);
    final capas = ref.watch(capasCalendarioProvider);
    final etiquetasVista = {
      VistaCalendario.dia: t.calVistaDia,
      VistaCalendario.semanaLaboral: t.calVistaSemanaLaboral,
      VistaCalendario.semana: t.calVistaSemana,
      VistaCalendario.mes: t.calVistaMes,
    };
    return Scaffold(
      appBar: AppBar(title: Text(t.tareasTitulo)),
      body: Column(children: [
        const AvisoDatosGuardados(prefijo: '/tareas-outlook'),
        const AvisoPendientes(),
        const SubnavTareas(),
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 4, 4, 0),
          child: Row(children: [
            IconButton(icon: const Icon(Icons.chevron_left), tooltip: t.tareasAnterior, onPressed: () => c.paso(-1)),
            IconButton(icon: const Icon(Icons.chevron_right), tooltip: t.tareasSiguiente, onPressed: () => c.paso(1)),
            Expanded(child: Text(_titulo(context, c), style: Theme.of(context).textTheme.titleMedium, overflow: TextOverflow.ellipsis)),
            TextButton(
              onPressed: () {
                setState(() => _diaElegido = null);
                c.irA(_hoy());
              },
              child: Text(t.calHoy),
            ),
            PopupMenuButton<VistaCalendario>(
              tooltip: etiquetasVista[c.vista],
              icon: const Icon(Icons.view_agenda_outlined),
              onSelected: c.cambiarVista,
              itemBuilder: (_) => [for (final e in etiquetasVista.entries) CheckedPopupMenuItem(value: e.key, checked: c.vista == e.key, child: Text(e.value))],
            ),
          ]),
        ),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          child: Row(children: [
            for (final (clave, etiqueta) in [('tareas', t.calCapaTareas), ('fiscal', t.calCapaFiscal), ('citas', t.calCapaCitas), ('fichaje', t.calCapaFichajes)])
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: FilterChip(label: Text(etiqueta), selected: capas.contains(clave), onSelected: (_) => ref.read(capasCalendarioProvider.notifier).alternar(clave)),
              ),
          ]),
        ),
        Expanded(
          child: calendario.when(
            loading: () => const EsqueletoLista(),
            error: (e, _) => EstadoError(error: e, alReintentar: c.refrescar),
            data: (cal) => RefreshIndicator(
              onRefresh: c.refrescar,
              child: _Cuerpo(cal: cal, vista: c.vista, capas: capas, diaElegido: _diaElegido, alElegirDia: (d) => setState(() => _diaElegido = d), alNuevaTarea: _nuevaTarea),
            ),
          ),
        ),
      ]),
    );
  }
}

class _Cuerpo extends ConsumerWidget {
  final CalendarioDeTareas cal;
  final VistaCalendario vista;
  final Set<String> capas;
  final String? diaElegido;
  final void Function(String) alElegirDia;
  final void Function(String) alNuevaTarea;
  const _Cuerpo({required this.cal, required this.vista, required this.capas, required this.diaElegido, required this.alElegirDia, required this.alNuevaTarea});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final avisoCitas = cal.avisoCitas == null ? null : BannerEstado(tipo: TipoBanner.aviso, texto: t.calAvisoCitas(cal.avisoCitas!));
    if (vista == VistaCalendario.mes) {
      final elegido = diaElegido ?? cal.dias.where((d) => d.esHoy).firstOrNull?.fecha ?? cal.fecha;
      final dia = cal.dias.where((d) => d.fecha == elegido).firstOrNull;
      return ListView(physics: const AlwaysScrollableScrollPhysics(), children: [
        ?avisoCitas,
        _MesGrid(cal: cal, capas: capas, elegido: elegido, alElegir: alElegirDia),
        const Divider(height: 24),
        if (dia != null) _Agenda(dia: dia, capas: capas, conTitulo: true, alNuevaTarea: alNuevaTarea),
      ]);
    }
    return ListView(physics: const AlwaysScrollableScrollPhysics(), padding: const EdgeInsets.only(bottom: 24), children: [
      ?avisoCitas,
      for (final d in cal.dias) _Agenda(dia: d, capas: capas, conTitulo: vista != VistaCalendario.dia, alNuevaTarea: alNuevaTarea, mostrarVacio: vista == VistaCalendario.dia),
    ]);
  }
}

bool _hay(DiaCalendario d, Set<String> capas) =>
    (capas.contains('tareas') && d.tareas.isNotEmpty) || (capas.contains('fiscal') && d.vencimientos.isNotEmpty) || (capas.contains('citas') && d.citas.isNotEmpty) || (capas.contains('fichaje') && d.fichadoSegundos > 0);

/// El mes en cuadrícula (semanas completas, lunes a domingo, como la web): cada día con el número y marcas de qué tiene.
class _MesGrid extends StatelessWidget {
  final CalendarioDeTareas cal;
  final Set<String> capas;
  final String elegido;
  final void Function(String) alElegir;
  const _MesGrid({required this.cal, required this.capas, required this.elegido, required this.alElegir});

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final nombres = MaterialLocalizations.of(context).narrowWeekdays; // domingo primero
    final lunesPrimero = [...nombres.skip(1), nombres.first];
    final semanas = [for (var i = 0; i < cal.dias.length; i += 7) cal.dias.sublist(i, i + 7 > cal.dias.length ? cal.dias.length : i + 7)];
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
      child: Column(children: [
        Row(children: [for (final n in lunesPrimero) Expanded(child: Center(child: Text(n, style: tema.textTheme.labelMedium)))]),
        for (final semana in semanas)
          Row(children: [
            for (final d in semana)
              Expanded(
                child: Semantics(
                  button: true,
                  selected: d.fecha == elegido,
                  child: InkWell(
                    borderRadius: BorderRadius.circular(8),
                    onTap: () => alElegir(d.fecha),
                    child: Container(
                      height: 52,
                      margin: const EdgeInsets.all(1.5),
                      decoration: BoxDecoration(
                        color: d.fecha == elegido ? tema.colorScheme.primaryContainer : null,
                        border: d.esHoy ? Border.all(color: tema.colorScheme.primary, width: 1.5) : null,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                        Text(
                          '${int.parse(d.fecha.substring(8, 10))}',
                          style: tema.textTheme.bodyMedium?.copyWith(
                            fontWeight: d.esHoy ? FontWeight.w700 : null,
                            color: d.esMesActual ? null : tema.colorScheme.outline,
                          ),
                        ),
                        const SizedBox(height: 3),
                        Row(mainAxisSize: MainAxisSize.min, children: [
                          if (capas.contains('tareas') && d.tareas.isNotEmpty) _Punto(color: tema.colorScheme.primary, texto: d.tareas.length > 1 ? '${d.tareas.length}' : null),
                          if (capas.contains('fiscal') && d.vencimientos.isNotEmpty) _Punto(color: tema.colorScheme.tertiary),
                          if (capas.contains('citas') && d.citas.isNotEmpty) _Punto(color: tema.colorScheme.secondary),
                          if (capas.contains('fichaje') && d.fichadoSegundos > 0) _Punto(color: tema.colorScheme.outline),
                        ]),
                      ]),
                    ),
                  ),
                ),
              ),
          ]),
      ]),
    );
  }
}

class _Punto extends StatelessWidget {
  final Color color;
  final String? texto;
  const _Punto({required this.color, this.texto});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 1.5),
        child: texto == null
            ? Container(width: 6, height: 6, decoration: BoxDecoration(color: color, shape: BoxShape.circle))
            : Container(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(6)),
                child: Text(texto!, style: TextStyle(fontSize: 9, color: Theme.of(context).colorScheme.onPrimary, fontWeight: FontWeight.w700)),
              ),
      );
}

/// Lo de un día: horas fichadas, vencimientos fiscales, citas y tareas (con su casilla para completarlas).
class _Agenda extends ConsumerWidget {
  final DiaCalendario dia;
  final Set<String> capas;
  final bool conTitulo;
  final bool mostrarVacio;
  final void Function(String) alNuevaTarea;
  const _Agenda({required this.dia, required this.capas, required this.conTitulo, required this.alNuevaTarea, this.mostrarVacio = true});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final idioma = Localizations.localeOf(context).languageCode;
    final fecha = Fecha.parse(dia.fecha);
    final hay = _hay(dia, capas);
    if (!hay && !mostrarVacio && !conTitulo) return const SizedBox.shrink();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (conTitulo)
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 8, 0),
          child: Row(children: [
            Expanded(
              child: Text(
                toBeginningOfSentenceCase(DateFormat.MMMMEEEEd(idioma).format(DateTime(fecha.anio, fecha.mes, fecha.dia))) ?? '',
                style: tema.textTheme.titleSmall?.copyWith(color: dia.esHoy ? tema.colorScheme.primary : null),
              ),
            ),
            IconButton(icon: const Icon(Icons.add), tooltip: t.calNuevaTarea, onPressed: () => alNuevaTarea(dia.fecha)),
          ]),
        ),
      if (capas.contains('fichaje') && dia.fichadoSegundos > 0)
        ListTile(dense: true, leading: const Icon(Icons.schedule, size: 20), title: Text(t.calHorasFichadas(duracionCorta((dia.fichadoSegundos / 60).round().clamp(1, 1 << 31))))),
      if (capas.contains('fiscal'))
        for (final v in dia.vencimientos)
          ListTile(
            dense: true,
            leading: Icon(v.presentado ? Icons.task_alt : Icons.account_balance_outlined, size: 20),
            title: Text('${v.modelo} · ${v.cliente}', style: v.presentado ? const TextStyle(decoration: TextDecoration.lineThrough) : null),
            subtitle: v.periodo == null ? null : Text(v.periodo!),
            onTap: () => ref.read(navegadorDeAvisosProvider).abrir(Destino('vencimiento', v.id)),
          ),
      if (capas.contains('citas'))
        for (final c in dia.citas)
          ListTile(
            dense: true,
            leading: const Icon(Icons.event_available_outlined, size: 20),
            title: Text(c.titulo),
            subtitle: (c.inicio ?? '').length >= 16 ? Text(c.inicio!.substring(11, 16)) : null,
          ),
      if (capas.contains('tareas'))
        for (final tarea in dia.tareas)
          FilaTarea(
            key: ValueKey('${dia.fecha}_${tarea.id}'),
            tarea: tarea,
            alCompletar: (x) async {
              await cambiarEstadoConAviso(context, ref, x, EstadoTarea.completada, alCambiar: (_) => ref.read(calendarioProvider.notifier).refrescar());
            },
          ),
      if (!hay && mostrarVacio)
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
          child: Row(children: [
            Expanded(child: Text(t.calSinNada, style: tema.textTheme.bodySmall)),
            if (!conTitulo) TextButton.icon(onPressed: () => alNuevaTarea(dia.fecha), icon: const Icon(Icons.add), label: Text(t.calNuevaTarea)),
          ]),
        ),
    ]);
  }
}
