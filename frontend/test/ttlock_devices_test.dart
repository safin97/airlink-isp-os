import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/ttlock.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  for (final width in [390.0, 1280.0]) {
    testWidgets('device management and app handoff at $width', (tester) async {
      await tester.binding.setSurfaceSize(Size(width, 900));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      var name = 'Office door';
      var fail = false;
      var removedInApp = false;
      var listCalls = 0;
      final writes = <http.Request>[];
      final api = Api(
        client: MockClient((request) async {
          if (request.method != 'GET') {
            writes.add(request);
            expect(request.method, 'PUT');
            expect(request.url.path, '/api/integrations/ttlock/locks/42/name');
            if (fail) {
              return http.Response(
                '{"detail":"Sync devices to check the name."}',
                502,
              );
            }
            name = jsonDecode(request.body)['name'];
            return http.Response(jsonEncode({'id': 42, 'name': name}), 200);
          }
          if (request.url.path.endsWith('/locks')) {
            listCalls++;
            return http.Response(
              jsonEncode({
                'items': removedInApp
                    ? []
                    : [
                        {
                          'id': 42,
                          'name': name,
                          'battery': 54,
                          'group': '',
                          'has_gateway': true,
                        },
                      ],
                'page': 1,
                'pages': removedInApp ? 0 : 1,
                'total': removedInApp ? 0 : 1,
              }),
              200,
            );
          }
          return http.Response(
            '{"configured":true,"region":"eu","username":"owner","client_id":"app123"}',
            200,
          );
        }),
      );
      api.user ??= {};
      api.user!.putIfAbsent('role', () => 'owner');
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: TTLockPage(api: api)),
        ),
      );
      await tester.pumpAndSettle();

      Future<void> tap(String label) async {
        if (label == 'Edit name' || label == 'Remove in app') {
          await tester.ensureVisible(find.byTooltip('Device options'));
          await tester.pumpAndSettle();
          await tester.tap(find.byTooltip('Device options'));
          await tester.pumpAndSettle();
        }
        await tester.ensureVisible(find.text(label));
        await tester.pumpAndSettle();
        await tester.tap(find.text(label));
        await tester.pumpAndSettle();
      }

      await tap('Add Lock');
      expect(find.textContaining('use Add Lock'), findsOneWidget);
      expect(writes, isEmpty);
      await tester.tap(find.widgetWithText(FilledButton, 'Sync devices').last);
      await tester.pumpAndSettle();
      expect(listCalls, 2);
      await tap('Edit name');
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Device name'),
        '',
      );
      await tap('Save name');
      expect(find.text('Required'), findsOneWidget);
      expect(writes, isEmpty);
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Device name'),
        'Main entrance',
      );
      await tap('Cancel');
      expect(writes, isEmpty);
      await tap('Edit name');
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Device name'),
        'Main entrance',
      );
      await tap('Save name');
      expect(jsonDecode(writes.single.body), {
        'name': 'Main entrance',
        'page': 1,
      });
      expect(find.text('Main entrance'), findsOneWidget);
      fail = true;
      await tap('Edit name');
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Device name'),
        'Unconfirmed',
      );
      await tap('Save name');
      expect(writes.length, 2);
      expect(
        find.textContaining('Sync devices to check the name'),
        findsOneWidget,
      );
      expect(find.text('Main entrance'), findsOneWidget);
      expect(find.text('Unconfirmed'), findsNothing);
      await tap('Remove in app');
      expect(
        find.textContaining('Main entrance • Lock ID: 42'),
        findsOneWidget,
      );
      expect(find.textContaining('Reset the physical lock'), findsOneWidget);
      removedInApp = true;
      await tester.tap(find.widgetWithText(FilledButton, 'Sync devices').last);
      await tester.pumpAndSettle();
      expect(find.text('Main entrance'), findsNothing);
      expect(
        find.textContaining('No administrator-owned locks'),
        findsOneWidget,
      );
      expect(writes.length, 2); // Add/remove guidance never sends mutations.
      expect(tester.takeException(), isNull);
    });
  }
}
