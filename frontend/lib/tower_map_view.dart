import 'dart:math' as math;

/// Fit the saved tower coordinates to the visible map, with room for controls.
String towerMapUrl(
  List<dynamic> towers,
  String? selected,
  double width,
  double height,
) {
  final located = towers
      .where((t) => t['latitude'] is num && t['longitude'] is num)
      .toList();
  final selectedTowers = located
      .where((t) => selected != null && t['id'] == selected)
      .toList();
  if (selectedTowers.isNotEmpty) {
    final t = selectedTowers.first;
    return Uri.https('maps.google.com', '/maps', {
      'q': '${t['latitude']},${t['longitude']}',
      'z': '15',
      'output': 'embed',
    }).toString();
  }
  if (located.isEmpty) {
    return Uri.https('maps.google.com', '/maps', {
      'q': 'Zakho, Iraq',
      'z': '13',
      'output': 'embed',
    }).toString();
  }
  double project(num latitude) {
    final lat =
        latitude.toDouble().clamp(-85.05112878, 85.05112878) * math.pi / 180;
    return (1 - math.log(math.tan(lat) + 1 / math.cos(lat)) / math.pi) / 2;
  }

  final xs =
      located
          .map((t) => ((t['longitude'] as num).toDouble() + 180) / 360)
          .toList()
        ..sort();
  final ys = located.map((t) => project(t['latitude'] as num)).toList()..sort();
  // Remove the largest longitude gap so towers across the date line fit together.
  double largestGap = -1;
  double start = xs.first;
  for (var i = 0; i < xs.length; i++) {
    final next = i + 1 < xs.length ? xs[i + 1] : xs.first + 1;
    if (next - xs[i] > largestGap) {
      largestGap = next - xs[i];
      start = next % 1;
    }
  }
  final spanX = 1 - largestGap;
  final spanY = ys.last - ys.first;
  final centerX = (start + spanX / 2) % 1;
  final centerY = (ys.first + ys.last) / 2;
  final n = math.pi * (1 - 2 * centerY);
  final latitude = math.atan((math.exp(n) - math.exp(-n)) / 2) * 180 / math.pi;
  final longitude = centerX * 360 - 180;
  double zoomFor(double span, double pixels) => span <= 0
      ? 15
      : math.log(math.max(80, pixels - 160) / (256 * span)) / math.ln2;
  final zoom = math
      .min(zoomFor(spanX, width), zoomFor(spanY, height))
      .floor()
      .clamp(1, 14);
  return Uri.https('maps.google.com', '/maps', {
    if (located.length == 1)
      'q': '${located.first['latitude']},${located.first['longitude']}',
    'll': '$latitude,$longitude',
    'z': '$zoom',
    'output': 'embed',
  }).toString();
}
