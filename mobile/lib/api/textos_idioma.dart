import 'dart:ui' show Locale;

import '../l10n/app_localizations.dart';

/// Los textos de la app en un idioma dado (`es`, `ca`, `en`, `fr`), para código sin `BuildContext` (errores de red...). Un idioma sin traducción cae al castellano.
AppLocalizations textosEnIdioma(String idioma) {
  try {
    return lookupAppLocalizations(Locale(idioma));
  } catch (_) {
    return lookupAppLocalizations(const Locale('es'));
  }
}
