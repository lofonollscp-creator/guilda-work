import 'package:flutter/material.dart';

import '../models/models.dart';
import '../services/api_client.dart';
import 'correo_ajustes_screen.dart';
import 'correo_compose_screen.dart';
import 'correo_mensaje_screen.dart';

/// Bandeja de correo (equivalente móvil de app/templates/correo_bandeja.html):
/// selector de cuenta + carpeta, buscador, y lista de mensajes. Sin las
/// acciones en lote ni el panel de lectura embebido de la web — cada mensaje
/// se abre en su propia pantalla (correo_mensaje_screen.dart).
class CorreoBandejaScreen extends StatefulWidget {
  final ApiClient api;

  const CorreoBandejaScreen({super.key, required this.api});

  @override
  State<CorreoBandejaScreen> createState() => _CorreoBandejaScreenState();
}

class _CorreoBandejaScreenState extends State<CorreoBandejaScreen> {
  late Future<List<CuentaCorreo>> _cuentas;
  List<Carpeta> _carpetas = [];
  int? _cuentaId;
  String _carpeta = 'INBOX';
  Future<List<Mensaje>>? _mensajes;
  final _buscarController = TextEditingController();
  bool _soloNoLeidos = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _cuentas = _cargarCuentas();
  }

  Future<List<CuentaCorreo>> _cargarCuentas() async {
    final cuentas = await widget.api.listarCuentasCorreo();
    if (cuentas.isNotEmpty) {
      await _seleccionarCuenta(cuentas.first.id);
    }
    return cuentas;
  }

  Future<void> _seleccionarCuenta(int cuentaId) async {
    final carpetas = await widget.api.listarCarpetas(cuentaId);
    setState(() {
      _cuentaId = cuentaId;
      _carpetas = carpetas;
      _carpeta = carpetas.isNotEmpty ? carpetas.first.nombre : 'INBOX';
    });
    _recargarMensajes();
  }

  void _recargarMensajes() {
    if (_cuentaId == null) return;
    final futuro = widget.api.listarMensajes(
      cuentaId: _cuentaId!,
      carpeta: _carpeta,
      noLeidos: _soloNoLeidos ? true : null,
      q: _buscarController.text.trim().isEmpty ? null : _buscarController.text.trim(),
    );
    setState(() {
      _mensajes = futuro;
      _error = null;
    });
    futuro.catchError((e) {
      setState(() => _error = e.toString());
      return <Mensaje>[];
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Correo'),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            tooltip: 'Ajustes de correo',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => CorreoAjustesScreen(api: widget.api)),
            ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: _cuentaId == null
            ? null
            : () async {
                await Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => CorreoComposeScreen(
                      api: widget.api,
                      cuentaIdInicial: _cuentaId,
                    ),
                  ),
                );
              },
        tooltip: 'Redactar',
        child: const Icon(Icons.edit),
      ),
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
          if (cuentas.isEmpty) {
            return const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  'Todavía no tienes ninguna cuenta de correo configurada. '
                  'Añade una desde la app de escritorio.',
                  textAlign: TextAlign.center,
                ),
              ),
            );
          }
          return Column(
            children: [
              Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: DropdownButton<int>(
                            isExpanded: true,
                            value: _cuentaId,
                            items: cuentas
                                .map((c) => DropdownMenuItem(value: c.id, child: Text(c.nombre)))
                                .toList(),
                            onChanged: (v) {
                              if (v != null) _seleccionarCuenta(v);
                            },
                          ),
                        ),
                        const SizedBox(width: 8),
                        if (_carpetas.isNotEmpty)
                          DropdownButton<String>(
                            value: _carpeta,
                            items: _carpetas
                                .map((f) => DropdownMenuItem(
                                      value: f.nombre,
                                      child: Text(f.nombreVisible),
                                    ))
                                .toList(),
                            onChanged: (v) {
                              if (v != null) {
                                setState(() => _carpeta = v);
                                _recargarMensajes();
                              }
                            },
                          ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    TextField(
                      controller: _buscarController,
                      decoration: const InputDecoration(
                        hintText: 'Buscar...',
                        prefixIcon: Icon(Icons.search),
                      ),
                      onSubmitted: (_) => _recargarMensajes(),
                    ),
                    Row(
                      children: [
                        Checkbox(
                          value: _soloNoLeidos,
                          onChanged: (v) {
                            setState(() => _soloNoLeidos = v ?? false);
                            _recargarMensajes();
                          },
                        ),
                        const Text('Solo no leídos'),
                      ],
                    ),
                    if (_error != null)
                      Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                  ],
                ),
              ),
              Expanded(
                child: _mensajes == null
                    ? const SizedBox()
                    : FutureBuilder<List<Mensaje>>(
                        future: _mensajes,
                        builder: (context, snapshot) {
                          if (snapshot.connectionState != ConnectionState.done) {
                            return const Center(child: CircularProgressIndicator());
                          }
                          if (snapshot.hasError) {
                            return Center(child: Text('Error al cargar: ${snapshot.error}'));
                          }
                          final mensajes = snapshot.data ?? [];
                          if (mensajes.isEmpty) {
                            return const Center(child: Text('No hay mensajes para este filtro.'));
                          }
                          return ListView.builder(
                            itemCount: mensajes.length,
                            itemBuilder: (context, i) => _tarjetaMensaje(mensajes[i]),
                          );
                        },
                      ),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _tarjetaMensaje(Mensaje m) {
    final vistaPrevia = (m.cuerpoTexto ?? '').trim();
    return ListTile(
      leading: m.destacado ? const Icon(Icons.star, color: Colors.amber) : const Icon(Icons.mail_outline),
      title: Text(
        m.asunto,
        style: TextStyle(fontWeight: m.leido ? FontWeight.normal : FontWeight.bold),
      ),
      subtitle: Text(
        '${m.remitente}${vistaPrevia.isNotEmpty ? ' · $vistaPrevia' : ''}',
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: m.fecha != null ? Text(m.fecha!.substring(0, 10)) : null,
      onTap: () async {
        await Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => CorreoMensajeScreen(
              api: widget.api,
              mensajeId: m.id,
              carpetas: _carpetas,
            ),
          ),
        );
        _recargarMensajes();
      },
    );
  }
}
