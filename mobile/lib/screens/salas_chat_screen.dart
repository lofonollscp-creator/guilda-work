import 'dart:async';

import 'package:flutter/material.dart';
import 'package:matrix/matrix.dart';

import '../services/matrix_service.dart';
import 'sala_chat_screen.dart';

/// Lista de salas del chat nativo (Fase 9) — equivalente a la pantalla de
/// salas de Element, pero 100% Flutter con el paquete `matrix`.
class SalasChatScreen extends StatefulWidget {
  final MatrixService matrix;

  const SalasChatScreen({super.key, required this.matrix});

  @override
  State<SalasChatScreen> createState() => _SalasChatScreenState();
}

class _SalasChatScreenState extends State<SalasChatScreen> {
  Client? _cliente;

  @override
  void initState() {
    super.initState();
    _conectar();
  }

  Future<void> _conectar() async {
    final cliente = await widget.matrix.clienteConectado();
    cliente.onSync.stream.listen((_) {
      if (mounted) setState(() {});
    });
    unawaited(cliente.sync());
    setState(() => _cliente = cliente);
  }

  @override
  Widget build(BuildContext context) {
    final cliente = _cliente;
    return Scaffold(
      appBar: AppBar(title: const Text('Salas')),
      body: cliente == null
          ? const Center(child: CircularProgressIndicator())
          : cliente.rooms.isEmpty
              ? const Center(child: Text('Todavía no perteneces a ninguna sala.'))
              : ListView.builder(
                  itemCount: cliente.rooms.length,
                  itemBuilder: (context, i) {
                    final sala = cliente.rooms[i];
                    return ListTile(
                      leading: CircleAvatar(child: Text(sala.getLocalizedDisplayname().substring(0, 1).toUpperCase())),
                      title: Text(sala.getLocalizedDisplayname()),
                      subtitle: sala.lastEvent != null ? Text(sala.lastEvent!.body, maxLines: 1, overflow: TextOverflow.ellipsis) : null,
                      trailing: sala.notificationCount > 0
                          ? CircleAvatar(radius: 10, child: Text('${sala.notificationCount}', style: const TextStyle(fontSize: 10)))
                          : null,
                      onTap: () => Navigator.of(context).push(
                        MaterialPageRoute(builder: (_) => SalaChatScreen(sala: sala)),
                      ),
                    );
                  },
                ),
    );
  }
}
