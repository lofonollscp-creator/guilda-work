import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../diseno/v3/v3.dart';
import '../l10n/app_localizations.dart';
import '../screens/ia_chat_screen.dart';
import 'servicios.dart';

/// Un destino de la barra: su icono (con y sin selección) y su etiqueta, siempre visible.
class DestinoBarra {
  final IconData icono;
  final IconData iconoActivo;
  final String etiqueta;
  const DestinoBarra(this.icono, this.iconoActivo, this.etiqueta);
}

/// La barra inferior v3: una píldora de vidrio con los destinos a los lados y el botón ✦ del asistente en el centro, con su aura.
/// [seleccionado] es el índice dentro de [destinos] (o null si la pestaña de ahora no está en la barra); el ✦ se reparte la mitad: [destinos] se parte por la mitad.
class BarraNavegacion extends StatelessWidget {
  final List<DestinoBarra> destinos;
  final int? seleccionado;
  final ValueChanged<int> alElegir;
  final VoidCallback alAsistente;

  /// Propuestas del asistente esperando tu respuesta: se ven como una insignia en el ✦.
  final int propuestas;
  const BarraNavegacion({super.key, required this.destinos, required this.seleccionado, required this.alElegir, required this.alAsistente, this.propuestas = 0});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final mitad = destinos.length ~/ 2;
    Widget destino(int i) => Expanded(
          child: _ItemBarra(destino: destinos[i], activo: seleccionado == i, alPulsar: () {
            Haptica.seleccion();
            alElegir(i);
          }),
        );
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
      child: Vidrio(
        radio: BorderRadius.circular(32),
        child: SizedBox(
          height: 68,
          child: Row(children: [
            for (var i = 0; i < mitad; i++) destino(i),
            _BotonAsistente(etiqueta: t.dashboardAsistenteIaTooltip, propuestas: propuestas, alPulsar: () {
              Haptica.toque();
              alAsistente();
            }),
            for (var i = mitad; i < destinos.length; i++) destino(i),
          ]),
        ),
      ),
    );
  }
}

class _ItemBarra extends StatelessWidget {
  final DestinoBarra destino;
  final bool activo;
  final VoidCallback alPulsar;
  const _ItemBarra({required this.destino, required this.activo, required this.alPulsar});

  @override
  Widget build(BuildContext context) {
    final p = PaletaV3.de(context);
    final tema = Theme.of(context);
    // El activo va en el color de texto pleno (contraste AA sobre el vidrio); el resto, en el suave.
    final color = activo ? p.texto : p.textoSuave;
    return Semantics(
      button: true,
      selected: activo,
      label: destino.etiqueta,
      onTap: alPulsar,
      excludeSemantics: true,
      child: InkWell(
        onTap: alPulsar,
        borderRadius: BorderRadius.circular(24),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          AnimatedContainer(
            duration: V3.durCorta,
            curve: V3.curvaEntrada,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            decoration: BoxDecoration(color: activo ? p.acento.withValues(alpha: p.oscuro ? 0.28 : 0.45) : Colors.transparent, borderRadius: BorderRadius.circular(16)),
            child: Icon(activo ? destino.iconoActivo : destino.icono, size: 24, color: color),
          ),
          const SizedBox(height: 2),
          Text(destino.etiqueta, maxLines: 1, overflow: TextOverflow.ellipsis, style: tema.textTheme.labelSmall?.copyWith(color: color, fontWeight: activo ? FontWeight.w800 : FontWeight.w600)),
        ]),
      ),
    );
  }
}

/// El ✦: un círculo violeta con el aura viva detrás. Es el centro de la app.
class _BotonAsistente extends StatelessWidget {
  final String etiqueta;
  final int propuestas;
  final VoidCallback alPulsar;
  const _BotonAsistente({required this.etiqueta, required this.propuestas, required this.alPulsar});

  @override
  Widget build(BuildContext context) {
    final ia = PaletaV3.de(context).ia;
    return Semantics(
      button: true,
      label: propuestas > 0 ? '$etiqueta. ${AppLocalizations.of(context).propuestasHoy(propuestas)}' : etiqueta,
      onTap: alPulsar,
      excludeSemantics: true,
      child: Pulsable(
        alPulsar: alPulsar,
        vibrar: false,
        radio: BorderRadius.circular(32),
        child: SizedBox(
          width: 72,
          height: 68,
          child: Center(
            child: Badge(
              isLabelVisible: propuestas > 0,
              label: Text(propuestas > 9 ? '9+' : '$propuestas'),
              offset: const Offset(2, -2),
              child: Container(
              width: 56,
              height: 56,
              decoration: BoxDecoration(shape: BoxShape.circle, color: ia.acento, boxShadow: [BoxShadow(color: ia.acento.withValues(alpha: 0.45), blurRadius: 18, spreadRadius: 1)]),
              child: Aura(
                radio: BorderRadius.circular(28),
                intensidad: 0.9,
                periodo: const Duration(seconds: 8),
                child: Center(child: Icon(Icons.auto_awesome, size: 28, color: ia.sobreAcento)),
              ),
            ),
            ),
          ),
        ),
      ),
    );
  }
}

/// «✦ Pídeme algo…»: la barra del asistente que flota sobre la de navegación. Un toque abre el chat como hoja, con el teclado listo.
class BarraPideme extends StatelessWidget {
  final VoidCallback alPulsar;
  const BarraPideme({super.key, required this.alPulsar});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final p = PaletaV3.de(context);
    final tema = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 4),
      child: Vidrio(
        radio: BorderRadius.circular(28),
        child: Pulsable(
          alPulsar: alPulsar,
          radio: BorderRadius.circular(28),
          etiqueta: t.iaPideme,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 52),
            child: ExcludeSemantics(
              child: Row(children: [
                const SizedBox(width: 16),
                Icon(Icons.auto_awesome, size: 20, color: p.ia.acento),
                const SizedBox(width: 10),
                Expanded(child: Text(t.iaPideme, style: tema.textTheme.bodyLarge?.copyWith(color: p.textoSuave))),
                Padding(padding: const EdgeInsets.only(right: 16), child: Icon(Icons.mic_none, size: 22, color: p.textoSuave)),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

/// Abre el asistente como hoja que sube sobre la pantalla (se queda debajo, a la vista). La conversación es la misma de siempre: la guarda el servidor.
Future<void> abrirHojaAsistente(BuildContext context, {String? consulta, String? contexto, String? contextoIa, bool enfocar = false}) {
  final s = ProviderScope.containerOf(context, listen: false).read(serviciosProvider);
  final alto = MediaQuery.sizeOf(context).height * 0.9;
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    showDragHandle: true,
    builder: (hoja) => SizedBox(
      height: alto,
      child: IaChatScreen(api: s.api, locale: s.locale, consultaInicial: consulta, contexto: contexto, contextoIa: contextoIa, enfocar: enfocar, alCerrar: () => Navigator.of(hoja).pop()),
    ),
  );
}
