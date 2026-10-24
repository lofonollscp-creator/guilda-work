import 'destinos.dart';

/// Decide qué hacer cuando la persona toca un aviso (push o elemento de «Hoy»):
/// esperar a que haya sesión, avisar si es de otro despacho, y abrir la pantalla.
/// No sabe de pantallas ni de Riverpod: recibe lo que necesita por constructor,
/// así que se prueba sin widgets (`test/avisos_test.dart`).
class NavegadorDeAvisos {
  /// ¿Hay sesión iniciada y la app lista para navegar?
  final bool Function() haySesion;

  /// Despacho activo (id como texto) y los ids de los despachos de la persona.
  final String? Function() despachoActivo;
  final Set<String> Function() despachosPropios;

  /// Pregunta si cambiar de despacho (devuelve false si dice que no).
  final Future<bool> Function(String despachoId) confirmarCambio;
  final Future<void> Function(String despachoId) cambiarDespacho;

  /// Ejecuta la apertura del destino.
  final Future<void> Function(Destino destino, {String? urlWeb}) abrir;

  Map<String, dynamic>? _pendiente;

  NavegadorDeAvisos({
    required this.haySesion,
    required this.despachoActivo,
    required this.despachosPropios,
    required this.confirmarCambio,
    required this.cambiarDespacho,
    required this.abrir,
  });

  /// Hay un aviso tocado antes de iniciar sesión, esperando.
  bool get hayPendiente => _pendiente != null;

  /// El `data` de un push que se ha tocado. Sin sesión se guarda y se abre al iniciarla.
  Future<void> abrirDesdePush(Map<String, dynamic> datos) async {
    if (!haySesion()) {
      _pendiente = datos;
      return;
    }
    final despacho = datos['despacho_id']?.toString();
    if (despacho != null && despacho.isNotEmpty && despacho != despachoActivo() && despachosPropios().contains(despacho)) {
      if (!await confirmarCambio(despacho)) return;
      await cambiarDespacho(despacho);
    }
    await abrir(Destino.desdePush(datos), urlWeb: datos['url']?.toString());
  }

  /// Se llama al iniciar sesión: abre el aviso que se tocó antes.
  Future<void> aplicarPendiente() async {
    final datos = _pendiente;
    if (datos == null || !haySesion()) return;
    _pendiente = null;
    await abrirDesdePush(datos);
  }
}
