import 'package:flutter/material.dart';

import '../../diseno/asistente.dart';
import '../../l10n/app_localizations.dart';
import 'asistente_controlador.dart';
import 'asistente_piezas.dart';

/// Con la conversación empezada, tres atajos encima del campo de texto (vacía, ya salen como tarjetas).
class AtajosRapidos extends StatelessWidget {
  final AsistenteControlador c;
  final ValueChanged<String> alEnviar;
  const AtajosRapidos({super.key, required this.c, required this.alEnviar});

  @override
  Widget build(BuildContext context) {
    if (c.mensajes.isEmpty || c.pendiente != null || c.enviando || c.cargando) return const SizedBox.shrink();
    final t = AppLocalizations.of(context);
    return SizedBox(
      height: 52,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        children: [
          for (final s in sugerenciasDeContexto(t, c.contextoVisible ? c.contextoIa : null).take(3))
            Padding(padding: const EdgeInsets.only(right: 8), child: ChipIa(texto: s, alPulsar: () => alEnviar(s))),
        ],
      ),
    );
  }
}

/// El campo de escritura con lo que lo rodea: adjuntar, dictar y enviar (que mientras responde pasa a ser «Detener»).
class CajaEntrada extends StatelessWidget {
  final AsistenteControlador c;
  final TextEditingController campo;
  final VoidCallback alEnviar;
  final VoidCallback alAdjuntar;
  const CajaEntrada({super.key, required this.c, required this.campo, required this.alEnviar, required this.alAdjuntar});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final bloqueado = c.pendiente != null;
    final enviando = c.enviando;
    final voz = c.voz;
    return Container(
      decoration: BoxDecoration(color: tema.colorScheme.surface, border: Border(top: BorderSide(color: tema.colorScheme.outlineVariant))),
      padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        if (c.subiendo || c.adjunto != null) _AdjuntoPendiente(c: c),
        Row(children: [
          IconButton(
            icon: const Icon(Icons.add),
            tooltip: t.iaAdjuntar,
            constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
            onPressed: (bloqueado || enviando || c.subiendo) ? null : alAdjuntar,
          ),
          if (voz.disponible) ...[
            IconButton.outlined(
              icon: Icon(voz.escuchando ? Icons.mic : Icons.mic_none),
              tooltip: t.iaDictar,
              style: voz.escuchando ? IconButton.styleFrom(backgroundColor: tema.colorScheme.error, foregroundColor: Colors.white) : null,
              onPressed: (bloqueado || enviando) ? null : voz.alternarMicrofono,
            ),
            const SizedBox(width: 8),
          ],
          Expanded(
            child: TextField(
              controller: campo,
              enabled: !bloqueado && !enviando,
              minLines: 1,
              maxLines: 4,
              textCapitalization: TextCapitalization.sentences,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => alEnviar(),
              decoration: InputDecoration(
                hintText: bloqueado ? t.iaResponderConfirmacion : t.iaEscribeMensaje,
                filled: true,
                fillColor: tema.colorScheme.surfaceContainerHighest.withValues(alpha: 0.5),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide.none),
                enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide.none),
                disabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide.none),
                contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
              ),
            ),
          ),
          const SizedBox(width: 4),
          // Mientras responde, el botón de enviar pasa a ser «Detener».
          IconButton.filled(
            style: IconButton.styleFrom(backgroundColor: ColoresIa.de(context).acento, foregroundColor: ColoresIa.de(context).sobreAcento),
            icon: Icon(enviando ? Icons.stop_rounded : Icons.arrow_upward),
            tooltip: enviando ? t.iaDetener : t.comunEnviar,
            onPressed: enviando ? c.detener : ((bloqueado || c.subiendo) ? null : alEnviar),
          ),
        ]),
      ]),
    );
  }
}

/// El archivo que irá con el próximo mensaje: subiéndose o ya listo, con su aspa para quitarlo.
class _AdjuntoPendiente extends StatelessWidget {
  final AsistenteControlador c;
  const _AdjuntoPendiente({required this.c});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final colores = ColoresIa.de(context);
    final nombre = c.adjunto?.nombre;
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 6, right: 4),
        padding: const EdgeInsets.only(left: 12),
        decoration: BoxDecoration(color: colores.fondo, border: Border.all(color: colores.borde), borderRadius: BorderRadius.circular(999)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (nombre == null)
            const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
          else
            ExcludeSemantics(child: Icon(Icons.attach_file, size: 16, color: colores.sobreFondo)),
          const SizedBox(width: 6),
          Flexible(child: Text(nombre ?? t.iaAdjuntoSubiendo, maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.labelLarge?.copyWith(color: colores.sobreFondo))),
          if (nombre != null)
            IconButton(
              icon: Icon(Icons.close, size: 18, color: colores.sobreFondo),
              tooltip: t.iaAdjuntoQuitar,
              constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: c.quitarAdjunto,
            )
          else
            const SizedBox(width: 12),
        ]),
      ),
    );
  }
}
