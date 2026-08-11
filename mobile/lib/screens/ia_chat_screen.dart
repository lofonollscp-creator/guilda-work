import 'dart:convert';

import 'package:flutter/material.dart';

import '../models/models.dart';
import '../services/api_client.dart';
import '../widgets/app_button.dart';
import 'ia_ajustes_screen.dart';

/// Chat con el Asistente IA (equivalente móvil de app/templates/ia_asistente.html
/// + app/static/ia_asistente.js). Habla con los mismos endpoints REST que ya
/// expone app/rutas_api.py (ver api_client.dart, sección "Asistente IA") --
/// comparte historial, modelo y modo autónomo con la web; la clave de
/// OpenRouter solo se gestiona desde allí (ver IaAjustesScreen).
class IaChatScreen extends StatefulWidget {
  final ApiClient api;

  const IaChatScreen({super.key, required this.api});

  @override
  State<IaChatScreen> createState() => _IaChatScreenState();
}

class _IaChatScreenState extends State<IaChatScreen> {
  final _controller = TextEditingController();
  final _scroll = ScrollController();

  List<IaMensaje> _mensajes = [];
  IaPendiente? _pendiente;
  bool _cargando = true;
  bool _enviando = false;
  bool _confirmando = false;
  String? _errorCarga;
  String? _errorTurno;

  @override
  void initState() {
    super.initState();
    _cargarHistorial();
  }

  @override
  void dispose() {
    _controller.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _cargarHistorial() async {
    setState(() {
      _cargando = true;
      _errorCarga = null;
    });
    try {
      final mensajes = await widget.api.listarMensajesIa();
      setState(() {
        _mensajes = mensajes;
        _pendiente = _pendienteDesdeHistorial(mensajes);
      });
    } on ApiException catch (e) {
      setState(() => _errorCarga = e.mensaje);
    } finally {
      if (mounted) setState(() => _cargando = false);
    }
  }

  void _scrollAlFinal() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 200),
        curve: Curves.easeOut,
      );
    });
  }

  Future<void> _enviar() async {
    final texto = _controller.text.trim();
    if (texto.isEmpty || _enviando) return;
    _controller.clear();
    setState(() {
      _enviando = true;
      _errorTurno = null;
    });
    _scrollAlFinal();
    try {
      final resultado = await widget.api.enviarMensajeIa(texto);
      setState(() {
        _mensajes = [..._mensajes, ...resultado.mensajesNuevos];
        _pendiente = resultado.pendiente;
      });
    } on ApiException catch (e) {
      setState(() => _errorTurno = e.mensaje);
    } finally {
      if (mounted) setState(() => _enviando = false);
      _scrollAlFinal();
    }
  }

  Future<void> _confirmar(bool aceptar) async {
    setState(() {
      _confirmando = true;
      _errorTurno = null;
    });
    try {
      final resultado = await widget.api.confirmarIa(aceptar);
      setState(() {
        _mensajes = [..._mensajes, ...resultado.mensajesNuevos];
        _pendiente = resultado.pendiente;
      });
    } on ApiException catch (e) {
      setState(() => _errorTurno = e.mensaje);
    } finally {
      if (mounted) setState(() => _confirmando = false);
      _scrollAlFinal();
    }
  }

  Future<void> _vaciar() async {
    final confirmado = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Vaciar conversación'),
        content: const Text('¿Borrar todo el historial de esta conversación? No se puede deshacer.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Borrar')),
        ],
      ),
    );
    if (confirmado != true) return;
    try {
      await widget.api.vaciarIa();
      setState(() {
        _mensajes = [];
        _pendiente = null;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.mensaje)));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Asistente IA'),
        actions: [
          IconButton(
            icon: const Icon(Icons.tune),
            tooltip: 'Ajustes del asistente',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => IaAjustesScreen(api: widget.api)),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.delete_outline),
            tooltip: 'Vaciar conversación',
            onPressed: _mensajes.isEmpty ? null : _vaciar,
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(child: _cuerpo(context)),
            if (_pendiente != null) _tarjetaPendiente(context),
            if (_errorTurno != null)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                child: Text(_errorTurno!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ),
            _cajaEntrada(context),
          ],
        ),
      ),
    );
  }

  Widget _cuerpo(BuildContext context) {
    if (_cargando) return const Center(child: CircularProgressIndicator());
    if (_errorCarga != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_errorCarga!, textAlign: TextAlign.center),
              const SizedBox(height: 12),
              FilledButton(onPressed: _cargarHistorial, child: const Text('Reintentar')),
            ],
          ),
        ),
      );
    }
    if (_mensajes.isEmpty && !_enviando) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.smart_toy_outlined, size: 48, color: Theme.of(context).colorScheme.outline),
              const SizedBox(height: 12),
              const Text(
                'Escríbele al asistente sobre tus notas, tareas o correo. '
                'Puede leer y modificar tus datos si se lo pides.',
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      );
    }
    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.all(12),
      itemCount: _mensajes.length + (_enviando ? 1 : 0),
      itemBuilder: (context, i) {
        if (i >= _mensajes.length) return _burbujaPensando(context);
        return _burbuja(context, _mensajes[i]);
      },
    );
  }

  Widget _burbujaPensando(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(12),
        ),
        child: const Text('Pensando…', style: TextStyle(fontStyle: FontStyle.italic)),
      ),
    );
  }

  Widget _burbuja(BuildContext context, IaMensaje m) {
    switch (m.rol) {
      case 'user':
        return Align(
          alignment: Alignment.centerRight,
          child: Container(
            margin: const EdgeInsets.symmetric(vertical: 4),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.8),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.primaryContainer,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(m.contenido ?? ''),
          ),
        );
      case 'tool':
        return Align(
          alignment: Alignment.center,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Text(
              _textoMensajeTool(m),
              style: TextStyle(
                fontSize: 12,
                color: Theme.of(context).colorScheme.outline,
                fontStyle: FontStyle.italic,
              ),
              textAlign: TextAlign.center,
            ),
          ),
        );
      case 'assistant':
      default:
        if ((m.contenido ?? '').isEmpty) return const SizedBox.shrink();
        return Align(
          alignment: Alignment.centerLeft,
          child: Container(
            margin: const EdgeInsets.symmetric(vertical: 4),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.8),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(12),
            ),
            child: SelectableText.rich(TextSpan(children: _spansMarkdownLite(context, m.contenido ?? ''))),
          ),
        );
    }
  }

  Widget _tarjetaPendiente(BuildContext context) {
    final pendiente = _pendiente!;
    return Card(
      margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text.rich(
              TextSpan(
                children: [
                  const TextSpan(text: '¿Ejecuto '),
                  TextSpan(text: pendiente.herramienta, style: const TextStyle(fontWeight: FontWeight.bold)),
                  const TextSpan(text: '?'),
                ],
              ),
            ),
            if (pendiente.argumentos.isNotEmpty) ...[
              const SizedBox(height: 8),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  pendiente.argumentos.entries.map((e) => '${e.key}: ${e.value}').join('\n'),
                  style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
                ),
              ),
            ],
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: _confirmando ? null : () => _confirmar(false),
                    child: const Text('No'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: AppButton(
                    texto: 'Sí, hazlo',
                    cargando: _confirmando,
                    onPressed: () => _confirmar(true),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _cajaEntrada(BuildContext context) {
    final bloqueado = _pendiente != null;
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _controller,
              enabled: !bloqueado && !_enviando,
              minLines: 1,
              maxLines: 4,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => _enviar(),
              decoration: InputDecoration(
                hintText: bloqueado ? 'Responde a la confirmación de arriba primero…' : 'Escribe un mensaje…',
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(24)),
                contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              ),
            ),
          ),
          const SizedBox(width: 8),
          IconButton.filled(
            icon: const Icon(Icons.send),
            onPressed: (bloqueado || _enviando) ? null : _enviar,
          ),
        ],
      ),
    );
  }
}

/// Texto compacto para un mensaje "tool" (misma lógica que textoMensajeTool
/// en app/static/ia_asistente.js): distingue error/rechazo/ejecución normal
/// leyendo el JSON crudo guardado en `contenido`.
String _textoMensajeTool(IaMensaje m) {
  final herramienta = m.nombreHerramienta ?? 'herramienta';
  final contenido = m.contenido;
  if (contenido == null || contenido.isEmpty) return '🔧 usó $herramienta';
  try {
    final datos = jsonDecode(contenido);
    if (datos is Map && datos['error'] != null) return '⚠️ $herramienta: ${datos['error']}';
    if (datos is Map && datos['rechazado'] == true) return '❌ $herramienta (rechazada)';
  } catch (_) {
    // contenido no era JSON válido: se deja el texto por defecto
  }
  return '🔧 usó $herramienta';
}

/// Reconstruye, a partir del historial completo, si hay una acción esperando
/// confirmación ahora mismo -- mismo criterio que
/// ia_asistente._tool_call_id_pendiente en el backend: el último mensaje es
/// "assistant" con tool_calls, y a alguno de esos tool_calls le falta su fila
/// "tool" de respuesta. Hace falta reconstruirlo aquí porque no hay ningún
/// endpoint REST equivalente a pendiente_actual() (solo lo usa la vista
/// server-rendered /ia/ de la web) -- así el móvil también recupera el
/// estado correcto si se cierra la app a media confirmación.
IaPendiente? _pendienteDesdeHistorial(List<IaMensaje> mensajes) {
  if (mensajes.isEmpty) return null;
  final ultimo = mensajes.last;
  if (ultimo.rol != 'assistant' || ultimo.toolCallsJson == null) return null;
  List<dynamic> toolCalls;
  try {
    toolCalls = (jsonDecode(ultimo.toolCallsJson!) as List);
  } catch (_) {
    return null;
  }
  final idsRespondidos = mensajes.where((m) => m.rol == 'tool').map((m) => m.toolCallId).toSet();
  for (final tc in toolCalls) {
    final id = tc['id'] as String;
    if (!idsRespondidos.contains(id)) {
      final funcion = tc['function'] as Map;
      Map<String, dynamic> argumentos = {};
      try {
        final crudos = funcion['arguments'] as String?;
        if (crudos != null && crudos.isNotEmpty) {
          argumentos = (jsonDecode(crudos) as Map).cast<String, dynamic>();
        }
      } catch (_) {
        // argumentos no parseables: se muestra la confirmación sin detalle
      }
      return IaPendiente(toolCallId: id, herramienta: funcion['name'] as String, argumentos: argumentos);
    }
  }
  return null;
}

/// Subconjunto de markdown ya usado por app/static/ia_asistente.js
/// (negrita, cursiva, código en línea, enlaces) traducido a TextSpans --
/// sin tablas por ahora (poco frecuentes en respuestas cortas de móvil;
/// si hiciera falta, se puede añadir un renderer de tabla como en el JS).
List<InlineSpan> _spansMarkdownLite(BuildContext context, String texto) {
  final spans = <InlineSpan>[];
  final patron = RegExp(r'(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\(https?://[^\s)]+\))');
  var ultimo = 0;
  for (final m in patron.allMatches(texto)) {
    if (m.start > ultimo) spans.add(TextSpan(text: texto.substring(ultimo, m.start)));
    final trozo = m.group(0)!;
    if (trozo.startsWith('`')) {
      spans.add(TextSpan(
        text: trozo.substring(1, trozo.length - 1),
        style: const TextStyle(fontFamily: 'monospace', backgroundColor: Color(0x22808080)),
      ));
    } else if (trozo.startsWith('**')) {
      spans.add(TextSpan(text: trozo.substring(2, trozo.length - 2), style: const TextStyle(fontWeight: FontWeight.bold)));
    } else if (trozo.startsWith('[')) {
      final cierre = trozo.indexOf(']');
      final etiqueta = trozo.substring(1, cierre);
      spans.add(TextSpan(
        text: etiqueta,
        style: TextStyle(color: Theme.of(context).colorScheme.primary, decoration: TextDecoration.underline),
      ));
    }
    ultimo = m.end;
  }
  if (ultimo < texto.length) spans.add(TextSpan(text: texto.substring(ultimo)));
  return spans;
}
