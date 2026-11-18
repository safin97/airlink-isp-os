import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/telegram_account.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  Future<void> mount(WidgetTester tester, Api api) async {
    await tester.binding.setSurfaceSize(const Size(900, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    api.user = {'role': 'owner'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: TelegramPhoneLookup(api: api, customerId: 7),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets(
    'A successful explicit click enables another test without lookup or fixed delay',
    (tester) async {
      var lookups = 0, sends = 0;
      final api = Api(
        client: MockClient((request) async {
          Object result = {
            'stage': 'connected',
            'profile': {'username': 'Owner'},
          };
          if (request.url.path.endsWith('/lookup')) {
            lookups++;
            result = {
              'status': 'found',
              'profile': {'id': '123', 'first_name': 'Customer'},
              'test_token': 'intent-1',
            };
          }
          if (request.url.path.endsWith('/test')) {
            sends++;
            expect(jsonDecode(request.body)['test_token'], 'intent-$sends');
            result = {'sent': true, 'next_test_token': 'intent-${sends + 1}'};
          }
          return http.Response(jsonEncode(result), 200);
        }),
      );
      await mount(tester, api);
      final button = find.widgetWithText(
        FilledButton,
        'Send test from connected account',
      );
      expect(sends, 0);
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(sends, 1);
      expect(tester.widget<FilledButton>(button).onPressed, isNotNull);
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(sends, 2);
      expect(lookups, 1);
      await tester.pump(const Duration(minutes: 1));
      expect(sends, 2);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'Unknown phone can select a public username and review before sending',
    (tester) async {
      var selections = 0, sends = 0;
      final api = Api(
        client: MockClient((request) async {
          Object result = {'stage': 'connected'};
          if (request.url.path.endsWith('/lookup')) {
            result = {'status': 'unknown'};
          }
          if (request.url.path.endsWith('/recipient')) {
            selections++;
            expect(jsonDecode(request.body), {'username': '@customer'});
            result = {
              'status': 'found',
              'matched_by': 'username',
              'profile': {
                'id': '123',
                'first_name': 'Selected Customer',
                'username': 'customer',
              },
              'test_token': 'selected-intent',
            };
          }
          if (request.url.path.endsWith('/test')) {
            sends++;
            expect(jsonDecode(request.body)['test_token'], 'selected-intent');
            result = {'sent': true, 'next_test_token': 'next-intent'};
          }
          return http.Response(jsonEncode(result), 200);
        }),
      );
      await mount(tester, api);
      final button = find.widgetWithText(
        FilledButton,
        'Send test from connected account',
      );
      expect(tester.widget<FilledButton>(button).onPressed, isNull);
      await tester.enterText(
        find.widgetWithText(
          TextField,
          'Customer Telegram @username (optional)',
        ),
        '@customer',
      );
      await tester.pump();
      await tester.tap(find.text('Find by username'));
      await tester.pumpAndSettle();
      expect(selections, 1);
      expect(sends, 0);
      expect(find.text('Telegram ID: 123'), findsOneWidget);
      expect(find.textContaining('Selected by username'), findsOneWidget);
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(sends, 1);
      await tester.enterText(
        find.widgetWithText(
          TextField,
          'Customer Telegram @username (optional)',
        ),
        '@different',
      );
      await tester.pump();
      expect(tester.widget<FilledButton>(button).onPressed, isNull);
      expect(find.text('Telegram ID: 123'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'Telegram send cooldown blocks repeats and never resends automatically',
    (tester) async {
      var sends = 0;
      final api = Api(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/test')) {
            sends++;
            return http.Response(
              '{"detail":"Telegram requested a cooldown."}',
              429,
              headers: {'retry-after': '3'},
            );
          }
          return http.Response(
            jsonEncode(
              request.url.path.endsWith('/lookup')
                  ? {
                      'status': 'found',
                      'profile': {'id': '123'},
                      'test_token': 'intent',
                    }
                  : {'stage': 'connected'},
            ),
            200,
          );
        }),
      );
      await mount(tester, api);
      final button = find.widgetWithText(
        FilledButton,
        'Send test from connected account',
      );
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(find.textContaining('Try again in 0h 0m 3s'), findsOneWidget);
      expect(tester.widget<FilledButton>(button).onPressed, isNull);
      await tester.pump(const Duration(seconds: 4));
      expect(sends, 1);
      expect(tester.widget<FilledButton>(button).onPressed, isNull);
      expect(
        tester
            .widget<OutlinedButton>(
              find.widgetWithText(OutlinedButton, 'Check saved phone'),
            )
            .onPressed,
        isNotNull,
      );
      await tester.pumpWidget(const SizedBox());
    },
  );
}
