import 'package:flutter/material.dart';

import '../../diseno/v3/v3.dart';
import '../../l10n/app_localizations.dart';
import '../../models/models.dart';

/// El icono y el nombre de cada tipo de fuente que cita el asistente.
IconData iconoDeFuente(String tipo) => switch (tipo) {
      'tarea' => Icons.task_alt,
      'nota' => Icons.sticky_note_2_outlined,
      'correo' => Icons.mail_outline,
      'vencimiento' => Icons.event_note_outlined,
      _ => Icons.folder_open_outlined,
    };

String nombreDeTipoFuente(AppLocalizations t, String tipo) => switch (tipo) {
      'tarea' => t.navTareas,
      'nota' => t.notasTitulo,
      'correo' => t.navCorreo,
      'vencimiento' => t.iaTipoVencimiento,
      _ => '',
    };

/// Lo que el asistente ha encontrado o tocado, como tarjetas que se abren: una por tarea, nota, correo o vencimiento citado.
/// Un toque lleva a la ficha de verdad (el mismo camino que las fuentes de antes).
class TarjetasResultado extends StatelessWidget {
  final List<IaFuente> fuentes;
  final ValueChanged<IaFuente> alAbrir;
  const TarjetasResultado({super.key, required this.fuentes, required this.alAbrir});

  @override
  Widget build(BuildContext context) {
    if (fuentes.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        for (final f in fuentes) Padding(padding: const EdgeInsets.only(bottom: 8), child: _TarjetaResultado(fuente: f, alAbrir: () => alAbrir(f))),
      ]),
    );
  }
}

class _TarjetaResultado extends StatelessWidget {
  final IaFuente fuente;
  final VoidCallback alAbrir;
  const _TarjetaResultado({required this.fuente, required this.alAbrir});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final p = PaletaV3.de(context);
    final tipo = nombreDeTipoFuente(t, fuente.tipo);
    final fondo = TarjetaBento.fondoDe(p, TonoBento.neutro);
    return TarjetaBento(
      alPulsar: alAbrir,
      etiqueta: tipo.isEmpty ? fuente.titulo : '$tipo: ${fuente.titulo}',
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      // La etiqueta ya dice tipo y título: lo de dentro no se lee otra vez.
      child: ExcludeSemantics(
          child: Row(children: [
        Container(
          width: 40,
          height: 40,
          decoration: BoxDecoration(color: p.ia.fondo, borderRadius: BorderRadius.circular(V3.radioS - 4)),
          child: ExcludeSemantics(child: Icon(iconoDeFuente(fuente.tipo), size: 22, color: p.ia.acento)),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            if (tipo.isNotEmpty) Text(tipo, style: tema.textTheme.labelMedium?.copyWith(color: p.suaveSobre(fondo), fontWeight: FontWeight.w700)),
            Text(fuente.titulo, style: tema.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700), maxLines: 2, overflow: TextOverflow.ellipsis),
          ]),
        ),
        const SizedBox(width: 8),
        Icon(Icons.north_east, size: 18, color: p.suaveSobre(fondo)),
      ])),
    );
  }
}

/// La respuesta que va llegando, con un cursor suave al final (un punto que respira). Con «reducir movimiento» el cursor queda fijo.
class TextoVivo extends StatefulWidget {
  final String texto;
  final List<InlineSpan> Function(BuildContext, String) construir;
  const TextoVivo({super.key, required this.texto, required this.construir});

  @override
  State<TextoVivo> createState() => _TextoVivoState();
}

class _TextoVivoState extends State<TextoVivo> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 900));

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (reducirMovimiento(context)) {
      _c.stop();
      _c.value = 1;
    } else if (!_c.isAnimating) {
      _c.repeat(reverse: true);
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final color = PaletaV3.de(context).ia.acento;
    return AnimatedBuilder(
      animation: _c,
      builder: (context, _) => Text.rich(TextSpan(children: [
        ...widget.construir(context, widget.texto),
        WidgetSpan(
          alignment: PlaceholderAlignment.middle,
          child: ExcludeSemantics(
            child: Container(
              margin: const EdgeInsets.only(left: 4),
              width: 8,
              height: 8,
              decoration: BoxDecoration(color: color.withValues(alpha: 0.35 + 0.65 * _c.value), shape: BoxShape.circle),
            ),
          ),
        ),
      ])),
    );
  }
}

/// El aviso discreto del tope de IA: al 80 % «llevas X de Y» y, agotado, cuándo se renueva. Sin tope o lejos de él no sale.
class AvisoConsumoIa extends StatelessWidget {
  final ConsumoIa? consumo;
  const AvisoConsumoIa({super.key, required this.consumo});

  @override
  Widget build(BuildContext context) {
    final c = consumo;
    if (c == null || !(c.agotado || c.cerca)) return const SizedBox.shrink();
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final p = PaletaV3.de(context);
    final texto = c.agotado ? t.iaConsumoAgotado : t.iaConsumoCerca(c.usadas, c.limite!);
    final fondo = Color.alphaBlend((c.agotado ? tema.colorScheme.error : p.acento).withValues(alpha: 0.12), p.superficie);
    return Semantics(
      liveRegion: true,
      child: Container(
        margin: const EdgeInsets.fromLTRB(12, 4, 12, 4),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(V3.radioS)),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          ExcludeSemantics(child: Icon(c.agotado ? Icons.block : Icons.speed, size: 18, color: p.texto)),
          const SizedBox(width: 8),
          Expanded(child: Text(texto, style: tema.textTheme.labelMedium?.copyWith(color: p.texto))),
        ]),
      ),
    );
  }
}

/// Lo que hace el asistente mientras responde: el orbe pensando y, plegados, los pasos ya dados. Un toque los despliega.
class PasosPlegables extends StatefulWidget {
  final List<String> hechos;
  final String? enCurso;
  const PasosPlegables({super.key, required this.hechos, this.enCurso});

  @override
  State<PasosPlegables> createState() => _PasosPlegablesState();
}

class _PasosPlegablesState extends State<PasosPlegables> {
  bool _abierto = false;

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final p = PaletaV3.de(context);
    final suave = tema.textTheme.labelLarge?.copyWith(color: tema.colorScheme.onSurfaceVariant);
    final ok = p.oscuro ? const Color(0xFF7BD88F) : const Color(0xFF1B6B34);
    final hay = widget.hechos.isNotEmpty;
    return Semantics(
      liveRegion: true,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        InkWell(
          onTap: hay ? () => setState(() => _abierto = !_abierto) : null,
          borderRadius: BorderRadius.circular(12),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 44),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              const ExcludeSemantics(child: OrbeIa(tamano: 22, estado: EstadoOrbe.pensando)),
              const SizedBox(width: 10),
              Flexible(child: Text(widget.enCurso ?? t.iaPensando, style: suave)),
              if (hay) ...[
                const SizedBox(width: 8),
                Flexible(child: Text('· ${t.iaPasosN(widget.hechos.length)}', style: suave, maxLines: 1, overflow: TextOverflow.ellipsis)),
                ExcludeSemantics(child: Icon(_abierto ? Icons.expand_less : Icons.expand_more, size: 18, color: tema.colorScheme.onSurfaceVariant)),
              ],
            ]),
          ),
        ),
        if (_abierto)
          for (final h in widget.hechos)
            Padding(
              padding: const EdgeInsets.only(left: 6, bottom: 4),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                ExcludeSemantics(child: Icon(Icons.check, size: 16, color: ok)),
                const SizedBox(width: 8),
                Flexible(child: Text(h, style: suave)),
              ]),
            ),
      ]),
    );
  }
}
