import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';
import 'live_socket_fixture.dart';

void main() {
  for (final mixed in [false, true]) {
    testWidgets(
      'Mimosa shows live signal and Ethernet traffic (mixed: $mixed)',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(2000, 1100));
        addTearDown(() => tester.binding.setSurfaceSize(null));
        final socket = FakeSocket();
        final mimosa = <String, dynamic>{
          'id': 'm',
          'name': 'Backhaul',
          'vendor': 'mimosa',
          'tower_id': 'north',
          'ip_address': '192.0.2.1',
          'status': 'online',
          'telemetry': {
            'signal_dbm': -62.7,
            'wireless_ssids': ['Do not show Mimosa SSID'],
            'wireless_clients': 99,
            'ethernet_traffic': {
              'name': 'eth0',
              'speed_mbps': 1000,
              'tx_bps': 24000000,
              'rx_bps': 0,
            },
          },
        };
        final devices = [
          mimosa,
          if (mixed)
            {
              'id': 'r',
              'name': 'AP',
              'vendor': 'mikrotik',
              'tower_id': 'north',
              'ip_address': '192.0.2.2',
              'status': 'online',
              'telemetry': {
                'wireless_ssids': ['AP SSID'],
                'wireless_clients': 5,
              },
            },
        ];
        final fixtures = {
          '/api/towers': [
            {'id': 'north', 'name': 'North', 'status': 'online'},
          ],
          '/api/devices': devices,
          '/api/dashboard': <String, dynamic>{},
        };
        final api =
            Api(
                client: MockClient(
                  (r) async => http.Response(
                    jsonEncode(fixtures[r.url.path] ?? []),
                    200,
                  ),
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
        expect(
          find.text(mixed ? 'Wireless SSID / Signal' : 'Signal'),
          findsOneWidget,
        );
        expect(
          find.text(
            mixed
                ? 'Registration clients / TX / RX traffic'
                : 'TX / RX traffic',
          ),
          findsOneWidget,
        );
        expect(find.text('-62.7 dBm'), findsOneWidget);
        expect(find.text('TX: 24.000 Mbps\nRX: 0.000 Mbps'), findsOneWidget);
        expect(find.text('eth0: 1000 Mbps'), findsOneWidget);
        expect(find.text('Do not show Mimosa SSID'), findsNothing);
        expect(find.byKey(const ValueKey('wireless-clients-m')), findsNothing);
        if (mixed) {
          expect(find.text('AP SSID'), findsOneWidget);
          expect(
            find.byKey(const ValueKey('wireless-clients-r')),
            findsOneWidget,
          );
        }
        // Live patches change readings without navigation or a manual refresh.
        mimosa['telemetry'] = {
          'weakest_signal_dbm': -70.5,
          'ethernet_traffic': {
            'name': 'ether1',
            'speed_mbps': 100,
            'rx_bps': 12000000,
          },
        };
        socket.controller.add({
          'type': 'patch',
          'rows': {'devices': devices},
        });
        await tester.pumpAndSettle();
        expect(find.text('-70.5 dBm'), findsOneWidget);
        expect(find.text('TX: Unavailable\nRX: 12.000 Mbps'), findsOneWidget);
        expect(find.text('ether1: 100 Mbps'), findsOneWidget);
        mimosa['telemetry'] = <String, dynamic>{};
        socket.controller.add({
          'type': 'patch',
          'rows': {'devices': devices},
        });
        await tester.pumpAndSettle();
        expect(find.text('-70.5 dBm'), findsNothing);
        expect(find.text('TX: Unavailable\nRX: Unavailable'), findsOneWidget);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
}
