import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/vpn_settings.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  Future<void> show(WidgetTester tester, Api api) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(child: VpnSettings(api: api)),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('non-owner does not load or display VPN settings', (
    tester,
  ) async {
    final api = Api(
      client: MockClient(
        (request) async => throw StateError('Must not request VPN'),
      ),
    )..user = {'role': 'manager'};
    await show(tester, api);
    expect(find.text('L2TP/IPsec VPN'), findsNothing);
  });

  testWidgets('preview explains unavailable VPN and disables connection', (
    tester,
  ) async {
    final api = Api(
      client: MockClient(
        (request) async => http.Response(
          jsonEncode({
            'supported': false,
            'configured': false,
            'status': 'unavailable',
            'reason': 'VPN runs on the installed AirLink Linux PC.',
          }),
          200,
        ),
      ),
    )..user = {'role': 'owner'};
    await show(tester, api);
    expect(find.textContaining('installed AirLink Linux PC'), findsOneWidget);
    expect(
      tester
          .widget<FilledButton>(find.widgetWithText(FilledButton, 'Save VPN'))
          .onPressed,
      isNull,
    );
    expect(
      tester
          .widget<OutlinedButton>(
            find.widgetWithText(OutlinedButton, 'Connect'),
          )
          .onPressed,
      isNull,
    );
  });

  testWidgets(
    'silent status preserves edits and sends credentials only on save',
    (tester) async {
      final posts = <http.Request>[];
      var state = <String, dynamic>{
        'supported': true,
        'configured': true,
        'status': 'disconnected',
        'server': 'vpn.example.com',
        'username': 'old-user',
        'has_password': true,
        'has_psk': true,
        'routes': <String>[],
      };
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'POST') {
            posts.add(request);
            if (request.url.path.endsWith('/save')) {
              final body = jsonDecode(request.body);
              state = {
                ...state,
                'server': body['server'],
                'username': body['username'],
                'routes': body['routes'],
              };
            } else if (request.url.path.endsWith('/connect')) {
              state = {...state, 'status': 'connecting'};
            } else if (request.url.path.endsWith('/disconnect')) {
              state = {...state, 'status': 'disconnected'};
            }
          }
          return http.Response(jsonEncode(state), 200);
        }),
      )..user = {'role': 'owner'};
      await show(tester, api);
      final fields = find.byType(TextField);
      expect(tester.widget<TextField>(fields.at(2)).obscureText, isTrue);
      expect(tester.widget<TextField>(fields.at(3)).obscureText, isTrue);
      await tester.enterText(fields.at(1), 'new-user');
      await tester.enterText(fields.at(2), 'new-password');
      await tester.enterText(fields.at(4), '192.168.88.0/24\n10.2.0.0/16');
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();
      expect(
        tester.widget<TextField>(fields.at(1)).controller!.text,
        'new-user',
      );
      expect(
        tester.widget<TextField>(fields.at(2)).controller!.text,
        'new-password',
      );
      expect(posts, isEmpty);
      expect(
        tester
            .widget<OutlinedButton>(
              find.widgetWithText(OutlinedButton, 'Connect'),
            )
            .onPressed,
        isNull,
      );
      await tester.ensureVisible(find.text('Save VPN'));
      await tester.tap(find.text('Save VPN'));
      await tester.pumpAndSettle();
      expect(jsonDecode(posts.single.body), {
        'server': 'vpn.example.com',
        'username': 'new-user',
        'password': 'new-password',
        'psk': '',
        'routes': ['192.168.88.0/24', '10.2.0.0/16'],
      });
      expect(tester.widget<TextField>(fields.at(2)).controller!.text, isEmpty);
      await tester.ensureVisible(find.text('Connect'));
      await tester.tap(find.text('Connect'));
      await tester.pumpAndSettle();
      expect(posts.last.url.path, '/api/vpn/connect');
      expect(jsonDecode(posts.last.body), isEmpty);
      expect(find.text('VPN status: Connecting…'), findsOneWidget);
      state = {
        ...state,
        'status': 'connected',
        'addresses': ['10.10.0.2'],
      };
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();
      expect(find.text('VPN status: Connected'), findsOneWidget);
      expect(find.text('VPN address: 10.10.0.2'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, 'Save VPN'))
            .onPressed,
        isNull,
      );
      await tester.ensureVisible(find.text('Disconnect'));
      await tester.tap(find.text('Disconnect'));
      await tester.pumpAndSettle();
      expect(posts.last.url.path, '/api/vpn/disconnect');
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('failed action never claims a connection', (tester) async {
    final api = Api(
      client: MockClient(
        (request) async => request.method == 'POST'
            ? http.Response(jsonEncode({'detail': 'VPN operation failed'}), 409)
            : http.Response(
                jsonEncode({
                  'supported': true,
                  'configured': true,
                  'status': 'disconnected',
                  'server': 'vpn.example.com',
                  'username': 'user',
                }),
                200,
              ),
      ),
    )..user = {'role': 'owner'};
    await show(tester, api);
    await tester.ensureVisible(find.text('Connect'));
    await tester.tap(find.text('Connect'));
    await tester.pumpAndSettle();
    expect(find.text('VPN operation failed'), findsOneWidget);
    expect(find.text('VPN status: Connected'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });
}
