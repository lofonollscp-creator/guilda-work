import 'package:flutter/material.dart';

import '../dominio/tarea.dart';
import '../theme/brand_colors.dart';

/// Cómo se ve cada estado de una tarea: **color + icono + etiqueta** (nunca solo color).
/// Los colores de TEXTO cumplen contraste AA sobre la superficie de su tema (lo vigila `test/diseno_test.dart`).
class AspectoEstado {
  final IconData icono;
  final Color colorClaro;
  final Color colorOscuro;
  const AspectoEstado(this.icono, this.colorClaro, this.colorOscuro);

  Color color(Brightness b) => b == Brightness.dark ? colorOscuro : colorClaro;
}

const _gris = AspectoEstado(Icons.radio_button_unchecked, Color(0xFF5B6270), Color(0xFFA3AAB5));
const _azul = AspectoEstado(Icons.play_circle_outline, Color(0xFF1A56C4), Color(0xFF7DB0FF));
const _ambar = AspectoEstado(Icons.schedule, BrandColors.warningTextLight, BrandColors.warningTextDark);
const _grisAzulado = AspectoEstado(Icons.event_outlined, Color(0xFF4A6070), Color(0xFF9DB1C0));
const _verde = AspectoEstado(Icons.check_circle_outline, BrandColors.successTextLight, BrandColors.successTextDark);
const _violeta = AspectoEstado(Icons.visibility_outlined, Color(0xFF6A3AC0), Color(0xFFB99CFF));

/// «Vencida» no es un estado del servidor sino un indicador derivado de la fecha.
const aspectoVencida = AspectoEstado(Icons.error_outline, BrandColors.dangerTextLight, BrandColors.dangerTextDark);

AspectoEstado aspectoDe(EstadoTarea e) => switch (e) {
      EstadoTarea.noIniciada => _gris,
      EstadoTarea.enProgreso => _azul,
      EstadoTarea.esperando => _ambar,
      EstadoTarea.aplazada => _grisAzulado,
      EstadoTarea.completada => _verde,
      EstadoTarea.enRevision => _violeta,
      EstadoTarea.desconocido => _gris,
    };
