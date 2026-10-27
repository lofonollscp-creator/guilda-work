import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../diseno/asistente.dart';
import '../l10n/app_localizations.dart';
import '../screens/ia_chat_screen.dart';
import 'servicios.dart';

/// Abre el chat del asistente desde cualquier pantalla. [consulta] se envía nada más abrirlo (las sugerencias de un toque),
/// [contexto] dice de qué trata la conversación («Tareas»…) y [contextoIa] es lo que se le cuenta al asistente con tu primer mensaje
/// (`tarea #7 «Presentar el 303»`) para que sepa de qué elemento hablas sin que tengas que explicarlo.
Future<void> abrirAsistente(BuildContext context, {String? consulta, String? contexto, String? contextoIa}) {
  final s = ProviderScope.containerOf(context, listen: false).read(serviciosProvider);
  return Navigator.of(context).push(MaterialPageRoute(
    builder: (_) => IaChatScreen(api: s.api, locale: s.locale, consultaInicial: consulta, contexto: contexto, contextoIa: contextoIa),
  ));
}

/// El botón del asistente para la barra de una pantalla: la chispa violeta, que abre el chat sabiendo de qué pantalla (o elemento) viene.
class AccionAsistente extends StatelessWidget {
  final String contexto;
  final String? contextoIa;
  const AccionAsistente({super.key, required this.contexto, this.contextoIa});

  @override
  Widget build(BuildContext context) {
    return IconButton(
      icon: Icon(Icons.auto_awesome, color: ColoresIa.de(context).acento),
      tooltip: AppLocalizations.of(context).iaPreguntarAlAsistente,
      onPressed: () => abrirAsistente(context, contexto: contexto, contextoIa: contextoIa),
    );
  }
}
