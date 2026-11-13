import 'package:flutter/material.dart';
import 'noc_audio.dart';

Set<String> nocOutages(List<dynamic> devices) => {
  for (final device in devices)
    if (device['id'] != null &&
        const {'offline', 'down', 'timeout'}.contains(device['status']))
      device['id'].toString(),
};

class NocSound extends StatefulWidget {
  final List<dynamic> devices;
  final bool hasData;
  const NocSound({super.key, required this.devices, required this.hasData});
  @override
  State<NocSound> createState() => _NocSoundState();
}

class _NocSoundState extends State<NocSound> {
  final audio = NocAudio();
  bool enabled = false;
  bool enabling = false;
  String? error;
  Set<String> outages = {};

  @override
  void initState() {
    super.initState();
    toggle();
  }

  @override
  void didUpdateWidget(covariant NocSound oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.hasData) return;
    final current = nocOutages(widget.devices);
    if (enabled && current.difference(outages).isNotEmpty) audio.play();
    outages = current;
  }

  Future<void> toggle() async {
    if (enabled) {
      setState(() => enabled = false);
      return;
    }
    setState(() {
      enabling = true;
      error = null;
    });
    try {
      await audio.enable();
      if (!mounted) return;
      outages = widget.hasData ? nocOutages(widget.devices) : {};
      setState(() => enabled = true);
      audio.play(); // Confirmation tone also announces any existing outages.
    } catch (_) {
      if (mounted) {
        setState(() => error = 'Browser blocked sound. Click Enable sound.');
      }
    } finally {
      if (mounted) setState(() => enabling = false);
    }
  }

  @override
  void dispose() {
    audio.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      OutlinedButton.icon(
        onPressed: enabling ? null : toggle,
        icon: Icon(enabled ? Icons.volume_up : Icons.volume_off),
        label: Text(enabled ? 'Mute sound' : 'Enable sound'),
      ),
      if (error != null) Text(error!),
    ],
  );
}
