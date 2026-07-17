import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Guarda el token de la API (Keystore/Keychain, vía flutter_secure_storage
/// — nunca en claro) y la URL del servidor configurada (shared_preferences,
/// no es un dato sensible). Ver HOSTING.md/CASERO.md en la raíz del repo:
/// mientras no haya un hosting resuelto, el valor por defecto apunta al
/// alias que ve el emulador Android hacia el PC anfitrión.
class SessionService {
  static const _claveToken = 'auth_token';
  static const _claveServidor = 'server_url';
  static const servidorPorDefecto = 'http://10.0.2.2:8000';

  final _almacenSeguro = const FlutterSecureStorage();

  Future<String?> obtenerToken() => _almacenSeguro.read(key: _claveToken);

  Future<void> guardarToken(String token) =>
      _almacenSeguro.write(key: _claveToken, value: token);

  Future<void> borrarToken() => _almacenSeguro.delete(key: _claveToken);

  Future<String> obtenerServidor() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_claveServidor) ?? servidorPorDefecto;
  }

  Future<void> guardarServidor(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_claveServidor, url);
  }
}
