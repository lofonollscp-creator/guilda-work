import 'package:matrix/matrix.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api_client.dart';

/// Envuelve el `Client` del paquete `matrix` (Fase 9) — chat nativo de
/// Element/Synapse, sin pasar por Element-web. El homeserver de Synapse
/// SOLO admite login SSO (ver deploy/synapse/guilda-overrides.yaml,
/// `password_config.enabled: false`), así que el único flujo de login
/// posible es:
///
/// 1. `iniciarLoginSso()` abre `{homeserver}/_matrix/client/v3/login/sso/redirect`
///    en el navegador del sistema (no un WebView — así comparte cookies y
///    gestores de contraseñas del propio dispositivo, igual que hacen
///    FluffyChat/Element X).
/// 2. Synapse hace el login real contra Ory Hydra/Guilda Work y redirige a
///    `guildawork://matrix-callback?loginToken=...` (esquema propio,
///    registrado en AndroidManifest.xml/Info.plist) — la app lo recoge con
///    el paquete `app_links` (ver chat_login_screen.dart) y llama a
///    `completarLoginConToken(loginToken)`.
/// 3. A partir de ahí, todo nativo: `cliente.sync()`, `cliente.rooms`,
///    `room.getTimeline()`/`sendTextEvent()` — sin más navegador de por
///    medio.
class MatrixService {
  final ApiClient api;
  static const redirectUrlCallback = 'guildawork://matrix-callback';

  MatrixService({required this.api});

  Client? _client;

  Future<Client> _obtenerCliente() async {
    final existente = _client;
    if (existente != null) return existente;
    final database = await MatrixSdkDatabase.init('guilda_work_matrix');
    final cliente = Client(
      'Guilda Work',
      database: database,
      // El homeserver solo ofrece SSO — sin esto, checkHomeserver() lanza
      // BadServerLoginTypesException al no encontrar m.login.password.
      supportedLoginTypes: {AuthenticationTypes.sso, AuthenticationTypes.token},
    );
    _client = cliente;
    return cliente;
  }

  /// El cliente, restaurando la sesión persistida si ya se había iniciado
  /// sesión antes (no hace falta volver a pasar por SSO cada vez que se
  /// abre la app).
  Future<Client> clienteConectado() async {
    final cliente = await _obtenerCliente();
    if (!cliente.isLogged()) {
      await cliente.init();
    }
    return cliente;
  }

  Future<void> iniciarLoginSso() async {
    final cliente = await _obtenerCliente();
    final config = await api.obtenerChatConfig();
    await cliente.checkHomeserver(Uri.parse(config.homeserverUrl));
    final urlSso = Uri.parse('${cliente.homeserver}/_matrix/client/v3/login/sso/redirect')
        .replace(queryParameters: {'redirectUrl': redirectUrlCallback});
    await launchUrl(urlSso, mode: LaunchMode.externalApplication);
  }

  Future<void> completarLoginConToken(String loginToken) async {
    final cliente = await _obtenerCliente();
    await cliente.login(AuthenticationTypes.token, token: loginToken);
  }

  Future<void> cerrarSesion() async {
    final cliente = await _obtenerCliente();
    await cliente.logout();
  }
}
