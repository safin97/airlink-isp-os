import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:airlink_isp_os/noc_sound.dart';

void main() {
  testWidgets('sound enables on entry and re-enables after reopening NOC', (
    tester,
  ) async {
    const screen = MaterialApp(home: NocSound(devices: [], hasData: true));
    await tester.pumpWidget(screen);
    await tester.pump();
    expect(find.text('Mute sound'), findsOneWidget);
    await tester.tap(find.text('Mute sound'));
    await tester.pump();
    expect(find.text('Enable sound'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(screen);
    await tester.pump();
    expect(find.text('Mute sound'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  test('only down and timeout devices trigger outages', () {
    expect(
      nocOutages([
        {'id': 'a', 'status': 'offline'},
        {'id': 'b', 'status': 'timeout'},
        {'id': 'c', 'status': 'down'},
        {'id': 'd', 'status': 'unknown'},
        {'id': 'e', 'status': 'online'},
        {'id': 'f', 'status': 'warning'},
      ]),
      {'a', 'b', 'c'},
    );
  });
  test('unchanged outages do not retrigger; recovery permits a new alert', () {
    final down = nocOutages([
      {'id': 'a', 'status': 'offline'},
    ]);
    expect(down.difference(down), isEmpty);
    final recovered = nocOutages([
      {'id': 'a', 'status': 'online'},
    ]);
    expect(recovered, isEmpty);
    expect(down.difference(recovered), {'a'});
  });
}
