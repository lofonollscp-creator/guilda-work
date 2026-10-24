import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../l10n/app_localizations.dart';
import '../../nucleo/abrir_destino.dart';
import '../../nucleo/destinos.dart';
import '../../nucleo/servicios.dart';

/// Un resultado de la búsqueda global (`GET /buscar`).
class ResultadoBusqueda {
  final String tipo;
  final String texto;
  final Destino destino;
  final String? url;
  const ResultadoBusqueda(this.tipo, this.texto, this.destino, this.url);

  factory ResultadoBusqueda.desdeJson(Map<String, dynamic> j) => ResultadoBusqueda(
        j['tipo']?.toString() ?? '',
        (j['texto'] ?? '').toString(),
        j['destino'] is Map ? Destino.desdeJson(j['destino'] as Map) : const Destino('aviso'),
        j['url']?.toString(),
      );
}

/// La búsqueda como función, para poder sustituirla en las pruebas.
typedef Buscador = Future<List<ResultadoBusqueda>> Function(String texto);

final buscadorProvider = Provider<Buscador>((ref) => (texto) async {
      final crudo = await ref.read(clienteApiProvider).enviar('GET', '/buscar', consulta: {'q': texto, 'limit': 20});
      return [for (final r in crudo as List) ResultadoBusqueda.desdeJson(Map<String, dynamic>.from(r as Map))];
    });

/// Búsqueda global en notas, tareas y correo. Busca al dejar de escribir (350 ms) y desde dos letras.
class BusquedaScreen extends ConsumerStatefulWidget {
  const BusquedaScreen({super.key});

  @override
  ConsumerState<BusquedaScreen> createState() => _BusquedaScreenState();
}

class _BusquedaScreenState extends ConsumerState<BusquedaScreen> {
  final _controlador = TextEditingController();
  Timer? _espera;
  List<ResultadoBusqueda>? _resultados;
  String _consulta = '';
  bool _buscando = false;
  bool _error = false;

  @override
  void dispose() {
    _espera?.cancel();
    _controlador.dispose();
    super.dispose();
  }

  void _alEscribir(String texto) {
    _espera?.cancel();
    final q = texto.trim();
    if (q.length < 2) {
      setState(() {
        _resultados = null;
        _consulta = q;
        _error = false;
        _buscando = false;
      });
      return;
    }
    _espera = Timer(const Duration(milliseconds: 350), () => _buscar(q));
  }

  Future<void> _buscar(String q) async {
    setState(() {
      _buscando = true;
      _error = false;
      _consulta = q;
    });
    try {
      final r = await ref.read(buscadorProvider)(q);
      if (!mounted || q != _consulta) return; // ya se escribió otra cosa
      setState(() {
        _resultados = r;
        _buscando = false;
      });
    } catch (_) {
      if (!mounted || q != _consulta) return;
      setState(() {
        _error = true;
        _buscando = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: TextField(
          controller: _controlador,
          autofocus: true,
          textInputAction: TextInputAction.search,
          decoration: InputDecoration(hintText: t.busquedaHint, border: InputBorder.none),
          onChanged: _alEscribir,
          onSubmitted: (v) {
            _espera?.cancel();
            if (v.trim().length >= 2) _buscar(v.trim());
          },
        ),
        actions: [
          if (_controlador.text.isNotEmpty)
            IconButton(icon: const Icon(Icons.close), tooltip: t.comunCancelar, onPressed: () {
              _controlador.clear();
              _alEscribir('');
            }),
        ],
      ),
      body: _cuerpo(t),
    );
  }

  Widget _cuerpo(AppLocalizations t) {
    if (_error) return Center(child: Text(t.busquedaError));
    if (_buscando && _resultados == null) return const Center(child: CircularProgressIndicator());
    final r = _resultados;
    if (r == null) return Center(child: Text(t.busquedaMinimo));
    if (r.isEmpty) return Center(child: Text(t.busquedaSinResultados(_consulta)));
    return ListView.separated(
      itemCount: r.length,
      separatorBuilder: (_, _) => const Divider(height: 1),
      itemBuilder: (context, i) {
        final x = r[i];
        return ListTile(
          leading: Icon(_icono(x.tipo)),
          title: Text(x.texto, maxLines: 2, overflow: TextOverflow.ellipsis),
          subtitle: Text(_etiqueta(t, x.tipo)),
          onTap: () => ref.read(navegadorDeAvisosProvider).abrir(x.destino, urlWeb: x.url),
        );
      },
    );
  }

  IconData _icono(String tipo) => switch (tipo) {
        'nota' => Icons.sticky_note_2_outlined,
        'tarea' => Icons.checklist,
        'mensaje' => Icons.mail_outline,
        'vencimiento_fiscal' => Icons.calendar_month_outlined,
        'cliente_fiscal' => Icons.business_outlined,
        _ => Icons.search,
      };

  String _etiqueta(AppLocalizations t, String tipo) => switch (tipo) {
        'nota' => t.busquedaTipoNota,
        'tarea' => t.busquedaTipoTarea,
        'mensaje' => t.busquedaTipoCorreo,
        'vencimiento_fiscal' => t.busquedaTipoVencimiento,
        'cliente_fiscal' => t.busquedaTipoCliente,
        _ => tipo,
      };
}
