import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/card_system.dart';

void main() {
  testWidgets('Card System reads Radius, confirms changes and protects PINs', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1400, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final requests = <http.Request>[];
    var suspended = false;
    var fail = false;
    final api = Api(
      client: MockClient((request) async {
        requests.add(request);
        final path = request.url.path;
        Object data;
        if (path.endsWith('/managers')) {
          data = [
            {'id': 7, 'username': 'branch'},
          ];
        } else if (path.endsWith('/action')) {
          if (fail) {
            return http.Response(
              '{"detail":"Change was not confirmed. Refresh before trying again."}',
              502,
            );
          }
          suspended = true;
          data = {'ok': true};
        } else if (path.endsWith('/radius/cards')) {
          final reveal = request.url.queryParameters['reveal'] == 'true';
          data = {
            'columns': [
              {'key': 'serialnumber', 'label': 'Serial number'},
              if (reveal) {'key': 'pin', 'label': 'PIN'},
            ],
            'rows': [
              {'serialnumber': 'CARD-1', if (reveal) 'pin': 'SECRET-PIN'},
            ],
            'page': 1,
            'last_page': 1,
            'total': 1,
          };
        } else if (path.endsWith('/radius')) {
          data = {
            'columns': [
              {'key': 'series', 'label': 'Series'},
              {'key': 'suspended', 'label': 'Suspended'},
            ],
            'rows': [
              {'series': 'SERIES-1', 'suspended': suspended ? 1 : 0},
            ],
            'page': int.parse(request.url.queryParameters['page']!),
            'last_page': 2,
            'total': 26,
            'actions': {
              'cards': true,
              'suspend': true,
              'release': true,
              'delete': false,
              'owner': true,
            },
          };
        } else if (path.endsWith('/profiles')) {
          data = [];
        } else {
          data = {'items': [], 'total': 0};
        }
        return http.Response(jsonEncode(data), 200);
      }),
    )..user = {'role': 'owner'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(child: CardSystem(api: api)),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('SAS4 Radius cards'), findsOneWidget);
    expect(find.text('SERIES-1'), findsOneWidget);
    expect(find.byKey(const ValueKey('saved-card-pin')), findsNothing);
    await tester.enterText(
      find.byKey(const ValueKey('radius-card-search')),
      'SERIES',
    );
    await tester.pump(const Duration(milliseconds: 450));
    await tester.pumpAndSettle();
    expect(requests.last.url.queryParameters['search'], 'SERIES');
    await tester.tap(find.text('Next'));
    await tester.pumpAndSettle();
    expect(requests.last.url.queryParameters['page'], '2');
    await tester.tap(find.byTooltip('Manage series'));
    await tester.pumpAndSettle();
    expect(find.text('Delete series'), findsNothing);
    await tester.tap(find.text('Suspend series'));
    await tester.pumpAndSettle();
    expect(requests.where((r) => r.method == 'POST'), isEmpty);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(requests.where((r) => r.method == 'POST'), isEmpty);
    await tester.tap(find.byTooltip('Manage series'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Suspend series'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm'));
    await tester.pumpAndSettle();
    expect(jsonDecode(requests.singleWhere((r) => r.method == 'POST').body), {
      'series': 'SERIES-1',
      'action': 'suspend',
    });
    expect(find.text('Yes'), findsOneWidget);
    await tester.tap(find.text('SERIES-1'));
    await tester.pumpAndSettle();
    expect(find.text('CARD-1'), findsOneWidget);
    expect(find.text('SECRET-PIN'), findsNothing);
    await tester.tap(find.text('Show PINs'));
    await tester.pumpAndSettle();
    expect(find.text('SECRET-PIN'), findsOneWidget);
    await tester.tap(find.text('Hide PINs'));
    await tester.pumpAndSettle();
    expect(find.text('SECRET-PIN'), findsNothing);
    await tester.tap(find.text('All series'));
    await tester.pumpAndSettle();
    fail = true;
    await tester.tap(find.byTooltip('Manage series'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Release series'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Change was not confirmed'), findsOneWidget);
    expect(requests.where((r) => r.method == 'POST').length, 2);
    await tester.tap(find.text('Saved FIB PINs').first);
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('saved-card-pin')), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
