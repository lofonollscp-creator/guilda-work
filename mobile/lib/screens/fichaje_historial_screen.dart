import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../diseno/componentes.dart';

import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../theme/app_theme.dart';
import '../theme/brand_colors.dart';

/// Historial propio de fichajes (equivalente móvil de
/// app/templates/fichaje_historial.html), filtrable por fecha.
class FichajeHistorialScreen extends StatefulWidget {
  final ApiClient api;

  const FichajeHistorialScreen({super.key, required this.api});

  @override
  State<FichajeHistorialScreen> createState() => _FichajeHistorialScreenState();
}

class _FichajeHistorialScreenState extends State<FichajeHistorialScreen> {
  late Future<List<FichajeEvento>> _fichajes;
  DateTime? _desde;
  DateTime? _hasta;

  @override
  void initState() {
    super.initState();
    _fichajes = _cargar();
  }

  Future<List<FichajeEvento>> _cargar() {
    return widget.api.listarMisFichajes(
      desde: _desde?.toIso8601String().substring(0, 10),
      hasta: _hasta?.toIso8601String().substring(0, 10),
    );
  }

  Future<void> _recargar() async {
    final futuro = _cargar();
    setState(() => _fichajes = futuro);
    await futuro;
  }

  Future<void> _elegirFecha({required bool esDesde}) async {
    final elegida = await showDatePicker(
      context: context,
      initialDate: (esDesde ? _desde : _hasta) ?? DateTime.now(),
      firstDate: DateTime(2000),
      lastDate: DateTime(2100),
    );
    if (elegida == null) return;
    setState(() {
      if (esDesde) {
        _desde = elegida;
      } else {
        _hasta = elegida;
      }
    });
    await _recargar();
  }

  String _fecha(DateTime? d, AppLocalizations t) => d == null ? t.fichajeHistorialCualquiera : d.toIso8601String().substring(0, 10);

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final oscuro = tema.brightness == Brightness.dark;
    final idioma = Localizations.localeOf(context).languageCode;
    Color colorDe(String tipo) => switch (tipo) {
          'entrada' => BrandColors.success,
          'salida' => oscuro ? BrandColors.dangerDark : BrandColors.dangerLight,
          _ => oscuro ? BrandColors.warningDark : BrandColors.warningLight,
        };
    return Scaffold(
      appBar: AppBar(title: Text(t.fichajeHistorialTitulo)),
      body: Column(
        children: [
          // El rango, como dos píldoras (con la fecha escrita como en el resto de la app).
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 4),
            child: Row(children: [
              PildoraBoton(icono: Icons.event_outlined, texto: t.fichajeHistorialDesde(_fecha(_desde, t)), activo: _desde != null, alPulsar: () => _elegirFecha(esDesde: true)),
              const SizedBox(width: 8),
              PildoraBoton(icono: Icons.event_outlined, texto: t.fichajeHistorialHasta(_fecha(_hasta, t)), activo: _hasta != null, alPulsar: () => _elegirFecha(esDesde: false)),
            ]),
          ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: _recargar,
              child: FutureBuilder<List<FichajeEvento>>(
                future: _fichajes,
                builder: (context, snapshot) {
                  if (snapshot.connectionState != ConnectionState.done) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (snapshot.hasError) {
                    return Center(child: Text(mensajeDeError(t, snapshot.error!)));
                  }
                  final fichajes = snapshot.data ?? [];
                  if (fichajes.isEmpty) {
                    return ListView(children: [Padding(padding: const EdgeInsets.all(24), child: Text(t.fichajeHistorialSinFichajes))]);
                  }
                  final etiquetas = etiquetasFichaje(t);
                  // Agrupados por día, cada día en su tarjeta con sus marcas en orden.
                  final porDia = <String, List<FichajeEvento>>{};
                  for (final f in fichajes) {
                    porDia.putIfAbsent(f.marcaTiempo.substring(0, 10), () => []).add(f);
                  }
                  final dias = porDia.keys.toList()..sort((a, b) => b.compareTo(a));
                  return ListView(padding: const EdgeInsets.fromLTRB(12, 4, 12, 24), children: [
                    for (final dia in dias)
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: Card(
                          margin: EdgeInsets.zero,
                          child: Padding(
                            padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Text(
                                toBeginningOfSentenceCase(DateFormat.MMMMEEEEd(idioma).format(DateTime.parse(dia))) ?? dia,
                                style: tema.textTheme.titleSmall,
                              ),
                              const SizedBox(height: 4),
                              for (final f in porDia[dia]!)
                                Padding(
                                  padding: const EdgeInsets.symmetric(vertical: 6),
                                  child: Row(children: [
                                    Container(width: 10, height: 10, decoration: BoxDecoration(color: colorDe(f.tipo), shape: BoxShape.circle)),
                                    const SizedBox(width: 12),
                                    Expanded(child: Text(etiquetas[f.tipo] ?? f.tipo, style: tema.textTheme.bodyLarge)),
                                    if (f.origen == 'correccion_admin') Padding(padding: const EdgeInsets.only(right: 8), child: Tooltip(message: t.fichajeHistorialCorreccionAdmin, child: const Icon(Icons.info_outline, size: 18))),
                                    Text(f.marcaTiempo.substring(11, 16), style: AppTheme.cifra(fontSize: 16)),
                                  ]),
                                ),
                            ]),
                          ),
                        ),
                      ),
                  ]);
                },
              ),
            ),
          ),
        ],
      ),
    );
  }
}
