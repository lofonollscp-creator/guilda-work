import 'dart:io';

import 'package:flutter/material.dart';
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

  const CorreoMensajeScreen({
    super.key,
    required this.api,
    required this.mensajeId,
    required this.carpetas,
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
      setState(() => _error = e.toString());
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
        title: const Text('¿Eliminar este mensaje?'),
        content: const Text('Se eliminará de la copia local de este correo.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Eliminar')),
        ],
      ),
    );
    if (confirmar != true) return;
    try {
      await widget.api.eliminarMensaje(widget.mensajeId);
      if (!mounted) return;
      Navigator.of(context).pop();
    } catch (e) {
      setState(() => _error = e.toString());
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
          title: const Text('Remitente no confiable'),
          content: Text(
            'Este adjunto viene de "${m.remitente}", que no está en tu lista de confianza. '
            '¿Abrir igualmente "${a.nombreArchivo}"?',
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
            FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Abrir')),
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
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _descargandoAdjuntoId = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Mensaje'),
        actions: [
          IconButton(icon: const Icon(Icons.delete_outline), tooltip: 'Eliminar', onPressed: _eliminar),
        ],
      ),
      body: FutureBuilder<Mensaje>(
        future: _mensaje,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text('Error al cargar: ${snapshot.error}'));
          }
          final m = snapshot.data!;
          final mostrarSinBloqueo = m.remitenteConfiable || _mostrarImagenes;
          final (cuerpoMostrado, bloqueado) = mostrarSinBloqueo
              ? (m.cuerpoHtml ?? '', false)
              : _htmlConImagenesBloqueadas(m.cuerpoHtml);
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text(m.asunto, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 8),
              Text('De: ${m.remitente}'),
              Text('Para: ${m.destinatarios}'),
              if (m.cc != null && m.cc!.isNotEmpty) Text('Cc: ${m.cc}'),
              if (m.fecha != null) Text(m.fecha!),
              const SizedBox(height: 16),
              Wrap(
                spacing: 8,
                runSpacing: 4,
                children: [
                  ActionChip(
                    avatar: Icon(m.leido ? Icons.mark_email_read : Icons.mark_email_unread),
                    label: Text(m.leido ? 'Leído' : 'No leído'),
                    onPressed: () => _accion(() => widget.api.marcarLeido(m.id, !m.leido)),
                  ),
                  ActionChip(
                    avatar: Icon(m.destacado ? Icons.star : Icons.star_border),
                    label: const Text('Destacar'),
                    onPressed: () => _accion(() => widget.api.destacarMensaje(m.id, !m.destacado)),
                  ),
                  if (!m.remitenteConfiable)
                    ActionChip(
                      avatar: const Icon(Icons.shield_outlined),
                      label: const Text('Confiar en remitente'),
                      onPressed: () => _confiarEnRemitente(m.remitente),
                    ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: DropdownButtonFormField<int?>(
                      initialValue: m.categoriaId,
                      decoration: const InputDecoration(labelText: 'Categoría'),
                      items: [
                        const DropdownMenuItem(value: null, child: Text('Sin categoría')),
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
                        decoration: const InputDecoration(labelText: 'Mover a'),
                        items: widget.carpetas
                            .map((f) => DropdownMenuItem(value: f.nombre, child: Text(f.nombreVisible)))
                            .toList(),
                        onChanged: (v) {
                          if (v != null) _accion(() => widget.api.moverMensaje(m.id, v));
                        },
                      ),
                    ),
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
                      const Text('🖼 Imágenes ocultas por privacidad — este remitente no está en tu lista de confianza.'),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          TextButton(
                            onPressed: () => setState(() => _mostrarImagenes = true),
                            child: const Text('Mostrar solo esta vez'),
                          ),
                          TextButton(
                            onPressed: () => _confiarEnRemitente(m.remitente),
                            child: const Text('Confiar en remitente'),
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
                const Text('Sin contenido legible.'),
              if (m.adjuntos.isNotEmpty) ...[
                const Divider(height: 32),
                Text('Adjuntos', style: Theme.of(context).textTheme.titleSmall),
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
              const SizedBox(height: 24),
              Row(
                children: [
                  FilledButton.icon(
                    onPressed: () => _responder(m),
                    icon: const Icon(Icons.reply),
                    label: const Text('Responder'),
                  ),
                  const SizedBox(width: 12),
                  OutlinedButton.icon(
                    onPressed: () => _reenviar(m),
                    icon: const Icon(Icons.forward),
                    label: const Text('Reenviar'),
                  ),
                ],
              ),
            ],
          );
        },
      ),
    );
  }
}
