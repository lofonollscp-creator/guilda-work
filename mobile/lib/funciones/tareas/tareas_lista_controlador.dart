import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errores.dart';
import '../../api/generado/modelos.g.dart';
import '../../datos/cola.dart';
import '../../datos/local/cola_escritura.dart' show EstadoPendiente, Pendiente;
import '../../dominio/tarea.dart';
import '../../nucleo/sesion.dart';
import 'tareas_acciones.dart';
import 'tareas_repositorio.dart';

/// El estado de la lista de tareas: filtros, lo cargado hasta ahora y si quedan más páginas.
class EstadoListaTareas {
  final String ambito;
  final EstadoTarea? estado; // null = cualquiera
  final String busqueda;

  /// Filtros como en la web: prioridad, categoría (estilo Outlook) y «ver también completadas» (por defecto se ocultan, salvo que se pida un estado).
  final PrioridadTarea? prioridad;
  final String? categoria;
  final bool completadas;

  /// Ids de las tareas marcadas para una acción en lote (vacío = no hay selección).
  final Set<int> seleccion;
  final List<TareaOutlook> tareas;
  final bool cargando;
  final bool hayMas;
  final Object? error;

  /// Ids de tareas con un cambio hecho sin conexión, aún sin enviar (las creadas sin red llevan id negativo).
  final Set<int> pendientes;

  const EstadoListaTareas({
    this.ambito = 'propias',
    this.estado,
    this.busqueda = '',
    this.prioridad,
    this.categoria,
    this.completadas = false,
    this.seleccion = const {},
    this.tareas = const [],
    this.cargando = false,
    this.hayMas = true,
    this.error,
    this.pendientes = const {},
  });

  EstadoListaTareas copiaCon({
    String? ambito,
    EstadoTarea? estado,
    bool borrarEstado = false,
    String? busqueda,
    PrioridadTarea? prioridad,
    bool borrarPrioridad = false,
    String? categoria,
    bool borrarCategoria = false,
    bool? completadas,
    Set<int>? seleccion,
    List<TareaOutlook>? tareas,
    bool? cargando,
    bool? hayMas,
    Object? error,
    bool borrarError = false,
    Set<int>? pendientes,
  }) =>
      EstadoListaTareas(
        ambito: ambito ?? this.ambito,
        estado: borrarEstado ? null : (estado ?? this.estado),
        busqueda: busqueda ?? this.busqueda,
        prioridad: borrarPrioridad ? null : (prioridad ?? this.prioridad),
        categoria: borrarCategoria ? null : (categoria ?? this.categoria),
        completadas: completadas ?? this.completadas,
        seleccion: seleccion ?? this.seleccion,
        tareas: tareas ?? this.tareas,
        cargando: cargando ?? this.cargando,
        hayMas: hayMas ?? this.hayMas,
        error: borrarError ? null : (error ?? this.error),
        pendientes: pendientes ?? this.pendientes,
      );

  /// Cuántos filtros (aparte del ámbito, el estado y la búsqueda) hay puestos.
  int get filtrosActivos => (prioridad != null ? 1 : 0) + (categoria != null ? 1 : 0) + (completadas ? 1 : 0);

  /// Lo que se guarda en una vista, con las mismas claves y valores que la web (`vista`: mias/asignadas/compartidas o vacío = «mías y asignadas»).
  Map<String, String> get filtrosDeVista => {
        if (ambito != 'todas') 'vista': ambito == 'propias' ? 'mias' : ambito,
        if (estado != null) 'estado': estado!.valor,
        if (prioridad != null) 'prioridad': prioridad!.valor,
        if (categoria != null) 'categoria': categoria!,
        if (busqueda.isNotEmpty) 'q': busqueda,
        if (completadas) 'completadas': '1',
      };
}

/// Lista de tareas con filtros, búsqueda y paginación infinita. Al cambiar de despacho se vacía y vuelve a cargar.
class TareasListaControlador extends Notifier<EstadoListaTareas> {
  static const tamanoPagina = 30;
  int _generacion = 0; // descarta respuestas de una consulta que ya no es la vigente

  @override
  EstadoListaTareas build() {
    ref.watch(estadoSesionProvider.select((e) => e.despacho));
    // Cuando la cola envía lo que había pendiente, la lista vuelve a pedirse para enseñar lo real.
    ref.listen(colaEnviadaProvider, (_, _) => recargar());
    // Si se descarta algo pendiente (o sale), la lista deja de enseñarlo como hecho: se vuelve a pedir.
    ref.listen(colaCambiosProvider, (_, _) async {
      final ids = (await _delaCola()).ids;
      if (ref.mounted && state.pendientes.any((id) => !ids.contains(id))) await recargar();
    });
    Future.microtask(recargar);
    return const EstadoListaTareas(cargando: true);
  }

  TareasRepositorio get _repo => ref.read(tareasRepositorioProvider);

  /// Empieza de cero con los filtros actuales.
  Future<void> recargar() async {
    final mia = ++_generacion;
    state = state.copiaCon(cargando: true, borrarError: true, hayMas: true);
    try {
      final pagina = await _repo.listar(ambito: state.ambito, estado: state.estado?.valor, q: state.busqueda, limit: tamanoPagina, prioridad: state.prioridad?.valor, categoria: state.categoria, soloAbiertas: !state.completadas);
      if (mia != _generacion) return;
      final cola = await _delaCola();
      if (!ref.mounted || mia != _generacion) return;
      state = state.copiaCon(
        tareas: [...cola.nuevas, ...pagina.map(cola.aplicar)],
        pendientes: cola.ids,
        cargando: false,
        hayMas: pagina.length >= tamanoPagina,
      );
    } catch (e) {
      if (mia != _generacion) return;
      state = state.copiaCon(cargando: false, error: e);
    }
  }

  /// Lo hecho sin conexión que aún no ha llegado al servidor, leído de la cola (así sobrevive a recargar y a cerrar la app): las tareas
  /// creadas (con id negativo) y las que tienen un cambio de estado pendiente.
  Future<({List<TareaOutlook> nuevas, Set<int> ids, TareaOutlook Function(TareaOutlook) aplicar})> _delaCola() async {
    final e = ref.read(estadoSesionProvider);
    final cola = e.usuario == null ? const <Pendiente>[] : await ref.read(colaEscrituraProvider).de(e.usuario!.id, despachoDeLaCola(e.despacho));
    final nuevas = <TareaOutlook>[];
    final ids = <int>{};
    final estados = <int, EstadoTarea>{};
    for (final p in cola) {
      if (p.estado == EstadoPendiente.rechazada) continue;
      if (p.tipo == 'tarea.crear') {
        final c = p.cuerpoMapa ?? const {};
        final propia = state.ambito == 'propias' || state.ambito == 'todas';
        if (propia && (state.estado == null || state.estado == EstadoTarea.noIniciada)) {
          nuevas.insert(0, TareaOutlook.fromJson({'id': AccionesTareas.idProvisional(p), 'asunto': c['asunto'], 'estado': 'no_iniciada', 'prioridad': 'normal', 'fecha_vencimiento': c['fecha_vencimiento'], 'version': 0}));
          ids.add(-p.id);
        }
      } else if (p.tipo == 'tarea.estado') {
        final id = int.tryParse(p.entidad.split(':').last);
        final nuevo = EstadoTarea.desde(p.cuerpoMapa?['estado']?.toString());
        if (id != null && nuevo != EstadoTarea.desconocido) {
          estados[id] = nuevo;
          ids.add(id);
        }
      }
    }
    return (nuevas: nuevas, ids: ids, aplicar: (TareaOutlook t) => estados.containsKey(t.id) ? t.copyWith(estado: estados[t.id]!.valor) : t);
  }

  /// La página siguiente (al llegar al final de la lista).
  Future<void> masResultados() async {
    if (state.cargando || !state.hayMas) return;
    final mia = _generacion;
    state = state.copiaCon(cargando: true);
    try {
      final pagina = await _repo.listar(ambito: state.ambito, estado: state.estado?.valor, q: state.busqueda, limit: tamanoPagina, offset: state.tareas.length, prioridad: state.prioridad?.valor, categoria: state.categoria, soloAbiertas: !state.completadas);
      if (mia != _generacion) return;
      final ids = state.tareas.map((t) => t.id).toSet();
      state = state.copiaCon(tareas: [...state.tareas, ...pagina.where((t) => !ids.contains(t.id))], cargando: false, hayMas: pagina.length >= tamanoPagina);
    } catch (e) {
      if (mia != _generacion) return;
      state = state.copiaCon(cargando: false, error: e);
    }
  }

  Future<void> cambiarAmbito(String ambito) {
    state = state.copiaCon(ambito: ambito, tareas: const [], seleccion: const {});
    return recargar();
  }

  Future<void> cambiarEstado(EstadoTarea? estado) {
    state = estado == null ? state.copiaCon(borrarEstado: true, tareas: const [], seleccion: const {}) : state.copiaCon(estado: estado, tareas: const [], seleccion: const {});
    return recargar();
  }

  Future<void> cambiarFiltros({PrioridadTarea? prioridad, String? categoria, bool? completadas, bool quitarPrioridad = false, bool quitarCategoria = false}) {
    state = state.copiaCon(
      prioridad: prioridad, borrarPrioridad: quitarPrioridad, categoria: categoria, borrarCategoria: quitarCategoria, completadas: completadas, tareas: const [], seleccion: const {},
    );
    return recargar();
  }

  Future<void> limpiarFiltros() => cambiarFiltros(quitarPrioridad: true, quitarCategoria: true, completadas: false);

  /// Pone los filtros de una vista guardada (las mismas claves que la web).
  Future<void> aplicarVista(Map<String, dynamic> filtros) {
    final v = (filtros['vista'] ?? '').toString();
    final ambito = switch (v) { 'mias' => 'propias', 'asignadas' => 'asignadas', 'compartidas' => 'compartidas', _ => 'todas' };
    final estado = EstadoTarea.desde(filtros['estado']?.toString());
    final prioridad = (filtros['prioridad'] ?? '').toString();
    final categoria = (filtros['categoria'] ?? '').toString();
    state = EstadoListaTareas(
      ambito: ambito,
      estado: estado == EstadoTarea.desconocido ? null : estado,
      busqueda: (filtros['q'] ?? '').toString(),
      prioridad: prioridad.isEmpty ? null : PrioridadTarea.desde(prioridad),
      categoria: categoria.isEmpty ? null : categoria,
      completadas: filtros['completadas']?.toString() == '1',
      cargando: true,
    );
    return recargar();
  }

  Future<void> buscar(String texto) {
    state = state.copiaCon(busqueda: texto.trim(), tareas: const [], seleccion: const {});
    return recargar();
  }

  /// Crea una tarea y la pone la primera. Sin conexión queda en la cola (y se enseña como pendiente); si el servidor la rechaza, lanza (la
  /// pantalla enseña el mensaje). Devuelve si quedó en la cola.
  Future<bool> crear(String asunto, {String? fechaVencimiento}) async {
    final r = await ref.read(accionesTareasProvider).crear(asunto, fechaVencimiento: fechaVencimiento);
    final nueva = r.valor!;
    // Solo entra en la lista si encaja con lo que se está viendo (propias, sin otro filtro de estado distinto).
    if (state.ambito != 'asignadas' && state.ambito != 'compartidas' && (state.estado == null || state.estado == EstadoTarea.desde(nueva.estado))) {
      state = state.copiaCon(tareas: [nueva, ...state.tareas], pendientes: r.encolada ? {...state.pendientes, nueva.id} : null);
    }
    return r.encolada;
  }

  /// Completa una tarea desde la lista (con su versión, para no pisar un cambio ajeno). Lanza [ApiException] si no se puede
  /// (bloqueada, con subtareas abiertas, conflicto...).
  Future<bool> completar(TareaOutlook t) async {
    try {
      final r = await ref.read(accionesTareasProvider).transicionar(t, EstadoTarea.completada);
      reemplazar(r.valor!);
      if (r.encolada) state = state.copiaCon(pendientes: {...state.pendientes, t.id});
      return r.encolada;
    } on ApiException catch (e) {
      if (e.categoria == CategoriaError.conflicto) await refrescarUna(t.id); // enseña lo que hay ahora
      rethrow;
    }
  }

  // --- selección y acciones en lote ---

  void alternarSeleccion(int id) {
    if (id < 0) return; // lo creado sin conexión aún no existe en el servidor
    final s = {...state.seleccion};
    s.contains(id) ? s.remove(id) : s.add(id);
    state = state.copiaCon(seleccion: s);
  }

  void seleccionarTodas() => state = state.copiaCon(seleccion: {for (final t in state.tareas) if (t.id > 0) t.id});
  void limpiarSeleccion() => state = state.copiaCon(seleccion: const {});

  /// Una acción sobre las marcadas (`completar`, `estado`, `prioridad`, `fecha`). Cada una con sus permisos en el servidor; al acabar se vuelve a pedir la lista.
  Future<({int ok, int fallos})> accionLote(String accion, {String? valor}) async {
    final ids = state.seleccion.toList();
    final r = await _repo.lote(ids, accion, valor: valor);
    state = state.copiaCon(seleccion: const {});
    await recargar();
    return r;
  }

  /// A la papelera (varias o una). Devuelve las que de verdad se eliminaron, para ofrecer «Deshacer» con [restaurar].
  Future<List<int>> eliminar(List<int> ids) async {
    final hechas = <int>[];
    for (final id in ids) {
      try {
        await _repo.eliminar(id);
        hechas.add(id);
      } on ApiException {
        // sin permiso o ya no existe: se cuenta como no eliminada
      }
    }
    state = state.copiaCon(tareas: [for (final t in state.tareas) if (!hechas.contains(t.id)) t], seleccion: const {});
    return hechas;
  }

  Future<void> restaurar(List<int> ids) async {
    for (final id in ids) {
      await _repo.restaurar(id);
    }
    await recargar();
  }

  /// Deshace un cambio de estado hecho desde la lista (p. ej. completar). Si aún estaba en la cola sin enviar, solo se retira de la cola; si ya
  /// se envió, se vuelve al estado anterior con la versión de ahora (si alguien más la tocó, lanza el conflicto y no pisa nada).
  Future<void> deshacerEstado(TareaOutlook antes, {required bool encolada}) async {
    if (encolada) {
      final e = ref.read(estadoSesionProvider);
      final cola = ref.read(colaEscrituraProvider);
      final delaCola = e.usuario == null ? const <Pendiente>[] : await cola.de(e.usuario!.id, despachoDeLaCola(e.despacho));
      final p = delaCola.where((p) => p.tipo == 'tarea.estado' && p.entidad == 'tarea:${antes.id}' && p.estado == EstadoPendiente.pendiente).lastOrNull;
      if (p != null) {
        state = state.copiaCon(pendientes: {...state.pendientes}..remove(antes.id));
        reemplazar(antes);
        await cola.eliminar(p.id);
        return;
      }
    }
    final actual = state.tareas.where((t) => t.id == antes.id).firstOrNull ?? antes;
    final r = await ref.read(accionesTareasProvider).transicionar(actual, EstadoTarea.desde(antes.estado));
    reemplazar(r.valor!);
    if (r.encolada) state = state.copiaCon(pendientes: {...state.pendientes, antes.id});
  }

  void reemplazar(TareaOutlook nueva) {
    state = state.copiaCon(tareas: [for (final t in state.tareas) t.id == nueva.id ? nueva : t]);
  }

  Future<void> refrescarUna(int id) async {
    try {
      reemplazar(await _repo.obtener(id));
    } catch (_) {
      // sigue la versión anterior
    }
  }
}

final tareasListaProvider = NotifierProvider<TareasListaControlador, EstadoListaTareas>(TareasListaControlador.new);

/// Las categorías (estilo Outlook) que ya usan las tareas, para el filtro. Se pide al abrir los filtros.
final categoriasOutlookProvider = FutureProvider.autoDispose<List<String>>((ref) => ref.read(tareasRepositorioProvider).categoriasOutlook());

/// Las vistas guardadas (las propias y las que comparte el despacho): los mismos filtros con nombre que en la web.
final vistasTareasProvider = FutureProvider.autoDispose<List<Vista>>((ref) => ref.read(tareasRepositorioProvider).vistas());
