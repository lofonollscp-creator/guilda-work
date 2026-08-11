import 'package:flutter/material.dart';

/// Paleta de marca de Guilda Work, calcada de las variables CSS de la web
/// (app/static/style.css:1-104 — estética "terminal/neón", acento único
/// verde-lima, fondo casi negro puro en oscuro). Cualquier cambio de marca
/// debe hacerse en LOS DOS SITIOS a la vez para no perder la paridad que
/// persigue la Fase 3 del plan "eventual-herding-kitten".
class BrandColors {
  BrandColors._();

  // --primary / --primary-dark
  static const primaryLight = Color(0xFFA6E600);
  static const primaryDarkAccent = Color(0xFF8FC400); // --primary-dark en claro
  static const primaryDark = Color(0xFFCCFF33);
  static const primaryDarkAccentDark = Color(0xFFA6E600); // --primary-dark en oscuro

  // --on-accent: texto sobre --primary, igual en los dos temas (el lima es
  // demasiado claro para texto blanco legible en ninguno de los dos).
  static const onAccent = Color(0xFF0A0A0A);

  // --bg / --surface / --border
  static const bgLight = Color(0xFFF7F8FA);
  static const surfaceLight = Color(0xFFFFFFFF);
  static const borderLight = Color(0xFFD8DBE1);

  static const bgDark = Color(0xFF0A0A0C);
  static const surfaceDark = Color(0xFF101113);
  static const borderDark = Color(0xFF2A2D33);

  // --text / --text-muted
  static const textLight = Color(0xFF1A1D23);
  static const textMutedLight = Color(0xFF6B7280);
  static const textDark = Color(0xFFE8EAE9);
  static const textMutedDark = Color(0xFF8A9099);

  // --danger / --success / --warning (success no cambia entre temas en la
  // web -- se deja igual aquí a propósito).
  static const dangerLight = Color(0xFFE0555A);
  static const dangerDark = Color(0xFFFF6B70);
  static const success = Color(0xFF1F9D55);
  static const warningLight = Color(0xFFB8860B);
  static const warningDark = Color(0xFFEAB308);

  // --radius: 4px en la web ("esquinas casi rectas a propósito", look
  // terminal). En móvil se relaja un poco por ergonomía táctil (decisión
  // tomada en el plan de la Fase 3) sin perder el aire "recto" de la marca.
  static const radius = 8.0;
  static const radiusSmall = 6.0;
  static const radiusLarge = 12.0;
}
