import 'dart:convert';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/ttlock.dart';

void main() {
  for (final width in [390.0, 1280.0]) {
    testWidgets('TTLock login, status and confirmed commands at $width', (
      tester,
    ) async {
      tester.view.physicalSize = Size(width, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var configured = false;
      final commands = <Map<String, dynamic>>[];
      final listing = {
        'items': [
          {
            'id': 42,
            'name': 'Office door',
            'battery': 54,
            'has_gateway': true,
            'group': '',
          },
        ],
        'page': 1,
        'pages': 1,
        'total': 1,
        'observed_at': '2026-11-23T10:00:00Z',
      };
      final api = Api(
        client: MockClient((request) async {
          final path = request.url.path;
          if (path.endsWith('/application')) {
            return http.Response(
              '{"configured":true,"region":"eu","client_id":"app123"}',
              200,
            );
          }
          if (path.endsWith('/action')) {
            expect(request.method, 'POST');
            commands.add(Map<String, dynamic>.from(jsonDecode(request.body)));
            return http.Response('{"status":"completed"}', 200);
          }
          if (path.endsWith('/state')) {
            return http.Response(
              '{"state":"locked","observed_at":"2026-11-23T10:00:00Z"}',
              200,
            );
          }
          if (path.endsWith('/locks')) {
            return http.Response(jsonEncode(listing), 200);
          }
          expect(path, '/api/integrations/ttlock');
          if (request.method == 'PUT') {
            expect(jsonDecode(request.body), {
              'username': '+9647500000000',
              'password': 'app-password',
            });
            configured = true;
            return http.Response(
              jsonEncode({'configured': true, 'locks': listing}),
              200,
            );
          }
          if (request.method == 'DELETE') configured = false;
          return http.Response(
            jsonEncode({
              'configured': configured,
              if (configured) ...{
                'region': 'eu',
                'username': '+9647500000000',
                'client_id': 'app123',
              },
            }),
            200,
          );
        }),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: TTLockPage(api: api)),
        ),
      );
      await tester.pumpAndSettle();
      for (final pair in [
        ('TTLock username / phone', '+9647500000000'),
        ('TTLock password', 'app-password'),
      ]) {
        final field = find.widgetWithText(TextFormField, pair.$1);
        await tester.ensureVisible(field);
        await tester.pumpAndSettle();
        await tester.enterText(field, pair.$2);
      }
      await tester.ensureVisible(find.text('Sign in to TTLock'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Sign in to TTLock'));
      await tester.pumpAndSettle();
      expect(find.text('Office door'), findsOneWidget);
      expect(find.text('Battery: 54%'), findsOneWidget);
      expect(find.text('State Unknown'), findsOneWidget);
      await tester.ensureVisible(find.text('Check status'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Check status'));
      await tester.pumpAndSettle();
      expect(find.text('Locked'), findsOneWidget);
      await tester.ensureVisible(find.text('Unlock'));
      await tester.pumpAndSettle();
      final unlock = tester
          .widget<FilledButton>(find.widgetWithText(FilledButton, 'Unlock'))
          .onPressed!;
      unlock();
      unlock();
      await tester.pumpAndSettle();
      expect(find.text('Unlock Office door?'), findsOneWidget);
      expect(commands, isEmpty);
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(commands, isEmpty);
      await tester.tap(find.text('Unlock'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Confirm Unlock'));
      await tester.pumpAndSettle();
      expect(commands.length, 1);
      expect(commands.single['action'], 'unlock');
      expect(commands.single['page'], 1);
      expect(commands.single['request_id'], matches(RegExp(r'^[a-f0-9]{32}$')));
      expect(find.text('State Unknown'), findsOneWidget);
      await tester.ensureVisible(find.text('Reconnect'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Reconnect'));
      await tester.pumpAndSettle();
      expect(find.widgetWithText(TextFormField, 'Client Secret'), findsNothing);
      expect(find.widgetWithText(TextFormField, 'Client ID'), findsNothing);
      final password = tester.widget<TextField>(
        find.descendant(
          of: find.widgetWithText(TextFormField, 'TTLock password'),
          matching: find.byType(TextField),
        ),
      );
      expect(password.controller!.text, isEmpty);
      expect(password.obscureText, isTrue);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('unconfirmed command is shown once without automatic replay', (
    tester,
  ) async {
    var commands = 0;
    final api = Api(
      client: MockClient((request) async {
        if (request.url.path.endsWith('/action')) {
          commands++;
          return http.Response(
            '{"detail":"TTLock did not confirm the result. Check the physical lock."}',
            502,
          );
        }
        if (request.url.path.endsWith('/locks')) {
          return http.Response(
            jsonEncode({
              'items': [
                {
                  'id': 42,
                  'name': 'Office door',
                  'battery': null,
                  'group': '',
                  'has_gateway': true,
                },
              ],
              'page': 1,
              'pages': 1,
              'total': 1,
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
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: TTLockPage(api: api)),
      ),
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Unlock'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Unlock'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm Unlock'));
    await tester.pumpAndSettle();
    expect(commands, 1);
    expect(find.textContaining('Check the physical lock'), findsOneWidget);
    expect(find.text('State Unknown'), findsOneWidget);
  });
  testWidgets('one-time setup stays separate from two-field login', (
    tester,
  ) async {
    var saved = false;
    var loginCalls = 0;
    final api = Api(
      client: MockClient((request) async {
        if (request.url.path.endsWith('/application')) {
          if (request.method == 'PUT') {
            expect(jsonDecode(request.body), {
              'region': 'eu',
              'client_id': 'app123',
              'client_secret': 'private-secret',
            });
            saved = true;
          }
          return http.Response(
            jsonEncode({
              'configured': saved,
              'region': 'eu',
              'client_id': 'app123',
            }),
            200,
          );
        }
        if (request.method == 'PUT') loginCalls++;
        return http.Response('{"configured":false}', 200);
      }),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: TTLockPage(api: api)),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byType(TextFormField), findsNWidgets(2));
    await tester.ensureVisible(find.text('Sign in to TTLock'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Sign in to TTLock'));
    await tester.pumpAndSettle();
    expect(
      find.text('Enter your TTLock username and password.').hitTestable(),
      findsOneWidget,
    );
    expect(loginCalls, 0);
    await tester.ensureVisible(find.text('One-time integration setup'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('One-time integration setup'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.widgetWithText(TextFormField, 'Client ID'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Client ID'),
      'app123',
    );
    await tester.ensureVisible(
      find.widgetWithText(TextFormField, 'Client Secret'),
    );
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Client Secret'),
      'private-secret',
    );
    await tester.ensureVisible(find.text('Save integration setup'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Save integration setup'));
    await tester.pumpAndSettle();
    expect(saved, isTrue);
    expect(loginCalls, 0);
    expect(find.widgetWithText(TextFormField, 'Client Secret'), findsNothing);
    await tester.ensureVisible(find.text('TTLock login'));
    await tester.pumpAndSettle();
    await tester.pumpAndSettle();
    expect(find.byType(TextFormField), findsNWidgets(2));
    expect(tester.takeException(), isNull);
  });
  testWidgets(
    'login fields are editable immediately and preserve drafts during loading',
    (tester) async {
      final settings = Completer<http.Response>();
      final api = Api(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/application')) return settings.future;
          expect(request.url.path, '/api/integrations/ttlock');
          return http.Response(
            '{"configured":true,"username":"saved-account"}',
            200,
          );
        }),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: TTLockPage(api: api)),
        ),
      );
      final username = find.widgetWithText(
        TextFormField,
        'TTLock username / phone',
      );
      final password = find.widgetWithText(TextFormField, 'TTLock password');
      expect(username, findsOneWidget);
      expect(password, findsOneWidget);
      await tester.enterText(username, 'my-account');
      await tester.enterText(password, 'draft-password');
      settings.complete(
        http.Response(
          '{"configured":true,"region":"eu","client_id":"app123"}',
          200,
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('my-account'), findsOneWidget);
      expect(
        tester
            .widget<TextField>(
              find.descendant(of: password, matching: find.byType(TextField)),
            )
            .controller!
            .text,
        'draft-password',
      );
      expect(find.text('TTLock login'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('failed settings and account reads never hide login fields', (
    tester,
  ) async {
    final api = Api(
      client: MockClient(
        (request) async =>
            http.Response('{"detail":"Connection unavailable"}', 503),
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: TTLockPage(api: api)),
      ),
    );
    await tester.pumpAndSettle();
    final username = find.widgetWithText(
      TextFormField,
      'TTLock username / phone',
    );
    final password = find.widgetWithText(TextFormField, 'TTLock password');
    expect(username, findsOneWidget);
    expect(password, findsOneWidget);
    await tester.enterText(username, 'my-account');
    await tester.enterText(password, 'draft-password');
    expect(
      tester
          .widget<TextField>(
            find.descendant(of: username, matching: find.byType(TextField)),
          )
          .enabled,
      isTrue,
    );
    expect(find.text('Connection unavailable'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
