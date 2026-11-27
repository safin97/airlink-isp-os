import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/payment_settings.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  for (final readOnly in [false, true]) {
    testWidgets('payment manager assignments persist; read only: $readOnly', (
      tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(1100, 1500));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final rows = [
        for (final provider in ['fib', 'fastpay'])
          <String, dynamic>{
            'provider': provider,
            'configured': true,
            'merchant_id': '$provider-account',
            'environment': 'sandbox',
            'has_secret': true,
            'access_mode': provider == 'fib' ? 'selected' : 'all',
            'manager_ids': provider == 'fib' ? ['alice'] : [],
          },
      ];
      final writes = <Map<String, dynamic>>[];
      final api =
          Api(
              client: MockClient((r) async {
                if (r.method == 'PUT') {
                  final body = Map<String, dynamic>.from(jsonDecode(r.body));
                  writes.add(body);
                  final row = rows.firstWhere(
                    (row) => r.url.path.endsWith('/${row['provider']}'),
                  );
                  row.addAll(body);
                  return http.Response(jsonEncode(row), 200);
                }
                return http.Response(
                  jsonEncode(
                    r.url.path.endsWith('/managers')
                        ? [
                            {
                              'id': 'alice',
                              'username': 'Alice',
                              'active': true,
                            },
                            {'id': 'bob', 'username': 'Bob', 'active': true},
                          ]
                        : rows,
                  ),
                  200,
                );
              }),
            )
            ..user = readOnly
                ? {
                    'role': 'manager',
                    'sections': ['payment_gateways'],
                    'editable_sections': <String>[],
                  }
                : {'role': 'owner'};
      Future<void> show() => tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: PaymentSettings(
                key: UniqueKey(),
                api: api,
                embedded: true,
              ),
            ),
          ),
        ),
      );
      await show();
      await tester.pumpAndSettle();
      final alice = find.byKey(const ValueKey('payment-manager-fib-alice'));
      final bob = find.byKey(const ValueKey('payment-manager-fib-bob'));
      expect(tester.widget<CheckboxListTile>(alice).value, isTrue);
      expect(tester.widget<CheckboxListTile>(bob).value, isFalse);
      if (readOnly) {
        expect(tester.widget<CheckboxListTile>(bob).onChanged, isNull);
        expect(
          tester
              .widget<FilledButton>(
                find.byKey(const ValueKey('save-payment-fib')),
              )
              .onPressed,
          isNull,
        );
        expect(writes, isEmpty);
      } else {
        await tester.ensureVisible(alice);
        await tester.tap(alice);
        await tester.tap(bob);
        final save = find.byKey(const ValueKey('save-payment-fib'));
        await tester.ensureVisible(save);
        await tester.tap(save);
        await tester.pumpAndSettle();
        expect(writes.single['access_mode'], 'selected');
        expect(writes.single['manager_ids'], ['bob']);
        expect(writes.single['secret'], isNull);
        expect(rows[1]['access_mode'], 'all');
        await show();
        await tester.pumpAndSettle();
        expect(tester.widget<CheckboxListTile>(bob).value, isTrue);
        expect(tester.widget<CheckboxListTile>(alice).value, isFalse);
      }
      await tester.pumpWidget(const SizedBox());
    });
  }
}
