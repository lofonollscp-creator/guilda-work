import 'package:flutter/material.dart';

import '../theme/brand_colors.dart';

/// Tono semántico de un StatusBadge -- se traduce a los colores de marca de
/// BrandColors (nunca Colors.red/green/amber sueltos, para que cualquier
/// estado/prioridad de la app tenga el mismo lenguaje visual que la web).
enum BadgeTono { neutro, exito, aviso, peligro, acento }

/// Pastilla de estado/prioridad compacta -- sustituye a los Chip/Text
/// sueltos con colores de Material por defecto que había en fichaje_screen,
/// tareas_outlook_screen, tiquets_screen, etc. (Fase 5 del plan
/// "eventual-herding-kitten").
class StatusBadge extends StatelessWidget {
  final String texto;
  final BadgeTono tono;

  const StatusBadge({super.key, required this.texto, this.tono = BadgeTono.neutro});

  @override
  Widget build(BuildContext context) {
    final oscuro = Theme.of(context).brightness == Brightness.dark;
    final Color color = switch (tono) {
      BadgeTono.exito => BrandColors.success,
      BadgeTono.aviso => oscuro ? BrandColors.warningDark : BrandColors.warningLight,
      BadgeTono.peligro => oscuro ? BrandColors.dangerDark : BrandColors.dangerLight,
      BadgeTono.acento => oscuro ? BrandColors.primaryDark : BrandColors.primaryLight,
      BadgeTono.neutro => Theme.of(context).colorScheme.onSurfaceVariant,
    };
    final Color onColor = tono == BadgeTono.acento ? BrandColors.onAccent : Colors.white;
    final Color fondo = tono == BadgeTono.neutro ? color.withValues(alpha: 0.15) : color;
    final Color colorTexto = tono == BadgeTono.neutro ? color : onColor;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(BrandColors.radiusLarge)),
      child: Text(
        texto,
        style: TextStyle(color: colorTexto, fontSize: 12, fontWeight: FontWeight.w600),
      ),
    );
  }
}
