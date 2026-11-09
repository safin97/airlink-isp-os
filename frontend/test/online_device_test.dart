import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/sas4_clients.dart';
import 'package:airlink_isp_os/online_device_dialog.dart';
import 'package:airlink_isp_os/online_device_dashboard.dart';

void main() {
  for (final upgrade in [false, true]) {
    testWidgets(
      'SSH first key connects automatically, changed key stops (upgrade: $upgrade)',
      (tester) async {
        tester.view.physicalSize = const Size(1800, 1200);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final key = 'SHA256:${List.filled(43, 'A').join()}';
        final changed = 'SHA256:${List.filled(43, 'B').join()}';
        var calls = 0;
        final api = Api(
          client: MockClient((request) async {
            if (request.url.path.endsWith('/device-access')) {
              return http.Response('{}', 200);
            }
            if (request.url.path.endsWith('/device-login-profiles')) {
              return http.Response('[]', 200);
            }
            calls++;
            final body = jsonDecode(request.body);
            if (calls == 1) {
              expect(body['ssh_fingerprint'], isNull);
              return http.Response(
                jsonEncode(
                  upgrade
                      ? {'vendor': 'Ubiquiti', 'ssh_upgrade_fingerprint': key}
                      : {'requires_trust': true, 'ssh_fingerprint': key},
                ),
                200,
              );
            }
            expect(body['ssh_fingerprint'], key);
            if (calls == 2) {
              return http.Response(
                '{"vendor":"Ubiquiti","wireless":[],"ethernet":[]}',
                200,
              );
            }
            return http.Response(
              jsonEncode({'requires_trust': true, 'ssh_fingerprint': changed}),
              200,
            );
          }),
        )..user = {'role': 'owner'};
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: OnlineDeviceDialog(
                api: api,
                row: const {'username': 'subscriber', 'ip_address': '10.2.3.4'},
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('login-profile-auto')));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Temporary username and password').last);
        await tester.pumpAndSettle();
        await tester.enterText(
          find.byKey(const ValueKey('device-username')),
          'admin',
        );
        await tester.enterText(
          find.byKey(const ValueKey('device-password')),
          'test-device-password',
        );
        await tester.tap(find.text('Connect'));
        await tester.pumpAndSettle();
        expect(calls, 2);
        expect(find.text('Wireless (Radio)'), findsOneWidget);
        expect(find.text('Trust this SSH key and connect'), findsNothing);
        await tester.tap(find.byTooltip('Refresh'));
        await tester.pumpAndSettle();
        expect(calls, 3);
        expect(find.textContaining('SSH host key changed'), findsOneWidget);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }

  testWidgets(
    'Auto Detect tries own enabled logins sequentially and saves with the winner',
    (tester) async {
      tester.view.physicalSize = const Size(1800, 1400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final attempted = <String>[];
      var saves = 0;
      final api = Api(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/device-access')) {
            return http.Response(
              '{"enabled":true,"has_api_password":true,"api_username":"default"}',
              200,
            );
          }
          if (request.url.path.endsWith('/device-login-profiles')) {
            return http.Response(
              jsonEncode([
                for (final id in ['disabled', 'first', 'second', 'third'])
                  {'id': id, 'name': id, 'enabled': id != 'disabled'},
              ]),
              200,
            );
          }
          final body = jsonDecode(request.body);
          expect(body['login'], isNull);
          expect(body['password'], isNull);
          final id = body['use_online_login'] == true
              ? 'default'
              : body['profile_id'] as String;
          if (request.method == 'PUT') {
            expect(id, 'second');
            expect(body['connection']['transport'], 'routeros');
            saves++;
            return http.Response('{"status":"accepted"}', 200);
          }
          attempted.add(id);
          if (id != 'second') {
            return http.Response('{"detail":"Device login rejected."}', 502);
          }
          return http.Response(
            jsonEncode({
              'vendor': 'MikroTik',
              'connection': {'transport': 'routeros'},
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
              row: const {'username': 'subscriber', 'ip_address': '10.2.3.4'},
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final picker = tester.widget<DropdownButton<String>>(
        find.byType(DropdownButton<String>),
      );
      expect(picker.items!.map((item) => item.value).toList(), [
        'auto',
        'online',
        'first',
        'second',
        'third',
        'manual',
      ]);
      await tester.tap(find.text('Connect'));
      await tester.pumpAndSettle();
      expect(attempted, ['default', 'first', 'second']);
      await tester.tap(find.byTooltip('Device settings and details'));
      await tester.pumpAndSettle();
      final field = find.widgetWithText(TextField, 'wlan1 SSID');
      await tester.ensureVisible(field);
      await tester.enterText(field, 'After');
      await tester.pump();
      await tester.ensureVisible(find.text('Save SSID'));
      await tester.tap(find.text('Save SSID'));
      await tester.pumpAndSettle();
      expect(saves, 1);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('Device dashboard fits a phone and does not invent readings', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: OnlineDeviceDashboard(
          data: const {'vendor': 'Ubiquiti'},
          row: const {'ip_address': '10.0.0.2'},
          busy: false,
          stale: false,
          showDetails: false,
          onRefresh: () {},
          onClose: () {},
          onSettings: () {},
          details: const SizedBox(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Unavailable'), findsWidgets);
    expect(find.text('Full Duplex'), findsNothing);
    expect(find.text('Excellent'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  for (final fixture in const [
    (
      family: 'mikrotik',
      vendor: 'MikroTik',
      model: 'MikroTik SXT Lite5',
      port: 'ether1',
    ),
    (
      family: 'ubiquiti_m5',
      vendor: 'Ubiquiti',
      model: 'Ubiquiti NanoStation M5',
      port: 'eth0',
    ),
  ]) {
    testWidgets('Device overview identifies ${fixture.family}', (tester) async {
      tester.view.physicalSize = const Size(900, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          home: OnlineDeviceDashboard(
            data: {
              'vendor': fixture.vendor,
              'detected_vendor': fixture.family,
              'groups': {
                'System': [
                  {'device_model': fixture.model},
                ],
              },
              'wireless': [
                {'name': 'wlan1', 'ssid': 'AirLink', 'signal_dbm': -61},
              ],
              'ethernet': [
                {'name': fixture.port, 'speed_mbps': 100},
              ],
            },
            row: const {
              'username': 'subscriber',
              'ip_address': '10.0.0.2',
              'status': 'active • online',
            },
            busy: false,
            stale: false,
            showDetails: false,
            onRefresh: () {},
            onClose: () {},
            onSettings: () {},
            details: const SizedBox(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text(fixture.vendor), findsOneWidget);
      expect(find.text(fixture.model), findsOneWidget);
      expect(find.text('Device overview'), findsOneWidget);
      expect(find.text('Wireless (Radio)'), findsOneWidget);
      expect(find.text('Ethernet (LAN)'), findsOneWidget);
      expect(find.text('PPPoE Subscription'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets(
    'Hidden device access retains standalone session identity and read-only readings',
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
      expect(find.text('Device access'), findsNothing);
      expect(find.text('Connection'), findsNothing);
      expect(find.text('Open device'), findsNothing);
      await tester.pumpWidget(
        MaterialApp(
          home: OnlineDeviceDialog(
            api: api,
            row: const {
              'id': 7,
              'session_id': 90,
              'username': 'subscriber',
              'ip_address': '10.2.3.4',
            },
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byType(OnlineDeviceDialog), findsOneWidget);
      expect(deviceRequests, 0);
      await tester.tap(find.text('Connect'));
      await tester.pumpAndSettle();
      expect(find.text('Wireless (Radio)'), findsOneWidget);
      expect(find.text('Ethernet (LAN)'), findsOneWidget);
      await tester.tap(find.byTooltip('Device settings and details'));
      await tester.pumpAndSettle();
      for (final text in [
        'AirLink-Test',
        '-61 dBm',
        'ether1',
        '1000 Mbps',
        'pppoe-out1',
      ]) {
        expect(find.text(text), findsWidgets);
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
          matching: find.byTooltip('Refresh'),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.textContaining('Device login rejected.'), findsOneWidget);
      expect(find.text('Showing the previous readings.'), findsOneWidget);
      expect(find.text('AirLink-Test'), findsWidgets);
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
        if (request.url.path.endsWith('/device-access')) {
          return http.Response('{}', 200);
        }
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
        expect(body['login']['verify_tls'], isTrue);
        expect(body['login'].containsKey('port'), isFalse);
        expect(body['login'].containsKey('snmp_community'), isFalse);
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
    expect(find.text('Device login — default credentials'), findsNothing);
    expect(find.text('Automatic — SAS4 manager login'), findsNothing);
    await tester.tap(find.byKey(const ValueKey('login-profile-auto')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Temporary username and password').last);
    await tester.pumpAndSettle();
    expect(find.byType(TextField), findsNWidgets(2));
    expect(find.text('Verify device TLS certificate'), findsNothing);
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
    await tester.tap(find.byTooltip('Device settings and details'));
    await tester.pumpAndSettle();
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
