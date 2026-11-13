import 'dart:js_interop';
import 'package:web/web.dart' as web;

class NocAudio {
  web.AudioContext? _context;
  Future<void> enable() async {
    final context = _context ??= web.AudioContext();
    await context.resume().toDart.timeout(const Duration(seconds: 2));
    if (context.state != 'running') throw StateError('Audio unavailable');
  }

  void play() {
    final context = _context;
    if (context == null || context.state != 'running') return;
    for (var i = 0; i < 3; i++) {
      final start = context.currentTime + i * 0.3;
      final oscillator = context.createOscillator();
      final gain = context.createGain();
      oscillator.frequency.value = 880;
      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(0.15, start + 0.02);
      gain.gain.linearRampToValueAtTime(0, start + 0.2);
      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.start(start);
      oscillator.stop(start + 0.21);
    }
  }

  void dispose() {
    _context?.close();
    _context = null;
  }
}
