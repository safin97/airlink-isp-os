import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/sas4_clients.dart';
import 'package:airlink_isp_os/sas4_connection.dart';

void main() {
  testWidgets(
    'dashboard, users, online users, pagination and automatic refresh',
    (tester) async {
      tester.view.physicalSize = const Size(1400, 1100);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final requests = <http.Request>[];
      bool configured = false;
      final api = Api(
        client: MockClient((request) async {
          requests.add(request);
          if (request.method == 'PUT') configured = true;
          if (request.url.path.endsWith('/dashboard')) {
            return http.Response(
              jsonEncode({
                'total_users': 120,
                'active_users': 100,
                'online_users': 80,
                'expired_users': 20,
                'about_to_expire': 7,
                'balance': '1250.50',
                'reward_points': 42,
                'warnings': [],
              }),
              200,
            );
          }
          if (request.url.path.endsWith('/clients') ||
              request.url.path.endsWith('/online')) {
            final page = int.parse(request.url.queryParameters['page']!);
            return http.Response(
              jsonEncode({
                'clients': [
                  {
                    'username': request.url.path.endsWith('/online')
                        ? 'online-$page'
                        : 'client-$page',
                    'name': 'Client $page',
                    'profile': '20 Mbps',
                    'status': 'online',
                    'ethernet_links': page == 1
                        ? [
                            {'name': 'eth0', 'speed_mbps': 1000},
                          ]
                        : [],
                    'signal_dbm': page == 1 ? -62 : null,
                  },
                ],
                'total': 2,
                'page': page,
                'last_page': 2,
                'per_page': 1,
                'fetched_at': '2026-11-02T10:00:00Z',
              }),
              200,
            );
          }
          return http.Response(
            jsonEncode({
              'configured': configured,
              'server_url': 'http://airlinkcom.online',
              'username': '',
              'has_password': false,
            }),
            200,
          );
        }),
      )..user = {'role': 'manager'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(child: Sas4Connection(api: api)),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextFormField).at(0), 'sas-reader');
      await tester.enterText(
        find.byType(TextFormField).at(1),
        'test-credential',
      );
      await tester.tap(find.text('Save SAS4 connection'));
      await tester.pumpAndSettle();
      final save = requests.singleWhere((request) => request.method == 'PUT');
      expect(jsonDecode(save.body), {
        'username': 'sas-reader',
        'password': 'test-credential',
      });
      expect(
        tester
            .widget<TextFormField>(find.byType(TextFormField).at(1))
            .controller!
            .text,
        isEmpty,
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(child: Sas4Clients(api: api)),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byType(TextFormField), findsNothing);
      expect(find.text('SAS4 connection'), findsNothing);
      for (final label in [
        'Total users',
        'Active users',
        'Online users',
        'Expired users',
        'About to expire',
        'Balance',
        'Reward points',
      ]) {
        expect(find.text(label), findsOneWidget);
      }
      for (final value in ['120', '100', '80', '20', '7', '1250.50', '42']) {
        expect(find.text(value), findsOneWidget);
      }
      final beforeDashboardRefresh = requests
          .where((r) => r.url.path.endsWith('/dashboard'))
          .length;
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();
      expect(
        requests.where((r) => r.url.path.endsWith('/dashboard')).length,
        beforeDashboardRefresh + 1,
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: Sas4Clients(
                key: const ValueKey('users'),
                api: api,
                showDashboard: false,
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('ISP Card • Users list'), findsOneWidget);
      expect(find.text('client-1'), findsOneWidget);
      expect(find.text('20 Mbps'), findsOneWidget);
      expect(find.text('Page 1 of 2'), findsOneWidget);
      await tester.tap(find.text('Next'));
      await tester.pumpAndSettle();
      expect(find.text('client-2'), findsOneWidget);
      expect(find.text('Ethernet speed'), findsNothing);
      expect(find.text('Signal'), findsNothing);
      expect(find.text('Page 2 of 2'), findsOneWidget);
      final beforeRefresh = requests
          .where((r) => r.url.path.endsWith('/clients'))
          .length;
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();
      expect(
        requests.where((r) => r.url.path.endsWith('/clients')).length,
        beforeRefresh + 1,
      );
      expect(requests.last.url.queryParameters['page'], '2');
      expect(find.text('client-2'), findsOneWidget);
      expect(find.text('Ethernet speed'), findsNothing);
      expect(find.text('Signal'), findsNothing);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: Sas4Clients(
                key: const ValueKey('online'),
                api: api,
                showDashboard: false,
                showOnline: true,
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('online-1'), findsOneWidget);
      expect(find.text('Ethernet speed'), findsOneWidget);
      expect(find.text('Signal'), findsOneWidget);
      expect(find.text('1 Gbps'), findsOneWidget);
      expect(find.text('-62 dBm'), findsOneWidget);
      expect(find.text('client-2'), findsNothing);
      await tester.enterText(find.byType(TextField), 'Ali');
      await tester.tap(find.text('Search'));
      await tester.pumpAndSettle();
      expect(requests.last.url.path, endsWith('/online'));
      expect(requests.last.url.queryParameters['search'], 'Ali');
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();
      expect(requests.last.url.path, endsWith('/online'));
      expect(requests.last.url.queryParameters['search'], 'Ali');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'background refresh preserves controls and ignores stale responses',
    (tester) async {
      tester.view.physicalSize = const Size(1400, 1100);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final pending = <Completer<http.Response>>[];
      int calls = 0;
      http.Response users(String name, String timestamp) => http.Response(
        jsonEncode({
          'clients': [
            {'username': name, 'profile': '20 Mbps'},
          ],
          'total': 1,
          'page': 1,
          'last_page': 1,
          'fetched_at': timestamp,
        }),
        200,
      );
      final api = Api(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/sas4')) {
            return http.Response('{"configured":true}', 200);
          }
          calls++;
          if (calls == 1) return users('original', '2026-11-02T10:00:00Z');
          if (request.url.queryParameters['search'] == 'Ali') {
            return users('Ali', '2026-11-02T10:02:00Z');
          }
          final response = Completer<http.Response>();
          pending.add(response);
          return response.future;
        }),
      )..user = {'role': 'manager'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: Sas4Clients(api: api, showDashboard: false),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final initialRow = tester.widget(find.text('original'));
      await tester.enterText(find.byType(TextField), 'draft');
      final editable = tester.state<EditableTextState>(
        find.descendant(
          of: find.byType(TextField),
          matching: find.byType(EditableText),
        ),
      );
      await tester.pump(const Duration(seconds: 5));
      expect(find.byType(LinearProgressIndicator), findsNothing);
      expect(tester.widget<TextField>(find.byType(TextField)).enabled, isTrue);
      expect(editable.widget.focusNode.hasFocus, isTrue);
      expect(find.text('original'), findsOneWidget);
      pending.removeAt(0).complete(users('original', '2026-11-02T10:01:00Z'));
      await tester.pumpAndSettle();
      expect(
        identical(tester.widget(find.text('original')), initialRow),
        isTrue,
      );
      expect(
        tester.widget<TextField>(find.byType(TextField)).controller!.text,
        'draft',
      );
      await tester.pump(const Duration(seconds: 5));
      pending.removeAt(0).complete(users('changed', '2026-11-02T10:01:30Z'));
      await tester.pumpAndSettle();
      expect(find.text('changed'), findsOneWidget);
      expect(editable.widget.focusNode.hasFocus, isTrue);
      await tester.pump(const Duration(seconds: 5));
      await tester.enterText(find.byType(TextField), 'Ali');
      await tester.tap(find.text('Search'));
      await tester.pumpAndSettle();
      expect(find.text('Ali'), findsWidgets);
      pending.removeAt(0).complete(users('stale', '2026-11-02T10:01:45Z'));
      await tester.pumpAndSettle();
      expect(find.text('stale'), findsNothing);
      expect(find.text('Ali'), findsWidgets);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('technician cannot fetch SAS4 credentials or client data', (
    tester,
  ) async {
    final api = Api(
      client: MockClient((request) async {
        fail('Unexpected SAS4 request for a technician');
      }),
    )..user = {'role': 'technician'};
    await tester.pumpWidget(MaterialApp(home: Sas4Clients(api: api)));
    await tester.pumpAndSettle();
    expect(
      find.text('Manager access is required to connect and view SAS4 clients.'),
      findsOneWidget,
    );
  });
}
