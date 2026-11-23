import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/ttlock.dart';
import 'package:airlink_isp_os/ttlock_records.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  for (final width in [390.0, 820.0, 1440.0]) {
    for (final mode in [Brightness.light, Brightness.dark]) {
      testWidgets('dashboard $width $mode and unsupported controls', (
        tester,
      ) async {
        await tester.binding.setSurfaceSize(Size(width, 1000));
        addTearDown(() => tester.binding.setSurfaceSize(null));
        final writes = <http.Request>[];
        final api = Api(
          client: MockClient((r) async {
            if (r.method != 'GET') writes.add(r);
            if (r.url.path.endsWith('/locks')) {
              return http.Response(
                jsonEncode({
                  'items': [
                    {
                      'id': 42,
                      'name': 'shqa2',
                      'battery': 12,
                      'has_gateway': false,
                      'group': 'Office',
                    },
                    {
                      'id': 43,
                      'name': 'shqa3',
                      'battery': null,
                      'has_gateway': true,
                      'group': '',
                    },
                  ],
                  'page': 1,
                  'pages': 1,
                  'total': 2,
                  'observed_at': '2026-11-23T10:00:00Z',
                }),
                200,
              );
            }
            if (r.url.path.endsWith('/pending')) {
              return http.Response('{"items":[]}', 200);
            }
            if (r.url.path.contains('/credentials/')) {
              return http.Response('{"items":[],"pages":0,"total":0}', 200);
            }
            return http.Response(
              '{"configured":true,"username":"owner","region":"eu","client_id":"app"}',
              200,
            );
          }),
        );
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: mode),
            home: Scaffold(body: TTLockPage(api: api)),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('Total Smart Locks'), findsOneWidget);
        expect(find.text('Online Locks'), findsOneWidget);
        expect(
          find.textContaining('2 locks on this page have not been checked'),
          findsOneWidget,
        );
        final search = find.byType(TextField);
        await tester.ensureVisible(search);
        await tester.enterText(search, '42');
        await tester.pumpAndSettle();
        expect(find.text('shqa2'), findsOneWidget);
        expect(find.text('shqa3'), findsNothing);
        await tester.ensureVisible(find.text('Unlock'));
        await tester.pumpAndSettle();
        expect(
          tester
              .widget<FilledButton>(find.widgetWithText(FilledButton, 'Unlock'))
              .onPressed,
          isNull,
        );
        expect(find.text('State Unknown'), findsOneWidget);
        expect(writes, isEmpty);
        await tester.ensureVisible(find.text('eKeys'));
        await tester.tap(find.text('eKeys'));
        await tester.pumpAndSettle();
        expect(find.text('eKey management is not connected'), findsOneWidget);
        expect(
          tester
              .widget<OutlinedButton>(
                find.widgetWithText(OutlinedButton, 'Send eKey'),
              )
              .onPressed,
          isNull,
        );
        expect(writes, isEmpty);
        expect(tester.takeException(), isNull);
        for (final label in [
          'Overview',
          'Passcodes',
          'Cards',
          'Fingerprints',
          'Records',
          'Settings',
        ]) {
          final chip = find.widgetWithText(ChoiceChip, label);
          await tester.ensureVisible(chip);
          await tester.pumpAndSettle();
          await tester.tap(chip);
          await tester.pumpAndSettle();
          expect(tester.widget<ChoiceChip>(chip).selected, isTrue);
          expect(tester.takeException(), isNull, reason: label);
        }
        await tester.pageBack();
        await tester.pumpAndSettle();
        final gateways = find.text('Gateway Management');
        await tester.ensureVisible(gateways);
        await tester.pumpAndSettle();
        await tester.tap(gateways);
        await tester.pumpAndSettle();
        expect(find.text('Gateway visibility'), findsOneWidget);
        expect(
          tester
              .widget<OutlinedButton>(
                find.widgetWithText(OutlinedButton, 'Add gateway'),
              )
              .onPressed,
          isNull,
        );
        expect(writes, isEmpty);
        expect(tester.takeException(), isNull);
      });
    }
  }
  test('record parser refuses fabricated rows', () {
    expect(
      ttParseRecords('[{"recordType":7,"userName":"A"}]').single['recordType'],
      7,
    );
    expect(ttParseRecords({'list': []}), isEmpty);
    expect(() => ttParseRecords('{"unexpected":true}'), throwsFormatException);
  });
  testWidgets('records timeline paginates actual rows', (tester) async {
    final records = List.generate(
      22,
      (i) => {
        'userName': 'Person $i',
        'recordType': 7,
        'operateDate': 1795430000000,
        'success': i == 0
            ? true
            : i == 1
            ? false
            : null,
      },
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: TTRecords(records: records, lockName: 'shqa2'),
          ),
        ),
      ),
    );
    expect(find.text('Person 0'), findsOneWidget);
    expect(find.text('Person 21'), findsNothing);
    await tester.ensureVisible(find.text('Next records'));
    await tester.tap(find.text('Next records'));
    await tester.pumpAndSettle();
    expect(find.text('Person 21'), findsOneWidget);
    expect(find.text('Person 0'), findsNothing);
    expect(find.textContaining('Method code 7'), findsNWidgets(2));
    expect(tester.takeException(), isNull);
  });
}
