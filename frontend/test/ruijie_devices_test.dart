import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';
import 'live_socket_fixture.dart';

void main() {
  for (final automatic in [false, true]) {
    testWidgets('Reyee ports and retained readings (auto: $automatic)', (
      tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(2200, 1100));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final socket = FakeSocket();
      final device = <String, dynamic>{
        'id': 'reyee',
        'name': 'RG-EST450G',
        'tower_id': 'north',
        'vendor': automatic ? 'generic' : 'ruijie',
        'detected_vendor': 'ruijie',
        'ip_address': '192.0.2.45',
        'status': 'online',
        'telemetry': {
          'wireless_ssids': ['Bridge SSID'],
          'signal_dbm': -63,
          'wireless_clients': 0,
          'ethernet_links': [
            {'name': 'LAN1', 'speed_mbps': 1000},
            {'name': 'LAN2', 'speed_mbps': 100},
            {'name': 'LAN3', 'speed_mbps': null},
          ],
        },
      };
      final fixtures = {
        '/api/towers': [
          {'id': 'north', 'name': 'North', 'status': 'online'},
        ],
        '/api/devices': [device],
        '/api/devices/reyee/ethernet-ports': {
          'supported': true,
          'snmp_status': 'connected',
          'snmp_version': '2c',
          'poll_interval': 60,
          'ports': [
            {'name': 'LAN1', 'state': 'connected', 'speed_mbps': 1000},
            {'name': 'LAN2', 'state': 'disconnected'},
            {'name': 'LAN3', 'state': 'disabled'},
          ],
        },
        '/api/dashboard': <String, dynamic>{},
      };
      final api =
          Api(
              client: MockClient(
                (r) async =>
                    http.Response(jsonEncode(fixtures[r.url.path] ?? []), 200),
              ),
              liveConnector: (uri, token) => socket,
            )
            ..user = {'username': 'viewer', 'role': 'viewer'}
            ..token = 'token';
      await tester.pumpWidget(
        MaterialApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(ListTile, 'NOC Screen'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('North').first);
      await tester.pumpAndSettle();
      void expectReadings() {
        expect(find.text('Ethernet speed'), findsOneWidget);
        expect(find.text('LAN1: 1000 Mbps · LAN2: 100 Mbps'), findsOneWidget);
        expect(find.text('Wireless SSID / Signal'), findsOneWidget);
        expect(find.text('Bridge SSID'), findsOneWidget);
        expect(find.text('-63 dBm'), findsOneWidget);
      }

      expectReadings();
      await tester.tap(find.byKey(const ValueKey('ethernet-ports-reyee')));
      await tester.pumpAndSettle();
      expect(find.text('Ethernet ports — RG-EST450G'), findsOneWidget);
      expect(find.text('LAN1'), findsOneWidget);
      expect(find.text('LAN2'), findsOneWidget);
      expect(find.text('LAN3'), findsOneWidget);
      expect(find.text('Not running · Link down'), findsOneWidget);
      expect(find.text('Not running · Disabled'), findsOneWidget);
      expect(find.textContaining('MikroTik'), findsNothing);
      await tester.tap(find.text('Close'));
      await tester.pumpAndSettle();
      device['status'] = 'offline';
      device['telemetry_stale_fields'] = [
        'wireless_ssids',
        'signal_dbm',
        'wireless_clients',
        'ethernet_links',
      ];
      socket.controller.add({
        'type': 'patch',
        'rows': {
          'devices': [device],
        },
      });
      await tester.pumpAndSettle();
      expectReadings();
      expect(find.text('Last known readings'), findsOneWidget);
      final clients = tester.widget<TextButton>(
        find.byKey(const ValueKey('wireless-clients-reyee')),
      );
      expect(clients.onPressed, isNotNull);
      expect(
        find.descendant(
          of: find.byKey(const ValueKey('wireless-clients-reyee')),
          matching: find.text('0'),
        ),
        findsOneWidget,
      );
      // Unreported wireless readings must never be replaced by fabricated zeros.
      device['telemetry'] = <String, dynamic>{};
      device['telemetry_stale_fields'] = <String>[];
      socket.controller.add({
        'type': 'patch',
        'rows': {
          'devices': [device],
        },
      });
      await tester.pumpAndSettle();
      expect(find.text('Bridge SSID'), findsNothing);
      expect(find.text('-63 dBm'), findsNothing);
      expect(
        find.byKey(const ValueKey('wireless-clients-reyee')),
        findsNothing,
      );
      await tester.pumpWidget(const SizedBox());
    });
  }
}
