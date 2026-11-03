import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/sas4_clients.dart';
import 'package:airlink_isp_os/online_device_dialog.dart';

void main() {
  testWidgets(
    'Open device uses session identity and displays read-only readings',
    (tester) async {
      tester.view.physicalSize = const Size(1800, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var deviceRequests = 0;
      final api = Api(
        client: MockClient((request) async {
          expect(request.method, 'GET');
          dynamic body;
          if (request.url.path.endsWith('/online')) {
            body = {
              'clients': [
                {
                  'id': 7,
                  'session_id': 90,
                  'username': 'subscriber',
                  'ip_address': '10.2.3.4',
                  'online': true,
                  'status': 'active',
                },
              ],
              'total': 1,
              'page': 1,
              'last_page': 1,
              'per_page': 7,
            };
          } else if (request.url.path.endsWith('/online-device')) {
            deviceRequests++;
            expect(request.url.queryParameters, {
              'username': 'subscriber',
              'ip_address': '10.2.3.4',
              'session_id': '90',
            });
            if (deviceRequests == 2) {
              return http.Response(
                jsonEncode({'detail': 'Device login rejected.'}),
                502,
              );
            }
            body = {
              'vendor': 'MikroTik',
              'credential_source': 'North',
              'wireless': [
                {
                  'name': 'wlan1',
                  'ssid': 'AirLink-Test',
                  'signal_dbm': -61,
                  'status': 'connected',
                },
              ],
              'ethernet': [
                {'name': 'ether1', 'speed_mbps': 1000, 'status': 'link-ok'},
              ],
              'pppoe': [
                {
                  'name': 'pppoe-out1',
                  'username': 'subscriber',
                  'interface': 'wlan1',
                  'status': 'connected',
                  'uptime': '2h',
                },
              ],
            };
          } else {
            body = {'configured': true};
          }
          return http.Response(jsonEncode(body), 200);
        }),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: Sas4Clients(
                api: api,
                showDashboard: false,
                showOnline: true,
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(deviceRequests, 0);
      await tester.tap(find.text('Open device'));
      await tester.pumpAndSettle();
      expect(find.byType(OnlineDeviceDialog), findsOneWidget);
      for (final text in [
        'AirLink-Test',
        '-61 dBm',
        'ether1',
        '1000 Mbps',
        'pppoe-out1',
      ]) {
        expect(find.text(text), findsOneWidget);
      }
      expect(
        find.descendant(
          of: find.byType(OnlineDeviceDialog),
          matching: find.byType(TextField),
        ),
        findsNothing,
      );
      await tester.tap(
        find.descendant(
          of: find.byType(OnlineDeviceDialog),
          matching: find.text('Refresh'),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Device login rejected.'), findsOneWidget);
      expect(find.text('Showing the previous readings.'), findsOneWidget);
      expect(find.text('AirLink-Test'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
