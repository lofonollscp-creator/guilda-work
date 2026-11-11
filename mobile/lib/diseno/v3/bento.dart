import 'package:flutter/material.dart';

import 'tokens_v3.dart';

/// Lo que se hunde un poco al pulsarlo (un 3 %) y vibra suave: la respuesta táctil de la v3. Mantiene la onda, el foco de teclado y la semántica de un
/// `InkWell`. Sin [alPulsar] no hace nada (es solo un contenedor).
class Pulsable extends StatefulWidget {
  final Widget child;
  final VoidCallback? alPulsar;
  final VoidCallback? alMantener;
  final BorderRadius radio;
  final bool vibrar;
  final String? etiqueta;
  const Pulsable({super.key, required this.child, this.alPulsar, this.alMantener, this.radio = const BorderRadius.all(Radius.circular(V3.radioM)), this.vibrar = true, this.etiqueta});

  @override
  State<Pulsable> createState() => _PulsableState();
}

class _PulsableState extends State<Pulsable> {
  bool _abajo = false;

  @override
  Widget build(BuildContext context) {
    if (widget.alPulsar == null && widget.alMantener == null) return widget.child;
    final quieto = reducirMovimiento(context);
    return Semantics(
      button: true,
      label: widget.etiqueta,
      container: widget.etiqueta != null,
      child: AnimatedScale(
        scale: _abajo && !quieto ? 0.97 : 1,
        duration: V3.durCorta,
        curve: V3.curvaEntrada,
        child: Material(
          type: MaterialType.transparency,
          child: InkWell(
            borderRadius: widget.radio,
            onHighlightChanged: (v) => setState(() => _abajo = v),
            onTap: widget.alPulsar == null
                ? null
                : () {
                    if (widget.vibrar) Haptica.toque();
                    widget.alPulsar!();
                  },
            onLongPress: widget.alMantener,
            child: widget.child,
          ),
        ),
      ),
    );
  }
}

/// Cómo se tiñe una [TarjetaBento].
enum TonoBento {
  /// Una superficie más del tema.
  neutro,

  /// Un velo del acento de marca: lo importante («Lo siguiente», fichaje en curso).
  acento,

  /// Un velo del violeta de la IA: lo que viene del asistente (resumen, propuestas).
  ia,
}

/// Una tarjeta del mosaico de «Hoy» y de las pantallas nuevas: radio grande, filo fino, relleno por capas (sin sombra) y, si se pulsa, respuesta táctil.
/// El texto de dentro siempre va sobre el color de superficie del tema, así que mantiene el contraste AA en los dos temas.
class TarjetaBento extends StatelessWidget {
  final Widget child;
  final TonoBento tono;
  final VoidCallback? alPulsar;
  final EdgeInsetsGeometry padding;
  final String? etiqueta;
  final double? alto;
  const TarjetaBento({super.key, required this.child, this.tono = TonoBento.neutro, this.alPulsar, this.padding = const EdgeInsets.all(16), this.etiqueta, this.alto});

  /// El color de fondo (sin el destello) de cada tono: lo que hay detrás del texto, para comprobar el contraste.
  static Color fondoDe(PaletaV3 p, TonoBento tono) => switch (tono) {
        TonoBento.neutro => p.superficie,
        TonoBento.acento => Color.alphaBlend(p.acento.withValues(alpha: p.oscuro ? 0.13 : 0.12), p.superficie),
        TonoBento.ia => Color.alphaBlend(p.ia.acento.withValues(alpha: p.oscuro ? 0.20 : 0.10), p.superficie),
      };

  @override
  Widget build(BuildContext context) {
    final p = PaletaV3.de(context);
    final radio = BorderRadius.circular(V3.radioM);
    final filo = switch (tono) {
      TonoBento.neutro => p.filo,
      TonoBento.acento => p.acento.withValues(alpha: p.oscuro ? 0.45 : 0.55),
      TonoBento.ia => p.ia.borde,
    };
    final tarjeta = Container(
      height: alto,
      padding: padding,
      decoration: BoxDecoration(
        borderRadius: radio,
        border: Border.all(color: filo),
        color: fondoDe(p, tono),
        // Un destello arriba a la izquierda da volumen sin sombra.
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Colors.white.withValues(alpha: p.oscuro ? 0.04 : 0.35), Colors.white.withValues(alpha: 0)],
        ),
      ),
      child: child,
    );
    return Pulsable(alPulsar: alPulsar, radio: radio, etiqueta: etiqueta, child: tarjeta);
  }
}
