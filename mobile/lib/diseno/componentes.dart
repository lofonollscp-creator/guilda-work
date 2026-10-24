import 'package:flutter/material.dart';

import '../api/errores.dart';
import '../dominio/tarea.dart';
import '../l10n/app_localizations.dart';
import '../theme/brand_colors.dart';
import 'estados.dart';

/// Lo que la persona lee cuando algo falla, según la **categoría** del error y no según el texto técnico (catálogo A.16 del plan de UX).
/// Un error de validación enseña el mensaje del servidor (dice qué campo está mal); el resto, un texto claro y una salida.
String mensajeDeError(AppLocalizations t, Object error) {
  if (error is! ApiException) return t.errDesconocido;
  return switch (error.categoria) {
    CategoriaError.red => t.errRed,
    CategoriaError.autenticacion => t.errAutenticacion,
    CategoriaError.prohibido => t.errProhibido,
    CategoriaError.noEncontrado => t.errNoEncontrado,
    CategoriaError.bloqueado => t.errBloqueado,
    CategoriaError.conflicto => t.errConflicto,
    CategoriaError.validacion => error.mensaje,
    CategoriaError.limite => t.errLimite,
    CategoriaError.actualizar => t.errActualizar,
    CategoriaError.servidor => t.errServidor,
    CategoriaError.desconocido => error.mensaje.isEmpty ? t.errDesconocido : error.mensaje,
  };
}

/// Una pantalla (o zona) sin contenido: icono, frase en lenguaje llano y, si hay, **una** acción.
class EstadoVacio extends StatelessWidget {
  final IconData icono;
  final String titulo;
  final String? detalle;
  final String? accion;
  final VoidCallback? alAccionar;
  const EstadoVacio({super.key, required this.icono, required this.titulo, this.detalle, this.accion, this.alAccionar});

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ExcludeSemantics(child: Icon(icono, size: 56, color: tema.colorScheme.onSurfaceVariant)),
          const SizedBox(height: 12),
          Text(titulo, style: tema.textTheme.titleMedium, textAlign: TextAlign.center),
          if (detalle != null) ...[const SizedBox(height: 4), Text(detalle!, style: tema.textTheme.bodyMedium?.copyWith(color: tema.colorScheme.onSurfaceVariant), textAlign: TextAlign.center)],
          if (accion != null) ...[const SizedBox(height: 16), FilledButton(onPressed: alAccionar, child: Text(accion!))],
        ]),
      ),
    );
  }
}

/// Un error con su salida: el texto sale de [mensajeDeError], y si el servidor dio un código de soporte (`request_id`) se enseña pequeño
/// para poder darlo a soporte. Con [alReintentar] ofrece «Reintentar» (nunca un callejón sin salida).
class EstadoError extends StatelessWidget {
  final Object error;
  final VoidCallback? alReintentar;
  const EstadoError({super.key, required this.error, this.alReintentar});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final ref = error is ApiException ? (error as ApiException).requestId : null;
    final sinRed = error is ApiException && (error as ApiException).esDeConexion;
    return Semantics(
      liveRegion: true,
      child: EstadoVacio(
        icono: sinRed ? Icons.cloud_off_outlined : Icons.error_outline,
        titulo: mensajeDeError(t, error),
        detalle: ref == null ? null : t.errReferencia(ref),
        accion: alReintentar == null ? null : t.estadoVacioReintentar,
        alAccionar: alReintentar,
      ),
    );
  }
}

/// Marcador de posición mientras carga una lista: barras que laten suavemente (quietas si la persona ha pedido «reducir movimiento»).
class EsqueletoLista extends StatefulWidget {
  final int filas;
  const EsqueletoLista({super.key, this.filas = 6});

  @override
  State<EsqueletoLista> createState() => _EsqueletoListaState();
}

class _EsqueletoListaState extends State<EsqueletoLista> with SingleTickerProviderStateMixin {
  late final AnimationController _latido = AnimationController(vsync: this, duration: const Duration(milliseconds: 900));

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (MediaQuery.disableAnimationsOf(context)) {
      _latido.stop();
      _latido.value = 0.5;
    } else if (!_latido.isAnimating) {
      _latido.repeat(reverse: true);
    }
  }

  @override
  void dispose() {
    _latido.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final base = Theme.of(context).colorScheme.outline;
    return ExcludeSemantics(
      child: AnimatedBuilder(
        animation: _latido,
        builder: (context, _) {
          final color = base.withValues(alpha: 0.18 + 0.2 * _latido.value);
          Widget barra(double ancho, double alto) => Container(width: ancho, height: alto, decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(6)));
          return ListView(
            physics: const NeverScrollableScrollPhysics(),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            children: [
              for (var i = 0; i < widget.filas; i++)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  child: Row(children: [
                    Container(width: 24, height: 24, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
                    const SizedBox(width: 16),
                    Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [barra(double.infinity, 14), const SizedBox(height: 8), barra(140 + (i % 3) * 30, 11)])),
                  ]),
                ),
            ],
          );
        },
      ),
    );
  }
}

enum TipoBanner { info, aviso, error, sinConexion }

/// Una franja de aviso (info, aviso, error o sin conexión), con acción opcional. Siempre icono + texto: el color nunca es lo único que informa.
class BannerEstado extends StatelessWidget {
  final TipoBanner tipo;
  final String texto;
  final String? accion;
  final VoidCallback? alAccionar;
  const BannerEstado({super.key, required this.tipo, required this.texto, this.accion, this.alAccionar});

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final oscuro = tema.brightness == Brightness.dark;
    final (icono, fondo) = switch (tipo) {
      TipoBanner.info => (Icons.info_outline, tema.colorScheme.surfaceContainerHighest),
      TipoBanner.aviso => (Icons.warning_amber_outlined, (oscuro ? BrandColors.warningDark : BrandColors.warningLight).withValues(alpha: 0.18)),
      TipoBanner.error => (Icons.error_outline, (oscuro ? BrandColors.dangerDark : BrandColors.dangerLight).withValues(alpha: 0.18)),
      TipoBanner.sinConexion => (Icons.cloud_off_outlined, tema.colorScheme.surfaceContainerHighest),
    };
    return Semantics(
      liveRegion: true,
      container: true,
      child: Container(
        width: double.infinity,
        color: fondo,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Row(children: [
          ExcludeSemantics(child: Icon(icono, size: 20)),
          const SizedBox(width: 10),
          Expanded(child: Text(texto, style: tema.textTheme.bodyMedium)),
          if (accion != null) TextButton(onPressed: alAccionar, child: Text(accion!)),
        ]),
      ),
    );
  }
}

/// El estado de una tarea: **icono + etiqueta + color** (nunca solo color), con el tono AA de su tema.
class ChipEstado extends StatelessWidget {
  final EstadoTarea estado;
  final String etiqueta;
  final bool vencida;
  const ChipEstado({super.key, required this.estado, required this.etiqueta, this.vencida = false});

  @override
  Widget build(BuildContext context) {
    final b = Theme.of(context).brightness;
    final a = vencida ? aspectoVencida : aspectoDe(estado);
    final color = a.color(b);
    return Row(mainAxisSize: MainAxisSize.min, children: [
      ExcludeSemantics(child: Icon(a.icono, size: 16, color: color)),
      const SizedBox(width: 4),
      Flexible(child: Text(etiqueta, style: Theme.of(context).textTheme.labelMedium?.copyWith(color: color), overflow: TextOverflow.ellipsis)),
    ]);
  }
}
