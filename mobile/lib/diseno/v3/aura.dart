import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'tokens_v3.dart';

/// El aura del asistente: tres manchas de luz (violeta de la IA, acento de marca y un violeta claro) que derivan despacio tras [child].
/// Es decorativa (no la lee un lector de pantalla). Con «reducir movimiento» se queda quieta, en una posición agradable.
class Aura extends StatefulWidget {
  final Widget? child;

  /// 0 (invisible) a 1 (a tope). Como fondo de pantalla basta 0,25–0,4; tras el botón central, 0,8–1.
  final double intensidad;
  final BorderRadius? radio;
  final Duration periodo;
  const Aura({super.key, this.child, this.intensidad = 1, this.radio, this.periodo = const Duration(seconds: 16)});

  @override
  State<Aura> createState() => _AuraState();
}

class _AuraState extends State<Aura> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: widget.periodo);

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (reducirMovimiento(context)) {
      _c.stop();
      _c.value = 0.15;
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
    final colores = PaletaV3.de(context).aura;
    Widget fondo = ExcludeSemantics(
      child: RepaintBoundary(
        child: AnimatedBuilder(
          animation: _c,
          builder: (_, _) => CustomPaint(painter: _PintorAura(_c.value, colores, widget.intensidad), size: Size.infinite),
        ),
      ),
    );
    if (widget.radio != null) fondo = ClipRRect(borderRadius: widget.radio!, child: fondo);
    return Stack(fit: StackFit.passthrough, children: [
      Positioned.fill(child: fondo),
      if (widget.child != null) widget.child!,
    ]);
  }
}

class _PintorAura extends CustomPainter {
  final double t;
  final List<Color> colores;
  final double intensidad;
  _PintorAura(this.t, this.colores, this.intensidad);

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty || intensidad <= 0) return;
    final w = size.width, h = size.height;
    final lado = math.max(w, h * 0.8);
    final a = t * 2 * math.pi;

    void mancha(Offset centro, double radio, Color color, double fuerza) {
      final rect = Rect.fromCircle(center: centro, radius: radio);
      final pincel = Paint()
        ..shader = RadialGradient(colors: [color.withValues(alpha: (fuerza * intensidad).clamp(0, 1)), color.withValues(alpha: 0)]).createShader(rect);
      canvas.drawCircle(centro, radio, pincel);
    }

    mancha(Offset(w * (0.30 + 0.14 * math.cos(a)), h * (0.42 + 0.16 * math.sin(a))), lado * 0.60, colores[0], 0.55);
    mancha(Offset(w * (0.72 + 0.12 * math.sin(a + 1.3)), h * (0.58 + 0.14 * math.cos(a + 2.1))), lado * 0.52, colores[1], 0.40);
    mancha(Offset(w * (0.50 + 0.16 * math.cos(a * 2 + 0.7)), h * (0.30 + 0.10 * math.sin(a * 2))), lado * 0.40, colores[2], 0.35);
  }

  @override
  bool shouldRepaint(_PintorAura viejo) => viejo.t != t || viejo.intensidad != intensidad || viejo.colores != colores;
}

/// Qué está haciendo el asistente: el orbe lo cuenta sin texto.
enum EstadoOrbe { reposo, escuchando, pensando }

/// El orbe del asistente: una esfera con degradado violeta→acento. Respira en reposo, late con el volumen al escuchar y gira al pensar.
/// Decorativo: el estado lo dice el texto de al lado.
class OrbeIa extends StatefulWidget {
  final double tamano;
  final EstadoOrbe estado;
  const OrbeIa({super.key, this.tamano = 64, this.estado = EstadoOrbe.reposo});

  @override
  State<OrbeIa> createState() => _OrbeIaState();
}

class _OrbeIaState extends State<OrbeIa> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1800));

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (reducirMovimiento(context)) {
      _c.stop();
      _c.value = 0;
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
    final colores = PaletaV3.de(context).aura;
    return ExcludeSemantics(
      child: RepaintBoundary(
        child: AnimatedBuilder(
          animation: _c,
          builder: (_, _) => CustomPaint(size: Size.square(widget.tamano), painter: _PintorOrbe(_c.value, widget.estado, colores)),
        ),
      ),
    );
  }
}

class _PintorOrbe extends CustomPainter {
  final double t;
  final EstadoOrbe estado;
  final List<Color> colores;
  _PintorOrbe(this.t, this.estado, this.colores);

  @override
  void paint(Canvas canvas, Size size) {
    final centro = size.center(Offset.zero);
    final base = size.shortestSide / 2;
    final seno = math.sin(t * 2 * math.pi);
    final escala = switch (estado) {
      EstadoOrbe.reposo => 0.86 + 0.02 * seno,
      EstadoOrbe.escuchando => 0.80 + 0.07 * seno,
      EstadoOrbe.pensando => 0.84,
    };
    final radio = base * escala;

    // Halo: dos anillos que se abren y se apagan al escuchar.
    if (estado == EstadoOrbe.escuchando) {
      for (final desfase in [0.0, 0.5]) {
        final f = (t + desfase) % 1;
        canvas.drawCircle(centro, radio + (base - radio) * f * 1.0, Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2
          ..color = colores[0].withValues(alpha: 0.5 * (1 - f)));
      }
    }

    final rect = Rect.fromCircle(center: centro, radius: radio);
    // Una esfera de violeta con dos manchas de luz (acento y violeta claro) que se mueven por dentro: al pensar dan la vuelta, en reposo se quedan casi quietas.
    final giro = estado == EstadoOrbe.pensando ? t * 2 * math.pi : 0.9;
    canvas.save();
    canvas.clipPath(Path()..addOval(rect));
    canvas.drawRect(rect, Paint()..color = Color.lerp(colores[0], Colors.black, 0.25)!);
    void luz(double angulo, double distancia, double tamano, Color color, double fuerza) {
      final c = centro + Offset(math.cos(angulo), math.sin(angulo)) * radio * distancia;
      final r = Rect.fromCircle(center: c, radius: radio * tamano);
      canvas.drawCircle(c, radio * tamano, Paint()..shader = RadialGradient(colors: [color.withValues(alpha: fuerza), color.withValues(alpha: 0)]).createShader(r));
    }

    luz(giro, 0.45, 0.95, colores[1], 0.95);
    luz(giro + math.pi, 0.5, 0.95, colores[2], 0.85);
    luz(giro + math.pi / 2, 0.35, 0.6, colores[0], 0.8);
    // Brillo arriba a la izquierda para que parezca una esfera y no un disco.
    canvas.drawRect(rect, Paint()..shader = RadialGradient(center: const Alignment(-0.35, -0.45), radius: 0.7, colors: [Colors.white.withValues(alpha: 0.40), Colors.white.withValues(alpha: 0)]).createShader(rect));
    canvas.restore();
  }

  @override
  bool shouldRepaint(_PintorOrbe viejo) => viejo.t != t || viejo.estado != estado || viejo.colores != colores;
}
