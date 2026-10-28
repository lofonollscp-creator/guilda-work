import 'package:flutter/material.dart';

import '../../nucleo/abrir_asistente.dart';
import '../../nucleo/panel_asistente.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../api/errores.dart';
import '../../api/fechas.dart';
import '../../datos/cola.dart';
import '../../diseno/componentes.dart';
import '../../dominio/tarea.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/lectura_guardada.dart';
import '../../nucleo/sesion.dart';
import '../pendientes/pendientes_sheet.dart';
import 'tarea_detalle_screen.dart';
import 'tareas_repositorio.dart';
import 'tareas_vistas.dart';

Fecha _lunesDe(Fecha f) => f.masDias(1 - f.diaSemana);

/// El plan de carga de la semana por persona del despacho (`GET /tareas-outlook/carga`): horas estimadas de las tareas que vencen cada día frente a la jornada,
/// con las atrasadas y las que no tienen fecha. Se rehace al cambiar de despacho y cuando la cola sin conexión envía algo.
class CargaControlador extends AsyncNotifier<CargaSemanal> {
  Fecha semana = _lunesDe(Fecha(DateTime.now().year, DateTime.now().month, DateTime.now().day));

  @override
  Future<CargaSemanal> build() {
    ref.watch(estadoSesionProvider.select((e) => e.despacho));
    ref.listen(colaEnviadaProvider, (_, _) => refrescar());
    return ref.read(tareasRepositorioProvider).carga(semana);
  }

  Future<void> refrescar() async {
    final anterior = state.value;
    try {
      state = AsyncData(await ref.read(tareasRepositorioProvider).carga(semana));
    } catch (e, st) {
      state = anterior == null ? AsyncError(e, st) : AsyncData(anterior);
    }
  }

  Future<void> irA(Fecha lunes) {
    semana = _lunesDe(lunes);
    return refrescar();
  }
}

final cargaProvider = AsyncNotifierProvider<CargaControlador, CargaSemanal>(CargaControlador.new);

class CargaScreen extends ConsumerWidget {
  const CargaScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) => ConAsistenteLateral(contexto: AppLocalizations.of(context).tareasTitulo, anchoMinimo: anchoConAsistente, hijo: _pantalla(context, ref));

  Widget _pantalla(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final carga = ref.watch(cargaProvider);
    final c = ref.read(cargaProvider.notifier);
    final idioma = Localizations.localeOf(context).languageCode;
    final fin = c.semana.masDias(6);
    final titulo = '${DateFormat.MMMd(idioma).format(DateTime(c.semana.anio, c.semana.mes, c.semana.dia))} – ${DateFormat.yMMMd(idioma).format(DateTime(fin.anio, fin.mes, fin.dia))}';
    return Scaffold(
      appBar: AppBar(title: Text(t.tareasTitulo), actions: [AccionAsistente(contexto: t.tareasTitulo, anchoMinimoPanel: anchoConAsistente)]),
      body: Column(children: [
        const AvisoDatosGuardados(prefijo: '/tareas-outlook'),
        const AvisoPendientes(),
        const SubnavTareas(),
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 4, 4, 0),
          child: Row(children: [
            IconButton(icon: const Icon(Icons.chevron_left), tooltip: t.tareasAnterior, onPressed: () => c.irA(c.semana.masDias(-7))),
            IconButton(icon: const Icon(Icons.chevron_right), tooltip: t.tareasSiguiente, onPressed: () => c.irA(c.semana.masDias(7))),
            Expanded(child: Text(titulo, style: Theme.of(context).textTheme.titleMedium, overflow: TextOverflow.ellipsis)),
            TextButton(onPressed: () => c.irA(Fecha(DateTime.now().year, DateTime.now().month, DateTime.now().day)), child: Text(t.cargaEstaSemana)),
          ]),
        ),
        Expanded(
          child: carga.when(
            loading: () => const EsqueletoLista(),
            error: (e, _) => EstadoError(error: e, alReintentar: c.refrescar),
            data: (datos) => RefreshIndicator(
              onRefresh: c.refrescar,
              child: ListView(padding: const EdgeInsets.fromLTRB(12, 8, 12, 24), physics: const AlwaysScrollableScrollPhysics(), children: [
                if (datos.personas.length < 2) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(t.cargaSoloTu, style: Theme.of(context).textTheme.bodySmall)),
                for (final p in datos.personas) _TarjetaPersona(persona: p, carga: datos),
              ]),
            ),
          ),
        ),
      ]),
    );
  }
}

Color _colorNivel(BuildContext context, NivelCarga n) {
  final esquema = Theme.of(context).colorScheme;
  return switch (n) {
    NivelCarga.rojo => esquema.errorContainer,
    NivelCarga.ambar => Colors.amber.withValues(alpha: 0.30),
    NivelCarga.verde => Colors.green.withValues(alpha: 0.22),
    NivelCarga.ninguno => esquema.surfaceContainerHighest,
  };
}

class _TarjetaPersona extends ConsumerWidget {
  final PersonaDeCarga persona;
  final CargaSemanal carga;
  const _TarjetaPersona({required this.persona, required this.carga});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final idioma = Localizations.localeOf(context).languageCode;
    final nivelSemana = CeldaDeCarga(persona.semanaMin, 1, 0, 0, const []).nivel(persona.capacidadSemanaMin);
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(persona.yo ? '${persona.nombre} (${t.cargaTu})' : persona.nombre, style: tema.textTheme.titleSmall, overflow: TextOverflow.ellipsis)),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(color: _colorNivel(context, nivelSemana), borderRadius: BorderRadius.circular(8)),
              child: Text('${t.cargaSemanaTotal}: ${duracionCorta(persona.semanaMin)} / ${duracionCorta(persona.capacidadSemanaMin)}', style: tema.textTheme.labelMedium),
            ),
          ]),
          const SizedBox(height: 8),
          Wrap(spacing: 6, runSpacing: 6, children: [
            if (persona.atrasadas.n > 0) _Celda(etiqueta: t.cargaAtrasadas, celda: persona.atrasadas, capacidad: 0, persona: persona, carga: carga),
            for (final dia in carga.dias)
              _Celda(
                etiqueta: toBeginningOfSentenceCase(DateFormat('E d', idioma).format(DateTime.parse(dia))) ?? dia,
                celda: persona.dias[dia] ?? CeldaDeCarga.vacia,
                capacidad: DateTime.parse(dia).weekday <= 5 ? persona.capacidadDiaMin : 0,
                persona: persona,
                carga: carga,
                fecha: dia,
              ),
            if (persona.sinFecha.n > 0) _Celda(etiqueta: t.cargaSinFecha, celda: persona.sinFecha, capacidad: 0, persona: persona, carga: carga),
          ]),
        ]),
      ),
    );
  }
}

class _Celda extends ConsumerWidget {
  final String etiqueta;
  final CeldaDeCarga celda;
  final int capacidad;
  final PersonaDeCarga persona;
  final CargaSemanal carga;
  final String? fecha;
  const _Celda({required this.etiqueta, required this.celda, required this.capacidad, required this.persona, required this.carga, this.fecha});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tema = Theme.of(context);
    final t = AppLocalizations.of(context);
    return Semantics(
      button: celda.n > 0,
      label: '$etiqueta: ${celda.n == 0 ? '—' : duracionCorta(celda.minutos)}',
      excludeSemantics: true,
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: celda.n == 0 ? null : () => showModalBottomSheet<void>(context: context, isScrollControlled: true, showDragHandle: true, builder: (_) => _HojaCelda(titulo: '${persona.nombre} · $etiqueta', celda: celda, carga: carga, fecha: fecha)),
        child: Container(
          width: 76,
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
          decoration: BoxDecoration(color: _colorNivel(context, celda.nivel(capacidad)), borderRadius: BorderRadius.circular(8)),
          child: Column(children: [
            Text(etiqueta, style: tema.textTheme.labelSmall, maxLines: 1, overflow: TextOverflow.ellipsis),
            const SizedBox(height: 2),
            Text(celda.n == 0 ? '—' : (celda.minutos > 0 ? duracionCorta(celda.minutos) : '${celda.n}'), style: tema.textTheme.titleSmall),
            if (celda.sinEstimar > 0) Text(t.cargaSinEstimar(celda.sinEstimar), style: tema.textTheme.labelSmall, maxLines: 1, overflow: TextOverflow.ellipsis),
          ]),
        ),
      ),
    );
  }
}

/// Las tareas de una celda; mantener pulsada una abre sus acciones: reasignarla a otra persona o cambiarle el día (como arrastrarla en la web).
class _HojaCelda extends ConsumerWidget {
  final String titulo;
  final CeldaDeCarga celda;
  final CargaSemanal carga;
  final String? fecha;
  const _HojaCelda({required this.titulo, required this.celda, required this.carga, this.fecha});

  Future<void> _mover(BuildContext context, WidgetRef ref, TareaDeCarga tarea, {bool persona = false, int? personaId, bool dia = false, String? nuevoDia}) async {
    final t = AppLocalizations.of(context);
    final mensajero = ScaffoldMessenger.of(context);
    try {
      await ref.read(tareasRepositorioProvider).mover(tarea.id, cambiarPersona: persona, personaId: personaId, cambiarFecha: dia, fecha: nuevoDia);
      await ref.read(cargaProvider.notifier).refrescar();
      mensajero.showSnackBar(SnackBar(content: Text(t.cargaMovida)));
      if (context.mounted) Navigator.pop(context);
    } on ApiException catch (e) {
      mensajero.showSnackBar(SnackBar(content: Text(e.mensaje)));
    }
  }

  Future<void> _acciones(BuildContext context, WidgetRef ref, TareaDeCarga tarea) async {
    final t = AppLocalizations.of(context);
    final eleccion = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (_) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(leading: const Icon(Icons.person_outline), title: Text(t.cargaReasignar), onTap: () => Navigator.pop(context, 'persona')),
          ListTile(leading: const Icon(Icons.event_outlined), title: Text(t.cargaCambiarDia), onTap: () => Navigator.pop(context, 'dia')),
          ListTile(leading: const Icon(Icons.event_busy_outlined), title: Text(t.cargaQuitarFecha), onTap: () => Navigator.pop(context, 'sin')),
        ]),
      ),
    );
    if (eleccion == null || !context.mounted) return;
    switch (eleccion) {
      case 'persona':
        final id = await showModalBottomSheet<(int?,)>(
          context: context,
          showDragHandle: true,
          builder: (_) => SafeArea(
            child: ListView(shrinkWrap: true, children: [
              for (final p in carga.personas) ListTile(title: Text(p.nombre), onTap: () => Navigator.pop(context, (p.id,))),
            ]),
          ),
        );
        if (id != null && context.mounted) await _mover(context, ref, tarea, persona: true, personaId: id.$1);
      case 'dia':
        final ahora = DateTime.now();
        final inicial = fecha == null ? ahora : DateTime.parse(fecha!);
        final d = await showDatePicker(context: context, initialDate: inicial, firstDate: DateTime(ahora.year - 1), lastDate: DateTime(ahora.year + 5));
        if (d != null && context.mounted) await _mover(context, ref, tarea, dia: true, nuevoDia: Fecha(d.year, d.month, d.day).toJson());
      case 'sin':
        await _mover(context, ref, tarea, dia: true, nuevoDia: null);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    return SafeArea(
      child: ListView(shrinkWrap: true, children: [
        Padding(padding: const EdgeInsets.fromLTRB(16, 0, 16, 8), child: Text(titulo, style: tema.textTheme.titleMedium)),
        for (final x in celda.tareas)
          ListTile(
            dense: true,
            title: Text(x.asunto, maxLines: 2, overflow: TextOverflow.ellipsis, style: x.prioridad == 'alta' ? const TextStyle(fontWeight: FontWeight.w700) : null),
            trailing: Text(x.estimacionMin == null ? '' : duracionCorta(x.estimacionMin!), style: tema.textTheme.labelMedium),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => TareaDetalleScreen(tareaId: x.id))),
            onLongPress: () => _acciones(context, ref, x),
            leading: IconButton(icon: const Icon(Icons.more_vert), onPressed: () => _acciones(context, ref, x)),
          ),
        if (celda.mas > 0) Padding(padding: const EdgeInsets.fromLTRB(16, 4, 16, 12), child: Text(t.cargaYMas(celda.mas), style: tema.textTheme.bodySmall)),
      ]),
    );
  }
}
