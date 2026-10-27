import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/cliente.dart';
import '../../api/generado/modelos.g.dart';
import '../../api/generado/operaciones.g.dart';
import '../../nucleo/servicios.dart';
import '../../nucleo/sesion.dart';

/// Algo que está en la papelera: lo de la persona (notas, tareas, proyectos) o lo del calendario fiscal del despacho (clientes y vencimientos).
class ElementoPapelera {
  final Papelera dato;
  final bool fiscal;
  const ElementoPapelera(this.dato, {this.fiscal = false});

  String get origen => dato.origen ?? '';
  int get id => dato.id ?? 0;
  String get clave => '${fiscal ? 'f' : 'p'}-$origen-$id';

  /// Lo fiscal solo se recupera: la API no ofrece borrarlo para siempre (se purga solo a los 30 días).
  bool get sePuedeEliminar => !fiscal;
}

/// Todo lo que la app hace con la papelera contra la API (`/papelera` y `/fiscal/papelera`).
class PapeleraRepositorio {
  final ClienteApi _cliente;
  PapeleraRepositorio(this._cliente);

  Operaciones get _o => Operaciones(_cliente);

  /// La papelera personal y, si hay despacho con calendario fiscal, la fiscal (si esta falla —sin permiso, sin módulo— se queda sin ella).
  Future<List<ElementoPapelera>> listar({bool conFiscal = false}) async {
    final propia = await _o.papelera();
    var fiscal = const <Papelera>[];
    if (conFiscal) {
      try {
        fiscal = await _o.papeleraFiscal();
      } catch (_) {
        // el calendario fiscal es opcional
      }
    }
    final todo = [for (final p in propia) ElementoPapelera(p), for (final p in fiscal) ElementoPapelera(p, fiscal: true)];
    todo.sort((a, b) => (b.dato.papeleraEn ?? '').compareTo(a.dato.papeleraEn ?? ''));
    return todo;
  }

  Future<void> restaurar(ElementoPapelera e) => e.fiscal ? _o.restaurarPapeleraFiscal(tipo: e.origen, itemId: e.id) : _o.restaurarDePapelera(tipo: e.origen, itemId: e.id);

  Future<void> eliminarParaSiempre(ElementoPapelera e) => _o.eliminarDefinitivamenteDePapelera(tipo: e.origen, itemId: e.id);
}

final papeleraRepositorioProvider = Provider<PapeleraRepositorio>((ref) => PapeleraRepositorio(ref.read(clienteApiProvider)));

/// La papelera. Se rehace al cambiar de despacho.
class PapeleraControlador extends AsyncNotifier<List<ElementoPapelera>> {
  @override
  Future<List<ElementoPapelera>> build() {
    final e = ref.watch(estadoSesionProvider);
    return ref.read(papeleraRepositorioProvider).listar(conFiscal: e.usuario?.tenantId != null);
  }

  Future<void> refrescar() async {
    final anterior = state.value;
    try {
      state = AsyncData(await build());
    } catch (err, st) {
      if (anterior == null) state = AsyncError(err, st);
    }
  }

  /// Lo quita de la lista (ya se recuperó o se eliminó en el servidor).
  void quitar(ElementoPapelera e) => state = AsyncData([for (final x in state.value ?? const <ElementoPapelera>[]) if (x.clave != e.clave) x]);
}

final papeleraProvider = AsyncNotifierProvider<PapeleraControlador, List<ElementoPapelera>>(PapeleraControlador.new);
