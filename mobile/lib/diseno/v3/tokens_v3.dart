import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show HapticFeedback;

import '../asistente.dart';

/// Medidas, tiempos y curvas de la v3 de la app. Los **colores de marca** siguen saliendo de `tokens.g.dart` (la hoja de estilos de la web); aquí vive
/// solo lo que es propio del móvil: radios más generosos, vidrio, aura y movimiento. Si la web quiere adoptarlo, se sube después a `style.css`.
class V3 {
  V3._();

  // Radios: píldora para controles, 16/24/32 para superficies.
  static const radioS = 16.0;
  static const radioM = 24.0;
  static const radioL = 32.0;

  // Movimiento: corto y con intención. Nada pasa de ~420 ms.
  static const durCorta = Duration(milliseconds: 160);
  static const durMedia = Duration(milliseconds: 260);
  static const durLarga = Duration(milliseconds: 420);
  static const curvaEntrada = Curves.easeOutCubic;
  static const curvaSalida = Curves.easeInCubic;

  /// Un muelle corto: pasa un poco de largo y vuelve (para botones que «saltan» y tarjetas que aparecen).
  static const curvaMuelle = Cubic(0.34, 1.4, 0.64, 1);

  /// Desenfoque del vidrio, en píxeles lógicos.
  static const desenfoque = 24.0;

  /// Altura y margen de la barra flotante de la fase 2.
  static const alturaBarraFlotante = 68.0;
  static const margenBarraFlotante = 12.0;

  /// Interruptor global del vidrio: Ajustes lo apagará para móviles lentos (superficie opaca en su lugar).
  static final ValueNotifier<bool> vidrioActivo = ValueNotifier(true);
}

/// «Reducir movimiento» del sistema: sin aura viva, sin muelles ni brillo de carga.
bool reducirMovimiento(BuildContext context) => MediaQuery.disableAnimationsOf(context);

/// La vibración de la app, con nombre por lo que significa y no por su fuerza.
class Haptica {
  Haptica._();

  /// Cambiar de pestaña, elegir una opción.
  static void seleccion() => HapticFeedback.selectionClick();

  /// Pulsar un botón o abrir algo.
  static void toque() => HapticFeedback.lightImpact();

  /// Una acción hecha: completar una tarea, fichar, aprobar.
  static void hecho() => HapticFeedback.mediumImpact();

  /// Algo que pide atención: un error, una acción destructiva.
  static void aviso() => HapticFeedback.heavyImpact();
}

/// Los colores derivados del tema para las superficies de la v3 (vidrio, tonos de tarjeta, aura). Se calculan del [ThemeData] vigente, así que siguen al tema
/// claro/oscuro y al acento que haya elegido la persona; no hay que registrarlos en el tema.
class PaletaV3 {
  final bool oscuro;
  final Color fondo;
  final Color superficie;
  final Color superficieAlta;
  final Color filo;
  final Color acento;
  final Color texto;
  final Color textoSuave;
  final ColoresIa ia;

  const PaletaV3._(this.oscuro, this.fondo, this.superficie, this.superficieAlta, this.filo, this.acento, this.texto, this.textoSuave, this.ia);

  factory PaletaV3.de(BuildContext context) {
    final tema = Theme.of(context);
    final c = tema.colorScheme;
    final oscuro = tema.brightness == Brightness.dark;
    final fondo = tema.scaffoldBackgroundColor;
    // Las capas suben de claridad (oscuro) o de «blancura» (claro): así se lee la profundidad sin sombras pesadas.
    final superficie = c.surface;
    final alta = Color.alphaBlend((oscuro ? Colors.white : Colors.black).withValues(alpha: oscuro ? 0.05 : 0.03), superficie);
    final filo = (oscuro ? Colors.white : Colors.black).withValues(alpha: oscuro ? 0.09 : 0.07);
    return PaletaV3._(oscuro, fondo, superficie, alta, filo, c.primary, c.onSurface, c.onSurfaceVariant, ColoresIa.de(context));
  }

  /// El texto suave (secundario) sobre un [fondo] concreto: el de siempre si da contraste AA (4,5:1) y, si el fondo lo estropea (un velo de color sobre la tarjeta),
  /// el mismo gris oscurecido (o aclarado, en oscuro) hacia el color del texto justo hasta llegar. Úsalo para el texto secundario dentro de [TarjetaBento] teñida.
  Color suaveSobre(Color fondo) {
    double contraste(Color a, Color b) {
      final la = a.computeLuminance(), lb = b.computeLuminance();
      return ((la > lb ? la : lb) + 0.05) / ((la > lb ? lb : la) + 0.05);
    }

    var c = textoSuave;
    for (var i = 0; i < 12 && contraste(c, fondo) < 4.5; i++) {
      c = Color.lerp(c, texto, 0.15)!;
    }
    return c;
  }

  /// El relleno del vidrio: la superficie algo transparente, para que se adivine lo de detrás.
  Color get vidrio => superficie.withValues(alpha: oscuro ? 0.72 : 0.80);

  /// Sombra suave y difusa (en oscuro casi no se ve, y está bien: ahí manda el filo).
  List<BoxShadow> get sombra => [
        BoxShadow(color: Colors.black.withValues(alpha: oscuro ? 0.45 : 0.10), blurRadius: 28, offset: const Offset(0, 10)),
        BoxShadow(color: Colors.black.withValues(alpha: oscuro ? 0.30 : 0.05), blurRadius: 6, offset: const Offset(0, 2)),
      ];

  /// Los tres colores del aura: el violeta de la IA, el acento de marca y un violeta más claro que los une.
  List<Color> get aura => [ia.acento, acento, Color.lerp(ia.acento, Colors.white, 0.35)!];
}
