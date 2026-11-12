import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';

import 'tokens_v3.dart';

/// La cabecera de las pantallas principales: un **título grande** que se pliega a la barra normal al hacer scroll, con vidrio detrás para que lo que pasa
/// por debajo no estorbe. Es un sliver: va dentro de un `CustomScrollView`.
class CabeceraGrande extends StatelessWidget {
  final String titulo;
  final String? subtitulo;
  final List<Widget> acciones;
  final Widget? leading;
  const CabeceraGrande({super.key, required this.titulo, this.subtitulo, this.acciones = const [], this.leading});

  static const _alto = 132.0;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final p = PaletaV3.de(context);
    return SliverAppBar(
      pinned: true,
      expandedHeight: _alto,
      backgroundColor: p.fondo.withValues(alpha: 0.72),
      surfaceTintColor: Colors.transparent,
      scrolledUnderElevation: 0,
      elevation: 0,
      leading: leading,
      actions: acciones,
      flexibleSpace: ClipRect(
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 18, sigmaY: 18),
          child: FlexibleSpaceBar(
            expandedTitleScale: 1.45,
            titlePadding: const EdgeInsetsDirectional.only(start: 16, bottom: 14),
            // Con la letra del sistema muy grande el título no cabe en la cabecera plegada: se limita su escala (el resto de la pantalla sigue a la del sistema).
            title: MediaQuery.withClampedTextScaling(maxScaleFactor: 1.2, child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(titulo, style: tema.textTheme.titleLarge?.copyWith(fontSize: 20, letterSpacing: -0.4)),
              if (subtitulo != null) Text(subtitulo!, style: tema.textTheme.labelSmall?.copyWith(color: p.textoSuave)),
            ])),
          ),
        ),
      ),
    );
  }
}

/// Envuelve un bloque de carga con un brillo que lo recorre (como un esqueleto vivo). Quieto con «reducir movimiento».
class Brillo extends StatefulWidget {
  final Widget child;
  const Brillo({super.key, required this.child});

  @override
  State<Brillo> createState() => _BrilloState();
}

class _BrilloState extends State<Brillo> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1500));

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (reducirMovimiento(context)) {
      _c.stop();
      _c.value = 0.5;
    } else if (!_c.isAnimating) {
      _c.repeat();
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = PaletaV3.de(context);
    final luz = Colors.white.withValues(alpha: p.oscuro ? 0.10 : 0.70);
    return ExcludeSemantics(
      child: AnimatedBuilder(
        animation: _c,
        child: widget.child,
        builder: (_, hijo) => ShaderMask(
          blendMode: BlendMode.srcATop,
          shaderCallback: (r) {
            final x = -1.0 + 3.0 * _c.value;
            return LinearGradient(begin: Alignment(x - 1, 0), end: Alignment(x + 0.2, 0), colors: [Colors.transparent, luz, Colors.transparent]).createShader(r);
          },
          child: hijo,
        ),
      ),
    );
  }
}

/// Un rectángulo gris de relleno para esqueletos (con [Brillo] por encima).
class BloqueEsqueleto extends StatelessWidget {
  final double? ancho;
  final double alto;
  final double radio;
  const BloqueEsqueleto({super.key, this.ancho, this.alto = 14, this.radio = 8});

  @override
  Widget build(BuildContext context) {
    final p = PaletaV3.de(context);
    return Container(
      width: ancho,
      height: alto,
      decoration: BoxDecoration(color: p.superficieAlta, borderRadius: BorderRadius.circular(radio), border: Border.all(color: p.filo)),
    );
  }
}
