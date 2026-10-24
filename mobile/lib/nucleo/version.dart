import 'package:flutter/foundation.dart';

/// Versión de la app que se manda en `X-App-Version`. El CI la fija con
/// `--dart-define=APP_VERSION=1.2.3` (la misma que `--build-name`); sin ella,
/// la de `pubspec.yaml`.
const versionApp = String.fromEnvironment('APP_VERSION', defaultValue: '1.0.0');

/// `android` / `ios` para `X-App-Platform`.
String plataformaApp() => switch (defaultTargetPlatform) {
      TargetPlatform.iOS => 'ios',
      TargetPlatform.android => 'android',
      _ => defaultTargetPlatform.name,
    };

/// Compara versiones `1.2.3` (los trozos que no sean números cuentan como 0;
/// `+build` y `-pre` se ignoran). Negativo si [a] < [b].
int compararVersiones(String a, String b) {
  List<int> trozos(String v) =>
      v.split(RegExp(r'[+-]')).first.split('.').map((x) => int.tryParse(x) ?? 0).toList();
  final x = trozos(a), y = trozos(b);
  for (var i = 0; i < (x.length > y.length ? x.length : y.length); i++) {
    final c = (i < x.length ? x[i] : 0).compareTo(i < y.length ? y[i] : 0);
    if (c != 0) return c;
  }
  return 0;
}
