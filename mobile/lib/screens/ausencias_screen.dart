import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../services/api_client.dart';

/// Ausencias, vacaciones y permisos (equivalente móvil de
/// app/templates/ausencias.html): saldo del año, mis solicitudes, pedir una
/// nueva y, para quien gestiona el fichaje, aprobar o rechazar las del equipo.
class AusenciasScreen extends StatefulWidget {
  final ApiClient api;

  const AusenciasScreen({super.key, required this.api});

  @override
  State<AusenciasScreen> createState() => _AusenciasScreenState();
}

class _Datos {
  final SaldoAusencias saldo;
  final List<Ausencia> mias;
  final List<Ausencia> equipo;

  _Datos(this.saldo, this.mias, this.equipo);
}

class _AusenciasScreenState extends State<AusenciasScreen> {
  late Future<_Datos> _datos;

  @override
  void initState() {
    super.initState();
    _datos = _cargar();
  }

  Future<_Datos> _cargar() async {
    final anio = DateTime.now().year;
    final saldo = await widget.api.saldoAusencias(anio: anio);
    final mias = await widget.api.listarMisAusencias(anio: anio);
    var equipo = <Ausencia>[];
    try {
      equipo = await widget.api.ausenciasPendientesDelEquipo();
    } on ApiException {
      // Quien no gestiona el fichaje no tiene esta sección.
    }
    return _Datos(saldo, mias, equipo);
  }

  Future<void> _recargar() async {
    final futuro = _cargar();
    setState(() => _datos = futuro);
    await futuro;
  }

  void _aviso(String texto) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(texto)));

  Future<void> _ejecutar(Future<void> Function() accion, String exito) async {
    try {
      await accion();
      if (!mounted) return;
      _aviso(exito);
      await _recargar();
    } on ApiException catch (e) {
      if (mounted) _aviso(e.mensaje);
    }
  }

  Future<void> _cancelar(Ausencia a) async {
    final t = AppLocalizations.of(context);
    final seguro = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        content: Text(t.ausenciasCancelarPregunta),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(t.ausenciasMantener)),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: Text(t.ausenciasCancelarAccion)),
        ],
      ),
    );
    if (seguro == true) await _ejecutar(() => widget.api.cancelarAusencia(a.id), t.ausenciasCancelada);
  }

  Future<void> _pedir() async {
    final t = AppLocalizations.of(context);
    final enviado = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(ctx).viewInsets.bottom),
        child: _FormularioAusencia(api: widget.api),
      ),
    );
    if (enviado == true && mounted) {
      _aviso(t.ausenciasEnviada);
      await _recargar();
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(t.ausenciasTitulo)),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _pedir,
        icon: const Icon(Icons.add),
        label: Text(t.ausenciasPedir),
      ),
      body: RefreshIndicator(
        onRefresh: _recargar,
        child: FutureBuilder<_Datos>(
          future: _datos,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              return Center(child: Text(t.comunErrorCargar(snapshot.error.toString())));
            }
            final d = snapshot.data!;
            final hoy = DateTime.now();
            return ListView(
              padding: const EdgeInsets.only(bottom: 88),
              children: [
                _TarjetaSaldo(saldo: d.saldo),
                if (d.equipo.isNotEmpty) ...[
                  _Titulo(t.ausenciasPendientesEquipo),
                  for (final a in d.equipo)
                    _FilaAusencia(
                      a: a,
                      titulo: '${a.persona ?? ''} · ${_nombreTipo(t, a.tipo)}',
                      acciones: [
                        TextButton(
                          onPressed: () => _ejecutar(() => widget.api.resolverAusencia(a.id, aprobar: false), t.ausenciasResuelta),
                          child: Text(t.ausenciasRechazar),
                        ),
                        FilledButton(
                          onPressed: () => _ejecutar(() => widget.api.resolverAusencia(a.id, aprobar: true), t.ausenciasResuelta),
                          child: Text(t.ausenciasAprobar),
                        ),
                      ],
                    ),
                ],
                _Titulo(t.ausenciasMias),
                if (d.mias.isEmpty)
                  Padding(padding: const EdgeInsets.all(24), child: Text(t.ausenciasSinAusencias))
                else
                  for (final a in d.mias)
                    _FilaAusencia(
                      a: a,
                      titulo: _nombreTipo(t, a.tipo),
                      acciones: [
                        if (a.puedeCancelarse(hoy)) TextButton(onPressed: () => _cancelar(a), child: Text(t.comunCancelar)),
                      ],
                    ),
              ],
            );
          },
        ),
      ),
    );
  }
}

String _nombreTipo(AppLocalizations t, String tipo) => switch (tipo) {
  'vacaciones' => t.ausenciaTipoVacaciones,
  'asuntos_propios' => t.ausenciaTipoAsuntosPropios,
  'permiso' => t.ausenciaTipoPermiso,
  'baja' => t.ausenciaTipoBaja,
  _ => t.ausenciaTipoOtro,
};

String _nombreEstado(AppLocalizations t, String estado) => switch (estado) {
  'pendiente' => t.ausenciaEstadoPendiente,
  'aprobada' => t.ausenciaEstadoAprobada,
  'rechazada' => t.ausenciaEstadoRechazada,
  _ => t.ausenciaEstadoCancelada,
};

class _Titulo extends StatelessWidget {
  final String texto;

  const _Titulo(this.texto);

  @override
  Widget build(BuildContext context) =>
      Padding(padding: const EdgeInsets.fromLTRB(16, 20, 16, 4), child: Text(texto, style: Theme.of(context).textTheme.titleMedium));
}

class _TarjetaSaldo extends StatelessWidget {
  final SaldoAusencias saldo;

  const _TarjetaSaldo({required this.saldo});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return Card(
      margin: const EdgeInsets.all(16),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(t.ausenciasDisponibles(formatoDias(saldo.disponibles), saldo.anio), style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 6),
            Text(t.ausenciasResumen(formatoDias(saldo.aprobadas), formatoDias(saldo.pendientes), formatoDias(saldo.total))),
          ],
        ),
      ),
    );
  }
}

class _FilaAusencia extends StatelessWidget {
  final Ausencia a;
  final String titulo;
  final List<Widget> acciones;

  const _FilaAusencia({required this.a, required this.titulo, required this.acciones});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final fechas = a.desde == a.hasta ? a.desde : '${a.desde} → ${a.hasta}';
    return ListTile(
      leading: const Icon(Icons.beach_access_outlined),
      title: Text(titulo),
      subtitle: Text([
        '$fechas · ${t.ausenciasDias(formatoDias(a.dias))}',
        _nombreEstado(t, a.estado),
        if (a.motivo != null && a.motivo!.isNotEmpty) a.motivo!,
        if (a.comentario != null && a.comentario!.isNotEmpty) a.comentario!,
      ].join('\n')),
      isThreeLine: true,
      trailing: acciones.isEmpty ? null : Row(mainAxisSize: MainAxisSize.min, children: acciones),
    );
  }
}

class _FormularioAusencia extends StatefulWidget {
  final ApiClient api;

  const _FormularioAusencia({required this.api});

  @override
  State<_FormularioAusencia> createState() => _FormularioAusenciaState();
}

class _FormularioAusenciaState extends State<_FormularioAusencia> {
  String _tipo = 'vacaciones';
  DateTime? _desde;
  DateTime? _hasta;
  bool _medioDia = false;
  final _motivo = TextEditingController();
  bool _enviando = false;
  String? _error;

  @override
  void dispose() {
    _motivo.dispose();
    super.dispose();
  }

  String _iso(DateTime d) => d.toIso8601String().substring(0, 10);

  Future<void> _elegir({required bool esDesde}) async {
    final elegida = await showDatePicker(
      context: context,
      initialDate: (esDesde ? _desde : _hasta) ?? _desde ?? DateTime.now(),
      firstDate: DateTime.now().subtract(const Duration(days: 30)),
      lastDate: DateTime(DateTime.now().year + 2),
    );
    if (elegida == null) return;
    setState(() {
      if (esDesde) {
        _desde = elegida;
        if (_hasta != null && _hasta!.isBefore(elegida)) _hasta = null;
      } else {
        _hasta = elegida;
      }
    });
  }

  Future<void> _enviar() async {
    if (_desde == null) return;
    setState(() {
      _enviando = true;
      _error = null;
    });
    try {
      await widget.api.pedirAusencia(
        tipo: _tipo,
        desde: _iso(_desde!),
        hasta: _hasta == null ? null : _iso(_hasta!),
        medioDia: _medioDia && (_hasta == null || _iso(_hasta!) == _iso(_desde!)),
        motivo: _motivo.text,
      );
      if (mounted) Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.mensaje);
    } finally {
      if (mounted) setState(() => _enviando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final unSoloDia = _hasta == null || (_desde != null && _iso(_hasta!) == _iso(_desde!));
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(t.ausenciasPedir, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _tipo,
            decoration: InputDecoration(labelText: t.ausenciasTipo),
            items: [for (final x in tiposAusencia) DropdownMenuItem(value: x, child: Text(_nombreTipo(t, x)))],
            onChanged: (v) => setState(() => _tipo = v ?? _tipo),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: () => _elegir(esDesde: true),
                  child: Text(t.ausenciasDesde(_desde == null ? '—' : _iso(_desde!))),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton(
                  onPressed: _desde == null ? null : () => _elegir(esDesde: false),
                  child: Text(t.ausenciasHasta(_hasta == null ? '—' : _iso(_hasta!))),
                ),
              ),
            ],
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(t.ausenciasMedioDia),
            value: _medioDia && unSoloDia,
            onChanged: unSoloDia ? (v) => setState(() => _medioDia = v) : null,
          ),
          TextField(controller: _motivo, maxLength: 500, decoration: InputDecoration(labelText: t.ausenciasMotivo)),
          if (_error != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
          FilledButton(onPressed: _desde == null || _enviando ? null : _enviar, child: Text(t.ausenciasEnviar)),
        ],
      ),
    );
  }
}
