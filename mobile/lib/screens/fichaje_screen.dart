import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';

import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../datos/cola.dart';
import '../datos/local/cola_escritura.dart' show ColaLlena;
import '../funciones/fichaje/fichaje_acciones.dart';
import '../funciones/pendientes/pendientes_sheet.dart';
import '../theme/app_theme.dart';
import '../theme/brand_colors.dart';
import '../widgets/status_badge.dart';
import 'fichaje_datos_screen.dart';
import 'ausencias_screen.dart';
import 'fichaje_historial_screen.dart';

/// Panel de fichaje del trabajador (equivalente móvil de
/// app/templates/fichaje_panel.html): estado actual + botones grandes de
/// Entrada/Pausa/Fin de pausa/Salida, y los fichajes de hoy. Sin las
/// vistas de administración (revisar horas de un tenant no es una tarea
/// de móvil, se queda en web/escritorio -- ver app/rutas_fichaje.py).
class FichajeScreen extends ConsumerStatefulWidget {
  final ApiClient api;
  final Usuario usuario;

  const FichajeScreen({super.key, required this.api, required this.usuario});

  @override
  ConsumerState<FichajeScreen> createState() => _FichajeScreenState();
}

class _FichajeScreenState extends ConsumerState<FichajeScreen> {
  late Future<(String, bool)> _estado;
  Future<List<FichajeEvento>>? _hoy;
  Future<ResumenSemanaFichaje>? _semana;
  String? _error;
  bool _marcando = false;

  @override
  void initState() {
    super.initState();
    _estado = _cargar();
  }

  static const _estadoTrasMarcar = {
    'entrada': 'dentro',
    'pausa_inicio': 'en_pausa',
    'pausa_fin': 'dentro',
    'salida': 'fuera',
  };

  Future<(String, bool)> _cargar() async {
    final estado = await widget.api.obtenerEstadoFichaje();
    if (estado.$2) {
      final hoy = DateTime.now().toIso8601String().substring(0, 10);
      setState(() {
        _hoy = widget.api.listarMisFichajes(desde: hoy, hasta: hoy);
        _semana = widget.api.obtenerResumenSemanaFichaje();
      });
    }
    return estado;
  }

  Future<void> _recargar() async {
    final futuro = _cargar();
    setState(() {
      _estado = futuro;
      _error = null;
    });
    await futuro;
  }

  /// Ubicación opcional (Fase G3) -- solo se pide si el tenant la tiene
  /// activada (widget.usuario.fichajeGeolocalizacion); nunca bloquea
  /// fichar: si el permiso se deniega, tarda, o falla por cualquier
  /// motivo, se sigue sin coordenadas (mismo criterio que la web).
  Future<(double?, double?)> _ubicacionOpcional() async {
    if (!widget.usuario.fichajeGeolocalizacion) return (null, null);
    try {
      final servicioActivo = await Geolocator.isLocationServiceEnabled();
      if (!servicioActivo) return (null, null);
      var permiso = await Geolocator.checkPermission();
      if (permiso == LocationPermission.denied) {
        permiso = await Geolocator.requestPermission();
      }
      if (permiso == LocationPermission.denied || permiso == LocationPermission.deniedForever) {
        return (null, null);
      }
      final posicion = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(accuracy: LocationAccuracy.medium),
      ).timeout(const Duration(seconds: 3));
      return (posicion.latitude, posicion.longitude);
    } catch (_) {
      return (null, null);
    }
  }

  Future<void> _marcar(String tipo) async {
    final t = AppLocalizations.of(context);
    setState(() {
      _marcando = true;
      _error = null;
    });
    try {
      final (latitud, longitud) = await _ubicacionOpcional();
      final r = await ref.read(accionesFichajeProvider).marcar(tipo, latitud: latitud, longitud: longitud);
      if (r.encolada) {
        // UI optimista: refleja el nuevo estado sin esperar a que se envíe.
        setState(() => _estado = Future.value((_estadoTrasMarcar[tipo]!, true)));
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(t.fichajeSinConexionNota)),
          );
        }
      } else {
        await _recargar();
      }
    } on ColaLlena {
      setState(() => _error = t.colaLlena);
    } on ApiException catch (e) {
      setState(() => _error = e.toString());
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _marcando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(t.fichajeTitulo),
        // Antes tres iconos sueltos sin texto; ahora un menú con nombre (historial, ausencias, mis datos).
        actions: [
          PopupMenuButton<String>(
            tooltip: t.menuMasOpciones,
            onSelected: (v) async {
              switch (v) {
                case 'historial':
                  await Navigator.of(context).push(MaterialPageRoute(builder: (_) => FichajeHistorialScreen(api: widget.api)));
                case 'ausencias':
                  await Navigator.of(context).push(MaterialPageRoute(builder: (_) => AusenciasScreen(api: widget.api)));
                case 'datos':
                  await Navigator.of(context).push(MaterialPageRoute(builder: (_) => FichajeDatosScreen(api: widget.api)));
                  await _recargar();
              }
            },
            itemBuilder: (_) => [
              PopupMenuItem(value: 'historial', child: ListTile(leading: const Icon(Icons.history), title: Text(t.fichajeHistorialTooltip), contentPadding: EdgeInsets.zero)),
              PopupMenuItem(value: 'ausencias', child: ListTile(leading: const Icon(Icons.beach_access_outlined), title: Text(t.ausenciasTooltip), contentPadding: EdgeInsets.zero)),
              PopupMenuItem(value: 'datos', child: ListTile(leading: const Icon(Icons.badge_outlined), title: Text(t.fichajeMisDatosTooltip), contentPadding: EdgeInsets.zero)),
            ],
          ),
        ],
      ),
      body: FutureBuilder<(String, bool)>(
        future: _estado,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text(t.comunErrorCargar(snapshot.error.toString())));
          }
          final (estado, datosCompletos) = snapshot.data!;
          if (!datosCompletos) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      t.fichajeDatosIncompletos,
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 16),
                    FilledButton(
                      onPressed: () async {
                        await Navigator.of(context).push(
                          MaterialPageRoute(builder: (_) => FichajeDatosScreen(api: widget.api)),
                        );
                        await _recargar();
                      },
                      child: Text(t.fichajeRellenarDatosBoton),
                    ),
                  ],
                ),
              ),
            );
          }
          return RefreshIndicator(
            onRefresh: _recargar,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                const AvisoPendientes(),
                Center(child: _pillEstado(estado, t)),
                if (ref.watch(numFichajesPendientesProvider) > 0) ...[
                  const SizedBox(height: 8),
                  Center(
                    child: Text(
                      t.fichajePendientesSinc(ref.watch(numFichajesPendientesProvider)),
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
                ],
                const SizedBox(height: 20),
                if (_error != null) ...[
                  Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                  const SizedBox(height: 12),
                ],
                Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  alignment: WrapAlignment.center,
                  children: [
                    _botonFichar(t.fichajeEntradaBoton, BrandColors.success, estado == 'fuera', () => _marcar('entrada')),
                    _botonFichar(t.fichajeIniciarPausaBoton, _colorAviso(context), estado == 'dentro', () => _marcar('pausa_inicio')),
                    _botonFichar(t.fichajeFinPausaBoton, _colorAviso(context), estado == 'en_pausa', () => _marcar('pausa_fin')),
                    _botonFichar(t.fichajeSalidaBoton, _colorPeligro(context), estado != 'fuera', () => _marcar('salida')),
                  ],
                ),
                const SizedBox(height: 24),
                if (_semana != null) _tarjetaSemana(t),
                const SizedBox(height: 24),
                Text(t.fichajeHoyTitulo, style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                if (_hoy != null)
                  FutureBuilder<List<FichajeEvento>>(
                    future: _hoy,
                    builder: (context, snap) {
                      if (snap.connectionState != ConnectionState.done) {
                        return const Padding(
                          padding: EdgeInsets.all(16),
                          child: Center(child: CircularProgressIndicator()),
                        );
                      }
                      final eventos = snap.data ?? [];
                      if (eventos.isEmpty) {
                        return Padding(
                          padding: const EdgeInsets.all(8),
                          child: Text(t.fichajeSinFichajesHoy),
                        );
                      }
                      final etiquetas = etiquetasFichaje(t);
                      return Column(
                        children: eventos
                            .map((f) => ListTile(
                                  dense: true,
                                  leading: const Icon(Icons.access_time),
                                  title: Text(etiquetas[f.tipo] ?? f.tipo),
                                  trailing: Text(f.marcaTiempo.substring(11, 16), style: AppTheme.cifra(fontSize: 15)),
                                ))
                            .toList(),
                      );
                    },
                  ),
              ],
            ),
          );
        },
      ),
    );
  }

  /// Resumen de la semana en curso: horas frente a la jornada contratada y barras por día. Es un extra: si falla, no se muestra.
  Widget _tarjetaSemana(AppLocalizations t) {
    return FutureBuilder<ResumenSemanaFichaje>(
      future: _semana,
      builder: (context, snap) {
        final r = snap.data;
        if (r == null) return const SizedBox.shrink();
        final tema = Theme.of(context);
        final mayor = r.dias.fold<double>(8 * 3600, (m, d) => d.segundos > m ? d.segundos : m);
        final contratados = r.contratados;
        return Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(t.fichajeSemanaTitulo, style: tema.textTheme.titleMedium),
                const SizedBox(height: 6),
                Text(
                  contratados == null ? formatoHoras(r.segundos) : t.fichajeSemanaDeContratadas(formatoHoras(r.segundos), formatoHoras(contratados)),
                  style: AppTheme.cifra(fontSize: 20),
                ),
                if (r.porcentaje != null) ...[
                  const SizedBox(height: 8),
                  LinearProgressIndicator(value: r.porcentaje! / 100, minHeight: 8, borderRadius: BorderRadius.circular(4)),
                  const SizedBox(height: 6),
                  Text(
                    r.excedida ? t.fichajeSemanaExcedida(formatoHoras(r.diferencia!)) : t.fichajeSemanaRestan(formatoHoras(-r.diferencia!)),
                    style: tema.textTheme.bodySmall,
                  ),
                ] else ...[
                  const SizedBox(height: 6),
                  Text(t.fichajeSemanaSinJornada, style: tema.textTheme.bodySmall),
                ],
                const SizedBox(height: 12),
                SizedBox(
                  height: 56,
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      for (final d in r.dias)
                        Expanded(
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 3),
                            child: Container(
                              height: 4 + 52 * (d.segundos / mayor).clamp(0.0, 1.0),
                              decoration: BoxDecoration(
                                color: d.hoy ? tema.colorScheme.primary : tema.colorScheme.primary.withValues(alpha: 0.35),
                                borderRadius: BorderRadius.circular(3),
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Color _colorAviso(BuildContext context) =>
      Theme.of(context).brightness == Brightness.dark ? BrandColors.warningDark : BrandColors.warningLight;

  Color _colorPeligro(BuildContext context) =>
      Theme.of(context).brightness == Brightness.dark ? BrandColors.dangerDark : BrandColors.dangerLight;

  Widget _pillEstado(String estado, AppLocalizations t) {
    final (texto, tono) = switch (estado) {
      'dentro' => (t.fichajeEstadoDentro, BadgeTono.exito),
      'en_pausa' => (t.fichajeEstadoPausa, BadgeTono.aviso),
      _ => (t.fichajeEstadoFuera, BadgeTono.neutro),
    };
    return StatusBadge(texto: texto, tono: tono);
  }

  Widget _botonFichar(String texto, Color color, bool habilitado, VoidCallback onPressed) {
    return SizedBox(
      width: 150,
      height: 56,
      child: FilledButton(
        style: FilledButton.styleFrom(backgroundColor: habilitado ? color : null),
        onPressed: (habilitado && !_marcando) ? onPressed : null,
        child: Text(texto),
      ),
    );
  }
}
