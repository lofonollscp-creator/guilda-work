import 'dart:math' as math;

import 'package:flutter/painting.dart';

/// Los colores de acento que se pueden elegir (los mismos ocho que en Perfil → Apariencia de la web, con las mismas claves y colores) y el cálculo del
/// contraste: el texto sobre el acento (negro o blanco, el que más contraste dé) y el acento como texto en tema claro y oscuro (oscurecido o aclarado hasta
/// llegar a 4,5:1). Es el mismo cálculo que `app/marca.py::colores_derivados` del servidor (`test/acento_test.dart` lo comprueba con sus resultados).
const acentos = <String, int>{
  'lima': 0xFFA6E600,
  'azul': 0xFF3B82F6,
  'turquesa': 0xFF14B8A6,
  'violeta': 0xFF8B5CF6,
  'rosa': 0xFFEC4899,
  'rojo': 0xFFEF4444,
  'naranja': 0xFFF97316,
  'ambar': 0xFFF5B400,
};

class ColoresAcento {
  final Color primary;
  final Color primaryDark;
  final Color onAccent;
  final Color textoClaro;
  final Color textoOscuro;
  const ColoresAcento(this.primary, this.primaryDark, this.onAccent, this.textoClaro, this.textoOscuro);
}

/// Luminancia relativa (WCAG) de un color opaco.
double _luminancia(Color c) {
  double lin(double v) => v <= 0.03928 ? v / 12.92 : math.pow((v + 0.055) / 1.055, 2.4).toDouble();
  return 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b);
}

double _contraste(double l1, double l2) => (math.max(l1, l2) + 0.05) / (math.min(l1, l2) + 0.05);

int _redondear(double x) {
  // como Python: la mitad se redondea al par
  final f = x.floorToDouble();
  final d = x - f;
  if (d < 0.5) return f.toInt();
  if (d > 0.5) return f.toInt() + 1;
  return f.toInt().isEven ? f.toInt() : f.toInt() + 1;
}

Color _mezclar(Color c, Color con, double peso) {
  int canal(double a, double b) => _redondear((a * 255) * (1 - peso) + (b * 255) * peso);
  return Color.fromARGB(255, canal(c.r, con.r), canal(c.g, con.g), canal(c.b, con.b));
}

// Los fondos reales de la interfaz (#f7f8fa y #101113): el acento como texto tiene que leerse sobre ellos (mismas constantes que app/marca.py).
const _lumFondoClaro = 0.9355;
const _lumFondoOscuro = 0.0056;

const _negro = Color(0xFF000000);
const _blanco = Color(0xFFFFFFFF);
const _casiNegro = Color(0xFF0A0A0A);

ColoresAcento coloresDeAcento(String clave) {
  final color = Color(acentos[clave] ?? acentos['lima']!);
  final lum = _luminancia(color);
  final sobre = _contraste(lum, _luminancia(_casiNegro)) >= _contraste(lum, 1.0) ? _casiNegro : _blanco;
  var claro = color;
  for (var i = 0; i < 12; i++) {
    if (_contraste(_luminancia(claro), _lumFondoClaro) >= 4.5) break;
    claro = _mezclar(claro, _negro, 0.15);
  }
  var oscuro = color;
  for (var i = 0; i < 12; i++) {
    if (_contraste(_luminancia(oscuro), _lumFondoOscuro) >= 4.5) break;
    oscuro = _mezclar(oscuro, _blanco, 0.15);
  }
  return ColoresAcento(color, _mezclar(color, _negro, 0.15), sobre, claro, oscuro);
}
