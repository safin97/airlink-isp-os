import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/telegram_account.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  testWidgets(
    'owner signs in with code and two-step password, then disconnects',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(900, 1600));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      var stage = 'disconnected';
      final bodies = <Map<String, dynamic>>[];
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'DELETE') {
            stage = 'disconnected';
          } else if (request.method == 'POST') {
            bodies.add(jsonDecode(request.body));
            stage = request.url.path.endsWith('/login')
                ? 'code'
                : stage == 'code'
                ? 'password'
                : 'connected';
          }
          return http.Response(
            jsonEncode({
              'stage': stage,
              'profile': {'first_name': 'Owner', 'username': 'owner'},
            }),
            200,
          );
        }),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: TelegramAccountSettings(api: api),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextField, 'Telegram API ID'),
        '12345',
      );
      await tester.enterText(
        find.widgetWithText(TextField, 'Telegram API hash'),
        'a' * 32,
      );
      await tester.enterText(
        find.widgetWithText(
          TextField,
          'Your Telegram phone number (+country code)',
        ),
        '+9647501234567',
      );
      expect(
        tester
            .widget<TextField>(
              find.widgetWithText(TextField, 'Telegram API hash'),
            )
            .obscureText,
        isTrue,
      );
      await tester.tap(find.text('Send login code'));
      await tester.pumpAndSettle();
      expect(bodies.first['api_id'], 12345);
      await tester.enterText(
        find.widgetWithText(TextField, 'Telegram login code'),
        '12345',
      );
      await tester.tap(find.text('Verify code'));
      await tester.pumpAndSettle();
      expect(find.text('Telegram two-step password'), findsOneWidget);
      await tester.enterText(
        find.widgetWithText(TextField, 'Telegram two-step password'),
        'secret',
      );
      await tester.tap(find.text('Sign in to Telegram'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Connected: Owner'), findsOneWidget);
      expect(bodies.last, {'password': 'secret'});
      await tester.tap(find.text('Disconnect Telegram account'));
      await tester.pumpAndSettle();
      expect(find.text('Send login code'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  for (final status in ['found', 'unknown']) {
    testWidgets(
      'customer lookup automatically checks once and displays $status',
      (tester) async {
        var checks = 0;
        final api = Api(
          client: MockClient((request) async {
            if (request.url.path.endsWith('/lookup')) {
              checks++;
              expect(request.method, 'POST');
              expect(request.url.path.endsWith('/users/7/lookup'), isTrue);
              return http.Response(
                jsonEncode({
                  'status': status,
                  'profile': status == 'found'
                      ? {
                          'id': '123',
                          'first_name': 'Customer',
                          'username': 'customer',
                        }
                      : null,
                }),
                200,
              );
            }
            return http.Response('{"stage":"connected"}', 200);
          }),
        )..user = {'role': 'owner'};
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(body: TelegramPhoneLookup(api: api, customerId: 7)),
          ),
        );
        await tester.pumpAndSettle();
        expect(checks, 1);
        expect(
          find.textContaining(
            status == 'found' ? 'Telegram account found' : 'Unknown —',
          ),
          findsOneWidget,
        );
        await tester.pump(const Duration(seconds: 30));
        expect(checks, 1);
        await tester.tap(find.text('Check saved phone'));
        await tester.pumpAndSettle();
        expect(checks, 2);
        expect(
          find.textContaining('must still start and link'),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets('disconnected account does not attempt lookup', (tester) async {
    var requests = 0;
    final api = Api(
      client: MockClient((request) async {
        requests++;
        expect(request.method, 'GET');
        return http.Response('{"stage":"disconnected"}', 200);
      }),
    )..user = {'role': 'owner'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: TelegramPhoneLookup(api: api, customerId: 7)),
      ),
    );
    await tester.pumpAndSettle();
    expect(requests, 1);
    expect(
      find.textContaining('Connect your Telegram user account'),
      findsOneWidget,
    );
  });

  for (final succeeds in [true, false]) {
    testWidgets('phone test sends only on click and handles success=$succeeds', (
      tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(900, 1400));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      var sends = 0;
      final api = Api(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/test')) {
            sends++;
            expect(request.method, 'POST');
            expect(jsonDecode(request.body), {
              'test_token': 'opaque-recipient',
              'language': 'ar',
            });
            return http.Response(
              succeeds
                  ? '{"sent":true,"sender":"telegram_account"}'
                  : '{"detail":"Telegram privacy settings prevent delivery."}',
              succeeds ? 200 : 403,
            );
          }
          if (request.url.path.endsWith('/lookup')) {
            return http.Response(
              '{"status":"found","profile":{"id":"123","first_name":"Customer"},"test_token":"opaque-recipient"}',
              200,
            );
          }
          return http.Response(
            '{"stage":"connected","profile":{"username":"OwnerAccount"}}',
            200,
          );
        }),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TelegramPhoneLookup(api: api, customerId: 7, language: 'ar'),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(sends, 0);
      expect(find.text('Test sender: @OwnerAccount'), findsOneWidget);
      await tester.tap(find.text('Send test from connected account'));
      await tester.pumpAndSettle();
      expect(sends, 1);
      expect(
        find.text(
          succeeds
              ? 'Telegram accepted the test from your connected account.'
              : 'Telegram privacy settings prevent delivery.',
        ),
        findsOneWidget,
      );
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(
                FilledButton,
                'Send test from connected account',
              ),
            )
            .onPressed,
        isNull,
      );
      await tester.pump(const Duration(seconds: 35));
      expect(sends, 1);
      expect(tester.takeException(), isNull);
    });
  }
}
