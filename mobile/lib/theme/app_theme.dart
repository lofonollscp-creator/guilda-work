import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

import 'brand_colors.dart';

/// Sistema de diseño de la app móvil — construye ThemeData explícitamente a
/// partir de BrandColors (NO ColorScheme.fromSeed: esa API deriva colores a
/// partir de una semilla y no puede reproducir el acento único + fondo casi
/// negro que define app/static/style.css).
///
/// Tipografía híbrida (decisión tomada en el plan de la Fase 3): fuente
/// monoespaciada del sistema en titulares/cifras para evocar el look
/// "terminal" de la web sin depender de descargar una fuente en tiempo de
/// ejecución (nada de google_fonts: Menlo/monospace ya vienen en el SO), y
/// sans-serif normal en el resto del texto para mantener la app legible.
class AppTheme {
  AppTheme._();

  /// Menlo en iOS/macOS, "monospace" (alias de Droid Sans Mono) en Android;
  /// en cualquier otra plataforma se deja que Flutter use su fallback
  /// habitual en vez de forzar un nombre de fuente que no existiría ahí.
  static String? get _fuenteMono {
    if (kIsWeb) return null;
    if (Platform.isIOS || Platform.isMacOS) return 'Menlo';
    if (Platform.isAndroid) return 'monospace';
    return null;
  }

  static TextTheme _construirTextTheme(TextTheme base, Color color, Color colorMuted) {
    final mono = _fuenteMono;
    return base.copyWith(
      // Titulares y etiquetas en mono -- eco de la identidad "terminal".
      headlineLarge: base.headlineLarge?.copyWith(fontFamily: mono, color: color, fontWeight: FontWeight.w600),
      headlineMedium: base.headlineMedium?.copyWith(fontFamily: mono, color: color, fontWeight: FontWeight.w600),
      headlineSmall: base.headlineSmall?.copyWith(fontFamily: mono, color: color, fontWeight: FontWeight.w600),
      titleLarge: base.titleLarge?.copyWith(fontFamily: mono, color: color, fontWeight: FontWeight.w600),
      titleMedium: base.titleMedium?.copyWith(fontFamily: mono, color: color, fontWeight: FontWeight.w600),
      titleSmall: base.titleSmall?.copyWith(fontFamily: mono, color: color, fontWeight: FontWeight.w500),
      labelLarge: base.labelLarge?.copyWith(fontFamily: mono, color: color),
      labelMedium: base.labelMedium?.copyWith(fontFamily: mono, color: colorMuted),
      labelSmall: base.labelSmall?.copyWith(fontFamily: mono, color: colorMuted),
      // Cuerpo de texto en la sans-serif normal del sistema -- legible en
      // bloques largos (correos, notas, respuestas del asistente).
      bodyLarge: base.bodyLarge?.copyWith(color: color),
      bodyMedium: base.bodyMedium?.copyWith(color: color),
      bodySmall: base.bodySmall?.copyWith(color: colorMuted),
    );
  }

  /// TextStyle suelto en mono, para usarlo directamente en cifras sensibles
  /// (horas de fichaje, duraciones, saldos) fuera del TextTheme normal.
  static TextStyle cifra({double? fontSize, FontWeight? fontWeight, Color? color}) =>
      TextStyle(fontFamily: _fuenteMono, fontSize: fontSize, fontWeight: fontWeight ?? FontWeight.w600, color: color);

  static ThemeData get light => _construir(
        brightness: Brightness.light,
        primary: BrandColors.primaryLight,
        bg: BrandColors.bgLight,
        surface: BrandColors.surfaceLight,
        border: BrandColors.borderLight,
        text: BrandColors.textLight,
        textMuted: BrandColors.textMutedLight,
        danger: BrandColors.dangerLight,
        warning: BrandColors.warningLight,
      );

  static ThemeData get dark => _construir(
        brightness: Brightness.dark,
        primary: BrandColors.primaryDark,
        bg: BrandColors.bgDark,
        surface: BrandColors.surfaceDark,
        border: BrandColors.borderDark,
        text: BrandColors.textDark,
        textMuted: BrandColors.textMutedDark,
        danger: BrandColors.dangerDark,
        warning: BrandColors.warningDark,
      );

  static ThemeData _construir({
    required Brightness brightness,
    required Color primary,
    required Color bg,
    required Color surface,
    required Color border,
    required Color text,
    required Color textMuted,
    required Color danger,
    required Color warning,
  }) {
    final colorScheme = ColorScheme(
      brightness: brightness,
      primary: primary,
      onPrimary: BrandColors.onAccent,
      primaryContainer: primary,
      onPrimaryContainer: BrandColors.onAccent,
      secondary: primary,
      onSecondary: BrandColors.onAccent,
      error: danger,
      onError: Colors.white,
      surface: surface,
      onSurface: text,
      surfaceContainerHighest: Color.alphaBlend(border.withValues(alpha: 0.35), surface),
      onSurfaceVariant: textMuted,
      outline: border,
      outlineVariant: border.withValues(alpha: 0.6),
      tertiary: warning,
      onTertiary: BrandColors.onAccent,
    );

    final base = brightness == Brightness.light ? ThemeData.light() : ThemeData.dark();
    final textTheme = _construirTextTheme(base.textTheme, text, textMuted);
    final radius = BorderRadius.circular(BrandColors.radius);

    return base.copyWith(
      brightness: brightness,
      colorScheme: colorScheme,
      scaffoldBackgroundColor: bg,
      textTheme: textTheme,
      primaryTextTheme: textTheme,
      appBarTheme: AppBarTheme(
        backgroundColor: bg,
        foregroundColor: text,
        elevation: 0,
        scrolledUnderElevation: 1,
        centerTitle: false,
        titleTextStyle: textTheme.titleLarge,
      ),
      cardTheme: CardThemeData(
        color: surface,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: radius, side: BorderSide(color: border)),
        margin: const EdgeInsets.symmetric(vertical: 4),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: primary,
          foregroundColor: BrandColors.onAccent,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(BrandColors.radiusSmall)),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          textStyle: textTheme.labelLarge,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: text,
          side: BorderSide(color: border),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(BrandColors.radiusSmall)),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          textStyle: textTheme.labelLarge,
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(foregroundColor: primary, textStyle: textTheme.labelLarge),
      ),
      iconButtonTheme: IconButtonThemeData(style: IconButton.styleFrom(foregroundColor: text)),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: surface,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(BrandColors.radiusSmall), borderSide: BorderSide(color: border)),
        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(BrandColors.radiusSmall), borderSide: BorderSide(color: border)),
        focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(BrandColors.radiusSmall), borderSide: BorderSide(color: primary, width: 2)),
        labelStyle: TextStyle(color: textMuted),
      ),
      switchTheme: SwitchThemeData(
        thumbColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? primary : null),
        trackColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.selected) ? primary.withValues(alpha: 0.5) : null,
        ),
      ),
      floatingActionButtonTheme: FloatingActionButtonThemeData(
        backgroundColor: primary,
        foregroundColor: BrandColors.onAccent,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(BrandColors.radiusLarge)),
      ),
      dividerTheme: DividerThemeData(color: border, space: 1),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: text,
        contentTextStyle: TextStyle(color: bg),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(BrandColors.radiusSmall)),
      ),
      listTileTheme: ListTileThemeData(iconColor: textMuted, textColor: text),
      dialogTheme: DialogThemeData(
        backgroundColor: surface,
        shape: RoundedRectangleBorder(borderRadius: radius),
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(color: primary),
    );
  }
}
