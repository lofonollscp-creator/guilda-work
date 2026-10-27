import 'package:flutter/material.dart';

import '../../nucleo/abrir_asistente.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errores.dart';
import '../../api/generado/modelos.g.dart';
import '../../diseno/componentes.dart';
import '../../diseno/formatos.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/lectura_guardada.dart';
import '../pendientes/pendientes_sheet.dart';
import 'nota_screen.dart';
import 'notas_acciones.dart';
import 'notas_lista_controlador.dart';
import 'notas_repositorio.dart';
import 'texto_nota.dart';

/// Las notas: lo tuyo y lo que te han compartido, las fijadas primero. Buscar, filtrar por ámbito y proyecto, fijar y borrar (con «Deshacer») desde la lista.
class NotasScreen extends ConsumerStatefulWidget {
  const NotasScreen({super.key});

  @override
  ConsumerState<NotasScreen> createState() => _NotasScreenState();
}

class _NotasScreenState extends ConsumerState<NotasScreen> {
  final _scroll = ScrollController();
  final _buscar = TextEditingController();
  bool _buscando = false;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels > _scroll.position.maxScrollExtent - 300) ref.read(notasListaProvider.notifier).masResultados();
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    _buscar.dispose();
    super.dispose();
  }

  Future<void> _abrir(int? id) async {
    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => NotaScreen(notaId: id)));
    if (mounted) ref.read(notasListaProvider.notifier).recargar();
  }

  Future<void> _fijar(Nota n) async {
    final mensajero = ScaffoldMessenger.of(context);
    try {
      final nueva = await ref.read(notasRepositorioProvider).fijar(n.id, n.fijada != 1);
      ref.read(notasListaProvider.notifier).reemplazar(nueva);
    } on ApiException catch (e) {
      mensajero.showSnackBar(SnackBar(content: Text(e.mensaje)));
    }
  }

  Future<void> _eliminar(Nota n) async {
    if (!await eliminarNotaConDeshacer(context, ref, n)) ref.read(notasListaProvider.notifier).recargar(); // la fila ya se deslizó fuera
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final estado = ref.watch(notasListaProvider);
    final c = ref.read(notasListaProvider.notifier);
    return Scaffold(
      appBar: AppBar(
        title: _buscando
            ? TextField(
                controller: _buscar,
                autofocus: true,
                decoration: InputDecoration(hintText: t.notasBuscar, border: InputBorder.none),
                textInputAction: TextInputAction.search,
                onSubmitted: c.buscar,
              )
            : Text(t.notasTitulo),
        actions: [
          AccionAsistente(contexto: t.notasTitulo),
          IconButton(
            icon: Icon(_buscando ? Icons.close : Icons.search),
            tooltip: t.notasBuscar,
            onPressed: () {
              if (_buscando) {
                _buscar.clear();
                c.buscar('');
              }
              setState(() => _buscando = !_buscando);
            },
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(onPressed: () => _abrir(null), icon: const Icon(Icons.add), label: Text(t.notasNueva)),
      body: Column(children: [
        const AvisoDatosGuardados(prefijo: '/notas'),
        const AvisoPendientes(),
        _Filtros(estado: estado),
        Expanded(child: _Cuerpo(estado: estado, scroll: _scroll, alAbrir: _abrir, alFijar: _fijar, alEliminar: _eliminar)),
      ]),
    );
  }
}

/// Una fila de filtros: ámbito (todas, mías, compartidas conmigo) y proyecto.
class _Filtros extends ConsumerWidget {
  final EstadoNotas estado;
  const _Filtros({required this.estado});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final c = ref.read(notasListaProvider.notifier);
    final proyectos = ref.watch(proyectosProvider).value ?? const <Proyecto>[];
    final ambitos = {AmbitoNotas.todas: t.notasAmbitoTodas, AmbitoNotas.mias: t.notasAmbitoMias, AmbitoNotas.compartidas: t.notasAmbitoCompartidas};
    final proyecto = proyectos.where((p) => p.id == estado.proyectoId).firstOrNull;
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
      child: Row(children: [
        PildoraMenu<AmbitoNotas>(
          icono: Icons.person_outline,
          texto: ambitos[estado.ambito]!,
          activo: estado.ambito != AmbitoNotas.todas,
          opciones: [for (final e in ambitos.entries) (e.key, e.value)],
          seleccionado: estado.ambito,
          alElegir: c.cambiarAmbito,
        ),
        if (proyectos.isNotEmpty) ...[
          const SizedBox(width: 8),
          PildoraMenu<int?>(
            icono: Icons.folder_outlined,
            texto: proyecto?.nombre ?? t.notasTodosProyectos,
            activo: proyecto != null,
            opciones: [(null, t.notasTodosProyectos), for (final p in proyectos) (p.id, p.nombre ?? '')],
            seleccionado: estado.proyectoId,
            alElegir: c.cambiarProyecto,
          ),
        ],
      ]),
    );
  }
}

class _Cuerpo extends ConsumerWidget {
  final EstadoNotas estado;
  final ScrollController scroll;
  final Future<void> Function(int?) alAbrir;
  final Future<void> Function(Nota) alFijar;
  final Future<void> Function(Nota) alEliminar;
  const _Cuerpo({required this.estado, required this.scroll, required this.alAbrir, required this.alFijar, required this.alEliminar});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final c = ref.read(notasListaProvider.notifier);
    if (estado.notas.isEmpty) {
      if (estado.cargando) return const EsqueletoLista();
      final buscando = estado.busqueda.isNotEmpty || estado.proyectoId != null || estado.ambito != AmbitoNotas.todas;
      return RefreshIndicator(
        onRefresh: c.recargar,
        child: ListView(controller: scroll, physics: const AlwaysScrollableScrollPhysics(), children: [
          SizedBox(
            height: 360,
            child: estado.error != null
                ? EstadoError(error: estado.error!, alReintentar: c.recargar)
                : EstadoVacio(icono: buscando ? Icons.search_off : Icons.sticky_note_2_outlined, titulo: buscando ? t.notasSinResultados : t.notasVacio, detalle: buscando ? null : t.notasVacioDetalle),
          ),
        ]),
      );
    }
    return RefreshIndicator(
      onRefresh: c.recargar,
      child: ListView.builder(
        controller: scroll,
        padding: const EdgeInsets.only(bottom: 96),
        itemCount: estado.notas.length + (estado.cargando ? 1 : 0),
        itemBuilder: (context, i) {
          if (i >= estado.notas.length) return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
          final n = estado.notas[i];
          return _Tarjeta(key: ValueKey('nota-${n.id}'), nota: n, alAbrir: () => alAbrir(n.id), alFijar: () => alFijar(n), alEliminar: () => alEliminar(n));
        },
      ),
    );
  }
}

/// Cómo se ve una nota en una lista: su título y el principio del texto. Sin título, la primera línea con texto hace de título y el resto, de principio.
({String titulo, String resto}) partesDeNota(Nota n) {
  final titulo = (n.titulo ?? '').trim();
  final texto = n.texto ?? '';
  if (titulo.isNotEmpty) return (titulo: titulo, resto: textoPlanoDeNota(texto));
  final lineas = texto.split('\n');
  final i = lineas.indexWhere((l) => l.trim().isNotEmpty);
  if (i < 0) return (titulo: '', resto: '');
  return (titulo: textoPlanoDeNota(lineas[i]), resto: textoPlanoDeNota(lineas.skip(i + 1).join('\n')));
}

class _Tarjeta extends StatelessWidget {
  final Nota nota;
  final VoidCallback alAbrir;
  final VoidCallback alFijar;
  final VoidCallback alEliminar;
  const _Tarjeta({super.key, required this.nota, required this.alAbrir, required this.alFijar, required this.alEliminar});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final fijada = nota.fijada == 1;
    final esDueno = nota.rol == null || nota.rol == NotaRol.dueno;
    final (:titulo, :resto) = partesDeNota(nota);
    final fecha = context.formatos.deServidor(nota.creadaEn);
    final tarjeta = Material(
      color: tema.colorScheme.surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: BorderSide(color: tema.colorScheme.outlineVariant)),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: alAbrir,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 4, 12),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(titulo.isEmpty ? t.notasNueva : titulo, style: tema.textTheme.titleMedium, maxLines: 2, overflow: TextOverflow.ellipsis),
                if (resto.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(resto, style: tema.textTheme.bodyMedium?.copyWith(color: tema.colorScheme.onSurfaceVariant), maxLines: 2, overflow: TextOverflow.ellipsis),
                ],
                const SizedBox(height: 8),
                Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  if (fijada) Pildora(icono: Icons.push_pin_outlined, texto: t.notasFijada),
                  if ((nota.categoriaNombre ?? '').isNotEmpty) Pildora(icono: Icons.folder_outlined, texto: nota.categoriaNombre!),
                  if (!esDueno) Pildora(icono: Icons.person_outline, texto: t.notasDeNombre(nota.duenoNombre ?? ''))
                  else if ((nota.nParticipantes ?? 0) > 0) Pildora(icono: Icons.group_outlined, texto: t.notasCompartida),
                  if (nota.rol == NotaRol.observa) Pildora(icono: Icons.lock_outline, texto: t.notasRolObserva),
                  if ((nota.nAdjuntos ?? 0) > 0) Pildora(icono: Icons.attach_file, texto: '${nota.nAdjuntos}'),
                  if (fecha != null) Pildora(icono: Icons.event_outlined, texto: fecha),
                ]),
              ]),
            ),
            if (esDueno)
              PopupMenuButton<String>(
                icon: const Icon(Icons.more_vert),
                onSelected: (v) => v == 'fijar' ? alFijar() : alEliminar(),
                itemBuilder: (_) => [
                  PopupMenuItem(value: 'fijar', child: Text(fijada ? t.notasDesfijar : t.notasFijar)),
                  PopupMenuItem(value: 'eliminar', child: Text(t.notasEliminar)),
                ],
              )
            else
              const SizedBox(width: 10),
          ]),
        ),
      ),
    );
    final con = Padding(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4), child: tarjeta);
    if (!esDueno) return con;
    return Dismissible(
      key: ValueKey('desliza-nota-${nota.id}'),
      direction: DismissDirection.endToStart,
      background: Container(
        margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        decoration: BoxDecoration(color: tema.colorScheme.errorContainer, borderRadius: BorderRadius.circular(16)),
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 20),
        child: Icon(Icons.delete_outline, color: tema.colorScheme.onErrorContainer),
      ),
      onDismissed: (_) => alEliminar(),
      child: con,
    );
  }
}
