import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../theme/acento.dart';

/// Persiste la preferencia de tema (sistema/claro/oscuro) en
/// SharedPreferences -- mismo criterio que app/static/sidebar.js con
/// localStorage en la web (clave 'gw_tema' allí, ver plan Fase 3). Es un
/// ChangeNotifier para que main.dart pueda escucharlo y reconstruir el
/// MaterialApp con el themeMode nuevo en cuanto cambie desde AjustesScreen.
class ThemeService extends ChangeNotifier {
  static const _clavePreferencia = 'gw_tema';
  static const _claveAcento = 'gw_acento';

  ThemeMode _modo = ThemeMode.system;
  ThemeMode get modo => _modo;

  /// Clave del color de acento elegido (`lima` por defecto): ver `theme/acento.dart`. Solo vale en este móvil.
  String _acento = 'lima';
  String get acento => _acento;

  Future<void> cambiarAcento(String clave) async {
    _acento = clave;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_claveAcento, clave);
  }

  Future<void> cargar() async {
    final prefs = await SharedPreferences.getInstance();
    final a = prefs.getString(_claveAcento);
    if (a != null && acentos.containsKey(a)) _acento = a;
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
