import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:url_launcher/link.dart';
import 'app_language.dart';
import 'client_speed_test.dart';
import 'client_dashboard_style.dart';

class ClientSpeedGauge extends StatefulWidget {
  final ClientSpeedTest Function()? testFactory;
  const ClientSpeedGauge({super.key, this.testFactory});
  @override
  State<ClientSpeedGauge> createState() => ClientSpeedGaugeState();
}

class ClientSpeedGaugeState extends State<ClientSpeedGauge> {
  ClientSpeedTest? runner;
  bool running = false;
  int generation = 0;
  String stage = 'Ready to test your connection', direction = 'download_mbps';
  Map<String, double> measurements = {};

  @override
  void dispose() {
    runner?.close();
    super.dispose();
  }

  void stop() {
    generation++;
    runner?.close();
    setState(() {
      running = false;
      stage = 'Test stopped.';
      measurements = {};
    });
  }

  Future<void> start() async {
    if (running) return;
    final id = ++generation;
    final test = widget.testFactory?.call() ?? ClientSpeedTest();
    runner = test;
    setState(() {
      running = true;
      measurements = {};
      direction = 'download_mbps';
      stage = 'Checking internet…';
    });
    test.onMeasurement = (kind, value) {
      if (mounted && id == generation) {
        setState(() => measurements[kind] = value);
      }
    };
    try {
      final result = await test.run((value) {
        if (mounted && id == generation) {
          setState(() {
            stage = value;
            if (value == 'Testing upload…') direction = 'upload_mbps';
          });
        }
      });
      if (mounted && id == generation) {
        setState(() {
          measurements = result;
          direction = 'download_mbps';
          stage = 'Speed test complete.';
        });
      }
    } catch (_) {
      if (mounted && id == generation) {
        setState(() {
          measurements = {};
          stage = 'Test unavailable. Check your connection and try again.';
        });
      }
    } finally {
      test.close();
      if (mounted && id == generation) setState(() => running = false);
    }
  }

  Widget metric(String label, String key, String unit, IconData icon) => Column(
    children: [
      Icon(icon, color: clientCyan, size: 20),
      const SizedBox(height: 8),
      Text(
        measurements[key] == null ? '—' : measurements[key]!.toStringAsFixed(1),
        style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w700),
      ),
      const SizedBox(height: 2),
      Text(
        '$label · $unit',
        style: const TextStyle(fontSize: 14, color: clientMuted),
        textAlign: TextAlign.center,
      ),
    ],
  );

  @override
  Widget build(BuildContext context) {
    final value = measurements[direction];
    final maxSpeed = math.max(100.0, ((value ?? 0) / 100).ceil() * 100.0);
    return ClientGlass(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Icon(Icons.speed_rounded, color: clientCyan),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  tr('Internet speed'),
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ),
              if (running)
                const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
            ],
          ),
          const SizedBox(height: 16),
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 260),
              child: AspectRatio(
                aspectRatio: 1.15,
                child: TweenAnimationBuilder<double>(
                  tween: Tween(end: value ?? 0),
                  duration: const Duration(milliseconds: 650),
                  curve: Curves.easeOutCubic,
                  builder: (context, speed, _) => CustomPaint(
                    painter: _SpeedArc((speed / maxSpeed).clamp(0, 1)),
                    child: Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            value == null ? '—' : speed.toStringAsFixed(1),
                            style: const TextStyle(
                              fontSize: 48,
                              fontWeight: FontWeight.w700,
                              letterSpacing: -2,
                            ),
                          ),
                          const Text(
                            'Mbps',
                            style: TextStyle(color: clientCyan, fontSize: 16),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            tr(
                              direction == 'upload_mbps'
                                  ? 'Upload'
                                  : 'Download',
                            ),
                            style: const TextStyle(
                              color: clientMuted,
                              fontSize: 14,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
          Text(
            tr(stage),
            textAlign: TextAlign.center,
            style: const TextStyle(color: clientMuted, fontSize: 14),
          ),
          const SizedBox(height: 20),
          FilledButton.icon(
            onPressed: running ? stop : start,
            icon: Icon(running ? Icons.stop_rounded : Icons.bolt_rounded),
            label: AppText(running ? 'Stop test' : 'Start speed test'),
          ),
          const SizedBox(height: 22),
          LayoutBuilder(
            builder: (context, box) {
              final metrics = [
                metric(
                  tr('Download'),
                  'download_mbps',
                  'Mbps',
                  Icons.south_rounded,
                ),
                metric(
                  tr('Upload'),
                  'upload_mbps',
                  'Mbps',
                  Icons.north_rounded,
                ),
                metric(tr('Ping'), 'latency_ms', 'ms', Icons.timer_outlined),
                metric(
                  tr('Jitter'),
                  'jitter_ms',
                  'ms',
                  Icons.multiline_chart_rounded,
                ),
              ];
              return Wrap(
                spacing: 8,
                runSpacing: 20,
                children: [
                  for (final child in metrics)
                    SizedBox(
                      width:
                          (box.maxWidth - (box.maxWidth >= 440 ? 24 : 8)) /
                          (box.maxWidth >= 440 ? 4 : 2),
                      child: child,
                    ),
                ],
              );
            },
          ),
          const SizedBox(height: 22),
          const SizedBox(height: 12),
          const AppText(
            'Measures this device’s connection to Cloudflare. Ping and jitter use HTTP timing. Uses up to 26 MB.',
            textAlign: TextAlign.center,
          ),
          Link(
            uri: Uri.parse('https://www.speedtest.net/'),
            target: LinkTarget.blank,
            builder: (_, follow) => TextButton(
              onPressed: follow,
              child: const AppText('Open Speedtest.net'),
            ),
          ),
        ],
      ),
    );
  }
}

class _SpeedArc extends CustomPainter {
  final double fraction;
  _SpeedArc(this.fraction);
  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final rect = Rect.fromCircle(
      center: center,
      radius: math.min(size.width, size.height) / 2 - 10,
    );
    final track = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 13
      ..strokeCap = StrokeCap.round
      ..color = const Color(0xff203b56);
    const start = math.pi * .75, sweep = math.pi * 1.5;
    canvas.drawArc(rect, start, sweep, false, track);
    final fill = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 13
      ..strokeCap = StrokeCap.round
      ..shader = const SweepGradient(
        startAngle: start,
        endAngle: start + sweep,
        colors: [clientBlue, clientCyan],
        transform: GradientRotation(start),
      ).createShader(rect);
    if (fraction > 0) {
      canvas.drawArc(rect, start, sweep * fraction, false, fill);
    }
    final ticks = Paint()
      ..color = const Color(0xff456782)
      ..strokeWidth = 1.4;
    for (var i = 0; i <= 30; i++) {
      final angle = start + sweep * i / 30;
      final r = rect.width / 2 - 17;
      canvas.drawLine(
        center + Offset(math.cos(angle), math.sin(angle)) * r,
        center +
            Offset(math.cos(angle), math.sin(angle)) *
                (r - (i % 5 == 0 ? 7 : 3)),
        ticks,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _SpeedArc old) => old.fraction != fraction;
}
