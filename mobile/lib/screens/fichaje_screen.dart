import 'package:flutter/material.dart';

import '../diseno/componentes.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:intl/intl.dart';

import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../datos/cola.dart';
import '../datos/local/cola_escritura.dart' show ColaLlena;
import '../funciones/fichaje/fichaje_acciones.dart';
import '../funciones/pendientes/pendientes_sheet.dart';
import '../theme/app_theme.dart';
import '../theme/brand_colors.dart';
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
      if (mounted) setState(() => _error = mensajeDeError(AppLocalizations.of(context), e));
    } catch (e) {
      if (mounted) setState(() => _error = mensajeDeError(AppLocalizations.of(context), e));
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
            return Center(child: Text(mensajeDeError(t, snapshot.error!)));
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
                FutureBuilder<List<FichajeEvento>>(
                  future: _hoy,
                  builder: (context, snap) => _tarjetaEstado(estado, snap.data ?? const [], t),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  BannerEstado(tipo: TipoBanner.error, texto: _error!),
                ],
                const SizedBox(height: 16),
                _acciones(estado, t),
                const SizedBox(height: 16),
                if (_semana != null) _tarjetaSemana(t),
                const SizedBox(height: 16),
                _tarjetaHoy(t),
              ],
            ),
          );
        },
      ),
    );
  }

  /// El estado de ahora, grande, y desde cuándo (de la última marca de hoy).
  Widget _tarjetaEstado(String estado, List<FichajeEvento> eventos, AppLocalizations t) {
    final tema = Theme.of(context);
    final oscuro = tema.brightness == Brightness.dark;
    final (titulo, icono, color) = switch (estado) {
      'dentro' => (t.fichajeEstadoDentro, Icons.work_outline, BrandColors.success),
      'en_pausa' => (t.fichajeEstadoPausa, Icons.free_breakfast_outlined, oscuro ? BrandColors.warningDark : BrandColors.warningLight),
      _ => (t.fichajeEstadoFuera, Icons.logout, tema.colorScheme.onSurfaceVariant),
    };
    final ultima = eventos.isEmpty ? null : eventos.last;
    final hora = ultima == null || ultima.marcaTiempo.length < 16 ? '' : ultima.marcaTiempo.substring(11, 16);
    final detalle = switch (estado) {
      'dentro' => hora.isEmpty ? '' : t.fichajeDesdeLas(hora),
      'en_pausa' => hora.isEmpty ? '' : t.fichajePausaDesdeLas(hora),
      _ => ultima == null ? t.fichajeAunNoHoy : t.fichajeSalisteALas(hora),
    };
    final pendientes = ref.watch(numFichajesPendientesProvider);
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Row(children: [
          Container(
            width: 64,
            height: 64,
            decoration: BoxDecoration(color: color.withValues(alpha: 0.16), shape: BoxShape.circle),
            child: ExcludeSemantics(child: Icon(icono, size: 32, color: color)),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(titulo, style: tema.textTheme.headlineSmall),
              if (detalle.isNotEmpty) Text(detalle, style: tema.textTheme.bodyMedium?.copyWith(color: tema.colorScheme.onSurfaceVariant)),
              if (pendientes > 0) Padding(padding: const EdgeInsets.only(top: 6), child: Pildora(icono: Icons.cloud_upload_outlined, texto: t.fichajePendientesSinc(pendientes))),
            ]),
          ),
        ]),
      ),
    );
  }

  /// Solo las acciones que valen ahora (antes eran cuatro botones, dos de ellos apagados): entrada si estás fuera; pausa y salida si estás dentro;
  /// fin de pausa y salida si estás en pausa.
  Widget _acciones(String estado, AppLocalizations t) {
    final oscuro = Theme.of(context).brightness == Brightness.dark;
    final aviso = oscuro ? BrandColors.warningDark : BrandColors.warningLight;
    final peligro = oscuro ? BrandColors.dangerDark : BrandColors.dangerLight;
    Widget boton(String texto, IconData icono, Color color, String tipo) => Expanded(
          child: SizedBox(
            height: 64,
            child: FilledButton.icon(
              style: FilledButton.styleFrom(backgroundColor: color, foregroundColor: BrandColors.onAccent, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16))),
              onPressed: _marcando ? null : () => _marcar(tipo),
              icon: Icon(icono),
              label: Text(texto, style: Theme.of(context).textTheme.titleMedium?.copyWith(color: BrandColors.onAccent)),
            ),
          ),
        );
    final botones = switch (estado) {
      'dentro' => [boton(t.fichajeIniciarPausaBoton, Icons.pause_circle_outline, aviso, 'pausa_inicio'), boton(t.fichajeSalidaBoton, Icons.logout, peligro, 'salida')],
      'en_pausa' => [boton(t.fichajeFinPausaBoton, Icons.play_circle_outline, BrandColors.success, 'pausa_fin'), boton(t.fichajeSalidaBoton, Icons.logout, peligro, 'salida')],
      _ => [boton(t.fichajeEntradaBoton, Icons.login, BrandColors.success, 'entrada')],
    };
    return Row(children: [for (var i = 0; i < botones.length; i++) ...[if (i > 0) const SizedBox(width: 12), botones[i]]]);
  }

  /// Las marcas de hoy como una línea de tiempo.
  Widget _tarjetaHoy(AppLocalizations t) {
    final tema = Theme.of(context);
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t.fichajeHoyTitulo, style: tema.textTheme.titleMedium),
          const SizedBox(height: 8),
          if (_hoy == null)
            Text(t.fichajeSinFichajesHoy, style: tema.textTheme.bodySmall)
          else
            FutureBuilder<List<FichajeEvento>>(
              future: _hoy,
              builder: (context, snap) {
                if (snap.connectionState != ConnectionState.done) {
                  return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
                }
                final eventos = snap.data ?? [];
                if (eventos.isEmpty) return Text(t.fichajeSinFichajesHoy, style: tema.textTheme.bodySmall);
                final etiquetas = etiquetasFichaje(t);
                final oscuro = tema.brightness == Brightness.dark;
                Color colorDe(String tipo) => switch (tipo) {
                      'entrada' => BrandColors.success,
                      'salida' => oscuro ? BrandColors.dangerDark : BrandColors.dangerLight,
                      _ => oscuro ? BrandColors.warningDark : BrandColors.warningLight,
                    };
                return Column(children: [
                  for (var i = 0; i < eventos.length; i++)
                    IntrinsicHeight(
                      child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                        SizedBox(
                          width: 24,
                          child: Column(children: [
                            Container(width: 2, height: 6, color: i == 0 ? Colors.transparent : tema.colorScheme.outlineVariant),
                            Container(width: 12, height: 12, decoration: BoxDecoration(color: colorDe(eventos[i].tipo), shape: BoxShape.circle)),
                            Expanded(child: Container(width: 2, color: i == eventos.length - 1 ? Colors.transparent : tema.colorScheme.outlineVariant)),
                          ]),
                        ),
                        const SizedBox(width: 8),
                        Expanded(child: Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Text(etiquetas[eventos[i].tipo] ?? eventos[i].tipo, style: tema.textTheme.bodyLarge))),
                        Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Text(eventos[i].marcaTiempo.substring(11, 16), style: AppTheme.cifra(fontSize: 16))),
                      ]),
                    ),
                ]);
              },
            ),
        ]),
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
                  height: 84,
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      for (final d in r.dias)
                        Expanded(
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 4),
                            child: Column(mainAxisAlignment: MainAxisAlignment.end, children: [
                              Container(
                                height: 4 + 52 * (d.segundos / mayor).clamp(0.0, 1.0),
                                decoration: BoxDecoration(
                                  color: d.hoy ? tema.colorScheme.primary : tema.colorScheme.primary.withValues(alpha: 0.35),
                                  borderRadius: BorderRadius.circular(6),
                                ),
                              ),
                              const SizedBox(height: 6),
                              // La inicial del día debajo de cada barra; hoy, en negrita.
                              Text(
                                DateFormat.EEEEE(Localizations.localeOf(context).languageCode).format(DateTime.parse(d.fecha)).toUpperCase(),
                                style: tema.textTheme.labelSmall?.copyWith(fontWeight: d.hoy ? FontWeight.w800 : null, color: d.hoy ? tema.colorScheme.onSurface : null),
                              ),
                            ]),
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
}
