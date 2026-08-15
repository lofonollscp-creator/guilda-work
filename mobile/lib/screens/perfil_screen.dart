import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../widgets/app_button.dart';

/// Espacio de ajustes de usuario (Fase G1): nombre a mostrar, avatar y
/// notificaciones -- a diferencia de ajustes_screen.dart (tema/idioma/
/// servidor, ajustes de la APLICACIÓN), esto es el perfil del usuario en
/// sí. Cambiar contraseña/email se deja solo en la web (el flujo
/// `settings` de Kratos es HTML, no una API JSON limpia para Flutter),
/// mismo criterio que ya usa el móvil con las claves de OpenRouter.
class PerfilScreen extends StatefulWidget {
  final ApiClient api;
  final Usuario usuario;

  const PerfilScreen({super.key, required this.api, required this.usuario});

  @override
  State<PerfilScreen> createState() => _PerfilScreenState();
}

class _PerfilScreenState extends State<PerfilScreen> {
  late Future<PerfilUsuario> _perfil;
  Uint8List? _avatarBytes;
  final _nombreController = TextEditingController();
  bool _guardando = false;
  bool _subiendoAvatar = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _perfil = _cargar();
  }

  Future<PerfilUsuario> _cargar() async {
    final perfil = await widget.api.obtenerPerfil();
    _nombreController.text = perfil.nombreMostrado ?? '';
    if (perfil.tieneAvatar) {
      _avatarBytes = await widget.api.descargarAvatar(widget.usuario.id);
    } else {
      _avatarBytes = null;
    }
    return perfil;
  }

  Future<void> _recargar() async {
    final futuro = _cargar();
    setState(() => _perfil = futuro);
    await futuro;
  }

  Future<void> _guardar() async {
    setState(() {
      _guardando = true;
      _error = null;
    });
    try {
      await widget.api.editarPerfil(nombreMostrado: _nombreController.text.trim());
      await _recargar();
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _guardando = false);
    }
  }

  Future<void> _elegirAvatar(ImageSource origen) async {
    final picker = ImagePicker();
    final XFile? archivo = await picker.pickImage(source: origen, imageQuality: 90);
    if (archivo == null) return;
    setState(() => _subiendoAvatar = true);
    try {
      final bytes = await archivo.readAsBytes();
      await widget.api.subirAvatar(bytes, archivo.name);
      await _recargar();
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _subiendoAvatar = false);
    }
  }

  Future<void> _eliminarAvatar() async {
    setState(() => _subiendoAvatar = true);
    try {
      await widget.api.eliminarAvatar();
      await _recargar();
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _subiendoAvatar = false);
    }
  }

  void _mostrarSelectorAvatar() {
    final t = AppLocalizations.of(context);
    showModalBottomSheet(
      context: context,
      builder: (context) => SafeArea(
        child: Wrap(
          children: [
            ListTile(
              leading: const Icon(Icons.photo_library_outlined),
              title: Text(t.perfilAvatarGaleria),
              onTap: () {
                Navigator.pop(context);
                _elegirAvatar(ImageSource.gallery);
              },
            ),
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined),
              title: Text(t.perfilAvatarCamara),
              onTap: () {
                Navigator.pop(context);
                _elegirAvatar(ImageSource.camera);
              },
            ),
            if (_avatarBytes != null)
              ListTile(
                leading: const Icon(Icons.delete_outline),
                title: Text(t.perfilAvatarQuitar),
                onTap: () {
                  Navigator.pop(context);
                  _eliminarAvatar();
                },
              ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(t.perfilTitulo)),
      body: FutureBuilder<PerfilUsuario>(
        future: _perfil,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text(t.comunErrorCargar(snapshot.error.toString())));
          }
          final perfil = snapshot.data!;
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Center(
                child: GestureDetector(
                  onTap: _subiendoAvatar ? null : _mostrarSelectorAvatar,
                  child: Stack(
                    children: [
                      CircleAvatar(
                        radius: 48,
                        backgroundImage: _avatarBytes != null ? MemoryImage(_avatarBytes!) : null,
                        child: _subiendoAvatar
                            ? const CircularProgressIndicator()
                            : _avatarBytes == null
                                ? Text(
                                    (perfil.nombreMostrado ?? widget.usuario.email).substring(0, 1).toUpperCase(),
                                    style: const TextStyle(fontSize: 32),
                                  )
                                : null,
                      ),
                      Positioned(
                        right: 0,
                        bottom: 0,
                        child: CircleAvatar(
                          radius: 14,
                          child: Icon(Icons.edit, size: 16),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 24),
              TextField(
                controller: _nombreController,
                decoration: InputDecoration(
                  labelText: t.perfilNombreLabel,
                  hintText: widget.usuario.email,
                ),
              ),
              const SizedBox(height: 8),
              Text(t.perfilNombreSubtitulo, style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 24),
              Text(t.perfilNotificacionesLabel, style: Theme.of(context).textTheme.titleSmall),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: perfil.notificarPushVencimientos,
                title: Text(t.perfilNotificacionesVencimientos),
                onChanged: (v) async {
                  await widget.api.editarPerfil(notificarPushVencimientos: v);
                  await _recargar();
                },
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: perfil.notificarPushTiquets,
                title: Text(t.perfilNotificacionesTiquets),
                onChanged: (v) async {
                  await widget.api.editarPerfil(notificarPushTiquets: v);
                  await _recargar();
                },
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: perfil.notificarResumenSemanal,
                title: Text(t.perfilNotificacionesResumenSemanal),
                onChanged: (v) async {
                  await widget.api.editarPerfil(notificarResumenSemanal: v);
                  await _recargar();
                },
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ],
              const SizedBox(height: 24),
              AppButton(texto: t.comunGuardar, cargando: _guardando, onPressed: _guardar),
              const SizedBox(height: 24),
              Text(t.perfilCredencialesAviso, style: Theme.of(context).textTheme.bodySmall),
            ],
          );
        },
      ),
    );
  }
}
