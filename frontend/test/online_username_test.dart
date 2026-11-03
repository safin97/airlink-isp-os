import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/sas4_clients.dart';
import 'package:airlink_isp_os/sas4_user_details.dart';

void main() {
  for (final id in [null, 7]) {
    testWidgets('Online username opens information with user ID $id', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1800, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final paths = <String>[];
      final api = Api(
        client: MockClient((request) async {
          expect(request.method, 'GET');
          paths.add(request.url.path);
          dynamic body;
          if (request.url.path.endsWith('/online')) {
            body = {
              'clients': [
                {
                  'id': id,
                  'session_id': 900,
                  'username': 'customer',
                  'ip_address': '192.0.2.1',
                  'online': true,
                  'status': 'active',
                },
              ],
              'total': 1,
              'page': 1,
              'last_page': 1,
              'per_page': 7,
            };
          } else if (request.url.path.endsWith('/resolve-user')) {
            expect(id, isNull);
            expect(request.url.queryParameters['username'], 'customer');
            body = {'id': 7, 'username': 'customer'};
          } else if (request.url.path.endsWith('/users/7')) {
            body = {
              'id': 7,
              'username': 'customer',
              'fields': [],
              'can_recharge': false,
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
      await tester.tap(find.text('192.0.2.1'));
      await tester.pumpAndSettle();
      expect(find.byType(Sas4UserDetails), findsNothing);
      await tester.tap(find.text('customer'));
      await tester.pumpAndSettle();
      expect(
        tester.widget<Sas4UserDetails>(find.byType(Sas4UserDetails)).userId,
        7,
      );
      expect(paths, contains('/api/integrations/sas4/users/7'));
      expect(paths, isNot(contains('/api/integrations/sas4/users/900')));
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }
}
