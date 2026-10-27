import 'package:flutter/material.dart';

import '../diseno/adaptable.dart';

import '../nucleo/abrir_asistente.dart';

import '../l10n/app_localizations.dart';

import '../services/api_client.dart';
import 'correo_reglas_categoria_screen.dart';
import 'correo_remitentes_confiables_screen.dart';

/// Ajustes de correo en el móvil (Fase 5): punto de entrada a las dos
/// pantallas de gestión nuevas — remitentes de confianza y reglas de
/// categorización — mismo concepto que "Ajustes de correo" en la web.
class CorreoAjustesScreen extends StatelessWidget {
  final ApiClient api;

  const CorreoAjustesScreen({super.key, required this.api});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(AppLocalizations.of(context).correoAjustesTitulo), actions: [AccionAsistente(contexto: AppLocalizations.of(context).correoAjustesTitulo)]),
      body: AnchoMaximo(child: ListView(
        children: [
          ListTile(
            leading: const Icon(Icons.shield_outlined),
            title: Text(AppLocalizations.of(context).correoRemitentesTitulo),
            subtitle: Text(AppLocalizations.of(context).correoRemitentesSub),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => CorreoRemitentesConfiablesScreen(api: api)),
            ),
          ),
          ListTile(
            leading: const Icon(Icons.rule),
            title: Text(AppLocalizations.of(context).correoReglasTitulo),
            subtitle: Text(AppLocalizations.of(context).correoReglasSub),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => CorreoReglasCategoriaScreen(api: api)),
            ),
          ),
        ],
      )),
    );
  }
}
