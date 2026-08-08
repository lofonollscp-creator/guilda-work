import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Guarda el token de la API (Keystore/Keychain, vía flutter_secure_storage
/// — nunca en claro) y la URL del servidor configurada (shared_preferences,
/// no es un dato sensible). Por defecto apunta al servidor de producción
/// real (guildawork.com); para desarrollo local con el emulador Android,
/// cambiar la URL en Ajustes → Servidor a http://10.0.2.2:8000.
class SessionService {
  static const _claveToken = 'auth_token';
  static const _claveServidor = 'server_url';
  static const servidorPorDefecto = 'https://app.guildawork.com';

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
