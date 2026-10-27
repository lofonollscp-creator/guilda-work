import 'package:flutter/material.dart';

import '../nucleo/abrir_asistente.dart';

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
          AccionAsistente(contexto: AppLocalizations.of(context).dashboardCorreoTooltip),
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
          final t = AppLocalizations.of(context);
          final cuentaActual = cuentas.where((c) => c.id == _cuentaId).firstOrNull;
          final carpetaActual = _carpetas.where((f) => f.nombre == _carpeta).firstOrNull;
          return Column(
            children: [
              // Una sola fila de píldoras (cuenta, carpeta, no leídos) y el buscador redondeado, en vez de dos desplegables y una casilla.
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.fromLTRB(12, 10, 12, 4),
                child: Row(children: [
                  if (cuentas.length > 1) ...[
                    PildoraMenu<int>(
                      icono: Icons.alternate_email,
                      texto: cuentaActual?.nombre ?? '',
                      activo: false,
                      opciones: [for (final c in cuentas) (c.id, c.nombre)],
                      seleccionado: _cuentaId ?? cuentas.first.id,
                      alElegir: _seleccionarCuenta,
                    ),
                    const SizedBox(width: 8),
                  ],
                  if (_carpetas.isNotEmpty) ...[
                    PildoraMenu<String>(
                      icono: Icons.folder_outlined,
                      texto: carpetaActual?.nombreVisible ?? _carpeta,
                      activo: false,
                      opciones: [for (final f in _carpetas) (f.nombre, f.nombreVisible)],
                      seleccionado: _carpeta,
                      alElegir: (v) {
                        setState(() => _carpeta = v);
                        _recargarMensajes();
                      },
                    ),
                    const SizedBox(width: 8),
                  ],
                  PildoraBoton(
                    icono: _soloNoLeidos ? Icons.mark_email_unread : Icons.mark_email_unread_outlined,
                    texto: t.correoSoloNoLeidos,
                    activo: _soloNoLeidos,
                    alPulsar: () {
                      setState(() => _soloNoLeidos = !_soloNoLeidos);
                      _recargarMensajes();
                    },
                  ),
                ]),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
                child: TextField(
                  controller: _buscarController,
                  textInputAction: TextInputAction.search,
                  decoration: InputDecoration(
                    hintText: t.comunBuscarHint,
                    prefixIcon: const Icon(Icons.search),
                    isDense: true,
                    contentPadding: const EdgeInsets.symmetric(vertical: 12),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide(color: Theme.of(context).colorScheme.outlineVariant)),
                    enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide(color: Theme.of(context).colorScheme.outlineVariant)),
                  ),
                  onSubmitted: (_) => _recargarMensajes(),
                ),
              ),
              if (_error != null) BannerEstado(tipo: TipoBanner.error, texto: _error!),
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
    final tema = Theme.of(context);
    final t = AppLocalizations.of(context);
    final vistaPrevia = (m.cuerpoTexto ?? '').trim().replaceAll(RegExp(r'\s+'), ' ');
    final remitente = nombreDeRemitente(m.remitente);
    final fecha = m.fecha == null ? null : context.formatos.deServidor(m.fecha);
    return InkWell(
      onTap: () async {
        await Navigator.of(context).push(
          MaterialPageRoute(builder: (_) => CorreoMensajeScreen(api: widget.api, mensajeId: m.id, carpetas: _carpetas)),
        );
        _recargarMensajes();
      },
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 10, 16, 10),
        decoration: BoxDecoration(
          color: m.leido ? null : tema.colorScheme.primary.withValues(alpha: tema.brightness == Brightness.dark ? 0.06 : 0.09),
          border: Border(bottom: BorderSide(color: tema.colorScheme.outlineVariant.withValues(alpha: 0.6))),
        ),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          // El avatar con la inicial; el punto de «no leído» va en una esquina (y se dice en voz alta: no solo es color ni negrita).
          Semantics(
            label: m.leido ? null : t.correoNoLeido,
            child: Stack(clipBehavior: Clip.none, children: [
              _AvatarRemitente(nombre: remitente),
              if (!m.leido) Positioned(right: -2, top: -2, child: Container(width: 12, height: 12, decoration: BoxDecoration(color: tema.colorScheme.primary, shape: BoxShape.circle, border: Border.all(color: tema.colorScheme.surface, width: 2)))),
            ]),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Expanded(child: Text(remitente, maxLines: 1, overflow: TextOverflow.ellipsis, style: tema.textTheme.titleSmall?.copyWith(fontWeight: m.leido ? FontWeight.w500 : FontWeight.w800))),
                if (fecha != null) Text(fecha, style: tema.textTheme.labelMedium),
              ]),
              const SizedBox(height: 2),
              Row(children: [
                Expanded(child: Text(m.asunto, maxLines: 1, overflow: TextOverflow.ellipsis, style: tema.textTheme.bodyMedium?.copyWith(fontWeight: m.leido ? FontWeight.w400 : FontWeight.w700))),
                if (m.destacado) Padding(padding: const EdgeInsets.only(left: 6), child: Icon(Icons.star, size: 18, color: tema.brightness == Brightness.dark ? BrandColors.warningDark : BrandColors.warningLight)),
              ]),
              if (vistaPrevia.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 2), child: Text(vistaPrevia, maxLines: 1, overflow: TextOverflow.ellipsis, style: tema.textTheme.bodySmall)),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// Círculo con la inicial del remitente; el color sale de su nombre (siempre el mismo para la misma persona) y el texto se lee sobre él.
class _AvatarRemitente extends StatelessWidget {
  final String nombre;
  const _AvatarRemitente({required this.nombre});

  @override
  Widget build(BuildContext context) {
    final oscuro = Theme.of(context).brightness == Brightness.dark;
    final limpio = nombre.trim();
    final inicial = limpio.isEmpty ? '?' : String.fromCharCode(limpio.runes.first).toUpperCase();
    final tono = limpio.codeUnits.fold<int>(0, (a, c) => (a * 31 + c) % 360).toDouble();
    final fondo = HSLColor.fromAHSL(1, tono, 0.45, oscuro ? 0.30 : 0.86).toColor();
    final texto = HSLColor.fromAHSL(1, tono, 0.55, oscuro ? 0.88 : 0.22).toColor();
    return ExcludeSemantics(
      child: CircleAvatar(radius: 22, backgroundColor: fondo, child: Text(inicial, style: Theme.of(context).textTheme.titleMedium?.copyWith(color: texto))),
    );
  }
}
