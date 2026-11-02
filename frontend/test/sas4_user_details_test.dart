import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/sas4_clients.dart';

void main() {
  testWidgets(
    'click user, preserve edits during refresh, save changed fields and return',
    (tester) async {
      tester.view.physicalSize = const Size(1400, 1100);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final requests = <http.Request>[];
      final api = Api(
        client: MockClient((request) async {
          requests.add(request);
          if (request.method == 'PUT') {
            return http.Response('{"saved":true}', 200);
          }
          if (request.url.path.endsWith('/users/7')) {
            return http.Response(
              jsonEncode({
                'id': 7,
                'username': 'customer',
                'fields': [
                  {
                    'key': 'firstname',
                    'label': 'First name',
                    'kind': 'text',
                    'value': 'Old',
                    'editable': true,
                  },
                  {
                    'key': 'lastname',
                    'label': 'Last name',
                    'kind': 'text',
                    'value': 'Family',
                    'editable': true,
                  },
                  {
                    'key': 'phone',
                    'label': 'Phone number',
                    'kind': 'text',
                    'value': '123',
                    'editable': true,
                  },
                  {
                    'key': 'expiration',
                    'label': 'Card expiry date',
                    'kind': 'datetime',
                    'value': '2026-12-01 00:00:00',
                    'editable': false,
                    'reason': 'Requires SAS4 advanced permission.',
                  },
                  {
                    'key': 'new_password',
                    'label': 'New password',
                    'kind': 'password',
                    'value': null,
                    'editable': true,
                  },
                ],
              }),
              200,
            );
          }
          if (request.url.path.endsWith('/clients')) {
            return http.Response(
              jsonEncode({
                'clients': [
                  {'id': 7, 'username': 'customer'},
                ],
                'total': 1,
                'page': 1,
                'last_page': 1,
              }),
              200,
            );
          }
          return http.Response('{"configured":true}', 200);
        }),
      )..user = {'role': 'manager'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: Sas4Clients(api: api, showDashboard: false),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('customer'));
      await tester.pumpAndSettle();
      expect(find.text('customer • User information'), findsOneWidget);
      // Locate through TextField decoration; TextFormField keeps its builder configuration private.
      Finder input(String label) => find.byWidgetPredicate(
        (w) => w is TextField && w.decoration?.labelText == label,
      );
      expect(
        tester.widget<TextField>(input('Card expiry date')).readOnly,
        isTrue,
      );
      expect(tester.widget<TextField>(input('First name')).readOnly, isTrue);
      expect(find.text('Save changes'), findsNothing);
      await tester.tap(find.text('Edit'));
      await tester.pumpAndSettle();
      expect(tester.widget<TextField>(input('First name')).readOnly, isFalse);
      await tester.enterText(input('First name'), 'New');
      await tester.enterText(input('Phone number'), '555');
      final before = requests.length;
      await tester.pump(const Duration(seconds: 30));
      await tester.pumpAndSettle();
      expect(requests.length, before);
      expect(
        tester.widget<TextField>(input('First name')).controller!.text,
        'New',
      );
      await tester.tap(find.byIcon(Icons.arrow_back));
      await tester.pumpAndSettle();
      expect(find.text('Discard unsaved changes?'), findsNothing);
      expect(find.text('ISP Card • Users list'), findsOneWidget);
      expect(requests.where((r) => r.method == 'PUT'), isEmpty);
      await tester.tap(find.text('customer'));
      await tester.pumpAndSettle();
      expect(
        tester.widget<TextField>(input('First name')).controller!.text,
        'Old',
      );
      await tester.tap(find.text('Edit'));
      await tester.pumpAndSettle();
      await tester.enterText(input('First name'), 'New');
      await tester.enterText(input('Phone number'), '555');
      await tester.tap(find.text('Save changes'));
      await tester.pumpAndSettle();
      final save = requests.singleWhere((r) => r.method == 'PUT');
      expect(save.url.path, '/api/integrations/sas4/users/7');
      expect(jsonDecode(save.body), {
        'changes': {'firstname': 'New', 'phone': '555'},
      });
      expect(find.text('User information saved to SAS4.'), findsOneWidget);
      expect(find.text('Edit'), findsOneWidget);
      expect(tester.widget<TextField>(input('First name')).readOnly, isTrue);
      await tester.tap(find.byIcon(Icons.arrow_back));
      await tester.pumpAndSettle();
      expect(find.text('ISP Card • Users list'), findsOneWidget);
      expect(requests.last.url.path, '/api/integrations/sas4/clients');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
