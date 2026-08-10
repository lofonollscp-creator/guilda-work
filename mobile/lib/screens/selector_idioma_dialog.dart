import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../services/locale_service.dart';

/// Diálogo simple para elegir idioma, mismo patrón que
/// ajustes_servidor_dialog.dart. Los 4 idiomas se muestran siempre en
/// su propio nombre (Castellano/Català/English/Français) en vez de
/// traducidos, igual que el selector de la web (app/templates/base.html)
/// -- así se reconoce el propio idioma aunque la app esté en otro.
Future<void> mostrarSelectorIdioma(
  BuildContext context,
  LocaleService locale,
) async {
  final t = AppLocalizations.of(context);
  await showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(t.comunIdioma),
      content: RadioGroup<String>(
        groupValue: locale.locale.languageCode,
        onChanged: (v) {
          if (v != null) locale.cambiar(v);
          Navigator.pop(context);
        },
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (final (codigo, nombre) in LocaleService.idiomasDisponibles)
              RadioListTile<String>(
                value: codigo,
                title: Text(nombre),
              ),
          ],
        ),
      ),
    ),
  );
}
