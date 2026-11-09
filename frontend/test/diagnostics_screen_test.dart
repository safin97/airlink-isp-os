import 'dart:convert';

import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  testWidgets('Diagnostics navigation shows system and update problems', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var diagnosticsReads = 0;
    final api = Api(
      client: MockClient((request) async {
        if (request.url.path == '/api/diagnostics') {
          diagnosticsReads++;
          return http.Response(
            jsonEncode({
              'status': 'problems',
              'problems': [
                {
                  'severity': 'critical',
                  'source': 'update',
                  'title': 'Software update requires local recovery review',
                  'detail': 'Migration failed',
                },
              ],
              'services': {
                'airlink-api': 'active',
                'airlink-monitor': 'failed',
              },
              'resources': {
                'cpu_percent': 10,
                'memory_percent': 20,
                'storage_percent': 30,
              },
              'update': {'status': 'failed', 'recovery_required': true},
              'recent_errors': ['airlink-update-job: migration failed'],
            }),
            200,
          );
        }
        if (request.url.path == '/api/dashboard') {
          return http.Response('{}', 200);
        }
        return http.Response('[]', 200);
      }),
    )..user = {'username': 'owner', 'role': 'owner'};

    await tester.pumpWidget(
      MaterialApp(
        home: Operations(api: api, logout: () async {}),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(ListTile, 'Diagnostics'));
    await tester.pumpAndSettle();

    expect(find.text('1 active problem'), findsOneWidget);
    expect(
      find.text('Software update requires local recovery review'),
      findsOneWidget,
    );
    expect(find.text('Migration failed'), findsOneWidget);
    expect(find.text('airlink-monitor: failed'), findsOneWidget);
    expect(find.text('airlink-update-job: migration failed'), findsOneWidget);
    expect(
      find.textContaining('do not clear the failed update marker'),
      findsOneWidget,
    );
    expect(diagnosticsReads, 1);

    await tester.tap(
      find.widgetWithText(OutlinedButton, 'Refresh diagnostics'),
    );
    await tester.pumpAndSettle();
    expect(diagnosticsReads, 2);
  });
}
