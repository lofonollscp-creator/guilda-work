import 'package:flutter/material.dart';

/// Card con el padding interno de contenido ya aplicado -- el CardTheme
/// global (theme/app_theme.dart) define color/borde/radio, pero cada
/// pantalla repetía su propio Padding a mano de forma inconsistente. Uso:
/// AppCard(child: ...) en vez de Card(child: Padding(padding: ..., child: ...)).
class AppCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;
  final EdgeInsetsGeometry? margin;

  const AppCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(16),
    this.margin,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: margin,
      child: Padding(padding: padding, child: child),
    );
  }
}
