import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

/// El texto de una nota con el mismo subconjunto de Markdown que la web (`app/notas_formato.py`): **negrita**, *cursiva*, listas con «-», «*» o «1.»,
/// enlaces `[texto](https://…)` y direcciones sueltas. Nada más: un `<b>` se ve tal cual.
class TextoNota extends StatefulWidget {
  final String texto;
  final TextStyle? estilo;
  const TextoNota(this.texto, {super.key, this.estilo});

  @override
  State<TextoNota> createState() => _TextoNotaState();
}

class _TextoNotaState extends State<TextoNota> {
  final List<TapGestureRecognizer> _reconocedores = [];

  void _soltar() {
    for (final r in _reconocedores) {
      r.dispose();
    }
    _reconocedores.clear();
  }

  @override
  void dispose() {
    _soltar();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    _soltar();
    final tema = Theme.of(context);
    final base = widget.estilo ?? tema.textTheme.bodyLarge!;
    final enlace = base.copyWith(color: tema.colorScheme.primary, decoration: TextDecoration.underline);
    final bloques = bloquesDeNota(widget.texto);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final b in bloques)
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: b.item == null
              ? Text.rich(TextSpan(style: base, children: _inline(b.texto, base, enlace)))
              : Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  SizedBox(width: 24, child: Text(b.item!, style: base)),
                  Expanded(child: Text.rich(TextSpan(style: base, children: _inline(b.texto, base, enlace)))),
                ]),
        ),
    ]);
  }

  List<InlineSpan> _inline(String texto, TextStyle base, TextStyle enlace) {
    final salida = <InlineSpan>[];
    for (final t in trozosDeNota(texto)) {
      switch (t.tipo) {
        case TrozoNota.texto:
          salida.add(TextSpan(text: t.texto));
        case TrozoNota.negrita:
          salida.add(TextSpan(text: t.texto, style: const TextStyle(fontWeight: FontWeight.w800)));
        case TrozoNota.cursiva:
          salida.add(TextSpan(text: t.texto, style: const TextStyle(fontStyle: FontStyle.italic)));
        case TrozoNota.enlace:
          final r = TapGestureRecognizer()..onTap = () => launchUrl(Uri.parse(t.url!), mode: LaunchMode.externalApplication);
          _reconocedores.add(r);
          salida.add(TextSpan(text: t.texto, style: enlace, recognizer: r));
      }
    }
    return salida;
  }
}

/// Un párrafo o un elemento de lista (`item` = «•» o «1.»).
class BloqueNota {
  final String texto;
  final String? item;
  const BloqueNota(this.texto, [this.item]);
}

final _itemLista = RegExp(r'^\s*[-*•]\s+(.*)$');
final _itemNumerado = RegExp(r'^\s*(\d+)[.)]\s+(.*)$');

/// Las líneas de la nota como bloques: cada elemento de lista aparte y los renglones seguidos de texto, unidos en un párrafo.
List<BloqueNota> bloquesDeNota(String texto) {
  final bloques = <BloqueNota>[];
  final parrafo = <String>[];
  void cerrar() {
    if (parrafo.isNotEmpty) bloques.add(BloqueNota(parrafo.join('\n')));
    parrafo.clear();
  }

  for (final linea in texto.split('\n')) {
    final lista = _itemLista.firstMatch(linea);
    final numerado = _itemNumerado.firstMatch(linea);
    if (lista != null) {
      cerrar();
      bloques.add(BloqueNota(lista[1]!, '•'));
    } else if (numerado != null) {
      cerrar();
      bloques.add(BloqueNota(numerado[2]!, '${numerado[1]}.'));
    } else if (linea.trim().isEmpty) {
      cerrar();
    } else {
      parrafo.add(linea);
    }
  }
  cerrar();
  return bloques;
}

enum TrozoNota { texto, negrita, cursiva, enlace }

class TrozoDeNota {
  final TrozoNota tipo;
  final String texto;
  final String? url;
  const TrozoDeNota(this.tipo, this.texto, [this.url]);
}

final _enlaceOUrl = RegExp(r'\[([^\]\n]+)\]\((https?://[^\s)]+)\)|(?<!["' "'" r'=>])(https?://[^\s<)]+)');
final _negrita = RegExp(r'\*\*(?=\S)(.+?)(?<=\S)\*\*');
final _cursiva = RegExp(r'(?<![\*\w])\*(?=[^\s\*])(.+?)(?<=[^\s\*])\*(?![\*\w])');

/// Un texto de una línea o párrafo como trozos con su formato. Primero los enlaces (así ni la negrita ni la cursiva tocan el interior de una dirección).
List<TrozoDeNota> trozosDeNota(String texto) {
  final salida = <TrozoDeNota>[];
  var desde = 0;
  for (final m in _enlaceOUrl.allMatches(texto)) {
    if (m.start > desde) salida.addAll(_formato(texto.substring(desde, m.start)));
    if (m[2] != null) {
      salida.add(TrozoDeNota(TrozoNota.enlace, m[1]!, m[2]));
    } else {
      var url = m[3]!;
      var sobrante = '';
      while (url.isNotEmpty && '.,;:!?'.contains(url[url.length - 1])) {
        sobrante = url[url.length - 1] + sobrante;
        url = url.substring(0, url.length - 1);
      }
      salida.add(TrozoDeNota(TrozoNota.enlace, url, url));
      if (sobrante.isNotEmpty) salida.add(TrozoDeNota(TrozoNota.texto, sobrante));
    }
    desde = m.end;
  }
  if (desde < texto.length) salida.addAll(_formato(texto.substring(desde)));
  return salida;
}

List<TrozoDeNota> _formato(String texto) {
  final salida = <TrozoDeNota>[];
  var desde = 0;
  for (final m in _negrita.allMatches(texto)) {
    if (m.start > desde) salida.addAll(_cursivas(texto.substring(desde, m.start)));
    salida.add(TrozoDeNota(TrozoNota.negrita, m[1]!));
    desde = m.end;
  }
  if (desde < texto.length) salida.addAll(_cursivas(texto.substring(desde)));
  return salida;
}

List<TrozoDeNota> _cursivas(String texto) {
  final salida = <TrozoDeNota>[];
  var desde = 0;
  for (final m in _cursiva.allMatches(texto)) {
    if (m.start > desde) salida.add(TrozoDeNota(TrozoNota.texto, texto.substring(desde, m.start)));
    salida.add(TrozoDeNota(TrozoNota.cursiva, m[1]!));
    desde = m.end;
  }
  if (desde < texto.length) salida.add(TrozoDeNota(TrozoNota.texto, texto.substring(desde)));
  return salida;
}

/// Lo que se ve de una nota sin sus marcas (para el principio que enseña la lista): sin `**`, `*`, viñetas ni la dirección de los enlaces.
String textoPlanoDeNota(String texto) => [
      for (final b in bloquesDeNota(texto)) trozosDeNota(b.texto).map((t) => t.texto).join().replaceAll('\n', ' '),
    ].where((x) => x.isNotEmpty).join(' · ');
