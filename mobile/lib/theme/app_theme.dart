import 'package:flutter/material.dart';

import 'brand_colors.dart';

/// Sistema de diseño de la app móvil — construye ThemeData explícitamente a
/// partir de BrandColors (NO ColorScheme.fromSeed: esa API deriva colores a
/// partir de una semilla y no puede reproducir el acento único + fondo casi
/// negro que define app/static/style.css). Los colores y medidas salen de los
/// tokens generados desde esa misma hoja de estilos (`diseno/tokens.g.dart`).
///
/// Tipografía: **Manrope** en todo (títulos 20–28 sp, cuerpo 15–16 sp), con Inter
/// de respaldo para los glifos que Manrope no trae. Las cifras (horas, importes,
/// saldos) usan números tabulares para que se alineen: ver [cifra].
class AppTheme {
  AppTheme._();

  static const _familia = 'Manrope';
  static const _respaldo = ['Inter'];

  static TextStyle _estilo(double tamano, FontWeight peso, Color color, {double? altura}) =>
      TextStyle(fontFamily: _familia, fontFamilyFallback: _respaldo, fontSize: tamano, fontWeight: peso, color: color, height: altura);

  static TextTheme _construirTextTheme(TextTheme base, Color color, Color colorMuted) => base.copyWith(
        headlineLarge: _estilo(28, FontWeight.w700, color, altura: 1.2),
        headlineMedium: _estilo(24, FontWeight.w700, color, altura: 1.25),
        headlineSmall: _estilo(20, FontWeight.w700, color, altura: 1.3),
        titleLarge: _estilo(20, FontWeight.w700, color, altura: 1.3),
        titleMedium: _estilo(16, FontWeight.w600, color, altura: 1.35),
        titleSmall: _estilo(14, FontWeight.w600, color, altura: 1.35),
        bodyLarge: _estilo(16, FontWeight.w400, color, altura: 1.45),
        bodyMedium: _estilo(15, FontWeight.w400, color, altura: 1.45),
        bodySmall: _estilo(13, FontWeight.w400, colorMuted, altura: 1.4),
        labelLarge: _estilo(14, FontWeight.w600, color),
        labelMedium: _estilo(12, FontWeight.w600, colorMuted),
        labelSmall: _estilo(11, FontWeight.w500, colorMuted),
      );

  /// Estilo para cifras sensibles (horas de fichaje, duraciones, saldos): números tabulares, para que las columnas de cifras se alineen.
  static TextStyle cifra({double? fontSize, FontWeight? fontWeight, Color? color}) => TextStyle(
        fontFamily: _familia,
        fontFamilyFallback: _respaldo,
        fontSize: fontSize,
        fontWeight: fontWeight ?? FontWeight.w600,
        color: color,
        fontFeatures: const [FontFeature.tabularFigures()],
      );

  static ThemeData get light => _construir(
        brightness: Brightness.light,
        primary: BrandColors.primaryLight,
        primaryText: BrandColors.primaryTextLight,
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
        primaryText: BrandColors.primaryTextDark,
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
    required Color primaryText,
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
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: BorderSide(color: border)),
        margin: const EdgeInsets.symmetric(vertical: 4),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: primary,
          foregroundColor: BrandColors.onAccent,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(BrandColors.radiusSmall)),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          minimumSize: const Size(48, 48),
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
      // Texto de botón: el lima como TEXTO sobre fondo claro da 1,5:1 (ilegible); se usa su versión AA (--primary-text).
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(foregroundColor: primaryText, minimumSize: const Size(48, 48), textStyle: textTheme.labelLarge),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: surface,
        indicatorColor: primary,
        iconTheme: WidgetStateProperty.resolveWith((s) => IconThemeData(color: s.contains(WidgetState.selected) ? BrandColors.onAccent : textMuted)),
        labelTextStyle: WidgetStateProperty.resolveWith((s) => textTheme.labelMedium?.copyWith(color: s.contains(WidgetState.selected) ? text : textMuted)),
      ),
      // Selección «tonal»: un tinte del acento con el texto de siempre, y borde del acento. Un lima sólido con texto claro (el de los chips antiguos en oscuro)
      // no se leía; así el contraste es el del texto normal sobre un fondo casi neutro, en los dos temas.
      chipTheme: ChipThemeData(
        backgroundColor: surface,
        selectedColor: Color.alphaBlend(primary.withValues(alpha: brightness == Brightness.dark ? 0.22 : 0.30), surface),
        disabledColor: surface,
        shape: const StadiumBorder(),
        side: WidgetStateBorderSide.resolveWith((s) => BorderSide(color: s.contains(WidgetState.selected) ? primaryText : border, width: s.contains(WidgetState.selected) ? 1.5 : 1)),
        labelStyle: textTheme.labelLarge?.copyWith(color: text),
        secondaryLabelStyle: textTheme.labelLarge?.copyWith(color: text),
        checkmarkColor: text,
        iconTheme: IconThemeData(color: textMuted, size: 18),
        padding: const EdgeInsets.symmetric(horizontal: 6),
      ),
      segmentedButtonTheme: SegmentedButtonThemeData(
        style: ButtonStyle(
          shape: WidgetStatePropertyAll(RoundedRectangleBorder(borderRadius: BorderRadius.circular(BrandColors.radiusSmall))),
          side: WidgetStatePropertyAll(BorderSide(color: border)),
          backgroundColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? Color.alphaBlend(primary.withValues(alpha: brightness == Brightness.dark ? 0.22 : 0.30), surface) : surface),
          foregroundColor: WidgetStatePropertyAll(text),
          textStyle: WidgetStatePropertyAll(textTheme.labelLarge),
          minimumSize: const WidgetStatePropertyAll(Size(48, 44)),
        ),
      ),
      // Casillas redondas (completar una tarea se parece a marcar un círculo, no a rellenar un formulario).
      checkboxTheme: CheckboxThemeData(
        shape: const CircleBorder(),
        side: BorderSide(color: textMuted, width: 1.6),
        fillColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? primary : Colors.transparent),
        checkColor: const WidgetStatePropertyAll(BrandColors.onAccent),
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: surface,
        showDragHandle: true,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(BrandColors.radiusLarge))),
      ),
      // OJO: NO se fija aquí un IconButtonThemeData con foregroundColor fijo
      // -- forzaba el mismo color de icono en TODOS los IconButton,
      // incluidos los `.filled` (ej. el botón de enviar del chat IA, fondo
      // lima brillante): salía un icono casi blanco sobre lima, contraste
      // roto (bug encontrado en vivo). Sin este override, Material 3 ya
      // resuelve bien cada variante a partir de colorScheme (onSurface para
      // el icono normal, onPrimary/BrandColors.onAccent para `.filled`).
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
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(BrandColors.radiusLarge)),
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(color: primary),
    );
  }
}
