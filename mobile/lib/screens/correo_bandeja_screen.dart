import 'package:flutter/material.dart';

import '../diseno/componentes.dart';

import '../l10n/app_localizations.dart';

import '../diseno/formatos.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../theme/brand_colors.dart';
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
      if (mounted) setState(() => _error = mensajeDeError(AppLocalizations.of(context), e));
      return <Mensaje>[];
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(AppLocalizations.of(context).dashboardCorreoTooltip),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            tooltip: AppLocalizations.of(context).correoAjustesTitulo,
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
        tooltip: AppLocalizations.of(context).correoRedactar,
        child: const Icon(Icons.edit),
      ),
      body: FutureBuilder<List<CuentaCorreo>>(
        future: _cuentas,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text(mensajeDeError(AppLocalizations.of(context), snapshot.error!)));
          }
          final cuentas = snapshot.data ?? [];
          if (cuentas.isEmpty) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text(
                  AppLocalizations.of(context).correoSinCuenta,
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
                      decoration: InputDecoration(
                        hintText: AppLocalizations.of(context).comunBuscarHint,
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
                        Text(AppLocalizations.of(context).correoSoloNoLeidos),
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
                            return Center(child: Text(mensajeDeError(AppLocalizations.of(context), snapshot.error!)));
                          }
                          final mensajes = snapshot.data ?? [];
                          if (mensajes.isEmpty) {
                            return Center(child: Text(AppLocalizations.of(context).correoSinMensajes));
                          }
                          return ListView.builder(
                            padding: const EdgeInsets.only(bottom: 88), // que el botón «+» no tape el último correo
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
      // Punto de «no leído» (no solo la negrita) y estrella si es destacado.
      leading: SizedBox(
        width: 28,
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Semantics(label: m.leido ? null : AppLocalizations.of(context).correoNoLeido, child: Icon(Icons.circle, size: 10, color: m.leido ? Colors.transparent : Theme.of(context).colorScheme.primary)),
          const SizedBox(width: 6),
          Icon(m.destacado ? Icons.star : Icons.mail_outline, size: 18, color: m.destacado ? BrandColors.warningLight : null),
        ]),
      ),
      title: Text(
        nombreDeRemitente(m.remitente),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(fontWeight: m.leido ? FontWeight.w400 : FontWeight.w700),
      ),
      subtitle: Text(
        '${m.asunto}${vistaPrevia.isNotEmpty ? ' · $vistaPrevia' : ''}',
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: m.fecha == null ? null : Text(context.formatos.deServidor(m.fecha) ?? '', style: Theme.of(context).textTheme.labelMedium),
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
