import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/tower_discovery.dart';

void main() {
  testWidgets('scan and add only new responding hosts to this tower', (
    tester,
  ) async {
    final added = <dynamic>[];
    final api = Api(
      client: MockClient((request) async {
        expect(request.method, 'POST');
        final body = jsonDecode(request.body);
        if (request.url.path == '/api/towers/north/discover') {
          expect(body, {'prefix': 24});
          return http.Response(
            jsonEncode({
              'network': '192.0.2.0/24',
              'scanned': 254,
              'hosts': [
                {'ip_address': '192.0.2.1', 'already_added': true},
                {'ip_address': '192.0.2.2', 'already_added': false},
              ],
            }),
            200,
          );
        }
        expect(request.url.path, '/api/devices');
        added.add(body);
        return http.Response('{"id":"new"}', 201);
      }),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TowerDiscoveryDialog(
            api: api,
            tower: {
              'id': 'north',
              'name': 'North',
              'management_ip': '192.0.2.1',
            },
          ),
        ),
      ),
    );
    await tester.tap(find.text('Discover with ping'));
    await tester.pumpAndSettle();
    expect(
      find.text('192.0.2.0/24: 2 responding / 254 checked'),
      findsOneWidget,
    );
    expect(find.text('Already in inventory'), findsOneWidget);
    await tester.tap(find.text('Add all (1)'));
    await tester.pumpAndSettle();
    expect(added, [
      {
        'name': 'Device 192.0.2.2',
        'ip_address': '192.0.2.2',
        'tower_id': 'north',
      },
    ]);
    expect(find.text('Already in inventory'), findsNWidgets(2));
    expect(find.text('Add all (1)'), findsNothing);
    expect(tester.takeException(), isNull);
  });
  testWidgets('SNMP discovery scans batches and adds matching profiles', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final added = <dynamic>[];
    final offsets = <int>[];
    final api = Api(
      client: MockClient((request) async {
        if (request.url.path == '/api/snmp-profiles') {
          return http.Response('[]', 200);
        }
        final body = jsonDecode(request.body);
        if (request.url.path.endsWith('/discover-snmp')) {
          offsets.add(body['offset']);
          return http.Response(
            jsonEncode({
              'network': '192.0.2.0/24',
              'scanned': body['offset'] == 0 ? 32 : 254,
              'total': 254,
              'next_offset': body['offset'] == 0 ? 32 : null,
              'timed_out': false,
              'hosts': body['offset'] == 0
                  ? [
                      {
                        'ip_address': '192.0.2.1',
                        'name': 'North radio',
                        'vendor': 'mimosa',
                        'vendor_label': 'Mimosa',
                        'snmp_version': '2c',
                        'snmp_profile_id': null,
                        'profile_name': 'public',
                        'already_added': false,
                      },
                    ]
                  : [],
            }),
            200,
          );
        }
        if (request.url.path.endsWith('/discovery-public')) {
          expect(body, {'version': '2c'});
          return http.Response('{"id":"public-profile"}', 200);
        }
        expect(request.url.path, '/api/devices');
        added.add(body);
        return http.Response('{"id":"new"}', 201);
      }),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TowerDiscoveryDialog(
            api: api,
            snmp: true,
            tower: {
              'id': 'north',
              'name': 'North',
              'management_ip': '192.0.2.1',
            },
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Discover with SNMP'));
    await tester.pumpAndSettle();
    expect(offsets, [0, 32]);
    expect(find.textContaining('Mimosa · SNMP v2'), findsOneWidget);
    await tester.tap(find.text('Add all (1)'));
    await tester.pumpAndSettle();
    expect(added.single, {
      'name': 'North radio',
      'ip_address': '192.0.2.1',
      'tower_id': 'north',
      'vendor': 'mimosa',
      'snmp_profile_id': 'public-profile',
    });
    expect(find.text('Already in inventory'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
