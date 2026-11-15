import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/pc_updates.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  testWidgets('owner reviews versions and confirms the exact plan', (
    tester,
  ) async {
    final writes = <http.Request>[];
    var state = <String, dynamic>{
      'supported': true,
      'state': {'status': 'idle'},
    };
    final api = Api(
      client: MockClient((request) async {
        if (request.method == 'POST') {
          writes.add(request);
          if (request.url.path.endsWith('/check')) {
            state = {
              'supported': true,
              'state': {'status': 'ready'},
              'plan': {
                'id': 'exact-reviewed-plan',
                'packages': [
                  {
                    'name': 'nvidia-driver',
                    'installed': '610.1',
                    'candidate': '610.2',
                    'category': 'GPU driver',
                  },
                ],
              },
            };
          } else {
            state = {
              'supported': true,
              'state': {'status': 'installed'},
              'reboot_required': true,
            };
          }
        }
        return http.Response(
          jsonEncode(state),
          200,
          headers: {'content-type': 'application/json'},
        );
      }),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(child: PcUpdates(api: api)),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(writes, isEmpty);
    await tester.tap(find.text('Check online'));
    await tester.pumpAndSettle();
    expect(find.text('610.1 → 610.2'), findsOneWidget);
    await tester.tap(find.text('Review and install'));
    await tester.pumpAndSettle();
    expect(writes.length, 1);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(writes.length, 1);
    await tester.tap(find.text('Review and install'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Install updates'));
    await tester.pumpAndSettle();
    expect(jsonDecode(writes.last.body), {
      'confirm': true,
      'plan_id': 'exact-reviewed-plan',
    });
    expect(
      find.textContaining('Restart recommended to activate updates'),
      findsOneWidget,
    );
  });

  testWidgets('local preview disables online package operations', (
    tester,
  ) async {
    final api = Api(
      client: MockClient((request) async {
        expect(request.method, 'GET');
        return http.Response(
          jsonEncode({
            'supported': false,
            'state': {'status': 'unavailable'},
            'reason': 'Available on the installed AirLink Linux PC.',
          }),
          200,
        );
      }),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: PcUpdates(api: api)),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      find.text('Available on the installed AirLink Linux PC.'),
      findsOneWidget,
    );
    expect(
      tester
          .widget<OutlinedButton>(
            find.widgetWithText(OutlinedButton, 'Check online'),
          )
          .onPressed,
      isNull,
    );
    expect(find.text('Review and install'), findsNothing);
  });
}
