import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/theme/acento.dart';
import 'package:guilda_work_mobile/theme/app_theme.dart';

double _lum(Color c) {
  double lin(double v) => v <= 0.03928 ? v / 12.92 : math.pow((v + 0.055) / 1.055, 2.4).toDouble();
  return 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b);
}

double _contraste(Color a, Color b) => (math.max(_lum(a), _lum(b)) + 0.05) / (math.min(_lum(a), _lum(b)) + 0.05);

String _hex(Color c) => '#${c.toARGB32().toRadixString(16).substring(2)}';

void main() {
  // Lo que calcula app/marca.py::colores_derivados del servidor para los mismos ocho colores (primary_dark, texto sobre el acento, acento como texto en claro y en oscuro).
  const esperado = {
    'lima': ('#8dc400', '#0a0a0a', '#577900', '#a6e600'),
    'azul': ('#326ed1', '#0a0a0a', '#326ed1', '#3b82f6'),
    'turquesa': ('#119c8d', '#0a0a0a', '#0c7166', '#14b8a6'),
    'violeta': ('#764ed1', '#0a0a0a', '#764ed1', '#9c74f7'),
    'rosa': ('#c93d82', '#0a0a0a', '#ab346e', '#ec4899'),
    'rojo': ('#cb3a3a', '#0a0a0a', '#cb3a3a', '#ef4444'),
    'naranja': ('#d46213', '#0a0a0a', '#b45310', '#f97316'),
    'ambar': ('#d09900', '#0a0a0a', '#805e00', '#f5b400'),
  };


  group('color de acento', () {
    test('son los mismos ocho que en la web y el cálculo da lo mismo que el servidor', () {
      expect(acentos.keys.toSet(), esperado.keys.toSet());
      for (final e in esperado.entries) {
        final c = coloresDeAcento(e.key);
        expect((_hex(c.primaryDark), _hex(c.onAccent), _hex(c.textoClaro), _hex(c.textoOscuro)), e.value, reason: e.key);
      }
    });

    test('con cualquiera de los ocho se lee todo: botón, enlaces y foco, en claro y en oscuro (>= 4,5:1)', () {
      for (final clave in acentos.keys) {
        final claro = AppTheme.claro(clave), oscuro = AppTheme.oscuro(clave);
        for (final tema in [claro, oscuro]) {
          final e = tema.colorScheme;
          expect(_contraste(e.onPrimary, e.primary), greaterThanOrEqualTo(4.5), reason: '$clave: texto del botón');
          final enlace = tema.textButtonTheme.style!.foregroundColor!.resolve({})!;
          expect(_contraste(enlace, tema.scaffoldBackgroundColor), greaterThanOrEqualTo(4.5), reason: '$clave: texto de los enlaces sobre el fondo');
          expect(_contraste(enlace, e.surface), greaterThanOrEqualTo(4.5), reason: '$clave: texto de los enlaces sobre las tarjetas');
        }
        expect(claro.colorScheme.primary.toARGB32(), acentos[clave], reason: clave);
      }
    });

    test('el de Guilda Work (lima) no cambia: es el de siempre en claro y en oscuro', () {
      expect(AppTheme.claro().colorScheme.primary, AppTheme.light.colorScheme.primary);
      expect(AppTheme.oscuro('lima').colorScheme.primary, AppTheme.dark.colorScheme.primary);
    });
  });
}
