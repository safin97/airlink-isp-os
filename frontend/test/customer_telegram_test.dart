import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/customer_telegram.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  testWidgets(
    'existing Telegram chat can receive a test before phone verification',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(900, 1600));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      var testsSent = 0;
      final api = Api(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/test')) {
            expect(request.method, 'POST');
            testsSent++;
            return http.Response('{"sent":true}', 200);
          }
          return http.Response(
            jsonEncode(
              request.url.path.endsWith('/customer-telegram')
                  ? {
                      'configured': true,
                      'enabled': true,
                      'can_manage': false,
                      'username': 'OwnerBot',
                    }
                  : {
                      'linked': false,
                      'telegram_linked': true,
                      'test_ready': true,
                      'phone_verified': false,
                      'phone_available': true,
                      'language': 'en',
                      'recent': [],
                    },
            ),
            200,
          );
        }),
      )..user = {'role': 'manager'};
      await tester.pumpWidget(
        MaterialApp(home: CustomerTelegram(api: api, customerId: 7)),
      );
      await tester.pumpAndSettle();
      expect(
        find.text('Telegram linked · phone verification pending'),
        findsOneWidget,
      );
      await tester.ensureVisible(find.text('Send test to Telegram'));
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Send test to Telegram'),
            )
            .onPressed,
        isNotNull,
      );
      await tester.tap(find.text('Send test to Telegram'));
      await tester.pumpAndSettle();
      expect(testsSent, 1);
      expect(
        find.text(
          'Test notification sent to the customer’s Telegram from the owner bot.',
        ),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'manager links customers through owner bot without token controls',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(360, 1400));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final requests = <http.Request>[];
      var pending = false;
      var awaitingPhone = false;
      final api = Api(
        client: MockClient((request) async {
          requests.add(request);
          Object data;
          if (request.url.path.endsWith('/customer-telegram')) {
            expect(request.method, 'GET');
            data = {
              'configured': true,
              'enabled': true,
              'username': 'OwnerCustomerBot',
              'can_manage': false,
              'sender': 'owner',
              'timezone': 'Asia/Baghdad',
            };
          } else if (request.url.path.endsWith('/link')) {
            expect(request.method, 'POST');
            expect(jsonDecode(request.body), {'language': 'en'});
            pending = true;
            data = {
              'url':
                  'https://t.me/OwnerCustomerBot?start=private-customer-link',
            };
          } else {
            data = {
              'linked': false,
              'language': 'en',
              'pending_link': pending,
              'awaiting_phone': awaitingPhone,
              'phone_available': true,
              'phone_verified': false,
              'recent': [],
            };
          }
          return http.Response(jsonEncode(data), 200);
        }),
      )..user = {'role': 'manager'};
      await tester.pumpWidget(
        MaterialApp(home: CustomerTelegram(api: api, customerId: 7)),
      );
      await tester.pumpAndSettle();
      expect(find.text('@OwnerCustomerBot'), findsOneWidget);
      expect(find.text('Owner bot enabled'), findsOneWidget);
      expect(find.text('Save customer bot'), findsNothing);
      expect(find.byType(TextField), findsNothing);
      expect(find.byType(SwitchListTile), findsNothing);
      await tester.ensureVisible(find.text('Create customer link'));
      await tester.tap(find.text('Create customer link'));
      await tester.pumpAndSettle();
      expect(
        find.text('https://t.me/OwnerCustomerBot?start=private-customer-link'),
        findsOneWidget,
      );
      expect(
        find.text('Waiting for customer to start the bot'),
        findsOneWidget,
      );
      expect(requests.where((r) => r.method == 'PUT'), isEmpty);
      awaitingPhone = true;
      await tester.ensureVisible(find.text('Refresh link and delivery status'));
      await tester.tap(find.text('Refresh link and delivery status'));
      await tester.pumpAndSettle();
      expect(
        find.text('Waiting for customer to share their phone in Telegram'),
        findsOneWidget,
      );
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Send test to Telegram'),
            )
            .onPressed,
        isNull,
      );
      expect(tester.takeException(), isNull);
    },
  );
  for (final width in [360.0, 1440.0]) {
    testWidgets('customer bot setup, link and unsubscribe at $width', (
      tester,
    ) async {
      await tester.binding.setSurfaceSize(Size(width, 1300));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      var configured = false, linked = false, pending = false;
      var testFails = false;
      var testAttempts = 0;
      var language = 'en';
      final requests = <http.Request>[];
      final api = Api(
        client: MockClient((request) async {
          requests.add(request);
          Object data;
          if (request.url.path.endsWith('/customer-telegram')) {
            if (request.method == 'PUT') {
              configured = true;
              expect(jsonDecode(request.body)['bot_token'], '123:private-test');
            }
            data = {
              'configured': configured,
              'enabled': configured,
              'username': configured ? 'TestBot' : null,
              'timezone': 'Asia/Baghdad',
            };
          } else if (request.url.path.endsWith('/link')) {
            pending = true;
            language = jsonDecode(request.body)['language'];
            data = {'url': 'https://t.me/TestBot?start=private-once'};
          } else if (request.url.path.endsWith('/test')) {
            expect(request.method, 'POST');
            testAttempts++;
            if (testFails) {
              return http.Response(
                '{"detail":"Telegram did not confirm the test."}',
                502,
              );
            }
            data = {'sent': true};
          } else if (request.url.path.endsWith('/language')) {
            language = jsonDecode(request.body)['language'];
            data = {'language': language};
          } else {
            if (request.method == 'DELETE') {
              linked = false;
              pending = false;
            }
            data = {
              'linked': linked,
              'phone_available': true,
              'phone_verified': linked,
              'pending_link': pending,
              'language': language,
              'recent': linked
                  ? [
                      {
                        'kind': 'linked',
                        'status': 'sent',
                        'created_at': '2026-11-16',
                      },
                    ]
                  : [],
            };
          }
          return http.Response(jsonEncode(data), 200);
        }),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(home: CustomerTelegram(api: api, customerId: 7)),
      );
      await tester.pumpAndSettle();
      expect(find.text('Customer not linked'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Send test to Telegram'),
            )
            .onPressed,
        isNull,
      );
      expect(testAttempts, 0);
      await tester.enterText(
        find.widgetWithText(TextField, 'Bot token'),
        '123:private-test',
      );
      await tester.ensureVisible(find.text('Save customer bot'));
      await tester.tap(find.text('Save customer bot'));
      await tester.pumpAndSettle();
      expect(find.text('123:private-test'), findsNothing);
      await tester.ensureVisible(find.text('Create customer link'));
      await tester.tap(find.text('Create customer link'));
      await tester.pumpAndSettle();
      expect(
        find.text('https://t.me/TestBot?start=private-once'),
        findsOneWidget,
      );
      expect(
        find.text('Waiting for customer to start the bot'),
        findsOneWidget,
      );
      linked = true;
      pending = false;
      await tester.ensureVisible(find.text('Refresh link and delivery status'));
      await tester.tap(find.text('Refresh link and delivery status'));
      await tester.pumpAndSettle();
      expect(find.text('Customer linked'), findsOneWidget);
      expect(find.text('linked · sent'), findsOneWidget);
      expect(
        find.text('https://t.me/TestBot?start=private-once'),
        findsNothing,
      );
      await tester.ensureVisible(find.text('Send test to Telegram'));
      await tester.tap(find.text('Send test to Telegram'));
      await tester.pumpAndSettle();
      expect(testAttempts, 1);
      expect(
        find.text(
          'Test notification sent to the customer’s Telegram from the owner bot.',
        ),
        findsOneWidget,
      );
      testFails = true;
      await tester.ensureVisible(find.text('Send test to Telegram'));
      await tester.tap(find.text('Send test to Telegram'));
      await tester.pumpAndSettle();
      expect(testAttempts, 2);
      expect(
        find.textContaining('Telegram did not confirm the test.'),
        findsOneWidget,
      );
      expect(
        find.text(
          'Test notification sent to the customer’s Telegram from the owner bot.',
        ),
        findsNothing,
      );
      await tester.ensureVisible(find.text('Unlink customer'));
      await tester.tap(find.text('Unlink customer'));
      await tester.pumpAndSettle();
      expect(find.text('Customer not linked'), findsOneWidget);
      expect(requests.where((r) => r.method == 'DELETE').length, 1);
      expect(tester.takeException(), isNull);
    });
  }
}
