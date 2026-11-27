import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';
import 'live_socket_fixture.dart';

void main() {
  testWidgets(
    'CCR registration column shows PPP counts and retained readings',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(2200, 1100));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final socket = FakeSocket();
      final device = <String, dynamic>{
        'id': 'ccr',
        'name': 'Core router',
        'tower_id': 'north',
        'vendor': 'mikrotik_ccr',
        'vendor_label': 'MikroTik CCR',
        'detected_vendor': 'mikrotik',
        'ip_address': '192.0.2.1',
        'status': 'online',
        'registration_counts': {'online': 99, 'offline': 10},
        'telemetry': {'ppp_active_count': 350, 'wireless_clients': 99},
      };
      final fixtures = {
        '/api/towers': [
          {'id': 'north', 'name': 'North', 'status': 'online'},
        ],
        '/api/devices': [device],
        '/api/devices/ccr/ethernet-ports': {
          'supported': true,
          'source': 'API',
          'connection_status': 'connected',
          'ports': [
            {'name': 'ether1', 'state': 'connected'},
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
      expect(find.text('Registration clients'), findsOneWidget);
      expect(find.text('PPP active: 350'), findsOneWidget);
      expect(find.text('Online: 99\nOffline: 10'), findsNothing);
      expect(find.byKey(const ValueKey('wireless-clients-ccr')), findsNothing);
      Future<void> refresh() async {
        socket.controller.add({
          'type': 'patch',
          'rows': {
            'devices': [device],
          },
        });
        await tester.pumpAndSettle();
      }

      device['status'] = 'offline';
      device['telemetry_stale_fields'] = ['ppp_active_count'];
      await refresh();
      expect(find.text('PPP active: 350'), findsOneWidget);
      expect(
        find.byTooltip(RegExp('Active PPP sessions\nLast known reading')),
        findsOneWidget,
      );
      device['status'] = 'online';
      device['telemetry_stale_fields'] = <String>[];
      device['telemetry'] = {'ppp_active_count': 0};
      await refresh();
      expect(find.text('PPP active: 0'), findsOneWidget);
      device['telemetry'] = <String, dynamic>{};
      await refresh();
      expect(find.text('PPP active: Unavailable'), findsOneWidget);
      final portCounts = {'online': 2, 'offline': 3, 'unknown': 1};
      device['telemetry'] = {'ethernet_port_counts': portCounts};
      await refresh();
      expect(
        find.text('Ethernet\nRunning: 2 · Down: 3\nUnknown: 1'),
        findsOneWidget,
      );
      await tester.tap(find.byKey(const ValueKey('ethernet-count-ccr')));
      await tester.pumpAndSettle();
      expect(find.text('Ethernet ports — Core router'), findsOneWidget);
      expect(find.text('Running'), findsOneWidget);
      await tester.tap(find.text('Close'));
      await tester.pumpAndSettle();
      device['telemetry'] = {
        'ethernet_port_counts': portCounts,
        'ppp_active_count': 0,
      };
      await refresh();
      expect(find.text('PPP active: 0'), findsOneWidget);
      expect(find.byKey(const ValueKey('ethernet-count-ccr')), findsNothing);
      device['vendor'] = 'mikrotik';
      device['registration_counts'] = null;
      device['telemetry'] = {'ethernet_port_counts': portCounts};
      device['telemetry_stale_fields'] = ['ethernet_port_counts'];
      await refresh();
      expect(
        find.text('Ethernet\nRunning: 2 · Down: 3\nUnknown: 1'),
        findsOneWidget,
      );
      expect(
        find.byTooltip(RegExp('Down counts.*Last known reading', dotAll: true)),
        findsOneWidget,
      );
      device['telemetry'] = {
        'ethernet_port_counts': portCounts,
        'wireless_clients': 0,
      };
      await refresh();
      expect(
        find.byKey(const ValueKey('wireless-clients-ccr')),
        findsOneWidget,
      );
      expect(find.byKey(const ValueKey('ethernet-count-ccr')), findsNothing);
      device['telemetry'] = {'ethernet_port_counts': portCounts};
      device['registration_counts'] = {'online': 0, 'offline': 1, 'unknown': 0};
      await refresh();
      expect(find.text('Online: 0\nOffline: 1'), findsOneWidget);
      expect(find.byKey(const ValueKey('ethernet-count-ccr')), findsNothing);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
