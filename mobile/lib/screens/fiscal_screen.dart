import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../services/api_client.dart';
import 'fiscal_clientes_screen.dart';
import 'fiscal_vencimientos_screen.dart';
import 'tareas_calendario_screen.dart';

/// Entrada única del "Calendario fiscal" en móvil -- equivalente al
/// subnav de la web (Clientes / Vencimientos / Papelera en
/// app/templates/fiscal_clientes.html), aquí como TabBar en vez de 3
/// pantallas sueltas encadenadas con Navigator.push: menos saltos para
/// moverse entre las tres vistas relacionadas. La papelera no tiene
/// pestaña propia en esta v1 (no hay tanto volumen en móvil como para
/// necesitarla de entrada; restaurar/purgar un cliente o vencimiento
/// eliminado por error sigue disponible desde la web).
class FiscalScreen extends StatelessWidget {
  final ApiClient api;

  const FiscalScreen({super.key, required this.api});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: Text(t.fiscalTitulo),
          bottom: TabBar(
            tabs: [
              Tab(text: t.fiscalTabClientes),
              Tab(text: t.fiscalTabVencimientos),
              Tab(text: t.fiscalTabCalendario),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            FiscalClientesScreen(api: api),
            FiscalVencimientosScreen(api: api),
            TareasCalendarioScreen(api: api),
          ],
        ),
      ),
    );
  }
}
