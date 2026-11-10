import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:airlink_isp_os/tower_device_panel.dart';

Map<String, dynamic> fixture() => {
  'username': 'Roof switch',
  'ip_address': '192.0.2.1',
  'credential_source': 'Saved API',
  'ethernet': [
    for (var n = 1; n <= 48; n++)
      {
        'name': 'ether$n',
        'status': n == 2 ? 'not running' : 'running',
        'speed_mbps': 1000,
        'rx_bps': 0,
        'tx_bps': 2000000,
      },
  ],
  'wireless': [
    {
      'name': 'wlan1',
      'ssid': 'AirLink',
      'signal_dbm': -55,
      'status': 'running',
    },
  ],
  'registrations': [],
  'interfaces': ['ether1', 'ether2'],
  'tower_settings': [
    {
      'resource': 'identity',
      'title': 'Device identity',
      'fields': [
        {'key': 'name', 'label': 'Device name', 'kind': 'text'},
      ],
      'rows': [
        {
          'id': '',
          'values': {'name': 'Roof'},
          'editable': true,
        },
      ],
    },
  ],
};

void main() {
  Future<void> mount(
    WidgetTester tester, {
    bool canEdit = true,
    bool stale = false,
    required Future<void> Function() refresh,
    required Future<void> Function(Map<String, dynamic>) save,
  }) async {
    tester.view.physicalSize = const Size(1500, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TowerDevicePanel(
            data: fixture(),
            busy: false,
            stale: stale,
            canEdit: canEdit,
            onRefresh: refresh,
            onSave: save,
            onClose: () {},
            onChangeLogin: () {},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets(
    'All ports and traffic are shown; drafts pause refresh and require Review then Save',
    (tester) async {
      var refreshes = 0;
      final saves = <Map<String, dynamic>>[];
      await mount(
        tester,
        refresh: () async {
          refreshes++;
        },
        save: (change) async {
          saves.add(change);
        },
      );
      expect(find.text('Port overview'), findsOneWidget);
      expect(find.text('ether48'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('device-tab-1')));
      await tester.pumpAndSettle();
      expect(find.text('Ethernet ports (48)'), findsOneWidget);
      expect(find.text('0.00 Mbps'), findsNWidgets(48));
      expect(find.text('2.00 Mbps'), findsNWidgets(48));
      await tester.pump(const Duration(seconds: 15));
      expect(refreshes, 1);
      await tester.tap(find.byKey(const ValueKey('device-tab-3')));
      await tester.pumpAndSettle();
      final settings = find.text('Device identity settings (1)');
      await tester.ensureVisible(settings);
      await tester.tap(settings);
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byTooltip('Edit Device identity'));
      await tester.tap(find.byTooltip('Edit Device identity'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Device name'),
        'New roof',
      );
      await tester.pump(const Duration(seconds: 30));
      expect(refreshes, 1);
      expect(find.text('New roof'), findsOneWidget);
      expect(saves, isEmpty);
      await tester.tap(find.text('Review'));
      await tester.pumpAndSettle();
      expect(find.text('name: Roof → New roof'), findsOneWidget);
      expect(saves, isEmpty);
      await tester.tap(find.text('Save to device'));
      await tester.pumpAndSettle();
      expect(saves.single, {
        'resource': 'identity',
        'action': 'set',
        'record_id': '',
        'previous': {'name': 'Roof'},
        'changes': {'name': 'New roof'},
      });
      await tester.pumpWidget(const SizedBox());
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'Read-only managers have no edit actions; stale readings pause polling',
    (tester) async {
      var refreshes = 0;
      await mount(
        tester,
        canEdit: false,
        stale: true,
        refresh: () async {
          refreshes++;
        },
        save: (_) async {
          fail('Read-only save');
        },
      );
      await tester.tap(find.byKey(const ValueKey('device-tab-3')));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Your account needs Towers edit permission'),
        findsOneWidget,
      );
      await tester.ensureVisible(find.text('Device identity settings (1)'));
      await tester.tap(find.text('Device identity settings (1)'));
      await tester.pumpAndSettle();
      expect(find.byTooltip('Edit Device identity'), findsNothing);
      await tester.pump(const Duration(seconds: 30));
      expect(refreshes, 0);
      await tester.pumpWidget(const SizedBox());
      expect(tester.takeException(), isNull);
    },
  );
}
