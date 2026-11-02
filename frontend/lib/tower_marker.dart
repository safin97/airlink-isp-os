import 'dart:math' as math;
import 'package:flutter/material.dart';

/// AirLink's vector tower badge, with a map-pin variant and live status accent.
class TowerMarker extends StatelessWidget {
  final Color statusColor;
  final double size;
  final bool mapPin;
  const TowerMarker({
    super.key,
    required this.statusColor,
    this.size = 36,
    this.mapPin = false,
  });

  @override
  Widget build(BuildContext context) => SizedBox(
    width: size,
    height: size + (mapPin ? 10 : 0),
    child: CustomPaint(painter: _TowerMarkerPainter(statusColor, mapPin)),
  );
}

class _TowerMarkerPainter extends CustomPainter {
  final Color statusColor;
  final bool mapPin;
  const _TowerMarkerPainter(this.statusColor, this.mapPin);

  @override
  void paint(Canvas canvas, Size size) {
    final side = size.width;
    canvas.save();
    canvas.scale(side / 48);
    if (mapPin) {
      final pointer = Path()
        ..moveTo(18, 42)
        ..lineTo(24, 56)
        ..lineTo(30, 42)
        ..close();
      canvas.drawPath(pointer, Paint()..color = Colors.white);
    }
    final shape = RRect.fromRectAndRadius(
      const Rect.fromLTWH(1, 1, 46, 46),
      const Radius.circular(14),
    );
    canvas.drawShadow(
      Path()..addRRect(shape),
      Colors.black.withValues(alpha: .35),
      4,
      false,
    );
    canvas.drawRRect(shape, Paint()..color = const Color(0xff10233d));
    canvas.drawRRect(
      shape,
      Paint()
        ..color = const Color(0xffe4edff)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.7,
    );
    final line = Paint()
      ..color = const Color(0xff78aaff)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.8
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    final mast = Path()
      ..moveTo(24, 17)
      ..lineTo(16, 36)
      ..moveTo(24, 17)
      ..lineTo(32, 36)
      ..moveTo(20, 27)
      ..lineTo(28, 27)
      ..moveTo(18, 32)
      ..lineTo(30, 32)
      ..moveTo(21, 24)
      ..lineTo(28, 32)
      ..moveTo(27, 24)
      ..lineTo(20, 32)
      ..moveTo(14, 36)
      ..lineTo(34, 36);
    canvas.drawPath(mast, line);
    canvas.drawCircle(const Offset(24, 15), 2.5, Paint()..color = Colors.white);
    for (final radius in [7.0, 11.0]) {
      final bounds = Rect.fromCircle(
        center: const Offset(24, 15),
        radius: radius,
      );
      canvas.drawArc(bounds, -math.pi / 3, 2 * math.pi / 3, false, line);
      canvas.drawArc(bounds, 2 * math.pi / 3, 2 * math.pi / 3, false, line);
    }
    canvas.drawCircle(
      const Offset(40, 40),
      5.5,
      Paint()..color = const Color(0xff10233d),
    );
    canvas.drawCircle(const Offset(40, 40), 3.7, Paint()..color = statusColor);
    canvas.restore();
  }

  @override
  bool shouldRepaint(_TowerMarkerPainter oldDelegate) =>
      oldDelegate.statusColor != statusColor || oldDelegate.mapPin != mapPin;
}
