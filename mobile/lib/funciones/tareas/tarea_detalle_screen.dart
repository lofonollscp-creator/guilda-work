import 'dart:io';

import 'package:dio/dio.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../../nucleo/abrir_asistente.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';

import '../../api/errores.dart';
import '../../api/fechas.dart';
import '../../api/generado/modelos.g.dart';
import '../../diseno/componentes.dart';
import '../../diseno/estados.dart';
import '../../diseno/formatos.dart';
import '../../dominio/tarea.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/lectura_guardada.dart';
import '../../datos/local/cola_escritura.dart' show ColaLlena;
import '../../nucleo/sesion.dart';
import 'tarea_bloques.dart';
import 'tarea_editor_screen.dart';
import '../../theme/brand_colors.dart';
import 'tareas_acciones.dart';
import 'tareas_lista_controlador.dart';
import 'tareas_repositorio.dart';
import 'textos.dart';

/// Qué hace la persona cuando alguien cambió la tarea mientras la tenía abierta.
enum ResolucionConflicto { ver, aplicar, descartar }

class _Datos {
  final TareaOutlook tarea;
  final List<Subtarea> subtareas;
  final List<ChecklistItem> checklist;
  final List<ComentarioTarea> comentarios;
  final List<AdjuntoTarea> adjuntos;
  const _Datos(this.tarea, this.subtareas, this.checklist, this.comentarios, this.adjuntos);

  _Datos con({TareaOutlook? tarea, List<Subtarea>? subtareas, List<ChecklistItem>? checklist, List<ComentarioTarea>? comentarios, List<AdjuntoTarea>? adjuntos}) =>
      _Datos(tarea ?? this.tarea, subtareas ?? this.subtareas, checklist ?? this.checklist, comentarios ?? this.comentarios, adjuntos ?? this.adjuntos);
}

/// La tarea entera: estado (con control de versión), notas, subtareas, lista de comprobación, comentarios y adjuntos.
class TareaDetalleScreen extends ConsumerStatefulWidget {
  final int tareaId;
  const TareaDetalleScreen({super.key, required this.tareaId});

  @override
  ConsumerState<TareaDetalleScreen> createState() => _TareaDetalleScreenState();
}

class _TareaDetalleScreenState extends ConsumerState<TareaDetalleScreen> {
  _Datos? _datos;
  Object? _error;
  bool _cargando = true;
  final _subtarea = TextEditingController();
  final _punto = TextEditingController();
  final _comentario = TextEditingController();

  TareasRepositorio get _repo => ref.read(tareasRepositorioProvider);

  @override
  void initState() {
    super.initState();
    _cargar();
  }

  @override
  void dispose() {
    _subtarea.dispose();
    _punto.dispose();
    _comentario.dispose();
    super.dispose();
  }

  /// Si falla la tarea, falla la pantalla; si falla un apartado (subtareas, adjuntos...), ese apartado queda vacío.
  Future<T> _opcional<T>(Future<T> f, T vacio) => f.catchError((_) => vacio);

  Future<void> _cargar() async {
    setState(() {
      _cargando = true;
      _error = null;
    });
    try {
      final id = widget.tareaId;
      final r = await Future.wait<dynamic>([
        _repo.obtener(id),
        _opcional(_repo.subtareas(id).then((x) => x.subtareas), <Subtarea>[]),
        _opcional(_repo.checklist(id), <ChecklistItem>[]),
        _opcional(_repo.comentarios(id), <ComentarioTarea>[]),
        _opcional(_repo.adjuntos(id), <AdjuntoTarea>[]),
      ]);
      if (!mounted) return;
      setState(() {
        _datos = _Datos(r[0] as TareaOutlook, r[1] as List<Subtarea>, r[2] as List<ChecklistItem>, r[3] as List<ComentarioTarea>, r[4] as List<AdjuntoTarea>);
        _cargando = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e;
        _cargando = false;
      });
    }
  }

  void _aviso(String texto) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(texto)));

  /// Ejecuta una acción del servidor; los errores de negocio (tarea bloqueada, subtareas abiertas...) se enseñan tal cual.
  Future<bool> _intentar(Future<void> Function() accion) async {
    try {
      await accion();
      return true;
    } on ApiException catch (e) {
      if (mounted) _aviso(e.mensaje);
      return false;
    }
  }

  void _publicar(TareaOutlook nueva) {
    setState(() => _datos = _datos!.con(tarea: nueva));
    ref.read(tareasListaProvider.notifier).reemplazar(nueva); // la lista de atrás refleja el cambio
  }

  // --- estado y conflicto ---

  Future<void> _elegirEstado() async {
    final t = AppLocalizations.of(context);
    final actual = EstadoTarea.desde(_datos!.tarea.estado);
    final nuevo = await showModalBottomSheet<EstadoTarea>(
      context: context,
      builder: (_) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          for (final e in EstadoTarea.elegibles)
            ListTile(
              leading: Icon(e == actual ? Icons.radio_button_checked : Icons.radio_button_unchecked),
              title: Text(etiquetaEstado(t, e)),
              onTap: () => Navigator.pop(context, e),
            ),
        ]),
      ),
    );
    if (nuevo == null || nuevo == actual) return;
    String? motivo;
    if (nuevo.pideMotivo) {
      motivo = await _pedirTexto(t.tareaMotivoPregunta, t.tareaMotivoHint);
      if (motivo == null || motivo.isEmpty) return;
    }
    await _transicionar(nuevo, motivo, _datos!.tarea.version);
  }

  Future<void> _transicionar(EstadoTarea nuevo, String? motivo, int? version, {bool esDeshacer = false}) async {
    try {
      final t = AppLocalizations.of(context);
      final base = _datos!.tarea.copyWith(version: version);
      final anterior = EstadoTarea.desde(base.estado);
      final r = await ref.read(accionesTareasProvider).transicionar(base, nuevo, motivo: motivo);
      _publicar(r.valor!);
      if (r.encolada) {
        _aviso(t.colaGuardada);
      } else {
        await _recargarSecundarios();
        if (!mounted) return;
        // «Deshacer» vuelve al estado de antes con la versión de ahora; si pedía motivo (bloqueada) no se ofrece.
        final mensajero = ScaffoldMessenger.of(context);
        mensajero.hideCurrentSnackBar();
        mensajero.showSnackBar(SnackBar(
          content: Text(esDeshacer ? t.tareaDeshechaAviso : t.tareaEstadoCambiadoAviso(etiquetaEstado(t, nuevo))),
          duration: const Duration(seconds: 6),
          action: esDeshacer || anterior.pideMotivo || anterior == EstadoTarea.desconocido
              ? null
              : SnackBarAction(label: t.comunDeshacer, onPressed: () => _transicionar(anterior, null, _datos?.tarea.version, esDeshacer: true)),
        ));
      }
    } on ColaLlena {
      if (mounted) _aviso(AppLocalizations.of(context).colaLlena);
    } on ApiException catch (e) {
      if (e.categoria == CategoriaError.conflicto && e.codigo == 'version_obsoleta') {
        final r = await _preguntarConflicto();
        switch (r) {
          case ResolucionConflicto.aplicar:
            await _transicionar(nuevo, motivo, e.versionActual); // sobrescribir sabiendo la versión que hay ahora
          case ResolucionConflicto.ver:
          case ResolucionConflicto.descartar:
          case null:
            await _cargar();
        }
      } else if (mounted) {
        _aviso(e.mensaje);
      }
    }
  }

  Future<ResolucionConflicto?> _preguntarConflicto() {
    final t = AppLocalizations.of(context);
    return showDialog<ResolucionConflicto>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(t.tareaConflictoTitulo),
        content: Text(t.tareaConflictoCuerpo),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, ResolucionConflicto.descartar), child: Text(t.tareaConflictoDescartar)),
          TextButton(onPressed: () => Navigator.pop(c, ResolucionConflicto.ver), child: Text(t.tareaConflictoVer)),
          FilledButton(onPressed: () => Navigator.pop(c, ResolucionConflicto.aplicar), child: Text(t.tareaConflictoAplicar)),
        ],
      ),
    );
  }

  Future<String?> _pedirTexto(String titulo, String hint, {String inicial = ''}) {
    final t = AppLocalizations.of(context);
    final c = TextEditingController(text: inicial);
    return showDialog<String>(
      context: context,
      builder: (d) => AlertDialog(
        title: Text(titulo),
        content: TextField(controller: c, autofocus: true, decoration: InputDecoration(hintText: hint), maxLines: null),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d), child: Text(t.comunCancelar)),
          FilledButton(onPressed: () => Navigator.pop(d, c.text.trim()), child: Text(t.tareaAceptar)),
        ],
      ),
    );
  }

  Future<void> _recargarSecundarios() async {
    final id = widget.tareaId;
    final sub = await _opcional(_repo.subtareas(id).then((x) => x.subtareas), _datos!.subtareas);
    if (mounted) setState(() => _datos = _datos!.con(subtareas: sub));
  }

  // --- edición ---

  Future<void> _editar() async {
    final yo = ref.read(estadoSesionProvider).usuario?.id;
    final tarea = _datos!.tarea;
    final nueva = await Navigator.of(context).push<TareaOutlook>(
      MaterialPageRoute(builder: (_) => TareaEditorScreen(tarea: tarea, esDueno: yo == null || tarea.usuarioId == null || tarea.usuarioId == yo)),
    );
    if (nueva != null) _publicar(nueva);
  }

  // --- subtareas, comprobación, comentarios ---

  Future<void> _alternarSubtarea(Subtarea s) async {
    final nuevo = s.estado.abierta ? EstadoTarea.completada : EstadoTarea.noIniciada;
    if (await _intentar(() async => _repo.transicionar(s.id, nuevo))) await _recargarSecundarios();
  }

  Future<void> _anadirSubtarea() async {
    final texto = _subtarea.text.trim();
    if (texto.isEmpty) return;
    if (await _intentar(() => _repo.crearSubtarea(widget.tareaId, texto))) {
      _subtarea.clear();
      await _recargarSecundarios();
    }
  }

  Future<void> _alternarPunto(ChecklistItem p) async {
    if (await _intentar(() => _repo.alternarItem(p.id))) {
      final lista = await _opcional(_repo.checklist(widget.tareaId), _datos!.checklist);
      if (mounted) setState(() => _datos = _datos!.con(checklist: lista));
    }
  }

  Future<void> _anadirPunto() async {
    final texto = _punto.text.trim();
    if (texto.isEmpty) return;
    if (await _intentar(() => _repo.agregarItem(widget.tareaId, texto))) {
      _punto.clear();
      final lista = await _opcional(_repo.checklist(widget.tareaId), _datos!.checklist);
      if (mounted) setState(() => _datos = _datos!.con(checklist: lista));
    }
  }

  Future<void> _comentar() async {
    final texto = _comentario.text.trim();
    if (texto.isEmpty) return;
    final t = AppLocalizations.of(context);
    var encolado = false;
    final ok = await _intentar(() async {
      try {
        encolado = await ref.read(accionesTareasProvider).comentar(widget.tareaId, _datos!.tarea.asunto ?? '', texto);
      } on ColaLlena {
        throw ApiException(t.colaLlena);
      }
    });
    if (!ok) return;
    _comentario.clear();
    if (encolado) {
      _aviso(t.colaGuardada);
      // Se enseña ya, marcado como pendiente (id negativo), hasta que la cola lo envíe.
      final provisional = ComentarioTarea.fromJson({'id': -DateTime.now().millisecondsSinceEpoch, 'texto': texto, 'creado_en': DateTime.now().toIso8601String().substring(0, 16)});
      if (mounted) setState(() => _datos = _datos!.con(comentarios: [..._datos!.comentarios, provisional]));
      return;
    }
    final lista = await _opcional(_repo.comentarios(widget.tareaId), _datos!.comentarios);
    if (mounted) setState(() => _datos = _datos!.con(comentarios: lista));
  }

  // --- adjuntos ---

  Future<void> _adjuntar() async {
    final t = AppLocalizations.of(context);
    final origen = await showModalBottomSheet<String>(
      context: context,
      builder: (_) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(leading: const Icon(Icons.photo_camera_outlined), title: Text(t.tareaAdjuntoFoto), onTap: () => Navigator.pop(context, 'camara')),
          ListTile(leading: const Icon(Icons.photo_library_outlined), title: Text(t.tareaAdjuntoGaleria), onTap: () => Navigator.pop(context, 'galeria')),
          ListTile(leading: const Icon(Icons.attach_file), title: Text(t.tareaAdjuntoArchivo), onTap: () => Navigator.pop(context, 'archivo')),
        ]),
      ),
    );
    if (origen == null) return;
    String? ruta, nombre;
    if (origen == 'archivo') {
      final r = await FilePicker.pickFiles();
      final f = r?.files.single;
      ruta = f?.path;
      nombre = f?.name;
    } else {
      final x = await ImagePicker().pickImage(source: origen == 'camara' ? ImageSource.camera : ImageSource.gallery, imageQuality: 85);
      ruta = x?.path;
      nombre = x?.name;
    }
    if (ruta == null || nombre == null) return;
    final archivo = await MultipartFile.fromFile(ruta, filename: nombre);
    if (await _intentar(() => _repo.subirAdjunto(widget.tareaId, archivo))) {
      if (mounted) _aviso(t.tareaAdjuntoSubido);
      final lista = await _opcional(_repo.adjuntos(widget.tareaId), _datos!.adjuntos);
      if (mounted) setState(() => _datos = _datos!.con(adjuntos: lista));
    }
  }

  Future<void> _abrirAdjunto(AdjuntoTarea a) async {
    final t = AppLocalizations.of(context);
    try {
      final bytes = await _repo.descargarAdjunto(a.id!);
      final dir = await getTemporaryDirectory();
      final f = File('${dir.path}/${a.nombreArchivo ?? 'adjunto'}');
      await f.writeAsBytes(bytes);
      await OpenFilex.open(f.path);
    } catch (_) {
      if (mounted) _aviso(t.tareaNoSePudoAbrir);
    }
  }

  Future<void> _quitarAdjunto(AdjuntoTarea a) async {
    if (await _intentar(() => _repo.eliminarAdjunto(a.id!))) {
      final lista = await _opcional(_repo.adjuntos(widget.tareaId), _datos!.adjuntos);
      if (mounted) setState(() => _datos = _datos!.con(adjuntos: lista));
    }
  }

  // --- interfaz ---

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final d = _datos;
    return Scaffold(
      appBar: AppBar(
        title: Text(t.tareaDetalleTitulo),
        actions: [
          if (d != null) AccionAsistente(contexto: t.tareaDetalleTitulo, contextoIa: 'tarea #${d.tarea.id} «${d.tarea.asunto}»'),
          if (d != null) IconButton(icon: const Icon(Icons.edit_outlined), tooltip: t.tareaEditar, onPressed: _editar),
        ],
      ),
      body: Column(children: [
        const AvisoDatosGuardados(prefijo: '/tareas-outlook'),
        Expanded(
          child: d == null
              ? (_cargando ? const EsqueletoLista(filas: 5) : EstadoError(error: _error ?? Object(), alReintentar: _cargar))
              : RefreshIndicator(onRefresh: _cargar, child: _contenido(context, d)),
        ),
      ]),
    );
  }

  Widget _contenido(BuildContext context, _Datos d) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final tarea = d.tarea;
    final estado = EstadoTarea.desde(tarea.estado);
    final fecha = Fecha.intentar(tarea.fechaVencimiento);
    final vencida = tarea.vencida == true && estado.abierta;
    final hechas = d.subtareas.where((s) => !s.estado.abierta).length;

    final yo = ref.read(estadoSesionProvider).usuario?.id;
    final esDueno = tarea.usuarioId == null || tarea.usuarioId == yo;
    final colorVencida = aspectoVencida.color(tema.brightness);

    return ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 32), children: [
      Text(tarea.asunto ?? '', style: tema.textTheme.headlineSmall),
      const SizedBox(height: 12),
      // Lo esencial de un vistazo: estado (se toca para cambiarlo), prioridad y vencimiento, y debajo lo que cuelga de la tarea.
      Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
        Pildora(icono: aspectoDe(estado).icono, texto: '${t.tareaEstado}: ${etiquetaEstado(t, estado)}', color: aspectoDe(estado).color(tema.brightness), fuerte: true, alPulsar: _elegirEstado),
        Pildora(icono: Icons.flag_outlined, texto: '${t.tareaPrioridad}: ${etiquetaPrioridad(t, PrioridadTarea.desde(tarea.prioridad))}', color: PrioridadTarea.desde(tarea.prioridad) == PrioridadTarea.alta ? (tema.brightness == Brightness.dark ? BrandColors.warningTextDark : BrandColors.warningTextLight) : null),
        Pildora(
          icono: Icons.event_outlined,
          texto: fecha == null ? t.tareaSinFecha : '${t.tareaVence}: ${context.formatos.fecha(fecha)}${vencida ? ' · ${t.tareasVencida}' : ''}',
          color: vencida ? colorVencida : null,
          fuerte: vencida,
        ),
      ]),
      const SizedBox(height: 8),
      _Contexto(tarea: tarea),
      if (estado == EstadoTarea.esperando && (tarea.motivoBloqueo ?? '').isNotEmpty)
        BloqueFicha(titulo: t.tareaMotivoBloqueo, hijo: Text(tarea.motivoBloqueo!)),
      if ((tarea.cuerpo ?? '').isNotEmpty) BloqueFicha(titulo: t.tareaNotas, hijo: Text(tarea.cuerpo!)),
      BloqueFicha(
        hijo: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          BloqueEspera(tareaId: tarea.id, puedeEditar: true, alCambiar: _cargar),
          const Divider(height: 20),
          BloqueCompartida(tareaId: tarea.id, esDueno: esDueno, miId: yo),
        ]),
      ),
      BloqueFicha(
        titulo: d.subtareas.isEmpty ? t.tareaSubtareas : '${t.tareaSubtareas} · $hechas/${d.subtareas.length}',
        hijo: Column(children: [
          for (final s in d.subtareas)
            CheckboxListTile(
              dense: true,
              controlAffinity: ListTileControlAffinity.leading,
              contentPadding: EdgeInsets.zero,
              value: !s.estado.abierta,
              title: Text(s.asunto, style: s.estado.abierta ? null : const TextStyle(decoration: TextDecoration.lineThrough)),
              onChanged: (_) => _alternarSubtarea(s),
            ),
          _Entrada(controlador: _subtarea, hint: t.tareaSubtareaNueva, alEnviar: _anadirSubtarea),
        ]),
      ),
      BloqueFicha(
        titulo: t.tareaChecklist,
        hijo: Column(children: [
          for (final p in d.checklist)
            CheckboxListTile(
              dense: true,
              controlAffinity: ListTileControlAffinity.leading,
              contentPadding: EdgeInsets.zero,
              value: p.hecha == 1,
              title: Text(p.texto ?? '', style: p.hecha == 1 ? const TextStyle(decoration: TextDecoration.lineThrough) : null),
              onChanged: (_) => _alternarPunto(p),
            ),
          _Entrada(controlador: _punto, hint: t.tareaChecklistNuevo, alEnviar: _anadirPunto),
        ]),
      ),
      BloqueFicha(
        titulo: t.tareaAdjuntos,
        hijo: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final a in d.adjuntos)
            ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.attach_file),
              title: Text(a.nombreArchivo ?? '', maxLines: 1, overflow: TextOverflow.ellipsis),
              subtitle: a.tamanoBytes == null ? null : Text(_tamano(a.tamanoBytes!)),
              trailing: IconButton(icon: const Icon(Icons.delete_outline), tooltip: t.tareaEliminar, onPressed: () => _quitarAdjunto(a)),
              onTap: () => _abrirAdjunto(a),
            ),
          TextButton.icon(onPressed: _adjuntar, icon: const Icon(Icons.add), label: Text(t.tareaAdjuntar)),
        ]),
      ),
      BloqueFicha(hijo: BloqueRevision(tarea: tarea, miId: yo, esDueno: esDueno, alCambiar: _cargar)),
      BloqueFicha(hijo: BloqueTiempo(tarea: tarea, alCambiar: null)),
      BloqueFicha(hijo: BloqueRecordatorios(tarea: tarea)),
      BloqueFicha(
        titulo: t.tareaComentarios,
        hijo: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final c in d.comentarios)
            ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              leading: Icon(c.id < 0 ? Icons.cloud_upload_outlined : Icons.chat_bubble_outline, size: 20),
              title: Text(c.texto ?? ''),
              subtitle: Text(_cuando(c.creadoEn)),
            ),
          _Entrada(controlador: _comentario, hint: t.tareaComentarioNuevo, alEnviar: _comentar),
        ]),
      ),
      BloqueFicha(hijo: BloqueClienteConversacion(tarea: tarea)),
      BloqueFicha(hijo: BloqueActividad(tareaId: tarea.id)),
    ]);
  }

  String _tamano(int bytes) => bytes < 1024 * 1024 ? '${(bytes / 1024).ceil()} KB' : '${(bytes / 1024 / 1024).toStringAsFixed(1)} MB';

  String _cuando(String? iso) {
    final m = MomentoLocal.intentar(iso);
    return m == null ? '' : context.formatos.momento(m);
  }
}

/// Lo que cuelga de la tarea y la web enseña en su cabecera: quién la tiene, el cliente, el proyecto y cuánto se calcula que lleva.
class _Contexto extends ConsumerWidget {
  final TareaOutlook tarea;
  const _Contexto({required this.tarea});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final companeros = ref.watch(companerosProvider).value ?? const <Companero>[];
    final persona = tarea.asignadaA == null ? null : companeros.where((c) => c.id == tarea.asignadaA).firstOrNull;
    final principal = (tarea.clientes ?? const <ClienteDeTarea>[]).where((c) => c.principal == true).firstOrNull;
    final otros = (tarea.clientes ?? const <ClienteDeTarea>[]).length - (principal == null ? 0 : 1);
    final chips = <Widget>[
      if ((tarea.categoriaNombre ?? '').isNotEmpty) Pildora(icono: Icons.folder_outlined, texto: tarea.categoriaNombre!),
      if (principal != null) Pildora(icono: Icons.business_outlined, texto: otros > 0 ? '${principal.nombre ?? ''} +$otros' : (principal.nombre ?? '')),
      if (persona != null) Pildora(icono: Icons.person_outline, texto: t.tareaAsignadaA(persona.nombre ?? persona.email ?? '')),
      if (tarea.estimacionMin != null) Pildora(icono: Icons.timer_outlined, texto: t.tareaEstimadaEn(duracionCorta(tarea.estimacionMin!))),
      if ((tarea.categoriaOutlook ?? '').isNotEmpty) Pildora(icono: Icons.label_outline, texto: tarea.categoriaOutlook!),
    ];
    return chips.isEmpty ? const SizedBox.shrink() : Wrap(spacing: 8, runSpacing: 8, children: chips);
  }
}

class _Entrada extends StatelessWidget {
  final TextEditingController controlador;
  final String hint;
  final VoidCallback alEnviar;
  const _Entrada({required this.controlador, required this.hint, required this.alEnviar});

  @override
  Widget build(BuildContext context) => Row(children: [
        Expanded(
          child: TextField(controller: controlador, textInputAction: TextInputAction.send, decoration: InputDecoration(hintText: hint, isDense: true), onSubmitted: (_) => alEnviar()),
        ),
        IconButton(icon: const Icon(Icons.send), tooltip: hint, onPressed: alEnviar),
      ]);
}
