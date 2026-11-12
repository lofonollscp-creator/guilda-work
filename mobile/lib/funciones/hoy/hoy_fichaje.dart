import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/errores.dart';
import '../../datos/local/cola_escritura.dart' show ColaLlena;
import '../../diseno/componentes.dart' show mensajeDeError;
import '../../diseno/v3/v3.dart';
import '../../l10n/app_localizations.dart';
import '../../models/models.dart';
import '../../nucleo/rutas.dart' show rutaFichaje;
import '../../nucleo/servicios.dart';
import '../../nucleo/sesion.dart';
import '../../theme/brand_colors.dart';
import '../fichaje/fichaje_acciones.dart';

/// Cómo está tu jornada: `dentro`, `en_pausa` o `fuera`; desde qué hora (de la última marca de hoy) y si faltan datos para poder fichar.
class EstadoFichajeHoy {
  final String estado;
  final bool datosCompletos;
  final String? desde;
  const EstadoFichajeHoy(this.estado, this.datosCompletos, [this.desde]);
}

const _estadoTrasMarcar = {'entrada': 'dentro', 'pausa_inicio': 'en_pausa', 'pausa_fin': 'dentro', 'salida': 'fuera'};

/// El fichaje de hoy para la tarjeta de Hoy. Se rehace al cambiar de despacho. Si no se puede leer (sin red, sin permiso) no rompe Hoy: la tarjeta se apaga.
class FichajeHoyControlador extends AsyncNotifier<EstadoFichajeHoy> {
  @override
  Future<EstadoFichajeHoy> build() {
    ref.watch(estadoSesionProvider.select((e) => e.despacho));
    return _pedir();
  }

  Future<EstadoFichajeHoy> _pedir() async {
    final api = ref.read(serviciosProvider).api;
    final (estado, completos) = await api.obtenerEstadoFichaje();
    String? desde;
    if (completos) {
      final hoy = DateTime.now().toIso8601String().substring(0, 10);
      final List<FichajeEvento> eventos = await api.listarMisFichajes(desde: hoy, hasta: hoy);
      final marca = eventos.isEmpty ? '' : eventos.last.marcaTiempo;
      if (marca.length >= 16) desde = marca.substring(11, 16);
    }
    return EstadoFichajeHoy(estado, completos, desde);
  }

  Future<void> refrescar() async {
    try {
      state = AsyncData(await _pedir());
    } catch (e, st) {
      state = state.value == null ? AsyncError(e, st) : state;
    }
  }

  /// Ficha ([tipo]: `entrada`, `pausa_inicio`, `pausa_fin` o `salida`). Sin red se encola y el estado se adelanta; con red se vuelve a leer.
  Future<ResultadoMarca> marcar(String tipo) async {
    final usuario = ref.read(estadoSesionProvider).usuario;
    final (lat, lon) = await ubicacionOpcionalFichaje(activa: usuario?.fichajeGeolocalizacion ?? false);
    final r = await ref.read(accionesFichajeProvider).marcar(tipo, latitud: lat, longitud: lon);
    if (r.encolada) {
      final hora = DateTime.now();
      state = AsyncData(EstadoFichajeHoy(_estadoTrasMarcar[tipo]!, true, '${hora.hour.toString().padLeft(2, '0')}:${hora.minute.toString().padLeft(2, '0')}'));
      return ResultadoMarca.encolada;
    }
    await refrescar();
    return ResultadoMarca.enviada;
  }
}

enum ResultadoMarca { enviada, encolada }

final fichajeHoyProvider = AsyncNotifierProvider<FichajeHoyControlador, EstadoFichajeHoy>(FichajeHoyControlador.new);

/// La tarjeta de fichaje de Hoy: tu estado y el botón que toca ahora (entrada, o salida; y pausa), sin cambiar de pantalla.
/// Tocar la tarjeta abre el Fichaje completo (historial, semana, datos).
class TarjetaFichajeHoy extends ConsumerStatefulWidget {
  const TarjetaFichajeHoy({super.key});

  @override
  ConsumerState<TarjetaFichajeHoy> createState() => _TarjetaFichajeHoyState();
}

class _TarjetaFichajeHoyState extends ConsumerState<TarjetaFichajeHoy> {
  bool _marcando = false;

  Future<void> _marcar(String tipo) async {
    final t = AppLocalizations.of(context);
    final mensajero = ScaffoldMessenger.of(context);
    setState(() => _marcando = true);
    try {
      final r = await ref.read(fichajeHoyProvider.notifier).marcar(tipo);
      Haptica.hecho();
      if (r == ResultadoMarca.encolada) mensajero.showSnackBar(SnackBar(content: Text(t.fichajeSinConexionNota)));
    } on ColaLlena {
      mensajero.showSnackBar(SnackBar(content: Text(t.colaLlena)));
    } on ApiException catch (e) {
      mensajero.showSnackBar(SnackBar(content: Text(mensajeDeError(t, e))));
    } finally {
      if (mounted) setState(() => _marcando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final f = ref.watch(fichajeHoyProvider).value;
    if (f == null) return const SizedBox.shrink(); // cargando o sin poder leerlo: Hoy sigue sin la tarjeta
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final p = PaletaV3.de(context);
    final oscuro = p.oscuro;
    final (titulo, icono, color) = switch (f.estado) {
      'dentro' => (t.fichajeEstadoDentro, Icons.work_outline, BrandColors.success),
      'en_pausa' => (t.fichajeEstadoPausa, Icons.free_breakfast_outlined, oscuro ? BrandColors.warningDark : BrandColors.warningLight),
      _ => (t.fichajeEstadoFuera, Icons.logout, p.textoSuave),
    };
    final detalle = !f.datosCompletos
        ? t.fichajeDatosIncompletos
        : switch (f.estado) {
            'dentro' => f.desde == null ? '' : t.fichajeDesdeLas(f.desde!),
            'en_pausa' => f.desde == null ? '' : t.fichajePausaDesdeLas(f.desde!),
            _ => f.desde == null ? t.fichajeAunNoHoy : t.fichajeSalisteALas(f.desde!),
          };
    final peligro = oscuro ? BrandColors.dangerDark : BrandColors.dangerLight;
    final aviso = oscuro ? BrandColors.warningDark : BrandColors.warningLight;
    Widget boton(String texto, IconData i, Color c, String tipo) => Expanded(
          child: SizedBox(
            height: 52,
            child: FilledButton.icon(
              style: FilledButton.styleFrom(backgroundColor: c, foregroundColor: BrandColors.onAccent),
              onPressed: _marcando ? null : () => _marcar(tipo),
              icon: Icon(i),
              label: Text(texto, style: tema.textTheme.titleSmall?.copyWith(color: BrandColors.onAccent)),
            ),
          ),
        );
    final botones = switch (f.estado) {
      'dentro' => [boton(t.fichajeIniciarPausaBoton, Icons.pause_circle_outline, aviso, 'pausa_inicio'), boton(t.fichajeSalidaBoton, Icons.logout, peligro, 'salida')],
      'en_pausa' => [boton(t.fichajeFinPausaBoton, Icons.play_circle_outline, BrandColors.success, 'pausa_fin'), boton(t.fichajeSalidaBoton, Icons.logout, peligro, 'salida')],
      _ => [boton(t.fichajeEntradaBoton, Icons.login, BrandColors.success, 'entrada')],
    };
    return TarjetaBento(
      alPulsar: () => GoRouter.of(context).go(rutaFichaje),
      etiqueta: '${t.navFichaje}: $titulo',
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        ExcludeSemantics(
          child: Row(children: [
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(color: color.withValues(alpha: 0.16), shape: BoxShape.circle),
              child: Icon(icono, size: 24, color: color),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(titulo, style: tema.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
                if (detalle.isNotEmpty) Text(detalle, style: tema.textTheme.bodySmall?.copyWith(color: p.textoSuave), maxLines: 2, overflow: TextOverflow.ellipsis),
              ]),
            ),
          ]),
        ),
        // Sin los datos de fichaje no se puede marcar: el botón lleva a completarlos (en el Fichaje completo).
        if (f.datosCompletos) ...[const SizedBox(height: 14), Row(children: [for (var i = 0; i < botones.length; i++) ...[if (i > 0) const SizedBox(width: 10), botones[i]]])],
      ]),
    );
  }
}
