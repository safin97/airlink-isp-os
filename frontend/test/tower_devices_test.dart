import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';

void main() {
  for (final entry in ['NOC Screen', 'Towers']) {
    testWidgets('$entry opens devices by tower ID and clears the filter', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1440, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final fixtures = {
        '/api/devices/1/ethernet-ports': {
          'supported': true,
          'snmp_status': 'connected',
          'poll_interval': 60,
          'ports': [
            {
              'name': 'ether1',
              'state': 'connected',
              'speed_mbps': 1000,
              'rx_bps': 24000000,
              'tx_bps': 0,
            },
            {'name': 'ether2', 'state': 'disconnected'},
            {'name': 'sfp1', 'state': 'disabled'},
          ],
        },
        '/api/devices/1/wireless-clients': {
          'status': 'available',
          'total': 2,
          'clients': [
            {
              'mac_address': 'AA:BB:CC:DD:EE:01',
              'interface': 'wlan1',
              'pppoe_username': 'airlink_customer_01',
              'ssid': 'AirLink North',
              'signal_dbm': -60,
            },
            {
              'mac_address': 'AA:BB:CC:DD:EE:02',
              'interface': 'wlan1',
              'ssid': 'AirLink North',
              'signal_dbm': -72,
            },
          ],
        },
        '/api/dashboard': {
          'devices': 4,
          'online': 2,
          'offline': 1,
          'unknown': 1,
          'active_alerts': 0,
        },
        '/api/towers': [
          {'id': 'north', 'name': 'North', 'status': 'offline'},
          {'id': 'south', 'name': 'South', 'status': 'online'},
          {'id': 'empty', 'name': 'Empty tower', 'status': 'unknown'},
        ],
        '/api/devices': [
          {
            'id': '1',
            'name': 'North online',
            'vendor': 'mikrotik_switch',
            'snmp_status': 'connected',
            'api_status': 'connected',
            'telemetry': {
              'ethernet_links': [
                {'name': 'ether1', 'speed_mbps': 1000},
                {'name': 'ether2', 'speed_mbps': 100},
              ],
              'signal_dbm': -62,
              'wireless_ssids': ['AirLink North'],
              'wireless_clients': 2,
              'cpu_percent': 23,
              'memory_percent': 48,
              'uptime_seconds': 90060,
            },
            'tower_id': 'north',
            'ip_address': '192.0.2.1',
            'status': 'online',
          },
          {
            'id': '2',
            'name': 'North offline',
            'vendor': 'mikrotik',
            'snmp_status': 'failed',
            'tower_id': 'north',
            'ip_address': '192.0.2.2',
            'status': 'offline',
            'downtime_seconds': 7200,
          },
          {
            'id': '3',
            'name': 'North unknown',
            'vendor': 'generic',
            'detected_vendor': 'mikrotik_switch',
            'snmp_status': 'pending',
            'tower_id': 'north',
            'ip_address': '192.0.2.3',
            'status': 'unknown',
          },
          {
            'id': '4',
            'name': 'North stranger',
            'tower_id': 'south',
            'ip_address': '192.0.2.4',
            'status': 'online',
          },
        ],
      };
      final api = Api(
        client: MockClient((request) async {
          expect(request.method, 'GET');
          return http.Response(
            jsonEncode(fixtures[request.url.path] ?? []),
            200,
            headers: {'content-type': 'application/json'},
          );
        }),
      )..user = {'username': 'viewer', 'role': 'viewer'};
      await tester.pumpWidget(
        MaterialApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(ListTile, entry));
      await tester.pumpAndSettle();
      if (entry == 'Towers') {
        expect(find.text('North'), findsNothing);
        await tester.tap(find.text('Unassigned towers'));
        await tester.pumpAndSettle();
      }
      await tester.tap(find.text('North').first);
      await tester.pumpAndSettle();
      expect(find.text('Devices at North'), findsOneWidget);
      expect(find.text('3 devices'), findsOneWidget);
      expect(find.text('Tower'), findsNothing);
      expect(find.text('SNMP status'), findsNothing);
      expect(find.text('Connected'), findsNothing);
      expect(find.text('API status'), findsNothing);
      expect(find.text('Device'), findsNothing);
      expect(find.text('ether1: 1000 Mbps'), findsOneWidget);
      expect(find.text('AirLink North'), findsOneWidget);
      expect(find.text('ether2: 100 Mbps'), findsNothing);
      expect(find.text('CPU'), findsNothing);
      expect(find.byTooltip('Manage switch'), findsOneWidget);
      expect(find.byKey(const ValueKey('manage-switch-2')), findsNothing);
      expect(find.byKey(const ValueKey('manage-switch-3')), findsNothing);
      final manage = find.byKey(const ValueKey('manage-switch-1'));
      await tester.ensureVisible(manage);
      await tester.tap(manage);
      await tester.pumpAndSettle();
      expect(
        find.text('3 ports · 1 running · 2 not running · 0 unknown'),
        findsOneWidget,
      );
      expect(find.text('24.000 Mbps'), findsOneWidget);
      expect(find.text('Running'), findsOneWidget);
      expect(find.text('Not running · Link down'), findsOneWidget);
      expect(find.text('Not running · Disabled'), findsOneWidget);
      expect(find.text('Receive traffic (RX)'), findsOneWidget);
      expect(find.text('Transmit traffic (TX)'), findsOneWidget);
      expect(find.text('ether1'), findsOneWidget);
      expect(find.text('ether2'), findsOneWidget);
      expect(find.text('sfp1'), findsOneWidget);
      await tester.tap(find.text('Close'));
      await tester.pumpAndSettle();
      for (final action in [
        'Ethernet ports',
        'Login device',
        'Manage device',
        'Monitoring history',
      ]) {
        expect(find.byTooltip(action), findsNothing);
      }
      // A viewer still has no write actions.
      expect(find.byTooltip('Edit'), findsNothing);
      expect(find.byTooltip('Delete'), findsNothing);
      expect(find.text('Memory'), findsNothing);
      expect(find.text('Registration clients'), findsOneWidget);
      final clients = find.byKey(const ValueKey('wireless-clients-1'));
      await tester.ensureVisible(clients);
      await tester.tap(clients);
      await tester.pumpAndSettle();
      expect(find.text('AA:BB:CC:DD:EE:01'), findsOneWidget);
      expect(find.text('PPPoE username'), findsOneWidget);
      expect(find.text('airlink_customer_01'), findsOneWidget);
      expect(find.text('Interface'), findsNothing);
      expect(find.text('wlan1'), findsNothing);
      expect(find.text('AA:BB:CC:DD:EE:02'), findsOneWidget);
      expect(find.text('-60 dBm'), findsOneWidget);
      await tester.tap(find.text('Close'));
      await tester.pumpAndSettle();
      expect(find.text('1d 1h 1m'), findsOneWidget);
      expect(find.text('Downtime'), findsOneWidget);
      expect(find.text('0d 2h 0m'), findsOneWidget);
      expect(find.text('Failed'), findsNothing);
      expect(find.text('Waiting for poll'), findsNothing);
      for (final name in ['North online', 'North offline', 'North unknown']) {
        expect(find.text(name), findsNothing);
      }
      expect(find.text('North stranger'), findsNothing);
      await tester.enterText(find.byType(TextField), 'North offline');
      await tester.pumpAndSettle();
      expect(find.text('1 devices'), findsOneWidget);
      await tester.tap(find.widgetWithText(ListTile, 'Towers'));
      await tester.pumpAndSettle();
      expect(find.text('All devices'), findsNothing);
      expect(find.text('Show all devices'), findsNothing);
      expect(
        tester.widget<EditableText>(find.byType(EditableText)).controller.text,
        isEmpty,
      );
      await tester.tap(find.widgetWithText(ListTile, entry));
      await tester.pumpAndSettle();
      if (entry == 'Towers') {
        expect(find.text('North'), findsNothing);
        await tester.tap(find.text('Unassigned towers'));
        await tester.pumpAndSettle();
      }
      await tester.tap(find.text('North').first);
      await tester.pumpAndSettle();
      await tester.tap(
        find.text(
          entry == 'NOC Screen' ? 'Back to NOC Screen' : 'Back to Towers',
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Devices at North'), findsNothing);
      await tester.tap(find.widgetWithText(ListTile, 'Towers'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Unassigned towers'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Empty tower').first);
      await tester.pumpAndSettle();
      expect(
        find.text('No devices are assigned to this tower yet.'),
        findsOneWidget,
      );
      expect(find.text('North stranger'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }
}
