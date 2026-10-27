import 'package:flutter/material.dart';

/// Los colores del asistente de IA: un violeta propio que lo distingue de lo demás de la app
/// (el acento de marca sigue siendo para las acciones de siempre). Los pares fondo/texto
/// cumplen el contraste AA en los dos temas.
class ColoresIa {
  final Color acento;
  final Color sobreAcento;
  final Color fondo;
  final Color sobreFondo;
  final Color borde;
  const ColoresIa._(this.acento, this.sobreAcento, this.fondo, this.sobreFondo, this.borde);

  static const _claro = ColoresIa._(Color(0xFF4A3FB5), Color(0xFFFFFFFF), Color(0xFFECEBFA), Color(0xFF2B2A6B), Color(0xFFD5D2F3));
  static const _oscuro = ColoresIa._(Color(0xFFB9B3FF), Color(0xFF1B1840), Color(0xFF2A2755), Color(0xFFE4E1FF), Color(0xFF4A4590));

  static ColoresIa de(BuildContext context) => Theme.of(context).brightness == Brightness.dark ? _oscuro : _claro;
}

/// La insignia del asistente: un cuadrado redondeado con la chispa. Decorativa (el texto de al lado dice quién es).
class InsigniaIa extends StatelessWidget {
  final double tamano;
  const InsigniaIa({super.key, this.tamano = 28});

  @override
  Widget build(BuildContext context) {
    final c = ColoresIa.de(context);
    return ExcludeSemantics(
      child: Container(
        width: tamano,
        height: tamano,
        decoration: BoxDecoration(color: c.acento, borderRadius: BorderRadius.circular(tamano * 0.32)),
        child: Icon(Icons.auto_awesome, size: tamano * 0.57, color: c.sobreAcento),
      ),
    );
  }
}

/// Una sugerencia rápida en forma de píldora violeta: un toque y se la pide al asistente.
class ChipIa extends StatelessWidget {
  final String texto;
  final VoidCallback? alPulsar;
  const ChipIa({super.key, required this.texto, required this.alPulsar});

  @override
  Widget build(BuildContext context) {
    final c = ColoresIa.de(context);
    return Semantics(
      button: true,
      enabled: alPulsar != null,
      child: InkWell(
        onTap: alPulsar,
        borderRadius: BorderRadius.circular(999),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 48),
          child: Center(
            widthFactor: 1,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              decoration: BoxDecoration(color: c.fondo, border: Border.all(color: c.borde), borderRadius: BorderRadius.circular(999)),
              child: Text(texto, style: Theme.of(context).textTheme.labelLarge?.copyWith(color: c.sobreFondo, fontWeight: FontWeight.w500)),
            ),
          ),
        ),
      ),
    );
  }
}

/// La barra que invita a hablar con el asistente: parece un campo de texto, pero al tocarla abre el chat
/// (ya con el contexto de la pantalla desde la que se abre). Lleva el micro por si se prefiere dictar.
class BarraAsistente extends StatelessWidget {
  final String pista;
  final VoidCallback alPulsar;

  /// Si se pasa, el micro es un botón aparte (abre el chat dictando); si no, solo adorna.
  final VoidCallback? alDictar;
  final String? etiquetaDictar;
  const BarraAsistente({super.key, required this.pista, required this.alPulsar, this.alDictar, this.etiquetaDictar});

  @override
  Widget build(BuildContext context) {
    final c = ColoresIa.de(context);
    final tema = Theme.of(context);
    return Material(
      color: c.fondo,
      shape: StadiumBorder(side: BorderSide(color: c.borde)),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: alPulsar,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 56),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 6, 0),
            child: Row(children: [
              const InsigniaIa(tamano: 32),
              const SizedBox(width: 10),
              Expanded(child: Text(pista, maxLines: 1, overflow: TextOverflow.ellipsis, style: tema.textTheme.bodyLarge?.copyWith(color: c.sobreFondo, fontWeight: FontWeight.w500))),
              if (alDictar != null)
                IconButton(
                  icon: Icon(Icons.mic_none, color: c.sobreFondo),
                  tooltip: etiquetaDictar,
                  constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
                  onPressed: alDictar,
                )
              else
                ExcludeSemantics(child: Padding(padding: const EdgeInsets.all(12), child: Icon(Icons.mic_none, color: c.sobreFondo))),
            ]),
          ),
        ),
      ),
    );
  }
}

/// La tarjeta del asistente para «Hoy»: qué puede hacer por ti ahora mismo (sugerencias de un toque) y la barra para pedirle otra cosa.
class TarjetaAsistente extends StatelessWidget {
  final String titulo;
  final String pista;
  final List<String> sugerencias;
  final ValueChanged<String> alElegir;
  final VoidCallback alAbrir;
  const TarjetaAsistente({super.key, required this.titulo, required this.pista, required this.sugerencias, required this.alElegir, required this.alAbrir});

  @override
  Widget build(BuildContext context) {
    final c = ColoresIa.de(context);
    final tema = Theme.of(context);
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 10),
      decoration: BoxDecoration(color: c.fondo.withValues(alpha: 0.55), border: Border.all(color: c.borde), borderRadius: BorderRadius.circular(20)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const InsigniaIa(),
          const SizedBox(width: 10),
          Expanded(child: Text(titulo, style: tema.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600))),
        ]),
        const SizedBox(height: 6),
        Wrap(spacing: 8, children: [for (final s in sugerencias) ChipIa(texto: s, alPulsar: () => alElegir(s))]),
        const SizedBox(height: 2),
        BarraAsistente(pista: pista, alPulsar: alAbrir),
      ]),
    );
  }
}

/// «Esto es una IA y puede equivocarse»: una línea discreta con la chispa del asistente, para ponerla junto al campo de escritura.
class AvisoIa extends StatelessWidget {
  final String texto;
  const AvisoIa({super.key, required this.texto});

  @override
  Widget build(BuildContext context) {
    final c = ColoresIa.de(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(color: c.fondo.withValues(alpha: 0.55), borderRadius: BorderRadius.circular(10)),
      child: Row(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(padding: const EdgeInsets.only(top: 1), child: ExcludeSemantics(child: Icon(Icons.auto_awesome, size: 13, color: c.sobreFondo))),
        const SizedBox(width: 6),
        Flexible(child: Text(texto, style: Theme.of(context).textTheme.labelSmall?.copyWith(color: c.sobreFondo))),
      ]),
    );
  }
}
