import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';
import 'package:airlink_isp_os/snmp_visibility_control.dart';
import 'live_socket_fixture.dart';

void main() {
  testWidgets('manager sees only SNMP settings and loses access live', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final account = <String, dynamic>{
      'id': 'm',
      'username': 'manager',
      'role': 'manager',
      'sections': ['towers'],
      'show_snmp_profiles': true,
    };
    final socket = FakeSocket();
    final requests = <String>[];
    final api =
        Api(
            liveConnector: (_, token) => socket,
            client: MockClient((request) async {
              requests.add(request.url.path);
              final Object body = switch (request.url.path) {
                '/api/auth/me' => account,
                '/api/snmp-profiles' => [
                  {'id': 'p', 'name': 'Branch profile', 'version': '2c'},
                ],
                _ => <dynamic>[],
              };
              return http.Response(jsonEncode(body), 200);
            }),
          )
          ..token = 'test-token'
          ..user = Map<String, dynamic>.from(account);
    await tester.pumpWidget(
      MaterialApp(
        home: Operations(api: api, logout: () async {}),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(ListTile, 'Settings'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(ListTile, 'SNMP profiles').last);
    await tester.pumpAndSettle();
    expect(find.text('Branch profile'), findsOneWidget);
    expect(find.text('Add SNMP profile'), findsNothing);
    expect(find.text('Network'), findsNothing);
    expect(requests, contains('/api/snmp-profiles'));
    account['show_snmp_profiles'] = false;
    socket.controller.add({
      'type': 'patch',
      'user': Map<String, dynamic>.from(account),
      'rows': {'snmp-profiles': []},
    });
    await tester.pumpAndSettle();
    expect(find.text('Branch profile'), findsNothing);
    expect(find.widgetWithText(ListTile, 'Settings'), findsNothing);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('bulk checkbox saves show and hide for all accounts', (
    tester,
  ) async {
    final saved = <bool>[];
    final accounts = <dynamic>[
      {'role': 'manager', 'show_snmp_profiles': false},
    ];
    final api = Api(
      client: MockClient((request) async {
        expect(request.url.path, '/api/snmp-profile-visibility');
        expect(request.method, 'PUT');
        final enabled = jsonDecode(request.body)['enabled'] as bool;
        saved.add(enabled);
        accounts[0]['show_snmp_profiles'] = enabled;
        return http.Response(jsonEncode({'enabled': enabled}), 200);
      }),
    )..user = {'role': 'owner'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SnmpVisibilityControl(
            api: api,
            accounts: accounts,
            onChanged: () async {},
          ),
        ),
      ),
    );
    await tester.tap(find.byType(CheckboxListTile));
    await tester.pumpAndSettle();
    expect(saved, [true]);
    await tester.tap(find.byType(CheckboxListTile));
    await tester.pumpAndSettle();
    expect(saved, [true, false]);
    expect(api.user!['default_snmp_profile_visibility'], false);
    await tester.pumpWidget(const SizedBox());
  });
}
