import 'package:flutter/material.dart';
import 'package:table_calendar/table_calendar.dart';

import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../widgets/status_badge.dart';
import 'fiscal_vencimiento_edit_screen.dart';

/// Calendario mensual de vencimientos fiscales -- primera vista de
/// calendario que existe en la app móvil (ni tareas ni fiscal tenían
/// ninguna hasta ahora), equivalente visual de
/// app/templates/tareas_calendario.html pero SOLO con los vencimientos
/// fiscales (el nombre del archivo sigue el del plan original, que
/// contemplaba combinar tareas normales -- se deja fuera de esta v1 por
/// alcance: no hay hoy un endpoint REST de tareas agrupadas por fecha,
/// añadirlo sería una función nueva aparte del calendario fiscal en sí;
/// se puede retomar más adelante sin tocar esta pantalla).
///
/// Sin Scaffold/AppBar propios a propósito: vive como una de las 3
/// pestañas de FiscalScreen (fiscal_screen.dart), no como ruta
/// independiente -- un AppBar aquí duplicaría el de esa pantalla.
class TareasCalendarioScreen extends StatefulWidget {
  final ApiClient api;

  const TareasCalendarioScreen({super.key, required this.api});

  @override
  State<TareasCalendarioScreen> createState() => _TareasCalendarioScreenState();
}

class _TareasCalendarioScreenState extends State<TareasCalendarioScreen> {
  late Future<List<VencimientoFiscal>> _vencimientos;
  DateTime _focusedDay = DateTime.now();
  DateTime? _selectedDay;
  Map<DateTime, List<VencimientoFiscal>> _porDia = {};

  @override
  void initState() {
    super.initState();
    _selectedDay = DateTime.now();
    _vencimientos = _cargar();
  }

  Future<List<VencimientoFiscal>> _cargar() async {
    final lista = await widget.api.listarVencimientosFiscales();
    _porDia = {};
    for (final v in lista) {
      final fecha = DateTime.parse(v.fechaLimite.substring(0, 10));
      final clave = DateTime(fecha.year, fecha.month, fecha.day);
      _porDia.putIfAbsent(clave, () => []).add(v);
    }
    return lista;
  }

  List<VencimientoFiscal> _eventosDelDia(DateTime dia) {
    return _porDia[DateTime(dia.year, dia.month, dia.day)] ?? [];
  }

  Future<void> _recargar() async {
    final futuro = _cargar();
    setState(() => _vencimientos = futuro);
    await futuro;
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return FutureBuilder<List<VencimientoFiscal>>(
      future: _vencimientos,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return Center(
            child: Text(t.comunErrorCargar(snapshot.error.toString())),
          );
        }
        final eventosDia = _selectedDay != null
            ? _eventosDelDia(_selectedDay!)
            : <VencimientoFiscal>[];
        return Column(
          children: [
            TableCalendar<VencimientoFiscal>(
              firstDay: DateTime.utc(2020, 1, 1),
              lastDay: DateTime.utc(2100, 12, 31),
              focusedDay: _focusedDay,
              selectedDayPredicate: (day) => isSameDay(_selectedDay, day),
              eventLoader: _eventosDelDia,
              onDaySelected: (selected, focused) {
                setState(() {
                  _selectedDay = selected;
                  _focusedDay = focused;
                });
              },
              onPageChanged: (focused) => _focusedDay = focused,
              calendarStyle: CalendarStyle(
                markerDecoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.error,
                  shape: BoxShape.circle,
                ),
                selectedDecoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.primary,
                  shape: BoxShape.circle,
                ),
                todayDecoration: BoxDecoration(
                  color: Theme.of(
                    context,
                  ).colorScheme.primary.withValues(alpha: 0.35),
                  shape: BoxShape.circle,
                ),
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: RefreshIndicator(
                onRefresh: _recargar,
                child: eventosDia.isEmpty
                    ? ListView(
                        children: [
                          Padding(
                            padding: const EdgeInsets.all(24),
                            child: Text(t.fiscalCalendarioSinVencimientos),
                          ),
                        ],
                      )
                    : ListView.builder(
                        itemCount: eventosDia.length,
                        itemBuilder: (context, i) =>
                            _tarjetaVencimiento(eventosDia[i], t),
                      ),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _tarjetaVencimiento(VencimientoFiscal v, AppLocalizations t) {
    final tono = switch (v.estado) {
      'presentado' => BadgeTono.exito,
      'fuera_plazo' => BadgeTono.peligro,
      _ => BadgeTono.aviso,
    };
    final etiquetaEstado = estadosVencimientoFiscal(t)
        .firstWhere((e) => e.$1 == v.estado, orElse: () => (v.estado, v.estado))
        .$2;
    return ListTile(
      leading: const Icon(Icons.receipt_long_outlined),
      title: Text('${v.modelo} — ${v.clienteNombre}'),
      subtitle: Wrap(
        spacing: 8,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          Text(v.periodo),
          StatusBadge(texto: etiquetaEstado, tono: tono),
        ],
      ),
      onTap: () async {
        final cambiado = await Navigator.of(context).push<bool>(
          MaterialPageRoute(
            builder: (_) =>
                FiscalVencimientoEditScreen(api: widget.api, vencimiento: v),
          ),
        );
        if (cambiado == true) await _recargar();
      },
    );
  }
}
