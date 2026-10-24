import 'package:flutter/widgets.dart';
import 'package:intl/intl.dart';

import '../api/fechas.dart';
import '../l10n/app_localizations.dart';

/// **Una sola** forma de enseñar fechas y horas en toda la app (antes cada pantalla tenía la suya: `2026-10-22`, `22/10`, `24/10 09:30`...).
/// Las fechas del servidor son locales y sin zona (ver [Fecha]); aquí no se pasan por `DateTime` con zona, solo se formatean.
///
///  - hoy / ayer / mañana (traducido), con el día de la semana dentro de la semana próxima o pasada («mié 28 oct»), y con el año solo si no es el actual.
///  - horas siempre `HH:mm` (24 h).
class Formatos {
  final AppLocalizations t;
  final String idioma;
  final Fecha Function() _hoy;

  Formatos(this.t, {String? idioma, Fecha Function()? hoy})
      : idioma = idioma ?? t.localeName,
        _hoy = hoy ?? (() {
          final d = DateTime.now();
          return Fecha(d.year, d.month, d.day);
        });

  /// «hoy», «ayer», «mañana», «mié 28 oct» o «28 oct 2027».
  String fecha(Fecha f) {
    final hoy = _hoy();
    final dias = hoy.diasHasta(f);
    if (dias == 0) return t.formatoHoy;
    if (dias == -1) return t.formatoAyer;
    if (dias == 1) return t.formatoManana;
    final d = DateTime(f.anio, f.mes, f.dia); // solo para nombrar el día; no se hace aritmética con él
    if (f.anio != hoy.anio) return DateFormat.yMMMd(idioma).format(d);
    return dias.abs() < 7 ? DateFormat('EEE d MMM', idioma).format(d) : DateFormat.MMMd(idioma).format(d);
  }

  /// `HH:mm`.
  String hora(int hora, int minuto) => '${hora.toString().padLeft(2, '0')}:${minuto.toString().padLeft(2, '0')}';

  /// Fecha y, si tiene hora distinta de 00:00, la hora: «hoy 09:30», «mié 28 oct».
  String momento(MomentoLocal m) => (m.hora == 0 && m.minuto == 0) ? fecha(m.fecha) : '${fecha(m.fecha)} ${hora(m.hora, m.minuto)}';

  /// Lo que manda el servidor (`AAAA-MM-DD` o `AAAA-MM-DDTHH:MM`) → texto, o null si no se entiende.
  String? deServidor(String? texto) {
    final m = MomentoLocal.intentar(texto);
    if (m != null) return momento(m);
    final f = Fecha.intentar(texto);
    return f == null ? null : fecha(f);
  }
}

extension FormatosEnContexto on BuildContext {
  /// `context.formatos.fecha(...)`: el formateo único de fechas y horas, en el idioma de la app.
  Formatos get formatos => Formatos(AppLocalizations.of(this));
}

/// El nombre de quien manda un correo, no la dirección entera: `"Ana Pla" <ana@x.com>` → `Ana Pla`; `Ana Pla <ana@x.com>` → `Ana Pla`;
/// sin nombre, la dirección. Así la lista de correo se lee como personas, no como cabeceras.
String nombreDeRemitente(String remitente) {
  final texto = remitente.trim();
  final m = RegExp(r'^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$').firstMatch(texto);
  if (m == null) return texto;
  final nombre = m.group(1)!.trim();
  return nombre.isEmpty ? m.group(2)!.trim() : nombre;
}
