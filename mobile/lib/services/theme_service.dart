import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Persiste la preferencia de tema (sistema/claro/oscuro) en
/// SharedPreferences -- mismo criterio que app/static/sidebar.js con
/// localStorage en la web (clave 'gw_tema' allí, ver plan Fase 3). Es un
/// ChangeNotifier para que main.dart pueda escucharlo y reconstruir el
/// MaterialApp con el themeMode nuevo en cuanto cambie desde AjustesScreen.
class ThemeService extends ChangeNotifier {
  static const _clavePreferencia = 'gw_tema';

  ThemeMode _modo = ThemeMode.system;
  ThemeMode get modo => _modo;

  Future<void> cargar() async {
    final prefs = await SharedPreferences.getInstance();
    final guardado = prefs.getString(_clavePreferencia);
    _modo = switch (guardado) {
      'light' => ThemeMode.light,
      'dark' => ThemeMode.dark,
      _ => ThemeMode.system,
    };
    notifyListeners();
  }

  Future<void> cambiar(ThemeMode modo) async {
    _modo = modo;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_clavePreferencia, switch (modo) {
      ThemeMode.light => 'light',
      ThemeMode.dark => 'dark',
      ThemeMode.system => 'system',
    });
  }
}
