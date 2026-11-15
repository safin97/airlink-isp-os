import 'dart:async';
import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/deye_solar.dart';
import 'package:airlink_isp_os/deye_energy_overview.dart';
import 'package:airlink_isp_os/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'live_socket_fixture.dart';

Object cloudResponse(String path) {
  if (path.endsWith('/latest')) {
    return {
      'solar_w': 4200,
      'load_w': 1800,
      'battery_soc': 76,
      'grid_w': 400,
      'battery_w': 2000,
      'freshness': 'recent',
      'observed_at': '2026-11-15T10:00:00Z',
    };
  }
  if (path.endsWith('/stations')) {
    return {
      'stations': [
        {'id': '123', 'name': 'North solar'},
      ],
      'total': 1,
    };
  }
  return {
    'configured': true,
    'region': 'eu',
    'login_type': 'email',
    'account': 'solar@example.invalid',
    'app_id': 'test-app',
  };
}

void main() {
  testWidgets(
    'live solar frames update readings and recover without extra HTTP calls',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(1440, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final socket = FakeSocket();
      var requests = 0;
      Completer<http.Response>? pendingReading;
      String? pinnedStation;
      final api =
          Api(
              client: MockClient((request) async {
                requests++;
                if (pendingReading != null &&
                    request.url.path.endsWith('/latest')) {
                  return pendingReading.future;
                }
                final response = Map<String, dynamic>.from(
                  cloudResponse(request.url.path) as Map,
                );
                if (request.url.path.endsWith('/deye') &&
                    pinnedStation != null) {
                  response['dashboard_station'] = {
                    'id': pinnedStation,
                    'name': 'Live solar',
                  };
                }
                return http.Response(jsonEncode(response), 200);
              }),
              liveConnector: (_, _) => socket,
            )
            ..token = 'test-token'
            ..user = {'role': 'owner', 'id': 'test-owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: DeyeSolar(api: api, dashboard: true),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      api.startLive();
      final initial = requests;
      void push(
        Map<String, dynamic> readings, {
        String station = '123',
        String? failure,
      }) {
        socket.controller.add({
          'type': 'patch',
          'deye': {
            'configured': true,
            'dashboard_station': {'id': station, 'name': 'Live solar'},
            'readings': readings,
            'monitor_error': failure,
          },
        });
      }

      Map<String, dynamic> power(double watts) => {
        'solar_w': watts,
        'freshness': 'recent',
        'observed_at': '2026-11-15T10:01:00Z',
        'fetched_at': '2026-11-15T10:01:01Z',
      };
      push({'123': power(5500)});
      await tester.pumpAndSettle();
      expect(find.text('5.50 kW'), findsOneWidget);
      expect(requests, initial);
      push({
        '123': {'error': 'Cloud unavailable'},
      }, failure: 'Cloud unavailable');
      await tester.pumpAndSettle();
      expect(find.text('5.50 kW'), findsNothing);
      expect(find.byTooltip('Cloud unavailable'), findsOneWidget);
      pinnedStation = '456';
      push({'456': power(6800)}, station: '456');
      await tester.pumpAndSettle();
      expect(find.text('6.80 kW'), findsOneWidget);
      expect(find.byTooltip('Cloud unavailable'), findsNothing);
      expect(requests, initial);
      // A healthy stream does not reload the card, including beyond the old 33s cycle.
      for (var i = 0; i < 7; i++) {
        socket.controller.add({'type': 'heartbeat'});
        await tester.pump();
        await tester.pump(const Duration(seconds: 5));
      }
      expect(requests, initial);
      pendingReading = Completer<http.Response>();
      socket.controller.add({'type': 'connection', 'connected': false});
      await tester.pump();
      await tester.pump(const Duration(seconds: 5));
      await tester.pump();
      // The fallback leaves existing power readings visible while the request is pending.
      expect(find.text('6.80 kW'), findsOneWidget);
      expect(find.byType(LinearProgressIndicator), findsNothing);
      expect(requests, greaterThan(initial));
      pendingReading.complete(
        http.Response(jsonEncode(cloudResponse('/latest')), 200),
      );
      pendingReading = null;
      await tester.pumpAndSettle();
      expect(find.text('4.20 kW'), findsOneWidget);
      socket.controller.add({
        'type': 'patch',
        'deye': {'configured': false},
      });
      await tester.pumpAndSettle();
      expect(find.text('Your solar energy, at a glance'), findsOneWidget);
      expect(find.text('4.20 kW'), findsNothing);
      await tester.pumpWidget(const SizedBox());
      api.stopLive();
      await tester.pump();
    },
  );

  testWidgets(
    'compact flow shows battery power and direction without grid history',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(390, 1500));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      var reading = <String, dynamic>{
        'battery_soc': 76,
        'battery_w': 2200,
        'charge_w': 2200,
        'discharge_w': 0,
        'solar_w': 4200,
        'load_w': 1800,
        'grid_w': 0,
        'import_w': 0,
        'export_w': 0,
        'freshness': 'recent',
        'observed_at': '2026-11-15T10:00:00Z',
        'grid_availability': {
          'state': 'up',
          'started_at': '2026-11-15T09:00:00Z',
          'uptime_seconds': 1800,
          'downtime_seconds': 60,
          'unknown_seconds': 120,
        },
      };
      Widget view() => MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: DeyeEnergyOverview(reading: reading, compact: true),
          ),
        ),
      );
      await tester.pumpWidget(view());
      await tester.pumpAndSettle();
      expect(find.text('Power: 2.20 kW'), findsOneWidget);
      expect(find.text('Charging · 2.20 kW'), findsOneWidget);
      expect(find.text('Grid available · voltage estimate'), findsNothing);
      expect(find.text('Observed uptime: 0h 30m 0s'), findsNothing);
      expect(find.text('Observed downtime: 0h 1m 0s'), findsNothing);
      reading = {
        ...reading,
        'charge_w': 0,
        'discharge_w': 2200,
        'observed_at': '2026-11-15T10:01:00Z',
      };
      await tester.pumpWidget(view());
      await tester.pumpAndSettle();
      expect(find.text('Discharging · 2.20 kW'), findsOneWidget);
      expect(find.text('Charging · 2.20 kW'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'station selected on page two persists on dashboard and refreshes saved changes',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(1440, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      Map<String, dynamic>? selected;
      final writes = <Map<String, dynamic>>[];
      final readings = <String>[];
      final api = Api(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/dashboard-station')) {
            final body = Map<String, dynamic>.from(jsonDecode(request.body));
            writes.add(body);
            selected = {
              'id': body['station_id'],
              'name': 'South solar',
              'page': body['page'],
            };
            return http.Response(
              jsonEncode({'dashboard_station': selected}),
              200,
            );
          }
          if (request.url.path.endsWith('/stations')) {
            final second = request.url.queryParameters['page'] == '2';
            return http.Response(
              jsonEncode({
                'stations': [
                  {
                    'id': second ? '456' : '123',
                    'name': second ? 'South solar' : 'North solar',
                  },
                ],
                'total': 51,
              }),
              200,
            );
          }
          if (request.url.path.endsWith('/latest')) {
            readings.add(request.url.path);
            return http.Response(
              jsonEncode(cloudResponse(request.url.path)),
              200,
            );
          }
          return http.Response(
            jsonEncode({
              ...cloudResponse('/config') as Map,
              'dashboard_station': selected,
            }),
            200,
          );
        }),
      )..user = {'role': 'owner'};
      Widget view(bool dashboard) => MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: DeyeSolar(
              key: ValueKey(dashboard),
              api: api,
              dashboard: dashboard,
              onOpen: () {},
            ),
          ),
        ),
      );
      await tester.pumpWidget(view(false));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byTooltip('Next stations'));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Next stations'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Show this station on dashboard'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Show this station on dashboard'));
      await tester.pumpAndSettle();
      expect(writes.single, {'station_id': '456', 'page': 2});
      expect(find.text('Shown on dashboard'), findsOneWidget);
      await tester.pumpWidget(view(true));
      await tester.pumpAndSettle();
      expect(find.text('South solar'), findsNothing);
      expect(find.byType(DropdownButtonFormField<String>), findsNothing);
      expect(readings.last, '/api/integrations/deye/stations/456/latest');
      selected = {'id': '123', 'name': 'North solar', 'page': 1};
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();
      expect(find.text('North solar'), findsNothing);
      expect(readings.last, '/api/integrations/deye/stations/123/latest');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'dashboard shows solar, opens full view, and removes revoked manager access',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(1500, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final socket = FakeSocket();
      var cloudCalls = 0;
      final identity = <String, dynamic>{
        'id': 'solar-manager',
        'role': 'manager',
        'username': 'manager',
        'sections': ['dashboard', 'deye'],
        'editable_sections': [],
        'deletable_sections': [],
      };
      final api =
          Api(
              client: MockClient((request) async {
                if (request.url.path.startsWith('/api/integrations/deye')) {
                  cloudCalls++;
                  return http.Response(
                    jsonEncode(cloudResponse(request.url.path)),
                    200,
                  );
                }
                return http.Response(
                  request.url.path == '/api/dashboard' ? '{}' : '[]',
                  200,
                );
              }),
              liveConnector: (_, _) => socket,
            )
            ..token = 'session'
            ..user = identity;
      await tester.pumpWidget(
        MaterialApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        tester.widget<DeyeSolar>(find.byType(DeyeSolar)).dashboard,
        isTrue,
      );
      expect(find.text('4.20 kW'), findsOneWidget);
      expect(find.text('76%'), findsOneWidget);
      expect(find.text('Connection'), findsNothing);
      expect(find.text('Full solar view'), findsNothing);
      final solarMenu = find.widgetWithText(ListTile, 'Deye Solar');
      await tester.ensureVisible(solarMenu);
      await tester.pumpAndSettle();
      await tester.tap(solarMenu);
      await tester.pumpAndSettle();
      expect(
        tester.widget<DeyeSolar>(find.byType(DeyeSolar)).dashboard,
        isFalse,
      );
      expect(find.text('Deye inverter'), findsOneWidget);
      socket.controller.add({
        'type': 'patch',
        'user': {
          ...identity,
          'sections': ['dashboard'],
        },
      });
      await tester.pumpAndSettle();
      expect(find.byType(DeyeSolar), findsNothing);
      final previous = cloudCalls;
      await tester.pump(const Duration(seconds: 31));
      expect(cloudCalls, previous);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'manager without Deye access makes no solar requests on dashboard',
    (tester) async {
      final api =
          Api(
              client: MockClient((request) async {
                expect(
                  request.url.path,
                  isNot(startsWith('/api/integrations/deye')),
                );
                return http.Response(
                  request.url.path == '/api/dashboard' ? '{}' : '[]',
                  200,
                );
              }),
            )
            ..user = {
              'role': 'manager',
              'username': 'manager',
              'sections': ['dashboard'],
            };
      await tester.pumpWidget(
        MaterialApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byType(DeyeSolar), findsNothing);
      await tester.pumpWidget(const SizedBox());
    },
  );

  for (final width in [360.0, 800.0, 1440.0]) {
    testWidgets('dashboard energy cards fit width $width', (tester) async {
      await tester.binding.setSurfaceSize(Size(width, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final api = Api(
        client: MockClient(
          (request) async =>
              http.Response(jsonEncode(cloudResponse(request.url.path)), 200),
        ),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: DeyeSolar(api: api, dashboard: true, onOpen: () {}),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('76%'), findsOneWidget);
      for (final label in [
        'Solar panels',
        'Battery',
        'Grid',
        'Load',
        'Inverter',
      ]) {
        expect(find.text(label), findsOneWidget);
      }
      expect(find.text('Deye Solar'), findsNothing);
      expect(find.text('North solar'), findsNothing);
      expect(find.byType(IconButton), findsNothing);
      expect(find.textContaining('Observed uptime'), findsNothing);
      expect(find.text('Live updates · 30s refresh'), findsNothing);
      expect(find.text('Recent cloud reading'), findsNothing);
      expect(find.text('Connection'), findsNothing);
      expect(find.byType(TextField), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }

  testWidgets(
    'unconnected dashboard offers setup without showing a login form or invented readings',
    (tester) async {
      var opened = false;
      final api = Api(
        client: MockClient(
          (_) async => http.Response('{"configured":false}', 200),
        ),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: DeyeSolar(
                api: api,
                dashboard: true,
                onOpen: () => opened = true,
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byType(TextField), findsNothing);
      expect(find.text('0 W'), findsNothing);
      await tester.tap(find.text('Connect Deye Cloud'));
      expect(opened, isTrue);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
