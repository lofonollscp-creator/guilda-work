import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../diseno/v3/tokens_v3.dart' show V3;
import '../theme/acento.dart';

/// Persiste la preferencia de tema (sistema/claro/oscuro) en
/// SharedPreferences -- mismo criterio que app/static/sidebar.js con
/// localStorage en la web (clave 'gw_tema' allí, ver plan Fase 3). Es un
/// ChangeNotifier para que main.dart pueda escucharlo y reconstruir el
/// MaterialApp con el themeMode nuevo en cuanto cambie desde AjustesScreen.
class ThemeService extends ChangeNotifier {
  static const _clavePreferencia = 'gw_tema';
  static const _claveAcento = 'gw_acento';
  static const _claveVidrio = 'gw_vidrio';

  ThemeMode _modo = ThemeMode.system;
  ThemeMode get modo => _modo;

  /// Clave del color de acento elegido (`lima` por defecto): ver `theme/acento.dart`. Solo vale en este móvil.
  String _acento = 'lima';
  String get acento => _acento;

  /// El efecto cristal de las barras flotantes (fondo translúcido con desenfoque). Apagarlo las deja opacas: lo que más pesa en móviles modestos.
  bool get vidrio => V3.vidrioActivo.value;

  Future<void> cambiarVidrio(bool activo) async {
    V3.vidrioActivo.value = activo;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_claveVidrio, activo);
  }

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
    V3.vidrioActivo.value = prefs.getBool(_claveVidrio) ?? true;
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
