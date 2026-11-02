import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/sas4_clients.dart';

void main() {
  for (final editable in [true, false]) {
    testWidgets(
      'list recharge precedes Profile and respects permissions: $editable',
      (tester) async {
        tester.view.physicalSize = const Size(1600, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final requests = <http.Request>[];
        final api =
            Api(
                client: MockClient((r) async {
                  requests.add(r);
                  final Object data = switch (r.url.path) {
                    '/api/integrations/sas4' => {'configured': true},
                    '/api/integrations/sas4/clients' => {
                      'clients': [
                        {
                          'id': 7,
                          'username': 'customer',
                          'name': 'Customer',
                          'profile': '20 Mbps',
                        },
                      ],
                      'total': 1,
                      'page': 1,
                      'last_page': 1,
                    },
                    '/api/integrations/sas4/users/7/recharge' => {
                      'username': 'customer',
                      'profile': '20 Mbps',
                      'methods': {'credit': true},
                      'manager_cost': 100,
                    },
                    _ => [],
                  };
                  return http.Response(jsonEncode(data), 200);
                }),
              )
              ..user = {
                'role': 'manager',
                'sections': ['isp_card'],
                'editable_sections': editable ? ['isp_card'] : [],
              };
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
        expect(
          tester.getTopLeft(find.text('Recharge card')).dx,
          lessThan(tester.getTopLeft(find.text('Profile')).dx),
        );
        final button = find.widgetWithText(TextButton, 'Recharge');
        if (editable) {
          await tester.tap(button);
          await tester.pumpAndSettle();
          expect(
            requests.any(
              (r) => r.url.path == '/api/integrations/sas4/users/7/recharge',
            ),
            isTrue,
          );
          expect(requests.every((r) => r.method == 'GET'), isTrue);
          await tester.tap(find.widgetWithText(TextButton, 'Close'));
          await tester.pumpAndSettle();
        } else {
          expect(tester.widget<TextButton>(button).onPressed, isNull);
          expect(
            requests.any((r) => r.url.path.endsWith('/recharge')),
            isFalse,
          );
        }
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
}
