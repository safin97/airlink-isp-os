import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/ttlock_device_page.dart';
import 'package:airlink_isp_os/ttlock_mobile_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'ttlock_mobile_test.dart' show FakeBluetooth;

class FakeService extends TTLockMobileService {
  final operations = <Map<String, dynamic>>[];
  final commands = <String>[];
  bool connectionFails = false;
  FakeService(super.api) : super(bluetooth: FakeBluetooth());
  @override
  Future<Map<String, dynamic>> command(
    int lockId,
    int page,
    String action,
    Map<String, dynamic> options,
    void Function(String) progress,
  ) async {
    expect(lockId, 42);
    expect(page, 1);
    commands.add(action);
    if (connectionFails) throw Exception('Lock is out of Bluetooth range');
    return {'battery': 72};
  }

  @override
  Future<Map<String, dynamic>> run(
    Map<String, dynamic> parameters,
    void Function(String) progress, {
    Map<String, dynamic>? scan,
  }) async {
    operations.add(parameters);
    return {'status': 'synced'};
  }
}

void main() {
  for (final mobile in [false, true]) {
    testWidgets('card management on ${mobile ? 'phone' : 'web'}', (
      tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 900));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final api = Api(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/pending')) {
            return http.Response('{"items":[]}', 200);
          }
          expect(request.method, 'GET');
          return http.Response(
            jsonEncode({
              'items': [
                {
                  'id': 7,
                  'name': 'Office card',
                  'number': '12345',
                  'start': 0,
                  'end': 0,
                  'cyclic': false,
                },
              ],
              'page': 1,
              'pages': 1,
              'total': 1,
            }),
            200,
          );
        }),
      );
      final service = FakeService(api);
      api.user ??= {};
      api.user!.putIfAbsent('role', () => 'owner');
      await tester.pumpWidget(
        MaterialApp(
          home: TTLockDevicePage(
            api: api,
            lock: {'id': 42, 'name': 'Office door'},
            lockPage: 1,
            service: mobile ? service : null,
          ),
        ),
      );
      await tester.pumpAndSettle();
      Future<void> tap(String label) async {
        if (find.text(label).evaluate().isEmpty) {
          await tester.scrollUntilVisible(find.text(label), 250);
        }
        await tester.ensureVisible(find.text(label).last);
        await tester.pumpAndSettle();
        await tester.tap(find.text(label).last);
        await tester.pumpAndSettle();
      }

      if (!mobile) {
        expect(find.text('Office card'), findsOneWidget);
        final add = tester.widget<FilledButton>(
          find.widgetWithText(FilledButton, 'Add card'),
        );
        expect(add.onPressed, isNull);
        expect(find.textContaining('Android or iPhone app'), findsOneWidget);
        expect(find.text('Connect via Bluetooth'), findsNothing);
      } else {
        await tap('Overview');
        await tester.scrollUntilVisible(
          find.text('Connect via Bluetooth'),
          250,
          scrollable: find.byType(Scrollable).last,
        );
        expect(find.text('Bluetooth not verified'), findsOneWidget);
        await tap('Connect via Bluetooth');
        expect(service.commands, ['battery']);
        expect(service.operations, isEmpty);
        expect(find.textContaining('Bluetooth verified at'), findsOneWidget);
        expect(find.text('Battery: 72%'), findsOneWidget);
        service.connectionFails = true;
        await tap('Connect via Bluetooth');
        expect(find.text('Bluetooth not verified'), findsOneWidget);
        expect(find.text('Battery: 72%'), findsNothing);
        expect(find.textContaining('out of Bluetooth range'), findsOneWidget);
        await tap('Cards');
        await tap('Add card');
        await tap('Start enrollment');
        expect(find.text('Enter a name'), findsOneWidget);
        expect(service.operations, isEmpty);
        await tester.enterText(
          find.widgetWithText(TextFormField, 'Name'),
          'New card',
        );
        await tap('Permanent access');
        await tap('Start enrollment');
        expect(service.operations.single, containsPair('action', 'card_add'));
        expect(service.operations.single['start'], 0);
        await tap('Remove card');
        expect(service.operations.length, 1);
        await tap('Cancel');
        expect(service.operations.length, 1);
        await tap('Remove card');
        await tap('Confirm');
        expect(service.operations.last['action'], 'card_delete');
        expect(service.operations.last['card_id'], 7);
      }
      expect(tester.takeException(), isNull);
    });
  }
}
