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

/// Un dato pequeño con forma de píldora (icono + texto) para las filas y tarjetas: mismo tamaño y mismo aire en todas las pantallas. El tono por defecto es neutro; con
/// [color] se tiñe (vencida en rojo, prioridad alta en ámbar…). Siempre lleva texto: el color nunca es lo único que informa.
class Pildora extends StatelessWidget {
  final IconData? icono;
  final String texto;
  final Color? color;
  final bool fuerte;

  /// Si se pasa, la píldora es un botón (lleva una flechita) —p. ej. el estado de la ficha, que se toca para cambiarlo.
  final VoidCallback? alPulsar;
  const Pildora({super.key, this.icono, required this.texto, this.color, this.fuerte = false, this.alPulsar});

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final c = color ?? tema.colorScheme.onSurfaceVariant;
    final grande = alPulsar != null;
    final pildora = Container(
      padding: EdgeInsets.symmetric(horizontal: grande ? 12 : 8, vertical: grande ? 8 : 3),
      constraints: BoxConstraints(minHeight: grande ? 40 : 0),
      decoration: BoxDecoration(color: c.withValues(alpha: color == null ? 0.10 : 0.14), borderRadius: BorderRadius.circular(999)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        if (icono != null) ...[ExcludeSemantics(child: Icon(icono, size: grande ? 18 : 14, color: c)), SizedBox(width: grande ? 6 : 4)],
        Flexible(child: Text(texto, style: (grande ? tema.textTheme.labelLarge : tema.textTheme.labelMedium)?.copyWith(color: c, fontWeight: fuerte ? FontWeight.w700 : null), maxLines: 1, overflow: TextOverflow.ellipsis)),
        if (grande) ExcludeSemantics(child: Icon(Icons.arrow_drop_down, size: 20, color: c)),
      ]),
    );
    if (!grande) return pildora;
    return Semantics(button: true, child: InkWell(borderRadius: BorderRadius.circular(999), onTap: alPulsar, child: pildora));
  }
}

/// Pestañas de texto con el subrayado del acento en la activa (como el submenú de la web): ligeras, sin cajas, y se deslizan si no caben.
class PestanasSubnav<T> extends StatelessWidget {
  final List<(T, String, IconData)> opciones;
  final T actual;
  final void Function(T) alElegir;
  const PestanasSubnav({super.key, required this.opciones, required this.actual, required this.alElegir});

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Container(
      decoration: BoxDecoration(border: Border(bottom: BorderSide(color: tema.colorScheme.outlineVariant))),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 8),
        child: Row(children: [
          for (final (valor, etiqueta, icono) in opciones)
            Semantics(
              button: true,
              selected: valor == actual,
              child: InkWell(
                onTap: () => alElegir(valor),
                child: Container(
                  constraints: const BoxConstraints(minHeight: 48),
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  decoration: BoxDecoration(border: Border(bottom: BorderSide(color: valor == actual ? tema.colorScheme.primary : Colors.transparent, width: 3))),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    ExcludeSemantics(child: Icon(icono, size: 18, color: valor == actual ? tema.colorScheme.onSurface : tema.colorScheme.onSurfaceVariant)),
                    const SizedBox(width: 6),
                    Text(etiqueta, style: tema.textTheme.labelLarge?.copyWith(color: valor == actual ? tema.colorScheme.onSurface : tema.colorScheme.onSurfaceVariant)),
                  ]),
                ),
              ),
            ),
        ]),
      ),
    );
  }
}

/// Un bloque de la ficha: título y contenido dentro de una tarjeta, para que la ficha no sea una columna larga de texto suelto.
class BloqueFicha extends StatelessWidget {
  final String? titulo;
  final Widget hijo;
  final Widget? accion;
  const BloqueFicha({super.key, this.titulo, required this.hijo, this.accion});

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Material(
        color: tema.colorScheme.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: BorderSide(color: tema.colorScheme.outlineVariant)),
        clipBehavior: Clip.antiAlias,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (titulo != null) Row(children: [Expanded(child: Text(titulo!, style: tema.textTheme.titleSmall)), ?accion]),
            if (titulo != null) const SizedBox(height: 4),
            hijo,
          ]),
        ),
      ),
    );
  }
}

/// Un botón con forma de píldora (icono + texto), para barras de filtros: con `activo` se tiñe del acento.
class PildoraBoton extends StatelessWidget {
  final IconData icono;
  final String texto;
  final bool activo;
  final VoidCallback alPulsar;
  const PildoraBoton({super.key, required this.icono, required this.texto, this.activo = false, required this.alPulsar});

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final fondo = activo ? Color.alphaBlend(tema.colorScheme.primary.withValues(alpha: tema.brightness == Brightness.dark ? 0.22 : 0.30), tema.colorScheme.surface) : tema.colorScheme.surface;
    return Semantics(
      button: true,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: alPulsar,
        child: Container(
          constraints: const BoxConstraints(minHeight: 40),
          padding: const EdgeInsets.symmetric(horizontal: 14),
          decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(999), border: Border.all(color: activo ? tema.colorScheme.primary : tema.colorScheme.outlineVariant, width: activo ? 1.5 : 1)),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(icono, size: 18, color: tema.colorScheme.onSurfaceVariant),
            const SizedBox(width: 6),
            Text(texto, style: tema.textTheme.labelLarge?.copyWith(color: tema.colorScheme.onSurface)),
          ]),
        ),
      ),
    );
  }
}

/// Un menú desplegable con forma de píldora: enseña la elección actual y abre la lista de opciones.
class PildoraMenu<T> extends StatelessWidget {
  final IconData icono;
  final String texto;
  final bool activo;
  final List<(T, String)> opciones;
  final T seleccionado;
  final void Function(T) alElegir;
  const PildoraMenu({super.key, required this.icono, required this.texto, required this.activo, required this.opciones, required this.seleccionado, required this.alElegir});

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final fondo = activo ? Color.alphaBlend(tema.colorScheme.primary.withValues(alpha: tema.brightness == Brightness.dark ? 0.22 : 0.30), tema.colorScheme.surface) : tema.colorScheme.surface;
    return PopupMenuButton<T>(
      tooltip: texto,
      position: PopupMenuPosition.under,
      onSelected: alElegir,
      itemBuilder: (_) => [for (final (valor, etiqueta) in opciones) CheckedPopupMenuItem<T>(value: valor, checked: valor == seleccionado, child: Text(etiqueta))],
      child: Container(
        constraints: const BoxConstraints(minHeight: 40),
        padding: const EdgeInsets.only(left: 14, right: 8),
        decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(999), border: Border.all(color: activo ? tema.colorScheme.primary : tema.colorScheme.outlineVariant, width: activo ? 1.5 : 1)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(icono, size: 18, color: tema.colorScheme.onSurfaceVariant),
          const SizedBox(width: 6),
          Text(texto, style: tema.textTheme.labelLarge?.copyWith(color: tema.colorScheme.onSurface)),
          Icon(Icons.arrow_drop_down, color: tema.colorScheme.onSurfaceVariant),
        ]),
      ),
    );
  }
}


/// Un grupo de filas (accesos o ajustes) en una tarjeta, con un filo entre ellas.
class GrupoAjustes extends StatelessWidget {
  final List<Widget> children;
  const GrupoAjustes({super.key, required this.children});

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Material(
        color: tema.colorScheme.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: BorderSide(color: tema.colorScheme.outlineVariant)),
        clipBehavior: Clip.antiAlias,
        child: Column(children: [
          for (var i = 0; i < children.length; i++) ...[if (i > 0) Divider(height: 1, indent: 64, color: tema.colorScheme.outlineVariant), children[i]],
        ]),
      ),
    );
  }
}

/// Una fila de «Más» o de Ajustes: su icono en un círculo con el tinte del acento, el nombre y, a la derecha, una flecha.
class FilaAjuste extends StatelessWidget {
  final IconData icono;
  final String titulo;
  final String? subtitulo;
  final Widget? final_;

  /// Una acción que cierra o borra algo (cerrar sesión): se pinta con el tono de peligro.
  final bool peligro;
  final VoidCallback alPulsar;
  const FilaAjuste({super.key, required this.icono, required this.titulo, this.subtitulo, this.final_, this.peligro = false, required this.alPulsar});

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return ListTile(
      minTileHeight: 56,
      leading: Container(
        width: 40,
        height: 40,
        decoration: BoxDecoration(color: (peligro ? tema.colorScheme.error : tema.colorScheme.primary).withValues(alpha: tema.brightness == Brightness.dark ? 0.22 : 0.30), shape: BoxShape.circle),
        child: ExcludeSemantics(child: Icon(icono, size: 22, color: peligro ? tema.colorScheme.error : tema.colorScheme.onSurface)),
      ),
      title: Text(titulo, style: tema.textTheme.titleSmall?.copyWith(color: peligro ? tema.colorScheme.error : null)),
      subtitle: subtitulo == null ? null : Text(subtitulo!),
      trailing: final_,
      onTap: alPulsar,
    );
  }
}
