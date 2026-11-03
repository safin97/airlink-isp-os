import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/device_management_dialog.dart';

void main() {
  for (final canEdit in [true, false]) {
    testWidgets('Device management explicit apply and clients; edit=$canEdit', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1400, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final writes = <dynamic>[];
      final api = Api(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/wireless-clients')) {
            return http.Response(
              jsonEncode({
                'status': 'available',
                'total': 1,
                'clients': [
                  {
                    'mac_address': 'AA:BB:CC:DD:EE:01',
                    'interface': 'wlan1',
                    'ssid': 'Old',
                    'signal_dbm': -60,
                  },
                ],
              }),
              200,
            );
          }
          if (request.method == 'PUT') {
            writes.add(jsonDecode(request.body));
            return http.Response('{"status":"accepted"}', 200);
          }
          return http.Response(
            jsonEncode({
              'supported': true,
              'radios': [
                {
                  'menu': 'wireless',
                  'id': '*1',
                  'name': 'wlan1',
                  'ssid': 'Old',
                  'editable': true,
                },
              ],
            }),
            200,
          );
        }),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: DeviceManagementDialog(
              api: api,
              device: {
                'id': 'radio',
                'name': 'Radio',
                'ip_address': '192.0.2.1',
              },
              canEdit: canEdit,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final field = find.byKey(const ValueKey('ssid-wireless:*1'));
      expect(tester.widget<TextField>(field).enabled, canEdit);
      if (canEdit) {
        await tester.enterText(field, 'New');
        await tester.pumpAndSettle();
        expect(writes, isEmpty);
        await tester.tap(find.text('Apply SSID'));
        await tester.pumpAndSettle();
        expect(writes.single, {
          'menu': 'wireless',
          'radio_id': '*1',
          'previous_ssid': 'Old',
          'ssid': 'New',
        });
        expect(find.textContaining('Device accepted'), findsOneWidget);
      } else {
        expect(find.text('Apply SSID'), findsNothing);
        expect(writes, isEmpty);
      }
      await tester.tap(find.text('Registration clients'));
      await tester.pumpAndSettle();
      expect(find.text('AA:BB:CC:DD:EE:01'), findsOneWidget);
      await tester.tap(find.text('Close').last);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }
}
