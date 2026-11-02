import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';

void main() {
  testWidgets(
    'ISP Card reports load, paginate and switch statistics and transfers',
    (tester) async {
      tester.view.physicalSize = const Size(1500, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final requests = <Uri>[];
      var fail = false;
      final api = Api(
        client: MockClient((r) async {
          requests.add(r.url);
          final path = r.url.path;
          if (path == '/api/integrations/sas4/reports') {
            return http.Response(
              jsonEncode([
                {'id': 'activations', 'name': 'Activations'},
                {
                  'id': 'activation-statistics',
                  'name': 'Activation statistics',
                },
                {'id': 'money-transfers', 'name': 'Money Transfers'},
              ]),
              200,
            );
          }
          if (path.endsWith('/reports/managers')) {
            return http.Response(
              '[{"id":7,"username":"regional-manager"},{"id":8,"username":"branch-manager"}]',
              200,
            );
          }
          if (path.contains('/reports/')) {
            if (fail) {
              return http.Response(
                jsonEncode({'detail': 'SAS4 permission denied'}),
                502,
              );
            }
            return http.Response(
              jsonEncode({
                'columns': [
                  {'key': 'name', 'label': 'Username'},
                ],
                'rows': [
                  {'name': 'record-${r.url.queryParameters['page']}'},
                ],
                'total': 26,
                'page': int.parse(r.url.queryParameters['page']!),
                'last_page': 2,
              }),
              200,
            );
          }
          if (path == '/api/integrations/sas4') {
            return http.Response('{"configured":false}', 200);
          }
          return http.Response(path == '/api/dashboard' ? '{}' : '[]', 200);
        }),
      )..user = {'username': 'owner', 'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(ListTile, 'ISP Card'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('isp-card-reports')));
      await tester.pumpAndSettle();
      expect(find.text('SAS4 Reports'), findsOneWidget);
      expect(find.text('record-1'), findsOneWidget);
      Future<void> choose(String text, {bool last = false}) async {
        final fields = find.byType(DropdownButtonFormField<String>);
        await tester.tap(last ? fields.last : fields.first);
        await tester.pumpAndSettle();
        await tester.tap(find.text(text).last);
        await tester.pumpAndSettle();
      }

      expect(requests.last.path, endsWith('/activation-statistics'));
      expect(requests.last.queryParameters['period'], 'monthly');
      await choose('Activations');
      await tester.enterText(
        find.byKey(const ValueKey('sas4-report-search')),
        'alice',
      );
      expect(find.text('Apply'), findsNothing);
      await tester.pump(const Duration(milliseconds: 450));
      await tester.pumpAndSettle();
      expect(requests.last.queryParameters['search'], 'alice');
      final managerField = find.byKey(const ValueKey('sas4-report-manager'));
      final beforeSearch = requests.length;
      await tester.enterText(managerField, 'g');
      await tester.pumpAndSettle();
      expect(find.text('regional-manager'), findsNothing);
      await tester.enterText(managerField, 'GI');
      await tester.pumpAndSettle();
      expect(find.text('regional-manager'), findsOneWidget);
      expect(find.text('branch-manager'), findsNothing);
      expect(requests.length, beforeSearch);

      await tester.tap(find.text('regional-manager').last);
      await tester.pumpAndSettle();
      expect(requests.last.queryParameters['manager_id'], '7');
      await tester.tap(find.byTooltip('Next page'));
      await tester.pumpAndSettle();
      expect(find.text('record-2'), findsOneWidget);
      expect(requests.last.queryParameters['search'], 'alice');
      await choose('Activation statistics');
      expect(requests.last.path, endsWith('/activation-statistics'));
      expect(requests.last.queryParameters['period'], 'monthly');
      await choose('Daily', last: true);
      expect(requests.last.queryParameters['period'], 'daily');
      expect(requests.last.queryParameters['manager_id'], '7');
      expect(find.byKey(const ValueKey('sas4-report-search')), findsNothing);
      await choose('Monthly', last: true);
      expect(requests.last.queryParameters['period'], 'monthly');
      final monthField = find.byType(DropdownButtonFormField<int>).first;
      expect(
        tester.getTopLeft(monthField).dx,
        lessThan(
          tester
              .getTopLeft(find.byType(DropdownButtonFormField<String>).last)
              .dx,
        ),
      );
      await tester.tap(monthField);
      await tester.pumpAndSettle();
      await tester.tap(find.text('2').last);
      await tester.pumpAndSettle();
      expect(requests.last.queryParameters['month'], '2');
      expect(requests.last.queryParameters['page'], '1');

      await choose('Money Transfers');
      expect(requests.last.queryParameters['operation'], 'deposit');
      await choose('Withdrawal', last: true);
      expect(requests.last.queryParameters['operation'], 'withdrawal');
      expect(requests.last.queryParameters['manager_id'], '7');
      fail = true;
      await choose('Deposit', last: true);
      expect(find.text('SAS4 permission denied'), findsOneWidget);
      expect(find.text('No records found for these filters.'), findsNothing);
      fail = false;
      await tester.tap(find.byTooltip('All managers'));
      await tester.pumpAndSettle();
      expect(requests.last.queryParameters['manager_id'], '-1');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
