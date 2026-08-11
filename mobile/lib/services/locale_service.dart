import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Idioma elegido por el usuario (shared_preferences, mismo patrón que
/// la URL del servidor en session_service.dart). ChangeNotifier en vez
/// de un simple servicio async porque MaterialApp necesita reconstruirse
/// en cuanto cambia el idioma sin reiniciar la app -- ver el
/// ListenableBuilder alrededor de MaterialApp en main.dart.
///
/// Mismos 4 idiomas y mismo orden que IDIOMAS_DISPONIBLES en
/// app/main.py, para que el selector se vea igual en web y móvil.
class LocaleService extends ChangeNotifier {
  static const _claveIdioma = 'idioma';
  static const idiomaPorDefecto = 'es';
  static const idiomasDisponibles = [
    ('es', 'Castellano'),
    ('ca', 'Català'),
    ('en', 'English'),
    ('fr', 'Français'),
  ];

  Locale _locale = const Locale(idiomaPorDefecto);
  Locale get locale => _locale;

  Future<void> cargar() async {
    final prefs = await SharedPreferences.getInstance();
    final codigo = prefs.getString(_claveIdioma);
    if (codigo != null && idiomasDisponibles.any((i) => i.$1 == codigo)) {
      _locale = Locale(codigo);
      notifyListeners();
    }
  }

  Future<void> cambiar(String codigo) async {
    if (codigo == _locale.languageCode) return;
    _locale = Locale(codigo);
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_claveIdioma, codigo);
  }
}
