import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/telegram_account.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  Future<void> mount(WidgetTester tester, Widget child) async {
    await tester.binding.setSurfaceSize(const Size(900, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: SingleChildScrollView(child: child)),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets(
    'Saved cooldown survives reopening and expires without automatic verification',
    (tester) async {
      var requests = 0;
      final api = Api(
        client: MockClient((request) async {
          requests++;
          expect(request.method, 'GET');
          return http.Response('{"stage":"code","retry_after_seconds":3}', 200);
        }),
      )..user = {'role': 'owner'};
      await mount(tester, TelegramAccountSettings(api: api));
      expect(find.textContaining('Try again in 0h 0m 3s'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Verify code'),
            )
            .onPressed,
        isNull,
      );
      expect(
        tester
            .widget<TextButton>(find.widgetWithText(TextButton, 'Cancel login'))
            .onPressed,
        isNull,
      );
      await tester.pump(const Duration(seconds: 3));
      expect(
        find.text('The cooldown has ended. You can try again now.'),
        findsOneWidget,
      );
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Verify code'),
            )
            .onPressed,
        isNotNull,
      );
      expect(requests, 1);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'Login flood response uses Retry-After and blocks repeated code requests',
    (tester) async {
      var posts = 0;
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'GET') {
            return http.Response('{"stage":"disconnected"}', 200);
          }
          posts++;
          return http.Response(
            '{"detail":"Telegram requested a cooldown."}',
            429,
            headers: {'retry-after': '120'},
          );
        }),
      )..user = {'role': 'owner'};
      await mount(tester, TelegramAccountSettings(api: api));
      await tester.tap(find.text('Send login code'));
      await tester.pumpAndSettle();
      expect(posts, 1);
      expect(find.textContaining('Try again in 0h 2m 0s'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Send login code'),
            )
            .onPressed,
        isNull,
      );
      await tester.pump(const Duration(seconds: 120));
      expect(posts, 1);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Send login code'),
            )
            .onPressed,
        isNotNull,
      );
      await tester.pumpWidget(const SizedBox());
    },
  );

  for (final persisted in [true, false]) {
    testWidgets(
      'Phone lookup respects cooldown persisted=$persisted without retries',
      (tester) async {
        var lookups = 0;
        final api = Api(
          client: MockClient((request) async {
            if (request.url.path.endsWith('/lookup')) {
              lookups++;
              return http.Response(
                '{"detail":"Please wait."}',
                429,
                headers: {'retry-after': '3'},
              );
            }
            return http.Response(
              jsonEncode({
                'stage': 'connected',
                if (persisted) 'retry_after_seconds': 3,
              }),
              200,
            );
          }),
        )..user = {'role': 'owner'};
        await mount(tester, TelegramPhoneLookup(api: api, customerId: 7));
        expect(lookups, persisted ? 0 : 1);
        expect(find.textContaining('Try again in 0h 0m 3s'), findsOneWidget);
        expect(
          tester
              .widget<OutlinedButton>(
                find.widgetWithText(OutlinedButton, 'Check saved phone'),
              )
              .onPressed,
          isNull,
        );
        await tester.pump(const Duration(seconds: 3));
        expect(lookups, persisted ? 0 : 1);
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

  test('Malformed Retry-After preserves the normal API error', () async {
    final api = Api(
      client: MockClient(
        (_) async => http.Response(
          '{"detail":"Please wait."}',
          429,
          headers: {'retry-after': 'invalid'},
        ),
      ),
    );
    await expectLater(
      api.request('/example'),
      throwsA(
        isA<ApiException>()
            .having((e) => e.retryAfterSeconds, 'retry interval', isNull)
            .having((e) => e.message, 'message', 'Please wait.'),
      ),
    );
  });
}
