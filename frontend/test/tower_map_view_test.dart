import 'package:flutter_test/flutter_test.dart';
import 'package:airlink_isp_os/tower_map_view.dart';

void main() {
  test('opens Zakho without saved GPS and focuses a selected tower', () {
    expect(
      Uri.parse(towerMapUrl([], null, 1200, 800)).queryParameters['q'],
      'Zakho, Iraq',
    );
    expect(
      Uri.parse(
        towerMapUrl(
          [
            {'id': 'a', 'latitude': 37.1, 'longitude': 42.6},
            {'id': 'b', 'latitude': 37.3, 'longitude': 42.9},
          ],
          'b',
          1200,
          800,
        ),
      ).queryParameters['q'],
      '37.3,42.9',
    );
  });
  test('fits all tower coordinates and adapts zoom to smaller viewports', () {
    final towers = [
      {'id': 'a', 'latitude': 36.0, 'longitude': 42.0},
      {'id': 'b', 'latitude': 38.0, 'longitude': 44.0},
    ];
    final desktop = Uri.parse(
      towerMapUrl(towers, null, 1200, 800),
    ).queryParameters;
    final mobile = Uri.parse(
      towerMapUrl(towers, null, 390, 600),
    ).queryParameters;
    final center = desktop['ll']!.split(',').map(double.parse).toList();
    expect(center[0], inInclusiveRange(36, 38));
    expect(center[1], closeTo(43, 0.001));
    expect(
      int.parse(mobile['z']!),
      lessThanOrEqualTo(int.parse(desktop['z']!)),
    );
    expect(desktop.containsKey('q'), isFalse);
  });
  test(
    'fits nearby towers across the date line without zooming to the world',
    () {
      final params = Uri.parse(
        towerMapUrl(
          [
            {'latitude': 10.0, 'longitude': 179.5},
            {'latitude': 10.0, 'longitude': -179.5},
          ],
          null,
          1200,
          800,
        ),
      ).queryParameters;
      expect(
        double.parse(params['ll']!.split(',')[1]).abs(),
        closeTo(180, 0.01),
      );
      expect(int.parse(params['z']!), greaterThan(5));
    },
  );
}
