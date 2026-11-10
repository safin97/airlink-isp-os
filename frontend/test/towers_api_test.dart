import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';

void main() {
  testWidgets(
    'Towers API saves a login and tower device uses the selected profile',
    (tester) async {
      tester.view.physicalSize = const Size(1900, 1600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final profiles = <Map<String, dynamic>>[];
      final saves = <Map<String, dynamic>>[];
      final logins = <Map<String, dynamic>>[];
      final deviceChanges = <Map<String, dynamic>>[];
      var deviceName = 'Roof radio';
      final api = Api(
        client: MockClient((request) async {
          dynamic result = [];
          switch (request.url.path) {
            case '/api/dashboard':
              result = <String, dynamic>{};
            case '/api/towers':
              result = [
                {'id': 't', 'name': 'North'},
              ];
            case '/api/devices':
              result = [
                {
                  'id': 'd',
                  'name': 'Roof radio',
                  'ip_address': '192.0.2.1',
                  'tower_id': 't',
                  'vendor': 'mikrotik',
                },
              ];
            case '/api/towers-api-profiles/managers':
              result = [
                {'id': 'm', 'username': 'north-manager'},
              ];
            case '/api/towers-api-profiles':
              if (request.method == 'POST') {
                final body = Map<String, dynamic>.from(
                  jsonDecode(request.body),
                );
                saves.add(body);
                profiles.add({
                  'id': 'p',
                  'name': body['name'],
                  'username': body['username'],
                  'protocol': body['protocol'],
                  'transport': body['transport'],
                  'enabled': true,
                  'has_password': true,
                });
                result = profiles.single;
              } else {
                result = profiles;
              }
            case '/api/devices/d/login-profiles':
              result = profiles;
            case '/api/devices/d/settings':
              expect(request.method, 'PUT');
              final body = Map<String, dynamic>.from(jsonDecode(request.body));
              deviceChanges.add(body);
              deviceName = body['changes']['name'];
              result = {'status': 'accepted'};
            case '/api/devices/d/login':
              expect(request.method, 'POST');
              logins.add(Map<String, dynamic>.from(jsonDecode(request.body)));
              result = {
                'vendor': 'MikroTik',
                'credential_source': 'Roof API',
                'username': 'Roof radio',
                'ip_address': '192.0.2.1',
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
                        'values': {'name': deviceName},
                        'editable': true,
                      },
                    ],
                  },
                ],
                'wireless': [],
                'ethernet': [
                  {'name': 'ether1', 'speed_mbps': 1000},
                ],
                'pppoe': [],
                'groups': {
                  'Identity': [
                    {'name': 'Roof radio'},
                  ],
                },
              };
          }
          expect(
            request.url.path.startsWith('/api/integrations/sas4/'),
            isFalse,
          );
          return http.Response(
            jsonEncode(result),
            request.method == 'POST' ? 201 : 200,
          );
        }),
      )..user = {'role': 'owner', 'username': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      final nav = find.widgetWithText(ListTile, 'Towers API');
      await tester.ensureVisible(nav);
      await tester.tap(nav);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Add profile'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Profile name'),
        'Roof API',
      );
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Device username'),
        'reader',
      );
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Device password'),
        'device-test-secret',
      );
      final type = find.byWidgetPredicate(
        (widget) =>
            widget is DropdownButtonFormField<String> &&
            widget.decoration.labelText == 'Login type',
      );
      await tester.ensureVisible(type);
      await tester.tap(type);
      await tester.pumpAndSettle();
      await tester.tap(find.text('MikroTik API').last);
      await tester.pumpAndSettle();
      expect(find.text('Default: 8728'), findsOneWidget);
      await tester.ensureVisible(
        find.widgetWithText(CheckboxListTile, 'north-manager'),
      );
      await tester.tap(find.widgetWithText(CheckboxListTile, 'north-manager'));
      await tester.tap(find.text('Save profile'));
      await tester.pumpAndSettle();
      expect(saves.single['transport'], 'routeros');
      expect(saves.single['port'], isNull);
      expect(saves.single['password'], 'device-test-secret');
      expect(saves.single['manager_ids'], ['m']);
      expect(find.text('device-test-secret'), findsNothing);
      final towers = find.widgetWithText(ListTile, 'Towers');
      await tester.ensureVisible(towers);
      await tester.tap(towers);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Unassigned towers'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('North').first);
      await tester.pumpAndSettle();
      expect(find.byTooltip('Edit'), findsOneWidget);
      expect(find.byTooltip('Delete'), findsOneWidget);
      final actionButtons = tester.widgetList<IconButton>(
        find.descendant(
          of: find.byType(DataTable),
          matching: find.byType(IconButton),
        ),
      );
      expect(actionButtons.map((button) => button.tooltip).toList(), [
        'Login via API',
        'Edit',
        'Delete',
      ]);
      await tester.ensureVisible(find.byTooltip('Login via API'));
      await tester.tap(find.byTooltip('Login via API'));
      await tester.pumpAndSettle();
      expect(logins, isEmpty);
      expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, 'Connect'))
            .onPressed,
        isNull,
      );
      await tester.tap(find.byType(DropdownButtonFormField<String>));
      await tester.pumpAndSettle();
      expect(find.text('Temporary username and password'), findsNothing);
      expect(find.text('Automatic — try saved logins'), findsNothing);
      await tester.tap(find.text('Roof API — reader').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Connect'));
      await tester.pumpAndSettle();
      expect(logins.single, {'profile_id': 'p'});
      expect(find.text('AIRLINK  /  DEVICE MANAGER'), findsOneWidget);
      expect(find.text('MikroTik · 192.0.2.1'), findsOneWidget);
      expect(find.text('PPPoE Subscription'), findsNothing);
      await tester.tap(find.byKey(const ValueKey('device-tab-3')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Device identity settings (1)'));
      await tester.tap(find.text('Device identity settings (1)'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byTooltip('Edit Device identity'));
      await tester.tap(find.byTooltip('Edit Device identity'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Device name'),
        'Roof switch',
      );
      await tester.tap(find.text('Review'));
      await tester.pumpAndSettle();
      expect(deviceChanges, isEmpty);
      await tester.tap(find.text('Save to device'));
      await tester.pumpAndSettle();
      expect(deviceChanges.single, {
        'profile_id': 'p',
        'resource': 'identity',
        'action': 'set',
        'record_id': '',
        'previous': {'name': 'Roof radio'},
        'changes': {'name': 'Roof switch'},
      });
      expect(logins.length, 2);
      expect(find.text('Roof switch'), findsOneWidget);
      expect(
        find.text('Device accepted the change. Settings refreshed.'),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
