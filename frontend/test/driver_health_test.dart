import 'package:airlink_isp_os/driver_health.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

final snapshot = <String, dynamic>{
  'status': 'ready',
  'kernel': '6.12-test',
  'checked_at': '2026-11-15T12:00:00Z',
  'counts': {'loaded': 1, 'warning': 1, 'unknown': 1},
  'devices': [
    {
      'id': 'pci/01:00.0',
      'name': 'NVIDIA RTX',
      'category': 'Graphics',
      'driver': 'nvidia',
      'module': 'nvidia',
      'version': '610.1',
      'status': 'loaded',
      'detail': 'Driver bound.',
      'metrics': ['GPU usage: 0%'],
    },
    {
      'id': 'pci/02:00.0',
      'name': 'Ethernet controller',
      'category': 'Network',
      'status': 'warning',
      'detail': 'No driver bound.',
      'metrics': [],
    },
    {
      'id': 'cpu/power-management',
      'name': 'CPU power management',
      'category': 'CPU',
      'status': 'unknown',
      'detail': 'Scaling driver not exposed.',
      'metrics': [],
    },
  ],
  'modules': [
    {
      'name': 'nvidia',
      'version': '610.1',
      'status': 'loaded',
      'detail': 'Module state: live',
    },
  ],
};

Future<void> mount(WidgetTester tester, Map<String, dynamic>? data) async {
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(child: DriverHealth(data: data)),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('searches devices, shows version and real zero GPU usage', (
    tester,
  ) async {
    await mount(tester, snapshot);
    await tester.enterText(find.byType(TextField), 'nvidia');
    await tester.pumpAndSettle();
    expect(find.text('NVIDIA RTX'), findsOneWidget);
    expect(find.text('Version: 610.1'), findsOneWidget);
    expect(find.text('GPU usage: 0%'), findsOneWidget);
    expect(find.text('Ethernet controller'), findsNothing);
    expect(
      find.textContaining('does not guarantee good performance'),
      findsOneWidget,
    );
    await tester.ensureVisible(find.text('Loaded kernel components (1)'));
    await tester.tap(find.text('Loaded kernel components (1)'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.widgetWithText(ListTile, 'nvidia'));
    expect(find.widgetWithText(ListTile, 'nvidia'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('attention and unknown filters work at mobile width', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(360, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await mount(tester, snapshot);
    await tester.tap(find.widgetWithText(ChoiceChip, 'Needs attention'));
    await tester.pumpAndSettle();
    expect(find.text('Ethernet controller'), findsOneWidget);
    expect(find.text('NVIDIA RTX'), findsNothing);
    await tester.tap(find.widgetWithText(ChoiceChip, 'Unknown'));
    await tester.pumpAndSettle();
    expect(find.text('CPU power management'), findsOneWidget);
    expect(find.text('Ethernet controller'), findsNothing);
    await tester.enterText(find.byType(TextField), 'does-not-exist');
    await tester.pumpAndSettle();
    expect(find.text('No matching devices.'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('missing and partial inventory never claim all drivers healthy', (
    tester,
  ) async {
    await mount(tester, null);
    expect(
      find.textContaining('Driver information is unavailable'),
      findsOneWidget,
    );
    expect(find.byType(ChoiceChip), findsNothing);
    await mount(tester, {...snapshot, 'status': 'partial', 'truncated': true});
    expect(find.textContaining('Partial inventory'), findsOneWidget);
    await mount(tester, {
      'status': 'unavailable',
      'note': 'Requires the installed Linux PC.',
    });
    expect(find.text('Requires the installed Linux PC.'), findsOneWidget);
    expect(find.text('NVIDIA RTX'), findsNothing);
  });
}
