import 'package:flutter/material.dart';

import '../models/models.dart';
import '../services/api_client.dart';
import '../theme/app_theme.dart';

/// Qué mostrar en HistorialRapidoScreen -- a qué corresponde cada stat
/// pulsable del dashboard (en curso / notas hoy). "Correos sin leer" no
/// usa esta pantalla: ya tiene su propia (CorreoBandejaScreen).
enum FiltroHistorialRapido { enCurso, notasHoy }

/// Vista rápida y filtrada del histórico completo (todas las categorías),
/// reutilizando GET /historial sin categoria_id -- a petición del usuario,
/// para que las cifras "en curso"/"notas hoy" del dashboard lleven a algún
/// sitio en vez de ser solo decorativas. No existía antes una pantalla que
/// cruzara categorías, así que el filtro se aplica en el cliente sobre el
/// histórico completo (la API no tiene un parámetro "solo activas"/"solo
/// hoy" -- añadirlo no compensaba para esta vista puntual).
class HistorialRapidoScreen extends StatefulWidget {
  final ApiClient api;
  final FiltroHistorialRapido filtro;
  final String titulo;

  const HistorialRapidoScreen({super.key, required this.api, required this.filtro, required this.titulo});

  @override
  State<HistorialRapidoScreen> createState() => _HistorialRapidoScreenState();
}

class _HistorialRapidoScreenState extends State<HistorialRapidoScreen> {
  late Future<List<EntradaHistorial>> _entradas;

  @override
  void initState() {
    super.initState();
    _entradas = _cargar();
  }

  Future<List<EntradaHistorial>> _cargar() async {
    final todas = await widget.api.historial();
    final hoy = DateTime.now().toIso8601String().substring(0, 10);
    return todas.where((f) {
      switch (widget.filtro) {
        case FiltroHistorialRapido.enCurso:
          return f.origen == 'tarea' && f.tipo == 'duracion' && f.estado == 'en_curso';
        case FiltroHistorialRapido.notasHoy:
          return f.origen == 'nota' && (f.timestamp?.startsWith(hoy) ?? false);
      }
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.titulo)),
      body: FutureBuilder<List<EntradaHistorial>>(
        future: _entradas,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text('${snapshot.error}'));
          }
          final entradas = snapshot.data ?? [];
          if (entradas.isEmpty) {
            return const Center(child: Padding(padding: EdgeInsets.all(24), child: Text('Nada que mostrar aquí ahora mismo.')));
          }
          return ListView.builder(
            itemCount: entradas.length,
            itemBuilder: (context, i) => _tarjeta(entradas[i]),
          );
        },
      ),
    );
  }

  Widget _tarjeta(EntradaHistorial f) {
    final hora = f.timestamp != null && f.timestamp!.length >= 16 ? f.timestamp!.substring(11, 16) : '';
    String? duracion;
    if (f.duracionSegundos != null) {
      final h = f.duracionSegundos! ~/ 3600;
      final m = (f.duracionSegundos! % 3600) ~/ 60;
      duracion = '${h}h ${m}m';
    }
    return ListTile(
      leading: Text(hora, style: AppTheme.cifra(fontSize: 13, fontWeight: FontWeight.w400)),
      title: Text(f.texto),
      subtitle: f.categoriaNombre != null ? Text(f.categoriaNombre!) : null,
      trailing: duracion != null ? Text(duracion, style: AppTheme.cifra(fontSize: 13)) : null,
    );
  }
}
