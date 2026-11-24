import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/client_portal_settings.dart';

void main() {
  Future<void> open(WidgetTester tester, Api api) async {
    tester.view.physicalSize = const Size(390, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    api.user ??= {};
    api.user!.putIfAbsent('role', () => 'owner');
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            padding: const EdgeInsets.all(20),
            child: ClientPortalSettings(api: api),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  Future<void> tap(WidgetTester tester, String text) async {
    await tester.ensureVisible(find.text(text));
    await tester.pumpAndSettle();
    await tester.tap(find.text(text));
    await tester.pumpAndSettle();
  }

  testWidgets(
    'adds 172 without losing 10, persists changes and removes only the chosen range',
    (tester) async {
      var ranges = ['10.0.0.0/8'];
      final saves = <Map<String, dynamic>>[];
      final api = Api(
        client: MockClient((request) async {
          expect(request.url.path, '/api/client-portal');
          if (request.method == 'PUT') {
            final body = jsonDecode(request.body) as Map<String, dynamic>;
            saves.add(body);
            ranges = List<String>.from(body['subscriber_networks']);
          }
          return http.Response(
            jsonEncode({'enabled': true, 'subscriber_networks': ranges}),
            200,
          );
        }),
      );
      await open(tester, api);
      expect(find.text('10.0.0.0/8'), findsOneWidget);
      await tester.enterText(find.byType(TextField), '172.0.0.0/8');
      await tap(tester, 'Add IP range');
      expect(find.text('172.0.0.0/8'), findsOneWidget);
      expect(find.text('10.0.0.0/8'), findsOneWidget);
      expect(saves, isEmpty);
      await tap(tester, 'Save client portal');
      expect(saves.single, {
        'enabled': true,
        'subscriber_networks': ['10.0.0.0/8', '172.0.0.0/8'],
      });
      expect(
        find.text(
          'Client portal saved. Existing client sessions have been signed out.',
        ),
        findsOneWidget,
      );
      await tester.ensureVisible(find.byTooltip('Remove 10.0.0.0/8'));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Remove 10.0.0.0/8'));
      await tester.pumpAndSettle();
      await tap(tester, 'Save client portal');
      expect(saves.last['subscriber_networks'], ['172.0.0.0/8']);
      await tester.pumpWidget(const SizedBox.shrink());
      api.user ??= {};
      api.user!.putIfAbsent('role', () => 'owner');
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(child: ClientPortalSettings(api: api)),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('172.0.0.0/8'), findsOneWidget);
      expect(find.text('10.0.0.0/8'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'rejects invalid and duplicate ranges; Save includes an unadded valid range',
    (tester) async {
      final saves = <Map<String, dynamic>>[];
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'PUT') saves.add(jsonDecode(request.body));
          return http.Response(
            jsonEncode(
              saves.isEmpty
                  ? {
                      'enabled': true,
                      'subscriber_networks': ['10.0.0.0/8'],
                    }
                  : saves.last,
            ),
            200,
          );
        }),
      );
      await open(tester, api);
      for (final invalid in [
        '172.x.x.x',
        '172.0.0.0/33',
        '999.0.0.0/8',
        '172.20.5.10/16',
        '0.0.0.0/0',
        '10.0.0.0/8',
      ]) {
        await tester.ensureVisible(find.byType(TextField));
        await tester.enterText(find.byType(TextField), invalid);
        await tap(tester, 'Add IP range');
        expect(
          tester
              .widget<TextField>(find.byType(TextField))
              .decoration!
              .errorText,
          isNotNull,
        );
        await tap(tester, 'Save client portal');
        expect(saves, isEmpty);
      }
      await tester.ensureVisible(find.byType(TextField));
      await tester.enterText(find.byType(TextField), '2001:db8::/32');
      await tap(tester, 'Save client portal');
      expect(saves.single['subscriber_networks'], [
        '10.0.0.0/8',
        '2001:db8::/32',
      ]);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'failed reads prevent overwriting settings and failed saves retain edits',
    (tester) async {
      var readable = false, writes = 0;
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'PUT') {
            writes++;
            return http.Response('{"detail":"Could not save settings"}', 409);
          }
          return readable
              ? http.Response(
                  '{"enabled":true,"subscriber_networks":["10.0.0.0/8"]}',
                  200,
                )
              : http.Response('{"detail":"Settings unavailable"}', 403);
        }),
      );
      await open(tester, api);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Save client portal'),
            )
            .onPressed,
        isNull,
      );
      expect(writes, 0);
      readable = true;
      await tap(tester, 'Retry connection');
      await tester.ensureVisible(find.byType(TextField));
      await tester.enterText(find.byType(TextField), '172.0.0.0/8');
      await tap(tester, 'Save client portal');
      expect(writes, 1);
      expect(find.text('Could not save settings'), findsOneWidget);
      expect(find.text('172.0.0.0/8'), findsOneWidget);
      expect(find.text('10.0.0.0/8'), findsOneWidget);
      expect(find.textContaining('Client portal saved.'), findsNothing);
    },
  );
}
