import 'dart:io';

import 'package:dio/dio.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';

import '../../api/errores.dart';
import '../../api/generado/modelos.g.dart';
import '../../diseno/componentes.dart';
import '../../diseno/formatos.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/abrir_destino.dart';
import '../../nucleo/destinos.dart';
import '../../nucleo/sesion.dart';
import '../tareas/tareas_repositorio.dart' show companerosProvider;
import 'notas_acciones.dart';
import 'notas_lista_controlador.dart';
import 'notas_repositorio.dart';
import 'texto_nota.dart';

/// Una nota: se lee con su formato y, con permiso, se edita. Con `notaId` null es una nota nueva (empieza editando). Su dueño la fija, la vincula, la comparte,
/// le adjunta archivos y la borra; quien la tiene compartida como «colabora» edita texto y título; con «observa» solo la lee.
class NotaScreen extends ConsumerStatefulWidget {
  final int? notaId;
  const NotaScreen({super.key, this.notaId});

  @override
  ConsumerState<NotaScreen> createState() => _NotaScreenState();
}

class _NotaScreenState extends ConsumerState<NotaScreen> {
  final _titulo = TextEditingController();
  final _texto = TextEditingController();
  final _focoTexto = FocusNode();
  Nota? _nota;
  List<AdjuntoNota> _adjuntos = const [];
  Object? _error;
  bool _cargando = false;
  bool _editando = false;
  bool _guardando = false;

  NotasRepositorio get _repo => ref.read(notasRepositorioProvider);
  bool get _nueva => widget.notaId == null;
  NotaRol get _rol => _nueva ? NotaRol.dueno : (_nota?.rol ?? NotaRol.dueno);
  bool get _esDueno => _rol == NotaRol.dueno;
  bool get _puedeEditar => _rol == NotaRol.dueno || _rol == NotaRol.colabora;
  bool get _sinGuardar => _editando && (_titulo.text != (_nota?.titulo ?? '') || _texto.text != (_nota?.texto ?? ''));

  @override
  void initState() {
    super.initState();
    _titulo.addListener(_cambio);
    _texto.addListener(_cambio);
    if (_nueva) {
      _editando = true;
    } else {
      _cargar();
    }
  }

  void _cambio() => setState(() {}); // el botón de guardar y el aviso de descartar dependen de lo escrito

  @override
  void dispose() {
    _titulo.dispose();
    _texto.dispose();
    _focoTexto.dispose();
    super.dispose();
  }

  void _aviso(String texto) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(texto)));

  Future<void> _cargar() async {
    setState(() {
      _cargando = true;
      _error = null;
    });
    try {
      final n = await _repo.obtener(widget.notaId!);
      var adjuntos = const <AdjuntoNota>[];
      if (n.rol == NotaRol.dueno) {
        try {
          adjuntos = await _repo.adjuntos(n.id);
        } catch (_) {
          // un apartado que falla queda vacío: la nota se lee igual
        }
      }
      if (!mounted) return;
      setState(() {
        _nota = n;
        _adjuntos = adjuntos;
        _titulo.text = n.titulo ?? '';
        _texto.text = n.texto ?? '';
        _cargando = false;
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e;
          _cargando = false;
        });
      }
    }
  }

  Future<void> _guardar() async {
    final t = AppLocalizations.of(context);
    final texto = _texto.text.trim(), titulo = _titulo.text.trim();
    if (texto.isEmpty && titulo.isEmpty) return;
    setState(() => _guardando = true);
    final lista = ref.read(notasListaProvider.notifier);
    try {
      if (_nueva) {
        final creada = await ref.read(accionesNotasProvider).crearNota(texto, titulo: titulo);
        if (!mounted) return;
        if (creada.encolada) {
          _aviso(t.notasGuardadaSinConexion);
          Navigator.of(context).pop();
          return;
        }
        lista.recargar();
        _aviso(t.notasGuardada);
        Navigator.of(context).pop();
        return;
      }
      await _repo.editar(_nota!.id, texto: texto, titulo: titulo);
      if (!mounted) return;
      _aviso(t.notasGuardada);
      _editando = false;
      await _cargar();
      if (_nota != null) lista.reemplazar(_nota!);
    } on ApiException catch (e) {
      if (mounted) _aviso(e.mensaje);
    } finally {
      if (mounted) setState(() => _guardando = false);
    }
  }

  Future<bool> _confirmarDescartar() async {
    final t = AppLocalizations.of(context);
    final r = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(t.notasDescartarTitulo),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: Text(t.notasSeguirEditando)),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(t.notasDescartar)),
        ],
      ),
    );
    return r == true;
  }

  Future<void> _cancelarEdicion() async {
    if (_sinGuardar && !await _confirmarDescartar()) return;
    if (!mounted) return;
    if (_nueva) {
      Navigator.of(context).pop();
    } else {
      setState(() {
        _editando = false;
        _titulo.text = _nota?.titulo ?? '';
        _texto.text = _nota?.texto ?? '';
      });
    }
  }

  // --- formato ---

  void _envolver(String marca) {
    final s = _texto.selection;
    final texto = _texto.text;
    if (!s.isValid) {
      _texto.text = '$texto$marca$marca';
      _texto.selection = TextSelection.collapsed(offset: texto.length + marca.length);
    } else if (s.isCollapsed) {
      _texto.value = TextEditingValue(text: texto.replaceRange(s.start, s.end, '$marca$marca'), selection: TextSelection.collapsed(offset: s.start + marca.length));
    } else {
      final dentro = texto.substring(s.start, s.end);
      _texto.value = TextEditingValue(text: texto.replaceRange(s.start, s.end, '$marca$dentro$marca'), selection: TextSelection(baseOffset: s.start + marca.length, extentOffset: s.end + marca.length));
    }
    _focoTexto.requestFocus();
  }

  void _lista() {
    final texto = _texto.text;
    final s = _texto.selection.isValid ? _texto.selection : TextSelection.collapsed(offset: texto.length);
    final inicio = texto.lastIndexOf('\n', s.start > 0 ? s.start - 1 : 0) + 1;
    final final_ = s.end;
    final lineas = texto.substring(inicio, final_).split('\n');
    final nuevo = lineas.map((l) => l.startsWith('- ') ? l : '- $l').join('\n');
    _texto.value = TextEditingValue(text: texto.replaceRange(inicio, final_, nuevo), selection: TextSelection.collapsed(offset: inicio + nuevo.length));
    _focoTexto.requestFocus();
  }

  Future<void> _enlace() async {
    final t = AppLocalizations.of(context);
    final c = TextEditingController(text: 'https://');
    final url = await showDialog<String>(
      context: context,
      builder: (d) => AlertDialog(
        title: Text(t.notasEnlace),
        content: TextField(controller: c, autofocus: true, keyboardType: TextInputType.url, decoration: InputDecoration(hintText: t.notasEnlaceDireccion)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d), child: Text(t.comunCancelar)),
          FilledButton(onPressed: () => Navigator.pop(d, c.text.trim()), child: Text(t.tareaAceptar)),
        ],
      ),
    );
    c.dispose();
    if (url == null || !RegExp(r'^https?://\S+$').hasMatch(url)) return;
    final s = _texto.selection;
    final texto = _texto.text;
    final inicio = s.isValid ? s.start : texto.length, fin = s.isValid ? s.end : texto.length;
    final etiqueta = inicio == fin ? url : texto.substring(inicio, fin);
    final md = '[$etiqueta]($url)';
    _texto.value = TextEditingValue(text: texto.replaceRange(inicio, fin, md), selection: TextSelection.collapsed(offset: inicio + md.length));
    _focoTexto.requestFocus();
  }

  // --- acciones del dueño ---

  Future<void> _fijar() async {
    try {
      final n = await _repo.fijar(_nota!.id, _nota!.fijada != 1);
      ref.read(notasListaProvider.notifier).reemplazar(n);
      await _cargar();
    } on ApiException catch (e) {
      if (mounted) _aviso(e.mensaje);
    }
  }

  Future<void> _eliminar() async {
    if (await eliminarNotaConDeshacer(context, ref, _nota!) && mounted) Navigator.of(context).pop();
  }

  Future<void> _compartir() async {
    final t = AppLocalizations.of(context);
    final yo = ref.read(estadoSesionProvider).usuario?.id;
    final ya = {for (final p in _nota?.participantes ?? const <ParticipanteNota>[]) p.usuarioId};
    final todos = await ref.read(companerosProvider.future).catchError((_) => const <Companero>[]);
    final candidatos = [for (final c in todos) if (c.id != null && c.id != yo && !ya.contains(c.id)) c];
    if (!mounted) return;
    final elegido = await showModalBottomSheet<Companero>(
      context: context,
      showDragHandle: true,
      builder: (_) => SafeArea(
        child: ListView(shrinkWrap: true, children: [
          ListTile(title: Text(t.tareaCompartirAnadir, style: Theme.of(context).textTheme.titleMedium)),
          if (candidatos.isEmpty) ListTile(title: Text(t.tareaCompartirVacio)),
          for (final c in candidatos) ListTile(leading: const Icon(Icons.person_outline), title: Text(c.nombre ?? c.email ?? ''), onTap: () => Navigator.pop(context, c)),
        ]),
      ),
    );
    if (elegido == null || !mounted) return;
    final rol = await showDialog<String>(
      context: context,
      builder: (d) => SimpleDialog(title: Text(t.notasElegirRol), children: [
        SimpleDialogOption(onPressed: () => Navigator.pop(d, 'colabora'), child: Text(t.notasRolColabora)),
        SimpleDialogOption(onPressed: () => Navigator.pop(d, 'observa'), child: Text(t.notasRolObserva)),
      ]),
    );
    if (rol == null) return;
    try {
      await _repo.compartir(_nota!.id, elegido.id!, rol);
      await _cargar();
      if (_nota != null) ref.read(notasListaProvider.notifier).reemplazar(_nota!);
    } on ApiException catch (e) {
      if (mounted) _aviso(e.mensaje);
    }
  }

  Future<void> _dejarDeCompartir(ParticipanteNota p) async {
    try {
      await _repo.dejarDeCompartir(_nota!.id, p.usuarioId!);
      await _cargar();
      if (_nota != null) ref.read(notasListaProvider.notifier).reemplazar(_nota!);
    } on ApiException catch (e) {
      if (mounted) _aviso(e.mensaje);
    }
  }

  Future<void> _salir() async {
    final t = AppLocalizations.of(context);
    final yo = ref.read(estadoSesionProvider).usuario?.id;
    if (yo == null) return;
    final sigue = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        content: Text(t.notasSalirPregunta),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: Text(t.comunCancelar)),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(t.notasSalir)),
        ],
      ),
    );
    if (sigue != true) return;
    try {
      await _repo.dejarDeCompartir(_nota!.id, yo);
      ref.read(notasListaProvider.notifier).quitar(_nota!.id);
      if (mounted) Navigator.of(context).pop();
    } on ApiException catch (e) {
      if (mounted) _aviso(e.mensaje);
    }
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
    try {
      await _repo.subirAdjunto(_nota!.id, await MultipartFile.fromFile(ruta, filename: nombre));
      if (!mounted) return;
      _aviso(t.tareaAdjuntoSubido);
      final lista = await _repo.adjuntos(_nota!.id);
      if (mounted) setState(() => _adjuntos = lista);
    } on ApiException catch (e) {
      if (mounted) _aviso(e.mensaje);
    }
  }

  Future<void> _abrirAdjunto(AdjuntoNota a) async {
    final t = AppLocalizations.of(context);
    try {
      final bytes = await _repo.descargarAdjunto(a.id);
      final dir = await getTemporaryDirectory();
      final f = File('${dir.path}/${a.nombre ?? 'adjunto'}');
      await f.writeAsBytes(bytes);
      await OpenFilex.open(f.path);
    } catch (_) {
      if (mounted) _aviso(t.tareaNoSePudoAbrir);
    }
  }

  Future<void> _quitarAdjunto(AdjuntoNota a) async {
    try {
      await _repo.eliminarAdjunto(a.id);
      final lista = await _repo.adjuntos(_nota!.id);
      if (mounted) setState(() => _adjuntos = lista);
    } on ApiException catch (e) {
      if (mounted) _aviso(e.mensaje);
    }
  }

  // --- interfaz ---

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return PopScope(
      canPop: !_sinGuardar,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        if (await _confirmarDescartar() && context.mounted) Navigator.of(context).pop();
      },
      child: Scaffold(
        appBar: _editando ? _barraEdicion(t) : _barraLectura(t),
        body: _cuerpo(t),
      ),
    );
  }

  AppBar _barraEdicion(AppLocalizations t) => AppBar(
        leading: IconButton(icon: const Icon(Icons.close), tooltip: t.comunCancelar, onPressed: _guardando ? null : _cancelarEdicion),
        title: Text(_nueva ? t.notasNueva : t.notasEditar),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: FilledButton(
              onPressed: _guardando || (_texto.text.trim().isEmpty && _titulo.text.trim().isEmpty) ? null : _guardar,
              child: _guardando ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : Text(t.notasGuardar),
            ),
          ),
        ],
      );

  AppBar _barraLectura(AppLocalizations t) => AppBar(
        title: Text(t.notasTitulo),
        actions: [
          if (_nota != null && _puedeEditar) IconButton(icon: const Icon(Icons.edit_outlined), tooltip: t.notasEditar, onPressed: () => setState(() => _editando = true)),
          if (_nota != null && _esDueno)
            PopupMenuButton<String>(
              onSelected: (v) => v == 'fijar' ? _fijar() : _eliminar(),
              itemBuilder: (_) => [
                PopupMenuItem(value: 'fijar', child: Text(_nota!.fijada == 1 ? t.notasDesfijar : t.notasFijar)),
                PopupMenuItem(value: 'eliminar', child: Text(t.notasEliminar)),
              ],
            ),
        ],
      );

  Widget _cuerpo(AppLocalizations t) {
    if (_editando) return _editor(t);
    if (_cargando && _nota == null) return const EsqueletoLista(filas: 4);
    if (_error != null && _nota == null) return EstadoError(error: _error!, alReintentar: _cargar);
    final n = _nota;
    if (n == null) return const SizedBox.shrink();
    final tema = Theme.of(context);
    final fecha = context.formatos.deServidor(n.creadaEn);
    final titulo = (n.titulo ?? '').trim();
    final sinTexto = (n.texto ?? '').trim().isEmpty;
    return RefreshIndicator(
      onRefresh: _cargar,
      child: ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 32), children: [
        if (titulo.isNotEmpty) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(titulo, style: tema.textTheme.headlineSmall)),
        Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
          if (n.fijada == 1) Pildora(icono: Icons.push_pin_outlined, texto: t.notasFijada),
          if ((n.categoriaNombre ?? '').isNotEmpty) Pildora(icono: Icons.folder_outlined, texto: n.categoriaNombre!),
          if (!_esDueno) Pildora(icono: Icons.person_outline, texto: t.notasCompartidaPor(n.duenoNombre ?? '')),
          if (_rol == NotaRol.observa) Pildora(icono: Icons.lock_outline, texto: t.notasRolObserva),
          if (fecha != null) Pildora(icono: Icons.event_outlined, texto: fecha),
        ]),
        const SizedBox(height: 16),
        if (sinTexto) Text(t.notasVacia, style: tema.textTheme.bodyMedium?.copyWith(color: tema.colorScheme.onSurfaceVariant)) else TextoNota(n.texto ?? ''),
        const SizedBox(height: 8),
        ..._bloques(t, n),
      ]),
    );
  }

  List<Widget> _bloques(AppLocalizations t, Nota n) {
    final destino = ref.read(navegadorDeAvisosProvider);
    final vinculos = [
      if (n.clienteFiscalId != null && (n.clienteFiscalNombre ?? '').isNotEmpty) (Icons.business_outlined, n.clienteFiscalNombre!, t.busquedaTipoCliente, null as Destino?),
      if (n.tareaOutlookId != null && (n.tareaOutlookAsunto ?? '').isNotEmpty) (Icons.checklist, n.tareaOutlookAsunto!, t.busquedaTipoTarea, Destino('tarea', n.tareaOutlookId)),
      if (n.mensajeCorreoId != null && (n.mensajeCorreoAsunto ?? '').isNotEmpty) (Icons.mail_outline, n.mensajeCorreoAsunto!, t.busquedaTipoCorreo, Destino('correo', n.mensajeCorreoId)),
    ];
    final participantes = n.participantes ?? const <ParticipanteNota>[];
    return [
      if (vinculos.isNotEmpty)
        BloqueFicha(
          titulo: t.notasVinculos,
          hijo: Column(children: [
            for (final v in vinculos)
              ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: Icon(v.$1),
                title: Text(v.$2, maxLines: 2, overflow: TextOverflow.ellipsis),
                subtitle: Text(v.$3),
                trailing: v.$4 == null ? null : const Icon(Icons.chevron_right),
                onTap: v.$4 == null ? null : () => destino.abrir(v.$4!),
              ),
          ]),
        ),
      BloqueFicha(
        titulo: t.tareaCompartidaCon,
        hijo: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (participantes.isEmpty) Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: Text(t.tareaCompartirVacio)),
          for (final p in participantes)
            ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.person_outline),
              title: Text(p.nombre ?? ''),
              subtitle: Text(p.rol == ParticipanteNotaRol.colabora ? t.notasRolColabora : t.notasRolObserva),
              trailing: _esDueno ? IconButton(icon: const Icon(Icons.close), tooltip: t.notasDejarDeCompartir, onPressed: () => _dejarDeCompartir(p)) : null,
            ),
          if (_esDueno) TextButton.icon(onPressed: _compartir, icon: const Icon(Icons.person_add_alt_1_outlined), label: Text(t.tareaCompartirAnadir)),
          if (!_esDueno) TextButton.icon(onPressed: _salir, icon: const Icon(Icons.logout), label: Text(t.notasSalir)),
        ]),
      ),
      if (_esDueno)
        BloqueFicha(
          titulo: t.tareaAdjuntos,
          hijo: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final a in _adjuntos)
              ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.attach_file),
                title: Text(a.nombre ?? '', maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: a.tamano == null ? null : Text(_tamano(a.tamano!)),
                trailing: IconButton(icon: const Icon(Icons.delete_outline), tooltip: t.tareaEliminar, onPressed: () => _quitarAdjunto(a)),
                onTap: () => _abrirAdjunto(a),
              ),
            TextButton.icon(onPressed: _adjuntar, icon: const Icon(Icons.add), label: Text(t.tareaAdjuntar)),
          ]),
        ),
    ];
  }

  static String _tamano(int bytes) => bytes < 1024 * 1024 ? '${(bytes / 1024).ceil()} KB' : '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';

  Widget _editor(AppLocalizations t) {
    final tema = Theme.of(context);
    Widget herramienta(IconData icono, String tip, VoidCallback alPulsar) => IconButton(icon: Icon(icono), tooltip: tip, onPressed: alPulsar);
    return Column(children: [
      Expanded(
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 16), children: [
          TextField(
            controller: _titulo,
            style: tema.textTheme.titleLarge,
            textCapitalization: TextCapitalization.sentences,
            decoration: InputDecoration(hintText: t.notasTituloHint, border: InputBorder.none, filled: false),
            maxLength: 120,
            buildCounter: (_, {required currentLength, required isFocused, maxLength}) => null,
          ),
          TextField(
            controller: _texto,
            focusNode: _focoTexto,
            autofocus: _nueva,
            minLines: 10,
            maxLines: null,
            keyboardType: TextInputType.multiline,
            textCapitalization: TextCapitalization.sentences,
            decoration: InputDecoration(hintText: t.notasTextoHint, border: InputBorder.none, filled: false),
          ),
        ]),
      ),
      // La barra de formato va pegada al teclado.
      Material(
        color: tema.colorScheme.surface,
        child: SafeArea(
          top: false,
          child: DecoratedBox(
            decoration: BoxDecoration(border: Border(top: BorderSide(color: tema.colorScheme.outlineVariant))),
            child: Row(children: [
              herramienta(Icons.format_bold, t.notasNegrita, () => _envolver('**')),
              herramienta(Icons.format_italic, t.notasCursiva, () => _envolver('*')),
              herramienta(Icons.format_list_bulleted, t.notasLista, _lista),
              herramienta(Icons.link, t.notasEnlace, _enlace),
            ]),
          ),
        ),
      ),
    ]);
  }
}
