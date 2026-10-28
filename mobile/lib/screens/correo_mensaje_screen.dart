import 'dart:io';

import '../../diseno/adaptable.dart';
import 'package:flutter/material.dart';

import '../diseno/asistente.dart';

import '../nucleo/abrir_asistente.dart';

import '../diseno/componentes.dart';
import '../diseno/formatos.dart';

import '../l10n/app_localizations.dart';
import 'package:flutter_widget_from_html/flutter_widget_from_html.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';

import '../models/models.dart';
import '../services/api_client.dart';
import 'correo_compose_screen.dart';

/// Sustituye el `src` de `<img src="http(s)://...">` remotos por un
/// marcador inerte, igual que `correo.html_con_imagenes_bloqueadas` en el
/// backend — evita que HtmlWidget dispare peticiones de red (tracking
/// pixels) antes de que el usuario decida mostrarlas o confiar en el
/// remitente. Devuelve (html, hubo_bloqueo).
(String, bool) _htmlConImagenesBloqueadas(String? html) {
  if (html == null || html.isEmpty) return (html ?? '', false);
  final patron = RegExp(r'''(<img\b[^>]*\bsrc=["'])(https?://[^"']+)(["'])''', caseSensitive: false);
  var hubo = false;
  final resultado = html.replaceAllMapped(patron, (m) {
    hubo = true;
    return '${m.group(1)}data:,${m.group(3)}';
  });
  return (resultado, hubo);
}

/// Extrae la dirección "pelada" de un remitente tipo `Nombre <correo@x.com>`,
/// igual que `correo.direccion_email` en el backend.
String? _direccionEmail(String? texto) {
  if (texto == null || texto.trim().isEmpty) return null;
  var t = texto.trim();
  if (t.contains('<') && t.contains('>')) {
    t = t.split('<')[1].split('>')[0];
  }
  return t.trim().toLowerCase();
}

/// Detalle de un mensaje (equivalente móvil de la parte "reading pane" de
/// app/templates/correo_bandeja.html): cuerpo (HTML real vía
/// flutter_widget_from_html, con imágenes remotas bloqueadas por defecto
/// salvo remitente de confianza), adjuntos (descargables y abribles, Fase
/// 5a) y acciones básicas.
class CorreoMensajeScreen extends StatefulWidget {
  final ApiClient api;
  final int mensajeId;
  final List<Carpeta> carpetas;

  /// Si el mensaje va en el panel de la derecha (tableta), eliminarlo no cierra una pantalla: avisa a la bandeja para que vuelva a la vista vacía.
  final VoidCallback? alTerminar;

  const CorreoMensajeScreen({
    super.key,
    required this.api,
    required this.mensajeId,
    required this.carpetas,
    this.alTerminar,
  });

  @override
  State<CorreoMensajeScreen> createState() => _CorreoMensajeScreenState();
}

class _CorreoMensajeScreenState extends State<CorreoMensajeScreen> {
  late Future<Mensaje> _mensaje;
  List<CategoriaCorreo> _categorias = [];
  String? _error;
  bool _mostrarImagenes = false;
  int? _descargandoAdjuntoId;

  @override
  void initState() {
    super.initState();
    _mensaje = _cargar();
  }

  Future<Mensaje> _cargar() async {
    final resultados = await Future.wait([
      widget.api.obtenerMensaje(widget.mensajeId),
      widget.api.listarCategoriasCorreo(),
    ]);
    setState(() {
      _categorias = resultados[1] as List<CategoriaCorreo>;
    });
    return resultados[0] as Mensaje;
  }

  Future<void> _recargar() async {
    final futuro = _cargar();
    setState(() {
      _mensaje = futuro;
      _mostrarImagenes = false;
    });
    await futuro;
  }

  Future<void> _accion(Future<void> Function() llamada) async {
    try {
      await llamada();
      await _recargar();
    } catch (e) {
      if (mounted) setState(() => _error = mensajeDeError(AppLocalizations.of(context), e));
    }
  }

  Future<void> _confiarEnRemitente(String? remitente) async {
    final direccion = _direccionEmail(remitente);
    if (direccion == null) return;
    await _accion(() => widget.api.confiarEnRemitente(direccion));
  }

  Future<void> _eliminar() async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(AppLocalizations.of(context).correoEliminarTitulo),
        content: Text(AppLocalizations.of(context).correoEliminarCuerpo),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(AppLocalizations.of(context).comunCancelar)),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(AppLocalizations.of(context).comunEliminar)),
        ],
      ),
    );
    if (confirmar != true) return;
    try {
      await widget.api.eliminarMensaje(widget.mensajeId);
      if (!mounted) return;
      final alTerminar = widget.alTerminar;
      if (alTerminar != null) {
        alTerminar();
      } else {
        Navigator.of(context).pop();
      }
    } catch (e) {
      if (mounted) setState(() => _error = mensajeDeError(AppLocalizations.of(context), e));
    }
  }

  String _tamanoLegible(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }

  String _sinPrefijo(String asunto, String prefijo) {
    return asunto.toLowerCase().startsWith(prefijo.toLowerCase())
        ? asunto
        : '$prefijo $asunto';
  }

  void _responder(Mensaje m) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => CorreoComposeScreen(
          api: widget.api,
          cuentaIdInicial: m.cuentaId,
          destinatariosIniciales: m.remitente,
          asuntoInicial: _sinPrefijo(m.asunto, 'Re:'),
          cuerpoInicial:
              '<br><br><blockquote>${m.cuerpoHtml ?? m.cuerpoTexto ?? ''}</blockquote>',
          enRespuestaA: m.messageId,
        ),
      ),
    );
  }

  void _reenviar(Mensaje m) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => CorreoComposeScreen(
          api: widget.api,
          cuentaIdInicial: m.cuentaId,
          asuntoInicial: _sinPrefijo(m.asunto, 'Fwd:'),
          cuerpoInicial:
              '<br><br><blockquote>${m.cuerpoHtml ?? m.cuerpoTexto ?? ''}</blockquote>',
        ),
      ),
    );
  }

  Future<void> _abrirAdjunto(Mensaje m, Adjunto a) async {
    if (!m.remitenteConfiable) {
      final confirmar = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text(AppLocalizations.of(context).correoNoConfiableTitulo),
          content: Text(AppLocalizations.of(context).correoNoConfiableCuerpo(m.remitente, a.nombreArchivo)),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: Text(AppLocalizations.of(context).comunCancelar)),
            FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(AppLocalizations.of(context).comunAbrir)),
          ],
        ),
      );
      if (confirmar != true) return;
    }
    setState(() => _descargandoAdjuntoId = a.id);
    try {
      final bytes = await widget.api.descargarAdjunto(m.id, a.id);
      final dir = await getTemporaryDirectory();
      final archivo = File('${dir.path}/${a.nombreArchivo}');
      await archivo.writeAsBytes(bytes);
      await OpenFilex.open(archivo.path);
    } catch (e) {
      if (mounted) if (mounted) setState(() => _error = mensajeDeError(AppLocalizations.of(context), e));
    } finally {
      if (mounted) setState(() => _descargandoAdjuntoId = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(AppLocalizations.of(context).comunMensaje),
        actions: [
          AccionAsistente(contexto: AppLocalizations.of(context).comunMensaje, contextoIa: 'correo, mensaje #${widget.mensajeId}'),
          IconButton(icon: Icon(Icons.delete_outline), tooltip: AppLocalizations.of(context).comunEliminar, onPressed: _eliminar),
        ],
      ),
      // Atajos del asistente sobre este correo (en la tableta, el panel de al lado ya los ofrece).
      bottomNavigationBar: widget.alTerminar != null
          ? null
          : SafeArea(
              child: SizedBox(
                height: 56,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  children: [
                    for (final texto in [AppLocalizations.of(context).iaSugCorreoResumir, AppLocalizations.of(context).iaSugCorreoResponder, AppLocalizations.of(context).iaSugCorreoTarea])
                      Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: ChipIa(
                          texto: texto,
                          alPulsar: () => abrirAsistente(context, consulta: texto, contexto: AppLocalizations.of(context).comunMensaje, contextoIa: 'correo, mensaje #${widget.mensajeId}'),
                        ),
                      ),
                  ],
                ),
              ),
            ),
      body: AnchoMaximo(child: FutureBuilder<Mensaje>(
        future: _mensaje,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text(mensajeDeError(AppLocalizations.of(context), snapshot.error!)));
          }
          final m = snapshot.data!;
          final mostrarSinBloqueo = m.remitenteConfiable || _mostrarImagenes;
          final (cuerpoMostrado, bloqueado) = mostrarSinBloqueo
              ? (m.cuerpoHtml ?? '', false)
              : _htmlConImagenesBloqueadas(m.cuerpoHtml);
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text(m.asunto, style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 12),
              // Quién escribe, con su avatar, y cuándo; los destinatarios quedan plegados (casi nunca hacen falta).
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                _AvatarCorreo(nombre: nombreDeRemitente(m.remitente)),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(nombreDeRemitente(m.remitente), style: Theme.of(context).textTheme.titleSmall),
                    Text(_direccionEmail(m.remitente) ?? m.remitente, style: Theme.of(context).textTheme.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
                  ]),
                ),
                if (m.fecha != null) Text(context.formatos.deServidor(m.fecha) ?? '', style: Theme.of(context).textTheme.labelMedium),
              ]),
              ExpansionTile(
                tilePadding: EdgeInsets.zero,
                dense: true,
                title: Text(AppLocalizations.of(context).correoPara(m.destinatarios), maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.bodySmall),
                childrenPadding: EdgeInsets.zero,
                expandedAlignment: Alignment.centerLeft,
                children: [
                  Text(AppLocalizations.of(context).correoDe(m.remitente)),
                  Text(AppLocalizations.of(context).correoPara(m.destinatarios)),
                  if (m.cc != null && m.cc!.isNotEmpty) Text('Cc: ${m.cc}'),
                  const SizedBox(height: 8),
                ],
              ),
              Row(children: [
                Expanded(
                  child: FilledButton.icon(
                    onPressed: () => _responder(m),
                    icon: const Icon(Icons.reply),
                    label: Text(AppLocalizations.of(context).correoResponder),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () => _reenviar(m),
                    icon: const Icon(Icons.forward),
                    label: Text(AppLocalizations.of(context).correoReenviar),
                  ),
                ),
              ]),
              const SizedBox(height: 12),
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(children: [
                  PildoraBoton(
                    icono: m.leido ? Icons.mark_email_read_outlined : Icons.mark_email_unread_outlined,
                    texto: m.leido ? AppLocalizations.of(context).correoLeido : AppLocalizations.of(context).correoNoLeido,
                    alPulsar: () => _accion(() => widget.api.marcarLeido(m.id, !m.leido)),
                  ),
                  const SizedBox(width: 8),
                  PildoraBoton(
                    icono: m.destacado ? Icons.star : Icons.star_border,
                    texto: AppLocalizations.of(context).correoDestacar,
                    activo: m.destacado,
                    alPulsar: () => _accion(() => widget.api.destacarMensaje(m.id, !m.destacado)),
                  ),
                  if (!m.remitenteConfiable) ...[
                    const SizedBox(width: 8),
                    PildoraBoton(icono: Icons.shield_outlined, texto: AppLocalizations.of(context).correoConfiarRemitente, alPulsar: () => _confiarEnRemitente(m.remitente)),
                  ],
                ]),
              ),
              const SizedBox(height: 8),
              ExpansionTile(
                tilePadding: EdgeInsets.zero,
                dense: true,
                title: Text(AppLocalizations.of(context).correoCategoria, style: Theme.of(context).textTheme.labelLarge),
                leading: const Icon(Icons.label_outline, size: 20),
                childrenPadding: const EdgeInsets.only(bottom: 8),
                children: [
                  Row(children: [
                    Expanded(
                      child: DropdownButtonFormField<int?>(
                        initialValue: m.categoriaId,
                        decoration: InputDecoration(labelText: AppLocalizations.of(context).correoCategoria),
                        items: [
                          DropdownMenuItem(value: null, child: Text(AppLocalizations.of(context).correoSinCategoria)),
                          ..._categorias.map((c) => DropdownMenuItem(value: c.id, child: Text(c.nombre))),
                        ],
                        onChanged: (v) => _accion(() => widget.api.asignarCategoria(m.id, v)),
                      ),
                    ),
                    const SizedBox(width: 12),
                    if (widget.carpetas.length > 1)
                      Expanded(
                        child: DropdownButtonFormField<String>(
                          initialValue: m.carpeta,
                          decoration: InputDecoration(labelText: AppLocalizations.of(context).correoMoverA),
                          items: widget.carpetas.map((f) => DropdownMenuItem(value: f.nombre, child: Text(f.nombreVisible))).toList(),
                          onChanged: (v) {
                            if (v != null) _accion(() => widget.api.moverMensaje(m.id, v));
                          },
                        ),
                      ),
                  ]),
                ],
              ),
              if (_error != null) ...[
                const SizedBox(height: 8),
                Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ],
              if (bloqueado) ...[
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Theme.of(context).colorScheme.surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(AppLocalizations.of(context).correoImagenesOcultas),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          TextButton(
                            onPressed: () => setState(() => _mostrarImagenes = true),
                            child: Text(AppLocalizations.of(context).correoMostrarUnaVez),
                          ),
                          TextButton(
                            onPressed: () => _confiarEnRemitente(m.remitente),
                            child: Text(AppLocalizations.of(context).correoConfiarRemitente),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
              const Divider(height: 32),
              if (cuerpoMostrado.trim().isNotEmpty)
                HtmlWidget(cuerpoMostrado)
              else if ((m.cuerpoTexto ?? '').trim().isNotEmpty)
                Text(m.cuerpoTexto!)
              else
                Text(AppLocalizations.of(context).correoSinContenido),
              if (m.adjuntos.isNotEmpty) ...[
                const Divider(height: 32),
                Text(AppLocalizations.of(context).tareaAdjuntos, style: Theme.of(context).textTheme.titleSmall),
                const SizedBox(height: 8),
                ...m.adjuntos.map(
                  (a) => ListTile(
                    leading: _descargandoAdjuntoId == a.id
                        ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.attach_file),
                    title: Text(a.nombreArchivo),
                    subtitle: Text(_tamanoLegible(a.tamanoBytes)),
                    onTap: _descargandoAdjuntoId != null ? null : () => _abrirAdjunto(m, a),
                  ),
                ),
              ],
            ],
          );
        },
      )),
    );
  }
}

/// Círculo con la inicial de quien escribe (el mismo que en la bandeja: el color sale del nombre).
class _AvatarCorreo extends StatelessWidget {
  final String nombre;
  const _AvatarCorreo({required this.nombre});

  @override
  Widget build(BuildContext context) {
    final oscuro = Theme.of(context).brightness == Brightness.dark;
    final limpio = nombre.trim();
    final inicial = limpio.isEmpty ? '?' : String.fromCharCode(limpio.runes.first).toUpperCase();
    final tono = limpio.codeUnits.fold<int>(0, (a, c) => (a * 31 + c) % 360).toDouble();
    return ExcludeSemantics(
      child: CircleAvatar(
        radius: 22,
        backgroundColor: HSLColor.fromAHSL(1, tono, 0.45, oscuro ? 0.30 : 0.86).toColor(),
        child: Text(inicial, style: Theme.of(context).textTheme.titleMedium?.copyWith(color: HSLColor.fromAHSL(1, tono, 0.55, oscuro ? 0.88 : 0.22).toColor())),
      ),
    );
  }
}
