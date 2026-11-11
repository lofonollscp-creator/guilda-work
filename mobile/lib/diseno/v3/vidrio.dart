import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';

import 'tokens_v3.dart';

/// Una superficie de vidrio esmerilado: la superficie del tema algo transparente, con el fondo desenfocado detrás y un filo fino.
/// Se usa para lo que flota sobre el contenido (barra inferior, cabeceras al plegarse, hojas). Cae a una superficie **opaca** si la persona
/// ha pedido más contraste, si Ajustes apaga el vidrio (`V3.vidrioActivo`) o si se fuerza con [opaco]: el contenido se lee igual.
class Vidrio extends StatelessWidget {
  final Widget child;
  final BorderRadius? radio;
  final EdgeInsetsGeometry? padding;
  final double desenfoque;
  final bool opaco;
  final bool sombra;
  const Vidrio({super.key, required this.child, this.radio, this.padding, this.desenfoque = V3.desenfoque, this.opaco = false, this.sombra = false});

  @override
  Widget build(BuildContext context) {
    final p = PaletaV3.de(context);
    final r = radio ?? BorderRadius.circular(V3.radioM);
    return ValueListenableBuilder<bool>(
      valueListenable: V3.vidrioActivo,
      builder: (context, activo, _) {
        final conVidrio = activo && !opaco && !MediaQuery.highContrastOf(context);
        final cuerpo = DecoratedBox(
          decoration: BoxDecoration(
            color: conVidrio ? p.vidrio : p.superficieAlta,
            borderRadius: r,
            border: Border.all(color: p.filo),
          ),
          child: padding == null ? child : Padding(padding: padding!, child: child),
        );
        final recortado = ClipRRect(
          borderRadius: r,
          child: conVidrio ? BackdropFilter(filter: ImageFilter.blur(sigmaX: desenfoque, sigmaY: desenfoque), child: cuerpo) : cuerpo,
        );
        if (!sombra) return recortado;
        // La sombra va fuera del recorte (si no, se corta con el borde).
        return DecoratedBox(decoration: BoxDecoration(borderRadius: r, boxShadow: p.sombra), child: recortado);
      },
    );
  }
}
