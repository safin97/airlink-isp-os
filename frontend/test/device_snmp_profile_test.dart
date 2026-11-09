import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';

void main() {
  for (final scenario in [
    (vendor: 'mikrotik', add: false, profile: 'private'),
    (vendor: 'ubiquiti_ac', add: false, profile: 'private'),
    (vendor: 'mimosa', add: false, profile: 'private'),
    (vendor: 'mimosa', add: false, profile: null),
    (vendor: 'mimosa', add: true, profile: null),
  ]) {
    final vendor = scenario.vendor;
    testWidgets(
      '${scenario.add ? 'Add' : 'Edit'} $vendor with ${scenario.profile} SNMP profile',
      (tester) async {
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
          'snmp_profile_id': scenario.profile,
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
                if (request.method == 'POST') {
                  writes.add(
                    Map<String, dynamic>.from(jsonDecode(request.body)),
                  );
                  result = {'id': 'radio'};
                } else {
                  result = scenario.add ? [] : [device];
                }
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
        if (scenario.add) {
          await tester.tap(find.widgetWithText(FilledButton, 'Add device'));
        } else {
          await tester.ensureVisible(find.byTooltip('Edit'));
          await tester.tap(find.byTooltip('Edit'));
        }
        await tester.pumpAndSettle();
        expect(profileReads, greaterThan(reads));
        if (scenario.add) {
          await tester.enterText(
            find.widgetWithText(TextFormField, 'Device name'),
            'Radio',
          );
          await tester.enterText(
            find.widgetWithText(TextFormField, 'Management IP'),
            '192.0.2.1',
          );
          for (final selection in [('Tower', 'North'), ('Vendor', 'Mimosa')]) {
            final dropdown = find.byWidgetPredicate(
              (w) =>
                  w is DropdownButtonFormField<String> &&
                  w.decoration.labelText == selection.$1,
            );
            await tester.ensureVisible(dropdown);
            await tester.tap(dropdown);
            await tester.pumpAndSettle();
            await tester.tap(find.text(selection.$2).last);
            await tester.pumpAndSettle();
          }
        }
        final select = find.byWidgetPredicate(
          (w) =>
              w is DropdownButtonFormField<String> &&
              w.decoration.labelText == 'SNMP profile',
        );
        final label = switch (vendor) {
          'mikrotik' => 'MikroTik switch',
          'ubiquiti_ac' => 'UBNT (M5 / AC / other models)',
          _ => 'Mimosa (all models)',
        };
        if (scenario.profile != null) {
          // Opening an existing device must preserve its custom profile.
          expect(find.text('Private profile — SNMP v3'), findsOneWidget);
          expect(find.text('SNMP Community String'), findsNothing);
          await tester.ensureVisible(select);
          await tester.tap(select);
          await tester.pumpAndSettle();
          final preset = find.text('$label — SNMP v2c / public').last;
          if (vendor == 'mimosa' || vendor == 'mikrotik') {
            expect(find.text('$label — SNMP v1 / public'), findsNothing);
          }
          await tester.ensureVisible(preset);
          await tester.tap(preset);
          await tester.pumpAndSettle();
        }
        expect(find.text('$label — SNMP v2c / public'), findsOneWidget);
        expect(find.text('SNMPv2c'), findsOneWidget);
        final community = tester.widget<TextFormField>(
          find.widgetWithText(TextFormField, 'SNMP Community String'),
        );
        expect(community.initialValue, 'public');
        expect(
          tester
              .widget<TextField>(
                find.descendant(
                  of: find.widgetWithText(
                    TextFormField,
                    'SNMP Community String',
                  ),
                  matching: find.byType(TextField),
                ),
              )
              .readOnly,
          isTrue,
        );
        expect(writes, isEmpty);
        await tester.tap(find.widgetWithText(FilledButton, 'Save'));
        await tester.pumpAndSettle();
        expect(writes.single['snmp_profile_id'], 'public-profile');
        expect(writes.single['vendor'], vendor);
        expect(writes.single['ip_address'], '192.0.2.1');
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
}
