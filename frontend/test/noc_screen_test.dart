import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';
import 'package:airlink_isp_os/noc_screen.dart';

void main() {
  testWidgets('NOC preserves unknown status and excludes resolved incidents', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 1600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: NocScreen(
              summary: const {
                'online': 0,
                'offline': 0,
                'unknown': 1,
                'active_alerts': 1,
              },
              towers: const [
                {'id': 't', 'name': 'North tower', 'status': 'warning'},
              ],
              devices: const [
                {
                  'id': 'd',
                  'name': 'No recent poll',
                  'tower_id': 't',
                  'status': 'unknown',
                  'ip_address': '192.0.2.1',
                },
              ],
              alerts: const [
                {
                  'device_id': 'd',
                  'message': 'Current incident',
                  'severity': 'critical',
                  'resolved_at': null,
                },
                {
                  'device_id': 'd',
                  'message': 'Old resolved incident',
                  'severity': 'critical',
                  'resolved_at': '2026-01-01',
                },
              ],
              hasData: true,
              expanded: false,
              toggleExpanded: () {},
              openAlerts: () {},
              openMonitoring: () {},
              openTowerDevices: (_) {},
            ),
          ),
        ),
      ),
    );
    expect(find.text('UNKNOWN'), findsOneWidget);
    expect(find.text('Current incident'), findsOneWidget);
    expect(find.text('Old resolved incident'), findsNothing);
    expect(find.text('All monitored devices report online.'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'Sidebar NOC navigation, expanded view and existing routes work',
    (tester) async {
      tester.view.physicalSize = const Size(1440, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = Api(
        client: MockClient(
          (request) async => http.Response(
            jsonEncode(
              request.url.path == '/api/integrations/sas4/online-count'
                  ? {'online_users': 125}
                  : request.url.path.endsWith('/dashboard')
                  ? {
                      'online': 0,
                      'offline': 0,
                      'unknown': 0,
                      'devices': 0,
                      'towers': 0,
                      'sectors': 0,
                      'active_alerts': 0,
                    }
                  : [],
            ),
            200,
            headers: {'content-type': 'application/json'},
          ),
        ),
      )..user = {'username': 'manager', 'role': 'manager'};
      await tester.pumpWidget(
        MaterialApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(ListTile, 'NOC Screen'));
      await tester.pumpAndSettle();
      expect(find.text('Network operations center'), findsOneWidget);
      expect(find.text('Online users'), findsOneWidget);
      expect(find.text('125'), findsOneWidget);
      await tester.tap(find.text('Expand NOC'));
      await tester.pumpAndSettle();
      expect(find.widgetWithText(ListTile, 'Dashboard'), findsNothing);
      expect(find.byKey(const ValueKey('language-selector')), findsNothing);
      expect(find.byKey(const ValueKey('theme-toggle')), findsNothing);
      await tester.tap(find.text('Exit fullscreen'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('View alerts'));
      await tester.pumpAndSettle();
      expect(find.text('No alerts recorded.'), findsOneWidget);
      await tester.tap(find.widgetWithText(ListTile, 'Towers'));
      await tester.pumpAndSettle();
      expect(find.text('Places'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
