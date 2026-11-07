import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';

void main() {
  for (final vendor in ['mikrotik', 'ubiquiti_ac', 'mimosa']) {
    testWidgets('Edit $vendor selects a public or saved SNMP profile', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(2400, 1800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var profileReads = 0;
      final writes = <Map<String, dynamic>>[];
      final device = {
        'id': 'radio',
        'name': 'Radio',
        'tower_id': 'north',
        'ip_address': '192.0.2.1',
        'vendor': vendor,
        'snmp_profile_id': 'private',
        'status': 'online',
      };
      final api = Api(
        client: MockClient((request) async {
          dynamic result = [];
          switch (request.url.path) {
            case '/api/dashboard':
              result = {
                'devices': 1,
                'online': 1,
                'offline': 0,
                'unknown': 0,
                'active_alerts': 0,
              };
            case '/api/towers':
              result = [
                {'id': 'north', 'name': 'North', 'status': 'online'},
              ];
            case '/api/devices':
              result = [device];
            case '/api/snmp-profiles':
              profileReads++;
              result = [
                {'id': 'private', 'name': 'Private profile', 'version': '3'},
              ];
            case '/api/snmp-profiles/discovery-public':
              expect(request.method, 'POST');
              expect(jsonDecode(request.body), {'version': '2c'});
              result = {'id': 'public-profile', 'version': '2c'};
            case '/api/devices/radio':
              expect(request.method, 'PUT');
              writes.add(Map<String, dynamic>.from(jsonDecode(request.body)));
              result = {'id': 'radio'};
          }
          return http.Response(
            jsonEncode(result),
            200,
            headers: {'content-type': 'application/json'},
          );
        }),
      )..user = {'username': 'owner', 'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(ListTile, 'Towers'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Unassigned towers'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('North').first);
      await tester.pumpAndSettle();
      final reads = profileReads;
      await tester.ensureVisible(find.byTooltip('Edit'));
      await tester.tap(find.byTooltip('Edit'));
      await tester.pumpAndSettle();
      expect(profileReads, greaterThan(reads));
      expect(find.text('Private profile — SNMP v3'), findsOneWidget);
      final select = find.byWidgetPredicate(
        (w) =>
            w is DropdownButtonFormField<String> &&
            w.decoration.labelText == 'SNMP profile',
      );
      await tester.ensureVisible(select);
      await tester.tap(select);
      await tester.pumpAndSettle();
      final label = switch (vendor) {
        'mikrotik' => 'MikroTik (all models)',
        'ubiquiti_ac' => 'UBNT (M5 / AC / other models)',
        _ => 'Mimosa',
      };
      final preset = find.text('$label — SNMP v2c / public').last;
      await tester.ensureVisible(preset);
      await tester.tap(preset);
      await tester.pumpAndSettle();
      expect(writes, isEmpty);
      await tester.tap(find.widgetWithText(FilledButton, 'Save'));
      await tester.pumpAndSettle();
      expect(writes.single['snmp_profile_id'], 'public-profile');
      expect(writes.single['vendor'], vendor);
      expect(writes.single['ip_address'], '192.0.2.1');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }

  testWidgets('Add Mimosa at a tower assigns the SNMP v2c public profile', (
    tester,
  ) async {
    final devices = <Map<String, dynamic>>[];
    final profiles = <Map<String, dynamic>>[];
    final writes = <Map<String, dynamic>>[];
    final api = Api(
      client: MockClient((request) async {
        dynamic result = [];
        switch (request.url.path) {
          case '/api/dashboard':
            result = {
              'devices': devices.length,
              'online': 0,
              'offline': 0,
              'unknown': devices.length,
              'active_alerts': 0,
            };
          case '/api/towers':
            result = [
              {'id': 'north', 'name': 'North', 'status': 'unknown'},
            ];
          case '/api/devices':
            if (request.method == 'POST') {
              final data = Map<String, dynamic>.from(jsonDecode(request.body));
              writes.add(data);
              devices.add({'id': 'mimosa-radio', ...data, 'status': 'unknown'});
              result = devices.single;
            } else {
              expect(request.method, 'GET');
              result = devices;
            }
          case '/api/snmp-profiles':
            expect(request.method, 'GET');
            result = profiles;
          case '/api/snmp-profiles/discovery-public':
            expect(request.method, 'POST');
            expect(jsonDecode(request.body), {'version': '2c'});
            profiles.add({
              'id': 'mimosa-v2c',
              'name': 'Public v2c',
              'version': '2c',
            });
            result = profiles.single;
          default:
            expect(request.method, 'GET');
        }
        return http.Response(
          jsonEncode(result),
          200,
          headers: {'content-type': 'application/json'},
        );
      }),
    )..user = {'username': 'owner', 'role': 'owner'};

    await openNorthTower(tester, api);
    await tester.tap(find.widgetWithText(FilledButton, 'Add device'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Device name'),
      'Mimosa C5c',
    );
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Management IP'),
      '192.0.2.55',
    );
    await tester.tap(dropdownNamed('Tower'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('North').last);
    await tester.pumpAndSettle();
    await tester.tap(dropdownNamed('Vendor'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Mimosa').last);
    await tester.pumpAndSettle();
    await tester.ensureVisible(dropdownNamed('SNMP profile'));
    await tester.tap(dropdownNamed('SNMP profile'));
    await tester.pumpAndSettle();
    final preset = find.text('Mimosa — SNMP v2c / public').last;
    await tester.ensureVisible(preset);
    await tester.tap(preset);
    await tester.pumpAndSettle();
    expect(writes, isEmpty);
    await tester.tap(find.widgetWithText(FilledButton, 'Save'));
    await tester.pumpAndSettle();

    expect(profiles, hasLength(1));
    expect(writes, hasLength(1));
    expect(writes.single['name'], 'Mimosa C5c');
    expect(writes.single['tower_id'], 'north');
    expect(writes.single['vendor'], 'mimosa');
    expect(writes.single['ip_address'], '192.0.2.55');
    expect(writes.single['snmp_profile_id'], 'mimosa-v2c');
    expect(writes.single.containsKey('community'), isFalse);
    expect(find.byType(ResourceDialog), findsNothing);
    expect(find.text('192.0.2.55'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });

  for (final savedVersion in ['2c', '2']) {
    testWidgets(
      'Editing Mimosa keeps the private v2c profile stored as $savedVersion',
      (tester) async {
        final device = <String, dynamic>{
          'id': 'mimosa-radio',
          'name': 'Mimosa radio',
          'tower_id': 'north',
          'ip_address': '192.0.2.55',
          'vendor': 'mimosa',
          'model': 'C5c',
          'snmp_profile_id': 'private-v2c',
          'poll_interval': 120,
          'retries': 1,
          'failure_threshold': 5,
          'cpu_threshold': 85,
          'enabled': true,
          'status': 'online',
        };
        final writes = <Map<String, dynamic>>[];
        var profileCreates = 0;
        final api = Api(
          client: MockClient((request) async {
            dynamic result = [];
            switch (request.url.path) {
              case '/api/dashboard':
                result = {
                  'devices': 1,
                  'online': 1,
                  'offline': 0,
                  'unknown': 0,
                  'active_alerts': 0,
                };
              case '/api/towers':
                result = [
                  {'id': 'north', 'name': 'North', 'status': 'online'},
                ];
              case '/api/devices':
                expect(request.method, 'GET');
                result = [device];
              case '/api/snmp-profiles':
                expect(request.method, 'GET');
                result = [
                  {
                    'id': 'private-v2c',
                    'name': 'Mimosa private',
                    'version': savedVersion,
                  },
                ];
              case '/api/snmp-profiles/discovery-public':
                profileCreates++;
                result = {'id': 'unexpected-public-profile', 'version': '2c'};
              case '/api/devices/mimosa-radio':
                expect(request.method, 'PUT');
                final data = Map<String, dynamic>.from(
                  jsonDecode(request.body),
                );
                writes.add(data);
                device.addAll(data);
                result = device;
              default:
                expect(request.method, 'GET');
            }
            return http.Response(
              jsonEncode(result),
              200,
              headers: {'content-type': 'application/json'},
            );
          }),
        )..user = {'username': 'owner', 'role': 'owner'};

        await openNorthTower(tester, api);
        await tester.ensureVisible(find.byTooltip('Edit'));
        await tester.tap(find.byTooltip('Edit'));
        await tester.pumpAndSettle();
        expect(find.text('Mimosa private — SNMP v2c'), findsOneWidget);
        expect(find.byKey(const ValueKey('community')), findsNothing);
        await tester.enterText(
          find.widgetWithText(TextFormField, 'Device name'),
          'Renamed Mimosa radio',
        );
        await tester.tap(find.widgetWithText(FilledButton, 'Save'));
        await tester.pumpAndSettle();

        expect(profileCreates, 0);
        expect(writes, hasLength(1));
        expect(writes.single['name'], 'Renamed Mimosa radio');
        expect(writes.single['snmp_profile_id'], 'private-v2c');
        expect(writes.single['tower_id'], 'north');
        expect(writes.single['ip_address'], '192.0.2.55');
        expect(writes.single['vendor'], 'mimosa');
        expect(writes.single['model'], 'C5c');
        expect(writes.single['poll_interval'], 120);
        expect(writes.single['retries'], 1);
        expect(writes.single['failure_threshold'], 5);
        expect(writes.single['cpu_threshold'], 85);
        expect(writes.single.containsKey('community'), isFalse);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
}

Finder dropdownNamed(String label) => find.byWidgetPredicate(
  (widget) =>
      widget is DropdownButtonFormField<String> &&
      widget.decoration.labelText == label,
);

Future<void> openNorthTower(WidgetTester tester, Api api) async {
  tester.view.physicalSize = const Size(2400, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      home: Operations(api: api, logout: () async {}),
    ),
  );
  await tester.pumpAndSettle();
  await tester.tap(find.widgetWithText(ListTile, 'Towers'));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Unassigned towers'));
  await tester.pumpAndSettle();
  await tester.tap(find.text('North').first);
  await tester.pumpAndSettle();
}
