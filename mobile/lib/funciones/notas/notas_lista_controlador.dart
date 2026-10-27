import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/generado/modelos.g.dart';
import '../../nucleo/sesion.dart';
import 'notas_repositorio.dart';

/// El estado de la lista de notas: filtros, lo cargado hasta ahora y si quedan más páginas.
class EstadoNotas {
  final AmbitoNotas ambito;
  final int? proyectoId;
  final String busqueda;
  final List<Nota> notas;
  final bool cargando;
  final bool hayMas;
  final Object? error;

  const EstadoNotas({this.ambito = AmbitoNotas.todas, this.proyectoId, this.busqueda = '', this.notas = const [], this.cargando = false, this.hayMas = true, this.error});

  EstadoNotas copiaCon({AmbitoNotas? ambito, int? proyectoId, bool borrarProyecto = false, String? busqueda, List<Nota>? notas, bool? cargando, bool? hayMas, Object? error, bool borrarError = false}) => EstadoNotas(
        ambito: ambito ?? this.ambito,
        proyectoId: borrarProyecto ? null : (proyectoId ?? this.proyectoId),
        busqueda: busqueda ?? this.busqueda,
        notas: notas ?? this.notas,
        cargando: cargando ?? this.cargando,
        hayMas: hayMas ?? this.hayMas,
        error: borrarError ? null : (error ?? this.error),
      );
}

/// La lista de notas con filtros, búsqueda y paginación infinita. Al cambiar de despacho se vacía y vuelve a cargar.
class NotasListaControlador extends Notifier<EstadoNotas> {
  static const tamanoPagina = 30;
  int _generacion = 0; // descarta respuestas de una consulta que ya no es la vigente

  @override
  EstadoNotas build() {
    ref.watch(estadoSesionProvider.select((e) => e.despacho));
    Future.microtask(recargar);
    return const EstadoNotas(cargando: true);
  }

  NotasRepositorio get _repo => ref.read(notasRepositorioProvider);

  Future<void> recargar() async {
    final mia = ++_generacion;
    state = state.copiaCon(cargando: true, borrarError: true, hayMas: true);
    try {
      final pagina = await _repo.listar(ambito: state.ambito, q: state.busqueda, proyectoId: state.proyectoId, limit: tamanoPagina);
      if (!ref.mounted || mia != _generacion) return;
      state = state.copiaCon(notas: pagina, cargando: false, hayMas: pagina.length >= tamanoPagina);
    } catch (e) {
      if (!ref.mounted || mia != _generacion) return;
      state = state.copiaCon(cargando: false, error: e);
    }
  }

  Future<void> masResultados() async {
    if (state.cargando || !state.hayMas || state.error != null) return;
    final mia = _generacion;
    state = state.copiaCon(cargando: true);
    try {
      final pagina = await _repo.listar(ambito: state.ambito, q: state.busqueda, proyectoId: state.proyectoId, limit: tamanoPagina, offset: state.notas.length);
      if (!ref.mounted || mia != _generacion) return;
      state = state.copiaCon(notas: [...state.notas, ...pagina], cargando: false, hayMas: pagina.length >= tamanoPagina);
    } catch (e) {
      if (!ref.mounted || mia != _generacion) return;
      state = state.copiaCon(cargando: false, error: e);
    }
  }

  Future<void> buscar(String texto) {
    state = state.copiaCon(busqueda: texto.trim());
    return recargar();
  }

  Future<void> cambiarAmbito(AmbitoNotas a) {
    state = state.copiaCon(ambito: a);
    return recargar();
  }

  Future<void> cambiarProyecto(int? id) {
    state = id == null ? state.copiaCon(borrarProyecto: true) : state.copiaCon(proyectoId: id);
    return recargar();
  }

  /// Pone una nota (recién editada o fijada) en su sitio sin volver a pedir la lista; si no estaba, se pide de nuevo (es nueva).
  void reemplazar(Nota nota) {
    if (!state.notas.any((n) => n.id == nota.id)) {
      recargar();
      return;
    }
    final lista = [for (final n in state.notas) n.id == nota.id ? _conservandoLoDeLista(n, nota) : n];
    // fijadas primero, y dentro de cada grupo el orden de antes
    final orden = {for (var i = 0; i < state.notas.length; i++) state.notas[i].id: i};
    lista.sort((a, b) {
      final f = (b.fijada ?? 0).compareTo(a.fijada ?? 0);
      return f != 0 ? f : (orden[a.id] ?? 0).compareTo(orden[b.id] ?? 0);
    });
    state = state.copiaCon(notas: lista);
  }

  /// El detalle trae campos que la lista no (participantes) y la lista algunos que el detalle de una edición no (rol, contadores): se mezclan.
  Nota _conservandoLoDeLista(Nota antes, Nota nueva) => Nota(
        id: nueva.id,
        usuarioId: nueva.usuarioId ?? antes.usuarioId,
        texto: nueva.texto,
        categoriaId: nueva.categoriaId,
        creadaEn: nueva.creadaEn ?? antes.creadaEn,
        titulo: nueva.titulo,
        fijada: nueva.fijada,
        clienteFiscalId: nueva.clienteFiscalId,
        categoriaNombre: nueva.categoriaNombre ?? antes.categoriaNombre,
        categoriaColor: nueva.categoriaColor ?? antes.categoriaColor,
        duenoNombre: nueva.duenoNombre ?? antes.duenoNombre,
        rol: nueva.rol ?? antes.rol,
        nParticipantes: nueva.nParticipantes ?? antes.nParticipantes,
        nAdjuntos: nueva.nAdjuntos ?? antes.nAdjuntos,
      );

  /// Quita una nota de la lista (la papelera ya la tiene).
  void quitar(int id) => state = state.copiaCon(notas: [for (final n in state.notas) if (n.id != id) n]);
}

final notasListaProvider = NotifierProvider<NotasListaControlador, EstadoNotas>(NotasListaControlador.new);
