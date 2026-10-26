import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../diseno/componentes.dart';
import '../../diseno/formatos.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/abrir_destino.dart';
import '../../nucleo/destinos.dart';
import '../../nucleo/servicios.dart';

/// Un resultado de la búsqueda global (`GET /buscar`).
class ResultadoBusqueda {
  final String tipo;
  final String texto;
  final String titulo;
  final String fragmento;
  final String? fecha;
  final Destino destino;
  final String? url;
  const ResultadoBusqueda(this.tipo, this.texto, this.destino, this.url, {String? titulo, this.fragmento = '', this.fecha}) : titulo = titulo ?? texto;

  factory ResultadoBusqueda.desdeJson(Map<String, dynamic> j) {
    final texto = (j['texto'] ?? '').toString();
    final titulo = (j['titulo'] ?? '').toString();
    return ResultadoBusqueda(
      j['tipo']?.toString() ?? '',
      texto,
      j['destino'] is Map ? Destino.desdeJson(j['destino'] as Map) : const Destino('aviso'),
      j['url']?.toString(),
      titulo: titulo.isEmpty ? texto : titulo,
      fragmento: (j['fragmento'] ?? '').toString(),
      fecha: j['fecha']?.toString(),
    );
  }
}

/// La búsqueda como función, para poder sustituirla en las pruebas.
typedef Buscador = Future<List<ResultadoBusqueda>> Function(String texto);

final buscadorProvider = Provider<Buscador>((ref) => (texto) async {
      final crudo = await ref.read(clienteApiProvider).enviar('GET', '/buscar', consulta: {'q': texto, 'limit': 40});
      return [for (final r in crudo as List) ResultadoBusqueda.desdeJson(Map<String, dynamic>.from(r as Map))];
    });

/// Lo último que se buscó (hasta 8, lo más reciente primero), guardado en el dispositivo.
class BusquedasRecientes extends Notifier<List<String>> {
  static const _clave = 'busquedas_recientes';
  static const maximo = 8;

  @override
  List<String> build() {
    unawaited(_cargar());
    return const [];
  }

  Future<void> _cargar() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      state = prefs.getStringList(_clave) ?? const [];
    } catch (_) {
      // sin almacenamiento: no hay recientes y ya está
    }
  }

  Future<void> anotar(String texto) async {
    final q = texto.trim();
    if (q.length < 2) return;
    state = [q, for (final r in state) if (r.toLowerCase() != q.toLowerCase()) r].take(maximo).toList();
    await _guardar();
  }

  Future<void> borrar() async {
    state = const [];
    await _guardar();
  }

  Future<void> _guardar() async {
    try {
      (await SharedPreferences.getInstance()).setStringList(_clave, state);
    } catch (_) {
      // idem
    }
  }
}

final busquedasRecientesProvider = NotifierProvider<BusquedasRecientes, List<String>>(BusquedasRecientes.new);

/// Los grupos de la fila de píldoras: Todo · Tareas · Notas · Correo · Fiscal.
enum _Grupo {
  todo,
  tareas,
  notas,
  correo,
  fiscal;

  bool admite(String tipo) => switch (this) {
        _Grupo.todo => true,
        _Grupo.tareas => tipo == 'tarea',
        _Grupo.notas => tipo == 'nota',
        _Grupo.correo => tipo == 'mensaje',
        _Grupo.fiscal => tipo == 'vencimiento_fiscal' || tipo == 'cliente_fiscal',
      };

  String etiqueta(AppLocalizations t) => switch (this) {
        _Grupo.todo => t.busquedaFiltroTodo,
        _Grupo.tareas => t.busquedaFiltroTareas,
        _Grupo.notas => t.busquedaFiltroNotas,
        _Grupo.correo => t.busquedaFiltroCorreo,
        _Grupo.fiscal => t.busquedaFiltroFiscal,
      };
}

/// Búsqueda global en notas, tareas, correo y calendario fiscal. Busca al dejar de escribir (350 ms) y desde dos letras;
/// los resultados se filtran por tipo con una fila de píldoras y lo escrito se resalta en ellos.
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
  _Grupo _grupo = _Grupo.todo;

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
        _grupo = _Grupo.todo;
      });
    } catch (_) {
      if (!mounted || q != _consulta) return;
      setState(() {
        _error = true;
        _buscando = false;
      });
    }
  }

  void _usarReciente(String q) {
    _controlador.text = q;
    _controlador.selection = TextSelection.collapsed(offset: q.length);
    _espera?.cancel();
    _buscar(q);
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 0,
        title: Padding(
          padding: const EdgeInsets.only(right: 12),
          child: TextField(
            controller: _controlador,
            autofocus: true,
            textInputAction: TextInputAction.search,
            decoration: InputDecoration(
              hintText: t.busquedaHint,
              prefixIcon: const Icon(Icons.search),
              suffixIcon: _controlador.text.isEmpty
                  ? null
                  : IconButton(icon: const Icon(Icons.close), tooltip: t.comunCancelar, onPressed: () {
                      _controlador.clear();
                      _alEscribir('');
                    }),
              filled: true,
              fillColor: tema.colorScheme.surfaceContainerHighest,
              contentPadding: const EdgeInsets.symmetric(vertical: 10),
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide.none),
              enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide.none),
              focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide(color: tema.colorScheme.primary, width: 1.5)),
            ),
            onChanged: (v) {
              setState(() {}); // la «x»
              _alEscribir(v);
            },
            onSubmitted: (v) {
              _espera?.cancel();
              if (v.trim().length >= 2) _buscar(v.trim());
            },
          ),
        ),
      ),
      body: _cuerpo(t),
    );
  }

  Widget _cuerpo(AppLocalizations t) {
    if (_error) return EstadoError(error: Exception(), alReintentar: () => _buscar(_consulta));
    if (_buscando && _resultados == null) return const EsqueletoLista(filas: 5);
    final r = _resultados;
    if (r == null) return _Recientes(alElegir: _usarReciente);
    if (r.isEmpty) return EstadoVacio(icono: Icons.search_off, titulo: t.busquedaSinResultados(_consulta));
    final grupos = [for (final g in _Grupo.values) if (g == _Grupo.todo || r.any((x) => g.admite(x.tipo))) g];
    final visibles = [for (final x in r) if (_grupo.admite(x.tipo)) x];
    return Column(children: [
      if (grupos.length > 2)
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.fromLTRB(12, 8, 4, 4),
          child: Row(children: [
            for (final g in grupos)
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: ChoiceChip(
                  label: Text('${g.etiqueta(t)} (${r.where((x) => g.admite(x.tipo)).length})'),
                  selected: g == _grupo,
                  onSelected: (_) => setState(() => _grupo = g),
                ),
              ),
          ]),
        ),
      Expanded(
        child: ListView.builder(
          padding: const EdgeInsets.only(top: 4, bottom: 24),
          itemCount: visibles.length,
          itemBuilder: (context, i) => _Fila(
            resultado: visibles[i],
            consulta: _consulta,
            alAbrir: () {
              ref.read(busquedasRecientesProvider.notifier).anotar(_consulta);
              ref.read(navegadorDeAvisosProvider).abrir(visibles[i].destino, urlWeb: visibles[i].url);
            },
          ),
        ),
      ),
    ]);
  }
}

/// Con el campo vacío: lo que se buscó antes (para repetirlo con un toque) o, si no hay nada, la ayuda.
class _Recientes extends ConsumerWidget {
  final void Function(String) alElegir;
  const _Recientes({required this.alElegir});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final recientes = ref.watch(busquedasRecientesProvider);
    if (recientes.isEmpty) return EstadoVacio(icono: Icons.search, titulo: t.busquedaMinimo);
    return ListView(padding: const EdgeInsets.fromLTRB(12, 8, 12, 24), children: [
      Row(children: [
        Expanded(child: Padding(padding: const EdgeInsets.only(left: 4), child: Text(t.busquedaRecientes, style: tema.textTheme.labelLarge))),
        TextButton(onPressed: () => ref.read(busquedasRecientesProvider.notifier).borrar(), child: Text(t.busquedaBorrarRecientes)),
      ]),
      for (final r in recientes)
        ListTile(
          leading: const Icon(Icons.history),
          title: Text(r),
          trailing: const Icon(Icons.north_west, size: 18),
          onTap: () => alElegir(r),
        ),
    ]);
  }
}

class _Fila extends StatelessWidget {
  final ResultadoBusqueda resultado;
  final String consulta;
  final VoidCallback alAbrir;
  const _Fila({required this.resultado, required this.consulta, required this.alAbrir});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final fecha = context.formatos.deServidor(resultado.fecha);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Material(
        color: tema.colorScheme.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: BorderSide(color: tema.colorScheme.outlineVariant)),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: alAbrir,
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              ExcludeSemantics(
                child: CircleAvatar(
                  radius: 20,
                  backgroundColor: tema.colorScheme.onSurfaceVariant.withValues(alpha: 0.10),
                  child: Icon(_icono(resultado.tipo), size: 22, color: tema.colorScheme.onSurfaceVariant),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text.rich(resaltar(resultado.titulo, consulta, tema.textTheme.titleSmall!), maxLines: 2, overflow: TextOverflow.ellipsis),
                  if (resultado.fragmento.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Text.rich(resaltar(resultado.fragmento, consulta, tema.textTheme.bodyMedium!.copyWith(color: tema.colorScheme.onSurfaceVariant)), maxLines: 2, overflow: TextOverflow.ellipsis),
                  ],
                  const SizedBox(height: 6),
                  Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                    Pildora(texto: _etiqueta(t, resultado.tipo)),
                    if (fecha != null) Pildora(icono: Icons.event_outlined, texto: fecha),
                  ]),
                ]),
              ),
            ]),
          ),
        ),
      ),
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

/// Pone en negrita las palabras buscadas dentro de [texto] (sin distinguir mayúsculas). Una palabra de menos de dos letras no se resalta.
TextSpan resaltar(String texto, String consulta, TextStyle estilo) {
  final palabras = {for (final p in consulta.split(RegExp(r'\s+'))) if (p.length >= 2) RegExp.escape(p)};
  if (palabras.isEmpty) return TextSpan(text: texto, style: estilo);
  final re = RegExp(palabras.join('|'), caseSensitive: false);
  final fuerte = estilo.copyWith(fontWeight: FontWeight.w800);
  final trozos = <TextSpan>[];
  var desde = 0;
  for (final m in re.allMatches(texto)) {
    if (m.start > desde) trozos.add(TextSpan(text: texto.substring(desde, m.start)));
    trozos.add(TextSpan(text: m[0], style: fuerte));
    desde = m.end;
  }
  if (desde < texto.length) trozos.add(TextSpan(text: texto.substring(desde)));
  return TextSpan(style: estilo, children: trozos);
}
