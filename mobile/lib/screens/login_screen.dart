import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/material.dart';

import '../diseno/adaptable.dart';
import 'package:flutter/services.dart';

import '../diseno/componentes.dart';

import '../l10n/app_localizations.dart';
import '../services/api_client.dart';
import '../services/locale_service.dart';
import '../services/push_service.dart';
import '../services/session_service.dart';
import '../services/sync_service.dart';
import '../services/theme_service.dart';
import '../widgets/app_button.dart';
import 'ajustes_servidor_dialog.dart';
import 'dashboard_screen.dart';
import 'registro_screen.dart';
import 'selector_idioma_dialog.dart';

/// El alta pública desde la app está APAGADA (D10 del plan): crearía una cuenta sin despacho y sin verificar el correo. El acceso es por invitación de
/// un despacho. Se puede encender en un build de desarrollo con `--dart-define=REGISTRO_PUBLICO=true`.
const registroPublicoEnApp = bool.fromEnvironment('REGISTRO_PUBLICO', defaultValue: false);

class LoginScreen extends StatefulWidget {
  final ApiClient api;
  final SessionService sesion;
  final SyncService sync;
  final PushService push;
  final ThemeService tema;
  final LocaleService locale;
  /// Si lo da quien monta la pantalla (el enrutador), se llama con el usuario
  /// al iniciar sesión en vez de abrir [DashboardScreen] directamente.
  final void Function(Usuario usuario)? alIniciarSesion;

  const LoginScreen({
    super.key,
    required this.api,
    required this.sesion,
    required this.sync,
    required this.push,
    required this.tema,
    required this.locale,
    this.alIniciarSesion,
  });

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _contrasena = TextEditingController();
  final _codigo2fa = TextEditingController();
  String? _error;
  bool _cargando = false;
  bool _verContrasena = false;

  /// La API ha contestado que la cuenta tiene verificación en dos pasos: se pasa a una pantalla propia que pide solo el código.
  bool _pide2fa = false;

  /// Con la app de autenticación el código son 6 cifras (teclado numérico y envío automático); un código de recuperación lleva letras.
  bool _usaRecuperacion = false;

  @override
  void dispose() {
    _email.dispose();
    _contrasena.dispose();
    _codigo2fa.dispose();
    super.dispose();
  }

  Future<void> _iniciarSesion() async {
    if (_cargando) return;
    setState(() {
      _cargando = true;
      _error = null;
    });
    try {
      final (token, usuario) = await widget.api.login(
        _email.text.trim(),
        _contrasena.text,
        codigo2fa: _pide2fa ? _codigo2fa.text.trim() : null,
      );
      await widget.sesion.guardarToken(token);
      TextInput.finishAutofillContext(); // el gestor de contraseñas ofrece guardarla
      if (!mounted) return;
      if (widget.alIniciarSesion != null) {
        widget.alIniciarSesion!(usuario);
        return;
      }
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(
          builder: (_) => DashboardScreen(
            usuario: usuario,
            api: widget.api,
            sesion: widget.sesion,
            sync: widget.sync,
            push: widget.push,
            tema: widget.tema,
            locale: widget.locale,
          ),
        ),
        (route) => false,
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      // Primera vez: solo falta el código. Si ya se envió uno, el error es de verdad (código incorrecto) y se muestra.
      setState(() {
        if (e.requiere2fa) {
          _pide2fa = true;
          _error = null;
        } else {
          _error = mensajeDeError(AppLocalizations.of(context), e);
          if (_pide2fa) _codigo2fa.clear();
        }
      });
    } catch (e) {
      if (mounted) setState(() => _error = mensajeDeError(AppLocalizations.of(context), e));
    } finally {
      if (mounted) setState(() => _cargando = false);
    }
  }

  void _volverACredenciales() => setState(() {
        _pide2fa = false;
        _usaRecuperacion = false;
        _codigo2fa.clear();
        _contrasena.clear();
        _error = null;
      });

  Future<void> _explicarInvitacion() {
    final t = AppLocalizations.of(context);
    return showDialog<void>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(t.loginInvitadoTitulo),
        content: Text(t.loginInvitadoCuerpo),
        actions: [FilledButton(onPressed: () => Navigator.pop(c), child: Text(t.loginEntendido))],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: false,
        // El nombre ya va grande bajo el logotipo: la barra solo lleva los accesos (idioma y, en desarrollo, servidor).
        actions: [
          IconButton(
            icon: const Icon(Icons.language),
            tooltip: t.comunIdioma,
            onPressed: () => mostrarSelectorIdioma(context, widget.locale),
          ),
          // El servidor propio (desarrollo, instalación en un despacho) se cambia con una pulsación larga en el logotipo; el icono solo se ve en desarrollo.
          if (kDebugMode)
            IconButton(
              icon: const Icon(Icons.settings_ethernet),
              tooltip: t.loginServidorTooltip,
              onPressed: () => mostrarAjustesServidor(context, widget.sesion),
            ),
        ],
      ),
      body: AnchoMaximo(ancho: 440, child: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 400),
              child: AutofillGroup(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Semantics(
                      onLongPressHint: t.loginServidorPulsacion,
                      child: GestureDetector(
                        onLongPress: () => mostrarAjustesServidor(context, widget.sesion),
                        child: Column(children: [
                          Image.asset('assets/branding/logo.png', height: 96, excludeFromSemantics: true),
                          const SizedBox(height: 12),
                          Text('Guilda Work', style: Theme.of(context).textTheme.headlineSmall),
                        ]),
                      ),
                    ),
                    const SizedBox(height: 32),
                    if (_pide2fa) ..._pasoDosPasos(t) else ..._pasoCredenciales(t),
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      Semantics(
                        liveRegion: true,
                        child: Container(
                          width: double.infinity,
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(color: Theme.of(context).colorScheme.error.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(12)),
                          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            ExcludeSemantics(child: Icon(Icons.error_outline, size: 20, color: Theme.of(context).colorScheme.error)),
                            const SizedBox(width: 8),
                            Expanded(child: Text(_error!)),
                          ]),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ),
      )),
    );
  }

  List<Widget> _pasoCredenciales(AppLocalizations t) => [
        TextField(
          controller: _email,
          decoration: InputDecoration(labelText: t.loginEmailLabel),
          keyboardType: TextInputType.emailAddress,
          autofillHints: const [AutofillHints.username, AutofillHints.email],
          textInputAction: TextInputAction.next,
          autocorrect: false,
          enableSuggestions: false,
          autofocus: true,
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _contrasena,
          decoration: InputDecoration(
            labelText: t.loginContrasenaLabel,
            suffixIcon: IconButton(
              icon: Icon(_verContrasena ? Icons.visibility_off_outlined : Icons.visibility_outlined),
              tooltip: _verContrasena ? t.loginOcultarContrasena : t.loginMostrarContrasena,
              onPressed: () => setState(() => _verContrasena = !_verContrasena),
            ),
          ),
          obscureText: !_verContrasena,
          autofillHints: const [AutofillHints.password],
          textInputAction: TextInputAction.done,
          autocorrect: false,
          enableSuggestions: false,
          onSubmitted: (_) => _iniciarSesion(),
        ),
        const SizedBox(height: 24),
        SizedBox(width: double.infinity, child: AppButton(texto: t.loginEntrarBoton, cargando: _cargando, onPressed: _iniciarSesion)),
        const SizedBox(height: 8),
        if (registroPublicoEnApp)
          TextButton(
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => RegistroScreen(
                  api: widget.api,
                  sesion: widget.sesion,
                  sync: widget.sync,
                  push: widget.push,
                  tema: widget.tema,
                  locale: widget.locale,
                  alIniciarSesion: widget.alIniciarSesion,
                ),
              ),
            ),
            child: Text(t.loginRegistrateLink),
          )
        else
          TextButton(onPressed: _explicarInvitacion, child: Text(t.loginInvitadoLink)),
      ];

  List<Widget> _pasoDosPasos(AppLocalizations t) => [
        Align(alignment: Alignment.centerLeft, child: Text(t.login2faTitulo, style: Theme.of(context).textTheme.titleMedium)),
        const SizedBox(height: 4),
        Align(alignment: Alignment.centerLeft, child: Text(t.login2faAyuda, style: Theme.of(context).textTheme.bodySmall)),
        const SizedBox(height: 16),
        TextField(
          key: ValueKey('codigo-2fa-${_usaRecuperacion ? 'recuperacion' : 'app'}'),
          controller: _codigo2fa,
          decoration: InputDecoration(labelText: t.login2faLabel),
          keyboardType: _usaRecuperacion ? TextInputType.visiblePassword : TextInputType.number,
          inputFormatters: _usaRecuperacion ? null : [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(6)],
          autofillHints: const [AutofillHints.oneTimeCode],
          textInputAction: TextInputAction.done,
          autofocus: true,
          autocorrect: false,
          enableSuggestions: false,
          // Con la app, en cuanto están las 6 cifras se envía solo (también cuando el teclado las rellena desde un SMS o un gestor).
          onChanged: (v) {
            if (!_usaRecuperacion && v.length == 6 && !_cargando) _iniciarSesion();
          },
          onSubmitted: (_) => _iniciarSesion(),
        ),
        const SizedBox(height: 24),
        SizedBox(width: double.infinity, child: AppButton(texto: t.loginVerificar, cargando: _cargando, onPressed: _iniciarSesion)),
        const SizedBox(height: 8),
        TextButton(
          onPressed: () => setState(() {
            _usaRecuperacion = !_usaRecuperacion;
            _codigo2fa.clear();
            _error = null;
          }),
          child: Text(_usaRecuperacion ? t.login2faUsarApp : t.login2faRecuperacion),
        ),
        TextButton(onPressed: _volverACredenciales, child: Text(t.loginOtraCuenta)),
      ];
}
