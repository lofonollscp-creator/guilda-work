import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// Política de textos de la app (ADR M6 del plan): nada de `Text('literal')` en las pantallas, los cuatro idiomas con las mismas claves y los mismos
/// marcadores, y ninguna traducción que sea una copia del castellano. Si falla, o falta traducir algo, o se ha escrito un texto a pelo en una pantalla.
const _idiomas = ['es', 'ca', 'en', 'fr'];

Map<String, String> _arb(String l) {
  final j = jsonDecode(File('lib/l10n/app_$l.arb').readAsStringSync()) as Map<String, dynamic>;
  return {for (final e in j.entries) if (!e.key.startsWith('@')) e.key: e.value as String};
}

Set<String> _marcadores(String valor) => RegExp(r'\{(\w+)\}').allMatches(valor).map((m) => m.group(1)!).toSet();

void main() {
  final arb = {for (final l in _idiomas) l: _arb(l)};

  test('los cuatro idiomas tienen exactamente las mismas claves', () {
    final base = arb['es']!.keys.toSet();
    for (final l in _idiomas.skip(1)) {
      final otras = arb[l]!.keys.toSet();
      expect(base.difference(otras), isEmpty, reason: 'faltan en $l');
      expect(otras.difference(base), isEmpty, reason: 'sobran en $l (no están en es)');
    }
  });

  test('los marcadores {nombre} son los mismos en todos los idiomas', () {
    final fallos = <String>[];
    for (final e in arb['es']!.entries) {
      final base = _marcadores(e.value);
      for (final l in _idiomas.skip(1)) {
        final otro = arb[l]![e.key];
        if (otro != null && !_setIgual(base, _marcadores(otro)) && !e.value.contains('plural,')) fallos.add('${e.key} [$l]: $base ≠ ${_marcadores(otro)}');
      }
    }
    expect(fallos, isEmpty);
  });

  test('ninguna traducción larga es una copia del castellano', () {
    // Palabras que se escriben igual en varios idiomas (marcas, siglas, nombres propios...) no cuentan: solo se vigilan frases.
    final copias = <String>[];
    for (final e in arb['es']!.entries) {
      if (e.value.length < 25 || !e.value.contains(' ')) continue;
      // Un texto que es solo marcadores, símbolos y emojis (p. ej. «⚠️ {herramienta}: {error}») se escribe igual en todos los idiomas.
      if (!RegExp(r'[A-Za-zÁÉÍÓÚáéíóúñÑ]{3}').hasMatch(e.value.replaceAll(RegExp(r'\{\w+\}'), ''))) continue;
      for (final l in _idiomas.skip(1)) {
        if (arb[l]![e.key] == e.value) copias.add('${e.key} [$l]');
      }
    }
    expect(copias, isEmpty, reason: 'sin traducir');
  });

  test('las pantallas no llevan textos escritos a pelo', () {
    // Textos que pueden quedarse tal cual: marca, estándares del correo y siglas.
    const permitidos = {'Guilda Work', 'Cc', 'Re:', 'Fwd:', 'INBOX', 'OK', 'IA'};
    final contexto = RegExp(
      r"""(?:\bText|\bSnackBar|\bTextSpan)\(\s*(?:text:\s*)?'((?:[^'\\]|\\.)*)'|(?:hintText|labelText|tooltip|helperText|semanticLabel|errorText|texto|label)\s*:\s*(?:const\s*)?'((?:[^'\\]|\\.)*)'""",
    );
    final tieneTexto = RegExp(r'[A-Za-zÁÉÍÓÚáéíóúñÑ¿¡]{3}');
    final aPelo = <String>[];
    final raices = ['lib/screens', 'lib/funciones', 'lib/nucleo', 'lib/widgets', 'lib/diseno'];
    for (final r in raices) {
      for (final f in Directory(r).listSync(recursive: true).whereType<File>().where((f) => f.path.endsWith('.dart') && !f.path.endsWith('.g.dart'))) {
        final s = f.readAsStringSync();
        for (final m in contexto.allMatches(s)) {
          final lit = m.group(1) ?? m.group(2)!;
          if (!tieneTexto.hasMatch(lit) || permitidos.contains(lit)) continue;
          // Sin las variables interpoladas ($x, ${...}) no queda ninguna palabra: es solo dato y puntuación (p. ej. «${v.modelo} — ${v.cliente}»).
          final sinVariables = lit.replaceAll(RegExp(r'\$\{[^}]*(\}|$)'), '').replaceAll(RegExp(r'\$\w+'), '');
          if (!tieneTexto.hasMatch(sinVariables)) continue;
          final linea = s.substring(0, m.start).split('\n').length;
          aPelo.add('${f.path}:$linea: $lit');
        }
      }
    }
    expect(aPelo, isEmpty, reason: 'textos sin traducir en las pantallas:\n${aPelo.join('\n')}');
  });
}

bool _setIgual(Set<String> a, Set<String> b) => a.length == b.length && a.containsAll(b);
