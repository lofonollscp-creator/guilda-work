import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../models/models.dart';
import '../services/api_client.dart';

/// Redactar correo (equivalente móvil de app/templates/correo_redactar.html):
/// cuerpo en texto plano (sin editor enriquecido), enviado como cuerpo_html
/// envolviendo saltos de línea en <br> para que se vea razonable en el
/// destinatario. Usada tanto para mensajes nuevos como para Responder/Reenviar
/// (precargados desde correo_mensaje_screen.dart). Incluye adjuntar archivos
/// (Fase 5a) y autocompletar de destinatarios recientes (Fase 5c).
class CorreoComposeScreen extends StatefulWidget {
  final ApiClient api;
  final int? cuentaIdInicial;
  final String destinatariosIniciales;
  final String asuntoInicial;
  final String cuerpoInicial;
  final String? enRespuestaA;

  const CorreoComposeScreen({
    super.key,
    required this.api,
    this.cuentaIdInicial,
    this.destinatariosIniciales = '',
    this.asuntoInicial = '',
    this.cuerpoInicial = '',
    this.enRespuestaA,
  });

  @override
  State<CorreoComposeScreen> createState() => _CorreoComposeScreenState();
}

class _CorreoComposeScreenState extends State<CorreoComposeScreen> {
  late Future<List<CuentaCorreo>> _cuentas;
  int? _cuentaId;
  late final TextEditingController _destinatariosController;
  late final TextEditingController _asuntoController;
  late final TextEditingController _cuerpoController;
  final _ccController = TextEditingController();
  final _bccController = TextEditingController();
  bool _mostrarCcBcc = false;
  bool _enviando = false;
  String? _error;
  final List<ArchivoAdjuntoNuevo> _adjuntos = [];

  List<DestinatarioReciente> _sugerenciasPara = [];
  List<DestinatarioReciente> _sugerenciasCc = [];
  List<DestinatarioReciente> _sugerenciasBcc = [];
  Timer? _debounce;

  @override
  void initState() {
    super.initState();
    _cuentaId = widget.cuentaIdInicial;
    _destinatariosController = TextEditingController(text: widget.destinatariosIniciales);
    _asuntoController = TextEditingController(text: widget.asuntoInicial);
    _cuerpoController = TextEditingController();
    _cuentas = widget.api.listarCuentasCorreo();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  String _fragmentoActual(String texto) {
    final partes = texto.split(',');
    return partes.last.trim();
  }

  void _buscarSugerencias(String texto, void Function(List<DestinatarioReciente>) aplicar) {
    _debounce?.cancel();
    final q = _fragmentoActual(texto);
    if (q.length < 2) {
      aplicar([]);
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 250), () async {
      try {
        final resultados = await widget.api.buscarDestinatariosRecientes(q);
        if (mounted) aplicar(resultados);
      } catch (_) {
        // Sin conexión o error: simplemente no se muestran sugerencias.
      }
    });
  }

  void _elegirSugerencia(
    TextEditingController controlador,
    DestinatarioReciente elegido,
    void Function(List<DestinatarioReciente>) limpiar,
  ) {
    final partes = controlador.text.split(',');
    partes[partes.length - 1] = ' ${elegido.direccion}';
    controlador.text = '${partes.map((p) => p.trim()).where((p) => p.isNotEmpty).join(', ')}, ';
    controlador.selection = TextSelection.collapsed(offset: controlador.text.length);
    limpiar([]);
  }

  Widget _campoConAutocompletar({
    required TextEditingController controlador,
    required String etiqueta,
    required List<DestinatarioReciente> sugerencias,
    required void Function(String) alEscribir,
    required void Function(List<DestinatarioReciente>) limpiar,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TextField(
          controller: controlador,
          decoration: InputDecoration(labelText: etiqueta),
          onChanged: alEscribir,
        ),
        if (sugerencias.isNotEmpty)
          Container(
            margin: const EdgeInsets.only(top: 4),
            decoration: BoxDecoration(
              border: Border.all(color: Theme.of(context).dividerColor),
              borderRadius: BorderRadius.circular(6),
            ),
            constraints: const BoxConstraints(maxHeight: 160),
            child: ListView(
              shrinkWrap: true,
              children: sugerencias
                  .map((s) => ListTile(
                        dense: true,
                        title: Text(s.etiqueta),
                        onTap: () => _elegirSugerencia(controlador, s, limpiar),
                      ))
                  .toList(),
            ),
          ),
      ],
    );
  }

  Future<void> _adjuntarArchivo() async {
    final resultado = await FilePicker.pickFiles(withData: true);
    if (resultado == null || resultado.files.isEmpty) return;
    final archivo = resultado.files.single;
    if (archivo.bytes == null) return;
    setState(() {
      _adjuntos.add(ArchivoAdjuntoNuevo(
        nombre: archivo.name,
        tipo: 'application/octet-stream',
        bytes: archivo.bytes!,
      ));
    });
  }

  Future<void> _enviar() async {
    if (_cuentaId == null) {
      setState(() => _error = 'Elige una cuenta desde la que enviar.');
      return;
    }
    final destinatarios = _destinatariosController.text.trim();
    final asunto = _asuntoController.text.trim();
    if (destinatarios.isEmpty || asunto.isEmpty) {
      setState(() => _error = 'Rellena al menos destinatarios y asunto.');
      return;
    }
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('¿Enviar a $destinatarios?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Enviar')),
        ],
      ),
    );
    if (confirmar != true) return;

    setState(() {
      _enviando = true;
      _error = null;
    });
    final cuerpoPlano = _cuerpoController.text.trim();
    final cuerpoHtml =
        '${cuerpoPlano.replaceAll('\n', '<br>')}${widget.cuerpoInicial}';
    try {
      await widget.api.enviarCorreo(
        cuentaId: _cuentaId!,
        destinatarios: destinatarios,
        cc: _ccController.text.trim().isEmpty ? null : _ccController.text.trim(),
        bcc: _bccController.text.trim().isEmpty ? null : _bccController.text.trim(),
        asunto: asunto,
        cuerpoHtml: cuerpoHtml,
        enRespuestaA: widget.enRespuestaA,
        adjuntos: _adjuntos,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Correo enviado.')),
      );
      Navigator.of(context).pop();
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _enviando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Redactar')),
      body: FutureBuilder<List<CuentaCorreo>>(
        future: _cuentas,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text('Error al cargar: ${snapshot.error}'));
          }
          final cuentas = snapshot.data ?? [];
          _cuentaId ??= cuentas.isNotEmpty ? cuentas.first.id : null;
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              DropdownButtonFormField<int>(
                initialValue: _cuentaId,
                decoration: const InputDecoration(labelText: 'De'),
                items: cuentas
                    .map((c) => DropdownMenuItem(value: c.id, child: Text(c.nombre)))
                    .toList(),
                onChanged: (v) => setState(() => _cuentaId = v),
              ),
              const SizedBox(height: 12),
              _campoConAutocompletar(
                controlador: _destinatariosController,
                etiqueta: 'Para',
                sugerencias: _sugerenciasPara,
                alEscribir: (texto) => _buscarSugerencias(
                  texto,
                  (r) => setState(() => _sugerenciasPara = r),
                ),
                limpiar: (r) => setState(() => _sugerenciasPara = r),
              ),
              if (!_mostrarCcBcc)
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton(
                    onPressed: () => setState(() => _mostrarCcBcc = true),
                    child: const Text('Añadir Cc/Cco'),
                  ),
                )
              else ...[
                const SizedBox(height: 12),
                _campoConAutocompletar(
                  controlador: _ccController,
                  etiqueta: 'Cc',
                  sugerencias: _sugerenciasCc,
                  alEscribir: (texto) => _buscarSugerencias(
                    texto,
                    (r) => setState(() => _sugerenciasCc = r),
                  ),
                  limpiar: (r) => setState(() => _sugerenciasCc = r),
                ),
                const SizedBox(height: 12),
                _campoConAutocompletar(
                  controlador: _bccController,
                  etiqueta: 'Cco',
                  sugerencias: _sugerenciasBcc,
                  alEscribir: (texto) => _buscarSugerencias(
                    texto,
                    (r) => setState(() => _sugerenciasBcc = r),
                  ),
                  limpiar: (r) => setState(() => _sugerenciasBcc = r),
                ),
              ],
              const SizedBox(height: 12),
              TextField(
                controller: _asuntoController,
                decoration: const InputDecoration(labelText: 'Asunto'),
                autofocus: widget.asuntoInicial.isEmpty,
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _cuerpoController,
                decoration: const InputDecoration(labelText: 'Mensaje'),
                maxLines: 10,
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 4,
                children: [
                  ..._adjuntos.map(
                    (a) => Chip(
                      label: Text(a.nombre),
                      onDeleted: () => setState(() => _adjuntos.remove(a)),
                    ),
                  ),
                  ActionChip(
                    avatar: const Icon(Icons.attach_file, size: 18),
                    label: const Text('Adjuntar'),
                    onPressed: _adjuntarArchivo,
                  ),
                ],
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ],
              const SizedBox(height: 24),
              Row(
                children: [
                  FilledButton(
                    onPressed: _enviando ? null : _enviar,
                    child: const Text('Enviar'),
                  ),
                  const SizedBox(width: 12),
                  TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('Descartar'),
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
