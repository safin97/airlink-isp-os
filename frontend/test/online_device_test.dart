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
          expect(
            request.method,
            request.url.path.endsWith('/online-device/login') ? 'POST' : 'GET',
          );
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
          } else if (request.url.path.endsWith('/device-login-profiles')) {
            body = [
              {
                'id': 'profile1',
                'name': 'Roof devices',
                'username': 'reader',
                'enabled': true,
              },
            ];
          } else if (request.url.path.endsWith('/online-device/login')) {
            deviceRequests++;
            expect(request.url.query, isEmpty);
            expect(jsonDecode(request.body), {
              'username': 'subscriber',
              'ip_address': '10.2.3.4',
              'session_id': '90',
              'profile_id': 'profile1',
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
      expect(deviceRequests, 0);
      await tester.tap(find.byKey(const ValueKey('login-profile-manual')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Roof devices (reader)').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Connect'));
      await tester.pumpAndSettle();
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

  testWidgets('Temporary credentials stay in POST body and edits need Save', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1800, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var reads = 0, writes = 0;
    final api = Api(
      client: MockClient((request) async {
        if (request.url.path.endsWith('/device-login-profiles')) {
          return http.Response('[]', 200);
        }
        expect(request.url.query, isEmpty);
        expect(request.url.toString(), isNot(contains('temporary-secret')));
        final body = jsonDecode(request.body);
        expect(body['username'], 'subscriber');
        expect(body['session_id'], '90');
        expect(body['login']['username'], 'admin');
        expect(body['login']['password'], 'temporary-secret');
        expect(body['login']['transport'], 'auto');
        expect(body['login']['snmp_community'], 'public');
        if (request.method == 'PUT') {
          writes++;
          expect(body['connection']['transport'], 'routeros');
          expect(body['change'], {
            'menu': 'wireless',
            'radio_id': '*1',
            'previous_ssid': 'Before',
            'ssid': 'After',
          });
          return http.Response('{"status":"accepted"}', 200);
        }
        expect(request.method, 'POST');
        reads++;
        return http.Response(
          jsonEncode({
            'vendor': 'MikroTik',
            'credential_source': 'Temporary login',
            'connection': {'transport': 'routeros'},
            'snmp_version': '2',
            'connection_attempts': [
              {'connection': 'RouterOS API', 'status': 'Connected'},
            ],
            'wireless': [],
            'ethernet': [],
            'pppoe': [],
            'settings': [
              {
                'menu': 'wireless',
                'id': '*1',
                'name': 'wlan1',
                'ssid': 'Before',
                'editable': true,
              },
            ],
          }),
          200,
        );
      }),
    )..user = {'role': 'owner'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: OnlineDeviceDialog(
            api: api,
            row: {
              'username': 'subscriber',
              'ip_address': '10.2.3.4',
              'session_id': 90,
            },
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(reads, 0);
    await tester.enterText(
      find.byKey(const ValueKey('device-username')),
      'admin',
    );
    await tester.enterText(
      find.byKey(const ValueKey('device-password')),
      'temporary-secret',
    );
    expect(
      tester
          .widget<TextField>(find.byKey(const ValueKey('device-password')))
          .obscureText,
      isTrue,
    );
    await tester.tap(find.text('Connect'));
    await tester.pumpAndSettle();
    expect(reads, 1);
    final ssid = find.widgetWithText(TextField, 'wlan1 SSID');
    await tester.ensureVisible(ssid);
    await tester.enterText(ssid, 'After');
    await tester.pump();
    expect(writes, 0);
    await tester.ensureVisible(find.text('Save SSID'));
    await tester.tap(find.text('Save SSID'));
    await tester.pumpAndSettle();
    expect(writes, 1);
    expect(
      tester
          .widget<TextButton>(find.widgetWithText(TextButton, 'Save SSID'))
          .onPressed,
      isNull,
    );
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
