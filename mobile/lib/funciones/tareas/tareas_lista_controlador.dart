import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errores.dart';
import '../../api/generado/modelos.g.dart';
import '../../dominio/tarea.dart';
import '../../nucleo/sesion.dart';
import 'tareas_repositorio.dart';

/// El estado de la lista de tareas: filtros, lo cargado hasta ahora y si quedan más páginas.
class EstadoListaTareas {
  final String ambito;
  final EstadoTarea? estado; // null = cualquiera
  final String busqueda;
  final List<TareaOutlook> tareas;
  final bool cargando;
  final bool hayMas;
  final Object? error;

  const EstadoListaTareas({
    this.ambito = 'propias',
    this.estado,
    this.busqueda = '',
    this.tareas = const [],
    this.cargando = false,
    this.hayMas = true,
    this.error,
  });

  EstadoListaTareas copiaCon({
    String? ambito,
    EstadoTarea? estado,
    bool borrarEstado = false,
    String? busqueda,
    List<TareaOutlook>? tareas,
    bool? cargando,
    bool? hayMas,
    Object? error,
    bool borrarError = false,
  }) =>
      EstadoListaTareas(
        ambito: ambito ?? this.ambito,
        estado: borrarEstado ? null : (estado ?? this.estado),
        busqueda: busqueda ?? this.busqueda,
        tareas: tareas ?? this.tareas,
        cargando: cargando ?? this.cargando,
        hayMas: hayMas ?? this.hayMas,
        error: borrarError ? null : (error ?? this.error),
      );
}

/// Lista de tareas con filtros, búsqueda y paginación infinita. Al cambiar de despacho se vacía y vuelve a cargar.
class TareasListaControlador extends Notifier<EstadoListaTareas> {
  static const tamanoPagina = 30;
  int _generacion = 0; // descarta respuestas de una consulta que ya no es la vigente

  @override
  EstadoListaTareas build() {
    ref.watch(estadoSesionProvider.select((e) => e.despacho));
    Future.microtask(recargar);
    return const EstadoListaTareas(cargando: true);
  }

  TareasRepositorio get _repo => ref.read(tareasRepositorioProvider);

  /// Empieza de cero con los filtros actuales.
  Future<void> recargar() async {
    final mia = ++_generacion;
    state = state.copiaCon(cargando: true, borrarError: true, hayMas: true);
    try {
      final pagina = await _repo.listar(ambito: state.ambito, estado: state.estado?.valor, q: state.busqueda, limit: tamanoPagina);
      if (mia != _generacion) return;
      state = state.copiaCon(tareas: pagina, cargando: false, hayMas: pagina.length >= tamanoPagina);
    } catch (e) {
      if (mia != _generacion) return;
      state = state.copiaCon(cargando: false, error: e);
    }
  }

  /// La página siguiente (al llegar al final de la lista).
  Future<void> masResultados() async {
    if (state.cargando || !state.hayMas) return;
    final mia = _generacion;
    state = state.copiaCon(cargando: true);
    try {
      final pagina = await _repo.listar(ambito: state.ambito, estado: state.estado?.valor, q: state.busqueda, limit: tamanoPagina, offset: state.tareas.length);
      if (mia != _generacion) return;
      final ids = state.tareas.map((t) => t.id).toSet();
      state = state.copiaCon(tareas: [...state.tareas, ...pagina.where((t) => !ids.contains(t.id))], cargando: false, hayMas: pagina.length >= tamanoPagina);
    } catch (e) {
      if (mia != _generacion) return;
      state = state.copiaCon(cargando: false, error: e);
    }
  }

  Future<void> cambiarAmbito(String ambito) {
    state = state.copiaCon(ambito: ambito, tareas: const []);
    return recargar();
  }

  Future<void> cambiarEstado(EstadoTarea? estado) {
    state = estado == null ? state.copiaCon(borrarEstado: true, tareas: const []) : state.copiaCon(estado: estado, tareas: const []);
    return recargar();
  }

  Future<void> buscar(String texto) {
    state = state.copiaCon(busqueda: texto.trim(), tareas: const []);
    return recargar();
  }

  /// Crea una tarea y la pone la primera. Lanza si el servidor la rechaza (la pantalla enseña el mensaje).
  Future<TareaOutlook> crear(String asunto, {String? fechaVencimiento}) async {
    final nueva = await _repo.crear(asunto: asunto, fechaVencimiento: fechaVencimiento);
    // Solo entra en la lista si encaja con lo que se está viendo (propias, sin otro filtro de estado distinto).
    if (state.ambito != 'asignadas' && state.ambito != 'compartidas' && (state.estado == null || state.estado == EstadoTarea.desde(nueva.estado))) {
      state = state.copiaCon(tareas: [nueva, ...state.tareas]);
    }
    return nueva;
  }

  /// Completa una tarea desde la lista (con su versión, para no pisar un cambio ajeno). Lanza [ApiException] si no se puede
  /// (bloqueada, con subtareas abiertas, conflicto...).
  Future<void> completar(TareaOutlook t) async {
    try {
      final nueva = await _repo.transicionar(t.id, EstadoTarea.completada, version: t.version);
      reemplazar(nueva);
    } on ApiException catch (e) {
      if (e.categoria == CategoriaError.conflicto) await refrescarUna(t.id); // enseña lo que hay ahora
      rethrow;
    }
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
