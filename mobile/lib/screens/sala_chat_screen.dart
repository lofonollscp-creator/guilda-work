import 'package:flutter/material.dart';
import 'package:matrix/matrix.dart';

/// Timeline + composer de una sala del chat nativo (Fase 9).
class SalaChatScreen extends StatefulWidget {
  final Room sala;

  const SalaChatScreen({super.key, required this.sala});

  @override
  State<SalaChatScreen> createState() => _SalaChatScreenState();
}

class _SalaChatScreenState extends State<SalaChatScreen> {
  Timeline? _timeline;
  final _mensajeController = TextEditingController();
  bool _enviando = false;

  @override
  void initState() {
    super.initState();
    _cargarTimeline();
  }

  Future<void> _cargarTimeline() async {
    final timeline = await widget.sala.getTimeline(onUpdate: () {
      if (mounted) setState(() {});
    });
    setState(() => _timeline = timeline);
  }

  Future<void> _enviar() async {
    final texto = _mensajeController.text.trim();
    if (texto.isEmpty) return;
    setState(() => _enviando = true);
    try {
      await widget.sala.sendTextEvent(texto);
      _mensajeController.clear();
    } finally {
      if (mounted) setState(() => _enviando = false);
    }
  }

  @override
  void dispose() {
    _mensajeController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final timeline = _timeline;
    return Scaffold(
      appBar: AppBar(title: Text(widget.sala.getLocalizedDisplayname())),
      body: Column(
        children: [
          Expanded(
            child: timeline == null
                ? const Center(child: CircularProgressIndicator())
                : ListView.builder(
                    reverse: true,
                    padding: const EdgeInsets.all(12),
                    itemCount: timeline.events.length,
                    itemBuilder: (context, i) {
                      final evento = timeline.events[i];
                      if (evento.type != EventTypes.Message) return const SizedBox.shrink();
                      final esMio = evento.senderId == widget.sala.client.userID;
                      return Align(
                        alignment: esMio ? Alignment.centerRight : Alignment.centerLeft,
                        child: Container(
                          margin: const EdgeInsets.symmetric(vertical: 4),
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                          decoration: BoxDecoration(
                            color: esMio
                                ? Theme.of(context).colorScheme.primaryContainer
                                : Theme.of(context).colorScheme.surfaceContainerHighest,
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (!esMio)
                                Text(
                                  evento.senderFromMemoryOrFallback.calcDisplayname(),
                                  style: Theme.of(context).textTheme.labelSmall,
                                ),
                              Text(evento.body),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
          ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _mensajeController,
                      decoration: const InputDecoration(hintText: 'Mensaje...'),
                      onSubmitted: (_) => _enviar(),
                    ),
                  ),
                  IconButton(
                    icon: _enviando
                        ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.send),
                    onPressed: _enviando ? null : _enviar,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
