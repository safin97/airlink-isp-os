import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/deye_solar.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const config = {
  'configured': true,
  'region': 'eu',
  'login_type': 'email',
  'account': 'solar@example.invalid',
  'app_id': 'my-app',
};

Widget screen(Api api) => MaterialApp(
  home: Scaffold(
    body: SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: DeyeSolar(api: api),
    ),
  ),
);

http.Response response(Object value) => http.Response(jsonEncode(value), 200);

void main() {
  for (final width in [360.0, 800.0, 1440.0]) {
    testWidgets(
      'energy overview at width $width preserves missing and zero values',
      (tester) async {
        await tester.binding.setSurfaceSize(Size(width, 1000));
        addTearDown(() => tester.binding.setSurfaceSize(null));
        var latestCalls = 0;
        final api = Api(
          client: MockClient((request) async {
            if (request.url.path.endsWith('/latest')) {
              latestCalls++;
              return response({
                'solar_w': 4200,
                'load_w': 0,
                'battery_soc': 76,
                'battery_w': null,
                'grid_w': null,
                'freshness': 'stale',
                'observed_at': '2026-11-15T08:00:00+00:00',
              });
            }
            if (request.url.path.endsWith('/stations')) {
              return response({
                'stations': [
                  {'id': '123', 'name': 'North solar'},
                ],
                'total': 1,
              });
            }
            return response(config);
          }),
        )..user = {'role': 'owner'};
        await tester.pumpWidget(screen(api));
        await tester.pumpAndSettle();
        expect(find.text('4.20 kW'), findsOneWidget);
        expect(find.text('0 W'), findsOneWidget);
        expect(find.text('76%'), findsOneWidget);
        expect(find.text('Unavailable'), findsOneWidget);
        expect(find.textContaining('Stale cloud reading'), findsOneWidget);
        expect(latestCalls, 1);
        expect(tester.takeException(), isNull);
        await tester.pump(const Duration(seconds: 4));
        expect(latestCalls, 1);
        await tester.pump(const Duration(seconds: 1));
        await tester.pumpAndSettle();
        expect(latestCalls, 2);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }

  testWidgets('account form connects and clears secret fields', (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final writes = <Map<String, dynamic>>[];
    final api = Api(
      client: MockClient((request) async {
        if (request.method == 'PUT') {
          writes.add(jsonDecode(request.body));
          return response(config);
        }
        if (request.url.path.endsWith('/stations')) {
          return response({'stations': [], 'total': 0});
        }
        return response({'configured': false});
      }),
    )..user = {'role': 'owner'};
    await tester.pumpWidget(screen(api));
    await tester.pumpAndSettle();
    final fields = find.byType(TextField);
    await tester.enterText(fields.at(0), 'solar@example.invalid');
    await tester.enterText(fields.at(1), 'account-secret');
    await tester.enterText(fields.at(2), 'my-app');
    await tester.enterText(fields.at(3), 'app-secret');
    expect(tester.widget<TextField>(fields.at(1)).obscureText, isTrue);
    expect(tester.widget<TextField>(fields.at(3)).obscureText, isTrue);
    await tester.ensureVisible(find.text('Connect Deye Cloud'));
    await tester.tap(find.text('Connect Deye Cloud'));
    await tester.pumpAndSettle();
    expect(writes.single, {
      'region': 'eu',
      'login_type': 'email',
      'account': 'solar@example.invalid',
      'country_code': '',
      'app_id': 'my-app',
      'company_id': null,
      'password': 'account-secret',
      'app_secret': 'app-secret',
    });
    await tester.ensureVisible(find.text('Connection'));
    await tester.tap(find.text('Connection'));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(fields.at(1)).controller!.text, isEmpty);
    expect(tester.widget<TextField>(fields.at(3)).controller!.text, isEmpty);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
    'read-only accounts cannot change a connection and errors clear readings',
    (tester) async {
      var fail = false;
      final api =
          Api(
              client: MockClient((request) async {
                expect(request.method, 'GET');
                if (request.url.path.endsWith('/latest')) {
                  return fail
                      ? http.Response(
                          '{"detail":"Deye Cloud is unavailable"}',
                          502,
                        )
                      : response({'solar_w': 1234, 'freshness': 'recent'});
                }
                if (request.url.path.endsWith('/stations')) {
                  return response({
                    'stations': [
                      {'id': '123', 'name': 'Solar'},
                    ],
                    'total': 1,
                  });
                }
                return response(config);
              }),
            )
            ..user = {
              'role': 'manager',
              'sections': ['deye'],
              'editable_sections': [],
              'deletable_sections': [],
            };
      await tester.pumpWidget(screen(api));
      await tester.pumpAndSettle();
      expect(find.text('Connection'), findsNothing);
      expect(find.byTooltip('Disconnect Deye Cloud'), findsNothing);
      expect(find.text('1.23 kW'), findsOneWidget);
      fail = true;
      await tester.tap(find.byTooltip('Refresh energy readings'));
      await tester.pumpAndSettle();
      expect(find.text('1.23 kW'), findsNothing);
      expect(find.textContaining('Deye Cloud is unavailable'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
