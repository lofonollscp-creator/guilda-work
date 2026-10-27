import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../diseno/adaptable.dart';
import '../diseno/asistente.dart';
import '../l10n/app_localizations.dart';
import '../screens/ia_chat_screen.dart';
import 'servicios.dart';

/// ¿Está abierto el panel del asistente junto a la pantalla? Solo cabe en una tableta ancha; se cierra con su aspa y se reabre con la chispa de la barra.
/// Es el mismo para Tareas, Notas y Correo: lo que decidas en una vale para las otras.
class PanelAsistenteAbierto extends Notifier<bool> {
  @override
  bool build() => true;
  void poner(bool abierto) => state = abierto;
}

final panelAsistenteAbiertoProvider = NotifierProvider<PanelAsistenteAbierto, bool>(PanelAsistenteAbierto.new);

const anchoPanelAsistente = 340.0;

/// Ancho mínimo para tener en Tareas la lista, la ficha y el asistente a la vez.
const anchoConAsistente = 1280.0;

/// ¿Cabe el panel? En una tableta y con al menos [anchoMinimo] de ancho en total (lo que necesita lo demás de la pantalla más el panel).
bool cabePanelAsistente(BuildContext context, double anchoMinimo) => esAncha(context) && MediaQuery.sizeOf(context).width >= anchoMinimo;

/// El chat del asistente como columna lateral, con su cabecera y su aspa.
class PanelAsistente extends ConsumerWidget {
  final String contexto;
  final String? contextoIa;
  const PanelAsistente({super.key, required this.contexto, this.contextoIa});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.read(serviciosProvider);
    return SizedBox(
      width: anchoPanelAsistente,
      child: IaChatScreen(
        api: s.api,
        locale: s.locale,
        contexto: contexto,
        contextoIa: contextoIa,
        alCerrar: () => ref.read(panelAsistenteAbiertoProvider.notifier).poner(false),
      ),
    );
  }
}

/// Una pantalla con el panel del asistente a su derecha cuando hay sitio ([anchoMinimo]) y está abierto; si no, la pantalla sola.
class ConAsistenteLateral extends ConsumerWidget {
  final String contexto;
  final String? contextoIa;
  final double anchoMinimo;
  final Widget hijo;
  const ConAsistenteLateral({super.key, required this.contexto, this.contextoIa, this.anchoMinimo = 900, required this.hijo});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!cabePanelAsistente(context, anchoMinimo) || !ref.watch(panelAsistenteAbiertoProvider)) return hijo;
    return Row(children: [
      Expanded(child: hijo),
      VerticalDivider(width: 1, color: Theme.of(context).colorScheme.outlineVariant),
      PanelAsistente(contexto: contexto, contextoIa: contextoIa),
    ]);
  }
}

/// La chispa que reabre el panel cuando está cerrado (y cabe); sin sitio para el panel o con él abierto, no se pinta.
class ReabrirAsistente extends ConsumerWidget {
  final double anchoMinimo;
  const ReabrirAsistente({super.key, required this.anchoMinimo});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!cabePanelAsistente(context, anchoMinimo) || ref.watch(panelAsistenteAbiertoProvider)) return const SizedBox.shrink();
    return IconButton(
      icon: Icon(Icons.auto_awesome, color: ColoresIa.de(context).acento),
      tooltip: AppLocalizations.of(context).iaPreguntarAlAsistente,
      onPressed: () => ref.read(panelAsistenteAbiertoProvider.notifier).poner(true),
    );
  }
}
